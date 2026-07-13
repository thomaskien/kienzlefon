# kienzlefon tests
# Version: 1.8
# Changelog:
# - 1.8: Sicheres Verwerfen ausschliesslich leerer fehlerfreier Aufnahmen getestet.
# - 1.0: Vorgangs-ID, JSON-Inhalt und atomare Statuswechsel getestet.

from __future__ import annotations

import re

import pytest

from kienzlefon.models import CallState, CallType, FieldName
from kienzlefon.spool import Spool


def test_call_directory_and_payload(app_config) -> None:
    spool = Spool(app_config.paths.spool, app_config.practice.timezone)
    call = spool.create_call(CallType.PRESCRIPTION, "+4923311234", "rezept")
    assert re.fullmatch(r"202[0-9]{5}_[0-9]{6}_[0-9]{6}", call.call_id)
    record = call.load()
    assert record["id"] == "+4923311234"
    assert record["telefon"] == "+4923311234"
    assert record["zusammenfassung"] == "keine Zusammenfassung vorhanden"
    assert record["typ"] == "rezeptbestellung"

    audio = call.begin_audio(FieldName.MEDICATION, "medikament-01.wav", index=1)
    audio.write_bytes(b"RIFF" + b"0" * 100)
    queued = spool.finish_recording(call, "aufgelegt")
    assert queued.path.parent.name == CallState.QUEUE.value
    assert queued.load()["_kienzlefon"]["abschluss"] == "aufgelegt"


def test_missing_caller_id_is_unknown(app_config) -> None:
    spool = Spool(app_config.paths.spool, app_config.practice.timezone)
    call = spool.create_call(CallType.CALLBACK_FALLBACK, None, "rueckruf")
    record = call.load()
    assert record["id"] == "unbekannt"
    assert record["telefon"] == "unbekannt"


def test_only_empty_error_free_recording_can_be_discarded(app_config) -> None:
    spool = Spool(app_config.paths.spool, app_config.practice.timezone)
    empty = spool.create_call(CallType.CALLBACK_FALLBACK, None, "rueckruf")
    spool.discard_empty_recording(empty)
    assert not empty.path.exists()

    recorded = spool.create_call(CallType.CALLBACK_FALLBACK, None, "rueckruf")
    audio = recorded.begin_audio(FieldName.REASON, "grund.wav")
    audio.write_bytes(b"RIFF" + b"0" * 100)
    with pytest.raises(ValueError, match="vorhandener Aufnahme"):
        spool.discard_empty_recording(recorded)

    failed = spool.create_call(CallType.CALLBACK_FALLBACK, None, "rueckruf")
    failed.add_error("TEST_ERROR", "test", "Fehler")
    with pytest.raises(ValueError, match="technischem Fehler"):
        spool.discard_empty_recording(failed)
