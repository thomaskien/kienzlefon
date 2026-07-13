# kienzlefon
# Version: 1.8.2
# Changelog:
# - 1.8.2: Bereitschaftsdienst auch vor der ersten Tagesoeffnung aktiviert.
# - 1.8: Expliziten Telepraxis-Demomodus ohne Public Key ergaenzt.
# - 1.7: Optionales rotes Telefon und priorisierte Sonderqueue konfigurierbar gemacht.
# - 1.6: Getrennte Whisper-Modelle und Initial-Prompts je Feldgruppe ergaenzt.
# - 1.5: Konfigurierbare Ziellautheit und True-Peak-Grenze ergaenzt.
# - 1.4: PIN-freies internes Ansagen-IVR und klare deutsche Menuebausteine umgesetzt.
# - 1.3: Ansagen-IVR, Zusatztelefone und konfigurierbare Wahlregeln ergaenzt.
# - 1.2: Versionsbezogene Validierungsmeldungen aktualisiert.
# - 1.1: TTS-Pausen sowie IVR- und Notfalltelefonparameter ergaenzt.
# - 1.0: Zentrale TOML-Konfiguration mit Zeitprofilen und strenger Validierung.

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .models import CallType, FieldName

SUPPORTED_WHISPER_MODELS = frozenset({"large-v3-turbo", "large-v3"})
DEFAULT_MENU_INTRO = (
    "Bitte wählen Sie nun durch Tastendruck auf Ihrem Telefon eine der folgenden Möglichkeiten."
)
WEEKDAYS = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")
UNKNOWN_CALLER_IDS = frozenset(
    {"", "anonymous", "unknown", "unavailable", "private", "restricted", "withheld"}
)
TIME_RANGE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


class ConfigError(ValueError):
    """Raised when a required or safety-relevant setting is invalid."""


@dataclass(frozen=True)
class TimeWindow:
    start: time
    end: time

    def contains(self, value: time) -> bool:
        return self.start <= value < self.end


@dataclass(frozen=True)
class WeeklySchedule:
    days: tuple[tuple[TimeWindow, ...], ...]

    def windows_for(self, weekday: int) -> tuple[TimeWindow, ...]:
        return self.days[weekday]

    def is_active(self, value: datetime) -> bool:
        local_time = value.timetz().replace(tzinfo=None)
        return any(window.contains(local_time) for window in self.windows_for(value.weekday()))

    def after_last_window(self, value: datetime) -> bool:
        windows = self.windows_for(value.weekday())
        if not windows:
            return True
        local_time = value.timetz().replace(tzinfo=None)
        return local_time >= windows[-1].end

    def before_first_or_after_last_window(self, value: datetime) -> bool:
        windows = self.windows_for(value.weekday())
        if not windows:
            return True
        local_time = value.timetz().replace(tzinfo=None)
        return local_time < windows[0].start or local_time >= windows[-1].end


@dataclass(frozen=True)
class PathsConfig:
    spool: Path
    runtime: Path
    prompts: Path
    prompt_masters: Path


@dataclass(frozen=True)
class PracticeConfig:
    name: str
    timezone: ZoneInfo


@dataclass(frozen=True)
class OverrideConfig:
    active: bool
    announcement: str
    block_phone_hours: bool


@dataclass(frozen=True)
class IVRConfig:
    attempts: int
    digit_timeout_ms: int
    announcement_pause_ms: int
    queue_name: str
    queue_context: str
    pharmacy_priority: int
    red_enabled: bool
    red_extension: str
    red_ring_seconds: int
    red_fallback_priority: int
    specialist_announcement: bool


@dataclass(frozen=True)
class RecordingConfig:
    format: str
    short_silence_seconds: int
    long_silence_seconds: int
    short_max_seconds: int
    long_max_seconds: int
    stale_seconds: int


