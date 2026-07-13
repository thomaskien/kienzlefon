# kienzlefon tests
# Version: 1.8.2
# Changelog:
# - 1.8.2: Notrufnummern als Woerter und Geburtstag in Fallbacks getestet.
# - 1.5: Zweistufige Normalisierung und 16-kHz-Masterqualitaet getestet.
# - 1.4: PIN-freien Katalog und Bereinigung entfernter Audiodateien getestet.
# - 1.3: Stabile Nummerierung und gemeinsame Telefonzeit am Wochenende getestet.
# - 1.2: Zusammengefasste Werktags- und Wochenendansagen getestet.
# - 1.1: Piper-Parameter, Pausenmarker und Praxisnamen-Ersetzung abgesichert.
# - 1.0: Dynamische Wochen- und Freigabetexte abgesichert.

from __future__ import annotations

import json
import math
import shutil
import struct
import wave
from dataclasses import replace
from datetime import time
from pathlib import Path

import pytest

from kienzlefon.config import PromptConfig, TimeWindow, WeeklySchedule
from kienzlefon.prompts import PROMPT_CATALOG, PromptGenerator, rendered_prompts, split_pause_markers


def test_rendered_prompts_contain_released_texts(app_config) -> None:
    prompts = rendered_prompts(app_config)
    assert "Praxisname" in prompts["greeting_closed"]
    assert "eins eins zwei" in prompts["emergency"]
    assert "112" not in prompts["emergency"]
    assert "eins eins sechs, eins eins sieben" in prompts["urgent_help"]
    assert "116117" not in prompts["urgent_help"]
    assert "drücken Sie 6" in prompts["opening_hours_choice"]
    assert prompts["menu_intro"].startswith("Bitte wählen Sie nun durch Tastendruck")
    assert "An Wochenenden ist die Praxis geschlossen" in prompts["opening_hours"]
    assert prompts["completed"] == "Vielen Dank und bis bald!"
    assert "Geburtstag" in prompts["no_selection_closed"]
    assert "Geburtstag" in prompts["personal_data_fallback"]
    assert "Geburtsdatum" not in prompts["no_selection_closed"]
    assert "Geburtsdatum" not in prompts["personal_data_fallback"]


def test_practice_name_is_replaced_in_every_prompt(app_config) -> None:
    values = dict(app_config.prompts.values)
    values["invalid"] = "Bitte melden Sie sich bei {praxisname}."
    config = replace(app_config, prompts=PromptConfig(values))
    assert rendered_prompts(config)["invalid"] == "Bitte melden Sie sich bei Praxisname."


def test_common_weekday_times_and_closed_weekend_are_summarized(app_config) -> None:
    morning = TimeWindow(time(8), time(12))
    monday_afternoon = TimeWindow(time(14), time(17))
    wednesday_afternoon = TimeWindow(time(15), time(18))
    opening = WeeklySchedule(
        (
            (morning, monday_afternoon),
            (morning,),
            (morning, wednesday_afternoon),
            (morning,),
            (morning,),
            (),
            (),
        )
    )
    phone_window = (TimeWindow(time(8), time(10)),)
    phone = WeeklySchedule((phone_window,) * 5 + ((), ()))
    config = replace(app_config, opening_hours=opening, phone_hours=phone)
    prompts = rendered_prompts(config)

    assert "Jeden Werktag vormittags von 8 Uhr bis 12 Uhr." in prompts["opening_hours"]
    assert "Montag nachmittags von 14 Uhr bis 17 Uhr." in prompts["opening_hours"]
    assert "Dienstag nachmittags" not in prompts["opening_hours"]
    assert "An Wochenenden ist die Praxis geschlossen." in prompts["opening_hours"]
    assert "Unsere Telefonzeiten sind werktäglich von 8 Uhr bis 10 Uhr." in prompts["phone_hours"]
    assert "Am Wochenende sind wir telefonisch nicht erreichbar." in prompts["phone_hours"]


def test_prompt_catalog_keeps_released_numbers(app_config) -> None:
    assert PROMPT_CATALOG[0] == "appointment"
    assert PROMPT_CATALOG[35] == "whisper_failure"
    assert PROMPT_CATALOG[36] == "blocked_destination"
    assert PROMPT_CATALOG[37] == "admin_main"
    assert "admin_pin" not in PROMPT_CATALOG
    assert "Override" not in rendered_prompts(app_config)["admin_special_menu"]


