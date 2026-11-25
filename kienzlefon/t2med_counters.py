"""Local installer handoff for T2med counters. Only a token digest crosses into Fon."""
import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path

from .config import load_config
from .control_api import credentials, encode_credentials, private_read
from .middleware import private_write
from .telephony_policy import PBX_ID
from .webadmin import _set_toml_value


class SetupError(ValueError):
    pass


def read_config(path):
    if not path.exists():
        return {}
    if path.suffix == ".json":
        return json.loads(path.read_bytes())
    return tomllib.loads(path.read_text())


def common_id(fon, middleware):
    ids = {}
    for data, section in ((fon, "control_api"), (fon, "anrufstatistik"),
                          (middleware, "telephony_control"), (middleware, "call_statistics")):
        value = data.get(section, {}).get("pbx_id", "")
        if value:
            if not isinstance(value, str) or not PBX_ID.fullmatch(value):
                raise SetupError(f"Ungültige Anlagenkennung in [{section}].")
            ids[section] = value
    if len(set(ids.values())) > 1:
        raise SetupError("Abweichende Anlagenkennungen: " + ", ".join(f"{k}={v}" for k, v in ids.items()))
    return next(iter(ids.values()), None) or ("pbx-" + uuid.uuid4().hex)


def verify_dialplan(pbx_id):
    # Ask Asterisk for the running contexts, independently of the files on disk.
    def show(context):
        result = subprocess.run(["asterisk", "-rx", "dialplan show " + context],
                                capture_output=True, text=True, timeout=10)
        output = result.stdout + result.stderr
        if result.returncode and not (context == "kfx-phone-overflow-in" and "There is no existence of" in output):
            raise SetupError("Asterisk-Dialplan ist nicht erreichbar.")
        return output

    for context in ("kfx-phone-in", "kfx-phone-overflow-in", "kienzlefon-direct-queue-in", "kienzlefon-direct-red-in"):
        output = show(context)
        if context.endswith("overflow-in") and "There is no existence of" in output:
            continue
        entries = re.findall(r"Gosub\(kienzlefon-statistics-entry,s,1\(([^()]*)\)\)", output)
        if entries != [pbx_id]:
            raise SetupError(f"Wirksamer Dialplan [{context}]: Statistikeingang für {pbx_id} fehlt oder ist widersprüchlich. Fon-Installer mit --kombi --mit-t2med ausführen.")
    for hook, event in (("entry", "KienzlefonCallEntered"), ("route", "KienzlefonCallRoute")):
        output = show("kienzlefon-statistics-" + hook)
        if (not re.search(r"UserEvent\(" + event + r",[^)\n]*PbxId:\s*\$\{KF_STATS_PBX_ID\}(?:,|\))", output)
                or (hook == "entry" and "Set(__KF_STATS_PBX_ID=${ARG1})" not in output)):
            raise SetupError("Wirksames Statistikereignis fehlt oder hat eine falsche Anlagenkennung: " + event)


def stage(work, name, target, old, new):
    if old == new:
        return
    for suffix, contents in (("old", old), ("new", new), ("path", str(target))):
        private_write(work / f"{name}.{suffix}", contents)


