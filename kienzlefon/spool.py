# kienzlefon
# Version: 1.8
# Changelog:
# - 1.8: Sicheres Verwerfen vollstaendig leerer, fehlerfreier Aufnahmen ergaenzt.
# - 1.0: Atomarer Ordner-Spool und verlustarme Vorgangsverwaltung eingefuehrt.

from __future__ import annotations

import json
import os
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import payload_fields
from .models import AudioStatus, CallState, CallType, ClaimedCall, FieldName

SUMMARY_UNAVAILABLE = "keine Zusammenfassung vorhanden"
STATE_NAMES = tuple(state.value for state in CallState)


def iso_now(timezone: ZoneInfo) -> str:
    return datetime.now(timezone).isoformat(timespec="seconds")


def write_json_atomic(path: Path, value: Any, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON-Wurzel ist kein Objekt: {path}")
    return value


class WorkingCall:
    def __init__(self, path: Path, timezone: ZoneInfo):
        self.path = path
        self.timezone = timezone

    @property
    def call_id(self) -> str:
        return self.path.name

    @property
    def json_path(self) -> Path:
        return self.path / "call.json"

    @property
    def audio_directory(self) -> Path:
        return self.path / "audio"

    def load(self) -> dict[str, Any]:
        return read_json(self.json_path)

    def save(self, record: dict[str, Any]) -> None:
        record["_kienzlefon"]["aktualisiert_am"] = iso_now(self.timezone)
        write_json_atomic(self.json_path, record)

    def begin_audio(self, field: FieldName, filename: str, index: int | None = None) -> Path:
        record = self.load()
        entry: dict[str, Any] = {
            "feld": field.value,
            "datei": f"audio/{filename}",
            "status": AudioStatus.RECORDED.value,
            "transkript": "",
            "versuche": 0,
            "transkribieren": True,
        }
        if index is not None:
            entry["index"] = index
        record["_kienzlefon"]["audio"].append(entry)
        self.save(record)
        return self.audio_directory / filename

    def set_audio_record_status(self, filename: str, status: str, present: bool) -> None:
        record = self.load()
        entry = self._audio_entry(record, filename)
        entry["aufnahme_status"] = status
        entry["datei_vorhanden"] = present
        if status == "ERROR" or not present:
            entry["status"] = AudioStatus.ERROR.value
            entry["transkribieren"] = False
        self.save(record)

    def has_usable_audio(self) -> bool:
        if not self.audio_directory.is_dir():
            return False
        return any(
            path.is_file() and path.stat().st_size > 44
            for path in self.audio_directory.iterdir()
        )

    def add_error(self, code: str, phase: str, message: str) -> None:
        record = self.load()
        errors = record["_kienzlefon"]["errors"]
        if errors:
            previous = errors[-1]
            if (
                not previous.get("gemeldet", False)
                and previous.get("code") == code
                and previous.get("phase") == phase
                and previous.get("meldung") == message
            ):
                return
        errors.append(
            {
                "zeit": iso_now(self.timezone),
                "code": code,
                "phase": phase,
                "meldung": message,
                "gemeldet": False,
            }
        )
        record["_kienzlefon"]["status"] = CallState.ERROR.value
        self.save(record)

    def mark_error_reported(self, error_time: str) -> None:
        record = self.load()
        for error in record["_kienzlefon"]["errors"]:
            if error["zeit"] == error_time:
                error["gemeldet"] = True
        self.save(record)

    @staticmethod
    def _audio_entry(record: dict[str, Any], filename: str) -> dict[str, Any]:
        relative = f"audio/{filename}"
        for entry in record["_kienzlefon"]["audio"]:
            if entry["datei"] == relative:
                return entry
        raise KeyError(f"Audioeintrag fehlt: {relative}")


class Spool:
    def __init__(self, root: Path, timezone: ZoneInfo):
        self.root = root
        self.timezone = timezone

    def initialize(self) -> None:
        for name in STATE_NAMES:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def state_directory(self, state: CallState) -> Path:
        return self.root / state.value

    def create_call(self, call_type: CallType, caller_id: str | None, category: str) -> WorkingCall:
        self.initialize()
        now = datetime.now(self.timezone)
        for _ in range(100):
            call_id = f"{now:%Y%m%d_%H%M%S}_{secrets.randbelow(1_000_000):06d}"
            path = self.state_directory(CallState.RECORDING) / call_id
            try:
                path.mkdir(mode=0o750)
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("Konnte keine eindeutige Vorgangs-ID erzeugen")
        (path / "audio").mkdir(mode=0o750)

        effective_id = caller_id or "unbekannt"
        effective_phone = caller_id or "unbekannt"
        record: dict[str, Any] = {
            "typ": call_type.value,
            "id": effective_id,
            "telefon": effective_phone,
            "zusammenfassung": SUMMARY_UNAVAILABLE,
        }
        for field in payload_fields(call_type):
            record[field] = ""
        record["_kienzlefon"] = {
            "version": "1.0",
            "vorgang_id": call_id,
            "erstellt_am": now.isoformat(timespec="seconds"),
            "aktualisiert_am": now.isoformat(timespec="seconds"),
            "ivr_kategorie": category,
            "status": CallState.RECORDING.value,
            "abschluss": "",
            "audio": [],
            "errors": [],
        }
        write_json_atomic(path / "call.json", record)
        return WorkingCall(path, self.timezone)

    def transition(self, call: WorkingCall, destination: CallState) -> WorkingCall:
        target = self.state_directory(destination) / call.call_id
        target.parent.mkdir(parents=True, exist_ok=True)
        record = call.load()
        record["_kienzlefon"]["status"] = destination.value
        call.save(record)
        os.replace(call.path, target)
        return WorkingCall(target, self.timezone)

    def finish_recording(self, call: WorkingCall, reason: str) -> WorkingCall:
        record = call.load()
        record["_kienzlefon"]["abschluss"] = reason
        call.save(record)
        return self.transition(call, CallState.QUEUE)

    def discard_empty_recording(self, call: WorkingCall) -> None:
        recording_directory = self.state_directory(CallState.RECORDING)
        if call.path.parent != recording_directory or not call.path.is_dir():
            raise ValueError("Nur ein Vorgang im Aufnahmezustand darf verworfen werden")
        record = call.load()
        if record["_kienzlefon"]["errors"]:
            raise ValueError("Vorgang mit technischem Fehler darf nicht verworfen werden")
        if call.has_usable_audio():
            raise ValueError("Vorgang mit vorhandener Aufnahme darf nicht verworfen werden")
        shutil.rmtree(call.path)
        directory_fd = os.open(recording_directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def claim_next(self) -> ClaimedCall | None:
        queue = self.state_directory(CallState.QUEUE)
        processing = self.state_directory(CallState.PROCESSING)
        processing.mkdir(parents=True, exist_ok=True)
        for source in sorted(path for path in queue.iterdir() if path.is_dir()):
            target = processing / source.name
            try:
                os.replace(source, target)
            except FileNotFoundError:
                continue
            call = WorkingCall(target, self.timezone)
            record = call.load()
            record["_kienzlefon"]["status"] = CallState.PROCESSING.value
            call.save(record)
            return ClaimedCall(source.name, target)
        return None

    def recover_processing(self) -> int:
        return self._move_all(CallState.PROCESSING, CallState.QUEUE, "worker_neustart")

    def recover_stale_recordings(self, stale_seconds: int) -> int:
        now = datetime.now().timestamp()
        count = 0
        recording = self.state_directory(CallState.RECORDING)
        for path in sorted(item for item in recording.iterdir() if item.is_dir()):
            if now - path.stat().st_mtime < stale_seconds:
                continue
            call = WorkingCall(path, self.timezone)
            record = call.load()
            record["_kienzlefon"]["abschluss"] = "verwaiste_aufnahme_wiederhergestellt"
            call.save(record)
            self.transition(call, CallState.QUEUE)
            count += 1
        return count

    def _move_all(self, source_state: CallState, target_state: CallState, reason: str) -> int:
        count = 0
        source_dir = self.state_directory(source_state)
        for path in sorted(item for item in source_dir.iterdir() if item.is_dir()):
            call = WorkingCall(path, self.timezone)
            record = call.load()
            record["_kienzlefon"]["abschluss"] = reason
            call.save(record)
            self.transition(call, target_state)
            count += 1
        return count

    def calls(self, state: CallState) -> Iterable[WorkingCall]:
        directory = self.state_directory(state)
        if not directory.exists():
            return ()
        return tuple(
            WorkingCall(path, self.timezone)
            for path in sorted(item for item in directory.iterdir() if item.is_dir())
        )
