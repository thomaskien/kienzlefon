"""Configure the Kienzlefon-only AMI account and private control credentials."""

from __future__ import annotations

import argparse
import grp
import tempfile
import time
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import tomllib
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

from .config import AppConfig, load_config
from .control_api import STATE_DIR, credentials, encode_credentials, permits_queued_request, private_read, read_ami
from .middleware import manager_inventory, private_write
from .phone_callerid import apply_names
from .telephony_ami import AsteriskPlant
from .telephony_control import CLIENT, Controller, InventoryChanged, Journal, SourceError, _change_policy
from .telephony_policy import PBX_ID, RoutingPolicy, managed_phones, policy_for

MANAGED = "manager_kienzlefon_control.conf"
ACCOUNT = "kienzlefon-control"
BEGIN = "; kienzlefon control manager begin"
END = "; kienzlefon control manager end"


def render_policy(text: str, policy: RoutingPolicy, names: dict[str, str] | None = None) -> str:
    # Replace only our own tables, including nested member tables, and verify that
    # re-parsing retains the effective values of all unrelated TOML keys.
    original = tomllib.loads(text)
    body = []
    omit = False
    for line in text.splitlines(keepends=True):
        # The effective parse check below rejects any unusual quoting not matched here.
        match = re.match(r"^\s*\[{1,2}\s*([^\]]+?)\s*\]{1,2}(?:\s*#.*)?\s*$", line)
        if match:
            omit = bool(re.match(r"(?:routing_policy|\"routing_policy\"|'routing_policy')(?:\s*\.|$)", match[1]))
            if names is not None and match[1].strip("\"'") == "nebenstellennamen":
                omit = True
        if not omit:
            body.append(line)
    encoded = ["[routing_policy]", f"remote_enabled = {str(policy.remote_enabled).lower()}"]
    encoded.extend((f"workplace_mode = {json.dumps(policy.workplace_mode)}",
                    f"workplace_ids = {json.dumps(list(policy.workplace_ids))}"))
    for extension, routes in policy.export()["members"].items():
        for route, member in routes.items():
            encoded.extend(("", f'[routing_policy.members."{extension}".{route}]'))
            encoded.extend(f"{key} = {json.dumps(value)}" for key, value in member.items())
    if names is not None:
        encoded.extend(("", "[nebenstellennamen]"))
        encoded.extend(f'{key} = {json.dumps(name, ensure_ascii=False)}' for key, name in sorted(names.items()))
        original["nebenstellennamen"] = names
    updated = "".join(body).rstrip() + "\n\n" + "\n".join(encoded) + "\n"
    original["routing_policy"] = policy.export()
    if tomllib.loads(updated) != original:
        raise ValueError("Rufgruppen konnten nicht getrennt von anderen Einstellungen gespeichert werden")
    return updated


def write_policy(config: AppConfig, policy: RoutingPolicy, directory: Path = STATE_DIR, *,
                 names: dict[str, str] | None = None, expected_hash: str | None = None,
                 asterisk_dir: Path = Path("/etc/asterisk")) -> None:
    journal = Journal(directory)
    with journal.locked():
        state = journal.load()
        if state is not None and RoutingPolicy.parse(state["policy"]) != policy:
            if any(item["state"] in {"applying", "unknown"} for _, item in journal.pending()):
                raise ValueError("Ein Rufgruppenauftrag wird noch abgeglichen")
            _change_policy(state, policy)
        if not all(policy.defaults().values()):
            raise ValueError("Normal und ROT brauchen jeweils mindestens ein Standardmitglied")
        source = config.source
        content = source.read_bytes()
        if expected_hash is not None and hashlib.sha256(content).hexdigest() != expected_hash:
            raise ValueError("Konfigurationsstand hat sich geändert. Bitte neu laden.")
        updated = render_policy(content.decode("utf-8"), policy, names)
        sync = nullcontext() if names is None else apply_names(
            asterisk_dir, managed_phones(replace(config, phone_names=names)))
        with sync:
            private_write(source, updated, source.stat().st_mode & 0o777)


