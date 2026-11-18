"""Import a completed case from the Kienzlefon-AI 2.9 postprocessor."""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid5

from .config import AppConfig, ConfigError, caller_id_or_none, load_config
from .crypto import EncryptionError, TelepraxisEncryptor
from .delivery import ERROR, MAX_AUDIO_BYTES, Delivery
from .models import CallState
from .spool import MULTIPLE_CONCERNS, PERSON_FIELDS, Spool, WorkingCall, write_json_atomic

SCHEMA = "kienzlefon-multi-anliegen-v2.9"
IDENTITY = ("vorname", "nachname", "geburtsdatum")
RECORDING = "caller.wav"
JSON_LIMIT = 2 * 1024 * 1024
LOGGER = logging.getLogger(__name__)


def _read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Die KI-Falldatei fehlt oder ist kein regulärer Pfad.")
    with path.open("rb") as handle:
        raw = handle.read(JSON_LIMIT + 1)
    if len(raw) > JSON_LIMIT:
        raise ValueError("Die KI-Falldatei überschreitet die Größenbegrenzung.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Ungültige KI-Falldatei.")
    return value


def _call_id(case: dict) -> UUID:
    value = case.get("call_id")
    if not isinstance(value, str):
        raise ValueError("Ungültige KI-Vorgangskennung.")
    identifier = UUID(value)
    if str(identifier) != value:
        raise ValueError("Ungültige KI-Vorgangskennung.")
    return identifier


def _payloads(case: dict, result: dict, config: AppConfig, call_id: UUID) -> list[dict]:
    if (case.get("status") not in {"ready_for_review", "reviewed"}
            or result.get("schema") != SCHEMA or result.get("call_id") != str(call_id)
            or not isinstance(result.get("anliegen"), list)):
        raise ValueError("Der KI-Vorgang ist noch nicht zum Import freigegeben.")

    groups = defaultdict(list)
    for item in result["anliegen"]:
        if (not isinstance(item, dict) or not isinstance(item.get("fields"), dict)
                or not isinstance(item.get("call_type"), str) or not item["call_type"].strip()
                or not isinstance(item.get("zusammenfassung"), str)
                or any(not isinstance(value, str) for value in item["fields"].values())):
            raise ValueError("Ungültiges Teilanliegen im KI-Ergebnis.")
        fields = item["fields"]
        # Distinguish patients within the call even if the caller's number matches.
        name = tuple(fields.get(key, "").strip().casefold() for key in IDENTITY)
        identity = name + ("" if any(name) else fields.get("telefon", "").strip(),)
        groups[identity].append(item)

    try:
        created_at = datetime.fromtimestamp(case["created_epoch"], config.practice.timezone).isoformat(timespec="seconds")
    except (OverflowError, OSError) as exc:
        raise ValueError("Ungültige Erfassungszeit der KI.") from exc
    caller_value = case.get("caller_id")
    if caller_value is not None and not isinstance(caller_value, str):
        raise ValueError("Ungültige Anruferkennung der KI.")
    caller = caller_id_or_none(caller_value) or "unbekannt"
    payloads = []
    for number, identity in enumerate(sorted(groups), 1):
        orders = groups[identity]
        identifier = f"ai-{uuid5(call_id, str(number)).hex}" if len(groups) > 1 else f"ai-{call_id.hex}"
        person = orders[0]["fields"]
        concerns = []
        for index, order in enumerate(orders, 1):
            fields = {name: value for name, value in order["fields"].items()
                      if name not in PERSON_FIELDS | {"anliegen_id", "typ", "zusammenfassung", "_kienzlefon"}}
            concerns.append({**fields, "typ": order["call_type"], "anliegen_id": f"a-{index:03d}",
                             "zusammenfassung": order["zusammenfassung"]})
        phone = next((order["fields"]["telefon"] for order in orders if order["fields"].get("telefon")), caller)
        payload = {"id": caller, "telefon": phone,
                   **{key: person.get(key, "") for key in IDENTITY}}
        if len(concerns) == 1:
            payload.update({key: value for key, value in concerns[0].items() if key != "anliegen_id"})
        else:
            payload.update(typ=MULTIPLE_CONCERNS, anliegen_schema_version=1, anliegen_liste=concerns,
                           zusammenfassung="\n".join(item["zusammenfassung"] for item in concerns if item["zusammenfassung"]))
        payload["_kienzlefon"] = {
            "version": "1.0", "vorgang_id": identifier, "erstellt_am": created_at,
            "aktualisiert_am": created_at, "ivr_kategorie": "ki", "status": CallState.READY.value,
            "abschluss": "abgeschlossen", "audio": [], "errors": [],
        }
        payloads.append(payload)
    return payloads


