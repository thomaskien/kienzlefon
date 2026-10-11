"""Interactive installer for the AMI side of the separate middleware."""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
import tomllib
from dataclasses import asdict
from pathlib import Path

from .config import load_config
from .middleware import MiddlewareConfig, listener_plan, manager_inventory, private_write, provision

FIELDS = {
    "enabled": "aktiv", "source_ip": "quell_ip", "server_ip": "server_ip", "port": "port",
    "username": "benutzer", "transport": "transport", "lookup": "namensaufloesung",
    "lookup_available": "lookup_verfuegbar", "click_to_dial": "click_to_dial",
    "extensions": "nebenstellen", "ring_timeout_ms": "klingel_timeout_ms",
}


def save_options(path: Path, options: MiddlewareConfig) -> None:
    values = asdict(options)
    lines = ["[middleware]"]
    for key, value in values.items():
        if isinstance(value, tuple):
            value = list(value)
        lines.append(f"{FIELDS[key]} = {json.dumps(value, ensure_ascii=False)}")
    section = "\n".join(lines) + "\n"
    text = path.read_text(encoding="utf-8")
    pattern = r"^\[middleware\][^\n]*\n(?:(?!^\[).)*"
    if re.search(pattern, text, re.MULTILINE | re.DOTALL):
        text = re.sub(pattern, lambda _: section + "\n", text, count=1, flags=re.MULTILINE | re.DOTALL)
    else:
        text = text.rstrip() + "\n\n" + section
    tomllib.loads(text)
    private_write(path, text, path.stat().st_mode & 0o777)


def ask(prompt: str, default: str) -> str:
    return input(f"{prompt} [{default}]: ").strip() or default


def yes(prompt: str, default: bool) -> bool:
    while True:
        value = ask(prompt, "j" if default else "n").lower()
        if value in {"j", "ja", "y", "yes"}:
            return True
        if value in {"n", "nein", "no"}:
            return False
        print("Bitte j oder n eingeben.")


