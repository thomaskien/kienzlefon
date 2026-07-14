# kienzlefon tests
# Version: 1.8.3
# Changelog:
# - 1.8.3: Leere Personentranskripte blockieren ein langes Anliegen nicht mehr.
# - 1.6: Feldbezogene Modellwahl, Mehrmodell-Ladung und Initial-Prompts getestet.
# - 1.1: Entfernung genau eines abschliessenden Whisper-Punkts getestet.
# - 1.0: Sequentielle Transkription und Medikament-Zeilenumbrueche getestet.

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kienzlefon.models import CallState, CallType, FieldName
from kienzlefon.crypto import EncryptionError
from kienzlefon.spool import Spool, WorkingCall
from kienzlefon.worker import FasterWhisperTranscriber, Worker, clean_transcript


class FakeTranscriber:
    def transcribe(self, path: Path, _field: FieldName | str) -> str:
        return {
            "vorname.wav": "Max.",
            "nachname.wav": "Muster.",
            "geburtsdatum.wav": "1. Januar 1970",
            "medikament-01.wav": "Ramipril 5 Milligramm N3.",
            "medikament-02.wav": "Metoprolol 47,5 Milligramm N3.",
            "grund.wav": "Termin am Montag",
        }[path.name]


def test_worker_keeps_medications_on_separate_lines(app_config) -> None:
    spool = Spool(app_config.paths.spool, app_config.practice.timezone)
    call = spool.create_call(CallType.PRESCRIPTION, "+4923311234", "rezept")
    entries = (
        (FieldName.FIRST_NAME, "vorname.wav", None),
        (FieldName.LAST_NAME, "nachname.wav", None),
        (FieldName.BIRTH_DATE, "geburtsdatum.wav", None),
        (FieldName.MEDICATION, "medikament-01.wav", 1),
        (FieldName.MEDICATION, "medikament-02.wav", 2),
    )
    for field, filename, index in entries:
        path = call.begin_audio(field, filename, index)
        path.write_bytes(b"RIFF" + b"0" * 100)
    queued = spool.finish_recording(call, "abgeschlossen")
    claimed = spool.claim_next()
    assert claimed is not None

    worker = Worker(app_config, transcriber=FakeTranscriber())
    worker.process(WorkingCall(claimed.path, app_config.practice.timezone))

    ready = next(iter(spool.calls(CallState.READY)))
    record = ready.load()
    assert record["vorname"] == "Max"
    assert record["medikamente"] == ("Ramipril 5 Milligramm N3\nMetoprolol 47,5 Milligramm N3")
    assert (app_config.telepraxis.output_directory / f"{queued.call_id}.json.enc").is_file()


def test_transcript_cleanup_preserves_internal_punctuation() -> None:
    assert clean_transcript(" Seit gestern. Husten. ") == "Seit gestern. Husten"
    assert clean_transcript("Max") == "Max"
    assert clean_transcript("Text...") == "Text.."


def test_failed_person_field_does_not_block_fallback_text(app_config) -> None:
    class FallbackTranscriber:
        def transcribe(self, path: Path, _field: FieldName | str) -> str:
            return "Langer Inhalt mit allen Angaben"

    spool = Spool(app_config.paths.spool, app_config.practice.timezone)
    call = spool.create_call(CallType.APPOINTMENT, None, "termin")
    missing = call.begin_audio(FieldName.FIRST_NAME, "vorname.wav")
    assert not missing.exists()
    call.set_audio_record_status("vorname.wav", "ERROR", False)
    call.add_error("RECORDING_FAILED", "aufnahme", "Vorname fehlt")
    fallback = call.begin_audio(FieldName.REASON, "fallback.wav")
    fallback.write_bytes(b"RIFF" + b"0" * 100)
    spool.finish_recording(call, "abgeschlossen")
    claimed = spool.claim_next()
    assert claimed is not None

    Worker(app_config, transcriber=FallbackTranscriber()).process(
        WorkingCall(claimed.path, app_config.practice.timezone)
    )
    ready = next(iter(spool.calls(CallState.READY)))
    assert ready.load()["grund"] == "Langer Inhalt mit allen Angaben"
    error_outputs = list(app_config.telepraxis.output_directory.glob("*_error_*.json.enc"))
    assert len(error_outputs) == 1