def enable_local(config: AppConfig, pbx_id: str) -> None:
    """Opt in locally. Preserve a previously provisioned control service."""
    from .webadmin import _set_toml_value

    if config.control_api.enabled:
        return
    if not PBX_ID.fullmatch(pbx_id):
        raise ValueError("Anlagenkennung benötigt 1–64 Buchstaben, Ziffern, Bindestriche oder Unterstriche")
    source = config.source
    text = source.read_text(encoding="utf-8")
    for key, value in (("bind", "127.0.0.1"), ("allowed_networks", ["127.0.0.1/32"]),
                       ("pbx_id", pbx_id), ("enabled", True)):
        text = _set_toml_value(text, "control_api", key, value)
    if config.statistics_pbx_id and config.statistics_pbx_id != pbx_id:
        text = _set_toml_value(text, "anrufstatistik", "pbx_id", pbx_id)
    text = _set_toml_value(text, "routing_policy", "remote_enabled", False)
    with tempfile.NamedTemporaryFile(dir=source.parent, mode="w", encoding="utf-8") as draft:
        draft.write(text)
        draft.flush()
        load_config(Path(draft.name))
    private_write(source, text, source.stat().st_mode & 0o777)


def ensure_credentials(config: AppConfig) -> None:
    path = config.control_api.credentials_file
    if not path.exists() and (config.control_api.bind == "127.0.0.1"
                              and not config.routing_policy.remote_enabled):
        token_path = config.source.parent / "control-admin-lokal.token"
        if not token_path.exists():
            private_write(token_path, secrets.token_hex(32) + "\n")
        token = private_read(token_path, 128).decode("ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("Vorhandenes lokales Control-Token ist ungültig")
        private_write(path, json.dumps({"schema_version": 1, "identities": [{
            "id": "admin-lokal", "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
            "allowed_clients": ["anlagenadmin"],
        }]}) + "\n")
    credentials(path)


def provision(config: AppConfig, etc: Path) -> None:
    if not config.control_api.enabled:
        return
    ensure_credentials(config)
    manager = etc / "manager.conf"
    manager_existed = manager.exists()
    managed = etc / MANAGED
    general, users = manager_inventory(manager)
    if ACCOUNT in {name.lower() for name in users} and not managed.is_file():
        raise ValueError("AMI-Konto für Kienzlefon ist bereits anderweitig belegt")
    if general.get("disabledevents", "").strip():
        raise ValueError("Globale AMI-Ereignissperren verhindern den Anlagenabgleich")
    active = general.get("enabled", "no").lower() in {"yes", "true", "1", "on"}
    if not active and users - {ACCOUNT}:
        raise ValueError("Vorhandene AMI-Konfiguration vor der Aktivierung abstimmen")
    binding = ipaddress.ip_address(general.get("bindaddr", "127.0.0.1")) if active else ipaddress.ip_address("127.0.0.1")
    host = ipaddress.ip_address("::1" if binding.version == 6 else "127.0.0.1") if binding.is_unspecified else binding
    port = int(general.get("port", "5038")) if active else 5038
    if host.is_multicast or not 1 <= port <= 65535:
        raise ValueError("AMI-Listener ist für den lokalen Steuerungsdienst nicht erreichbar")
    secret_path = config.source.parent / "control-ami.json"
    secret = read_ami(secret_path).secret if secret_path.exists() else secrets.token_hex(32)
    if not re.fullmatch(r"[0-9a-f]{64}", secret):
        raise ValueError("Ungültiges lokales AMI-Secret")
    original = manager.read_text(encoding="utf-8") if manager.exists() else "[general]\n"
    planned = original
    if not active:
        planned = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), "", planned, flags=re.S).rstrip()
        if not re.search(r"^\s*\[general\]", planned, re.M | re.I):
            planned += "\n[general]"
        planned += f"\n\n{BEGIN}\n[general](+)\nenabled=yes\nport={port}\nbindaddr={host}\n{END}\n"
    include = f'#include "{MANAGED}"'
    if include not in planned.splitlines():
        planned = planned.rstrip() + "\n\n" + include + "\n"
    if not config.routing_policy.members:
        write_policy(config, policy_for(config))
    private_write(secret_path, json.dumps({"host": str(host), "port": port, "user": ACCOUNT, "secret": secret}) + "\n")
    private_write(managed, (
        f"; Verwaltet von Kienzlefon\n[{ACCOUNT}]\nsecret={secret}\n"
        f"deny=0.0.0.0/0\ndeny=::/0\npermit={host}/{host.max_prefixlen}\n"
        "read=system,call,agent,dialplan,reporting\nwrite=call,agent,reporting\n"
    ), 0o640)
    if not manager.exists() or planned != original:
        private_write(manager, planned, (manager.stat().st_mode & 0o777) if manager.exists() else 0o640)
    if os.geteuid() == 0:
        try:
            group = grp.getgrnam("asterisk").gr_gid
        except KeyError:
            group = manager.stat().st_gid if manager_existed else etc.stat().st_gid
        os.chown(managed, 0, group)
        if not manager_existed:
            os.chown(manager, manager.stat().st_uid, group)


