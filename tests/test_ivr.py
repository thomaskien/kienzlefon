# kienzlefon tests
# Version: 2.4.0
# Changelog:
# - 2.4.0: Lautlosen AI-Shortcut und deaktivierte Ansagen getestet.
# - 2.3.2: Bestandteil der Regressionstests fuer Kienzlefon 2.3.2.
# - 2.3.1: Eingangs- und Menuephase ohne DTMF-Eingabe abgesichert.
# - 2.3: Getrennte Eingangsphase und exakte DTMF-Uebergabe ins klassische Menue getestet.
# - 1.8.3: Vollstaendige Feldfolge trotz schweigend uebersprungener Personendaten getestet.
# - 1.8: Leeren Abbruch verwerfen und technische Fehler weiterhin einreihen getestet.
# - 1.7: Originale Vorgangs-ID bei normalisierter Telefonanzeige abgesichert.
# - 1.6.2: Auflegen nach vorhandener Aufnahme ohne falschpositiven IVR-Fehler getestet.
# - 1.3: Keine zusaetzliche Pause nach Feldansage vor der Aufnahme abgesichert.
# - 1.0: Taste 6 und die zwei echten Menue-Durchlaeufe abgesichert.

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from kienzlefon.agi import AgiHangup
from kienzlefon.ivr import IVR
from kienzlefon.models import CallState, CallType, FieldName, RecordingResult


class DummyChannel:
    environment = {"agi_callerid": "unknown"}

    def set_variable(self, _name: str, _value: str) -> None:
        pass


class VariableChannel:
    environment = {"agi_callerid": "unknown"}

    def __init__(self) -> None:
        self.variables: dict[str, str] = {}

    def set_variable(self, name: str, value: str) -> None:
        self.variables[name] = value


class OpeningPhaseIVR(IVR):
    def _opening_sequence(self) -> str:
        return "8"


class OpeningPhaseWithoutDigitIVR(IVR):
    def _opening_sequence(self) -> None:
        return None


def test_opening_phase_returns_pressed_digit_without_starting_menu(app_config) -> None:
    channel = VariableChannel()
    ivr = OpeningPhaseIVR(app_config, channel)  # type: ignore[arg-type]

    ivr.run_opening()

    assert channel.variables["KZF_IVR_OPENING_OK"] == "1"
    assert channel.variables["KZF_IVR_INITIAL_DIGIT"] == "8"


def test_opening_phase_without_digit_allows_ai_admission(app_config) -> None:
    channel = VariableChannel()
    ivr = OpeningPhaseWithoutDigitIVR(app_config, channel)  # type: ignore[arg-type]

    ivr.run_opening()

    assert channel.variables["KZF_IVR_OPENING_OK"] == "1"
    assert channel.variables["KZF_IVR_INITIAL_DIGIT"] == "none"


class InitialDigitIVR(IVR):
    def __init__(self, config, digit: str):
        super().__init__(config, DummyChannel())
        self.expected = digit
        self.handled: list[str] = []
        self.played: list[str] = []

    def _worker_healthy(self) -> bool:
        return True

    def _main_menu(self) -> str:
        if self.expected == "6":
            return "0"
        raise AssertionError("Bei mitgegebener Taste darf das Hauptmenue nicht vorher laufen")

    def _play(self, key: str) -> None:
        self.played.append(key)

    def _handle_menu_digit(self, digit: str) -> bool:
        self.handled.append(digit)
        return True


@pytest.mark.parametrize("digit", list("012345789*#"))
def test_menu_phase_consumes_exact_initial_digit(app_config, digit: str) -> None:
    ivr = InitialDigitIVR(app_config, digit)

    ivr.run_menu(digit)

    assert ivr.handled == [digit]


def test_menu_phase_applies_classic_opening_hours_logic_to_initial_six(app_config) -> None:
    ivr = InitialDigitIVR(app_config, "6")

    ivr.run_menu("6")

    assert ivr.played == ["opening_hours"]
    assert ivr.handled == ["0"]


