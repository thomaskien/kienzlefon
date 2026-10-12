from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from kienzlefon.config import load_config
from kienzlefon.migration import migrate_config, set_string
from kienzlefon.prompts import PROMPT_CATALOG, rendered_prompts
from kienzlefon.queue_prompts import (
    QUEUE_NUMBER_PROMPTS,
    QUEUE_NUMBER_TEXTS,
    digit_directory,
    german_number_files,
)

QUEUE_PROMPTS = (
    "queue_thankyou",
    "queue_youarenext",
    "queue_thereare",
    "queue_callswaiting",
)


def test_queue_prompts_are_appended_without_moving_existing_numbers() -> None:
    assert PROMPT_CATALOG[54:58] == (
        "webadmin_record",
        "webadmin_record_actions",
        "webadmin_record_saved",
        "webadmin_record_discarded",
    )
    assert PROMPT_CATALOG[58:62] == QUEUE_PROMPTS
    assert PROMPT_CATALOG[62:] == tuple(QUEUE_NUMBER_PROMPTS)


def test_queue_prompts_are_editable_rendered_texts(app_config) -> None:
    prompts = rendered_prompts(app_config)
    for name in QUEUE_PROMPTS:
        assert prompts[name] == app_config.prompts.values[name]
        assert prompts[name].strip()


def test_native_german_number_fragments_cover_composed_queue_positions() -> None:
    assert german_number_files(21) == ("1-and", "20")
    assert german_number_files(123) == ("1N", "hundred", "3-and", "20")
    assert german_number_files(1_002_003) == (
        "1F", "million", "2", "thousand", "3",
    )
    assert set(german_number_files(2_147_483_647)) <= set(QUEUE_NUMBER_PROMPTS.values())


def test_number_prompts_are_editable_and_have_unique_asterisk_files(app_config) -> None:
    prompts = rendered_prompts(app_config)
    assert len(set(QUEUE_NUMBER_PROMPTS.values())) == len(QUEUE_NUMBER_PROMPTS)
    for name, text in QUEUE_NUMBER_TEXTS.items():
        assert prompts[name] == text


def test_generation_repeats_and_manual_update_refresh_digit_aliases(
    app_config, monkeypatch
) -> None:
    from kienzlefon.prompts import PromptGenerator

    name = "queue_digit_1_and"

    def generate_one(self, prompt_name: str, text: str, staging: Path, **_kwargs) -> None:
        manual = self._manual_source(prompt_name)
        payload = manual.read_bytes() if manual is not None else text.encode("utf-8")
        master = staging / "masters" / f"{prompt_name}.wav"
        master.parent.mkdir(parents=True, exist_ok=True)
        master.write_bytes(payload)
        output = staging / "prompts"
        output.mkdir(parents=True, exist_ok=True)
        for suffix in ("sln16", "g722", "alaw", "ulaw"):
            (output / f"{prompt_name}.{suffix}").write_bytes(payload + suffix.encode())

    monkeypatch.setattr(PromptGenerator, "_generate_one", generate_one)
    generator = PromptGenerator(app_config)
    assert generator.generate(only={name}, force=True) == (1, 0)
    aliases = sorted(digit_directory(app_config.paths.prompts).glob("1-and.*"))
    assert len(aliases) == 4
    assert generator.generate(only={name}) == (0, 1)

    manual = app_config.tts.upload_directory / f"{name}.wav16"
    manual.parent.mkdir(parents=True, exist_ok=True)
    manual.write_bytes(b"manual-number")
    manual_config = replace(app_config, prompt_sources={name: "manuell"})
    assert PromptGenerator(manual_config).generate(only={name}) == (1, 0)
    assert all(path.read_bytes().startswith(b"manual-number") for path in aliases)


def test_queue_position_update_regenerates_only_both_changed_fragments(
    app_config, monkeypatch
) -> None:
    from kienzlefon.prompts import PromptGenerator

    def generate_one(self, name: str, text: str, staging: Path) -> None:
        for directory, suffixes in (("masters", ("wav",)),
                                    ("prompts", ("sln16", "g722", "alaw", "ulaw"))):
            output = staging / directory
            output.mkdir(parents=True, exist_ok=True)
            for suffix in suffixes:
                (output / f"{name}.{suffix}").write_text(text, encoding="utf-8")

    monkeypatch.setattr(PromptGenerator, "_generate_one", generate_one)
    set_string(app_config.source, "ansagen", "queue_thereare", "Vor Ihnen warten noch")
    set_string(app_config.source, "ansagen", "queue_callswaiting", "Anrufe.")
    selected = set(QUEUE_PROMPTS)
    assert PromptGenerator(load_config(app_config.source)).generate(only=selected) == (4, 0)

    template = Path("config/kienzlefon.toml.example")
    assert migrate_config(app_config.source, template) is True
    updated = load_config(app_config.source)
    assert PromptGenerator(updated).generate(only=selected) == (2, 2)
    assert migrate_config(app_config.source, template) is False
    assert PromptGenerator(updated).generate(only=selected) == (0, 4)
    prompts = rendered_prompts(updated)
    assert prompts["queue_youarenext"] == "Sie sind als Nächstes an der Reihe."
    # app_queue speaks qe->pos unchanged between these two audio fragments.
    assert " ".join((prompts["queue_thereare"], "zwei", prompts["queue_callswaiting"])) == (
        "Sie sind auf Position zwei in der Warteschlange."
    )
    for name in selected:
        for suffix in ("sln16", "g722", "alaw", "ulaw"):
            assert (updated.paths.prompts / f"{name}.{suffix}").read_text(
                encoding="utf-8"
            ) == prompts[name]


@pytest.mark.parametrize("name", ["queue_thereare", "queue_callswaiting"])
@pytest.mark.parametrize("customization", ["text", "manual", "upload-wav", "upload-wav16"])
def test_queue_position_migration_preserves_custom_pairs(app_config, name, customization) -> None:
    set_string(app_config.source, "ansagen", "queue_thereare", "Vor Ihnen warten noch")
    set_string(app_config.source, "ansagen", "queue_callswaiting", "Anrufe.")
    if customization == "text":
        set_string(app_config.source, "ansagen", name, "Eigener Text.")
    elif customization == "manual":
        with app_config.source.open("a", encoding="utf-8") as handle:
            handle.write(f'\n[ansagen_quellen]\n{name} = "manuell"\n')
    else:
        # Old installations also activate uploads without an explicit source.
        app_config.tts.upload_directory.mkdir(parents=True, exist_ok=True)
        (app_config.tts.upload_directory / f"{name}.{customization[7:]}").write_bytes(
            b"custom recording"
        )
    before = app_config.source.read_bytes()
    assert migrate_config(app_config.source, Path("config/kienzlefon.toml.example")) is False
    assert app_config.source.read_bytes() == before
