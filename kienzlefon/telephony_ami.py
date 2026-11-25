"""Local AMI transport, queue operations and complete Asterisk snapshots."""

from __future__ import annotations

import re
import socket
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .config import AppConfig
from .queue_dispatch import MEMBER_CONTEXT, member_interface
from .telephony_control import UUID, InventoryChanged, QueueInventory, Rejected, SourceError
from .telephony_policy import ROUTES

ROUTING_EVENTS = {"queuememberadded", "queuememberremoved", "queuememberpaused", "queuememberpenalty"}
LIVE_EVENTS = {"newchannel", "hangup", "rename", "bridgeenter", "bridgeleave", "bridgecreate", "bridgedestroy",
               "blindtransfer", "attendedtransfer", "localoptimizationbegin", "localoptimizationend",
               "queuecallerjoin", "queuecallerleave", "queuecallerabandon", "agentconnect"}
MARKERS = {"KF_LIVE_OWNER", "KF_LIVE_STAGE", "KF_STATS_CALL_ID", "KF_LIVE_OUTBOUND"}
MEMBER = re.compile(r"Local/([0-9]{2,8})@" + MEMBER_CONTEXT, re.I)
PJSIP = re.compile(r"PJSIP/(.+)-[0-9a-fA-F]+")
READY = "KF_CONTROL_READY"


@dataclass(frozen=True)
class AmiSettings:
    host: str
    port: int
    user: str
    secret: str


class AmiConnection:
    def __init__(self, settings: AmiSettings):
        self.routing = 0
        self.topology = 0
        self.notifications: deque[tuple[int, str, str]] = deque(maxlen=1024)
        self.condition = threading.Condition()
        self.responses: dict[str, list[dict[str, str]]] = {}
        self.closed = False
        self.socket = socket.create_connection((settings.host, settings.port), timeout=2)
        self.socket.settimeout(None)
        self.reader = threading.Thread(target=self._read, daemon=True, name="kienzlefon-ami")
        self.reader.start()
        try:
            self.action("Login", Username=settings.user, Secret=settings.secret, Events="on")
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()

    def _read(self) -> None:
        try:
            with self.socket.makefile("rb") as stream:
                message: dict[str, str] = {}
                size = 0
                while True:
                    line = stream.readline(16385)
                    if not line:
                        return
                    size += len(line)
                    if len(line) > 16384 or size > 65536:
                        return
                    if line in {b"\r\n", b"\n"}:
                        self._deliver(message)
                        message, size = {}, 0
                    elif b":" in line:
                        key, _, value = line.decode("utf-8", errors="replace").partition(":")
                        message[key.lower()] = value.strip()
        except OSError:
            pass
        finally:
            self.close()

    def _deliver(self, message: dict[str, str]) -> None:
        event = message.get("event", "").lower()
        if event == "shutdown":
            self.close()
            return
        with self.condition:
            if event in ROUTING_EVENTS:
                self.routing += 1
            if event in LIVE_EVENTS or (event == "varset" and message.get("variable", "").lstrip("_") in MARKERS):
                self.topology += 1
                self.notifications.append((self.topology, event, message.get("uniqueid", "")))
            waiting = self.responses.get(message.get("actionid", ""))
            if waiting is not None:
                waiting.append(message)
                if len(waiting) > 4096:
                    self.close()
                self.condition.notify_all()

    def action(self, name: str, *, complete: str = "", **fields: str) -> list[dict[str, str]]:
        identifier = uuid4().hex
        headers = {"Action": name, "ActionID": identifier, **fields}
        if any("\n" in value or "\r" in value for value in headers.values()):
            raise SourceError("Ungültige lokale AMI-Parameter")
        packet = ("\r\n".join(f"{key}: {value}" for key, value in headers.items()) + "\r\n\r\n").encode()
        with self.condition:
            if self.closed:
                raise SourceError("AMI nicht verbunden")
            reply: list[dict[str, str]] = []
            self.responses[identifier] = reply
        try:
            self.socket.sendall(packet)
            deadline = time.monotonic() + 2
            with self.condition:
                while not self.closed:
                    errors = any(item.get("response", "").lower() == "error" for item in reply)
                    if errors:
                        raise Rejected("Asterisk hat den AMI-Auftrag abgelehnt")
                    success = any(item.get("response", "").lower() == "success" for item in reply)
                    if success and (not complete or any(item.get("event", "").lower() == complete for item in reply)):
                        return reply.copy()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self.condition.wait(remaining)
        except OSError:
            pass
        finally:
            with self.condition:
                self.responses.pop(identifier, None)
        self.close()
        raise SourceError("AMI-Auftrag ohne bestätigte Antwort")

    def events_since(self, version: int) -> tuple[int, list[tuple[str, str]]]:
        with self.condition:
            if self.closed or (self.notifications and version < self.notifications[0][0] - 1):
                raise SourceError("AMI-Ereignisse konnten nicht vollständig abgeglichen werden")
            return self.topology, [(event, uid) for number, event, uid in self.notifications if number > version]


def process_key() -> str:
    result = subprocess.run(["/usr/bin/systemctl", "show", "--property=MainPID", "--value", "asterisk.service"],
                            capture_output=True, text=True, check=True, timeout=2)
    pid = result.stdout.strip()
    if not re.fullmatch(r"[1-9][0-9]*", pid):
        raise SourceError("Asterisk-Prozess nicht verfügbar")
    proc = Path("/proc") / pid
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    data = (proc / "stat").read_text()
    name, separator, tail = data.partition(") ")
    if not separator or name != f"{pid} (asterisk" or not UUID.fullmatch(boot) or len(tail.split()) <= 19:
        raise SourceError("Asterisk-Prozesskennung nicht belastbar")
    return f"{boot}:{pid}:{tail.split()[19]}"