@dataclass(frozen=True)
class WhisperConfig:
    standard_model: str
    name_model: str
    medication_model: str
    first_name_prompt: str
    last_name_prompt: str
    medication_prompt: str
    model_directory: Path
    device: str
    compute_type: str
    cpu_threads: int
    beam_size: int
    language: str
    poll_seconds: float
    heartbeat_seconds: int
    stale_heartbeat_seconds: int
    max_attempts: int

    @property
    def models(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.standard_model, self.name_model, self.medication_model)))

    def model_for(self, field: FieldName | str) -> str:
        value = field.value if isinstance(field, FieldName) else str(field)
        if value in {FieldName.FIRST_NAME.value, FieldName.LAST_NAME.value}:
            return self.name_model
        if value == FieldName.MEDICATION.value:
            return self.medication_model
        return self.standard_model

    def initial_prompt_for(self, field: FieldName | str) -> str | None:
        value = field.value if isinstance(field, FieldName) else str(field)
        prompts = {
            FieldName.FIRST_NAME.value: self.first_name_prompt,
            FieldName.LAST_NAME.value: self.last_name_prompt,
            FieldName.MEDICATION.value: self.medication_prompt,
        }
        return prompts.get(value) or None


@dataclass(frozen=True)
class TelepraxisConfig:
    channel: str
    output_directory: Path
    demo: bool
    public_key: Path | None


@dataclass(frozen=True)
class TTSConfig:
    engine: str
    voice: str
    voice_directory: Path
    upload_directory: Path
    volume: float
    length_scale: float
    sentence_silence: float
    target_loudness_lufs: float
    max_true_peak_db: float


@dataclass(frozen=True)
class SipLineConfig:
    enabled: bool
    did: str
    user: str
    password: str
    domain: str
    outbound_proxy: str
    expiration: int
    use_for_outbound: bool


@dataclass(frozen=True)
class AsteriskConfig:
    red_password: str
    phone_transport: str
    main_outbound_endpoint: str
    main_outbound_number: str
    outbound_counts_capacity: bool
    first_queue_extension: int
    queue_extension_count: int
    direct_queue: SipLineConfig
    direct_red: SipLineConfig


@dataclass(frozen=True)
class AnnouncementIVRConfig:
    extension: str
    silence_seconds: int
    max_seconds: int
    audit_log: Path


@dataclass(frozen=True)
class StandaloneExtensionConfig:
    extension: str
    password: str


@dataclass(frozen=True)
class SpecialQueueConfig:
    name: str
    weight: int
    additional_extensions: tuple[str, ...]


@dataclass(frozen=True)
class DialRulesConfig:
    country_code: str
    area_code: str
    practice_number: str
    minimum_external_digits: int
    block_international: bool
    block_0900: bool
    block_0137: bool
    block_118: bool
    block_019: bool
    block_0180: bool
    block_0700: bool
    block_032: bool
    audit_log: Path


@dataclass(frozen=True)
class PromptConfig:
    values: Mapping[str, str]

    def __getitem__(self, key: str) -> str:
        try:
            return self.values[key]
        except KeyError as exc:
            raise ConfigError(f"Fehlender Ansagetext: [ansagen].{key}") from exc


