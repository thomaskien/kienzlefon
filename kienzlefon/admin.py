# kienzlefon
# Version: 1.5
# Changelog:
# - 1.5: Ansagen mit Signalton als wav16 aufgenommen und vor Vorschau normalisiert.
# - 1.4: PIN entfernt und alle Menues nach fuenf Sekunden unbegrenzt wiederholt.
# - 1.3: Internes Ansagen- und Override-IVR mit sicherem Aktivierungsablauf eingefuehrt.

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .agi import AgiChannel
from .config import AppConfig, load_config
from .prompts import PROMPT_CATALOG, PromptGenerator

MENU_TIMEOUT_MS = 5000
MENU_TIMEOUT_SECONDS = 5


class AnnouncementAdmin:
    def __init__(self, config: AppConfig, channel: AgiChannel):
        self.config = config
        self.channel = channel
        self.caller_id = channel.environment.get("agi_callerid", "unbekannt")

    def run(self) -> None:
        self._audit("verwaltung_aufgerufen")
        while True:
            digit = self.channel.get_option(
                self._prompt("admin_main"), "120", MENU_TIMEOUT_MS
            )
            if digit == "1":
                self._prompt_menu()
            elif digit == "2":
                self._special_announcement_menu()
            elif digit == "0":
                return
            elif digit is None:
                continue
            else:
                self._play("admin_invalid")

    def _prompt_menu(self) -> None:
        while True:
            number = self.channel.read_digits(
                "KZF_PROMPT_NUMBER",
                self._prompt("admin_prompt_select"),
                2,
                timeout_seconds=MENU_TIMEOUT_SECONDS,
            )
            if not number:
                continue
            if number.isdigit() and 1 <= int(number) <= len(PROMPT_CATALOG):
                break
            self._play("admin_invalid")
        name = PROMPT_CATALOG[int(number) - 1]
        self._play("admin_current_prompt")
        self.channel.stream_file(self._prompt(name))
        candidate = self._candidate(name)
        while True:
            digit = self.channel.get_option(
                self._prompt("admin_prompt_actions"), "12340", MENU_TIMEOUT_MS
            )
            if digit == "1":
                self._record(name, candidate)
            elif digit == "2":
                if candidate.is_file():
                    self.channel.stream_file(candidate.with_suffix(""))
                else:
                    self._play("admin_no_recording")
            elif digit == "3":
                if candidate.is_file():
                    self._activate_manual(name, candidate)
                else:
                    self._play("admin_no_recording")
            elif digit == "4":
                self._activate_generated(name)
            elif digit == "0":
                return
            elif digit is None:
                continue
            else:
                self._play("admin_invalid")

    def _record(self, name: str, candidate: Path) -> None:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.unlink(missing_ok=True)
        raw = candidate.with_name(
            f".{candidate.stem}.aufnahme.{os.getpid()}.{secrets.token_hex(4)}.wav16"
        )
        self._play("admin_record")
        try:
            result = self.channel.record(
                raw,
                silence_seconds=self.config.announcement_ivr.silence_seconds,
                max_seconds=self.config.announcement_ivr.max_seconds,
                beep=True,
            )
            if result.status == "ERROR" or not result.present:
                raise RuntimeError(f"Ansagenaufnahme fehlgeschlagen: {name}: {result.status}")
            PromptGenerator(load_config(self.config.source)).normalize_audio(
                raw, candidate, f"telefonaufnahme-{name}"
            )
        finally:
            raw.unlink(missing_ok=True)
        self._audit("aufnahme_gespeichert", ansage=name)
        self._play("admin_record_ready")

    def _activate_manual(self, name: str, candidate: Path) -> None:
        active_wav16, active_wav = self._active_paths(name)
        active_wav16.parent.mkdir(parents=True, exist_ok=True)
        previous = self._snapshot((active_wav16, active_wav))
        try:
            for active in (active_wav16, active_wav):
                self._archive(active, name)
            self._atomic_copy(candidate, active_wav16)
            active_wav.unlink(missing_ok=True)
            PromptGenerator(load_config(self.config.source)).generate()
        except Exception:
            self._restore((active_wav16, active_wav), previous)
            raise
        finally:
            self._discard_snapshot(previous)
        self._audit("manuell_aktiviert", ansage=name)
        self._play("admin_activated")

    def _activate_generated(self, name: str) -> None:
        active_paths = self._active_paths(name)
        previous = self._snapshot(active_paths)
        try:
            for active in active_paths:
                self._archive(active, name)
                active.unlink(missing_ok=True)
            PromptGenerator(load_config(self.config.source)).generate()
        except Exception:
            self._restore(active_paths, previous)
            raise
        finally:
            self._discard_snapshot(previous)
        self._audit("piper_aktiviert", ansage=name)
        self._play("admin_generated")

    def _special_announcement_menu(self) -> None:
        while True:
            digit = self.channel.get_option(
                self._prompt("admin_special_menu"), "12340", MENU_TIMEOUT_MS
            )
            if digit == "1":
                self._set_override(True, False)
                self._play("admin_special_keep")
            elif digit == "2":
                self._set_override(True, True)
                self._play("admin_special_block")
            elif digit == "3":
                self._set_override(False, True)
                self._play("admin_special_disabled")
            elif digit == "4":
                current = load_config(self.config.source).override
                status = (
                    "admin_special_status_disabled"
                    if not current.active
                    else (
                        "admin_special_status_block"
                        if current.block_phone_hours
                        else "admin_special_status_keep"
                    )
                )
                self._play(status)
            elif digit == "0":
                return
            elif digit is None:
                continue
            else:
                self._play("admin_invalid")

    def _set_override(self, active: bool, block_phone_hours: bool) -> None:
        if active:
            current = load_config(self.config.source)
            manual = any(path.is_file() for path in self._active_paths("override"))
            if not current.override.announcement and not manual:
                raise RuntimeError(
                    "Feiertags- und Sonderansage kann ohne Text oder Aufnahme nicht aktiviert werden"
                )
        text = self.config.source.read_text(encoding="utf-8")
        text = _replace_toml_bool(text, "override", "aktiv", active)
        text = _replace_toml_bool(
            text, "override", "telefonzeiten_sperren", block_phone_hours
        )
        _atomic_text(self.config.source, text)
        load_config(self.config.source)
        self._audit(
            "override_geaendert", aktiv=active, telefonzeiten_sperren=block_phone_hours
        )

    def _candidate(self, name: str) -> Path:
        return self.config.tts.upload_directory / "kandidaten" / f"{name}.wav16"

    def _active_paths(self, name: str) -> tuple[Path, Path]:
        directory = self.config.tts.upload_directory
        return directory / f"{name}.wav16", directory / f"{name}.wav"

    def _prompt(self, name: str) -> Path:
        return self.config.paths.prompts / name

    def _play(self, name: str) -> None:
        self.channel.stream_file(self._prompt(name))

    def _audit(self, action: str, **details: object) -> None:
        value = {
            "zeit": datetime.now(self.config.practice.timezone).isoformat(timespec="seconds"),
            "caller_id": self.caller_id,
            "aktion": action,
            **details,
        }
        path = self.config.announcement_ivr.audit_log
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o640)
        try:
            os.write(descriptor, (json.dumps(value, ensure_ascii=False) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _archive(self, source: Path, name: str) -> None:
        if not source.is_file():
            return
        stamp = datetime.now(self.config.practice.timezone).strftime("%Y%m%d_%H%M%S_%f")
        target = self.config.tts.upload_directory / "inaktiv" / f"{name}_{stamp}{source.suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    @staticmethod
    def _snapshot(paths: tuple[Path, ...]) -> dict[Path, Path]:
        result: dict[Path, Path] = {}
        for source in paths:
            if not source.is_file():
                continue
            descriptor, name = tempfile.mkstemp(
                prefix="kienzlefon-active-", suffix=source.suffix
            )
            os.close(descriptor)
            target = Path(name)
            shutil.copy2(source, target)
            result[source] = target
        return result

    @staticmethod
    def _restore(paths: tuple[Path, ...], previous: dict[Path, Path]) -> None:
        for active in paths:
            active.unlink(missing_ok=True)
        for active, snapshot in previous.items():
            AnnouncementAdmin._atomic_copy(snapshot, active)

    @staticmethod
    def _discard_snapshot(previous: dict[Path, Path]) -> None:
        for snapshot in previous.values():
            snapshot.unlink(missing_ok=True)

    @staticmethod
    def _atomic_copy(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
        try:
            shutil.copyfile(source, temporary)
            os.chmod(temporary, 0o640)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def _replace_toml_bool(text: str, section: str, key: str, value: bool) -> str:
    pattern = re.compile(
        rf"(^\[{re.escape(section)}\]\n(?:(?!^\[).)*?^{re.escape(key)}\s*=\s*)(true|false)",
        re.M | re.S,
    )
    updated, count = pattern.subn(rf"\g<1>{str(value).lower()}", text, count=1)
    if count != 1:
        raise RuntimeError(f"TOML-Feld fehlt: [{section}].{key}")
    return updated


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
