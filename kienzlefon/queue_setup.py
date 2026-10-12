"""Installer checks and human-readable diagnostics for the active queue audio."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from .config import AppConfig, load_config
from .prompts import PromptGenerator
from .queue_dialplan import RULE_NAME, practice_timing
from .queue_dispatch import MEMBER_CONTEXT, member_interface
from .queue_prompts import QUEUE_PHRASES, phrase_output_paths, phrase_path
from .transfer_setup import _cli


def preflight() -> None:
    for function in ("QUEUE_GET_CHANNEL", "IMPORT"):
        if function + "(" not in _cli("core show function " + function):
            raise ValueError(f"Rufzyklen benoetigen Asterisk-Funktion {function}")
    for application in ("AGI", "Dial", "Queue"):
        if application + "(" not in _cli("core show application " + application):
            raise ValueError(f"Rufzyklen benoetigen Asterisk-Anwendung {application}")
    if "Local" not in _cli("core show channeltypes"):
        raise ValueError("Asterisk stellt den Local-Kanaltreiber nicht bereit")


def reload_queues() -> None:
    output = _cli("module reload app_queue.so")
    if "reloaded successfully" not in output:
        raise ValueError("Asterisk hat das Neuladen der Queue-Konfiguration nicht bestaetigt")


def audio_report(config: AppConfig) -> list[str]:
    generator = PromptGenerator(config)
    manifest = generator._load_manifest().get("prompts", {})
    result = []
    for name in QUEUE_PHRASES:
        if not all(path.is_file() and path.stat().st_size for path in
                   phrase_output_paths(config.paths.prompts, name)):
            raise ValueError(f"Queue-Ansage fehlt oder ist leer: {phrase_path(config.paths.prompts, name)}")
        entry = manifest.get(name, {})
        text = config.prompts.values[name]
        if entry.get("text") != text:
            raise ValueError(f"Queue-Ansage nicht aktuell erzeugt: {name}")
        source = generator._manual_source(name)
        if source is not None:
            result.append(f"{name}: Aufnahme {source}; gesprochener Text individuell")
        else:
            result.append(f"{name}: {text}")
        result.append(f"  Asterisk-Datei: {phrase_path(config.paths.prompts, name)}")
    return result


def verify(config: AppConfig) -> None:
    for context, markers in {
        "kfx-phone-queue": ("kienzlefon-queue-dispatch", "enter", "de_kienzlefon"),
        MEMBER_CONTEXT: ("kienzlefon-queue-dispatch", "KF_QUEUE_RING_SECONDS", "Dial(PJSIP/"),
    }.items():
        output = _cli("dialplan show " + context)
        if not all(marker in output for marker in markers):
            raise ValueError(f"Queue-Dialplan nicht vollstaendig geladen: {context}")
    first = config.asterisk.first_queue_extension
    for name in (config.ivr.queue_name, config.special_queue.name):
        output = _cli("queue show " + name)
        weight = 0 if name == config.ivr.queue_name else config.special_queue.weight
        if "'ringall' strategy" not in output or f"W:{weight}," not in output:
            raise ValueError(f"Queue {name}: Strategie oder Prioritaet nicht geladen")
        for number in range(first, first + config.asterisk.queue_extension_count):
            lines = [line for line in output.splitlines() if member_interface(str(number)) in line]
            penalty = number - first if name == config.ivr.queue_name else 0
            if len(lines) != 1 or "(ringinuse disabled)" not in lines[0]:
                raise ValueError(f"Queue {name}: Rufzyklen fuer Telefon {number} nicht geladen")
            found = re.search(r"with penalty (\d+)", lines[0])
            if (int(found[1]) if found else 0) != penalty:
                raise ValueError(f"Queue {name}: Rufstufe fuer Telefon {number} nicht geladen")
    cycle = sum(practice_timing(Path("/etc/asterisk/queues-kfx.conf"), config.ivr.queue_name))
    rules = _cli("queue show rules " + RULE_NAME)
    expected = [f"Rule: {RULE_NAME}"] + [
        f"After {index * cycle - 1} seconds, adjust QUEUE_MAX_PENALTY by 0, "
        f"adjust QUEUE_MIN_PENALTY by 0 and adjust QUEUE_RAISE_PENALTY to {index}"
        for index in range(1, config.asterisk.queue_extension_count)
    ]
    if [line.strip() for line in rules.splitlines() if line.strip()] != expected:
        raise ValueError("Queue-Rufregeln fehlen, weichen ab oder sind mehrfach geladen")
    for line in audio_report(config):
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kienzlefon Rufzyklen und Queue-Ansagen pruefen")
    parser.add_argument("mode", choices=("preflight", "reload", "verify", "audio"))
    parser.add_argument("--config", default="/etc/kienzlefon/kienzlefon.toml")
    args = parser.parse_args()
    try:
        if args.mode == "preflight":
            preflight()
        elif args.mode == "reload":
            reload_queues()
        elif args.mode == "audio":
            print("\n".join(audio_report(load_config(Path(args.config)))))
        else:
            verify(load_config(Path(args.config)))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Queue-Pruefung: {exc}\n")
