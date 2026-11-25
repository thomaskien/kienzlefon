# kienzlefon
# Version: 2.4.0
# Changelog:
# - 2.4.0: Ansagenmodi und lautlosen AI-Shortcut aus dem Hauptmenue umgesetzt.
# - 2.3.2: Bestandteil des Kienzlefon-Release 2.3.2.
# - 2.3.1: Fehlende DTMF-Eingaben in Eingangs- und Menuephase sicher behandelt.
# - 2.3: Eingangsansagen und klassischen Menuepfad fuer AI-Admission getrennt.
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
from .statistics import emit_agi_route

LOGGER = logging.getLogger(__name__)
ALL_DIGITS = "0123456789*#"
DIRECT_CONCERNS = {
    "rezept": CallType.PRESCRIPTION,
    "ueberweisung": CallType.REFERRAL,
    "termin": CallType.APPOINTMENT,
}
OTHER_CONCERNS = {"rueckruf": CallType.CALLBACK_DETAILS, "sonstiges": CallType.OTHER}
CONCERN_ROUTES = {
    CallType.PRESCRIPTION: "prescription",
    CallType.REFERRAL: "referral",
    CallType.APPOINTMENT: "appointment",
    CallType.CALLBACK_DETAILS: "callback",
    CallType.CALLBACK_FALLBACK: "callback",
    CallType.OTHER: "other",
}