@dataclass(frozen=True)
class AppConfig:
    source: Path
    paths: PathsConfig
    practice: PracticeConfig
    override: OverrideConfig
    ivr: IVRConfig
    recording: RecordingConfig
    whisper: WhisperConfig
    telepraxis: TelepraxisConfig
    tts: TTSConfig
    asterisk: AsteriskConfig
    announcement_ivr: AnnouncementIVRConfig
    standalone_extensions: tuple[StandaloneExtensionConfig, ...]
    special_queue: SpecialQueueConfig
    dial_rules: DialRulesConfig
    prompts: PromptConfig
    opening_hours: WeeklySchedule
    phone_hours: WeeklySchedule
    pharmacy_hours: WeeklySchedule
    specialist_hours: WeeklySchedule

    @property
    def local_extensions(self) -> tuple[str, ...]:
        first = self.asterisk.first_queue_extension
        values = [
            str(extension)
            for extension in range(first, first + self.asterisk.queue_extension_count)
        ]
        if self.ivr.red_enabled:
            values.append(self.ivr.red_extension)
        values.append(self.announcement_ivr.extension)
        values.extend(entry.extension for entry in self.standalone_extensions)
        return tuple(dict.fromkeys(values))

    def now(self) -> datetime:
        return datetime.now(self.practice.timezone)

    def practice_is_open(self, value: datetime | None = None) -> bool:
        current = _localize(value or self.now(), self.practice.timezone)
        return self.opening_hours.is_active(current)

    def phone_is_open(self, value: datetime | None = None) -> bool:
        if self.override.active and self.override.block_phone_hours:
            return False
        current = _localize(value or self.now(), self.practice.timezone)
        return self.phone_hours.is_active(current)

    def urgent_help_is_active(self, value: datetime | None = None) -> bool:
        current = _localize(value or self.now(), self.practice.timezone)
        return self.opening_hours.before_first_or_after_last_window(current)

    def pharmacy_is_available(self, value: datetime | None = None) -> bool:
        current = _localize(value or self.now(), self.practice.timezone)
        return self.pharmacy_hours.is_active(current)

    def specialist_is_available(self, value: datetime | None = None) -> bool:
        current = _localize(value or self.now(), self.practice.timezone)
        return self.specialist_hours.is_active(current)


REQUIRED_PROMPTS = frozenset(
    {
        "greeting_open",
        "greeting_closed",
        "emergency",
        "urgent_help",
        "menu_intro",
        "menu_open",
        "menu_closed",
        "pharmacy_access",
        "specialist_access",
        "opening_hours_choice",
        "opening_hours_prefix",
        "opening_hours_closed",
        "phone_hours_prefix",
        "phone_hours_closed",
        "phone_hours",
        "submenu_five",
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
        "no_selection_open",
        "no_selection_closed",
        "invalid",
        "completed",
        "whisper_failure",
        "prescription_information",
        "pharmacy_agent",
        "specialist_agent",
        "personal_data_fallback",
        "blocked_destination",
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
    }
)


