"""Configure the Kienzlefon-only AMI account and private control credentials."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import tomllib
from pathlib import Path

from .config import AppConfig, load_config
from .control_api import STATE_DIR, credentials, read_ami
from .middleware import manager_inventory, private_write
from .telephony_ami import AsteriskPlant
from .telephony_control import CLIENT, Controller, Journal, SourceError, _change_policy
from .telephony_policy import RoutingPolicy, policy_for

MANAGED = "manager_kienzlefon_control.conf"
ACCOUNT = "kienzlefon-control"
BEGIN = "; kienzlefon control manager begin"
END = "; kienzlefon control manager end"


def render_policy(text: str, policy: RoutingPolicy) -> str:
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
        if not omit:
            body.append(line)
    encoded = ["[routing_policy]", f"remote_enabled = {str(policy.remote_enabled).lower()}"]
    for extension, routes in policy.export()["members"].items():
        for route, member in routes.items():
            encoded.extend(("", f'[routing_policy.members."{extension}".{route}]'))
            encoded.extend(f"{key} = {json.dumps(value)}" for key, value in member.items())
    updated = "".join(body).rstrip() + "\n\n" + "\n".join(encoded) + "\n"
    original["routing_policy"] = policy.export()
    if tomllib.loads(updated) != original:
        raise ValueError("Rufgruppen konnten nicht getrennt von anderen Einstellungen gespeichert werden")
    return updated


def write_policy(config: AppConfig, policy: RoutingPolicy, directory: Path = STATE_DIR) -> None:
    journal = Journal(directory)
    with journal.locked():
        state = journal.load()
        if state is not None:
            if any(item["state"] in {"applying", "unknown"} for _, item in journal.pending()):
                raise ValueError("Ein Rufgruppenauftrag wird noch abgeglichen")
            _change_policy(state, policy)
        if not all(policy.defaults().values()):
            raise ValueError("Normal und ROT brauchen jeweils mindestens ein Standardmitglied")
        source = config.source
        private_write(source, render_policy(source.read_text(encoding="utf-8"), policy), source.stat().st_mode & 0o777)


def provision(config: AppConfig, etc: Path) -> None:
    if not config.control_api.enabled:
        return
    credentials(config.control_api.credentials_file)
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
        import grp

        group = grp.getgrnam("asterisk").gr_gid
        os.chown(managed, 0, group)
        if not manager_existed:
            os.chown(manager, manager.stat().st_uid, group)


def register(config: AppConfig, identifier: str, clients: list[str], token_file: Path) -> None:
    if not CLIENT.fullmatch(identifier) or not clients or any(not CLIENT.fullmatch(client) for client in clients):
        raise ValueError("Ungültige Identität oder Arbeitsplatzkennung")
    path = config.control_api.credentials_file
    identities = credentials(path) if path.exists() else {}
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    descriptor = os.open(token_file, os.O_CREAT | os.O_WRONLY | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write((token + "\n").encode("ascii"))
        output.flush()
        os.fsync(output.fileno())
    identities[identifier] = digest, set(clients)
    private_write(path, json.dumps({"schema_version": 1, "identities": [
        {"id": key, "token_sha256": value[0], "allowed_clients": sorted(value[1])}
        for key, value in identities.items()
    ]}, indent=2) + "\n")


def initialize(config: AppConfig) -> None:
    if not config.control_api.enabled:
        return
    plant = AsteriskPlant(read_ami(config.source.parent / "control-ami.json"))
    try:
        plant.connect()
        controller = Controller(Journal(STATE_DIR), plant)
        controller.refresh(config)
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
    sub.add_parser("provision")
    sub.add_parser("initialize")
    sub.add_parser("preflight")
    token = sub.add_parser("register")
    token.add_argument("--id", required=True)
    token.add_argument("--client", action="append", required=True)
    token.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command == "register":
            register(config, args.id, args.client, args.token_file)
        elif args.command == "initialize":
            initialize(config)
        elif args.command == "preflight":
            preflight(config)
        else:
            provision(config, args.asterisk_dir)
    except (OSError, ValueError, SourceError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Anlagensteuerung: {exc}\n")


if __name__ == "__main__":
    main()
