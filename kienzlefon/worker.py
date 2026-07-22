# kienzlefon
# Version: 1.9.3
# Changelog:
# - 1.9.3: Vollstaendig inhaltslose fehlerfreie Vorgaenge ohne Telepraxis-Datei abgeschlossen.
# - 1.9: Konfigurierte Demo-Anonymisierung an die Dateiausgabe uebergeben.
# - 1.8.3: Leere Einzeltranskripte uebersprungen, ohne spaetere Felder zu blockieren.
# - 1.8: Konfigurierten Telepraxis-Demomodus an die Dateiausgabe angebunden.
# - 1.6: Feldabhaengige Whisper-Modelle und Initial-Prompts dauerhaft geladen.
# - 1.1: Einen von Whisper angehaengten abschliessenden Punkt entfernen.
# - 1.0: Dauerhaft geladener faster-whisper-Worker mit Heartbeat und Wiederanlauf.

from __future__ import annotations

import fcntl
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any, Protocol

from .config import AppConfig
from .crypto import EncryptionError, TelepraxisEncryptor
from .errors import record_system_error, report_call_errors
from .health import Heartbeat
from .models import AudioStatus, CallState, FieldName
from .spool import Spool, WorkingCall

LOGGER = logging.getLogger(__name__)


def clean_transcript(value: str) -> str:
    text = value.strip()
    if text.endswith("."):
        text = text[:-1].rstrip()
    return text


class Transcriber(Protocol):
    def transcribe(self, path: Path, field: FieldName | str) -> str: ...


