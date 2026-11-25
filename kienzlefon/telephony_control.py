"""Authoritative routing reconciliation and restart-safe local request journal."""

from __future__ import annotations

import contextlib
import fcntl
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .config import AppConfig
from .telephony_policy import CLIENT, ROUTES, RoutingPolicy, managed_phones, policy_for

MAX_AGE_MS = 10000
RETENTION = 604800
ACTIVE = {"accepted", "applying", "unknown"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
EXTENSION = re.compile(r"[0-9]{1,12}")
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")
COMMAND_KEYS = {"request_id", "client_id", "extension", "route", "member", "expected_revision", "pbx_epoch", "expires_at"}
MESSAGES = {
    "invalid_request": (400, "Ungültiger Auftrag."), "unknown_client": (400, "Unbekannter Arbeitsplatz."),
    "unknown_extension": (400, "Unbekannte Nebenstelle."), "unknown_route": (400, "Unbekannte Rufgruppe."),
    "unauthenticated": (401, "Anmeldung fehlgeschlagen."), "forbidden_network": (403, "Zugriff aus diesem Netz gesperrt."),
    "client_forbidden": (403, "Arbeitsplatz nicht freigegeben."), "global_disabled": (403, "Fernsteuerung ist deaktiviert."),
    "admin_locked": (403, "Änderung administrativ gesperrt."), "not_eligible": (403, "Nebenstelle nicht für diese Gruppe freigegeben."),
    "not_found": (404, "Schnittstelle nicht gefunden."), "request_not_found": (404, "Auftrag nicht gefunden."),
    "method_not_allowed": (405, "Methode nicht freigegeben."), "payload_too_large": (413, "Anfrage zu groß."),
    "json_required": (415, "JSON erforderlich."), "revision_conflict": (409, "Rufgruppenstand hat sich geändert."),
    "pbx_restarted": (409, "Die Anlage wurde neu gestartet."), "request_id_conflict": (409, "Auftragskennung bereits belegt."),
    "last_member": (409, "Das letzte Rufgruppenmitglied muss erhalten bleiben."),
    "state_unknown": (409, "Teilnahme ist derzeit nicht bekannt."), "request_expired": (409, "Auftrag abgelaufen."),
    "route_unavailable": (409, "Rufgruppe ist derzeit nicht verfügbar."),
    "state_unavailable": (503, "Anlagenstand ist derzeit nicht verfügbar."),
    "apply_failed": (503, "Anwendung konnte nicht bestätigt werden."),
}


def stamp(epoch: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, UTC).isoformat(timespec="milliseconds")


def expires(value: str) -> float:
    if not TIME.fullmatch(value):
        raise ValueError("Ungültige Ablaufzeit")
    return datetime.fromisoformat(value).timestamp()


def parse_command(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != COMMAND_KEYS or type(value["member"]) is not bool:
        raise ControlError("invalid_request")
    for key, pattern in (("request_id", UUID), ("client_id", CLIENT), ("extension", EXTENSION),
                         ("pbx_epoch", UUID), ("expires_at", TIME)):
        if not isinstance(value[key], str) or not pattern.fullmatch(value[key]):
            raise ControlError("invalid_request")
    revision = value["expected_revision"]
    if not isinstance(revision, str) or not re.fullmatch(r"r1:" + UUID.pattern + r":[1-9][0-9]{0,18}", revision):
        raise ControlError("invalid_request")
    if not isinstance(value["route"], str) or value["route"] not in ROUTES:
        raise ControlError("unknown_route")
    try:
        expires(value["expires_at"])
    except (ValueError, OverflowError, OSError) as exc:
        raise ControlError("invalid_request") from exc
    return value.copy()


class ControlError(Exception):
    def __init__(self, code: str, epoch: str | None = None, revision: str | None = None):
        self.code = code
        self.status, message = MESSAGES[code]
        self.payload = {"code": code, "message": message,
                        "retryable": code in {"state_unavailable", "apply_failed", "state_unknown"},
                        "current_revision": revision, "current_pbx_epoch": epoch}
        super().__init__(message)


class SourceError(RuntimeError):
    """AMI disconnected or a native operation had an uncertain outcome."""


class InventoryChanged(SourceError):
    """Queue events overlapped a read of the Asterisk inventory."""


class Rejected(SourceError):
    """Asterisk explicitly rejected a synchronous action."""


@dataclass(frozen=True)
class QueueInventory:
    members: dict[str, dict[str, int]]
    generation: int


class Plant(Protocol):
    @property
    def connected(self) -> bool: ...
    @property
    def routing_generation(self) -> int: ...
    def process_key(self) -> str: ...
    def inventory(self, config: AppConfig) -> QueueInventory: ...
    def ready(self, value: bool) -> None: ...
    def change(self, config: AppConfig, route: str, extension: str, penalty: int | None) -> None: ...


class Journal:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise ValueError("Auftragsverzeichnis muss privat sein")
        self.database = directory / "control.sqlite"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS plant (id INTEGER PRIMARY KEY CHECK (id=1), body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT NOT NULL, principal TEXT NOT NULL, "
                       "command TEXT NOT NULL, body TEXT NOT NULL, updated REAL NOT NULL, terminal INTEGER NOT NULL, "
                       "PRIMARY KEY (principal, id))")
        self.database.chmod(0o600)

    @contextlib.contextmanager
    def connect(self):
        with contextlib.closing(sqlite3.connect(self.database, timeout=2)) as db:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db

    @contextlib.contextmanager
    def locked(self):
        with (self.directory / ".plant.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def load(self) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM plant WHERE id=1").fetchone()
            return json.loads(row[0]) if row else None

    def store(self, state: dict, request: tuple[str, dict] | None = None) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO plant VALUES (1, ?)", (json.dumps(state),))
            if request is not None:
                self._update(db, *request)

    def publish_members(self, state: dict) -> None:
        from .middleware import private_write

        path = self.directory / "members-confirmed.json"
        content = json.dumps({"revision": _revision(state), "members": state["members"]}) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            private_write(path, content)

    def request(self, principal: str, identifier: str) -> tuple[dict, dict] | None:
        with self.connect() as db:
            row = db.execute("SELECT command, body FROM requests WHERE principal=? AND id=?", (principal, identifier)).fetchone()
            return (json.loads(row[0]), json.loads(row[1])) if row else None

    def append(self, principal: str, command: dict, request: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO requests VALUES (?,?,?,?,?,0)", (
                command["request_id"], principal, json.dumps(command), json.dumps(request), time.time(),
            ))

    @staticmethod
    def _update(db, principal: str, request: dict) -> None:
        db.execute("UPDATE requests SET body=?,updated=?,terminal=? WHERE principal=? AND id=?", (
            json.dumps(request), time.time(), int(request["state"] not in ACTIVE), principal, request["request_id"],
        ))

    def update(self, principal: str, request: dict) -> None:
        with self.connect() as db:
            self._update(db, principal, request)

    def pending(self) -> list[tuple[str, dict]]:
        with self.connect() as db:
            return [(principal, json.loads(body)) for principal, body in db.execute(
                "SELECT principal, body FROM requests WHERE terminal=0 ORDER BY rowid")]

    def prune(self) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM requests WHERE terminal=1 AND updated < ?", (time.time() - RETENTION,))


def _record(request: dict, state: str, *, error=None, revision=None, changed=None) -> dict:
    now = stamp()
    record = {**request, "state": state, "updated_at": now, "error": error,
              "applied_at": now if state == "applied" else None, "result_revision": revision, "changed": changed}
    record.setdefault("created_at", now)
    return record


def _revision(state: dict) -> str:
    return f"r1:{state['epoch']}:{state['revision']}"


def _members(policy: RoutingPolicy, desired: dict[str, list[str]]) -> dict[str, dict[str, int]]:
    return {route: {extension: policy.members[extension][route].penalty for extension in active}
            for route, active in desired.items()}


def _target(state: dict, command: dict) -> dict[str, list[str]]:
    desired = {route: list(members) for route, members in state["members"].items()}
    active = set(desired[command["route"]])
    if command["member"]:
        active.add(command["extension"])
    else:
        active.discard(command["extension"])
    desired[command["route"]] = sorted(active)
    return desired


def permission(policy: RoutingPolicy, state: dict, route: str, extension: str, member: bool) -> str | None:
    if not policy.remote_enabled:
        return "global_disabled"
    config = policy.members[extension][route]
    if not config.eligible:
        return "not_eligible"
    if not (config.can_enable if member else config.can_disable):
        return "admin_locked"
    if not member and state["members"][route] == [extension]:
        return "last_member"
    return None


def _change_policy(previous: dict, policy: RoutingPolicy) -> dict[str, list[str]]:
    old = RoutingPolicy.parse(previous["policy"])
    desired = {}
    for route in ROUTES:
        active = set(previous["members"][route]) & policy.members.keys()
        for extension, routes in policy.members.items():
            member = routes[route]
            before = old.members.get(extension, {}).get(route)
            if not member.eligible or (not member.default_member and before and before.default_member):
                active.discard(extension)
            elif member.default_member and (before is None or not before.default_member):
                active.add(extension)
        if not active:
            raise ValueError("Normal und ROT brauchen je ein wirksames Rufgruppenmitglied")
        desired[route] = sorted(active)
    return desired


@dataclass(frozen=True)
class Confirmed:
    state: dict
    wall: float
    age_start: float
    generation: int


class Controller:
    def __init__(self, journal: Journal, plant: Plant,
                 permits_request: Callable[[AppConfig, str, str], bool] | None = None):
        self.journal = journal
        self.plant = plant
        self.permits_request = permits_request
        self.snapshot: Confirmed | None = None
        self.processing = threading.Lock()
        self.submission = threading.Lock()

    def _available(self, now: float | None = None) -> Confirmed | None:
        if now is None:
            now = time.monotonic()
        view = self.snapshot
        if (view and self.plant.connected and self.plant.routing_generation == view.generation
                and now - view.age_start < MAX_AGE_MS / 1000):
            return view
        return None

    def _decision(self, state: dict, policy: RoutingPolicy, command: dict) -> None:
        def fail(code):
            return ControlError(code, state["epoch"], _revision(state))

        if state["epoch"] != command["pbx_epoch"]:
            raise fail("pbx_restarted")
        now = time.time()
        deadline = expires(command["expires_at"])
        if deadline <= now:
            raise fail("request_expired")
        if deadline > now + 35:
            raise fail("invalid_request")
        if _revision(state) != command["expected_revision"]:
            raise fail("revision_conflict")
        if policy.workplace_mode == "selected" and command["client_id"] not in policy.workplace_ids:
            raise fail("client_forbidden")
        if command["extension"] not in policy.members:
            raise fail("unknown_extension")
        reason = permission(policy, state, command["route"], command["extension"], command["member"])
        if reason:
            raise fail(reason)

    def submit(self, principal: str, clients: set[str] | None, command: dict) -> dict:
        identifier = command["request_id"]
        if clients is not None and command["client_id"] not in clients:
            raise ControlError("client_forbidden")
        with self.submission:
            previous = self.journal.request(principal, identifier)
            if previous:
                original, result = previous
                same_time = expires(original["expires_at"]) == expires(command["expires_at"])
                if not same_time or {**original, "expires_at": command["expires_at"]} != command:
                    raise ControlError("request_id_conflict")
                return result
            snapshot = self._available()
            if not snapshot:
                raise ControlError("state_unavailable")
            state = snapshot.state
            self._decision(state, RoutingPolicy.parse(state["policy"]), command)
            accepted = _record(command, "accepted")
            self.journal.append(principal, command, accepted)
            return accepted

    def result(self, principal: str, clients: set[str] | None, identifier: str) -> dict:
        previous = self.journal.request(principal, identifier)
        if previous is None or (clients is not None and previous[0]["client_id"] not in clients):
            raise ControlError("request_not_found")
        return previous[1]

    def _confirm(self, config: AppConfig, state: dict, desired: dict[str, dict[str, int]],
                 current: QueueInventory) -> QueueInventory:
        if current.members != desired:
            for route in ROUTES:
                for extension, penalty in desired[route].items():
                    if current.members[route].get(extension) != penalty:
                        if self.plant.process_key() != state["process"]:
                            raise SourceError("Asterisk wurde neu gestartet")
                        self.plant.change(config, route, extension, penalty)
                for extension in current.members[route].keys() - desired[route].keys():
                    if self.plant.process_key() != state["process"]:
                        raise SourceError("Asterisk wurde neu gestartet")
                    self.plant.change(config, route, extension, None)
            for attempt in range(5):
                try:
                    current = self.plant.inventory(config)
                    break
                except InventoryChanged:
                    if attempt == 4:
                        raise
                    time.sleep(0.2)
        if current.members != desired or self.plant.process_key() != state["process"]:
            raise SourceError("Rufgruppen konnten nicht bestätigt werden")
        return current

    def set_local_member(self, config: AppConfig, revision: str, route: str, extension: str, member: bool) -> None:
        """Set participation from the privileged local admin, keeping the restart defaults."""
        with self.journal.locked():
            state = self.journal.load()
            policy = policy_for(config)
            if (state is None or state["process"] != self.plant.process_key() or _revision(state) != revision
                    or state["policy"] != policy.export() or self.journal.pending()):
                raise SourceError("Rufgruppenstand geändert oder noch nicht bestätigt. Bitte neu laden.")
            if route not in ROUTES or extension not in policy.members or type(member) is not bool:
                raise ValueError("Unbekannte Rufgruppe oder Nebenstelle")
            if not policy.members[extension][route].eligible:
                raise ValueError("Nebenstelle ist für diese Rufgruppe nicht zugelassen")
            target = _target(state, {"route": route, "extension": extension, "member": member})
            if not target[route]:
                raise ValueError("Das letzte Mitglied muss in der Rufgruppe bleiben")
            actual = self.plant.inventory(config)
            if actual.members != _members(policy, state["members"]):
                raise SourceError("Asterisk meldet abweichende Mitgliedschaften. Bitte erneut laden.")
            if target != state["members"]:
                self._confirm(config, state, _members(policy, target), actual)
                changed = {**state, "members": target, "revision": state["revision"] + 1}
                self.journal.store(changed)
                self.journal.publish_members(changed)

    def refresh(self, config: AppConfig, *, current_config: Callable[[], AppConfig] | None = None) -> None:
        with self.processing, self.journal.locked():
            if current_config is not None:
                config = current_config()
            key = self.plant.process_key()
            policy = policy_for(config)
            state = self.journal.load()
            if state is None or state["process"] != key:
                self.snapshot = None
                state = {"process": key, "epoch": str(uuid4()), "revision": 1, "policy": policy.export(),
                         "members": {route: sorted(entries) for route, entries in policy.defaults().items()}}
                self.plant.ready(False)
                self.journal.store(state)
            inventory = self.plant.inventory(config)
            state, uncertain = self._resolve_pending(state, inventory)
            if uncertain:
                self.snapshot = None
                return
            if policy.export() != state["policy"]:
                self.snapshot = None
                desired = _change_policy(state, policy)
                state.update(policy=policy.export(), members=desired, revision=state["revision"] + 1)
                self.journal.store(state)
            desired = _members(policy, state["members"])
            inventory = self.plant.inventory(config)
            if inventory.members != desired:
                self.snapshot = None
                state["revision"] += 1
                self.journal.store(state)
            inventory = self._confirm(config, state, desired, inventory)
            self.plant.ready(True)
            self.snapshot = Confirmed(state, time.time(), time.monotonic(), inventory.generation)
            self._execute_next(config, policy, state)
            if self.snapshot is not None:
                self.journal.publish_members(self.snapshot.state)

    def _resolve_pending(self, state: dict, inventory: QueueInventory) -> tuple[dict, bool]:
        uncertain = False
        for principal, request in self.journal.pending():
            if request["pbx_epoch"] != state["epoch"]:
                self.journal.update(principal, _record(request, "expired", error=ControlError("pbx_restarted", state["epoch"]).payload))
            elif request["state"] == "accepted" and expires(request["expires_at"]) <= time.time():
                self.journal.update(principal, _record(request, "expired", error=ControlError("request_expired", state["epoch"]).payload))
            elif request["state"] in {"applying", "unknown"}:
                target = _target(state, request)
                if inventory.members != _members(RoutingPolicy.parse(state["policy"]), target):
                    self.journal.update(principal, _record(request, "unknown", error=ControlError("apply_failed", state["epoch"]).payload))
                    uncertain = True
                    continue
                changed = target != state["members"]
                if changed:
                    state.update(members=target, revision=state["revision"] + 1)
                self.journal.store(state, (principal, _record(request, "applied", revision=_revision(state), changed=changed)))
        return state, uncertain

    def _execute_next(self, config: AppConfig, policy: RoutingPolicy, state: dict) -> None:
        item = next(((principal, job) for principal, job in self.journal.pending() if job["state"] == "accepted"), None)
        if item is None:
            return
        principal, pending = item
        def update(request):
            self.journal.update(principal, request)

        try:
            if self.permits_request and not self.permits_request(config, principal, pending["client_id"]):
                raise ControlError("client_forbidden", state["epoch"], _revision(state))
            self._decision(state, policy, pending)
        except ControlError as error:
            update(_record(pending, "expired" if error.code == "request_expired" else "rejected", error=error.payload))
            return
        target = _target(state, pending)
        if target == state["members"]:
            update(_record(pending, "applied", revision=_revision(state), changed=False))
            return
        self.snapshot = None
        applying = _record(pending, "applying")
        update(applying)
        try:
            actual = self.plant.inventory(config)
            if actual.members != _members(policy, state["members"]) or self.plant.process_key() != state["process"]:
                update(_record(applying, "rejected", error=ControlError("state_unknown", state["epoch"]).payload))
                return
            self._decision(state, policy, pending)
            inventory = self._confirm(config, state, _members(policy, target), actual)
        except ControlError as error:
            update(_record(applying, "expired" if error.code == "request_expired" else "rejected", error=error.payload))
        except Rejected:
            current = self.plant.inventory(config)
            confirmed_unchanged = current.members == _members(policy, state["members"]) and self.plant.process_key() == state["process"]
            update(_record(applying, "rejected" if confirmed_unchanged else "unknown", error=ControlError("apply_failed", state["epoch"]).payload))
        except SourceError:
            update(_record(applying, "unknown", error=ControlError("apply_failed", state["epoch"]).payload))
        else:
            changed = {**state, "members": target, "revision": state["revision"] + 1}
            self.journal.store(changed, (principal, _record(applying, "applied", revision=_revision(changed), changed=True)))
            self.snapshot = Confirmed(changed, time.time(), time.monotonic(), inventory.generation)

    def view(self, config: AppConfig, epoch: str | None) -> tuple[dict, list[dict]]:
        now = time.monotonic()
        confirmed = self._available(now)
        state = confirmed.state if confirmed and confirmed.state["epoch"] == epoch else None
        policy = RoutingPolicy.parse(state["policy"]) if state else policy_for(config)
        digit = config.ivr_keys["rot"]
        reason = "source_disconnected" if not self.plant.connected else "state_unknown"
        last = self.snapshot
        if self.plant.connected and last and last.state["epoch"] == epoch and now - last.age_start >= MAX_AGE_MS / 1000:
            reason = "stale"
        routing = {"supported": True, "enabled": policy.remote_enabled, "available": state is not None,
                   "pbx_epoch": epoch, "revision": _revision(state) if state else None,
                   "as_of": stamp(confirmed.wall) if state else None,
                   "age_ms": int((now - confirmed.age_start) * 1000) if state else None,
                   "max_age_ms": MAX_AGE_MS, "reason_code": None if state else reason,
                   "groups": [{"id": route, "label": label,
                               "ivr_digit": digit if route == "specialist" and len(digit) == 1 and digit.isdecimal() else None,
                               "available": state is not None} for route, label in ROUTES.items()]}
        extensions = []
        for extension, label in managed_phones(config).items():
            status = {route: extension in state["members"][route] if state else None for route in ROUTES}
            instructions = {}
            for route in ROUTES:
                enable, disable = (permission(policy, state, route, extension, member) if state else "state_unknown"
                                   for member in (True, False))
                instructions[route] = {"can_enable": enable is None, "enable_reason": enable,
                                       "can_disable": disable is None, "disable_reason": disable}
            extensions.append({"id": extension, "label": label, "routing": {**status, "permissions": instructions}})
        return routing, extensions