def _stage(call: WorkingCall, payload: dict, recording: Path | None, *, attach: bool) -> None:
    if call.path.is_dir():
        return
    with tempfile.TemporaryDirectory(prefix=".ki-", dir=call.path.parent) as temp:
        staged = WorkingCall(Path(temp), call.timezone)
        if attach:
            metadata = payload["_kienzlefon"]
            if recording is None or recording.is_symlink() or not recording.is_file() or (
                recording.stat().st_size > MAX_AUDIO_BYTES
            ):
                metadata["audio_beilage"] = ERROR.copy()
            else:
                staged.audio_directory.mkdir(mode=0o750)
                target = staged.audio_directory / RECORDING
                with recording.open("rb") as source, target.open("xb") as out:
                    os.chmod(target, 0o640)
                    shutil.copyfileobj(source, out)
                    out.flush()
                    os.fsync(out.fileno())
                metadata["audio"].append({
                    "feld": "gespraech", "datei": f"audio/{RECORDING}", "status": "transcribed",
                    "datei_vorhanden": True, "transkribieren": False,
                })
        staged.save(payload)
        os.rename(temp, call.path)


def import_case(case_directory: Path, config: AppConfig) -> list[str]:
    case = _read(case_directory / "call.json")
    call_id = _call_id(case)
    spool = Spool(config.paths.spool, config.practice.timezone)
    spool.initialize()
    pending = config.paths.spool / ".ki-import"
    pending.mkdir(mode=0o750, exist_ok=True)
    with (pending / ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        journal = pending / f"{call_id.hex}.json"
        if journal.exists():
            progress = _read(journal)
            identifiers = progress["vorgaenge"]
            if progress["abgeschlossen"]:
                return identifiers
        else:
            payloads = _payloads(case, _read(case_directory / "result.json"), config, call_id)
            identifiers = [payload["_kienzlefon"]["vorgang_id"] for payload in payloads]
            recording = case_directory / RECORDING if len(payloads) == 1 else None
            for identifier, payload in zip(identifiers, payloads, strict=True):
                call = WorkingCall(pending / identifier, config.practice.timezone)
                _stage(call, payload, recording, attach=config.telepraxis.attach_audio is True)
            write_json_atomic(journal, {"vorgaenge": identifiers, "abgeschlossen": not identifiers})
        if not identifiers:
            return []
        encryptor = TelepraxisEncryptor(
            config.telepraxis.public_key, config.telepraxis.output_directory, config.practice.timezone,
            demo_mode=config.telepraxis.demo,
            anonymize_phone_numbers=config.telepraxis.anonymize_phone_numbers,
        )
        delivery = Delivery(encryptor)
        for identifier in identifiers:
            ready = spool.state_directory(CallState.READY) / identifier
            if ready.is_dir():
                continue
            call = WorkingCall(pending / identifier, config.practice.timezone)
            persisted = call.load()
            delivery.publish(call, persisted, attach=bool(persisted["_kienzlefon"]["audio"]))
            os.rename(call.path, ready)
        write_json_atomic(journal, {"vorgaenge": identifiers, "abgeschlossen": True})
    return identifiers


def import_next_case(directory: Path, config: AppConfig) -> bool:
    journal_directory = config.paths.spool / ".ki-import"
    for candidate in sorted(directory.iterdir()):
        try:
            identifier = UUID(candidate.name)
        except ValueError:
            continue
        if str(identifier) != candidate.name or candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            journal = journal_directory / f"{identifier.hex}.json"
            if journal.exists() and _read(journal)["abgeschlossen"]:
                continue
            metadata = _read(candidate / "call.json")
            if metadata.get("status") not in {"ready_for_review", "reviewed"}:
                continue
            if metadata.get("call_id") != candidate.name:
                raise ValueError("Falsche KI-Vorgangskennung")
            import_case(candidate, config)
            return True
        except (EncryptionError, OSError, ValueError, TypeError, KeyError):
            LOGGER.warning("Ein KI-Vorgang konnte noch nicht importiert werden.")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Abgeschlossenen lokalen Kienzlefon-KI-Vorgang importieren")
    parser.add_argument("case_directory", type=Path, help="Verzeichnis des fertigen KI-Vorgangs")
    parser.add_argument("--config", default=os.environ.get("KIENZLEFON_CONFIG", "/etc/kienzlefon/kienzlefon.toml"))
    args = parser.parse_args()
    try:
        identifiers = import_case(args.case_directory, load_config(Path(args.config)))
    except (ConfigError, EncryptionError, OSError, ValueError, TypeError, KeyError):
        parser.exit(1, "KI-Vorgang konnte nicht importiert werden.\n")
    print(json.dumps({"vorgaenge": identifiers}))


if __name__ == "__main__":
    main()
