"""Restricted Control API v1 served by Kienzlefon on a private address."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import AppConfig, ConfigError, load_config
from .telephony_ami import AmiSettings, AsteriskPlant
from .telephony_control import CLIENT, MAX_AGE_MS, RETENTION, UUID, ControlError, Controller, Journal, SourceError, parse_command, stamp
from .telephony_live import LiveMonitor

LOGGER = logging.getLogger(__name__)
PREFIX = "/control/v1/"
LIMIT = 8192
HEX_TOKEN = re.compile(r"[0-9a-f]{64}")
STATE_DIR = Path("/var/lib/kienzlefon/control")


def private_read(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Schlüsseldatei benötigt Dienstbesitz und private Dateirechte")
        data = handle.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Ungültige Größe der Schlüsseldatei")
        return data


def no_duplicates(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Doppelte JSON-Schlüssel")
    return result


def credentials(path: Path) -> dict[str, tuple[str, set[str] | None]]:
    data = json.loads(private_read(path, 65536), object_pairs_hook=no_duplicates)
    if not isinstance(data, dict) or set(data) != {"schema_version", "identities"} or type(data["schema_version"]) is not int or data["schema_version"] not in (1, 2):
        raise ValueError("Ungültiges Control-Credentials-Schema")
    if not isinstance(data["identities"], list) or not data["identities"]:
        raise ValueError("Control-Identitäten fehlen")
    identities = {}
    hashes = set()
    for item in data["identities"]:
        if not isinstance(item, dict) or set(item) != {"id", "token_sha256", "allowed_clients"}:
            raise ValueError("Ungültige Control-Identität")
        identifier, digest, clients = item["id"], item["token_sha256"], item["allowed_clients"]
        if (not isinstance(identifier, str) or not CLIENT.fullmatch(identifier) or identifier in identities
                or not isinstance(digest, str) or not HEX_TOKEN.fullmatch(digest) or digest in hashes
                or (clients is None and (data["schema_version"] != 2 or identifier == "t2med-counters"))
                or (clients is not None and (not isinstance(clients, list)
                    or any(not isinstance(client, str) or not CLIENT.fullmatch(client) for client in clients)
                    or len(set(clients)) != len(clients)))):
            raise ValueError("Ungültige oder doppelte Control-Identität")
        identities[identifier] = digest, None if clients is None else set(clients)
        hashes.add(digest)
    return identities


def encode_credentials(identities: dict[str, tuple[str, set[str] | None]]) -> str:
    version = 2 if any(clients is None for _, clients in identities.values()) else 1
    return json.dumps({"schema_version": version, "identities": [
        {"id": key, "token_sha256": digest, "allowed_clients": None if clients is None else sorted(clients)}
        for key, (digest, clients) in identities.items()
    ]}, indent=2) + "\n"


def principal(path: Path, header: str) -> tuple[str, set[str] | None]:
    prefix = "Bearer "
    if not header.startswith(prefix) or not HEX_TOKEN.fullmatch(header[len(prefix):]):
        raise ControlError("unauthenticated")
    digest = hashlib.sha256(header[len(prefix):].encode("ascii")).hexdigest()
    matched = None
    for identifier, (expected, clients) in credentials(path).items():
        if hmac.compare_digest(digest, expected):
            matched = identifier, clients
    if matched is None:
        raise ControlError("unauthenticated")
    return matched


def permits_queued_request(config: AppConfig, identity: str, client: str) -> bool:
    entry = credentials(config.control_api.credentials_file).get(identity)
    return entry is not None and (entry[1] is None or client in entry[1])


class ControlService:
    def __init__(self, config: AppConfig, journal: Journal, plant: AsteriskPlant):
        self.config = config
        self.source = config.source
        self.control_settings = config.control_api
        self.journal = journal
        self.plant = plant
        self.controller = Controller(journal, plant, permits_queued_request)
        self.live = LiveMonitor(plant)
        self.epoch: str | None = None
        self.last_prune = 0.0

    def _current_config(self) -> AppConfig:
        config = load_config(self.source)
        if config.control_api != self.control_settings:
            self.controller.snapshot = None
            self.live.snapshot = None
            raise ValueError("Control-Konfiguration wurde geändert, Dienst neu starten")
        self.config = config
        return config

    def poll(self) -> None:
        self.plant.connect()
        process = self.plant.process_key()
        try:
            self.controller.refresh(self.config, current_config=self._current_config)
        except (SourceError, ValueError, sqlite3.Error):
            self.controller.snapshot = None
        state = self.journal.load()
        self.epoch = state["epoch"] if state and state["process"] == process else None
        if self.epoch is not None:
            try:
                self.live.collect(self.config, self.epoch, process)
            except (SourceError, KeyError):
                self.live.snapshot = None
                self.live.reason = "source_incomplete"
        if time.monotonic() - self.last_prune >= 3600:
            self.journal.prune()
            self.last_prune = time.monotonic()

    def capabilities(self) -> dict:
        return {"schema_version": 1, "pbx_id": self.control_settings.pbx_id,
                "features": {"routing_control": True, "live_counters": True, "statistics_events": True},
                "limits": {"command_ttl_seconds": 30, "max_body_bytes": LIMIT, "max_age_ms": MAX_AGE_MS,
                           "request_retention_seconds": RETENTION}}

    def state(self) -> dict:
        epoch = self.epoch
        config = self.config
        routing, extensions = self.controller.view(config, epoch)
        return {"schema_version": 1, "pbx_id": self.control_settings.pbx_id, "pbx_epoch": epoch,
                "generated_at": stamp(), "routing_control": routing, "extensions": extensions,
                "live_counters": self.live.view(epoch)}

    def run(self, stop: threading.Event) -> None:
        previous_error = False
        while not stop.is_set():
            started = time.monotonic()
            try:
                self.poll()
                previous_error = False
            except (SourceError, OSError, ValueError, ConfigError, sqlite3.Error):
                if not previous_error:
                    LOGGER.warning("Control-Dienst wartet auf eine bestätigte Anlagenverbindung.")
                previous_error = True
                self.controller.snapshot = None
                self.live.snapshot = None
                self.epoch = None
            stop.wait(max(0, 2 - (time.monotonic() - started)))


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, service: ControlService):
        self.service = service
        self.networks = tuple(ipaddress.ip_network(net) for net in service.control_settings.allowed_networks)
        bind = service.control_settings.bind
        self.address_family = socket.AF_INET6 if ipaddress.ip_address(bind).version == 6 else socket.AF_INET
        super().__init__((bind, service.control_settings.port), Handler)

    def get_request(self):
        client, addr = super().get_request()
        client.settimeout(5)
        return client, addr


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _body(self) -> object:
        if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
            raise ControlError("json_required")
        value = self.headers.get("Content-Length", "")
        if not re.fullmatch(r"[0-9]{1,10}", value):
            raise ControlError("invalid_request")
        length = int(value)
        if length > LIMIT:
            raise ControlError("payload_too_large")
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Unvollständiger Auftrag")
            data = json.loads(body, object_pairs_hook=no_duplicates)
            if not isinstance(data, dict) or any(isinstance(value, (dict, list)) for value in data.values()):
                raise ValueError("Routing-Auftrag darf nur skalare Felder enthalten")
            return data
        except (ValueError, RecursionError, OSError) as exc:
            raise ControlError("invalid_request") from exc

    def _handle(self) -> None:
        service = self.server.service
        command_response = False
        try:
            if not any(ipaddress.ip_address(self.client_address[0]) in net for net in self.server.networks):
                raise ControlError("forbidden_network")
            identity, clients = principal(service.control_settings.credentials_file, self.headers.get("Authorization", ""))
            if self.path == PREFIX + "capabilities" and self.command == "GET":
                self._json(200, service.capabilities())
                return
            if self.path == PREFIX + "state" and self.command == "GET":
                state = service.state()
                if self.headers.get("X-Kienzlefon-Display") == "1":
                    state["ai_enabled"] = service.config.ai_integration.admission_enabled
                self._json(200, state)
                return
            policy = service.config.routing_policy
            clients = policy.permitted_clients(clients)
            if self.path == PREFIX + "routing/workplaces":
                if self.command != "GET":
                    raise ControlError("method_not_allowed")
                self._json(200, {"schema_version": 1, "pbx_id": service.control_settings.pbx_id,
                                 "remote_enabled": policy.remote_enabled,
                                 "mode": "all" if clients is None else "selected",
                                 "client_ids": [] if clients is None else sorted(clients)})
                return
            path = PREFIX + "routing/requests"
            if self.path == path and self.command == "POST":
                data = self._body()
                command_response = True
                command = parse_command(data)
                result = service.controller.submit(identity, clients, command)
                status = (202 if result["state"] in {"accepted", "applying", "unknown"} else 200
                          if result["state"] == "applied" else ControlError(result["error"]["code"]).status)
                self._json(status, {"request": result, "error": result["error"]})
                return
            if self.path.startswith(path + "/") and UUID.fullmatch(self.path[len(path) + 1:]):
                if self.command != "GET":
                    raise ControlError("method_not_allowed")
                command_response = True
                result = service.controller.result(identity, clients, self.path[len(path) + 1:])
                self._json(200, {"request": result, "error": result["error"]})
                return
            if self.path in {path, PREFIX + "state", PREFIX + "capabilities"}:
                raise ControlError("method_not_allowed")
            raise ControlError("not_found")
        except ControlError as error:
            self._error(error, command_response)
        except (OSError, ValueError, sqlite3.Error):
            self._error(ControlError("state_unavailable"), command_response)

    def _error(self, error: ControlError, command: bool) -> None:
        body = {"error": error.payload}
        if command:
            body["request"] = None
        try:
            self._json(error.status, body)
        except OSError:
            pass

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _handle


def read_ami(path: Path) -> AmiSettings:
    data = json.loads(private_read(path, 8192))
    return AmiSettings(host=data["host"], port=data["port"], user=data["user"], secret=data["secret"])


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Kienzlefon Steuerungsdienst v1")
    parser.add_argument("--config", type=Path, default=Path("/etc/kienzlefon/kienzlefon.toml"))
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    args = parser.parse_args()
    config = load_config(args.config)
    if not config.control_api.enabled:
        return
    credentials(config.control_api.credentials_file)
    plant = AsteriskPlant(read_ami(config.source.parent / "control-ami.json"))
    service = ControlService(config, Journal(args.state_dir), plant)
    stop = threading.Event()
    with ControlServer(service) as server:
        worker = threading.Thread(target=service.run, args=(stop,), daemon=True, name="kienzlefon-control")
        worker.start()
        try:
            server.serve_forever()
        finally:
            stop.set()
            if plant.connection:
                plant.connection.close()
            worker.join(timeout=5)


if __name__ == "__main__":
    main()
