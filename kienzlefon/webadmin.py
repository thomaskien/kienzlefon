# kienzlefon
# Separate, privilege-separated web administration support.

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .agi import AgiChannel, AgiHangup
from .config import QWEN_SPEAKERS, WEEKDAYS, AppConfig, load_config
from .prompts import (
    PROMPT_CATALOG,
    PROMPT_PROGRESS_PREFIX,
    PromptGenerator,
    rendered_prompts,
)
from .spool import write_json_atomic

DEFAULT_CONFIG = Path("/etc/kienzlefon/kienzlefon.toml")
DEFAULT_DEFAULTS = Path("/usr/share/kienzlefon-webinterface/kienzlefon-defaults.toml")
DEFAULT_WEB_CONFIG = Path("/etc/kienzlefon/webinterface.json")
DEFAULT_RUNTIME = Path("/run/kienzlefon-webinterface")
DEFAULT_CONFIG_COMMAND = "/opt/kienzlefon/venv/bin/kienzlefon-config"
DEFAULT_PROMPTS_COMMAND = "/opt/kienzlefon/venv/bin/kienzlefon-ansagen"
DEFAULT_RECORD_COMMAND = "/opt/kienzlefon/venv/bin/kienzlefon-webaufnahme"
DEFAULT_ASTERISK_COMMAND = "/usr/sbin/asterisk"
EDITABLE_SCHEDULES = ("oeffnungszeiten", "telefonzeiten", "fachstellenzeiten")
SOURCE_VALUES = frozenset({"tts", "manuell"})
TTS_ENGINE_VALUES = frozenset({"piper", "qwen"})
RECORD_SESSION_SECONDS = 1500
JOB_ID = re.compile(r"^[a-f0-9]{32}$")
PROMPT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PRESET_ID = re.compile(r"^[a-f0-9]{32}$")
TIME_RANGE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]-(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
LOCAL_DATETIME = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]$"
)

STATUS_LABELS = {
    "konfiguration_wird_geprueft": "Konfiguration wird geprüft",
    "einstellungen_gespeichert": "Einstellungen gespeichert",
    "ansagen_werden_aktualisiert": "Ansagen werden aktualisiert",
    "ansagen_aktuell": "Ansagen aktuell",
    "ansagenerzeugung_fehlgeschlagen": "Ansagenerzeugung fehlgeschlagen",
    "nebenstelle_wird_angerufen": "Nebenstelle wird angerufen",
    "aufnahme_laeuft": "Aufnahme läuft",
    "aufnahme_gespeichert": "Aufnahme gespeichert",
    "aufnahme_verworfen": "Aufnahme verworfen",
    "nebenstelle_nicht_erreichbar": "Nebenstelle besetzt oder keine Antwort",
    "vorlage_wird_gespeichert": "Sonderansage wird gespeichert",
    "vorlage_gespeichert": "Sonderansage gespeichert",
    "vorlage_geloescht": "Sonderansage gelöscht",
    "vorgang_laeuft": "Ein anderer Vorgang läuft bereits",
    "auftrag_abgelehnt": "Auftrag abgelehnt",
}

PROMPT_LABELS = {
    "greeting_open": "Begrüßung bei geöffneter Praxis",
    "greeting_closed": "Begrüßung bei geschlossener Praxis",
    "emergency": "Notfallhinweis",
    "urgent_help": "Ärztlicher Bereitschaftsdienst",
    "menu_intro": "Einleitung Hauptmenü",
    "menu_open": "Hauptmenü innerhalb der Telefonzeiten",
    "menu_closed": "Hauptmenü außerhalb der Telefonzeiten",
    "opening_hours_choice": "Auswahl Öffnungszeiten",
    "opening_hours_prefix": "Einleitung Öffnungszeiten",
    "opening_hours_closed": "Geschlossener Wochentag",
    "phone_hours_prefix": "Einleitung Telefonzeiten",
    "phone_hours_closed": "Telefonisch nicht erreichbarer Wochentag",
    "phone_hours": "Zusätzlicher Telefonzeiten-Text",
    "override": "Temporäre Sonderansage",
    "webadmin_record": "Aufforderung zur Telefonaufnahme",
    "webadmin_record_actions": "Auswahl nach der Telefonaufnahme",
    "webadmin_record_saved": "Bestätigung gespeicherte Aufnahme",
    "webadmin_record_discarded": "Bestätigung verworfene Aufnahme",
}

PRIMARY_PROMPTS = frozenset(
    {
        "greeting_open",
        "greeting_closed",
        "emergency",
        "urgent_help",
        "menu_open",
        "menu_closed",
        "opening_hours_choice",
    }
)

PROMPT_GROUPS = {
    "hauptansagen": PRIMARY_PROMPTS,
    "zeiten_und_menue": frozenset(
        {
            "menu_intro",
            "pharmacy_access",
            "specialist_access",
            "opening_hours",
            "opening_hours_prefix",
            "opening_hours_closed",
            "phone_hours_prefix",
            "phone_hours_closed",
            "phone_hours",
            "submenu_five",
        }
    ),
    "datenerfassung": frozenset(
        {
            "recording_hint",
            "first_name",
            "last_name",
            "birth_date",
            "callback_number",
            "first_medication",
            "next_medication",
            "medication_choice",
            "specialty",
            "referral_reason",
            "appointment",
            "callback_reason",
            "other",
            "personal_data_fallback",
        }
    ),
    "abschluss_und_fehler": frozenset(
        {
            "no_selection_open",
            "no_selection_closed",
            "invalid",
            "completed",
            "whisper_failure",
            "prescription_information",
            "pharmacy_agent",
            "specialist_agent",
            "blocked_destination",
        }
    ),
    "interne_verwaltung": frozenset(
        {
            "admin_main",
            "admin_prompt_select",
            "admin_current_prompt",
            "admin_prompt_actions",
            "admin_record",
            "admin_record_ready",
            "admin_no_recording",
            "admin_activated",
            "admin_generated",
            "admin_special_menu",
            "admin_special_keep",
            "admin_special_block",
            "admin_special_disabled",
            "admin_invalid",
            "admin_special_status_disabled",
            "admin_special_status_keep",
            "admin_special_status_block",
            "webadmin_record",
            "webadmin_record_actions",
            "webadmin_record_saved",
            "webadmin_record_discarded",
        }
    ),
}


