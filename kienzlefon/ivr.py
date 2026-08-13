# kienzlefon
# Version: 2.0
# Changelog:
# - 2.0: Neue Aufnahmen waehrend der Qwen3-TTS-Wartungsphase sicher gesperrt.
# - 1.8.3: Alle Felder trotz Schweigens weiter aufgenommen und einzeln verarbeitet.
# - 1.8: Abbruch vor jeder verwertbaren Aufnahme ohne leeren Vorgang abgeschlossen.
# - 1.7: Anzeige-Caller-ID normalisiert, waehrend die Telepraxis-ID original bleibt.
# - 1.6: Whisper-Bereitschaft gegen alle konfigurierten Modelle geprueft.
# - 1.1: Menueeinleitung, tastensichere Ansagepausen und Abschlussansage ergaenzt.
# - 1.0: Freigegebener IVR-Ablauf mit strukturierten Einzelaufnahmen umgesetzt.

from __future__ import annotations

import fcntl
import logging
from pathlib import Path

from .agi import AgiChannel, AgiHangup
from .config import AppConfig, caller_id_or_none
from .dialing import normalize_incoming_caller_id
from .errors import record_system_error
from .health import worker_is_healthy
from .models import CallType, FieldName
from .spool import Spool, WorkingCall

LOGGER = logging.getLogger(__name__)
ALL_DIGITS = "0123456789*#"


