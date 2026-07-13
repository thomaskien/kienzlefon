# kienzlefon
# Version: 1.6
# Changelog:
# - 1.6: Heartbeat und Gesundheitspruefung auf mehrere Whisper-Modelle erweitert.
# - 1.0: Atomarer Whisper-Heartbeat und Fail-Closed-Pruefung eingefuehrt.

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .spool import write_json_atomic


class Heartbeat:
    def __init__(self, path: Path, models: tuple[str, ...], interval_seconds: int):
        self.path = path
        self.models = models
        self.interval_seconds = interval_seconds
        self.ready = False
        self.last_error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.write()
        self._thread = threading.Thread(target=self._run, name="whisper-heartbeat", daemon=True)
        self._thread.start()

    def set_ready(self, ready: bool, error: str = "") -> None:
        self.ready = ready
        self.last_error = error
        self.write()

    def write(self) -> None:
        value: dict[str, Any] = {
            "version": "1.6",
            "pid": os.getpid(),
            "models": list(self.models),
            "ready": self.ready,
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "last_error": self.last_error,
        }
        write_json_atomic(self.path, value, mode=0o640)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds + 1)
        self.set_ready(False, self.last_error)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.write()


def worker_is_healthy(path: Path, expected_models: tuple[str, ...], stale_seconds: int) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if value.get("ready") is not True or value.get("models") != list(expected_models):
            return False
        updated = datetime.fromisoformat(str(value["updated_at"]))
        if updated.tzinfo is None:
            return False
        return (datetime.now(UTC) - updated.astimezone(UTC)).total_seconds() <= stale_seconds
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