class MenuPhaseWithoutDigitIVR(IVR):
    def __init__(self, config):
        super().__init__(config, DummyChannel())
        self.handled: list[str] = []

    def _worker_healthy(self) -> bool:
        return True

    def _main_menu(self) -> str:
        return "0"

    def _handle_menu_digit(self, digit: str) -> bool:
        self.handled.append(digit)
        return True


def test_menu_phase_without_initial_digit_starts_normally(app_config) -> None:
    ivr = MenuPhaseWithoutDigitIVR(app_config)

    ivr.run_menu()

    assert ivr.handled == ["0"]


class MenuSixIVR(IVR):
    def __init__(self, config):
        super().__init__(config, DummyChannel())
        self.menu_calls = 0
        self.played = []
        self.fallback = False

    def _worker_healthy(self) -> bool:
        return True

    def _opening_sequence(self):
        return "6"

    def _main_menu(self):
        self.menu_calls += 1
        return None

    def _play(self, key):
        self.played.append(key)

    def _record_closed_fallback(self):
        self.fallback = True


def test_opening_hours_choice_does_not_consume_menu_attempt(app_config) -> None:
    ivr = MenuSixIVR(app_config)
    ivr.run()
    assert ivr.played == ["opening_hours"]
    assert ivr.menu_calls == 2
    assert ivr.fallback is True


@pytest.mark.parametrize("marker", ["asr-maintenance", "tts-maintenance"])
def test_qwen_maintenance_marker_makes_worker_unavailable(app_config, marker: str) -> None:
    app_config.paths.runtime.mkdir(parents=True, exist_ok=True)
    (app_config.paths.runtime / marker).write_text("test", encoding="utf-8")

    assert IVR(app_config, DummyChannel())._worker_healthy() is False


class RecordingChannel:
    environment = {"agi_callerid": "unknown"}

    def __init__(self) -> None:
        self.events: list[str] = []

    def stream_file(self, _path: Path, _digits: str = "") -> None:
        self.events.append("ansage")

    def record(self, path: Path, *, silence_seconds: int, max_seconds: int) -> RecordingResult:
        self.events.append("aufnahme")
        path.write_bytes(b"R" * 45)
        return RecordingResult(path, "DTMF", True)

    def command(self, _command: str):
        self.events.append("pause")
        raise AssertionError("Zwischen Feldansage und Aufnahme darf keine Pause liegen")


def test_field_recording_starts_immediately_after_prompt(app_config) -> None:
    channel = RecordingChannel()
    ivr = IVR(app_config, channel)  # type: ignore[arg-type]
    ivr.call = ivr.spool.create_call(CallType.CALLBACK_DETAILS, None, "test")
    assert ivr._record_field(FieldName.FIRST_NAME, "first_name", "vorname.wav", long=False)
    assert channel.events == ["ansage", "aufnahme"]


class OpeningSequenceIVR(IVR):
    def __init__(self, config):
        super().__init__(config, DummyChannel())
        self.played: list[str] = []

    def _stream(self, key: str, _digits: str = "", **_kwargs) -> None:
        self.played.append(key)


def test_zero_in_classic_menu_requests_silent_ai_retry(app_config) -> None:
    channel = VariableChannel()
    ivr = IVR(app_config, channel)  # type: ignore[arg-type]

    assert ivr._handle_menu_digit("0") is True
    assert channel.variables["KZF_IVR_AI_REQUESTED"] == "1"


class PromptModeChannel(VariableChannel):
    def __init__(self) -> None:
        super().__init__()
        self.played: list[str] = []

    def stream_file(self, path: Path, _digits: str = "") -> None:
        self.played.append(path.name)


def test_disabled_prompt_is_skipped_without_blocking_following_route(app_config) -> None:
    config = replace(
        app_config,
        prompt_modes={**app_config.prompt_modes, "no_selection_open": "deaktiviert"},
    )
    channel = PromptModeChannel()
    ivr = IVR(config, channel)  # type: ignore[arg-type]

    ivr._play("no_selection_open")
    ivr._play("completed")

    assert channel.played == ["completed"]


def test_urgent_help_always_follows_active_override_that_blocks_phone_hours(
    app_config, monkeypatch
) -> None:
    config = replace(
        app_config,
        override=replace(app_config.override, active=True),
    )
    monkeypatch.setattr(type(app_config), "urgent_help_is_active", lambda _self: False)
    ivr = OpeningSequenceIVR(config)

    assert ivr._opening_sequence() is None
    assert ivr.played == ["override", "emergency", "urgent_help"]