def queue_names(config: AppConfig) -> dict[str, str]:
    return {"normal": config.ivr.queue_name, "specialist": config.special_queue.name}


class AsteriskPlant:
    def __init__(self, settings: AmiSettings):
        self.settings = settings
        self.connection: AmiConnection | None = None
        self.sessions = 0
        self.ready_value: bool | None = None

    @property
    def connected(self) -> bool:
        return self.connection is not None and not self.connection.closed

    @property
    def routing_generation(self) -> int:
        return self.sessions * (1 << 32) + (self.connection.routing if self.connection else 0)

    @property
    def topology_generation(self) -> int:
        return self.sessions * (1 << 32) + (self.connection.topology if self.connection else 0)

    def events_since(self, generation: int) -> tuple[int, list[tuple[str, str]]]:
        if self.connection is None or generation >> 32 != self.sessions:
            raise SourceError("AMI-Verbindung wurde zwischenzeitlich neu aufgebaut")
        count, events = self.connection.events_since(generation % (1 << 32))
        return self.sessions * (1 << 32) + count, events

    def connect(self) -> None:
        if not self.connected:
            self.connection = AmiConnection(self.settings)
            self.sessions += 1
            self.ready_value = None

    def process_key(self) -> str:
        try:
            return process_key()
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise SourceError("Asterisk-Prozesskennung nicht verfügbar") from exc

    def _action(self, name: str, **fields) -> list[dict[str, str]]:
        if self.connection is None:
            raise SourceError("AMI nicht verbunden")
        return self.connection.action(name, **fields)

    def queue_data(self, config: AppConfig) -> dict[str, list[dict[str, str]]]:
        queues = {}
        for route, name in queue_names(config).items():
            records = self._action("QueueStatus", Queue=name, complete="queuestatuscomplete")
            if sum(row.get("event") == "QueueParams" and row.get("queue") == name for row in records) != 1:
                raise SourceError("Eine benötigte Queue ist nicht verfügbar")
            queues[route] = records
        return queues

    def inventory(self, config: AppConfig) -> QueueInventory:
        generation = self.routing_generation
        inventories = {route: {} for route in ROUTES}
        for route, records in self.queue_data(config).items():
            for row in records:
                if row.get("event") != "QueueMember":
                    continue
                match = MEMBER.fullmatch(row.get("location", ""))
                if match is None or row.get("membership") != "dynamic" or row.get("stateinterface") != f"PJSIP/{match[1]}":
                    raise SourceError("Unbekanntes oder statisches Mitglied in verwalteter Queue")
                extension = match[1]
                penalty = row.get("penalty", "")
                if extension in inventories[route] or not penalty.isdecimal():
                    raise SourceError("Unvollständiger Queue-Mitgliedsstatus")
                if row.get("paused") == "1":
                    inventories[route][extension] = -1
                elif row.get("paused") == "0":
                    inventories[route][extension] = int(penalty)
                else:
                    raise SourceError("Unbekannter Pause-Status")
        if generation != self.routing_generation:
            raise InventoryChanged("Queue-Mitgliedschaften haben sich während des Lesens geändert")
        return QueueInventory(inventories, generation)

    def ready(self, value: bool) -> None:
        if self.ready_value != value:
            self._action("Setvar", Variable=READY, Value="1" if value else "0")
            self.ready_value = value

    def change(self, config: AppConfig, route: str, extension: str, penalty: int | None) -> None:
        queue = queue_names(config)[route]
        fields = {"Queue": queue, "Interface": member_interface(extension)}
        if penalty is None:
            self._action("QueueRemove", **fields)
            return
        try:
            self._action("QueueAdd", **fields, Penalty=str(penalty), Paused="0",
                         MemberName=f"Telefon {extension}", StateInterface=f"PJSIP/{extension}")
        except Rejected:
            # Existing dynamic members can keep their offer state across an administrative penalty change.
            self._action("QueuePenalty", **fields, Penalty=str(penalty))
            self._action("QueuePause", **fields, Paused="0")

    def variable(self, channel: str, variable: str) -> str:
        for item in self._action("Getvar", Channel=channel, Variable=variable):
            if item.get("response") == "Success" and "value" in item:
                return item["value"]
        raise SourceError("Unvollständige Antwort für eine Kanalvariable")

    def channels(self) -> dict[str, dict[str, str]]:
        records = self._action("CoreShowChannels", complete="coreshowchannelscomplete")
        channels = {}
        for row in records:
            if row.get("event") == "CoreShowChannel":
                if not row.get("uniqueid") or not row.get("channel") or row["uniqueid"] in channels:
                    raise SourceError("Unvollständige Kanalübersicht")
                channels[row["uniqueid"]] = row
        return channels

    def bridge_members(self, bridge: str) -> set[str]:
        records = self._action("BridgeInfo", complete="bridgeinfocomplete", BridgeUniqueid=bridge)
        members = [row.get("uniqueid") for row in records if row.get("event") == "BridgeInfoChannel"]
        if None in members or len(members) != len(set(members)):
            raise SourceError("Mehrdeutige Brückenübersicht")
        return set(members)

    def bridges(self) -> set[str]:
        records = self._action("BridgeList", complete="bridgelistcomplete")
        bridges = [row.get("bridgeuniqueid") for row in records if row.get("event") == "BridgeListItem"]
        if any(not bridge for bridge in bridges) or len(bridges) != len(set(bridges)):
            raise SourceError("Unvollständige Brückenliste")
        return set(bridges)