def application_available(name: str) -> bool:
    try:
        result = subprocess.run(["asterisk", "-rx", "core show application " + name],
                                capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and name + "(" in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def raw_telephones(raw: dict) -> dict[str, str]:
    ast = raw["asterisk"]
    ivr = raw["ivr"]
    first = int(ast.get("erste_queue_nebenstelle", 201))
    result = {str(n): "Telefon (Praxisqueue)" for n in
              range(first, first + int(ast.get("queue_nebenstellen_anzahl", 1)))}
    if ivr.get("rotes_telefon_aktiv", True):
        result[str(ivr["rote_nebenstelle"])] = "Rotes Telefon"
    result.update({str(n): "Zusaetzliches Telefon" for n in
                   raw.get("zusaetzliche_nebenstellen", {}).get("nebenstellen", [])})
    ai = raw.get("ki_integration", {})
    if ai.get("aktiv", False):
        result.update({str(n): "KI-Nebenstelle" for n in
                       range(8810, 8810 + int(ai.get("anzahl_nebenstellen", 0)))})
    return result


def configure(path: Path, etc: Path) -> None:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    old = raw.get("middleware", {})
    values = dict(old)
    established = (path.parent / "middleware-secret").exists()
    enabled = yes("Middleware-Schnittstelle ueber AMI aktivieren?", old.get("aktiv", False))
    values["aktiv"] = enabled
    candidates = raw_telephones(raw)
    values["nebenstellen"] = [x for x in values.get("nebenstellen", []) if x in candidates]
    if enabled:
        general, users = manager_inventory(etc / "manager.conf")
        if users or general.get("enabled", "no") in {"yes", "true", "on", "1"}:
            print("Vorhandener AMI-Listener: " + general.get("bindaddr", "0.0.0.0")
                  + ":" + general.get("port", "5038") + "; bestehende Clients bleiben erhalten.")
        local = yes("Laeuft die Middleware auf diesem Rechner?", ipaddress.ip_address(
            values.get("quell_ip", "127.0.0.1")).is_loopback)
        if local:
            values["quell_ip"] = "127.0.0.1"
            values["server_ip"] = "127.0.0.1"
        else:
            values["quell_ip"] = ask("Exakte Quell-IP des Middleware-Rechners", old.get("quell_ip", ""))
            suggestion = old.get("server_ip", "")
            if suggestion in {"", "127.0.0.1"}:
                suggestion = general.get("bindaddr", "")
                if suggestion in {"0.0.0.0", "::", "127.0.0.1"}:
                    suggestion = ""
                if not suggestion:
                    try:
                        route = subprocess.run(["ip", "-j", "route", "get", values["quell_ip"]],
                                               capture_output=True, text=True, check=True)
                        suggestion = json.loads(route.stdout)[0].get("prefsrc", "")
                    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
                        pass
            values["server_ip"] = ask("Erreichbare IP dieser Telefonanlage", suggestion)
        values["transport"] = ask("Transport (tcp oder vorhandenes tls)", old.get("transport", "tcp"))
        default_port = general.get("port", "5038") if values["transport"] == "tcp" else "5039"
        values["port"] = int(ask("AMI-Port", str(old.get("port", default_port))))
        values["benutzer"] = ask("AMI-Benutzer", old.get("benutzer", "kienzlefon-middleware"))
        values["namensaufloesung"] = yes("Namensaufloesung vor dem Klingeln aktivieren?",
                                         (old.get("namensaufloesung", True) if established else True))
        available = application_available("WaitForCondition") and application_available("UserEvent")
        values["lookup_verfuegbar"] = available
        if values["namensaufloesung"] and not available:
            print("HINWEIS: WaitForCondition/UserEvent fehlt. Namenslookup bleibt ohne Wartezeit deaktiviert.")
        values["click_to_dial"] = yes("Click-to-Dial aktivieren?", (old.get("click_to_dial", True) if established else True))
        if values["click_to_dial"]:
            selected = []
            for extension, label in candidates.items():
                default = extension in old.get("nebenstellen", []) if established else label != "KI-Nebenstelle"
                if yes(f"{extension} – {label}: fuer Click-to-Dial freigeben?", default):
                    selected.append(extension)
            values["nebenstellen"] = selected
            values["klingel_timeout_ms"] = int(ask("Klingeldauer des Mitarbeitertelefons in Millisekunden",
                                                     str(old.get("klingel_timeout_ms", 20000))))
        options = MiddlewareConfig.parse(values)
        # Verify an actual local address, not a remote server entered by mistake.
        interfaces = json.loads(subprocess.check_output(["ip", "-j", "address", "show"], text=True))
        addresses = {str(ipaddress.ip_address(info["local"])) for item in interfaces
                     for info in item.get("addr_info", []) if "local" in info}
        if str(ipaddress.ip_address(options.server_ip)) not in addresses:
            raise ValueError("Die AMI-Zieladresse ist auf diesem Rechner nicht eingerichtet")
        listener_plan(options, etc / "manager.conf")
    else:
        options = MiddlewareConfig.parse(values)
    save_options(path, options)
    if enabled and (path.parent / "middleware-secret").exists():
        rotate = yes("Vorhandenes AMI-Secret erneuern? (Middleware danach aktualisieren)", False)
        # Root-owned marker contains no secret; consumed only by the installation step.
        marker = path.parent / ".middleware-rotate"
        if rotate:
            private_write(marker, "rotate\n")
        else:
            marker.unlink(missing_ok=True)


def update_firewall(config, previous: dict | None) -> None:
    """Manage only rules labelled for this integration on an already active UFW."""
    export = config.source.parent / "middleware-connection.json"
    # Retain ownership of our old rule even while UFW is unavailable/inactive.
    if previous and previous.get("ufw_rule") and export.exists():
        data = json.loads(export.read_text())
        data["ufw_rule"] = previous["ufw_rule"]
        private_write(export, json.dumps(data, indent=2) + "\n")
    if not shutil.which("ufw"):
        return
    result = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=15,
                            env={**__import__("os").environ, "LC_ALL": "C"})
    if result.returncode != 0 or not re.search(r"^Status: active\s*$", result.stdout, re.MULTILINE):
        return
    current = config.middleware
    old_rule = previous.get("ufw_rule") if previous else None
    new_rule = None
    if current.enabled and not ipaddress.ip_address(current.source_ip).is_loopback:
        new_rule = ["allow", "proto", "tcp", "from", current.source_ip, "to", current.server_ip,
                    "port", str(current.port), "comment", "kienzlefon-middleware"]
        subprocess.run(["ufw", *new_rule], check=True, capture_output=True, timeout=30)
    if old_rule and old_rule != new_rule:
        # Only use a structured rule previously generated here; never arbitrary imported arguments.
        if (isinstance(old_rule, list) and len(old_rule) == 11
                and old_rule[0:4] == ["allow", "proto", "tcp", "from"]
                and old_rule[-2:] == ["comment", "kienzlefon-middleware"]):
            subprocess.run(["ufw", "--force", "delete", *old_rule], check=True,
                           capture_output=True, timeout=30)
    export = config.source.parent / "middleware-connection.json"
    if export.exists():
        data = json.loads(export.read_text())
        data["ufw_rule"] = new_rule
        private_write(export, json.dumps(data, indent=2) + "\n")


def session_fds(output: str, username: str, configured_users: set[str]) -> list[int]:
    # Asterisk's CLI truncates names to 15 characters. Do not kick another
    # integration when that prefix is ambiguous.
    prefix = username[:15]
    rows = [line.split() for line in output.splitlines()]
    matches = [row for row in rows if len(row) == 8 and row[0] == prefix]
    if matches and any(name != username and name[:15] == prefix for name in configured_users):
        raise ValueError("AMI-Sitzungsname ist in der CLI mehrdeutig; alte Middleware-Sitzung manuell trennen")
    result = []
    for row in matches:
        if not row[4].lstrip("-").isdigit():
            raise ValueError("AMI-Sitzungsformat unbekannt; alte Middleware-Sitzung manuell trennen")
        if int(row[4]) > 0:
            result.append(int(row[4]))
    return result


