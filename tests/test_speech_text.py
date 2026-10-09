"""German spoken text and the 2.4.2 audio migration."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import time
from pathlib import Path

import pytest

from kienzlefon.config import OverrideConfig, TimeWindow, WeeklySchedule
from kienzlefon.kokoro import MODEL_FILES
from kienzlefon.prompts import PromptGenerator, rendered_prompts
from kienzlefon.speech_text import normalize_german_speech


@pytest.mark.parametrize(("source", "expected"), [
    ("Für unsere Öffnungszeiten drücken Sie 6.",
     "Für unsere Öffnungszeiten drücken Sie sechs."),
    ("Drücken Sie 0, dann 1 oder 9.", "Drücken Sie null, dann eins oder neun."),
    ("11 12 16 17 21 30 60 70", "elf zwölf sechzehn siebzehn einundzwanzig dreißig sechzig siebzig"),
    ("101 123 1.000 2026", "einhunderteins einhundertdreiundzwanzig eintausend zweitausendsechsundzwanzig"),
    ("1.000.001", "eine Million eins"),
    ("1,05", "eins Komma null fünf"),
    ("02331", "null zwei drei drei eins"),
    ("8:30 Uhr", "acht Uhr dreißig"),
    ("08:05", "acht Uhr fünf"),
    ("08.30 Uhr", "acht Uhr dreißig"),
    ("8 Uhr 05", "acht Uhr fünf"),
    ("08:00 Uhr", "acht Uhr"),
    ("8 Uhr 00", "acht Uhr"),
    ("14 Uhr", "vierzehn Uhr"),
    ("01:01 Uhr", "ein Uhr eins"),
    ("1 Uhr", "ein Uhr"),
    ("21 Uhr", "einundzwanzig Uhr"),
    ("00:00 Uhr", "null Uhr"),
    ("23:59 Uhr", "dreiundzwanzig Uhr neunundfünfzig"),
    ("24:00 Uhr", "vierundzwanzig Uhr"),
    ("24.000", "vierundzwanzigtausend"),
    ("von 8:30 bis 14:05 Uhr.", "von acht Uhr dreißig bis vierzehn Uhr fünf."),
    ("Vor 10 Uhr bestellt.", "Vor zehn Uhr bestellt."),
    ("6.{pause:500} Ab 8 Uhr 05.", "sechs.{pause:500} Ab acht Uhr fünf."),
    ("Schon ausgeschrieben: sechs, acht Uhr dreißig.",
     "Schon ausgeschrieben: sechs, acht Uhr dreißig."),
])
def test_german_numbers_and_times(source, expected):
    assert normalize_german_speech(source) == expected
    assert normalize_german_speech(expected) == expected


@pytest.mark.parametrize("engine", ["kokoro", "piper", "qwen"])
def test_every_engine_receives_spelled_text_and_numeric_options(app_config, tmp_path, engine):
    executable = tmp_path / "generate"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    model_dir = tmp_path / "model"
    for name in MODEL_FILES:
        model = model_dir / name
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"test model")
    config = replace(app_config, tts=replace(
        app_config.tts, engine=engine, kokoro_generator=executable,
        kokoro_model_directory=model_dir, qwen_generator=executable,
    ))
    output = tmp_path / "ansage-6.wav"
    command = PromptGenerator(config)._tts_command("Taste 6 ab 08:30 Uhr.", output)
    text_index = command.index("--" if engine == "piper" else "--text") + 1
    assert command[text_index] == "Taste sechs ab acht Uhr dreißig."
    assert str(output) in command
    option, value = {"kokoro": ("--speed", "1.0"), "qwen": ("--seed", "42"),
                     "piper": ("--length-scale", "1.3")}[engine]
    assert command[command.index(option) + 1] == value


def test_preview_spells_text_after_splitting_pause_controls(app_config, tmp_path, monkeypatch):
    generator = PromptGenerator(replace(app_config, tts=replace(app_config.tts, engine="piper")))
    commands = []
    joined = []
    monkeypatch.setattr(generator, "_run", lambda command, _: commands.append(command))
    monkeypatch.setattr(generator, "_join_with_pauses", lambda parts, *_: joined.extend(parts))
    monkeypatch.setattr(generator, "normalize_audio", lambda *_: None)
    generator.synthesize_text_file("Taste 6.{pause:700} Ab 8:05 Uhr.", tmp_path / "preview.wav", "test")
    assert [command[-1] for command in commands] == ["Taste sechs.", "Ab acht Uhr fünf."]
    assert joined[1] == 700


def test_dynamic_opening_and_phone_times_are_spelled(app_config):
    window = (TimeWindow(time(8, 5), time(14, 30)),)
    schedule = WeeklySchedule((window,) * 5 + ((), ()))
    config = replace(app_config, opening_hours=schedule, phone_hours=schedule,
                     tts=replace(app_config.tts, engine="piper"))
    rendered = rendered_prompts(config)
    generator = PromptGenerator(config)
    for name in ("opening_hours", "phone_hours"):
        spoken = generator._tts_command(rendered[name], Path("test.wav"))[-1]
        assert "von acht Uhr fünf bis vierzehn Uhr dreißig" in spoken
        assert not any(character.isdigit() for character in spoken)


def _stage_audio(config, name, content):
    for directory, suffixes in ((config.paths.prompt_masters, ("wav",)),
                               (config.paths.prompts, ("sln16", "g722", "alaw", "ulaw"))):
        directory.mkdir(parents=True, exist_ok=True)
        for suffix in suffixes:
            (directory / f"{name}.{suffix}").write_bytes(content)


def _fake_generate(generator, captured):
    def generate(name, text, staging):
        captured.append((name, generator._tts_command(text, staging / "source.wav")[-1]))
        staged_config = replace(generator.config, paths=replace(
            generator.config.paths, prompt_masters=staging / "masters", prompts=staging / "prompts",
        ))
        _stage_audio(staged_config, name, b"new audio")
    return generate


def test_update_refreshes_numbers_and_times_but_keeps_recordings_and_plain_text(
    app_config, monkeypatch,
):
    config = replace(app_config, tts=replace(app_config.tts, engine="piper"))
    generator = PromptGenerator(config)
    rendered = {"opening_hours_choice": "Drücken Sie 6.", "phone_hours": "Ab 8 Uhr 05.",
                "greeting_open": "Guten Tag.", "greeting_closed": "Ab 10 Uhr geschlossen."}
    config.tts.upload_directory.mkdir()
    manual = config.tts.upload_directory / "greeting_closed.wav"
    manual.write_bytes(b"personal recording")
    for name in rendered:
        _stage_audio(config, name, b"old audio")
    # 2.4.1 hashed unmodified source text, including digits.
    with monkeypatch.context() as legacy:
        legacy.setattr("kienzlefon.prompts.normalize_german_speech", lambda text: text)
        entries = {name: {"text": text, "sha256": generator._digest(name, text)}
                   for name, text in rendered.items()}
    generator.manifest_path.write_text(json.dumps({"prompts": entries}))
    monkeypatch.setattr("kienzlefon.prompts.rendered_prompts", lambda _: rendered)
    generated = []
    monkeypatch.setattr(generator, "_generate_one", _fake_generate(generator, generated))

    assert generator.generate() == (2, 2)
    assert set(generated) == {("opening_hours_choice", "Drücken Sie sechs."),
                              ("phone_hours", "Ab acht Uhr fünf.")}
    for name in ("opening_hours_choice", "phone_hours"):
        for suffix in ("sln16", "g722", "alaw", "ulaw"):
            assert (config.paths.prompts / f"{name}.{suffix}").read_bytes() == b"new audio"
    assert manual.read_bytes() == b"personal recording"
    assert (config.paths.prompt_masters / "greeting_closed.wav").read_bytes() == b"old audio"
    assert generator.generate() == (0, 4)
    assert len(generated) == 2


def test_update_refreshes_saved_scheduled_tts_and_active_audio_in_one_run(app_config, monkeypatch):
    config = replace(app_config, tts=replace(app_config.tts, engine="piper"))
    tts_file = app_config.source.parent / "special.wav"
    tts_file.write_bytes(b"old saved TTS")
    scheduled = OverrideConfig(
        active=True, announcement="Ab 08:30 Uhr geöffnet.", block_phone_hours=False,
        expires_at=None, position="statt_begruessung", identifier="1" * 32,
        source="tts", tts_path=tts_file,
    )
    config = replace(config, scheduled_overrides=(scheduled,))
    generator = PromptGenerator(config)
    _stage_audio(config, scheduled.prompt_name, b"old active audio")
    generator.manifest_path.write_text(json.dumps({
        "tts_identity": "legacy 2.4.1 identity",
        "prompts": {scheduled.prompt_name: {
            "text": scheduled.announcement,
            "sha256": generator._digest(scheduled.prompt_name, scheduled.announcement),
        }},
    }))
    # Use real rendering: scheduled prompts must survive the catalog filter.
    assert rendered_prompts(config)[scheduled.prompt_name] == scheduled.announcement
    generated = []
    synthesized = []

    def synthesize(text, output, _name, **_kwargs):
        synthesized.append(generator._tts_command(text, output)[-1])
        output.write_bytes(b"new saved TTS")

    def generate(name, text, staging):
        assert generator._manual_source(name).read_bytes() == b"new saved TTS"
        _fake_generate(generator, generated)(name, text, staging)

    monkeypatch.setattr(generator, "synthesize_text_file", synthesize)
    monkeypatch.setattr(generator, "_generate_one", generate)
    assert generator.generate(only={scheduled.prompt_name}) == (1, 0)
    assert synthesized == ["Ab acht Uhr dreißig geöffnet."]
    assert tts_file.read_bytes() == b"new saved TTS"
    assert (config.paths.prompt_masters / f"{scheduled.prompt_name}.wav").read_bytes() == b"new audio"
    assert generator.generate(only={scheduled.prompt_name}) == (0, 1)
    assert len(generated) == len(synthesized) == 1
