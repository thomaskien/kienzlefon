# kienzlefon
# Version: 2.1.2
# Changelog:
# - 2.1.2: Versionsausgabe der Konfigurationsmigration aktualisiert.
# - 2.1.1: Versionsausgabe der Konfigurationsmigration aktualisiert.
# - 2.1: Gezielte Qwen-Neugenerierung mit neuer Variante je Ansage ergaenzt.
# - 2.0: Laufende Ansagenerzeugung menschenlesbar und maschinenlesbar ausgegeben.
# - 2.0: TTS-Modell und Qwen-Sprecher in die konservative Migration aufgenommen.
# - 1.9.3: Migrationsausgabe auf Patchrelease 1.9.3 aktualisiert.
# - 1.9.2: Migrationsausgabe auf Patchrelease 1.9.2 aktualisiert.
# - 1.9.1: Migrationsausgabe auf Patchrelease 1.9.1 aktualisiert.
# - 1.9: Demo-Anonymisierung in Konfigurationspruefung und Status aufgenommen.
# - 1.8: Konfigurationspruefung und Status um den Telepraxis-Demomodus ergaenzt.
# - 1.7: AGI-Einstieg fuer die eingehende Anzeige-Caller-ID ergaenzt.
# - 1.6: Mehrmodell-Download, Statusausgabe und Modellmigration ergaenzt.
# - 1.5: Konfigurationsmigration auf die Audioeinstellungen 1.5 aktualisiert.
# - 1.4: PIN-freie Konfigurationsmigration fuer das Ansagen-IVR ergaenzt.
# - 1.3: AGI-Einstiege fuer Ansagenverwaltung und Wahlpruefung ergaenzt.
# - 1.1: Laufzeithinweis vor der Ansagengenerierung ergaenzt.
# - 1.0: Kommandozeilen-Einstiege fuer AGI, Worker, Ansagen und Diagnose.

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .admin import AnnouncementAdmin
from .agi import AgiChannel, AgiHangup
from .asterisk import install_asterisk_config
from .config import AppConfig, ConfigError, load_config
from .crypto import TelepraxisEncryptor
from .dialing import (
    audit_decision,
    canonical_practice_number,
    decide_number,
    normalize_incoming_caller_id,
)
from .errors import record_system_error
from .health import worker_is_healthy
from .ivr import IVR
from .models import CallState
from .migration import migrate_config, set_boolean, set_string
from .prompts import PROMPT_PROGRESS_PREFIX, PromptGenerator
from .spool import Spool
from .worker import Worker

DEFAULT_CONFIG = "/etc/kienzlefon/kienzlefon.toml"