def disconnect_previous(previous: dict, etc: Path) -> None:
    old_user = previous.get("ami", {}).get("username", "")
    if not old_user:
        return
    result = subprocess.run(["asterisk", "-rx", "manager show connected"],
                            capture_output=True, text=True, timeout=15, check=True)
    if "FileDes" not in result.stdout:
        raise RuntimeError("Alte AMI-Sitzungen konnten nicht geprueft werden")
    _, configured = manager_inventory(etc / "manager.conf")
    for fd in session_fds(result.stdout, old_user, configured):
        result = subprocess.run(["asterisk", "-rx", f"manager kick session {fd}"],
                                capture_output=True, text=True, timeout=15, check=True)
        if "No such command" in result.stdout:
            raise RuntimeError("Alte Middleware-Sitzung muss manuell getrennt werden")


def verify_listener(options: MiddlewareConfig) -> None:
    result = subprocess.run(["asterisk", "-rx", "manager show settings"],
                            capture_output=True, text=True, timeout=15, check=True)
    if not re.search(r"Manager \(AMI\):\s+Yes", result.stdout, re.IGNORECASE):
        raise RuntimeError("AMI ist nach dem Reload nicht aktiv")
    if options.transport == "tls" and not re.search(r"TLS Enable:\s+Yes", result.stdout, re.IGNORECASE):
        raise RuntimeError("AMI-TLS ist nach dem Reload nicht aktiv")
    # CLI reload success alone does not prove that the configured socket is listening.
    with socket.create_connection((options.server_ip, options.port), timeout=5):
        pass


def install(path: Path, etc: Path, rotate: bool = False) -> None:
    config = load_config(path)
    export = path.parent / "middleware-connection.json"
    previous = json.loads(export.read_text()) if export.exists() else None
    # A prerequisite can have changed since an earlier installer run.
    if config.middleware.enabled:
        from dataclasses import replace
        available = application_available("WaitForCondition") and application_available("UserEvent")
        options = replace(config.middleware, lookup_available=available)
        if options != config.middleware:
            save_options(path, options)
            config = load_config(path)
    marker = path.parent / ".middleware-rotate"
    rotate = rotate or marker.exists()
    export = provision(config, etc, rotate=rotate)
    marker.unlink(missing_ok=True)
    if config.middleware.enabled or previous:
        update_firewall(config, previous)
        result = subprocess.run(["asterisk", "-rx", "manager reload"], capture_output=True,
                                text=True, timeout=15)
        if result.returncode or "No such command" in result.stdout:
            raise RuntimeError("AMI-Konfiguration gespeichert, aber manager reload fehlgeschlagen")
    if previous and (
        rotate or not config.middleware.enabled
        or previous.get("ami", {}).get("username") != config.middleware.username
        or previous.get("allowed_source_ip") != config.middleware.source_ip
    ):
        disconnect_previous(previous, etc)
    if config.middleware.enabled:
        verify_listener(config.middleware)
        print(f"Middleware AMI: {config.middleware.server_ip}:{config.middleware.port} "
              f"({config.middleware.transport}), Benutzer {config.middleware.username}")
        print(f"Geschuetzte Uebergabedatei (root, 0600): {export}")
        print("Bei anderer Firewall TCP-Port gezielt fuer die konfigurierte Middleware-Quell-IP freigeben.")
        if config.middleware.lookup and not config.middleware.lookup_available:
            print("Namenslookup bleibt deaktiviert: benoetigte Asterisk-Anwendung fehlt.")
    else:
        print("Middleware deaktiviert; gespeicherte Einstellungen und Secret bleiben erhalten.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kienzlefon Middleware-Zugang verwalten")
    parser.add_argument("action", choices=["configure", "install", "show-secret", "rotate-secret"])
    parser.add_argument("--config", type=Path, default=Path("/etc/kienzlefon/kienzlefon.toml"))
    parser.add_argument("--asterisk-dir", type=Path, default=Path("/etc/asterisk"))
    args = parser.parse_args()
    try:
        if args.action == "configure":
            configure(args.config, args.asterisk_dir)
        elif args.action in {"install", "rotate-secret"}:
            install(args.config, args.asterisk_dir, rotate=args.action == "rotate-secret")
        else:
            # Deliberately bypass stdout/tee installer logs; requires a controlling terminal.
            with open("/dev/tty", "w", encoding="utf-8") as terminal:
                terminal.write("AMI-Secret: " + (args.config.parent / "middleware-secret").read_text().strip() + "\n")
    except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
        # No configuration dumps and no captured subprocess data (which may include a secret).
        print("Middleware-Einrichtung fehlgeschlagen: " + str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
