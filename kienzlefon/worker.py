# kienzlefon
# Version: 2.0
# Changelog:
# - 2.0: Neue ASR-Auftraege waehrend der Qwen3-TTS-Wartungsphase angehalten.
# - 1.9.3: Vollstaendig inhaltslose fehlerfreie Vorgaenge ohne Telepraxis-Datei abgeschlossen.
# - 1.9: Konfigurierte Demo-Anonymisierung an die Dateiausgabe uebergeben.
# - 1.8.3: Leere Einzeltranskripte uebersprungen, ohne spaetere Felder zu blockieren.
# - 1.8: Konfigurierten Telepraxis-Demomodus an die Dateiausgabe angebunden.
# - 1.6: Feldabhaengige Whisper-Modelle und Initial-Prompts dauerhaft geladen.
# - 1.1: Einen von Whisper angehaengten abschliessenden Punkt entfernen.
# - 1.0: Dauerhaft geladener faster-whisper-Worker mit Heartbeat und Wiederanlauf.

from __future__ import annotations

import fcntl
import http.client
import json
import logging
import os
import re
import signal
import threading
import time
from uuid import uuid4
from pathlib import Path
from typing import Any, Protocol

from .ai_import import import_next_case
from .config import AppConfig
from .crypto import EncryptionError, TelepraxisEncryptor
from .delivery import Delivery
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
                device="cpu" if config.whisper.commander_ip else config.whisper.device,
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