class IVR:
    def __init__(self, config: AppConfig, channel: AgiChannel):
        self.config = config
        self.channel = channel
        self.spool = Spool(config.paths.spool, config.practice.timezone)
        self.call: WorkingCall | None = None
        self.call_queued = False
        self.caller_id = caller_id_or_none(channel.environment.get("agi_callerid"))

    def run(self) -> None:
        try:
            displayed_caller_id = normalize_incoming_caller_id(
                self.caller_id,
                self.config.dial_rules.country_code,
                self.config.local_extensions,
            )
            if displayed_caller_id is not None:
                self.channel.set_variable("CALLERID(num)", displayed_caller_id)
            if not self._worker_healthy():
                self._play("whisper_failure")
                self._goto_queue()
                return
            digit = self._opening_sequence()
            attempts = 0
            while attempts < self.config.ivr.attempts:
                digit = digit or self._main_menu()
                if digit is None:
                    attempts += 1
                    continue
                if digit == "6":
                    self._play("opening_hours")
                    digit = None
                    continue
                if self._handle_menu_digit(digit):
                    return
                self._play("invalid")
                digit = None
                attempts += 1

            if self.config.phone_is_open():
                self._play("no_selection_open")
                self._goto_queue()
            else:
                self._record_closed_fallback()
        except AgiHangup:
            LOGGER.info("Anrufer hat aufgelegt")
        except Exception as exc:
            LOGGER.exception("IVR-Fehler")
            if self.call is not None:
                self.call.add_error("IVR_ERROR", "ivr", str(exc))
            else:
                record_system_error(
                    self.config,
                    code="IVR_ERROR",
                    phase="ivr",
                    message=str(exc),
                    caller_id=self.caller_id,
                )
        finally:
            self._queue_partial_call()

    def _opening_sequence(self) -> str | None:
        current_override = self.config.current_override()
        override_active = current_override is not None
        forced_closed = override_active and current_override.block_phone_hours
        greeting = (
            "greeting_open"
            if self.config.practice_is_open() and not forced_closed
            else "greeting_closed"
        )
        if not override_active:
            opening_prompts = (greeting,)
        elif current_override.position == "statt_begruessung":
            opening_prompts = (current_override.prompt_name,)
        elif current_override.position == "vor_begruessung":
            opening_prompts = (current_override.prompt_name, greeting)
        else:
            opening_prompts = (greeting, current_override.prompt_name)
        for prompt in opening_prompts:
            digit = self._stream(prompt, ALL_DIGITS)
            if digit:
                return digit
        digit = self._stream("emergency", ALL_DIGITS)
        if digit:
            return digit
        urgent_help_required = self.config.urgent_help_is_active() or (
            override_active and current_override.block_phone_hours
        )
        if urgent_help_required:
            return self._stream("urgent_help", ALL_DIGITS)
        return None

    def _main_menu(self) -> str | None:
        open_now = self.config.phone_is_open()
        digit = self._stream("menu_intro", ALL_DIGITS)
        if digit:
            return digit
        key = "menu_open" if open_now else "menu_closed"
        digit = self._stream(key, ALL_DIGITS)
        if digit:
            return digit
        digit = self._stream("opening_hours_choice", ALL_DIGITS)
        if digit:
            return digit
        if self.config.pharmacy_is_available():
            digit = self._stream("pharmacy_access", ALL_DIGITS)
            if digit:
                return digit
        if self.config.specialist_is_available():
            digit = self._stream("specialist_access", ALL_DIGITS)
            if digit:
                return digit
        current_override = self.config.current_override()
        if not open_now and not (
            current_override is not None and current_override.block_phone_hours
        ):
            digit = self._stream("phone_hours", ALL_DIGITS)
            if digit:
                return digit
        return self._wait_for_digit()

    def _handle_menu_digit(self, digit: str) -> bool:
        if digit == "1" and self.config.phone_is_open():
            self._goto_queue()
            return True
        if digit == "2":
            self._record_structured(CallType.PRESCRIPTION, "rezept")
            return True
        if digit == "3":
            self._record_structured(CallType.REFERRAL, "ueberweisung")
            return True
        if digit == "4":
            self._record_structured(CallType.APPOINTMENT, "termin")
            return True
        if digit == "5":
            return self._submenu_five()
        if digit == "8" and self.config.pharmacy_is_available():
            self.channel.goto("kienzlefon-pharmacy-queue,s,1")
            return True
        if digit == "9" and self.config.specialist_is_available():
            self.channel.goto("kienzlefon-specialist,s,1")
            return True
        return False

    def _submenu_five(self) -> bool:
        for _ in range(self.config.ivr.attempts):
            digit = self.channel.get_option(
                self._prompt("submenu_five"), "12", self.config.ivr.digit_timeout_ms
            )
            if digit == "1":
                self._record_structured(CallType.CALLBACK_DETAILS, "rueckruf")
                return True
            if digit == "2":
                self._record_structured(CallType.OTHER, "sonstiges")
                return True
            if digit is not None:
                self._play("invalid")
        if self.config.phone_is_open():
            self._play("no_selection_open")
            self._goto_queue()
        else:
            self._record_closed_fallback()
        return True

    def _record_structured(self, call_type: CallType, category: str) -> None:
        self.call = self._create_call_if_admitted(call_type, category)
        if self.call is None:
            self._play("whisper_failure")
            self._goto_queue()
            return
        self._play("recording_hint")
        for field, prompt, filename in (
            (FieldName.FIRST_NAME, "first_name", "vorname.wav"),
            (FieldName.LAST_NAME, "last_name", "nachname.wav"),
            (FieldName.BIRTH_DATE, "birth_date", "geburtsdatum.wav"),
        ):
            self._record_field(field, prompt, filename, long=False)

        if self.caller_id is None:
            self._record_field(
                FieldName.CALLBACK_NUMBER,
                "callback_number",
                "telefon.wav",
                long=False,
            )

        if call_type is CallType.PRESCRIPTION:
            self._record_medications()
            self._play("prescription_information")
        elif call_type is CallType.REFERRAL:
            self._record_field(FieldName.SPECIALTY, "specialty", "fachrichtung.wav", long=True)
            self._record_field(FieldName.REASON, "referral_reason", "grund.wav", long=True)
        elif call_type is CallType.APPOINTMENT:
            self._record_field(FieldName.REASON, "appointment", "grund.wav", long=True)
        elif call_type is CallType.CALLBACK_DETAILS:
            self._record_field(FieldName.REASON, "callback_reason", "grund.wav", long=True)
        elif call_type is CallType.OTHER:
            self._record_field(FieldName.CONCERN, "other", "anliegen.wav", long=True)

        self._play("completed")
        self._finish_call("abgeschlossen")

    def _record_closed_fallback(self) -> None:
        self.call = self._create_call_if_admitted(
            CallType.CALLBACK_FALLBACK,
            "rueckruf_ohne_tastenauswahl",
        )
        if self.call is None:
            self._play("whisper_failure")
            self._goto_queue()
            return
        self._record_field(
            FieldName.REASON,
            "no_selection_closed",
            "grund.wav",
            long=True,
        )
        self._play("completed")
        self._finish_call("stille_oder_auflegen")

    def _record_medications(self) -> None:
        index = 1
        while True:
            prompt = "first_medication" if index == 1 else "next_medication"
            if not self._record_field(
                FieldName.MEDICATION,
                prompt,
                f"medikament-{index:02d}.wav",
                long=False,
                index=index,
            ):
                return
            digit = self.channel.get_option(
                self._prompt("medication_choice"), "12", self.config.ivr.digit_timeout_ms
            )
            if digit != "1":
                return
            index += 1

    def _record_field(
        self,
        field: FieldName,
        prompt: str,
        filename: str,
        *,
        long: bool,
        index: int | None = None,
    ) -> bool:
        assert self.call is not None
        self._play(prompt)
        audio_path = self.call.begin_audio(field, filename, index)
        result = self.channel.record(
            audio_path,
            silence_seconds=(
                self.config.recording.long_silence_seconds
                if long
                else self.config.recording.short_silence_seconds
            ),
            max_seconds=(
                self.config.recording.long_max_seconds
                if long
                else self.config.recording.short_max_seconds
            ),
        )
        self.call.set_audio_record_status(filename, result.status, result.present)
        if result.status == "ERROR":
            self.call.add_error(
                "RECORDING_FAILED", "aufnahme", f"Aufnahme fehlgeschlagen: {filename}"
            )
            return False
        return result.present

    def _finish_call(self, reason: str) -> None:
        if self.call is None or self.call_queued:
            return
        self.call = self.spool.finish_recording(self.call, reason)
        self.call_queued = True

    def _queue_partial_call(self) -> None:
        if self.call is None or self.call_queued:
            return
        try:
            record = self.call.load()
            if not record["_kienzlefon"]["errors"] and not self.call.has_usable_audio():
                call_id = self.call.call_id
                self.spool.discard_empty_recording(self.call)
                self.call = None
                self.call_queued = True
                LOGGER.info("Leeren abgebrochenen Vorgang %s verworfen", call_id)
                return
            self._finish_call("aufgelegt_oder_abgebrochen")
        except Exception as exc:
            LOGGER.exception("Teilaufnahme %s konnte nicht eingereiht werden", self.call.call_id)
            try:
                self.call.add_error("QUEUE_FAILED", "warteschlange", str(exc))
            except Exception:
                LOGGER.exception("Fehler konnte nicht mehr in call.json geschrieben werden")

    def _worker_healthy(self) -> bool:
        if any(
            (self.config.paths.runtime / marker).exists()
            for marker in ("asr-maintenance", "tts-maintenance")
        ):
            return False
        return worker_is_healthy(
            self.config.paths.runtime / "whisper-health.json",
            self.config.whisper.models,
            self.config.whisper.stale_heartbeat_seconds,
        )

    def _create_call_if_admitted(
        self, call_type: CallType, category: str
    ) -> WorkingCall | None:
        """Prueft Bereitschaft und legt den Auftrag unter derselben Sperre an."""
        self.config.paths.runtime.mkdir(parents=True, exist_ok=True)
        lock_path = self.config.paths.runtime / "asr-admission.lock"
        with lock_path.open("a+b") as admission_lock:
            fcntl.flock(admission_lock.fileno(), fcntl.LOCK_SH)
            if not self._worker_healthy():
                return None
            return self.spool.create_call(call_type, self.caller_id, category)

    def _goto_queue(self) -> None:
        self.channel.goto(self.config.ivr.queue_context)

    def _prompt(self, key: str) -> Path:
        return self.config.paths.prompts / key

    def _play(self, key: str) -> None:
        self.channel.stream_file(self._prompt(key))

    def _stream(self, key: str, digits: str) -> str | None:
        digit = self.channel.stream_file(self._prompt(key), digits)
        if digit or self.config.ivr.announcement_pause_ms == 0:
            return digit
        response = self.channel.command(f"WAIT FOR DIGIT {self.config.ivr.announcement_pause_ms}")
        if response.result <= 0:
            return None
        digit = chr(response.result)
        return digit if digit in digits else None

    def _wait_for_digit(self) -> str | None:
        response = self.channel.command(f"WAIT FOR DIGIT {self.config.ivr.digit_timeout_ms}")
        return chr(response.result) if response.result > 0 else None
