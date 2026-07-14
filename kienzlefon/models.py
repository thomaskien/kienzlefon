# kienzlefon
# Version: 1.8.3
# Changelog:
# - 1.8.3: Leere Aufnahmen als eigenen, fehlerfreien Audiostatus abgebildet.
# - 1.0: Datenmodelle fuer Aufnahmen, Status und Fehler eingefuehrt.

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class CallState(StrEnum):
    RECORDING = "recording"
    QUEUE = "queue"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class AudioStatus(StrEnum):
    RECORDED = "recorded"
    TRANSCRIBED = "transcribed"
    EMPTY = "empty"
    ERROR = "error"


class FieldName(StrEnum):
    FIRST_NAME = "vorname"
    LAST_NAME = "nachname"
    BIRTH_DATE = "geburtsdatum"
    CALLBACK_NUMBER = "telefon"
    MEDICATION = "medikamente"
    SPECIALTY = "fachrichtung"
    REASON = "grund"
    CONCERN = "anliegen"


class CallType(StrEnum):
    PRESCRIPTION = "rezeptbestellung"
    REFERRAL = "ueb_req"
    APPOINTMENT = "termin"
    CALLBACK_DETAILS = "rueckruf_details"
    CALLBACK_FALLBACK = "rueckruf_tel_grund"
    OTHER = "sonstiges"
    ERROR = "kienzlefon_error"


@dataclass(frozen=True)
class ClaimedCall:
    call_id: str
    path: Path


@dataclass(frozen=True)
class RecordingResult:
    path: Path
    status: str
    present: bool
