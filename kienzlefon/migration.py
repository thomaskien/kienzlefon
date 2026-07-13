# kienzlefon
# Version: 1.8.2
# Changelog:
# - 1.8.2: Freigegebene Notruf- und Fallback-Standardtexte konservativ aktualisiert.
# - 1.8: Fehlenden Telepraxis-Demomodus konservativ aus der Vorlage ergaenzt.
# - 1.7: Fehlende Rottelefon- und Sonderqueue-Werte konservativ ergaenzt.
# - 1.6: Altes Whisper-Modell konservativ in die getrennte Modellwahl migriert.
# - 1.6: Einzelwertaktualisierung auf genau eine TOML-Zeile begrenzt.
# - 1.5: Standardtext der 16-kHz-Aufnahme konservativ aktualisiert.
# - 1.4: PIN- und alte Administrationsschluessel konservativ aus 1.3 entfernt.
# - 1.3: Fehlende 1.3-TOML-Eintraege ohne Ueberschreiben bestehender Werte ergaenzt.

from __future__ import annotations

import os
import re
import tomllib
import json
from pathlib import Path

REMOVED_KEYS = {
    "whisper": {"modell"},
    "ansagen_ivr": {"pin", "pin_versuche"},
    "ansagen": {
        "admin_pin",
        "admin_pin_failed",
        "admin_override_menu",
        "admin_override_keep",
        "admin_override_block",
        "admin_override_disabled",
        "admin_override_status_disabled",
        "admin_override_status_keep",
        "admin_override_status_block",
    },
}

OLD_PROMPT_DEFAULTS = {
    "emergency": "Bei lebensbedrohlichen Notf\u00e4llen w\u00e4hlen Sie bitte sofort die 112.",
    "urgent_help": (
        "Bei dringenden Beschwerden au\u00dferhalb unserer Sprechzeiten wenden Sie sich bitte "
        "an den \u00e4rztlichen Bereitschaftsdienst unter 116117."
    ),
    "no_selection_closed": (
        "Bitte sagen Sie Vorname, Nachname und Geburtsdatum und sagen Sie uns, worum es geht. "
        "Wir k\u00f6nnen Sie auch zur\u00fcckrufen. Bitte nennen Sie uns gegebenenfalls eine "
        "R\u00fcckrufnummer. Danach einfach auflegen."
    ),
    "personal_data_fallback": (
        "Ihre Personalangaben konnten nicht vollst\u00e4ndig aufgenommen werden. Bitte sagen Sie "
        "nun in einer zusammenh\u00e4ngenden Nachricht Vorname, Nachname und Geburtsdatum und "
        "sagen Sie uns, worum es geht. Bitte nennen Sie uns gegebenenfalls eine R\u00fcckrufnummer. "
        "Danach einfach auflegen."
    ),
    "admin_main": (
        "F\u00fcr die Ansagenverwaltung dr\u00fccken Sie 1. F\u00fcr die Override-Steuerung "
        "dr\u00fccken Sie 2. Zum Beenden dr\u00fccken Sie 0."
    ),
    "admin_prompt_select": (
        "Bitte geben Sie die Nummer des Ansagebausteins ein und best\u00e4tigen Sie mit der "
        "Raute-Taste."
    ),
    "admin_prompt_actions": (
        "Zum Aufnehmen dr\u00fccken Sie 1. Zum Anh\u00f6ren der neuen Aufnahme dr\u00fccken Sie 2. "
        "Zum Aktivieren dr\u00fccken Sie 3. F\u00fcr die computergenerierte Ansage dr\u00fccken Sie "
        "4. Zur\u00fcck mit 0."
    ),
    "admin_record": (
        "Die Aufnahme startet jetzt sofort. Beenden Sie mit einer Taste oder durch Stille.",
        "Sprechen Sie nach dem Ende dieser Ansage. Die Aufnahme beginnt sofort und ohne "
        "Signalton. Beenden Sie die Aufnahme mit einer beliebigen Taste oder durch eine "
        "l\u00e4ngere Sprechpause.",
    ),
    "admin_record_ready": (
        "Die Aufnahme wurde gespeichert und kann jetzt angeh\u00f6rt oder aktiviert werden."
    ),
    "admin_activated": "Die aufgenommene Ansage ist jetzt aktiv.",
    "admin_generated": "Die computergenerierte Ansage ist jetzt aktiv.",
    "admin_invalid": "Diese Eingabe ist nicht verf\u00fcgbar.",
}