def test_silent_personal_transcripts_do_not_block_reason_or_report_errors(app_config) -> None:
    transcribed: list[str] = []

    class PartialTranscriber:
        def transcribe(self, path: Path, _field: FieldName | str) -> str:
            transcribed.append(path.name)
            if path.name == "grund.wav":
                return "Seit gestern bestehen starke Beschwerden mit weiteren Einzelheiten."
            return ""

    spool = Spool(app_config.paths.spool, app_config.practice.timezone)
    call = spool.create_call(CallType.APPOINTMENT, None, "termin")
    for field, filename in (
        (FieldName.FIRST_NAME, "vorname.wav"),
        (FieldName.LAST_NAME, "nachname.wav"),
        (FieldName.BIRTH_DATE, "geburtsdatum.wav"),
        (FieldName.CALLBACK_NUMBER, "telefon.wav"),
        (FieldName.REASON, "grund.wav"),
    ):
        audio = call.begin_audio(field, filename)
        audio.write_bytes(b"RIFF" + b"0" * 100)
    spool.finish_recording(call, "abgeschlossen")
    claimed = spool.claim_next()
    assert claimed is not None

    Worker(app_config, transcriber=PartialTranscriber()).process(
        WorkingCall(claimed.path, app_config.practice.timezone)
    )

    ready = next(iter(spool.calls(CallState.READY)))
    record = ready.load()
    assert transcribed == [
        "vorname.wav",
        "nachname.wav",
        "geburtsdatum.wav",
        "telefon.wav",
        "grund.wav",
    ]
    assert record["vorname"] == ""
    assert record["nachname"] == ""
    assert record["geburtsdatum"] == ""
    assert record["telefon"] == "unbekannt"
    assert record["grund"] == "Seit gestern bestehen starke Beschwerden mit weiteren Einzelheiten"
    assert record["_kienzlefon"]["errors"] == []
    assert [entry["status"] for entry in record["_kienzlefon"]["audio"]] == [
        "empty",
        "empty",
        "empty",
        "empty",
        "transcribed",
    ]
    assert (app_config.telepraxis.output_directory / f"{call.call_id}.json.enc").is_file()
    assert not list(app_config.telepraxis.output_directory.glob("*_error_*.json.enc"))


def test_output_failure_marks_worker_unready_and_keeps_call(app_config) -> None:
    spool = Spool(app_config.paths.spool, app_config.practice.timezone)
    call = spool.create_call(CallType.APPOINTMENT, "+4923311234", "termin")
    reason = call.begin_audio(FieldName.REASON, "grund.wav")
    reason.write_bytes(b"RIFF" + b"0" * 100)
    spool.finish_recording(call, "abgeschlossen")
    claimed = spool.claim_next()
    assert claimed is not None
    worker = Worker(app_config, transcriber=FakeTranscriber())

    def fail_output(_payload, _basename):
        raise EncryptionError("Ausgabeverzeichnis nicht erreichbar")

    worker.encryptor.write_payload = fail_output
    worker.process(WorkingCall(claimed.path, app_config.practice.timezone))
    assert len(tuple(spool.calls(CallState.QUEUE))) == 1
    health = (app_config.paths.runtime / "whisper-health.json").read_text(encoding="utf-8")
    assert '"ready": false' in health


def test_faster_whisper_routes_fields_and_loads_unique_models_once(app_config) -> None:
    created: list[FakeWhisperModel] = []

    class FakeWhisperModel:
        def __init__(self, model_name: str, **options) -> None:
            self.model_name = model_name
            self.options = options
            self.calls: list[dict] = []
            created.append(self)

        def transcribe(self, path: str, **options):
            self.calls.append({"path": path, **options})
            return [SimpleNamespace(text=" Ergebnis. ")], None

    transcriber = FasterWhisperTranscriber(app_config, model_factory=FakeWhisperModel)
    audio = app_config.paths.spool / "feld.wav"

    assert transcriber.transcribe(audio, FieldName.FIRST_NAME) == "Ergebnis."
    assert transcriber.transcribe(audio, FieldName.LAST_NAME) == "Ergebnis."
    assert transcriber.transcribe(audio, FieldName.MEDICATION) == "Ergebnis."
    assert transcriber.transcribe(audio, FieldName.CONCERN) == "Ergebnis."

    assert [model.model_name for model in created] == ["large-v3-turbo", "large-v3"]
    models = {model.model_name: model for model in created}
    assert len(models["large-v3"].calls) == 2
    assert len(models["large-v3-turbo"].calls) == 2
    first_name_call = models["large-v3"].calls[0]
    last_name_call = models["large-v3"].calls[1]
    medication_call = models["large-v3-turbo"].calls[0]
    assert first_name_call["language"] == "de"
    assert first_name_call["task"] == "transcribe"
    assert first_name_call["beam_size"] == 5
    assert first_name_call["initial_prompt"] == (
        "Es folgt ausschließlich der Vorname einer Person."
    )
    assert last_name_call["initial_prompt"] == (
        "Es folgt ausschließlich der Familienname einer Person."
    )
    assert medication_call["initial_prompt"] == (
        "Es folgt eine Medikamentenangabe mit Medikamentenname oder Wirkstoff, "
        "Wirkstärke und Packungsgröße."
    )
    assert models["large-v3-turbo"].calls[1]["initial_prompt"] is None