class IVR:
    def __init__(self, config: AppConfig, channel: AgiChannel):
        self.config = config
        self.channel = channel
        self.spool = Spool(config.paths.spool, config.practice.timezone)
        self.call: WorkingCall | None = None
        self.call_queued = False
        self.caller_id = caller_id_or_none(channel.environment.get("agi_callerid"))

    def run(self) -> None:
        self._run_menu_flow(include_opening=True)

    def run_opening(self) -> None:
        try:
            self.channel.set_variable("KZF_IVR_OPENING_OK", "0")
            self.channel.set_variable("KZF_IVR_INITIAL_DIGIT", "none")
            self._prepare_caller_id()
            digit = self._opening_sequence()
            if digit is not None and digit in ALL_DIGITS:
                self.channel.set_variable("KZF_IVR_INITIAL_DIGIT", digit)
            self.channel.set_variable("KZF_IVR_OPENING_OK", "1")
        except AgiHangup:
            LOGGER.info("Anrufer hat waehrend der Eingangsansagen aufgelegt")
        except Exception as exc:
            LOGGER.exception("Fehler in den Eingangsansagen")
            record_system_error(
                self.config,
                code="IVR_OPENING_ERROR",
                phase="ivr",
                message=str(exc),
                caller_id=self.caller_id,
            )

    def run_menu(self, initial_digit: str | None = None) -> None:
        self.channel.set_variable("KZF_IVR_AI_REQUESTED", "0")
        digit = (
            initial_digit
            if initial_digit is not None and initial_digit in ALL_DIGITS
            else None
        )
        self._run_menu_flow(include_opening=False, initial_digit=digit)

    def _prepare_caller_id(self) -> None:
        displayed_caller_id = normalize_incoming_caller_id(
            self.caller_id,
            self.config.dial_rules.country_code,
            self.config.local_extensions,
        )
        if displayed_caller_id is not None:
            self.channel.set_variable("CALLERID(num)", displayed_caller_id)

    def _run_menu_flow(
        self, *, include_opening: bool, initial_digit: str | None = None
    ) -> None:
        try:
            self._prepare_caller_id()
            digit = self._opening_sequence() if include_opening else initial_digit
            if not self._worker_healthy():
                self._play("whisper_failure")
                self._goto_queue()
                return
            attempts = 0
            while attempts < self.config.ivr.attempts:
                digit = digit or self._main_menu()
                if digit is None:
                    attempts += 1
                    continue
                if digit == self.config.ivr_keys["oeffnungszeiten"]:
                    self._stat_route("opening_hours")
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
        effective_practice_open = self.config.practice_is_open() and not forced_closed
        greeting = (
            "greeting_open"
            if effective_practice_open
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
            digit = self._stream(
                prompt,
                ALL_DIGITS,
                practice_open=(
                    effective_practice_open
                    if prompt in {"greeting_open", "greeting_closed"}
                    else None
                ),
            )
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
        override = self.config.current_override()
        for name in self.config.menu_order:
            if name == ("menu_closed" if open_now else "menu_open"):
                continue
            if name == "opening_hours_choice" and not self.config.ivr_keys["oeffnungszeiten"]:
                continue
            if name == "pharmacy_access" and not (self.config.ivr_keys["apotheke"] and self.config.pharmacy_is_available()):
                continue
            if name == "specialist_access" and not (self.config.ivr_keys["rot"] and self.config.specialist_is_available()):
                continue
            if name == "phone_hours" and (open_now or (override and override.block_phone_hours)):
                continue
            digit = self._stream(name, ALL_DIGITS)
            if digit:
                return digit
        return self._wait_for_digit()

    def _handle_menu_digit(self, digit: str) -> bool:
        keys = self.config.ivr_keys
        if digit == keys["ki"]:
            self.channel.set_variable("KZF_IVR_AI_REQUESTED", "1")
            return True
        if digit == keys["praxis"] and self.config.phone_is_open():
            self._goto_queue()
            return True
        for action, call_type in DIRECT_CONCERNS.items():
            if digit == keys[action]:
                self._record_structured(call_type, action)
                return True
        if digit == keys["weitere"]:
            return self._submenu_five()
        if digit == keys["apotheke"] and self.config.pharmacy_is_available():
            self.channel.goto("kienzlefon-pharmacy-queue,s,1")
            return True
        if digit == keys["rot"] and self.config.specialist_is_available():
            self.channel.goto("kienzlefon-specialist,s,1")
            return True
        return False

    def _submenu_five(self) -> bool:
        selection = self._select_other_concern()
        if selection is not None:
            category, call_type = selection
            self._record_structured(call_type, category)
        elif self.config.phone_is_open():
            self._play("no_selection_open")
            self._goto_queue()
        else:
            self._record_closed_fallback()
        return True

    def _select_other_concern(self) -> tuple[str, CallType] | None:
        keys = self.config.ivr_keys
        available = {keys[action]: (action, call_type) for action, call_type in OTHER_CONCERNS.items()
                     if keys[action]}
        for _ in range(self.config.ivr.attempts if available else 0):
            digit = self._get_option("submenu_five", "".join(available))
            if digit in available:
                return available[digit]
            if digit is not None:
                self._play("invalid")
        return None

    def _record_structured(self, call_type: CallType, category: str) -> None:
        self._stat_route(CONCERN_ROUTES[call_type])
        self.call = self._create_call_if_admitted(call_type, category)
        if self.call is None:
            self._play("whisper_failure")
            self._goto_queue()
            return
        self._play("recording_hint")
        self._record_person_details()
        self._record_concern(call_type)
        self._record_more_concerns()
        self._play("completed")
        self._finish_call("abgeschlossen")

    def _record_person_details(self) -> None:
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

    def _record_more_concerns(self, *, needs_person_details: bool = False) -> None:
        assert self.call is not None
        keys = self.config.ivr_keys
        more = keys["weiteres_anliegen"]
        types = {keys[action]: call_type for action, call_type in DIRECT_CONCERNS.items() if keys[action]}
        submenu = keys["weitere"] if any(keys[action] for action in OTHER_CONCERNS) else ""
        available = "".join(types) + submenu
        if not more or not available or not self.config.prompt_is_active("more_concern"):
            return
        while self._get_option("more_concern", more + keys["anliegen_fertig"]) == more:
            digit = self._get_option("concern_types", available)
            if digit in types:
                call_type = types[digit]
            elif digit == submenu:
                selection = self._select_other_concern()
                if selection is None:
                    return
                _, call_type = selection
            else:
                return
            identifier = self.call.add_concern(call_type)
            if needs_person_details:
                self._record_person_details()
                needs_person_details = False
            self._stat_route(CONCERN_ROUTES[call_type])
            self._record_concern(call_type, concern_id=identifier)

    def _record_concern(self, call_type: CallType, *, concern_id: str | None = None) -> None:
        if call_type is CallType.PRESCRIPTION:
            self._record_medications(concern_id=concern_id)
            self._play("prescription_information")
        elif call_type is CallType.REFERRAL:
            self._record_field(FieldName.SPECIALTY, "specialty", "fachrichtung.wav", long=True, concern_id=concern_id)
            self._record_field(FieldName.REASON, "referral_reason", "grund.wav", long=True, concern_id=concern_id)
        elif call_type is CallType.APPOINTMENT:
            self._record_field(FieldName.REASON, "appointment", "grund.wav", long=True, concern_id=concern_id)
        elif call_type is CallType.CALLBACK_DETAILS:
            self._record_field(FieldName.REASON, "callback_reason", "grund.wav", long=True, concern_id=concern_id)
        elif call_type is CallType.OTHER:
            self._record_field(FieldName.CONCERN, "other", "anliegen.wav", long=True, concern_id=concern_id)

    def _record_closed_fallback(self) -> None:
        self.call = self._create_call_if_admitted(
            CallType.CALLBACK_FALLBACK,
            "rueckruf_ohne_tastenauswahl",
        )
        if self.call is None:
            self._play("whisper_failure")
            self._goto_queue()
            return
        captured = self._record_field(
            FieldName.REASON,
            "no_selection_closed",
            "grund.wav",
            long=True,
        )
        if captured:
            self._stat_route(CONCERN_ROUTES[CallType.CALLBACK_FALLBACK])
            self._record_more_concerns(needs_person_details=True)
        self._play("completed")
        self._finish_call("stille_oder_auflegen")

    def _record_medications(self, *, concern_id: str | None = None) -> None:
        index = 1
        while True:
            prompt = "first_medication" if index == 1 else "next_medication"
            if not self._record_field(
                FieldName.MEDICATION,
                prompt,
                f"medikament-{index:02d}.wav",
                long=False,
                index=index,
                concern_id=concern_id,
            ):
                return
            keys = self.config.ivr_keys
            available = keys["weiteres_medikament"] + keys["rezept_fertig"]
            if not available or self._get_option("medication_choice", available) != keys["weiteres_medikament"]:
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
        concern_id: str | None = None,
    ) -> bool:
        assert self.call is not None
        self._play(prompt)
        if concern_id is not None:
            filename = f"{concern_id}-{filename}"
        audio_path = self.call.begin_audio(field, filename, index, concern_id=concern_id)
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
        if self.config.statistics_pbx_id:
            self.channel.set_variable("KF_LIVE_STAGE", "other")
        self.channel.goto(self.config.ivr.queue_context)

    def _stat_route(self, route: str | None) -> None:
        if route is not None and self.config.statistics_pbx_id:
            emit_agi_route(self.channel, self.config.statistics_pbx_id, route)

    def _prompt(self, key: str) -> Path:
        return self.config.paths.prompts / key

    def _play(self, key: str) -> None:
        if not self.config.prompt_is_active(key):
            return
        self.channel.stream_file(self._prompt(key))

    def _stream(
        self,
        key: str,
        digits: str,
        *,
        practice_open: bool | None = None,
    ) -> str | None:
        if not self.config.prompt_is_active(key, practice_open=practice_open):
            return None
        digit = self.channel.stream_file(self._prompt(key), digits)
        if digit or self.config.ivr.announcement_pause_ms == 0:
            return digit
        response = self.channel.command(f"WAIT FOR DIGIT {self.config.ivr.announcement_pause_ms}")
        if response.result <= 0:
            return None
        digit = chr(response.result)
        return digit if digit in digits else None

    def _get_option(self, key: str, digits: str) -> str | None:
        if not self.config.prompt_is_active(key):
            digit = self._wait_for_digit()
            return digit if digit in digits else None
        return self.channel.get_option(
            self._prompt(key), digits, self.config.ivr.digit_timeout_ms
        )

    def _wait_for_digit(self) -> str | None:
        response = self.channel.command(f"WAIT FOR DIGIT {self.config.ivr.digit_timeout_ms}")
        return chr(response.result) if response.result > 0 else None