class FasterWhisperTranscriber:
    def __init__(self, config: AppConfig, model_factory: Any | None = None):
        if model_factory is None:
            from faster_whisper import WhisperModel

            model_factory = WhisperModel

        config.whisper.model_directory.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.models = {
            model_name: model_factory(
                model_name,
                device=config.whisper.device,
                compute_type=config.whisper.compute_type,
                cpu_threads=config.whisper.cpu_threads,
                num_workers=1,
                download_root=str(config.whisper.model_directory),
                local_files_only=True,
            )
            for model_name in config.whisper.models
        }

    def transcribe(self, path: Path, field: FieldName | str) -> str:
        model_name = self.config.whisper.model_for(field)
        field_value = field.value if isinstance(field, FieldName) else str(field)
        beam_size = (
            5
            if field_value in {FieldName.FIRST_NAME.value, FieldName.LAST_NAME.value}
            else self.config.whisper.beam_size
        )
        segments, _ = self.models[model_name].transcribe(
            str(path),
            language=self.config.whisper.language,
            task="transcribe",
            beam_size=beam_size,
            initial_prompt=self.config.whisper.initial_prompt_for(field),
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()


class Worker:
    def __init__(self, config: AppConfig, transcriber: Transcriber | None = None):
        self.config = config
        self.spool = Spool(config.paths.spool, config.practice.timezone)
        self.encryptor = TelepraxisEncryptor(
            config.telepraxis.public_key,
            config.telepraxis.output_directory,
            config.practice.timezone,
            demo_mode=config.telepraxis.demo,
            anonymize_phone_numbers=config.telepraxis.anonymize_phone_numbers,
        )
        self.transcriber = transcriber
        self.stop_event = threading.Event()
        self.heartbeat = Heartbeat(
            config.paths.runtime / "whisper-health.json",
            config.whisper.models,
            config.whisper.heartbeat_seconds,
        )
        self._lock_handle: Any = None

    def run(self) -> None:
        self.spool.initialize()
        self.config.paths.runtime.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        self._install_signal_handlers()
        self.heartbeat.start()
        try:
            recovered = self.spool.recover_processing()
            recovered += self.spool.recover_stale_recordings(self.config.recording.stale_seconds)
            if recovered:
                LOGGER.warning("%d nicht abgeschlossene Vorgaenge wiederhergestellt", recovered)
            self.flush_error_reports()
            if self.transcriber is None:
                self.transcriber = FasterWhisperTranscriber(self.config)
            self.heartbeat.set_ready(True)
            LOGGER.info(
                "Whisper-Modelle %s sind dauerhaft geladen",
                ", ".join(self.config.whisper.models),
            )
            while not self.stop_event.is_set():
                claimed = self.spool.claim_next()
                if claimed is None:
                    self.flush_error_reports()
                    self.stop_event.wait(self.config.whisper.poll_seconds)
                    continue
                self.process(WorkingCall(claimed.path, self.config.practice.timezone))
        except Exception as exc:
            self.heartbeat.set_ready(False, str(exc))
            record_system_error(
                self.config,
                code="WORKER_FATAL",
                phase="worker",
                message=str(exc),
            )
            raise
        finally:
            self.heartbeat.stop()
            self._release_lock()

    def process(self, call: WorkingCall) -> None:
        try:
            record = call.load()
            for entry in record["_kienzlefon"]["audio"]:
                if entry.get("status") == AudioStatus.TRANSCRIBED.value:
                    continue
                if entry.get("transkribieren") is False:
                    continue
                entry["versuche"] = int(entry.get("versuche", 0)) + 1
                call.save(record)
                audio_path = call.path / str(entry["datei"])
                if not audio_path.is_file() or audio_path.stat().st_size <= 44:
                    raise RuntimeError(f"Aufnahmedatei fehlt oder ist leer: {entry['datei']}")
                assert self.transcriber is not None
                transcript = clean_transcript(
                    self.transcriber.transcribe(audio_path, str(entry["feld"]))
                )
                if not transcript:
                    entry["status"] = AudioStatus.EMPTY.value
                    entry["transkribieren"] = False
                    entry.pop("fehler", None)
                    call.save(record)
                    continue
                entry["transkript"] = transcript
                entry["status"] = AudioStatus.TRANSCRIBED.value
                entry.pop("fehler", None)
                self._apply_transcripts(record)
                call.save(record)

            self._apply_transcripts(record)
            call.save(record)
            if not record["_kienzlefon"]["errors"] and not self._has_transcribed_content(record):
                self.spool.transition(call, CallState.READY)
                self.heartbeat.set_ready(True)
                LOGGER.info(
                    "Vorgang %s ohne erkannten Inhalt ohne Telepraxis-Ausgabe abgeschlossen",
                    call.call_id,
                )
                return
            report_call_errors(call, self.encryptor)
            self.encryptor.write_payload(record, call.call_id)
            self.spool.transition(call, CallState.READY)
            self.heartbeat.set_ready(True)
            output_kind = "unverschluesselt ausgegeben" if self.config.telepraxis.demo else "verschluesselt ausgegeben"
            LOGGER.info("Vorgang %s transkribiert und %s", call.call_id, output_kind)
        except Exception as exc:
            self._handle_failure(call, exc)

    def _handle_failure(self, call: WorkingCall, exc: Exception) -> None:
        LOGGER.exception("Verarbeitung von %s fehlgeschlagen", call.call_id)
        try:
            record = call.load()
            current = next(
                (
                    entry
                    for entry in record["_kienzlefon"]["audio"]
                    if entry.get("status") != AudioStatus.TRANSCRIBED.value
                    and entry.get("transkribieren") is not False
                ),
                None,
            )
            if current is None:
                record["_kienzlefon"]["ausgabe_versuche"] = (
                    int(record["_kienzlefon"].get("ausgabe_versuche", 0)) + 1
                )
                call.save(record)
            attempts = (
                int(current.get("versuche", 0))
                if current
                else int(record["_kienzlefon"]["ausgabe_versuche"])
            )
            if current is not None:
                current["status"] = AudioStatus.ERROR.value
                current["fehler"] = str(exc)
                call.save(record)
            if isinstance(exc, EncryptionError):
                call.add_error("OUTPUT_FAILED", "dateiausgabe", str(exc))
                self.heartbeat.set_ready(False, str(exc))
            else:
                call.add_error("TRANSCRIPTION_FAILED", "transkription", str(exc))
            try:
                report_call_errors(call, self.encryptor)
            except Exception as report_exc:
                call.add_error("ERROR_OUTPUT_FAILED", "dateiausgabe", str(report_exc))

            if attempts < self.config.whisper.max_attempts or isinstance(exc, EncryptionError):
                if current is not None:
                    record = call.load()
                    current = next(
                        entry
                        for entry in record["_kienzlefon"]["audio"]
                        if entry.get("status") == AudioStatus.ERROR.value
                    )
                    current["status"] = AudioStatus.RECORDED.value
                    call.save(record)
                self.spool.transition(call, CallState.QUEUE)
                return

            record = call.load()
            self._apply_transcripts(record)
            call.save(record)
            report_call_errors(call, self.encryptor)
            self.encryptor.write_payload(record, call.call_id)
            self.spool.transition(call, CallState.ERROR)
        except Exception:
            LOGGER.exception(
                "Fehlerzustand fuer %s konnte noch nicht abgeschlossen werden", call.call_id
            )
            if call.path.parent.name == CallState.PROCESSING.value:
                try:
                    self.spool.transition(call, CallState.QUEUE)
                except Exception:
                    LOGGER.exception(
                        "Vorgang %s konnte nicht erneut eingereiht werden", call.call_id
                    )

    @staticmethod
    def _has_transcribed_content(record: dict[str, Any]) -> bool:
        return any(
            entry.get("status") == AudioStatus.TRANSCRIBED.value
            and bool(clean_transcript(str(entry.get("transkript", ""))))
            for entry in record["_kienzlefon"]["audio"]
        )

    @staticmethod
    def _apply_transcripts(record: dict[str, Any]) -> None:
        medications: list[tuple[int, str]] = []
        for entry in record["_kienzlefon"]["audio"]:
            if entry.get("status") != AudioStatus.TRANSCRIBED.value:
                continue
            transcript = clean_transcript(str(entry.get("transkript", "")))
            entry["transkript"] = transcript
            field = str(entry["feld"])
            if field == FieldName.MEDICATION.value:
                medications.append((int(entry.get("index", len(medications) + 1)), transcript))
            elif field in record:
                record[field] = transcript
        if medications:
            record[FieldName.MEDICATION.value] = "\n".join(text for _, text in sorted(medications))

    def flush_error_reports(self) -> None:
        for call in self.spool.calls(CallState.ERROR):
            try:
                report_call_errors(call, self.encryptor)
            except Exception:
                LOGGER.exception(
                    "Offene Fehlermeldung %s bleibt fuer spaeter erhalten", call.call_id
                )

    def _acquire_lock(self) -> None:
        path = self.config.paths.runtime / "worker.lock"
        self._lock_handle = path.open("w", encoding="ascii")
        try:
            fcntl.flock(self._lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Ein anderer Kienzlefon-Worker laeuft bereits") from exc
        self._lock_handle.write(f"{os.getpid()}\n")
        self._lock_handle.flush()

    def _release_lock(self) -> None:
        if self._lock_handle is not None:
            fcntl.flock(self._lock_handle, fcntl.LOCK_UN)
            self._lock_handle.close()
            self._lock_handle = None

    def _install_signal_handlers(self) -> None:
        def stop(_signum: int, _frame: Any) -> None:
            self.stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