def test_override_without_phone_block_keeps_normal_urgent_help_timing(
    app_config, monkeypatch
) -> None:
    config = replace(
        app_config,
        override=replace(app_config.override, active=True, block_phone_hours=False),
    )
    monkeypatch.setattr(type(config), "urgent_help_is_active", lambda _self: False)
    ivr = OpeningSequenceIVR(config)

    assert ivr._opening_sequence() is None
    assert ivr.played == ["override", "emergency"]


def test_override_after_greeting_uses_closed_greeting_when_phone_hours_are_blocked(
    app_config, monkeypatch
) -> None:
    config = replace(
        app_config,
        override=replace(
            app_config.override,
            active=True,
            block_phone_hours=True,
            position="nach_begruessung",
        ),
    )
    monkeypatch.setattr(type(config), "practice_is_open", lambda _self: True)
    monkeypatch.setattr(type(config), "urgent_help_is_active", lambda _self: False)
    ivr = OpeningSequenceIVR(config)

    assert ivr._opening_sequence() is None
    assert ivr.played == [
        "greeting_closed",
        "override",
        "emergency",
        "urgent_help",
    ]


def test_override_before_greeting_uses_requested_order(app_config, monkeypatch) -> None:
    config = replace(
        app_config,
        override=replace(
            app_config.override,
            active=True,
            block_phone_hours=False,
            position="vor_begruessung",
        ),
    )
    monkeypatch.setattr(type(config), "practice_is_open", lambda _self: True)
    monkeypatch.setattr(type(config), "urgent_help_is_active", lambda _self: False)
    ivr = OpeningSequenceIVR(config)

    assert ivr._opening_sequence() is None
    assert ivr.played == ["override", "greeting_open", "emergency"]


def test_scheduled_override_uses_its_own_generated_prompt(app_config, monkeypatch) -> None:
    scheduled = replace(
        app_config.override,
        identifier="4" * 32,
        name="Geplante Ansage",
        active=True,
        priority=500,
        announcement="Geplanter Hinweis.",
        block_phone_hours=False,
    )
    config = replace(app_config, scheduled_overrides=(scheduled,))
    monkeypatch.setattr(type(config), "urgent_help_is_active", lambda _self: False)
    ivr = OpeningSequenceIVR(config)

    assert ivr._opening_sequence() is None
    assert ivr.played == [f"override_{'4' * 32}", "emergency"]


class SilentPersonalDataChannel:
    environment = {"agi_callerid": "unknown"}

    def __init__(self) -> None:
        self.recorded: list[str] = []

    def stream_file(self, _path: Path, _digits: str = "") -> None:
        pass

    def get_option(self, _path: Path, _digits: str, _timeout: int) -> None:
        return None

    def record(self, path: Path, *, silence_seconds: int, max_seconds: int) -> RecordingResult:
        self.recorded.append(path.name)
        if path.name == "grund.wav":
            path.write_bytes(b"RIFF" + b"0" * 100)
            return RecordingResult(path, "SILENCE", True)
        return RecordingResult(path, "SILENCE", False)


class HealthyRecordingIVR(IVR):
    def _worker_healthy(self) -> bool:
        return True


class FollowupChannel(VariableChannel):
    def __init__(self, choices, *, hangup_on: str = "", silent_on: str = "") -> None:
        super().__init__()
        self.choices = iter(choices)
        self.recorded: list[str] = []
        self.hangup_on = hangup_on
        self.silent_on = silent_on

    def stream_file(self, _path: Path, _digits: str = "") -> None:
        pass

    def get_option(self, path: Path, digits: str, _timeout: int) -> str | None:
        prompt, choice = next(self.choices)
        assert path.name == prompt
        assert choice is None or choice in digits
        return choice

    def record(self, path: Path, **_kwargs) -> RecordingResult:
        self.recorded.append(path.name)
        if path.name == self.hangup_on:
            raise AgiHangup("Aufgelegt während der Neuaufnahme")
        if path.name == self.silent_on:
            return RecordingResult(path, "SILENCE", False)
        path.write_bytes(b"RIFF" + b"0" * 100)
        return RecordingResult(path, "DTMF", True)