def register(config: AppConfig, identifier: str, clients: list[str] | None, token_file: Path) -> None:
    if not CLIENT.fullmatch(identifier) or (clients is not None and
            (not clients or any(not CLIENT.fullmatch(client) for client in clients))):
        raise ValueError("Ungültige Identität oder Arbeitsplatzkennung")
    path = config.control_api.credentials_file
    identities = credentials(path) if path.exists() else {}
    # Rotating without --client keeps the existing ceiling, including a read-only identity.
    allowed = identities[identifier][1] if clients is None and identifier in identities else (
        set(clients) if clients is not None else None)
    if identifier == "t2med-counters":
        previous = identities.get(identifier, ("", set()))[1]
        if allowed is None or not allowed.issubset(previous):
            raise ValueError("Der Statistikzugang kann keine neuen Schaltrechte erhalten")
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    identities[identifier] = digest, allowed
    encoded = encode_credentials(identities)
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("Fon-Control-Identitätsdatei ist voll")
    descriptor = os.open(token_file, os.O_CREAT | os.O_WRONLY | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write((token + "\n").encode("ascii"))
            output.flush()
            os.fsync(output.fileno())
        private_write(path, encoded)
    except OSError:
        token_file.unlink(missing_ok=True)
        raise


def initialize(config: AppConfig) -> None:
    if not config.control_api.enabled:
        return
    plant = AsteriskPlant(read_ami(config.source.parent / "control-ami.json"))
    try:
        plant.connect()
        controller = Controller(Journal(STATE_DIR), plant, permits_queued_request)
        for attempt in range(5):
            try:
                controller.refresh(config)
                break
            except InventoryChanged:
                if attempt == 4:
                    raise
                time.sleep(0.2)
        if controller.snapshot is None:
            raise SourceError("Asterisk hat die Rufgruppen nicht bestätigt")
    finally:
        if plant.connection:
            plant.connection.close()


def preflight(config: AppConfig) -> None:
    if not config.control_api.enabled:
        return
    from .transfer_setup import _cli

    if "UUID(" not in _cli("core show function UUID"):
        raise ValueError("Asterisk benötigt die UUID-Funktion für externe Eingänge")
    plant = AsteriskPlant(read_ami(config.source.parent / "control-ami.json"))
    try:
        plant.connect()
        plant.process_key()
        plant.channels()
        plant.bridges()
        records = plant.connection.action("QueueStatus", Queue=config.ivr.queue_name, complete="queuestatuscomplete")
        if not any(record.get("event") == "QueueParams" and record.get("queue") == config.ivr.queue_name
                   for record in records):
            raise SourceError("Bestehende Praxiswarteschlange fehlt")
    finally:
        if plant.connection:
            plant.connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kienzlefon-Anlagensteuerung lokal einrichten")
    parser.add_argument("--config", type=Path, default=Path("/etc/kienzlefon/kienzlefon.toml"))
    parser.add_argument("--asterisk-dir", type=Path, default=Path("/etc/asterisk"))
    sub = parser.add_subparsers(dest="command", required=True)
    local = sub.add_parser("enable-local")
    local.add_argument("--pbx-id", required=True)
    sub.add_parser("provision")
    sub.add_parser("initialize")
    sub.add_parser("preflight")
    sub.add_parser("sync-names")
    token = sub.add_parser("register")
    token.add_argument("--id", required=True)
    token.add_argument("--client", action="append", help="Zugang auf diese Platz-ID beschränken (wiederholbar)")
    token.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command == "enable-local":
            enable_local(config, args.pbx_id)
        elif args.command == "register":
            register(config, args.id, args.client, args.token_file)
        elif args.command == "initialize":
            initialize(config)
        elif args.command == "preflight":
            preflight(config)
        elif args.command == "sync-names":
            with Journal(STATE_DIR).locked():
                phones = managed_phones(load_config(args.config))
                with apply_names(args.asterisk_dir, phones, force_reload=True):
                    pass
        else:
            provision(config, args.asterisk_dir)
    except (OSError, ValueError, SourceError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Anlagensteuerung: {exc}\n")


if __name__ == "__main__":
    main()