def migrate_config(target: Path, template: Path) -> bool:
    text = target.read_text(encoding="utf-8")
    template_text = template.read_text(encoding="utf-8")
    updated = _migrate_legacy_whisper_model(text)
    updated = _replace_old_defaults(updated, template_text)
    for section, keys in REMOVED_KEYS.items():
        updated = _remove_keys(updated, section, keys)
    for section, body in _sections(template_text):
        current_match = re.search(
            rf"^\[{re.escape(section)}\]\n(?P<body>.*?)(?=^\[|\Z)", updated, re.M | re.S
        )
        if current_match is None:
            updated = updated.rstrip() + f"\n\n[{section}]\n{body.rstrip()}\n"
            continue
        existing_keys = set(re.findall(r"^([A-Za-z0-9_]+)\s*=", current_match["body"], re.M))
        missing = [line for line in body.splitlines() if _key(line) not in existing_keys]
        missing = [line for line in missing if _key(line) is not None]
        if missing:
            insertion = current_match.end("body")
            updated = updated[:insertion].rstrip() + "\n" + "\n".join(missing) + "\n\n" + updated[insertion:].lstrip("\n")
    if updated == text:
        return False
    temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(updated, encoding="utf-8")
        os.chmod(temporary, target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _migrate_legacy_whisper_model(text: str) -> str:
    whisper = tomllib.loads(text).get("whisper", {})
    legacy_model = whisper.get("modell")
    if legacy_model is None or "modell_standard" in whisper:
        return text
    match = re.search(
        r"(^\[whisper\]\n(?:(?!^\[).)*?^modell\s*=\s*)(?P<value>[^\n]+)$",
        text,
        re.M | re.S,
    )
    if match is None:
        raise ValueError("Altes TOML-Feld [whisper].modell konnte nicht migriert werden")
    insertion = match.end()
    return text[:insertion] + f"\nmodell_standard = {match['value'].strip()}" + text[insertion:]


def set_string(target: Path, section: str, key: str, value: str) -> None:
    text = target.read_text(encoding="utf-8")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    pattern = re.compile(
        rf"(^\[{re.escape(section)}\]\n(?:(?!^\[).)*?^{re.escape(key)}\s*=\s*)[^\n]*$",
        re.M | re.S,
    )
    updated, count = pattern.subn(rf'\g<1>"{escaped}"', text, count=1)
    if count != 1:
        raise ValueError(f"TOML-Feld fehlt nach Migration: [{section}].{key}")
    temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(updated, encoding="utf-8")
        os.chmod(temporary, target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _sections(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^\[([^]]+)\]\n", text, re.M))
    return [
        (match[1], text[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)])
        for index, match in enumerate(matches)
    ]


def _key(line: str) -> str | None:
    match = re.match(r"^([A-Za-z0-9_]+)\s*=", line)
    return match[1] if match else None


def _remove_keys(text: str, section: str, keys: set[str]) -> str:
    lines = text.splitlines()
    in_section = False
    kept: list[str] = []
    for line in lines:
        if line == f"[{section}]":
            in_section = True
        elif line.startswith("["):
            in_section = False
        key = _key(line) if in_section else None
        if key not in keys:
            kept.append(line)
    return "\n".join(kept) + "\n"


def _replace_old_defaults(text: str, template_text: str) -> str:
    current = tomllib.loads(text).get("ansagen", {})
    replacement = tomllib.loads(template_text).get("ansagen", {})
    updated = text
    for key, old_value in OLD_PROMPT_DEFAULTS.items():
        old_values = old_value if isinstance(old_value, tuple) else (old_value,)
        if current.get(key) not in old_values:
            continue
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.M)
        updated, count = pattern.subn(
            f"{key} = {json.dumps(replacement[key], ensure_ascii=False)}", updated, count=1
        )
        if count != 1:
            raise ValueError(f"TOML-Ansage fehlt waehrend Migration: {key}")
    return updated