def test_followup_records_repeat_types_with_separate_ids_and_shared_person(app_config) -> None:
    channel = FollowupChannel([
        ("medication_choice", "2"), ("more_concern", "1"), ("concern_types", "7"),
        ("medication_choice", "2"), ("more_concern", "1"), ("concern_types", "5"),
        ("submenu_five", "2"), ("more_concern", "2"),
    ])
    keys = {**app_config.ivr_keys, "rezept": "7", "ueberweisung": ""}
    ivr = HealthyRecordingIVR(replace(app_config, ivr_keys=keys), channel)

    ivr.run_menu(initial_digit="7")

    call, = ivr.spool.calls(CallState.QUEUE)
    record = call.load()
    assert record["typ"] == "mehrere_anliegen"
    assert [(item["anliegen_id"], item["typ"]) for item in record["anliegen_liste"]] == [
        ("a-001", "rezeptbestellung"), ("a-002", "rezeptbestellung"), ("a-003", "sonstiges"),
    ]
    assert channel.recorded[:4] == ["vorname.wav", "nachname.wav", "geburtsdatum.wav", "telefon.wav"]
    assert not any("anliegen_id" in audio for audio in record["_kienzlefon"]["audio"][:4])
    assert [(audio["anliegen_id"], audio["datei"]) for audio in record["_kienzlefon"]["audio"][4:]] == [
        ("a-001", "audio/medikament-01.wav"), ("a-002", "audio/a-002-medikament-01.wav"),
        ("a-003", "audio/a-003-anliegen.wav"),
    ]


@pytest.mark.parametrize("hangup", [False, True])
def test_empty_or_abandoned_followup_keeps_single_legacy_concern(app_config, hangup) -> None:
    extra = "a-002-grund.wav"
    choices = [("more_concern", "1"), ("concern_types", "4")]
    if not hangup:
        choices.append(("more_concern", None))
    channel = FollowupChannel(choices, hangup_on=extra if hangup else "", silent_on=extra)
    ivr = HealthyRecordingIVR(app_config, channel)

    ivr.run_menu(initial_digit="4")

    call, = ivr.spool.calls(CallState.QUEUE)
    record = call.load()
    assert record["typ"] == "termin"
    assert "anliegen_liste" not in record
    assert record["_kienzlefon"]["audio"][-1]["datei"] == "audio/grund.wav"
    assert "anliegen_id" not in record["_kienzlefon"]["audio"][-1]


def test_silent_personal_fields_do_not_skip_actual_concern(app_config) -> None:
    channel = SilentPersonalDataChannel()
    ivr = HealthyRecordingIVR(app_config, channel)  # type: ignore[arg-type]

    ivr._record_structured(CallType.APPOINTMENT, "termin")

    assert channel.recorded == [
        "vorname.wav",
        "nachname.wav",
        "geburtsdatum.wav",
        "telefon.wav",
        "grund.wav",
    ]
    queued = next(iter(ivr.spool.calls(CallState.QUEUE)))
    record = queued.load()
    assert record["_kienzlefon"]["errors"] == []
    assert [entry["status"] for entry in record["_kienzlefon"]["audio"]] == [
        "empty",
        "empty",
        "empty",
        "empty",
        "recorded",
    ]


class HangupAfterRecordingIVR(IVR):
    def _worker_healthy(self) -> bool:
        return True

    def _opening_sequence(self):
        self.call = self.spool.create_call(
            CallType.CALLBACK_FALLBACK,
            "+4923319265005",
            "rueckruf_ohne_tastenauswahl",
        )
        audio = self.call.begin_audio(FieldName.REASON, "grund.wav")
        audio.write_bytes(b"RIFF" + b"0" * 100)
        self.call.set_audio_record_status("grund.wav", "HANGUP", True)
        raise AgiHangup("AGI-Kanal ist bereits beendet")


