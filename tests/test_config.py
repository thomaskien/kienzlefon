# kienzlefon tests
# Version: 2.4.0
# Changelog:
# - 2.4.0: Ansagenmodi und Pflichttextpruefung getestet.
# - 2.3.2: Obsolete Hauptserver-Assistentenansage nicht mehr vorausgesetzt.
# - 2.3: Assistentenansage als Pflichtkonfiguration getestet.
# - 1.9: Demo-Anonymisierung und ihre Beschraenkung auf den Demomodus getestet.
# - 1.8.2: Bereitschaftsdienst vor erster und nach letzter Tagesoeffnung getestet.
# - 1.8: Demoausgabe ohne Public Key und Produktivpflicht fuer den Key getestet.
# - 1.7: Optionales rotes Telefon und Sonderqueue-Standardwerte abgesichert.
# - 1.6: Getrennte Whisper-Modellbereiche und Initial-Prompts abgesichert.
# - 1.5: Lautheits- und True-Peak-Standardwerte abgesichert.
# - 1.1: Standardwerte der neuen TTS-, IVR- und Notfallparameter abgesichert.
# - 1.0: Konfigurations-, Zeitprofil- und Caller-ID-Regeln abgesichert.

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from kienzlefon.config import (
    ConfigError,
    TimeWindow,
    WeeklySchedule,
    caller_id_or_none,
    load_config,
)


def test_unknown_caller_ids_are_rejected() -> None:
    for value in (None, "", "anonymous", "UNKNOWN", " private "):
        assert caller_id_or_none(value) is None
    assert caller_id_or_none("+4923311234") == "+4923311234"


