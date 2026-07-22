# kienzlefon
# Version: 1.9
# Changelog:
# - 1.9: Konfigurierte Demo-Anonymisierung auch auf Fehlerausgaben angewendet.
# - 1.8: Fehlerausgabe an den konfigurierten Demo- oder Produktivmodus angebunden.
# - 1.0: Einheitliche lokale und verschluesselte Fehlererfassung eingefuehrt.

from __future__ import annotations

import logging
import secrets
from .config import AppConfig
from .crypto import TelepraxisEncryptor
from .models import CallState, CallType
from .spool import Spool, WorkingCall

LOGGER = logging.getLogger(__name__)


def report_call_errors(call: WorkingCall, encryptor: TelepraxisEncryptor) -> int:
    reported = 0
    record = call.load()
    for error in list(record["_kienzlefon"]["errors"]):
        if error.get("gemeldet", False):
            continue
        payload = encryptor.error_payload(
            call_id=call.call_id,
            caller_id=str(record.get("id", "unbekannt")),
            phone=str(record.get("telefon", "unbekannt")),
            source_type=str(record.get("typ", "unknown")),
            error=error,
        )
        stamp = str(error["zeit"]).replace("-", "").replace(":", "").replace("+", "_")
        basename = f"{call.call_id}_error_{stamp}_{secrets.randbelow(1_000_000):06d}"
        encryptor.write_payload(payload, basename)
        call.mark_error_reported(str(error["zeit"]))
        reported += 1
    return reported


def record_system_error(
    config: AppConfig,
    *,
    code: str,
    phase: str,
    message: str,
    caller_id: str | None = None,
) -> WorkingCall:
    LOGGER.error("%s [%s]: %s", code, phase, message)
    spool = Spool(config.paths.spool, config.practice.timezone)
    call = spool.create_call(CallType.ERROR, caller_id, "system_error")
    call.add_error(code, phase, message)
    call = spool.transition(call, CallState.ERROR)
    try:
        encryptor = TelepraxisEncryptor(
            config.telepraxis.public_key,
            config.telepraxis.output_directory,
            config.practice.timezone,
            demo_mode=config.telepraxis.demo,
            anonymize_phone_numbers=config.telepraxis.anonymize_phone_numbers,
        )
        report_call_errors(call, encryptor)
    except Exception:
        LOGGER.exception("Fehlerereignis konnte noch nicht als Telepraxis-Datei ausgegeben werden")
    return call
