# kienzlefon tests
# Version: 1.5
# Changelog:
# - 1.5: wav16-Kandidat, Signalton und Normalisierung vor Vorschau getestet.
# - 1.4: PIN-freie interne Menues und unbegrenzte Fuenf-Sekunden-Wiederholung getestet.

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from kienzlefon.admin import AnnouncementAdmin
from kienzlefon.models import RecordingResult
from kienzlefon.prompts import PromptGenerator


class AdminChannel:
    environment = {"agi_callerid": "201"}

    def __init__(self, *, options: list[str | None], digits: list[str] | None = None):
        self.options = options
        self.digits = digits or []
        self.option_calls: list[tuple[str, int]] = []
        self.read_calls: list[tuple[str, int]] = []
        self.played: list[str] = []
        self.record_calls: list[tuple[Path, bool]] = []

    def get_option(self, prompt: Path, _digits: str, timeout_ms: int) -> str | None:
        self.option_calls.append((prompt.name, timeout_ms))
        return self.options.pop(0)

    def read_digits(
        self,
        _variable: str,
        prompt: Path,
        _maximum_digits: int,
        attempts: int = 1,
        timeout_seconds: int = 10,
    ) -> str:
        assert attempts == 1
        self.read_calls.append((prompt.name, timeout_seconds))
        return self.digits.pop(0)

    def stream_file(self, prompt: Path, _digits: str = "") -> None:
        self.played.append(prompt.name)

    def record(
        self,
        path: Path,
        *,
        silence_seconds: int,
        max_seconds: int,
        beep: bool = False,
    ) -> RecordingResult:
        assert silence_seconds == 3
        assert max_seconds == 180
        self.record_calls.append((path, beep))
        path.write_bytes(b"RIFF" + b"0" * 100)
        return RecordingResult(path, "DTMF", True)


def _admin(app_config, channel: AdminChannel) -> AnnouncementAdmin:
    admin = AnnouncementAdmin(app_config, channel)  # type: ignore[arg-type]
    admin._audit = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    return admin


def test_main_menu_repeats_after_five_seconds_without_pin(app_config) -> None:
    channel = AdminChannel(options=[None, None, "0"])
    _admin(app_config, channel).run()
    assert channel.option_calls == [("admin_main", 5000)] * 3
    assert not any("pin" in name for name, _timeout in channel.option_calls)


def test_prompt_selection_and_actions_repeat_without_disconnecting(app_config) -> None:
    channel = AdminChannel(options=[None, "2", "0"], digits=["", "1"])
    _admin(app_config, channel)._prompt_menu()
    assert channel.read_calls == [("admin_prompt_select", 5)] * 2
    assert channel.option_calls == [("admin_prompt_actions", 5000)] * 3
    assert channel.played[:2] == ["admin_current_prompt", "appointment"]
    assert "admin_no_recording" in channel.played


def test_special_announcement_menu_repeats_without_input(app_config) -> None:
    channel = AdminChannel(options=[None, "0"])
    _admin(app_config, channel)._special_announcement_menu()
    assert channel.option_calls == [("admin_special_menu", 5000)] * 2


def test_announcement_recording_beeps_and_normalizes_wav16(
    app_config, monkeypatch
) -> None:
    channel = AdminChannel(options=[])
    admin = _admin(app_config, channel)
    candidate = app_config.tts.upload_directory / "kandidaten" / "greeting_open.wav16"

    def normalize(_self, source: Path, output: Path, _name: str) -> None:
        shutil.copyfile(source, output)

    monkeypatch.setattr(PromptGenerator, "normalize_audio", normalize)
    admin._record("greeting_open", candidate)

    assert channel.record_calls[0][0].suffix == ".wav16"
    assert channel.record_calls[0][1] is True
    assert candidate.is_file()
    assert channel.played == ["admin_record", "admin_record_ready"]


def test_manual_activation_archives_legacy_wav(app_config, monkeypatch) -> None:
    channel = AdminChannel(options=[])
    admin = _admin(app_config, channel)
    upload = app_config.tts.upload_directory
    upload.mkdir(parents=True, exist_ok=True)
    legacy = upload / "greeting_open.wav"
    candidate = upload / "kandidaten" / "greeting_open.wav16"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"legacy")
    candidate.write_bytes(b"wideband")
    monkeypatch.setattr(PromptGenerator, "generate", lambda _self: (1, 53))

    admin._activate_manual("greeting_open", candidate)

    assert (upload / "greeting_open.wav16").read_bytes() == b"wideband"
    assert not legacy.exists()
    archived = list((upload / "inaktiv").glob("greeting_open_*.wav"))
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"legacy"


def test_failed_activation_restores_wav_and_wav16(app_config, monkeypatch) -> None:
    channel = AdminChannel(options=[])
    admin = _admin(app_config, channel)
    upload = app_config.tts.upload_directory
    upload.mkdir(parents=True, exist_ok=True)
    active_wav = upload / "greeting_open.wav"
    active_wav16 = upload / "greeting_open.wav16"
    candidate = upload / "kandidaten" / "greeting_open.wav16"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    active_wav.write_bytes(b"legacy")
    active_wav16.write_bytes(b"wide-old")
    candidate.write_bytes(b"wide-new")

    def fail(_self):
        raise RuntimeError("Konvertierung fehlgeschlagen")

    monkeypatch.setattr(PromptGenerator, "generate", fail)
    with pytest.raises(RuntimeError, match="Konvertierung fehlgeschlagen"):
        admin._activate_manual("greeting_open", candidate)

    assert active_wav.read_bytes() == b"legacy"
    assert active_wav16.read_bytes() == b"wide-old"