class CommanderTranscriber:
    def __init__(self, config: AppConfig, fallback: Transcriber):
        self.settings = config.whisper
        self.fallback = fallback
        self.retry_at = 0.0

    def transcribe(self, path: Path, field: FieldName | str) -> str:
        if time.monotonic() >= self.retry_at:
            try:
                return self._transcribe(path)
            except (OSError, ValueError, http.client.HTTPException) as exc:
                self.retry_at = time.monotonic() + 30
                LOGGER.warning("Commander-ASR nicht nutzbar (%s), CPU-Whisper aktiv",
                               type(exc).__name__)
        return self.fallback.transcribe(path, field)

    def _transcribe(self, path: Path) -> str:
        limit = 32 * 1024 * 1024
        with path.open("rb") as handle:
            audio = handle.read(limit + 1)
        if len(audio) > limit:
            raise ValueError("Commander-Audio zu gross")
        request_id = uuid4().hex
        boundary = f"kienzlefon-{request_id}"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n'
            f'{self.settings.language}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            'Content-Type: audio/wav\r\n\r\n'
        ).encode() + audio + f"\r\n--{boundary}--\r\n".encode()
        connection = http.client.HTTPConnection(
            self.settings.commander_ip, 8185, timeout=self.settings.commander_timeout,
        )
        try:
            connection.request("POST", "/v1/asr/final-block", body, {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Idempotency-Key": request_id,
            })
            with connection.getresponse() as response:
                if response.status != 200:
                    raise ValueError("Commander-Antwortstatus")
                maximum_response_bytes = 1024 * 1024
                raw = response.read(maximum_response_bytes + 1)
            if len(raw) > maximum_response_bytes:
                raise ValueError("Commander-Antwort zu gross")
            payload = json.loads(raw)
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Commander-Antwort ohne Text")
            return text.strip()
        finally:
            connection.close()


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
        self.delivery = Delivery(self.encryptor)
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
                local = FasterWhisperTranscriber(self.config)
                self.transcriber = (
                    CommanderTranscriber(self.config, local)
                    if self.config.whisper.commander_ip else local
                )
            self.heartbeat.set_ready(True)
            LOGGER.info(
                "Whisper-Modelle %s sind dauerhaft geladen",
                ", ".join(self.config.whisper.models),
            )
            next_receipt_poll = 0.0
            while not self.stop_event.is_set():
                if time.monotonic() >= next_receipt_poll:
                    self._poll_delivery_receipts()
                    if self.config.ai_integration.result_directory is not None:
                        try:
                            import_next_case(self.config.ai_integration.result_directory, self.config)
                        except OSError:
                            LOGGER.warning("Das KI-Ergebnisverzeichnis ist derzeit nicht lesbar.")
                    next_receipt_poll = time.monotonic() + 5
                claimed = self._claim_next_if_admitted()
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

    def _maintenance_active(self) -> bool:
        return any(
            (self.config.paths.runtime / marker).exists()
            for marker in ("asr-maintenance", "tts-maintenance")
        )

    def _claim_next_if_admitted(self) -> WorkingCall | None:
        """Verhindert einen neuen ASR-Start waehrend Wartung eingeleitet wird."""
        lock_path = self.config.paths.runtime / "asr-admission.lock"
        with lock_path.open("a+b") as admission_lock:
            fcntl.flock(admission_lock.fileno(), fcntl.LOCK_SH)
            if self._maintenance_active():
                return None
            claimed = self.spool.claim_next()
            if claimed is not None and self._maintenance_active():
                self.spool.transition(
                    WorkingCall(claimed.path, self.config.practice.timezone),
                    CallState.QUEUE,
                )
                return None
            return claimed

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
                if self.config.telepraxis.attach_audio is not None:
                    self.delivery.remove_source_audio(call)
                self.spool.transition(call, CallState.READY)
                self.heartbeat.set_ready(True)
                LOGGER.info(
                    "Vorgang %s ohne erkannten Inhalt ohne Telepraxis-Ausgabe abgeschlossen",
                    call.call_id,
                )
                return
            report_call_errors(call, self.encryptor)
            self._publish(call, record)
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
            self._publish(call, record)
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

    def _publish(self, call: WorkingCall, record: dict[str, Any]) -> None:
        attach = self.config.telepraxis.attach_audio
        if attach is None:
            self.encryptor.write_payload(record, call.call_id)
        else:
            self.delivery.publish(call, record, attach=attach)

    def _poll_delivery_receipts(self) -> None:
        for state in (CallState.READY, CallState.ERROR):
            for call in self.spool.calls(state):
                try:
                    self.delivery.receive_ack(call)
                except (OSError, ValueError, KeyError, EncryptionError):
                    LOGGER.exception("Zustellung für %s konnte noch nicht abgeglichen werden", call.call_id)

    @staticmethod
    def _apply_transcripts(record: dict[str, Any]) -> None:
        multiple = record.get("typ") == "mehrere_anliegen"
        concerns: dict[str, dict[str, Any]] = {}
        duplicates: set[str] = set()
        if multiple and record.get("anliegen_schema_version") == 1:
            items = record.get("anliegen_liste")
            if isinstance(items, list):
                for item in items:
                    identifier = item.get("anliegen_id") if isinstance(item, dict) else None
                    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier):
                        continue
                    if identifier in concerns:
                        duplicates.add(identifier)
                    concerns[identifier] = item
        medications: dict[str | None, list[tuple[int, str]]] = {}
        for entry in record["_kienzlefon"]["audio"]:
            if entry.get("status") != AudioStatus.TRANSCRIBED.value:
                continue
            transcript = clean_transcript(str(entry.get("transkript", "")))
            entry["transkript"] = transcript
            field = str(entry["feld"])
            identifier = entry.get("anliegen_id")
            if identifier is not None and (
                not isinstance(identifier, str) or identifier not in concerns or identifier in duplicates
            ):
                continue
            target = concerns[identifier] if identifier is not None else record
            if field == FieldName.MEDICATION.value:
                if multiple and identifier is None:
                    continue
                lines = medications.setdefault(identifier, [])
                lines.append((int(entry.get("index", len(lines) + 1)), transcript))
            elif field in target:
                target[field] = transcript
        for identifier, lines in medications.items():
            target = concerns[identifier] if identifier is not None else record
            target[FieldName.MEDICATION.value] = "\n".join(text for _, text in sorted(lines))

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