class WebAdminError(RuntimeError):
    pass


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    if not isinstance(value, dict):
        raise WebAdminError(f"TOML-Wurzel ist kein Objekt: {path}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise WebAdminError(f"JSON-Wurzel ist kein Objekt: {path}")
    return value


def _read_job(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 262_144:
            raise WebAdminError("Auftragsdatei ist unzulässig")
        payload = b""
        while len(payload) <= 262_144:
            chunk = os.read(descriptor, min(65_536, 262_145 - len(payload)))
            if not chunk:
                break
            payload += chunk
        if len(payload) > 262_144:
            raise WebAdminError("Auftragsdatei ist zu groß")
        value = json.loads(payload.decode("utf-8"))
    finally:
        os.close(descriptor)
    if not isinstance(value, dict):
        raise WebAdminError("Auftragswurzel ist kein Objekt")
    return value


def _config_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prompt_label(name: str) -> str:
    return PROMPT_LABELS.get(name, name.replace("_", " ").capitalize())


def _prompt_group(name: str) -> str:
    for group, names in PROMPT_GROUPS.items():
        if name in names:
            return group
    return "weitere_ansagen"


def _manual_path(config: AppConfig, name: str) -> Path | None:
    for suffix in ("wav16", "wav"):
        candidate = config.tts.upload_directory / f"{name}.{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _candidate_path(config: AppConfig, name: str) -> Path:
    return config.tts.upload_directory / "kandidaten" / f"{name}.wav16"


def _preset_root(config: AppConfig) -> Path:
    return config.paths.prompt_masters / "sonderansagen"


def _preset_directory(config: AppConfig, preset_id: str) -> Path:
    if not PRESET_ID.fullmatch(preset_id):
        raise WebAdminError("Ungültige Kennung der gespeicherten Sonderansage")
    root = _preset_root(config)
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        raise WebAdminError("Ablage der gespeicherten Sonderansagen ist unsicher")
    return root / preset_id


def _read_override_presets(config: AppConfig) -> list[dict[str, Any]]:
    current = config.current_override()
    now = config.now()
    presets: list[dict[str, Any]] = []
    for entry in config.scheduled_overrides:
        directory = _preset_directory(config, entry.identifier)
        metadata_path = directory / "metadata.json"
        updated_at = ""
        try:
            metadata = _read_json(metadata_path)
            updated_at = str(metadata.get("updated_at", ""))
        except (OSError, ValueError, json.JSONDecodeError, WebAdminError):
            pass
        presets.append(
            {
                "id": entry.identifier,
                "prompt_name": entry.prompt_name,
                "name": entry.name,
                "announcement": entry.announcement,
                "active": entry.active,
                "effective": current is not None
                and current.identifier == entry.identifier,
                "past": entry.expires_at is not None and now >= entry.expires_at,
                "future": entry.valid_from is not None and now < entry.valid_from,
                "priority": entry.priority,
                "valid_from": entry.valid_from.replace(tzinfo=None).isoformat(
                    timespec="minutes"
                )
                if entry.valid_from
                else "",
                "expires_at": entry.expires_at.replace(tzinfo=None).isoformat(
                    timespec="minutes"
                )
                if entry.expires_at
                else "",
                "block_phone_hours": entry.block_phone_hours,
                "position": entry.position,
                "source": entry.source,
                "updated_at": updated_at,
                "tts_available": (directory / "tts.wav").is_file()
                and not (directory / "tts.wav").is_symlink(),
                "manual_available": (directory / "manuell.wav").is_file()
                and not (directory / "manuell.wav").is_symlink(),
            }
        )
    return sorted(
        presets,
        key=lambda item: (
            not item["effective"],
            not item["active"],
            -item["priority"],
            item["name"].casefold(),
            item["id"],
        ),
    )


def _copy_audio_preview(source: Path, target: Path) -> bool:
    if not source.is_file() or source.is_symlink():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    )
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o640)
        os.replace(temporary, target)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _web_settings(path: Path) -> dict[str, Any]:
    value = _read_json(path) if path.is_file() else {}
    return {
        "passwordless": bool(value.get("passwordless", False)),
        "listen": str(value.get("listen", "")),
        "port": int(value.get("port", 0)),
        "server": str(value.get("server", "")),
        "tls": bool(value.get("tls", False)),
    }


def _qwen_generator_available(config: AppConfig) -> bool:
    generator = config.tts.qwen_generator
    if not generator.is_file() or not os.access(generator, os.X_OK):
        return False
    try:
        return b"kienzlefon-worker.service" in generator.read_bytes()
    except OSError:
        return False