def test_weekend_urgent_help_is_all_day(app_config) -> None:
    saturday = datetime(2026, 7, 11, 10, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    assert app_config.practice_is_open(saturday) is False
    assert app_config.urgent_help_is_active(saturday) is True


def test_urgent_help_wraps_daily_opening_span_but_excludes_midday_gap(app_config) -> None:
    monday = (
        TimeWindow(time(8), time(12)),
        TimeWindow(time(14), time(17)),
    )
    config = replace(
        app_config,
        opening_hours=WeeklySchedule((monday,) + ((),) * 6),
    )
    timezone = ZoneInfo("Europe/Berlin")

    assert config.urgent_help_is_active(datetime(2026, 7, 13, 0, 5, tzinfo=timezone)) is True
    assert config.urgent_help_is_active(datetime(2026, 7, 13, 7, 59, tzinfo=timezone)) is True
    assert config.urgent_help_is_active(datetime(2026, 7, 13, 8, 0, tzinfo=timezone)) is False
    assert config.urgent_help_is_active(datetime(2026, 7, 13, 12, 30, tzinfo=timezone)) is False
    assert config.urgent_help_is_active(datetime(2026, 7, 13, 14, 0, tzinfo=timezone)) is False
    assert config.urgent_help_is_active(datetime(2026, 7, 13, 17, 0, tzinfo=timezone)) is True


def test_override_blocks_phone_hours(app_config) -> None:
    assert app_config.override.active is False
    assert app_config.override.position == "statt_begruessung"
    assert app_config.ivr.attempts == 2
    assert app_config.whisper.standard_model == "large-v3-turbo"
    assert app_config.whisper.name_model == "large-v3"
    assert app_config.whisper.medication_model == "large-v3-turbo"
    assert app_config.whisper.models == ("large-v3-turbo", "large-v3")
    assert app_config.whisper.model_for("vorname") == "large-v3"
    assert app_config.whisper.model_for("nachname") == "large-v3"
    assert app_config.whisper.model_for("medikamente") == "large-v3-turbo"
    assert app_config.whisper.model_for("anliegen") == "large-v3-turbo"
    assert "Wirkstoff" in (app_config.whisper.initial_prompt_for("medikamente") or "")
    assert app_config.tts.length_scale == 1.3
    assert app_config.tts.target_loudness_lufs == -19.0
    assert app_config.tts.max_true_peak_db == -2.0
    assert app_config.tts.sentence_silence == 0.8
    assert app_config.tts.engine == "kokoro"
    assert app_config.tts.qwen_voice == "ryan"
    assert app_config.tts.qwen_language == "German"
    assert app_config.tts.qwen_seed == 42
    assert app_config.ivr.announcement_pause_ms == 700
    assert app_config.ivr.red_ring_seconds == 20
    assert app_config.ivr.red_fallback_priority == 100
    assert app_config.ivr.red_enabled is True
    assert app_config.special_queue.name == "kienzlefon-sonder"
    assert app_config.special_queue.weight == 100
    assert app_config.special_queue.additional_extensions == ()
    assert app_config.telepraxis.demo is False
    assert app_config.telepraxis.anonymize_phone_numbers is False
    assert app_config.telepraxis.public_key is not None
    assert app_config.ai_integration.enabled is False
    assert app_config.ai_integration.listener_mode == "local"
    assert app_config.ai_integration.listener_ip == "127.0.0.1"
    assert app_config.ai_integration.extension_count == 0
    assert "ai_assistant_intro" not in app_config.prompts.values


def test_ai_integration_derives_slots_and_extensions(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace("aktiv = false\nlistener_bindung", "aktiv = true\nlistener_bindung", 1)
    source = source.replace('listener_bindung = "local"', 'listener_bindung = "lan"')
    source = source.replace('listener_ip = "127.0.0.1"', 'listener_ip = "192.168.10.20"')
    source = source.replace("anzahl_nebenstellen = 0", "anzahl_nebenstellen = 3")
    source = source.replace(
        "sip_passwoerter = []",
        'sip_passwoerter = ["aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb", "cccccccccccccccccccccccc"]',
    )
    target = tmp_path / "ai.toml"
    target.write_text(source, encoding="utf-8")

    config = load_config(target)

    assert config.ai_integration.slot_ids == ("ai-slot-00", "ai-slot-01", "ai-slot-02")
    assert config.ai_integration.extensions == ("8810", "8811", "8812")
    assert "8800" in config.local_extensions
    assert "8812" in config.local_extensions


def test_ai_listener_rejects_wildcard_bind(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace('listener_ip = "127.0.0.1"', 'listener_ip = "0.0.0.0"')
    target = tmp_path / "wildcard.toml"
    target.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match="Wildcard"):
        load_config(target)


def test_ai_enabled_requires_toml_boolean(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace("aktiv = false\nlistener_bindung", 'aktiv = "false"\nlistener_bindung', 1)
    target = tmp_path / "invalid-ai-enabled.toml"
    target.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match="muss true oder false sein"):
        load_config(target)


def test_scheduled_overrides_select_highest_current_priority(app_config) -> None:
    root = app_config.paths.prompt_masters / "sonderansagen"
    entries = (
        (
            "1" * 32,
            {
                "name": "Erste Stufe",
                "announcement": "Erste Ansage.",
                "active": True,
                "priority": 300,
                "valid_from": "2026-12-24T00:00",
                "expires_at": "2026-12-25T00:00",
                "block_phone_hours": True,
                "position": "nach_begruessung",
                "source": "tts",
            },
        ),
        (
            "2" * 32,
            {
                "name": "Zweite Stufe",
                "announcement": "Zweite Ansage.",
                "active": True,
                "priority": 200,
                "valid_from": "",
                "expires_at": "2026-12-27T00:00",
                "block_phone_hours": False,
                "position": "vor_begruessung",
                "source": "tts",
            },
        ),
        (
            "3" * 32,
            {
                "name": "Dritte Stufe",
                "announcement": "Dritte Ansage.",
                "active": True,
                "priority": 100,
                "valid_from": "2026-12-27T00:00",
                "expires_at": "",
                "block_phone_hours": False,
                "position": "statt_begruessung",
                "source": "tts",
            },
        ),
    )
    for identifier, metadata in entries:
        directory = root / identifier
        directory.mkdir(parents=True)
        (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        (directory / "tts.wav").write_bytes(b"tts")

    config = load_config(app_config.source)
    timezone = ZoneInfo("Europe/Berlin")

    assert config.current_override(
        datetime(2026, 12, 24, 12, 0, tzinfo=timezone)
    ).name == "Erste Stufe"
    assert config.current_override(
        datetime(2026, 12, 26, 12, 0, tzinfo=timezone)
    ).name == "Zweite Stufe"
    assert config.current_override(
        datetime(2026, 12, 26, 12, 0, tzinfo=timezone)
    ).position == "vor_begruessung"
    assert config.current_override(
        datetime(2026, 12, 28, 12, 0, tzinfo=timezone)
    ).name == "Dritte Stufe"


def test_demo_mode_does_not_require_public_key(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace("demo = false", "demo = true")
    source = source.replace(
        'public_key = "/etc/kienzlefon/telepraxis-public.pem"', 'public_key = ""'
    )
    config_path = tmp_path / "demo.toml"
    config_path.write_text(source, encoding="utf-8")

    config = load_config(config_path)
    assert config.telepraxis.demo is True
    assert config.telepraxis.anonymize_phone_numbers is False
    assert config.telepraxis.public_key is None


def test_demo_mode_can_anonymize_phone_numbers(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace("demo = false", "demo = true")
    source = source.replace(
        "anrufernummern_anonymisieren = false",
        "anrufernummern_anonymisieren = true",
    )
    source = source.replace(
        'public_key = "/etc/kienzlefon/telepraxis-public.pem"', 'public_key = ""'
    )
    config_path = tmp_path / "anonymous-demo.toml"
    config_path.write_text(source, encoding="utf-8")

    config = load_config(config_path)

    assert config.telepraxis.demo is True
    assert config.telepraxis.anonymize_phone_numbers is True


def test_phone_number_anonymization_requires_demo_mode(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace(
        "anrufernummern_anonymisieren = false",
        "anrufernummern_anonymisieren = true",
    )
    config_path = tmp_path / "invalid-anonymization.toml"
    config_path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match="nur bei demo=true"):
        load_config(config_path)


def test_productive_mode_requires_public_key(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace(
        'public_key = "/etc/kienzlefon/telepraxis-public.pem"', 'public_key = ""'
    )
    config_path = tmp_path / "productive.toml"
    config_path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match="Produktivmodus erforderlich"):
        load_config(config_path)


def test_qwen_tts_accepts_only_allowlisted_speakers(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace('engine = "kokoro"', 'engine = "qwen"')
    source = source.replace('qwen_stimme = "ryan"', 'qwen_stimme = "serena"')
    config_path = tmp_path / "qwen.toml"
    config_path.write_text(source, encoding="utf-8")

    config = load_config(config_path)
    assert config.tts.engine == "qwen"
    assert config.tts.qwen_voice == "serena"

    config_path.write_text(
        source.replace('qwen_stimme = "serena"', 'qwen_stimme = "../../fremd"'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="nicht freigegeben"):
        load_config(config_path)


def test_demo_mode_rejects_string_value(tmp_path: Path) -> None:
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace("demo = false", 'demo = "false"')
    config_path = tmp_path / "invalid-demo.toml"
    config_path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match="muss true oder false sein"):
        load_config(config_path)


def test_prompt_modes_keep_defaults_and_allow_explicit_deactivation(app_config) -> None:
    assert app_config.prompt_mode("greeting_open") == "offen"
    assert app_config.prompt_mode("greeting_closed") == "zu"
    assert app_config.prompt_mode("emergency") == "immer"
    assert app_config.prompt_mode("completed") == "immer"

    text = app_config.source.read_text(encoding="utf-8").replace(
        'emergency = "immer"', 'emergency = "deaktiviert"', 1
    )
    app_config.source.write_text(text, encoding="utf-8")

    assert load_config(app_config.source).prompt_is_active("emergency") is False


def test_prompt_modes_follow_explicit_practice_state(app_config) -> None:
    config = replace(
        app_config,
        prompt_modes={
            **app_config.prompt_modes,
            "emergency": "offen",
            "greeting_open": "zu",
        },
    )

    assert config.prompt_is_active("emergency", practice_open=True) is True
    assert config.prompt_is_active("emergency", practice_open=False) is False
    assert config.prompt_is_active("greeting_open", practice_open=True) is False
    assert config.prompt_is_active("greeting_open", practice_open=False) is True


def test_invalid_prompt_mode_is_rejected(app_config) -> None:
    text = app_config.source.read_text(encoding="utf-8").replace(
        'emergency = "immer"', 'emergency = "manchmal"', 1
    )
    app_config.source.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="Ungueltige Ansagenmodi"):
        load_config(app_config.source)


def test_empty_required_prompt_is_rejected_but_optional_phone_text_remains_valid(
    app_config,
) -> None:
    assert app_config.prompts["phone_hours"] == ""
    text = app_config.source.read_text(encoding="utf-8").replace(
        'greeting_open = "Guten Tag, Sie sind verbunden mit der Praxis {praxisname}. Die Praxis ist momentan geöffnet."',
        'greeting_open = ""',
        1,
    )
    app_config.source.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="Leere Ansagetexte"):
        load_config(app_config.source)
