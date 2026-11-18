import json
import wave
from dataclasses import replace
from uuid import UUID

import pytest

from kienzlefon.ai_import import import_case, import_next_case
from kienzlefon.delivery import ERROR
from kienzlefon.models import CallState
from kienzlefon.spool import Spool


def _order(kind, *, person="Test", **fields):
    return {"call_type": kind, "complete": True, "zusammenfassung": "Synthetisches Anliegen",
            "fields": {"vorname": person, "nachname": "Beispiel", "geburtsdatum": "01.01.1980", **fields}}


def _case(directory, orders, identifier="5d360942-9234-4230-a967-4c05dbf5f201"):
    directory.mkdir()
    case = {"call_id": identifier, "status": "ready_for_review", "created_epoch": 1795000000,
            "caller_id": "+490000000000"}
    result = {"schema": "kienzlefon-multi-anliegen-v2.9", "call_id": identifier, "anliegen": orders}
    (directory / "call.json").write_text(json.dumps(case))
    (directory / "result.json").write_text(json.dumps(result))
    with wave.open(str(directory / "caller.wav"), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x02" * 160)
    return identifier


def test_ai_import_publishes_one_card_with_stable_concerns_and_optional_wav(app_config, tmp_path):
    config = replace(app_config, telepraxis=replace(app_config.telepraxis, demo=True, attach_audio=True))
    directory = tmp_path / "ai-case"
    call_id = _case(directory, [
        _order("rezeptbestellung", medikamente="Test A"),
        _order("rezeptbestellung", medikamente="Test B"),
        _order("ueb_req", fachrichtung="Testfach", grund="Testanlass"),
    ])

    identifier, = import_case(directory, config)

    output = config.telepraxis.output_directory
    assert identifier == f"ai-{UUID(call_id).hex}"
    target = output / f"{identifier}.json"
    document = json.loads(target.read_text())
    payload = document["payload"]
    assert document["typ"] == payload["typ"] == "mehrere_anliegen"
    assert payload["vorname"] == "Test"
    assert [(order["typ"], order["anliegen_id"]) for order in payload["anliegen_liste"]] == [
        ("rezeptbestellung", "a-001"), ("rezeptbestellung", "a-002"), ("ueb_req", "a-003"),
    ]
    assert all("vorname" not in order for order in payload["anliegen_liste"])
    wav = output / identifier / "audio/caller.wav"
    assert wav.read_bytes() == (directory / "caller.wav").read_bytes()
    ready, = Spool(config.paths.spool, config.practice.timezone).calls(CallState.READY)
    assert not (ready.audio_directory / "caller.wav").exists()
    target.unlink()
    wav.unlink()
    assert import_case(directory, config) == [identifier]
    assert not target.exists()
    assert not wav.exists()


def test_distinct_ai_patients_are_not_combined_or_given_shared_call_audio(app_config, tmp_path):
    config = replace(app_config, telepraxis=replace(app_config.telepraxis, demo=True, attach_audio=True))
    directory = tmp_path / "ai-case"
    _case(directory, [_order("termin", grund="Test A"), _order("termin", person="Muster", grund="Test B")])

    ids = import_case(directory, config)

    assert len(set(ids)) == 2
    output = config.telepraxis.output_directory
    payloads = [json.loads((output / f"{identifier}.json").read_text())["payload"] for identifier in ids]
    assert {item["vorname"] for item in payloads} == {"Test", "Muster"}
    assert all(item["typ"] == "termin" and "anliegen_liste" not in item for item in payloads)
    assert all(item["_kienzlefon"]["audio"] == [] for item in payloads)
    assert all(item["_kienzlefon"]["audio_beilage"] == ERROR for item in payloads)
    assert not tuple(output.rglob("*.wav"))


def test_json_only_ai_import_uses_existing_encrypted_format(app_config, tmp_path):
    config = replace(app_config, telepraxis=replace(app_config.telepraxis, attach_audio=False))
    directory = tmp_path / "ai-case"
    _case(directory, [_order("sonstiges", anliegen="Synthetische Mitteilung")])

    identifier, = import_case(directory, config)

    assert (config.telepraxis.output_directory / f"{identifier}.json.enc").is_file()
    assert not tuple(config.telepraxis.output_directory.glob("*.kienzlepaket"))
    ready, = Spool(config.paths.spool, config.practice.timezone).calls(CallState.READY)
    assert ready.load()["_kienzlefon"]["audio"] == []


def test_ai_import_rejects_unfinished_or_mismatched_case(app_config, tmp_path):
    directory = tmp_path / "ai-case"
    _case(directory, [_order("termin", grund="Test A")])
    meta = directory / "call.json"
    meta.write_text(json.dumps({**json.loads(meta.read_text()), "status": "pending"}))

    with pytest.raises(ValueError, match="noch nicht zum Import"):
        import_case(directory, app_config)


def test_automatic_import_only_processes_new_completed_case_directories(app_config, tmp_path):
    config = replace(app_config, telepraxis=replace(app_config.telepraxis, demo=True))
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    unfinished = "00250d31-c8f1-46d6-9600-12867f7d4c42"
    _case(incoming / unfinished, [_order("termin", grund="Test A")], unfinished)
    meta = incoming / unfinished / "call.json"
    meta.write_text(json.dumps({**json.loads(meta.read_text()), "status": "pending"}))
    finished = "b6542a28-081d-4888-8c91-f34ae209e4d5"
    _case(incoming / finished, [_order("termin", grund="Test B")], finished)

    assert import_next_case(incoming, config)
    assert not import_next_case(incoming, config)
    assert [path.name for path in config.telepraxis.output_directory.glob("*.json")] == [
        f"ai-{UUID(finished).hex}.json",
    ]
