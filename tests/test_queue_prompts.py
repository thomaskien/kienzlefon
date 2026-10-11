from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