def test_hangup_after_recording_queues_call_without_ivr_error(app_config) -> None:
    ivr = HangupAfterRecordingIVR(app_config, DummyChannel())  # type: ignore[arg-type]
    ivr.run()

    queued = tuple(ivr.spool.calls(CallState.QUEUE))
    assert len(queued) == 1
    record = queued[0].load()
    assert record["_kienzlefon"]["abschluss"] == "aufgelegt_oder_abgebrochen"
    assert record["_kienzlefon"]["errors"] == []
    assert record["_kienzlefon"]["audio"][0]["aufnahme_status"] == "HANGUP"
    assert record["_kienzlefon"]["audio"][0]["datei_vorhanden"] is True


class HangupBeforeRecordingIVR(IVR):
    def _worker_healthy(self) -> bool:
        return True

    def _opening_sequence(self):
        self.call = self.spool.create_call(
            CallType.CALLBACK_FALLBACK,
            "+4923319265005",
            "rueckruf_ohne_tastenauswahl",
        )
        raise AgiHangup("Aufgelegt, bevor die Aufnahme begonnen hat")


def test_hangup_before_recording_discards_empty_call(app_config) -> None:
    ivr = HangupBeforeRecordingIVR(app_config, DummyChannel())  # type: ignore[arg-type]
    ivr.run()

    assert tuple(ivr.spool.calls(CallState.RECORDING)) == ()
    assert tuple(ivr.spool.calls(CallState.QUEUE)) == ()


class TechnicalErrorBeforeRecordingIVR(HangupBeforeRecordingIVR):
    def _opening_sequence(self):
        self.call = self.spool.create_call(
            CallType.CALLBACK_FALLBACK,
            "+4923319265005",
            "rueckruf_ohne_tastenauswahl",
        )
        self.call.add_error("TEST_ERROR", "ivr", "Technischer Testfehler")
        raise AgiHangup("Aufgelegt nach technischem Fehler")


def test_technical_error_without_audio_is_not_discarded(app_config) -> None:
    ivr = TechnicalErrorBeforeRecordingIVR(
        app_config, DummyChannel()  # type: ignore[arg-type]
    )
    ivr.run()

    queued = tuple(ivr.spool.calls(CallState.QUEUE))
    assert len(queued) == 1
    assert queued[0].load()["_kienzlefon"]["errors"][0]["code"] == "TEST_ERROR"


class CallerIdIVR(IVR):
    def _worker_healthy(self) -> bool:
        return False

    def _play(self, _key: str) -> None:
        pass

    def _goto_queue(self) -> None:
        pass


class CallerIdChannel:
    environment = {"agi_callerid": "492331123456"}

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set_variable(self, name: str, value: str) -> None:
        self.values[name] = value


def test_phone_display_is_normalized_without_changing_original_caller_id(app_config) -> None:
    channel = CallerIdChannel()
    ivr = CallerIdIVR(app_config, channel)  # type: ignore[arg-type]
    ivr.run()
    assert channel.values["CALLERID(num)"] == "02331123456"
    assert ivr.caller_id == "492331123456"


def test_main_menu_uses_saved_order_and_preserves_time_gates_and_digits(app_config, monkeypatch):
    from kienzlefon.ivr_keys import MENU_PROMPTS, MENU_CHOICES
    from kienzlefon.prompts import rendered_prompts

    config = replace(app_config, menu_order=tuple(reversed(MENU_PROMPTS)), menu_choices=tuple(reversed(MENU_CHOICES)))
    text = rendered_prompts(config)["menu_open"]
    assert text.index("Für ein Rezept drücken Sie 2.") < text.index("Um mit der Praxis zu sprechen drücken Sie 1.")
    menu = IVR(config, DummyChannel())
    heard = []
    monkeypatch.setattr(menu, "_stream", lambda name, digits: heard.append(name))
    monkeypatch.setattr(menu, "_wait_for_digit", lambda: "2")
    assert menu._main_menu() == "2"
    assert heard == ["phone_hours", "opening_hours_choice", "menu_closed", "menu_intro"]
    monkeypatch.setattr(type(config), "phone_is_open", lambda self: True)
    assert menu._main_menu() == "2"
    assert heard[-3:] == ["opening_hours_choice", "menu_open", "menu_intro"]