def _write_text_atomic(path: Path, value: str, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _php_password_hash(password: str, php_binary: str, existing_hash: str = "") -> str:
    code = (
        "$v=json_decode(stream_get_contents(STDIN),true,2,JSON_THROW_ON_ERROR);"
        "$p=(string)$v['password'];$old=(string)$v['hash'];"
        "if($old!==''&&password_verify($p,$old)){echo $old;exit(0);}"
        "$h=password_hash($p,PASSWORD_DEFAULT);"
        "if($h===false){exit(2);}echo $h;"
    )
    result = subprocess.run(
        [php_binary, "-r", code],
        input=json.dumps(
            {"password": password, "hash": existing_hash}, ensure_ascii=False
        ).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise WebAdminError(f"Passwort-Hash konnte nicht erzeugt werden: {detail}")
    password_hash = result.stdout.decode("utf-8").strip()
    if not password_hash.startswith("$"):
        raise WebAdminError("PHP lieferte keinen verwendbaren Passwort-Hash")
    return password_hash


def export_state(
    config_path: Path,
    defaults_path: Path,
    web_config_path: Path,
    state_path: Path,
    auth_hash_path: Path,
    *,
    php_binary: str = "/usr/bin/php",
) -> dict[str, Any]:
    config = load_config(config_path)
    raw = _read_toml(config_path)
    defaults = _read_toml(defaults_path)
    web = _web_settings(web_config_path)
    web_toml = raw.get("webinterface", {})
    if not isinstance(web_toml, Mapping):
        raise WebAdminError("[webinterface] muss ein TOML-Abschnitt sein")
    password = str(web_toml.get("passwort", ""))
    auth_required = not web["passwordless"]
    auth_ready = bool(password) if auth_required else True
    if auth_required and password:
        existing_hash = ""
        if auth_hash_path.is_file() and auth_hash_path.stat().st_size <= 1024:
            existing_hash = auth_hash_path.read_text(encoding="utf-8").strip()
        _write_text_atomic(
            auth_hash_path,
            _php_password_hash(password, php_binary, existing_hash) + "\n",
        )
    else:
        _write_text_atomic(auth_hash_path, "")

    raw_prompts = raw.get("ansagen", {})
    default_prompts = defaults.get("ansagen", {})
    if not isinstance(raw_prompts, Mapping) or not isinstance(default_prompts, Mapping):
        raise WebAdminError("Ansagenabschnitt fehlt in Konfiguration oder Standarddatei")
    default_tts = defaults.get("tts", {})
    if not isinstance(default_tts, Mapping):
        raise WebAdminError("TTS-Standardabschnitt fehlt")
    prompt_fields = [
        {
            "name": str(name),
            "label": _prompt_label(str(name)),
            "group": _prompt_group(str(name)),
            "primary": str(name) in PRIMARY_PROMPTS,
            "value": str(value),
            "default": str(default_prompts.get(name, value)),
        }
        for name, value in raw_prompts.items()
    ]
    prompt_fields_by_name = {field["name"]: field for field in prompt_fields}

    rendered = rendered_prompts(config)
    ordered_names = [name for name in PROMPT_CATALOG if name in rendered]
    ordered_names.extend(
        sorted(
            name
            for name in set(rendered) - set(ordered_names)
            if not name.startswith("override_")
        )
    )
    preview_directory = state_path.parent / "audio"
    sources = []
    for name in ordered_names:
        manual = _manual_path(config, name)
        configured = config.prompt_sources.get(name)
        active_source = configured or ("manuell" if manual is not None else "tts")
        if name == "opening_hours":
            field_names = ("opening_hours_prefix", "opening_hours_closed")
        elif name == "phone_hours":
            field_names = ("phone_hours_prefix", "phone_hours_closed", "phone_hours")
        else:
            field_names = (name,)
        active_preview = _copy_audio_preview(
            config.paths.prompt_masters / f"{name}.wav",
            preview_directory / f"active-{name}.wav",
        )
        candidate_preview = _copy_audio_preview(
            _candidate_path(config, name),
            preview_directory / f"candidate-{name}.wav",
        )
        sources.append(
            {
                "name": name,
                "label": _prompt_label(name),
                "group": _prompt_group(name),
                "primary": name in PRIMARY_PROMPTS,
                "tts_text": rendered[name],
                "fields": [
                    prompt_fields_by_name[field_name]
                    for field_name in field_names
                    if field_name in prompt_fields_by_name
                ],
                "source": active_source,
                "manual_available": manual is not None,
                "candidate_available": _candidate_path(config, name).is_file(),
                "active_preview": active_preview,
                "candidate_preview": candidate_preview,
            }
        )

    override_presets = _read_override_presets(config)
    preset_root = _preset_root(config)
    for preset in override_presets:
        preset_id = preset["id"]
        preset["tts_preview"] = _copy_audio_preview(
            preset_root / preset_id / "tts.wav",
            preview_directory / f"preset-tts-{preset_id}.wav",
        )
        preset["manual_preview"] = _copy_audio_preview(
            preset_root / preset_id / "manuell.wav",
            preview_directory / f"preset-manual-{preset_id}.wav",
        )

    schedules: dict[str, dict[str, Any]] = {}
    default_schedules: dict[str, dict[str, Any]] = {}
    for section in EDITABLE_SCHEDULES:
        current = raw.get(section, {})
        standard = defaults.get(section, {})
        if not isinstance(current, Mapping) or not isinstance(standard, Mapping):
            raise WebAdminError(f"Zeitabschnitt fehlt: [{section}]")
        schedules[section] = {day: list(current.get(day, [])) for day in WEEKDAYS}
        default_schedules[section] = {day: list(standard.get(day, [])) for day in WEEKDAYS}

    override = raw.get("override", {})
    default_override = defaults.get("override", {})
    if not isinstance(override, Mapping) or not isinstance(default_override, Mapping):
        raise WebAdminError("[override] fehlt")
    record_extensions = [
        extension
        for extension in config.local_extensions
        if extension != config.announcement_ivr.extension
    ]
    override_source = next(
        (source for source in sources if source["name"] == "override"), {}
    )
    current_override = config.current_override()
    state = {
        "version": 1,
        "generated_at": datetime.now(config.practice.timezone).isoformat(timespec="seconds"),
        "config_hash": _config_hash(config_path),
        "practice": config.practice.name,
        "timezone": str(config.practice.timezone),
        "auth_required": auth_required,
        "auth_ready": auth_ready,
        "network": web,
        "schedules": schedules,
        "schedule_defaults": default_schedules,
        "prompts": prompt_fields,
        "sources": sources,
        "tts": {
            "engine": config.tts.engine,
            "qwen_voice": config.tts.qwen_voice,
            "qwen_available": _qwen_generator_available(config),
            "qwen_voices": list(QWEN_SPEAKERS),
            "defaults": {
                "engine": str(default_tts.get("engine", "piper")),
                "qwen_voice": str(default_tts.get("qwen_stimme", "ryan")),
            },
        },
        "override": {
            "active": bool(override.get("aktiv", False)),
            "effective": current_override is not None
            and current_override.identifier == "legacy",
            "past": config.override.expires_at is not None
            and config.now() >= config.override.expires_at,
            "announcement": str(override.get("ansage", "")),
            "expires_at": str(override.get("ablauf", "")),
            "block_phone_hours": bool(override.get("telefonzeiten_sperren", True)),
            "position": str(override.get("position", "statt_begruessung")),
            "source": config.prompt_sources.get("override")
            or ("manuell" if _manual_path(config, "override") else "tts"),
            "manual_available": _manual_path(config, "override") is not None,
            "candidate_available": _candidate_path(config, "override").is_file(),
            "active_preview": bool(override_source.get("active_preview", False)),
            "candidate_preview": bool(override_source.get("candidate_preview", False)),
            "defaults": {
                "active": bool(default_override.get("aktiv", False)),
                "announcement": str(default_override.get("ansage", "")),
                "expires_at": str(default_override.get("ablauf", "")),
                "block_phone_hours": bool(
                    default_override.get("telefonzeiten_sperren", True)
                ),
                "position": str(
                    default_override.get("position", "statt_begruessung")
                ),
            },
        },
        "override_presets": override_presets,
        "current_override": (
            {
                "id": current_override.identifier,
                "name": current_override.name,
                "priority": current_override.priority,
                "legacy": current_override.identifier == "legacy",
            }
            if current_override is not None
            else None
        ),
        "extensions": record_extensions,
    }
    write_json_atomic(state_path, state, mode=0o644)
    return state


def _toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return json.dumps(value, ensure_ascii=False)
    raise WebAdminError(f"Wert kann nicht als erlaubtes TOML geschrieben werden: {type(value)}")


def _set_toml_value(text: str, section: str, key: str, value: Any) -> str:
    header = re.search(rf"^\[{re.escape(section)}\]\s*$", text, re.M)
    literal = _toml_literal(value)
    if header is None:
        return text.rstrip() + f"\n\n[{section}]\n{key} = {literal}\n"
    next_header = re.search(r"^\[[^]]+\]\s*$", text[header.end() :], re.M)
    section_end = header.end() + (next_header.start() if next_header else len(text) - header.end())
    body = text[header.end() : section_end]
    pattern = re.compile(rf"^(?P<prefix>{re.escape(key)}\s*=\s*).*$", re.M)
    updated, count = pattern.subn(rf"\g<prefix>{literal}", body, count=1)
    if count == 0:
        updated = body.rstrip() + f"\n{key} = {literal}\n"
    return text[: header.end()] + updated + text[section_end:]


def _validate_schedule(section: str, value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping) or set(value) != set(WEEKDAYS):
        raise WebAdminError(f"Unvollständiger Zeitabschnitt: {section}")
    result: dict[str, list[str]] = {}
    for day in WEEKDAYS:
        ranges = value[day]
        if not isinstance(ranges, list) or len(ranges) > 8:
            raise WebAdminError(f"Ungültige Zeitliste: [{section}].{day}")
        normalized = []
        for item in ranges:
            text = str(item).strip()
            if not TIME_RANGE.fullmatch(text):
                raise WebAdminError(f"Ungültiger Zeitraum: [{section}].{day}: {text}")
            normalized.append(text)
        result[day] = normalized
    return result


def _validate_save_request(job: Mapping[str, Any], config: AppConfig) -> dict[str, Any]:
    allowed_top = {
        "action",
        "id",
        "config_hash",
        "schedules",
        "prompts",
        "override",
        "sources",
        "tts",
    }
    if set(job) - allowed_top:
        raise WebAdminError("Auftrag enthält nicht freigegebene Felder")
    config_hash = str(job.get("config_hash", ""))
    if not re.fullmatch(r"[a-f0-9]{64}", config_hash):
        raise WebAdminError("Konfigurationsstand fehlt oder ist ungültig")

    schedule_payload = job.get("schedules", {})
    if not isinstance(schedule_payload, Mapping) or set(schedule_payload) - set(EDITABLE_SCHEDULES):
        raise WebAdminError("Nicht freigegebener Zeitabschnitt")
    schedules = {
        section: _validate_schedule(section, value)
        for section, value in schedule_payload.items()
    }

    prompts_payload = job.get("prompts", {})
    if not isinstance(prompts_payload, Mapping):
        raise WebAdminError("Ansagenwerte müssen ein Objekt sein")
    unknown_prompts = set(prompts_payload) - set(config.prompts.values)
    if unknown_prompts:
        raise WebAdminError(
            "Nicht freigegebene Ansagentexte: " + ", ".join(sorted(unknown_prompts))
        )
    prompts: dict[str, str] = {}
    for key, value in prompts_payload.items():
        text = str(value).strip()
        if len(text) > 5000:
            raise WebAdminError(f"Ansagentext ist zu lang: {key}")
        prompts[str(key)] = text

    override_payload = job.get("override", {})
    if not isinstance(override_payload, Mapping):
        raise WebAdminError("Sonderansage muss ein Objekt sein")
    allowed_override = {
        "active",
        "announcement",
        "expires_at",
        "block_phone_hours",
        "position",
        "manual_preset_id",
    }
    if set(override_payload) - allowed_override:
        raise WebAdminError("Nicht freigegebener Wert der Sonderansage")
    override: dict[str, Any] = {}
    if "active" in override_payload:
        if not isinstance(override_payload["active"], bool):
            raise WebAdminError("Sonderansage aktiv muss boolesch sein")
        override["active"] = override_payload["active"]
    if "block_phone_hours" in override_payload:
        if not isinstance(override_payload["block_phone_hours"], bool):
            raise WebAdminError("Telefonzeitensperre muss boolesch sein")
        override["block_phone_hours"] = override_payload["block_phone_hours"]
    if "position" in override_payload:
        position = str(override_payload["position"])
        if position not in {
            "statt_begruessung",
            "vor_begruessung",
            "nach_begruessung",
        }:
            raise WebAdminError("Position der Sonderansage ist ungültig")
        override["position"] = position
    if "announcement" in override_payload:
        announcement = str(override_payload["announcement"]).strip()
        if len(announcement) > 5000:
            raise WebAdminError("Sonderansage ist zu lang")
        override["announcement"] = announcement
    if "expires_at" in override_payload:
        expires_at = str(override_payload["expires_at"]).strip()
        if expires_at:
            try:
                datetime.fromisoformat(expires_at)
            except ValueError as exc:
                raise WebAdminError("Ablaufdatum ist ungültig") from exc
        override["expires_at"] = expires_at
    if "manual_preset_id" in override_payload:
        preset_id = str(override_payload["manual_preset_id"])
        preset_directory = _preset_directory(config, preset_id)
        manual = preset_directory / "manuell.wav"
        if (
            not preset_directory.is_dir()
            or preset_directory.is_symlink()
            or not manual.is_file()
            or manual.is_symlink()
        ):
            raise WebAdminError("Gespeicherte manuelle Sonderansage fehlt")
        override["manual_preset_id"] = preset_id

    source_payload = job.get("sources", {})
    if not isinstance(source_payload, Mapping):
        raise WebAdminError("Ansagenquellen müssen ein Objekt sein")
    rendered_names = set(rendered_prompts(config))
    unknown_sources = set(source_payload) - rendered_names
    if unknown_sources:
        raise WebAdminError(
            "Nicht freigegebene Ansagenquellen: " + ", ".join(sorted(unknown_sources))
        )
    sources: dict[str, str] = {}
    for key, value in source_payload.items():
        source = str(value)
        if source not in SOURCE_VALUES:
            raise WebAdminError(f"Ungültige Ansagenquelle: {key}")
        preset_manual = key == "override" and "manual_preset_id" in override
        if source == "manuell" and not preset_manual and _manual_path(config, str(key)) is None:
            raise WebAdminError(f"Für {key} liegt keine manuelle Aufnahme vor")
        sources[str(key)] = source

    if "manual_preset_id" in override and sources.get("override") != "manuell":
        raise WebAdminError("Gespeicherte WAV wurde nicht als Audioquelle gewählt")

    tts_payload = job.get("tts", {})
    if not isinstance(tts_payload, Mapping) or set(tts_payload) - {"engine", "qwen_voice"}:
        raise WebAdminError("Nicht freigegebene TTS-Einstellung")
    tts: dict[str, str] = {}
    if "engine" in tts_payload:
        engine = str(tts_payload["engine"])
        if engine not in TTS_ENGINE_VALUES:
            raise WebAdminError("Ungültiges TTS-Erzeugungsmodell")
        if engine == "qwen" and not _qwen_generator_available(config):
            raise WebAdminError(
                "Qwen3-TTS ist nicht vollständig oder nicht sicher für Kienzlefon installiert"
            )
        tts["engine"] = engine
    if "qwen_voice" in tts_payload:
        qwen_voice = str(tts_payload["qwen_voice"]).strip().lower()
        if qwen_voice not in QWEN_SPEAKERS:
            raise WebAdminError("Qwen-Sprecher ist nicht freigegeben")
        tts["qwen_voice"] = qwen_voice

    return {
        "config_hash": config_hash,
        "schedules": schedules,
        "prompts": prompts,
        "override": override,
        "sources": sources,
        "tts": tts,
    }


def _render_updated_config(text: str, values: Mapping[str, Any]) -> str:
    updated = text
    for section, days in values["schedules"].items():
        for day, ranges in days.items():
            updated = _set_toml_value(updated, section, day, ranges)
    for key, value in values["prompts"].items():
        updated = _set_toml_value(updated, "ansagen", key, value)
    override_keys = {
        "active": "aktiv",
        "announcement": "ansage",
        "expires_at": "ablauf",
        "block_phone_hours": "telefonzeiten_sperren",
        "position": "position",
    }
    for source_key, toml_key in override_keys.items():
        if source_key in values["override"]:
            updated = _set_toml_value(
                updated, "override", toml_key, values["override"][source_key]
            )
    for key, value in values["sources"].items():
        updated = _set_toml_value(updated, "ansagen_quellen", key, value)
    tts_keys = {"engine": "engine", "qwen_voice": "qwen_stimme"}
    for source_key, toml_key in tts_keys.items():
        if source_key in values["tts"]:
            updated = _set_toml_value(updated, "tts", toml_key, values["tts"][source_key])
    return updated


def _run_command(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WebAdminError(
            f"Programm konnte nicht sicher ausgeführt werden: {command[0]}: {exc}"
        ) from exc


def _command_error(result: subprocess.CompletedProcess[bytes]) -> str:
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    if not detail:
        detail = result.stdout.decode("utf-8", errors="replace").strip()
    return detail[-2000:] or f"Rückgabecode {result.returncode}"


def _validate_preset_request(
    job: Mapping[str, Any], *, recording: bool
) -> dict[str, Any]:
    allowed = {
        "action",
        "id",
        "preset_id",
        "name",
        "announcement",
        "active",
        "priority",
        "valid_from",
        "expires_at",
        "block_phone_hours",
        "position",
        "source",
    }
    if recording:
        allowed.add("extension")
    if set(job) - allowed:
        raise WebAdminError("Vorlagenauftrag enthält nicht freigegebene Felder")
    name_value = job.get("name")
    announcement_value = job.get("announcement")
    block_value = job.get("block_phone_hours")
    position_value = job.get("position")
    active_value = job.get("active")
    priority_value = job.get("priority")
    valid_from_value = job.get("valid_from", "")
    expires_at_value = job.get("expires_at", "")
    source_value = job.get("source")
    if not isinstance(name_value, str):
        raise WebAdminError("Name der Sonderansage fehlt")
    name = " ".join(name_value.split()).strip()
    if not name or len(name) > 100 or any(ord(character) < 32 for character in name):
        raise WebAdminError("Name der Sonderansage ist ungültig")
    if not isinstance(announcement_value, str):
        raise WebAdminError("TTS-Text der Sonderansage fehlt")
    announcement = announcement_value.strip()
    if not announcement or len(announcement) > 5000:
        raise WebAdminError("TTS-Text der Sonderansage ist ungültig")
    if not isinstance(block_value, bool):
        raise WebAdminError("Telefonzeitensperre der Sonderansage ist ungültig")
    if position_value not in {
        "statt_begruessung",
        "vor_begruessung",
        "nach_begruessung",
    }:
        raise WebAdminError("Position der Sonderansage ist ungültig")
    if not isinstance(active_value, bool):
        raise WebAdminError("Aktivstatus der Sonderansage ist ungültig")
    if (
        isinstance(priority_value, bool)
        or not isinstance(priority_value, int)
        or not 0 <= priority_value <= 1000
    ):
        raise WebAdminError("Priorität muss eine ganze Zahl zwischen 0 und 1000 sein")
    if source_value not in SOURCE_VALUES:
        raise WebAdminError("Audioquelle der Sonderansage ist ungültig")
    parsed_datetimes: dict[str, datetime | None] = {}
    for key, raw_value, label in (
        ("valid_from", valid_from_value, "Gültig ab"),
        ("expires_at", expires_at_value, "Ablaufdatum"),
    ):
        if not isinstance(raw_value, str):
            raise WebAdminError(f"{label} ist ungültig")
        text_value = raw_value.strip()
        if text_value and not LOCAL_DATETIME.fullmatch(text_value):
            raise WebAdminError(f"{label} ist ungültig")
        try:
            parsed_datetimes[key] = (
                datetime.fromisoformat(text_value) if text_value else None
            )
        except ValueError as exc:
            raise WebAdminError(f"{label} ist ungültig") from exc
    if (
        parsed_datetimes["valid_from"] is not None
        and parsed_datetimes["expires_at"] is not None
        and parsed_datetimes["valid_from"] >= parsed_datetimes["expires_at"]
    ):
        raise WebAdminError("Gültigkeitsbeginn muss vor dem Ablaufdatum liegen")
    result: dict[str, Any] = {
        "name": name,
        "announcement": announcement,
        "active": active_value,
        "priority": priority_value,
        "valid_from": str(valid_from_value).strip(),
        "expires_at": str(expires_at_value).strip(),
        "block_phone_hours": block_value,
        "position": position_value,
        "source": source_value,
    }
    preset_id = job.get("preset_id", "")
    if preset_id:
        if not isinstance(preset_id, str) or not PRESET_ID.fullmatch(preset_id):
            raise WebAdminError("Kennung der gespeicherten Sonderansage ist ungültig")
        result["preset_id"] = preset_id
    if recording:
        extension = job.get("extension")
        if not isinstance(extension, str):
            raise WebAdminError("Aufnahme-Nebenstelle fehlt")
        result["extension"] = extension
    return result


class WebAdminWorker:
    def __init__(
        self,
        *,
        config_path: Path = DEFAULT_CONFIG,
        defaults_path: Path = DEFAULT_DEFAULTS,
        web_config_path: Path = DEFAULT_WEB_CONFIG,
        runtime_path: Path = DEFAULT_RUNTIME,
        config_command: str = DEFAULT_CONFIG_COMMAND,
        prompts_command: str = DEFAULT_PROMPTS_COMMAND,
        record_command: str = DEFAULT_RECORD_COMMAND,
        asterisk_command: str = DEFAULT_ASTERISK_COMMAND,
        php_binary: str = "/usr/bin/php",
    ):
        self.config_path = config_path
        self.defaults_path = defaults_path
        self.web_config_path = web_config_path
        self.runtime_path = runtime_path
        self.inbox = runtime_path / "inbox"
        self.status_directory = runtime_path / "status"
        self.state_path = runtime_path / "state.json"
        self.auth_hash_path = runtime_path / "password.hash"
        self.lock_path = runtime_path / "worker.lock"
        self.audio_lock_path = runtime_path / "audio.lock"
        self.config_command = config_command
        self.prompts_command = prompts_command
        self.record_command = record_command
        self.asterisk_command = asterisk_command
        self.php_binary = php_binary

    def export(self) -> dict[str, Any]:
        return export_state(
            self.config_path,
            self.defaults_path,
            self.web_config_path,
            self.state_path,
            self.auth_hash_path,
            php_binary=self.php_binary,
        )

    def run_once(self) -> bool:
        self.runtime_path.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            jobs_with_times = []
            for path in self.inbox.glob("job-*.json"):
                try:
                    jobs_with_times.append((path.lstat().st_mtime_ns, path))
                except FileNotFoundError:
                    continue
            jobs = [path for _modified, path in sorted(jobs_with_times)]
            if not jobs:
                self.export()
                return False
            self._process_file(jobs[0])
            return True

    def _status(self, job_id: str, code: str, *, detail: str = "") -> None:
        if not JOB_ID.fullmatch(job_id):
            raise WebAdminError("Ungültige Auftragsnummer")
        write_json_atomic(
            self.status_directory / f"{job_id}.json",
            {
                "job_id": job_id,
                "code": code,
                "label": STATUS_LABELS[code],
                "detail": detail,
                "updated_at": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(
                    timespec="seconds"
                ),
            },
            mode=0o644,
        )

    def _process_file(self, path: Path) -> None:
        job_id = path.stem.removeprefix("job-")
        if not JOB_ID.fullmatch(job_id):
            path.unlink(missing_ok=True)
            return
        try:
            job = _read_job(path)
            if job.get("id") != job_id:
                raise WebAdminError("Auftragsnummer stimmt nicht mit dem Dateinamen überein")
            action = job.get("action")
            if action == "save":
                self._apply_save(job_id, job)
            elif action == "record":
                self._start_recording(job_id, job)
            elif action == "activate_candidate":
                self._activate_candidate(job_id, job)
            elif action == "regenerate_prompt":
                self._regenerate_prompt(job_id, job)
            elif action == "save_override_preset":
                self._save_override_preset(job_id, job)
            elif action == "record_override_preset":
                self._record_override_preset(job_id, job)
            elif action == "delete_override_preset":
                self._delete_override_preset(job_id, job)
            else:
                raise WebAdminError("Aktion ist nicht freigegeben")
        except Exception as exc:
            status_path = self.status_directory / f"{job_id}.json"
            current = _read_json(status_path) if status_path.is_file() else {}
            if current.get("code") not in {
                "ansagenerzeugung_fehlgeschlagen",
                "nebenstelle_nicht_erreichbar",
                "aufnahme_gespeichert",
                "aufnahme_verworfen",
                "vorlage_gespeichert",
                "vorlage_geloescht",
            }:
                self._status(job_id, "auftrag_abgelehnt", detail=str(exc))
        finally:
            path.unlink(missing_ok=True)

    def _temporary_config(self, text: str) -> Path:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self.config_path.name}.webadmin.", dir=self.config_path.parent
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            stat = self.config_path.stat()
            os.chmod(temporary, stat.st_mode & 0o777)
            os.chown(temporary, stat.st_uid, stat.st_gid)
            return temporary
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _validate_temporary(self, path: Path) -> None:
        result = _run_command([self.config_command, "--config", str(path)], timeout=60)
        if result.returncode != 0:
            raise WebAdminError(_command_error(result))

    def _replace_config(self, temporary: Path) -> None:
        os.replace(temporary, self.config_path)
        directory_fd = os.open(self.config_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _generate_prompts(
        self, job_id: str, *, arguments: tuple[str, ...] = ()
    ) -> None:
        self._status(job_id, "ansagen_werden_aktualisiert")
        try:
            with self.audio_lock_path.open("a+b") as audio_lock:
                fcntl.flock(audio_lock.fileno(), fcntl.LOCK_EX)
                result = self._run_prompts_with_progress(
                    job_id,
                    timeout=14_400,
                    arguments=arguments,
                )
        except Exception as exc:
            self._status(job_id, "ansagenerzeugung_fehlgeschlagen", detail=str(exc))
            raise
        if result.returncode != 0:
            self._status(
                job_id, "ansagenerzeugung_fehlgeschlagen", detail=_command_error(result)
            )
            raise WebAdminError("Ansagenerzeugung fehlgeschlagen")
        self._status(job_id, "ansagen_aktuell")

    def _run_prompts_with_progress(
        self,
        job_id: str,
        *,
        timeout: int,
        arguments: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[bytes]:
        command = [
            self.prompts_command,
            "--config",
            str(self.config_path),
            "--machine-progress",
            *arguments,
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            raise WebAdminError(
                f"Programm konnte nicht sicher ausgeführt werden: {command[0]}: {exc}"
            ) from exc

        assert process.stdout is not None
        captured = bytearray()
        pending = bytearray()
        deadline = time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                for key, _events in selector.select(timeout=min(1.0, remaining)):
                    chunk = os.read(key.fd, 65_536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    captured.extend(chunk)
                    if len(captured) > 65_536:
                        del captured[:-65_536]
                    pending.extend(chunk)
                    while b"\n" in pending:
                        raw_line, _, remainder = pending.partition(b"\n")
                        pending = bytearray(remainder)
                        self._consume_prompt_progress(job_id, raw_line)
                    if len(pending) > 16_384:
                        del pending[:-16_384]
            remaining = max(0.1, deadline - time.monotonic())
            returncode = process.wait(timeout=remaining)
            if pending:
                self._consume_prompt_progress(job_id, bytes(pending))
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise WebAdminError(
                f"Ansagenerzeugung hat das Zeitlimit von {timeout} Sekunden überschritten"
            ) from exc
        finally:
            selector.close()
            process.stdout.close()
        return subprocess.CompletedProcess(command, returncode, bytes(captured), b"")

    def _regenerate_prompt(self, job_id: str, job: Mapping[str, Any]) -> None:
        allowed = {"action", "id", "config_hash", "prompt"}
        if set(job) - allowed:
            raise WebAdminError("Auftrag enthält nicht freigegebene Felder")
        if str(job.get("config_hash", "")) != _config_hash(self.config_path):
            raise WebAdminError("Die Konfiguration wurde zwischenzeitlich geändert")
        name = str(job.get("prompt", ""))
        config = load_config(self.config_path)
        if not PROMPT_NAME.fullmatch(name) or name not in rendered_prompts(config):
            raise WebAdminError("Unbekannte Ansage")
        if config.tts.engine != "qwen":
            raise WebAdminError(
                "Eine neue TTS-Variante ist nur mit Qwen3-TTS verfügbar"
            )
        scheduled = next(
            (
                entry
                for entry in config.scheduled_overrides
                if entry.prompt_name == name
            ),
            None,
        )
        manual_active = (
            scheduled.source == "manuell"
            if scheduled is not None
            else PromptGenerator(config)._manual_source(name) is not None
        )
        if manual_active:
            raise WebAdminError(
                "Für diese Ansage ist eine manuelle Aufnahme aktiv; bitte zuerst TTS wählen"
            )
        try:
            self._generate_prompts(
                job_id,
                arguments=("--prompt", name, "--new-variant"),
            )
        finally:
            self.export()

    def _consume_prompt_progress(self, job_id: str, raw_line: bytes) -> None:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith(PROMPT_PROGRESS_PREFIX):
            return
        try:
            event = json.loads(line.removeprefix(PROMPT_PROGRESS_PREFIX))
            if not isinstance(event, Mapping):
                return
            current = int(event.get("current", 0))
            total = int(event.get("total", 0))
            phase = str(event.get("phase", ""))
            name = str(event.get("name", ""))[:100]
            supplied_label = str(event.get("label", ""))[:100]
        except (ValueError, TypeError, json.JSONDecodeError):
            return
        if current < 0 or total < 0 or current > total:
            return
        label = supplied_label or _prompt_label(name)
        counter = f"{current}/{total}" if total else "0/0"
        details = {
            "plan": (
                f"{total} Verarbeitungsschritt(e) erforderlich."
                if total
                else "Keine Ansage muss neu erzeugt werden."
            ),
            "qwen_prepare": "Whisper-Worker wird für Qwen3-TTS vorbereitet.",
            "qwen_ready": "Whisper-Worker ist beendet; Qwen3-TTS arbeitet jetzt.",
            "generate": f"Automatische Ansage wird erzeugt: {label}",
            "manual": f"Manuelle Ansage wird verarbeitet: {label}",
            "scheduled_tts": f"TTS-Fassung der Sonderansage wird erzeugt: {label}",
            "qwen_restore": "Ansagen fertig; Whisper-Worker wird wieder gestartet.",
            "complete": "Ansagenverarbeitung abgeschlossen.",
        }
        detail = details.get(phase)
        if detail is not None:
            self._status(
                job_id,
                "ansagen_werden_aktualisiert",
                detail=f"[{counter}] {detail}",
            )

    def _apply_save(self, job_id: str, job: Mapping[str, Any]) -> None:
        config = load_config(self.config_path)
        values = _validate_save_request(job, config)
        if values["config_hash"] != _config_hash(self.config_path):
            raise WebAdminError(
                "Die Konfiguration wurde zwischenzeitlich geändert. Bitte Seite neu laden."
        )
        self._status(job_id, "konfiguration_wird_geprueft")
        text = self.config_path.read_text(encoding="utf-8")
        temporary: Path | None = None
        active_manual: Path | None = None
        previous_manual: bytes | None = None
        previous_manual_stat: os.stat_result | None = None
        try:
            preset_id = values["override"].get("manual_preset_id")
            if preset_id:
                source = _preset_directory(config, str(preset_id)) / "manuell.wav"
                if not source.is_file() or source.is_symlink():
                    raise WebAdminError("Gespeicherte manuelle Sonderansage fehlt")
                active_manual = config.tts.upload_directory / "override.wav16"
                active_manual.parent.mkdir(parents=True, exist_ok=True)
                if active_manual.is_file():
                    previous_manual = active_manual.read_bytes()
                    previous_manual_stat = active_manual.stat()
                    archive = config.tts.upload_directory / "inaktiv"
                    archive.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now(config.practice.timezone).strftime(
                        "%Y%m%d_%H%M%S_%f"
                    )
                    _write_bytes_atomic(
                        archive / f"override_{stamp}.wav16",
                        previous_manual,
                        None,
                    )
                _write_bytes_atomic(
                    active_manual, source.read_bytes(), previous_manual_stat
                )
            temporary = self._temporary_config(_render_updated_config(text, values))
            self._validate_temporary(temporary)
            self._replace_config(temporary)
        except Exception:
            if active_manual is not None:
                if previous_manual is None:
                    active_manual.unlink(missing_ok=True)
                else:
                    _write_bytes_atomic(
                        active_manual, previous_manual, previous_manual_stat
                    )
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._status(job_id, "einstellungen_gespeichert")
        try:
            self._generate_prompts(job_id)
        finally:
            self.export()

    def _activate_candidate(self, job_id: str, job: Mapping[str, Any]) -> None:
        allowed = {"action", "id", "config_hash", "prompt"}
        if set(job) - allowed:
            raise WebAdminError("Auftrag enthält nicht freigegebene Felder")
        if str(job.get("config_hash", "")) != _config_hash(self.config_path):
            raise WebAdminError("Die Konfiguration wurde zwischenzeitlich geändert")
        name = str(job.get("prompt", ""))
        config = load_config(self.config_path)
        if not PROMPT_NAME.fullmatch(name) or name not in rendered_prompts(config):
            raise WebAdminError("Unbekannte Ansage")
        candidate = _candidate_path(config, name)
        if not candidate.is_file():
            raise WebAdminError("Es liegt keine Kandidatenaufnahme vor")
        active = config.tts.upload_directory / f"{name}.wav16"
        active.parent.mkdir(parents=True, exist_ok=True)
        previous_config = self.config_path.read_bytes()
        previous_manual = active.read_bytes() if active.is_file() else None
        if previous_manual is not None:
            archive = config.tts.upload_directory / "inaktiv"
            archive.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(config.practice.timezone).strftime("%Y%m%d_%H%M%S_%f")
            _write_bytes_atomic(
                archive / f"{name}_{stamp}.wav16",
                previous_manual,
                None,
            )
        staged_manual = active.with_name(f".{active.name}.new.{os.getpid()}")
        shutil.copyfile(candidate, staged_manual)
        os.chmod(staged_manual, 0o640)
        updated = _set_toml_value(
            previous_config.decode("utf-8"), "ansagen_quellen", name, "manuell"
        )
        temporary = self._temporary_config(updated)
        try:
            self._status(job_id, "konfiguration_wird_geprueft")
            self._validate_temporary(temporary)
            os.replace(staged_manual, active)
            self._replace_config(temporary)
            self._status(job_id, "einstellungen_gespeichert")
            self._generate_prompts(job_id)
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception:
            _write_bytes_atomic(self.config_path, previous_config, self.config_path.stat())
            if previous_manual is None:
                active.unlink(missing_ok=True)
            else:
                metadata = active.stat() if active.exists() else None
                _write_bytes_atomic(active, previous_manual, metadata)
            raise
        finally:
            temporary.unlink(missing_ok=True)
            staged_manual.unlink(missing_ok=True)
            self.export()

    def _start_recording(self, job_id: str, job: Mapping[str, Any]) -> None:
        allowed = {"action", "id", "prompt", "extension"}
        if set(job) - allowed:
            raise WebAdminError("Auftrag enthält nicht freigegebene Felder")
        config = load_config(self.config_path)
        name = str(job.get("prompt", ""))
        extension = str(job.get("extension", ""))
        if not PROMPT_NAME.fullmatch(name) or name not in rendered_prompts(config):
            raise WebAdminError("Unbekannte Ansage")
        self._record_candidate(job_id, name, extension, config)
        self.export()

    def _record_candidate(
        self, job_id: str, name: str, extension: str, config: AppConfig
    ) -> str:
        allowed_extensions = set(config.local_extensions) - {
            config.announcement_ivr.extension
        }
        if extension not in allowed_extensions:
            raise WebAdminError("Nebenstelle ist nicht freigegeben")
        fixed_values = (
            str(config.tts.upload_directory),
            str(config.paths.prompts),
            str(self.status_directory),
            self.record_command,
        )
        if any("," in value or "\n" in value or "\r" in value for value in fixed_values):
            raise WebAdminError("Installationspfad ist für Asterisk ungeeignet")
        app_data = ",".join(
            (
                self.record_command,
                "--prompt",
                name,
                "--job",
                job_id,
                "--upload-dir",
                str(config.tts.upload_directory),
                "--prompts-dir",
                str(config.paths.prompts),
                "--status-dir",
                str(self.status_directory),
                "--silence",
                str(config.announcement_ivr.silence_seconds),
                "--max-seconds",
                str(config.announcement_ivr.max_seconds),
                "--session-seconds",
                str(RECORD_SESSION_SECONDS),
                "--target-lufs",
                str(config.tts.target_loudness_lufs),
                "--peak-db",
                str(config.tts.max_true_peak_db),
            )
        )
        self._status(job_id, "nebenstelle_wird_angerufen")
        command = [
            self.asterisk_command,
            "-rx",
            f"channel originate PJSIP/{extension} application AGI {app_data}",
        ]
        with self.audio_lock_path.open("a+b") as audio_lock:
            fcntl.flock(audio_lock.fileno(), fcntl.LOCK_EX)
            result = _run_command(command, timeout=15)
            if result.returncode != 0:
                self._status(
                    job_id, "nebenstelle_nicht_erreichbar", detail=_command_error(result)
                )
                return "nebenstelle_nicht_erreichbar"
            else:
                status_path = self.status_directory / f"{job_id}.json"
                deadline = (
                    time.monotonic()
                    + RECORD_SESSION_SECONDS
                    + config.announcement_ivr.max_seconds
                    + 75
                )
                answer_deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    current = _read_json(status_path) if status_path.is_file() else {}
                    code = current.get("code")
                    if code in {"aufnahme_gespeichert", "aufnahme_verworfen"}:
                        return str(code)
                    if code == "nebenstelle_wird_angerufen" and time.monotonic() >= answer_deadline:
                        self._status(job_id, "nebenstelle_nicht_erreichbar")
                        return "nebenstelle_nicht_erreichbar"
                    time.sleep(0.25)
                else:
                    self._status(job_id, "aufnahme_verworfen", detail="Aufnahmezeit überschritten")
                    return "aufnahme_verworfen"
        return "aufnahme_verworfen"

    def _save_override_preset_data(
        self,
        job_id: str,
        values: Mapping[str, Any],
        config: AppConfig,
        *,
        recording: bool = False,
    ) -> tuple[str, bool]:
        root = _preset_root(config)
        if root.exists() and (not root.is_dir() or root.is_symlink()):
            raise WebAdminError("Ablage der gespeicherten Sonderansagen ist unsicher")
        root.mkdir(parents=True, exist_ok=True)
        existing = _read_override_presets(config)
        requested_id = str(values.get("preset_id", ""))
        if requested_id:
            if not any(item["id"] == requested_id for item in existing):
                raise WebAdminError("Gespeicherte Sonderansage wurde nicht gefunden")
            preset_id = requested_id
        else:
            same_name = next(
                (
                    item
                    for item in existing
                    if item["name"].casefold() == str(values["name"]).casefold()
                ),
                None,
            )
            preset_id = str(same_name["id"]) if same_name else secrets.token_hex(16)
        collision = next(
            (
                item
                for item in existing
                if item["name"].casefold() == str(values["name"]).casefold()
                and item["id"] != preset_id
            ),
            None,
        )
        if collision is not None:
            raise WebAdminError("Eine Sonderansage mit diesem Namen ist bereits gespeichert")
        priority_collision = next(
            (
                item
                for item in existing
                if values["active"]
                and item["active"]
                and item["priority"] == values["priority"]
                and item["id"] != preset_id
            ),
            None,
        )
        if priority_collision is not None:
            raise WebAdminError(
                "Die Priorität wird bereits von der aktiven Sonderansage "
                f"„{priority_collision['name']}“ verwendet"
            )

        directory = _preset_directory(config, preset_id)
        if directory.exists() and (not directory.is_dir() or directory.is_symlink()):
            raise WebAdminError("Ablage der gespeicherten Sonderansage ist unsicher")
        existed = directory.is_dir()
        regenerate_tts = True
        metadata_path = directory / "metadata.json"
        tts_path = directory / "tts.wav"
        if (
            existed
            and metadata_path.is_file()
            and not metadata_path.is_symlink()
            and tts_path.is_file()
            and not tts_path.is_symlink()
        ):
            previous_metadata = _read_json(metadata_path)
            regenerate_tts = (
                str(previous_metadata.get("announcement", "")).strip()
                != str(values["announcement"]).strip()
            )
        manual_bytes: bytes | None = None
        manual = directory / "manuell.wav"
        if manual.is_file() and not manual.is_symlink():
            manual_bytes = manual.read_bytes()
        elif values["source"] == "manuell" and not recording:
            current_candidate = _candidate_path(config, "override")
            current_manual = _manual_path(config, "override")
            source = (
                current_candidate
                if current_candidate.is_file() and not current_candidate.is_symlink()
                else current_manual
            )
            if source is None or not source.is_file() or source.is_symlink():
                raise WebAdminError(
                    "Für diese Sonderansage liegt keine manuelle Aufnahme vor"
                )
            manual_bytes = source.read_bytes()
        source_value = str(values["source"])
        if recording and manual_bytes is None:
            source_value = "tts"
        pending_activation = bool(values["active"]) and (
            not existed or (recording and manual_bytes is None)
        )
        self._status(job_id, "vorlage_wird_gespeichert")
        with self.audio_lock_path.open("a+b") as audio_lock:
            fcntl.flock(audio_lock.fileno(), fcntl.LOCK_EX)
            directory.mkdir(mode=0o750, parents=False, exist_ok=True)
            if regenerate_tts:
                with tempfile.TemporaryDirectory(
                    prefix=f".sonderansage-{preset_id}-", dir=root
                ) as temporary_name:
                    generated = Path(temporary_name) / "tts.wav"
                    PromptGenerator(config).synthesize_text_file(
                        str(values["announcement"]),
                        generated,
                        f"sonderansage-{preset_id[:8]}",
                    )
                    _write_bytes_atomic(tts_path, generated.read_bytes(), None)
            if manual_bytes is not None:
                _write_bytes_atomic(directory / "manuell.wav", manual_bytes, None)
            write_json_atomic(
                metadata_path,
                {
                    "name": values["name"],
                    "announcement": values["announcement"],
                    "active": bool(values["active"]) and not pending_activation,
                    "priority": values["priority"],
                    "valid_from": values["valid_from"],
                    "expires_at": values["expires_at"],
                    "block_phone_hours": values["block_phone_hours"],
                    "position": values["position"],
                    "source": source_value,
                    "updated_at": datetime.now(config.practice.timezone).isoformat(
                        timespec="seconds"
                    ),
                },
                mode=0o640,
            )
        return preset_id, pending_activation

    def _update_override_preset_metadata(
        self, config: AppConfig, preset_id: str, **updates: Any
    ) -> None:
        directory = _preset_directory(config, preset_id)
        metadata_path = directory / "metadata.json"
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or not metadata_path.is_file()
            or metadata_path.is_symlink()
        ):
            raise WebAdminError("Gespeicherte Sonderansage wurde nicht gefunden")
        metadata = _read_json(metadata_path)
        metadata.update(updates)
        metadata["updated_at"] = datetime.now(config.practice.timezone).isoformat(
            timespec="seconds"
        )
        write_json_atomic(metadata_path, metadata, mode=0o640)

    def _save_override_preset(self, job_id: str, job: Mapping[str, Any]) -> None:
        config = load_config(self.config_path)
        values = _validate_preset_request(job, recording=False)
        preset_id, pending_activation = self._save_override_preset_data(
            job_id, values, config
        )
        try:
            self._generate_prompts(job_id)
            if pending_activation:
                self._update_override_preset_metadata(
                    config, preset_id, active=bool(values["active"])
                )
            self._status(job_id, "vorlage_gespeichert")
        finally:
            self.export()

    def _record_override_preset(self, job_id: str, job: Mapping[str, Any]) -> None:
        config = load_config(self.config_path)
        values = _validate_preset_request(job, recording=True)
        allowed_extensions = set(config.local_extensions) - {
            config.announcement_ivr.extension
        }
        if values["extension"] not in allowed_extensions:
            raise WebAdminError("Nebenstelle ist nicht freigegeben")
        requested_active = bool(values["active"])
        values = {**values, "source": "manuell"}
        preset_id, _pending_activation = self._save_override_preset_data(
            job_id, values, config, recording=True
        )
        self._generate_prompts(job_id)
        recording_name = f"preset_{preset_id}"
        result = self._record_candidate(
            job_id, recording_name, str(values["extension"]), config
        )
        if result == "aufnahme_gespeichert":
            try:
                candidate = _candidate_path(config, recording_name)
                if not candidate.is_file() or candidate.is_symlink():
                    raise WebAdminError("Gespeicherte Aufnahme wurde nicht gefunden")
                _write_bytes_atomic(
                    _preset_directory(config, preset_id) / "manuell.wav",
                    candidate.read_bytes(),
                    None,
                )
                candidate.unlink(missing_ok=True)
                self._update_override_preset_metadata(
                    config, preset_id, source="manuell", active=False
                )
                self._generate_prompts(job_id)
                if requested_active:
                    self._update_override_preset_metadata(
                        config, preset_id, active=True
                    )
                self._status(job_id, "vorlage_gespeichert")
            except Exception as exc:
                self._status(job_id, "auftrag_abgelehnt", detail=str(exc))
                raise
        self.export()

    def _delete_override_preset(self, job_id: str, job: Mapping[str, Any]) -> None:
        allowed = {"action", "id", "preset_id"}
        if set(job) - allowed:
            raise WebAdminError("Löschauftrag enthält nicht freigegebene Felder")
        preset_id = str(job.get("preset_id", ""))
        config = load_config(self.config_path)
        directory = _preset_directory(config, preset_id)
        if not directory.is_dir() or directory.is_symlink():
            raise WebAdminError("Gespeicherte Sonderansage wurde nicht gefunden")
        archive = _preset_root(config) / ".geloescht"
        if archive.exists() and (not archive.is_dir() or archive.is_symlink()):
            raise WebAdminError("Löscharchiv ist unsicher")
        archive.mkdir(mode=0o750, parents=True, exist_ok=True)
        stamp = datetime.now(config.practice.timezone).strftime("%Y%m%d_%H%M%S_%f")
        os.replace(directory, archive / f"{preset_id}-{stamp}")
        try:
            self._generate_prompts(job_id)
            self._status(job_id, "vorlage_geloescht")
        finally:
            self.export()


def _write_bytes_atomic(path: Path, value: bytes, stat: os.stat_result | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.restore.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, (stat.st_mode & 0o777) if stat else 0o640)
        if stat:
            os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _record_status(status_directory: Path, job_id: str, code: str, detail: str = "") -> None:
    write_json_atomic(
        status_directory / f"{job_id}.json",
        {
            "job_id": job_id,
            "code": code,
            "label": STATUS_LABELS[code],
            "detail": detail,
            "updated_at": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(
                timespec="seconds"
            ),
        },
        mode=0o644,
    )


def record_announcement(
    channel: AgiChannel,
    *,
    prompt: str,
    job_id: str,
    upload_directory: Path,
    prompts_directory: Path,
    status_directory: Path,
    silence_seconds: int,
    max_seconds: int,
    target_lufs: float,
    peak_db: float,
    session_seconds: int,
) -> None:
    if not PROMPT_NAME.fullmatch(prompt) or not JOB_ID.fullmatch(job_id):
        raise WebAdminError("Ungültige Aufnahmeparameter")
    candidate = upload_directory / "kandidaten" / f"{prompt}.wav16"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    raw = candidate.with_name(f".{candidate.stem}.raw.{os.getpid()}.wav16")
    accepted = False
    session_deadline = time.monotonic() + session_seconds
    try:
        while True:
            if time.monotonic() >= session_deadline:
                _record_status(
                    status_directory,
                    job_id,
                    "aufnahme_verworfen",
                    "Maximale Dauer des Aufnahmevorgangs überschritten",
                )
                channel.stream_file(prompts_directory / "webadmin_record_discarded")
                return
            raw.unlink(missing_ok=True)
            _record_status(status_directory, job_id, "aufnahme_laeuft")
            channel.stream_file(prompts_directory / "webadmin_record")
            result = channel.record(
                raw,
                silence_seconds=silence_seconds,
                max_seconds=max_seconds,
                beep=True,
                terminate_any_digit=False,
            )
            if result.status == "ERROR" or not result.present:
                raise WebAdminError(f"Aufnahme fehlgeschlagen: {result.status}")
            PromptGenerator.normalize_audio_file(
                raw,
                candidate,
                f"webaufnahme-{prompt}",
                target_lufs=target_lufs,
                peak_db=peak_db,
            )
            channel.stream_file(candidate.with_suffix(""))
            while True:
                if time.monotonic() >= session_deadline:
                    candidate.unlink(missing_ok=True)
                    _record_status(
                        status_directory,
                        job_id,
                        "aufnahme_verworfen",
                        "Maximale Dauer des Aufnahmevorgangs überschritten",
                    )
                    channel.stream_file(prompts_directory / "webadmin_record_discarded")
                    return
                digit = channel.get_option(
                    prompts_directory / "webadmin_record_actions", "123", 5000
                )
                if digit == "1":
                    accepted = True
                    _record_status(status_directory, job_id, "aufnahme_gespeichert")
                    channel.stream_file(prompts_directory / "webadmin_record_saved")
                    return
                if digit == "2":
                    candidate.unlink(missing_ok=True)
                    break
                if digit == "3":
                    candidate.unlink(missing_ok=True)
                    _record_status(status_directory, job_id, "aufnahme_verworfen")
                    channel.stream_file(prompts_directory / "webadmin_record_discarded")
                    return
    finally:
        raw.unlink(missing_ok=True)
        if not accepted:
            candidate.unlink(missing_ok=True)


def _common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--defaults", type=Path, default=DEFAULT_DEFAULTS)
    parser.add_argument("--web-config", type=Path, default=DEFAULT_WEB_CONFIG)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--config-command", default=DEFAULT_CONFIG_COMMAND)
    parser.add_argument("--prompts-command", default=DEFAULT_PROMPTS_COMMAND)
    parser.add_argument("--record-command", default=DEFAULT_RECORD_COMMAND)
    parser.add_argument("--asterisk-command", default=DEFAULT_ASTERISK_COMMAND)
    parser.add_argument("--php-binary", default="/usr/bin/php")
    return parser


def worker_main() -> None:
    arguments = _common_parser("Kienzlefon Webinterface-Auftrag verarbeiten").parse_args()
    worker = WebAdminWorker(
        config_path=arguments.config,
        defaults_path=arguments.defaults,
        web_config_path=arguments.web_config,
        runtime_path=arguments.runtime,
        config_command=arguments.config_command,
        prompts_command=arguments.prompts_command,
        record_command=arguments.record_command,
        asterisk_command=arguments.asterisk_command,
        php_binary=arguments.php_binary,
    )
    raise SystemExit(0 if worker.run_once() else 0)


def export_main() -> None:
    arguments = _common_parser("Kienzlefon Webinterface-Ansicht aktualisieren").parse_args()
    WebAdminWorker(
        config_path=arguments.config,
        defaults_path=arguments.defaults,
        web_config_path=arguments.web_config,
        runtime_path=arguments.runtime,
        config_command=arguments.config_command,
        prompts_command=arguments.prompts_command,
        record_command=arguments.record_command,
        asterisk_command=arguments.asterisk_command,
        php_binary=arguments.php_binary,
    ).export()


def record_main() -> None:
    parser = argparse.ArgumentParser(description="Kienzlefon Webinterface-Telefonaufnahme")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--upload-dir", type=Path, required=True)
    parser.add_argument("--prompts-dir", type=Path, required=True)
    parser.add_argument("--status-dir", type=Path, required=True)
    parser.add_argument("--silence", type=int, required=True)
    parser.add_argument("--max-seconds", type=int, required=True)
    parser.add_argument("--session-seconds", type=int, default=RECORD_SESSION_SECONDS)
    parser.add_argument("--target-lufs", type=float, required=True)
    parser.add_argument("--peak-db", type=float, required=True)
    arguments = parser.parse_args()
    channel = AgiChannel()
    try:
        record_announcement(
            channel,
            prompt=arguments.prompt,
            job_id=arguments.job,
            upload_directory=arguments.upload_dir,
            prompts_directory=arguments.prompts_dir,
            status_directory=arguments.status_dir,
            silence_seconds=arguments.silence,
            max_seconds=arguments.max_seconds,
            target_lufs=arguments.target_lufs,
            peak_db=arguments.peak_db,
            session_seconds=arguments.session_seconds,
        )
    except AgiHangup:
        _record_status(arguments.status_dir, arguments.job, "aufnahme_verworfen")
    except Exception as exc:
        _record_status(arguments.status_dir, arguments.job, "aufnahme_verworfen", str(exc))
        raise