def _localize(value: datetime, timezone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def _section(raw: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = raw.get(name)
    if not isinstance(value, Mapping):
        raise ConfigError(f"Fehlender Konfigurationsabschnitt [{name}]")
    return value


def _required(section: Mapping[str, Any], key: str, section_name: str) -> Any:
    if key not in section:
        raise ConfigError(f"Fehlende Einstellung [{section_name}].{key}")
    return section[key]


def _path(base: Path, value: Any) -> Path:
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _schedule(raw: Mapping[str, Any], name: str) -> WeeklySchedule:
    section = _section(raw, name)
    days: list[tuple[TimeWindow, ...]] = []
    for day in WEEKDAYS:
        values = section.get(day, [])
        if not isinstance(values, list):
            raise ConfigError(f"[{name}].{day} muss eine Liste von Zeitraeumen sein")
        windows: list[TimeWindow] = []
        for value in values:
            match = TIME_RANGE.fullmatch(str(value))
            if not match:
                raise ConfigError(f"Ungueltiger Zeitraum [{name}].{day}: {value!r}")
            try:
                start = time(int(match[1]), int(match[2]))
                end = time(int(match[3]), int(match[4]))
            except ValueError as exc:
                raise ConfigError(f"Ungueltige Uhrzeit [{name}].{day}: {value!r}") from exc
            if start >= end:
                raise ConfigError(f"Zeitraum muss am selben Tag enden [{name}].{day}: {value!r}")
            if windows and start < windows[-1].end:
                raise ConfigError(f"Ueberlappende Zeitraeume [{name}].{day}")
            windows.append(TimeWindow(start, end))
        days.append(tuple(windows))
    return WeeklySchedule(tuple(days))


def load_config(path: str | Path = "/etc/kienzlefon/kienzlefon.toml") -> AppConfig:
    source = Path(path).expanduser().resolve()
    with source.open("rb") as handle:
        raw = tomllib.load(handle)
    base = source.parent

    paths = _section(raw, "pfade")
    practice = _section(raw, "praxis")
    override = _section(raw, "override")
    ivr = _section(raw, "ivr")
    recording = _section(raw, "aufnahme")
    whisper = _section(raw, "whisper")
    telepraxis = _section(raw, "telepraxis")
    tts = _section(raw, "tts")
    asterisk = _section(raw, "asterisk")
    announcement_ivr = _section(raw, "ansagen_ivr")
    standalone = _section(raw, "zusaetzliche_nebenstellen")
    special_queue = _section(raw, "sonderqueue")
    dial_rules = _section(raw, "wahlregeln")
    direct_queue = _section(raw, "sip_direkte_queue")
    direct_red = _section(raw, "sip_rotes_telefon")
    prompts = _section(raw, "ansagen")

    whisper_models = {
        "modell_standard": str(_required(whisper, "modell_standard", "whisper")),
        "modell_namen": str(_required(whisper, "modell_namen", "whisper")),
        "modell_medikamente": str(_required(whisper, "modell_medikamente", "whisper")),
    }
    invalid_models = {
        key: value for key, value in whisper_models.items() if value not in SUPPORTED_WHISPER_MODELS
    }
    if invalid_models:
        detail = ", ".join(f"{key}={value!r}" for key, value in invalid_models.items())
        raise ConfigError(f"Nicht unterstuetzte Whisper-Modellwahl: {detail}")

    prompt_values = {str(key): str(value) for key, value in prompts.items()}
    prompt_values.setdefault("menu_intro", DEFAULT_MENU_INTRO)
    missing_prompts = REQUIRED_PROMPTS - prompt_values.keys()
    if missing_prompts:
        raise ConfigError(f"Fehlende Ansagetexte: {', '.join(sorted(missing_prompts))}")

    attempts = int(ivr.get("menue_durchlaeufe", 2))
    if attempts != 2:
        raise ConfigError("[ivr].menue_durchlaeufe ist verbindlich auf 2 festgelegt")
    heartbeat = int(whisper.get("heartbeat_sekunden", 5))
    heartbeat_stale = int(whisper.get("heartbeat_veraltet_sekunden", 20))
    if heartbeat_stale <= heartbeat:
        raise ConfigError("Whisper-Heartbeat muss vor seiner Verfallszeit erneuert werden")
    max_attempts = int(whisper.get("maximale_versuche", 3))
    if max_attempts < 1:
        raise ConfigError("[whisper].maximale_versuche muss mindestens 1 sein")

    try:
        timezone = ZoneInfo(str(practice.get("zeitzone", "Europe/Berlin")))
    except Exception as exc:
        raise ConfigError("Ungueltige [praxis].zeitzone") from exc

    standalone_extensions = _standalone_extensions(standalone)
    special_members = special_queue.get("zusaetzliche_nebenstellen", [])
    if not isinstance(special_members, list):
        raise ConfigError("[sonderqueue].zusaetzliche_nebenstellen muss eine Liste sein")
    demo_value = telepraxis.get("demo", False)
    if not isinstance(demo_value, bool):
        raise ConfigError("[telepraxis].demo muss true oder false sein")
    demo_mode = demo_value
    public_key_value = str(telepraxis.get("public_key", "")).strip()
    if not demo_mode and not public_key_value:
        raise ConfigError("[telepraxis].public_key ist im Produktivmodus erforderlich")
    config = AppConfig(
        source=source,
        paths=PathsConfig(
            spool=_path(base, _required(paths, "spool", "pfade")),
            runtime=_path(base, _required(paths, "runtime", "pfade")),
            prompts=_path(base, _required(paths, "ansagen", "pfade")),
            prompt_masters=_path(base, _required(paths, "ansagen_master", "pfade")),
        ),
        practice=PracticeConfig(name=str(_required(practice, "name", "praxis")), timezone=timezone),
        override=OverrideConfig(
            active=bool(override.get("aktiv", False)),
            announcement=str(override.get("ansage", "")).strip(),
            block_phone_hours=bool(override.get("telefonzeiten_sperren", True)),
        ),
        ivr=IVRConfig(
            attempts=attempts,
            digit_timeout_ms=int(ivr.get("tasten_timeout_ms", 6000)),
            announcement_pause_ms=int(ivr.get("ansage_pause_ms", 700)),
            queue_name=str(ivr.get("queue", "praxis")),
            queue_context=str(ivr.get("queue_context", "kfx-phone-queue,s,1")),
            pharmacy_priority=int(ivr.get("apotheken_prioritaet", 10)),
            red_enabled=bool(ivr.get("rotes_telefon_aktiv", True)),
            red_extension=str(_required(ivr, "rote_nebenstelle", "ivr")),
            red_ring_seconds=int(ivr.get("rotes_telefon_klingeldauer_sekunden", 20)),
            red_fallback_priority=int(ivr.get("rotes_telefon_queue_prioritaet", 100)),
            specialist_announcement=bool(ivr.get("fachstellen_ansage", False)),
        ),
        recording=RecordingConfig(
            format=str(recording.get("format", "wav")),
            short_silence_seconds=int(recording.get("stille_kurz_sekunden", 3)),
            long_silence_seconds=int(recording.get("stille_lang_sekunden", 6)),
            short_max_seconds=int(recording.get("maximum_kurz_sekunden", 30)),
            long_max_seconds=int(recording.get("maximum_lang_sekunden", 180)),
            stale_seconds=int(recording.get("verwaist_sekunden", 7200)),
        ),
        whisper=WhisperConfig(
            standard_model=whisper_models["modell_standard"],
            name_model=whisper_models["modell_namen"],
            medication_model=whisper_models["modell_medikamente"],
            first_name_prompt=str(whisper.get("initial_prompt_vorname", "")).strip(),
            last_name_prompt=str(whisper.get("initial_prompt_nachname", "")).strip(),
            medication_prompt=str(whisper.get("initial_prompt_medikamente", "")).strip(),
            model_directory=_path(base, _required(whisper, "modellverzeichnis", "whisper")),
            device=str(whisper.get("geraet", "cpu")),
            compute_type=str(whisper.get("compute_type", "int8")),
            cpu_threads=int(whisper.get("cpu_threads", 0)),
            beam_size=int(whisper.get("beam_size", 5)),
            language=str(whisper.get("sprache", "de")),
            poll_seconds=float(whisper.get("poll_sekunden", 0.5)),
            heartbeat_seconds=heartbeat,
            stale_heartbeat_seconds=heartbeat_stale,
            max_attempts=max_attempts,
        ),
        telepraxis=TelepraxisConfig(
            channel=str(_required(telepraxis, "kanal", "telepraxis")),
            output_directory=_path(base, _required(telepraxis, "ausgabeverzeichnis", "telepraxis")),
            demo=demo_mode,
            public_key=_path(base, public_key_value) if public_key_value else None,
        ),
        tts=TTSConfig(
            engine=str(tts.get("engine", "piper")),
            voice=str(_required(tts, "stimme", "tts")),
            voice_directory=_path(base, _required(tts, "stimmenverzeichnis", "tts")),
            upload_directory=_path(base, _required(tts, "uploadverzeichnis", "tts")),
            volume=float(tts.get("lautstaerke", 1.0)),
            length_scale=float(tts.get("length_scale", 1.3)),
            sentence_silence=float(tts.get("sentence_silence", 0.8)),
            target_loudness_lufs=float(tts.get("ziel_lautheit_lufs", -19.0)),
            max_true_peak_db=float(tts.get("max_true_peak_db", -2.0)),
        ),
        asterisk=AsteriskConfig(
            red_password=str(_required(asterisk, "rotes_telefon_passwort", "asterisk")),
            phone_transport=str(asterisk.get("telefon_transport", "transport-kfx-phone")),
            main_outbound_endpoint=str(_required(asterisk, "hauptausgang_endpoint", "asterisk")),
            main_outbound_number=str(_required(asterisk, "hauptausgang_nummer", "asterisk")),
            outbound_counts_capacity=bool(asterisk.get("ausgehend_zaehlt_kanalgrenze", True)),
            first_queue_extension=int(asterisk.get("erste_queue_nebenstelle", 201)),
            queue_extension_count=int(asterisk.get("queue_nebenstellen_anzahl", 1)),
            direct_queue=_sip_line(direct_queue, "sip_direkte_queue"),
            direct_red=_sip_line(direct_red, "sip_rotes_telefon"),
        ),
        announcement_ivr=AnnouncementIVRConfig(
            extension=str(announcement_ivr.get("nebenstelle", "777")),
            silence_seconds=int(announcement_ivr.get("aufnahme_stille_sekunden", 3)),
            max_seconds=int(announcement_ivr.get("aufnahme_max_sekunden", 180)),
            audit_log=_path(
                base,
                announcement_ivr.get(
                    "audit_log", "/var/lib/kienzlefon/ansagen-ivr-audit.jsonl"
                ),
            ),
        ),
        standalone_extensions=standalone_extensions,
        special_queue=SpecialQueueConfig(
            name=str(special_queue.get("name", "kienzlefon-sonder")).strip(),
            weight=int(special_queue.get("gewicht", 100)),
            additional_extensions=tuple(str(value) for value in special_members),
        ),
        dial_rules=DialRulesConfig(
            country_code=str(dial_rules.get("landesvorwahl", "49")),
            area_code=str(_required(dial_rules, "ortsvorwahl", "wahlregeln")),
            practice_number=str(_required(dial_rules, "praxisrufnummer", "wahlregeln")),
            minimum_external_digits=int(dial_rules.get("min_extern_ziffern", 3)),
            block_international=bool(dial_rules.get("international_gesperrt", True)),
            block_0900=bool(dial_rules.get("sperre_0900", True)),
            block_0137=bool(dial_rules.get("sperre_0137", True)),
            block_118=bool(dial_rules.get("sperre_118", True)),
            block_019=bool(dial_rules.get("sperre_019", True)),
            block_0180=bool(dial_rules.get("sperre_0180", False)),
            block_0700=bool(dial_rules.get("sperre_0700", False)),
            block_032=bool(dial_rules.get("sperre_032", False)),
            audit_log=_path(
                base, dial_rules.get("audit_log", "/var/lib/kienzlefon/telefonie-audit.jsonl")
            ),
        ),
        prompts=PromptConfig(prompt_values),
        opening_hours=_schedule(raw, "oeffnungszeiten"),
        phone_hours=_schedule(raw, "telefonzeiten"),
        pharmacy_hours=_schedule(raw, "apothekenzeiten"),
        specialist_hours=_schedule(raw, "fachstellenzeiten"),
    )
    if (
        config.override.active
        and not config.override.announcement
        and not any(
            (config.tts.upload_directory / f"override.{suffix}").is_file()
            for suffix in ("wav16", "wav")
        )
    ):
        raise ConfigError("Aktiver Override benoetigt Text oder eine manuelle Override-Ansage")
    if config.recording.format != "wav":
        raise ConfigError("[aufnahme].format ist fuer Version 1.7 verbindlich auf 'wav' festgelegt")
    if config.tts.engine != "piper":
        raise ConfigError("Version 1.7 implementiert als TTS-Engine ausschliesslich 'piper'")
    if not math.isfinite(config.tts.length_scale) or config.tts.length_scale <= 0:
        raise ConfigError("[tts].length_scale muss eine endliche Zahl groesser als 0 sein")
    if not math.isfinite(config.tts.sentence_silence) or config.tts.sentence_silence < 0:
        raise ConfigError("[tts].sentence_silence muss eine endliche Zahl ab 0 sein")
    if not -70.0 <= config.tts.target_loudness_lufs <= -5.0:
        raise ConfigError("[tts].ziel_lautheit_lufs muss zwischen -70 und -5 liegen")
    if not -9.0 <= config.tts.max_true_peak_db <= 0.0:
        raise ConfigError("[tts].max_true_peak_db muss zwischen -9 und 0 liegen")
    if not 0 <= config.ivr.announcement_pause_ms <= 10000:
        raise ConfigError("[ivr].ansage_pause_ms muss zwischen 0 und 10000 liegen")
    if config.ivr.red_ring_seconds < 1:
        raise ConfigError("[ivr].rotes_telefon_klingeldauer_sekunden muss mindestens 1 sein")
    if config.ivr.red_fallback_priority <= config.ivr.pharmacy_priority:
        raise ConfigError(
            "[ivr].rotes_telefon_queue_prioritaet muss groesser als die Apothekenprioritaet sein"
        )
    if not re.fullmatch(r"[1-9][0-9]{1,5}", config.ivr.red_extension):
        raise ConfigError("[ivr].rote_nebenstelle ist ungueltig")
    if not config.asterisk.red_password:
        raise ConfigError("[asterisk].rotes_telefon_passwort darf nicht leer sein")
    first = config.asterisk.first_queue_extension
    last = first + config.asterisk.queue_extension_count - 1
    if first <= int(config.ivr.red_extension) <= last:
        raise ConfigError("Die rote Nebenstelle darf keine Nebenstelle der Praxisqueue sein")
    if config.announcement_ivr.extension != "777":
        raise ConfigError("[ansagen_ivr].nebenstelle ist verbindlich auf '777' festgelegt")
    if config.ivr.red_extension == config.announcement_ivr.extension:
        raise ConfigError("Das rote Telefon darf nicht die Ansagen-Nebenstelle 777 verwenden")
    if first <= int(config.announcement_ivr.extension) <= last:
        raise ConfigError("Die Ansagen-Nebenstelle 777 darf nicht Teil der Praxisqueue sein")
    if config.announcement_ivr.silence_seconds < 1 or config.announcement_ivr.max_seconds < 1:
        raise ConfigError("Aufnahmezeiten des Ansagen-IVR muessen positiv sein")
    if config.dial_rules.country_code != "49":
        raise ConfigError("[wahlregeln].landesvorwahl ist verbindlich auf '49' festgelegt")
    if not re.fullmatch(r"0[1-9][0-9]+", config.dial_rules.area_code):
        raise ConfigError("[wahlregeln].ortsvorwahl muss mit 0 beginnen und nur Ziffern enthalten")
    if not re.fullmatch(r"[0-9]+", config.dial_rules.practice_number):
        raise ConfigError("[wahlregeln].praxisrufnummer darf nur Ziffern enthalten")
    if config.dial_rules.minimum_external_digits < 3:
        raise ConfigError("[wahlregeln].min_extern_ziffern muss mindestens 3 sein")
    reserved = {str(value) for value in range(first, last + 1)} | {
        config.ivr.red_extension,
        config.announcement_ivr.extension,
    }
    extensions = [entry.extension for entry in config.standalone_extensions]
    if len(extensions) != len(set(extensions)) or reserved.intersection(extensions):
        raise ConfigError("Zusaetzliche Nebenstellen sind doppelt oder mit festen Nebenstellen belegt")
    expected = [str(int(config.ivr.red_extension) + offset) for offset in range(1, len(extensions) + 1)]
    if extensions != expected:
        raise ConfigError("Zusaetzliche Nebenstellen muessen direkt nach dem roten Telefon aufsteigen")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", config.special_queue.name):
        raise ConfigError("[sonderqueue].name ist fuer Asterisk ungueltig")
    if config.special_queue.name == config.ivr.queue_name:
        raise ConfigError("Die Sonderqueue muss einen eigenen Namen besitzen")
    if config.special_queue.weight < 1:
        raise ConfigError("[sonderqueue].gewicht muss mindestens 1 sein")
    selected = config.special_queue.additional_extensions
    if len(selected) != len(set(selected)):
        raise ConfigError("[sonderqueue].zusaetzliche_nebenstellen enthaelt Duplikate")
    unknown = set(selected) - set(extensions)
    if unknown:
        raise ConfigError(
            "Sonderqueue enthaelt unbekannte zusaetzliche Nebenstellen: "
            + ", ".join(sorted(unknown))
        )
    return config


def _standalone_extensions(section: Mapping[str, Any]) -> tuple[StandaloneExtensionConfig, ...]:
    extensions = section.get("nebenstellen", [])
    passwords = section.get("passwoerter", [])
    if not isinstance(extensions, list) or not isinstance(passwords, list):
        raise ConfigError("[zusaetzliche_nebenstellen] erwartet Listen")
    if len(extensions) != len(passwords):
        raise ConfigError("Nebenstellen und Passwoerter muessen gleich viele Eintraege haben")
    result = tuple(
        StandaloneExtensionConfig(str(extension), str(password))
        for extension, password in zip(extensions, passwords, strict=True)
    )
    for entry in result:
        if not re.fullmatch(r"[1-9][0-9]{1,5}", entry.extension) or not entry.password:
            raise ConfigError("Ungueltige zusaetzliche Nebenstelle oder leeres Passwort")
    return result


def _sip_line(section: Mapping[str, Any], name: str) -> SipLineConfig:
    enabled = bool(section.get("aktiv", False))
    line = SipLineConfig(
        enabled=enabled,
        did=str(section.get("rufnummer", "")),
        user=str(section.get("benutzer", "")),
        password=str(section.get("passwort", "")),
        domain=str(section.get("domain", "")),
        outbound_proxy=str(section.get("outbound_proxy", "")),
        expiration=int(section.get("expiration", 300)),
        use_for_outbound=bool(section.get("ausgehend_verwenden", False)),
    )
    if enabled:
        missing = [
            field
            for field, value in (
                ("rufnummer", line.did),
                ("benutzer", line.user),
                ("passwort", line.password),
                ("domain", line.domain),
            )
            if not value
        ]
        if missing:
            raise ConfigError(f"[{name}] aktiv, aber unvollstaendig: {', '.join(missing)}")
    if line.use_for_outbound and not enabled:
        raise ConfigError(f"[{name}].ausgehend_verwenden setzt aktiv=true voraus")
    return line


def caller_id_or_none(value: str | None) -> str | None:
    normalized = (value or "").strip()
    if normalized.casefold() in UNKNOWN_CALLER_IDS:
        return None
    return normalized


def payload_fields(call_type: CallType) -> tuple[str, ...]:
    common = ("vorname", "nachname", "geburtsdatum")
    mapping = {
        CallType.PRESCRIPTION: common + ("medikamente",),
        CallType.REFERRAL: common + ("fachrichtung", "grund"),
        CallType.APPOINTMENT: common + ("grund",),
        CallType.CALLBACK_DETAILS: common + ("grund",),
        CallType.CALLBACK_FALLBACK: ("grund",),
        CallType.OTHER: common + ("anliegen",),
        CallType.ERROR: (),
    }
    return mapping[call_type]
