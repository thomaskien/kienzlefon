# kienzlefon tests
# Version: 1.8.3
# Changelog:
# - 1.8.3: Vollstaendige Feldfolge trotz schweigend uebersprungener Personendaten getestet.
# - 1.8: Leeren Abbruch verwerfen und technische Fehler weiterhin einreihen getestet.
# - 1.7: Originale Vorgangs-ID bei normalisierter Telefonanzeige abgesichert.
# - 1.6.2: Auflegen nach vorhandener Aufnahme ohne falschpositiven IVR-Fehler getestet.
# - 1.3: Keine zusaetzliche Pause nach Feldansage vor der Aufnahme abgesichert.
# - 1.0: Taste 6 und die zwei echten Menue-Durchlaeufe abgesichert.

from __future__ import annotations

from pathlib import Path

from kienzlefon.agi import AgiHangup
from kienzlefon.ivr import IVR
from kienzlefon.models import CallState, CallType, FieldName, RecordingResult


class DummyChannel:
    environment = {"agi_callerid": "unknown"}

    def set_variable(self, _name: str, _value: str) -> None:
        pass


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


class SilentPersonalDataChannel:
    environment = {"agi_callerid": "unknown"}

    def __init__(self) -> None:
        self.recorded: list[str] = []

    def stream_file(self, _path: Path, _digits: str = "") -> None:
        pass

    def record(self, path: Path, *, silence_seconds: int, max_seconds: int) -> RecordingResult:
        self.recorded.append(path.name)
        if path.name == "grund.wav":
            path.write_bytes(b"RIFF" + b"0" * 100)
            return RecordingResult(path, "SILENCE", True)
        return RecordingResult(path, "SILENCE", False)


class HealthyRecordingIVR(IVR):
    def _worker_healthy(self) -> bool:
        return True


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