def test_removed_prompt_outputs_are_cleaned(app_config, monkeypatch) -> None:
    generator = PromptGenerator(app_config)
    generator.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    current_text = "Aktuelles Menue"
    current_digest = generator._digest("admin_main", current_text)
    generator.manifest_path.write_text(
        json.dumps(
            {
                "prompts": {
                    "admin_main": {"sha256": current_digest},
                    "admin_pin": {"sha256": "alt"},
                }
            }
        ),
        encoding="utf-8",
    )
    obsolete = [app_config.paths.prompt_masters / "admin_pin.wav"] + [
        app_config.paths.prompts / f"admin_pin.{suffix}"
        for suffix in ("sln16", "g722", "alaw", "ulaw")
    ]
    for path in obsolete:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"alt")
    monkeypatch.setattr("kienzlefon.prompts.rendered_prompts", lambda _config: {"admin_main": current_text})
    monkeypatch.setattr(generator, "_outputs_exist", lambda _name: True)

    assert generator.generate() == (0, 1)
    assert not any(path.exists() for path in obsolete)
    manifest = json.loads(generator.manifest_path.read_text(encoding="utf-8"))
    assert "admin_pin" not in manifest["prompts"]


def test_piper_receives_configured_length_scale(app_config, tmp_path: Path) -> None:
    generator = PromptGenerator(app_config)
    commands: list[list[str]] = []

    def capture_first_command(command: list[str], _message: str) -> None:
        commands.append(command)
        raise RuntimeError("Piper-Aufruf erfasst")

    generator._run = capture_first_command  # type: ignore[method-assign]
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(RuntimeError, match="Piper-Aufruf erfasst"):
        generator._generate_one("test", "Testansage", staging)

    index = commands[0].index("--length-scale")
    assert commands[0][index + 1] == "1.3"
    index = commands[0].index("--sentence-silence")
    assert commands[0][index + 1] == "0.8"


def test_normalization_creates_loud_wav16_without_clipping(app_config, tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg fehlt")
    source = tmp_path / "quiet.wav"
    output = tmp_path / "normalized.wav16"
    sample_rate = 16000
    frames = b"".join(
        struct.pack("<h", int(300 * math.sin(2 * math.pi * 440 * index / sample_rate)))
        for index in range(sample_rate * 2)
    )
    with wave.open(str(source), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)

    generator = PromptGenerator(app_config)
    generator.normalize_audio(source, output, "normalisierungstest")
    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
    analysis = generator._run_capture(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-i", str(output),
            "-af", "loudnorm=I=-19:LRA=7:TP=-2:print_format=json", "-f", "null", "-",
        ],
        "Kontrollmessung fehlgeschlagen",
    )
    measured = generator._parse_loudnorm(analysis.stderr, "normalisierungstest")
    assert -19.5 <= float(measured["input_i"]) <= -18.5
    assert float(measured["input_tp"]) <= -1.8


def test_wav16_manual_source_has_precedence(app_config) -> None:
    app_config.tts.upload_directory.mkdir(parents=True, exist_ok=True)
    wav = app_config.tts.upload_directory / "greeting_open.wav"
    wav16 = app_config.tts.upload_directory / "greeting_open.wav16"
    wav.write_bytes(b"alt")
    wav16.write_bytes(b"neu")
    assert PromptGenerator(app_config)._manual_source("greeting_open") == wav16


def test_pause_marker_parser_rejects_malformed_marker() -> None:
    assert split_pause_markers("Guten Tag.{pause:800}Bitte wählen Sie.") == [
        "Guten Tag.",
        800,
        "Bitte wählen Sie.",
    ]
    with pytest.raises(ValueError, match="Ungueltiger Pausenmarker"):
        split_pause_markers("Guten Tag.{pause:abc}Weiter.")


def test_pause_marker_inserts_exact_silence(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "joined.wav"
    for path in (first, second):
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000)
            wav_file.writeframes(b"\x01\x00" * 80)

    PromptGenerator._join_with_pauses(
        ["Erster Satz.", 1000, "Zweiter Satz."],
        {0: first, 2: second},
        output,
        "test",
    )

    with wave.open(str(output), "rb") as result:
        assert result.getnframes() == 80 + 8000 + 80
