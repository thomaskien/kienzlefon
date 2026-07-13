# kienzlefon
# Version: 1.7
# Changelog:
# - 1.7: Externe eingehende Caller-ID fuer die Anzeige an Telefonen normalisiert.
# - 1.3: Deutsche Rufnummernnormalisierung, Sperrlisten und Auditprotokoll eingefuehrt.

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Collection

from .config import AppConfig, DialRulesConfig

EMERGENCY_NUMBERS = frozenset({"110", "112", "116116", "116117"})


@dataclass(frozen=True)
class DialDecision:
    allowed: bool
    normalized: str
    reason: str


def decide_number(rules: DialRulesConfig, dialed: str) -> DialDecision:
    value = dialed.strip().replace(" ", "")
    if value in EMERGENCY_NUMBERS:
        return DialDecision(True, value, "notruf_ausnahme")
    if value.startswith("+") or value.startswith("00"):
        if rules.block_international:
            return DialDecision(False, "", "international_gesperrt")
        value = value[1:] if value.startswith("+") else value[2:]
    if not value.isdigit() or len(value) < rules.minimum_external_digits:
        return DialDecision(False, "", "ungueltige_rufnummer")
    if rules.block_118 and value.startswith("118"):
        return DialDecision(False, "", "118_auskunft_gesperrt")

    national = _national_number(rules, value)
    blocked = _blocked_reason(rules, national)
    if blocked:
        return DialDecision(False, "", blocked)
    if value.startswith(rules.country_code):
        normalized = value
    elif value.startswith("0"):
        normalized = rules.country_code + value[1:]
    else:
        normalized = rules.country_code + rules.area_code[1:] + value
    return DialDecision(True, normalized, "freigegeben")


def canonical_practice_number(rules: DialRulesConfig) -> str:
    return decide_number(rules, rules.practice_number).normalized


def normalize_incoming_caller_id(
    value: str | None,
    country_code: str = "49",
    local_extensions: Collection[str] = (),
) -> str | None:
    if value is None:
        return None
    original = value.strip()
    compact = original.replace(" ", "")
    if not compact or not re.fullmatch(r"\+?[0-9]+", compact):
        return original
    if compact in local_extensions:
        return compact
    if compact.startswith("+"):
        compact = compact[1:]
    if compact.startswith("00"):
        international = compact[2:]
        if international.startswith(country_code):
            return "0" + international[len(country_code) :]
        return compact
    if compact.startswith("0"):
        return compact
    if compact.startswith(country_code):
        return "0" + compact[len(country_code) :]
    return "00" + compact


def audit_decision(config: AppConfig, dialed: str, caller_id: str, decision: DialDecision) -> None:
    value = {
        "zeit": datetime.now(config.practice.timezone).isoformat(timespec="seconds"),
        "caller_id": caller_id or "unbekannt",
        "gewaehlt": dialed,
        "freigegeben": decision.allowed,
        "normalisiert": decision.normalized,
        "grund": decision.reason,
    }
    _append_json_line(config.dial_rules.audit_log, value)


def _national_number(rules: DialRulesConfig, value: str) -> str:
    if value.startswith(rules.country_code):
        return "0" + value[len(rules.country_code) :]
    if value.startswith("0"):
        return value
    return rules.area_code + value


def _blocked_reason(rules: DialRulesConfig, national: str) -> str:
    for enabled, prefix, reason in (
        (rules.block_0900, "0900", "0900_gesperrt"),
        (rules.block_0137, "0137", "0137_gesperrt"),
        (rules.block_019, "019", "019_gesperrt"),
        (rules.block_0180, "0180", "0180_gesperrt"),
        (rules.block_0700, "0700", "0700_gesperrt"),
        (rules.block_032, "032", "032_gesperrt"),
    ):
        if enabled and national.startswith(prefix):
            return reason
    if rules.block_118 and national.startswith("0118"):
        return "118_auskunft_gesperrt"
    return ""


def _append_json_line(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    descriptor = os.open(path, flags, 0o640)
    try:
        payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