def _logging() -> None:
    logging.basicConfig(
        level=os.environ.get("KIENZLEFON_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--config",
        default=os.environ.get("KIENZLEFON_CONFIG", DEFAULT_CONFIG),
        help=f"TOML-Konfiguration (Standard: {DEFAULT_CONFIG})",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _load(path: str) -> AppConfig:
    return load_config(Path(path))


def agi_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Asterisk AGI")
    arguments = parser.parse_args()
    channel = AgiChannel()
    try:
        config = _load(arguments.config)
    except Exception as exc:
        logging.exception("Konfiguration fuer AGI unbrauchbar")
        try:
            channel.goto("kfx-phone-queue,s,1")
        except Exception:
            pass
        raise SystemExit(1) from exc
    IVR(config, channel).run()


def worker_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Whisper-Worker")
    arguments = parser.parse_args()
    try:
        Worker(_load(arguments.config)).run()
    except Exception:
        logging.exception("Kienzlefon-Worker beendet sich nach Fehler")
        raise SystemExit(1)


def prompts_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Ansagen erzeugen")
    parser.add_argument("--all", action="store_true", help="Alle Ansagen neu erzeugen")
    parser.add_argument(
        "--prompt",
        action="append",
        default=[],
        metavar="NAME",
        help="Nur diese Ansage neu erzeugen (mehrfach verwendbar)",
    )
    parser.add_argument(
        "--new-variant",
        action="store_true",
        help="Bei Qwen3-TTS einen neuen Seed fuer die gewaehlte Ansage verwenden",
    )
    parser.add_argument("--machine-progress", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.all and arguments.prompt:
        parser.error("--all und --prompt koennen nicht gemeinsam verwendet werden")
    if arguments.new_variant and not (arguments.all or arguments.prompt):
        parser.error("--new-variant erfordert --all oder mindestens ein --prompt")
    config: AppConfig | None = None

    def progress(event: dict[str, object]) -> None:
        if arguments.machine_progress:
            print(
                PROMPT_PROGRESS_PREFIX
                + json.dumps(event, ensure_ascii=False, separators=(",", ":")),
                flush=True,
            )
            return
        current = int(event["current"])
        total = int(event["total"])
        phase = str(event["phase"])
        name = str(event.get("name", ""))
        label = str(event.get("label", "")) or name
        prefix = f"[{current}/{total}]" if total else "[0/0]"
        messages = {
            "plan": (
                f"{total} Verarbeitungsschritt(e) erforderlich."
                if total
                else "Keine Ansage muss neu erzeugt werden."
            ),
            "qwen_prepare": "Whisper-Worker wird für Qwen3-TTS vorbereitet.",
            "qwen_ready": "Whisper-Worker ist beendet; Qwen3-TTS kann arbeiten.",
            "generate": f"Automatische Ansage wird erzeugt: {label}",
            "manual": f"Manuelle Ansage wird verarbeitet: {label}",
            "scheduled_tts": f"TTS-Fassung der Sonderansage wird erzeugt: {label}",
            "qwen_restore": "Ansagen fertig; Whisper-Worker wird wieder gestartet.",
            "complete": "Ansagenverarbeitung abgeschlossen.",
        }
        print(f"{prefix} {messages.get(phase, phase)}", flush=True)

    try:
        config = _load(arguments.config)
        print("Ansagen werden auf Aenderungen geprueft.", flush=True)
        selected = set(arguments.prompt) if arguments.prompt else None
        generated, skipped = PromptGenerator(config, progress=progress).generate(
            force=arguments.all or bool(selected),
            only=selected,
            # Ein ausdrueckliches Neu-Erzeugen soll bei einem stochastischen
            # Modell nicht wieder dieselbe deterministische Datei liefern.
            new_qwen_variant=arguments.all or arguments.new_variant,
        )
        print(f"Ansagen erzeugt: {generated}; unveraendert: {skipped}")
    except Exception as exc:
        logging.exception("Ansagenerzeugung fehlgeschlagen")
        if config is not None:
            record_system_error(
                config,
                code="PROMPT_GENERATION_FAILED",
                phase="ansagen",
                message=str(exc),
            )
        raise SystemExit(1)


def config_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Konfiguration pruefen")
    arguments = parser.parse_args()
    try:
        config = _load(arguments.config)
        TelepraxisEncryptor(
            config.telepraxis.public_key,
            config.telepraxis.output_directory,
            config.practice.timezone,
            demo_mode=config.telepraxis.demo,
            anonymize_phone_numbers=config.telepraxis.anonymize_phone_numbers,
        )
    except (OSError, ConfigError, ValueError, RuntimeError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Konfiguration gueltig: {config.source}")


def status_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Status")
    arguments = parser.parse_args()
    config = _load(arguments.config)
    spool = Spool(config.paths.spool, config.practice.timezone)
    spool.initialize()
    healthy = worker_is_healthy(
        config.paths.runtime / "whisper-health.json",
        config.whisper.models,
        config.whisper.stale_heartbeat_seconds,
    )
    status = {
        "version": __version__,
        "whisper_ready": healthy,
        "whisper_models": list(config.whisper.models),
        "calls": {state.value: len(tuple(spool.calls(state))) for state in CallState},
        "output_directory": str(config.telepraxis.output_directory),
        "demo_mode": config.telepraxis.demo,
        "demo_phone_numbers_anonymized": config.telepraxis.anonymize_phone_numbers,
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    raise SystemExit(0 if healthy else 1)


def model_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Whisper-Modell vorladen")
    arguments = parser.parse_args()
    config = _load(arguments.config)
    try:
        from faster_whisper import WhisperModel

        config.whisper.model_directory.mkdir(parents=True, exist_ok=True)
        for model_name in config.whisper.models:
            WhisperModel(
                model_name,
                device=config.whisper.device,
                compute_type=config.whisper.compute_type,
                cpu_threads=config.whisper.cpu_threads,
                num_workers=1,
                download_root=str(config.whisper.model_directory),
                local_files_only=False,
            )
            print(f"Whisper-Modell bereit: {model_name}")
    except Exception as exc:
        record_system_error(
            config,
            code="MODEL_DOWNLOAD_FAILED",
            phase="installation",
            message=str(exc),
        )
        raise


def asterisk_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Asterisk-Konfiguration erzeugen")
    parser.add_argument("--etc", default="/etc/asterisk", help="Asterisk-Konfigurationsordner")
    arguments = parser.parse_args()
    config = _load(arguments.config)
    try:
        install_asterisk_config(config, Path(arguments.etc))
    except Exception as exc:
        record_system_error(
            config,
            code="ASTERISK_CONFIG_FAILED",
            phase="installation",
            message=str(exc),
        )
        raise
    print(f"Asterisk-Konfiguration aktualisiert: {arguments.etc}")


def error_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Fehlerereignis erfassen")
    parser.add_argument("--code", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--caller-id")
    arguments = parser.parse_args()
    config = _load(arguments.config)
    call = record_system_error(
        config,
        code=arguments.code,
        phase=arguments.phase,
        message=arguments.message,
        caller_id=arguments.caller_id,
    )
    print(f"Fehler erfasst: {call.call_id}")


def admin_main() -> None:
    _logging()
    parser = _parser("Kienzlefon internes Ansagen-IVR")
    arguments = parser.parse_args()
    channel = AgiChannel()
    config = _load(arguments.config)
    try:
        AnnouncementAdmin(config, channel).run()
    except AgiHangup:
        return
    except Exception as exc:
        logging.exception("Ansagen-IVR fehlgeschlagen")
        record_system_error(
            config,
            code="ANNOUNCEMENT_ADMIN_FAILED",
            phase="ansagen_ivr",
            message=str(exc),
            caller_id=channel.environment.get("agi_callerid"),
        )
        raise SystemExit(1)


def dial_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Wahlpruefung")
    parser.add_argument("--number", required=True)
    arguments = parser.parse_args()
    channel = AgiChannel()
    config = _load(arguments.config)
    caller_id = channel.environment.get("agi_callerid", "unbekannt")
    try:
        decision = decide_number(config.dial_rules, arguments.number)
        audit_decision(config, arguments.number, caller_id, decision)
        channel.set_variable("KZF_DIAL_ALLOWED", "1" if decision.allowed else "0")
        channel.set_variable("KZF_DIAL_NUMBER", decision.normalized)
        channel.set_variable("KZF_DIAL_REASON", decision.reason)
        selected_caller_id = channel.get_variable("KZF_OUT_CALLERID")
        channel.set_variable(
            "KZF_DIAL_CALLERID",
            selected_caller_id or canonical_practice_number(config.dial_rules),
        )
    except AgiHangup:
        return
    except Exception as exc:
        logging.exception("Wahlpruefung fehlgeschlagen")
        record_system_error(
            config,
            code="DIAL_VALIDATION_FAILED",
            phase="wahlregeln",
            message=str(exc),
            caller_id=caller_id,
        )
        try:
            channel.set_variable("KZF_DIAL_ALLOWED", "0")
        except Exception:
            pass
        raise SystemExit(1)


def callerid_main() -> None:
    _logging()
    parser = _parser("Kienzlefon eingehende Caller-ID normalisieren")
    arguments = parser.parse_args()
    channel = AgiChannel()
    config = _load(arguments.config)
    caller_id = channel.environment.get("agi_callerid")
    try:
        normalized = normalize_incoming_caller_id(
            caller_id,
            config.dial_rules.country_code,
            config.local_extensions,
        )
        if normalized is not None:
            channel.set_variable("CALLERID(num)", normalized)
    except AgiHangup:
        return
    except Exception as exc:
        logging.exception("Caller-ID-Normalisierung fehlgeschlagen")
        record_system_error(
            config,
            code="CALLERID_NORMALIZATION_FAILED",
            phase="telefonie",
            message=str(exc),
            caller_id=caller_id,
        )
        raise SystemExit(1)


def migrate_main() -> None:
    _logging()
    parser = _parser("Kienzlefon Konfiguration auf 2.1.2 ergaenzen")
    parser.add_argument("--template", required=True)
    parser.add_argument("--area-code")
    parser.add_argument("--practice-number")
    parser.add_argument("--standard-model")
    parser.add_argument("--name-model")
    parser.add_argument("--medication-model")
    parser.add_argument("--demo-anonymize", choices=("true", "false"))
    parser.add_argument("--tts-engine", choices=("piper", "qwen"))
    parser.add_argument("--piper-voice")
    parser.add_argument("--qwen-voice")
    arguments = parser.parse_args()
    target = Path(arguments.config)
    migrate_config(target, Path(arguments.template))
    for section, key, value in (
        ("wahlregeln", "ortsvorwahl", arguments.area_code),
        ("wahlregeln", "praxisrufnummer", arguments.practice_number),
        ("whisper", "modell_standard", arguments.standard_model),
        ("whisper", "modell_namen", arguments.name_model),
        ("whisper", "modell_medikamente", arguments.medication_model),
        ("tts", "engine", arguments.tts_engine),
        ("tts", "stimme", arguments.piper_voice),
        ("tts", "qwen_stimme", arguments.qwen_voice),
    ):
        if value is not None:
            set_string(target, section, key, value)
    if arguments.demo_anonymize is not None:
        set_boolean(
            target,
            "telepraxis",
            "anrufernummern_anonymisieren",
            arguments.demo_anonymize == "true",
        )
    print(f"Konfiguration auf Version 2.1.2 ergaenzt: {target}")