def plan(source, work):
    config = load_config(source)
    data = json.loads((work / "fon-info.json").read_text())
    section = config.control_api
    if not section.enabled or section.pbx_id != data["pbx_id"]:
        raise SetupError("Fon-Control ist deaktiviert oder die Anlagenkennung wurde geändert.")
    digest = (work / "control.sha256").read_text().strip()
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise SetupError("Ungültiger Dienstschlüssel-Fingerabdruck.")
    path = section.credentials_file
    old = private_read(path, 65536).decode()
    identities = credentials(path)
    identity = "t2med-counters"
    existing = next((key for key, (value, _) in identities.items() if value == digest), None)
    if existing is None:
        if identity in identities:
            raise SetupError("Vorhandener Fon-Dienstschlüssel für t2med-counters weicht vom Middleware-Schlüssel ab.")
        identities[identity] = digest, set()
    elif identities[existing][1] != set() and not data["already_enabled"]:
        raise SetupError("Der vorhandene Control-Schlüssel besitzt Schaltrechte. Für die Erstaktivierung ist ein eigener Leseschlüssel erforderlich.")

    # An older middleware supplies only the counters digest. Never promote that key.
    routing_file = work / "routing.sha256"
    new_routing = False
    if routing_file.exists():
        routing_digest = private_read(routing_file, 128).decode("ascii").strip()
        if not re.fullmatch("[0-9a-f]{64}", routing_digest):
            raise SetupError("Ungültiger Fingerabdruck für den Rufgruppenzugang.")
        paired = next((key for key, (value, _) in identities.items() if value == routing_digest), None)
        if paired is not None:
            if paired == "admin-lokal" or identities[paired][1] == set():
                raise SetupError("Für Rufgruppen wird ein eigener Praxiszugang oder ein bestehender Schaltzugang benötigt.")
        else:
            writers = {key for key, (_, clients) in identities.items() if key != "admin-lokal" and clients != set()}
            if writers or "t2med-routing" in identities:
                raise SetupError("Bestehenden Rufgruppen-Schaltzugang samt Arbeitsplatzbeschränkung weiterverwenden.")
            identities["t2med-routing"] = routing_digest, None
            new_routing = True
    if existing is None or new_routing:
        updated = encode_credentials(identities)
        if len(updated.encode()) > 65536:
            raise SetupError("Fon-Control-Identitätsdatei ist voll.")
        stage(work, "identities", path, old, updated)
    original = source.read_text()
    raw = tomllib.loads(original)
    if raw.get("anrufstatistik", {}).get("pbx_id") != section.pbx_id:
        updated = _set_toml_value(original, "anrufstatistik", "pbx_id", section.pbx_id)
        raw.setdefault("anrufstatistik", {})["pbx_id"] = section.pbx_id
        if tomllib.loads(updated) != raw:
            raise SetupError("Individuelle Fon-Einstellungen konnten nicht erhalten werden.")
        stage(work, "statistics", source, original, updated)
    verify_dialplan(section.pbx_id)


def publish(work, rollback):
    conflicts = []
    for name in (("statistics", "identities") if rollback else ("identities", "statistics")):
        marker = work / (name + ".applied")
        path = work / (name + ".path")
        if not path.exists() or (rollback and not marker.exists()):
            continue
        target = Path(path.read_text())
        before, after = ((work / (name + "." + ext)).read_text() for ext in
                         (("new", "old") if rollback else ("old", "new")))
        current = None if target.is_symlink() or not target.is_file() else target.read_text()
        if rollback and current == after:
            continue
        if current != before:
            if rollback:
                conflicts.append(str(target))
                continue
            raise SetupError("Fon-Konfiguration wurde zwischenzeitlich geändert: " + str(target))
        if not rollback:
            marker.touch()
        private_write(target, after, stat.S_IMODE(target.stat().st_mode))
    if conflicts:
        raise SetupError("Zwischenzeitlich geänderte Fon-Dateien beim Rollback erhalten: " + ", ".join(conflicts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["pbx-id", "describe", "plan", "apply", "rollback"])
    parser.add_argument("--config", type=Path, default=Path("/etc/kienzlefon/kienzlefon.toml"))
    parser.add_argument("--middleware", type=Path)
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    if args.action in ("plan", "apply", "rollback"):
        if not args.work or stat.S_IMODE(args.work.stat().st_mode) != 0o700 or args.work.stat().st_uid != os.geteuid():
            raise SetupError("Privates Installer-Arbeitsverzeichnis erforderlich.")
        if args.action == "plan":
            plan(args.config, args.work)
        else:
            publish(args.work, args.action == "rollback")
        return
    middleware = args.middleware or Path("/etc/kienzlefon-t2med/config.toml")
    if args.middleware is None and not middleware.exists():
        middleware = middleware.with_suffix(".json")
    mw = read_config(middleware)
    pbx_id = common_id(read_config(args.config), mw)
    if args.action == "pbx-id":
        print(pbx_id)
        return
    control = load_config(args.config).control_api
    if not control.enabled:
        raise SetupError("Fon-Control ist deaktiviert. Fon-Installer mit --kombi --mit-t2med ausführen.")
    host = f"[{control.bind}]" if ":" in control.bind else control.bind
    print(json.dumps({"pbx_id": pbx_id, "base_url": f"http://{host}:{control.port}", "routing_pairing_version": 1,
                      "already_enabled": mw.get("telephony_control", {}).get("enabled", False)}))


if __name__ == "__main__":
    try:
        main()
    except SetupError as exc:
        sys.exit(str(exc))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f"Lokale Fon-Zählerübergabe fehlgeschlagen ({type(exc).__name__}). Fon-Konfiguration, Asterisk und Dateirechte prüfen.")
