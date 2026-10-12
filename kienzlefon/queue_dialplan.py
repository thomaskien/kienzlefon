"""Reversible Queue entry/member wrappers; retain native priorities and ordering."""
from __future__ import annotations

import glob
import re
from pathlib import Path

from .config import AppConfig
from .queue_dispatch import member_interface
from .transfer_dialplan import _split_arguments
from .transfer_features import _INCLUDE, _SECTION, _include_argument, _strip_comment

BEGIN = "; kienzlefon queue cycle begin"
END = "; kienzlefon queue cycle end"
MEMBER_BEGIN = "; kienzlefon queue member begin"
MEMBER_END = "; kienzlefon queue member end"
RULE_NAME = "kienzlefon-progressive"


def validate_rules_include(etc: Path, planned: dict[str, str]) -> None:
    """Read the proposed include graph before publishing; names must be unique.

    Do not deduplicate visited files: two differently spelled includes of the
    same rule file create two Asterisk rule lists and must be rejected as well.
    """
    etc = etc.resolve()
    count = 0

    def local_path(path: Path) -> Path:
        # Generated includes target production /etc/asterisk; map them to the
        # caller's configuration directory for isolated installation planning.
        if path.is_relative_to("/etc/asterisk"):
            path = etc / path.relative_to("/etc/asterisk")
        return path.resolve()

    def read(path: Path, stack: tuple[Path, ...]) -> None:
        nonlocal count
        path = local_path(path)
        if path in stack or len(stack) >= 32:
            raise ValueError("Queue-Regeln: zyklische oder zu tiefe Includes")
        text = (planned[path.name] if path.parent == etc and path.name in planned
                else path.read_text(encoding="utf-8"))
        for raw in text.splitlines():
            line = _strip_comment(raw).strip()
            directive = _INCLUDE.fullmatch(line)
            if directive:
                kind = directive[1].lower()
                if kind == "exec":
                    raise ValueError("Queue-Regeln: #exec kann nicht sicher geprueft werden")
                argument = Path(_include_argument(directive[2]))
                pattern = local_path(argument if argument.is_absolute() else etc / argument)
                matches = {Path(item).resolve() for item in glob.glob(str(pattern))}
                matches.update(etc / name for name in planned if (etc / name).match(str(pattern)))
                if not matches and kind == "include":
                    raise ValueError(f"Queue-Regeln: Pflicht-Include fehlt: {argument}")
                for child in sorted(matches):
                    read(child, (*stack, path))
                continue
            if line.startswith("#"):
                raise ValueError("Queue-Regeln: unbekannte Praeprozessoranweisung")
            section = _SECTION.fullmatch(line)
            if section and section[1].strip().lower() == RULE_NAME:
                count += 1
                if path != etc / "queuerules-kienzlefon.conf" or section[2]:
                    raise ValueError(f"Queue-Regel {RULE_NAME} ist fremd belegt: {path}")
    read(etc / "queuerules.conf", ())
    if count != 1:
        raise ValueError(f"Queue-Regel {RULE_NAME} muss genau einmal eingebunden sein (gefunden: {count})")


def render_rules(config: AppConfig, timing: tuple[int, int]) -> str:
    # app_queue's head-caller path applies rules at elapsed > rule_time. Use the
    # second before the next cycle, otherwise a stage can be a full cycle late.
    cycle = sum(timing)
    rules = "\n".join(f"penaltychange => {index * cycle - 1},,,{index}"
                      for index in range(1, config.asterisk.queue_extension_count))
    return f"; Kienzlefon Rufzyklen\n[{RULE_NAME}]\n{rules}\n"


def unwrap(text: str, begin: str = BEGIN, end: str = END) -> str:
    return re.sub(re.escape(begin) + r"\n; original: ([^\n]*)\n.*?" + re.escape(end),
                  lambda match: match[1], text, flags=re.DOTALL)


def practice_timing(path: Path, queue: str) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    section = re.search(r"^\[" + re.escape(queue) + r"\]\n(.*?)(?=^\[|\Z)", text,
                        re.MULTILINE | re.DOTALL)
    body = section[1] if section else ""
    values = {}
    for key, default, lower, upper in (("timeout", 19, 2, 600), ("retry", 1, 1, 60)):
        found = re.findall(r"^\s*" + key + r"\s*=\s*([^;\n]+)", body, re.MULTILINE)
        value = int(found[-1].strip()) if found else default
        if not lower <= value <= upper:
            raise ValueError(f"Queue {queue}: {key} muss zwischen {lower} und {upper} liegen")
        values[key] = value
    return values["timeout"], values["retry"]


def decorate_entries(text: str, config: AppConfig, timing: tuple[int, int] = (19, 1)) -> str:
    text = unwrap(text)
    output = []
    for line in text.splitlines():
        match = re.fullmatch(
            r"(\s*(?:exten\s*=>\s*[^,]+,[^,]+,|same\s*=>\s*[^,]+,))"
            r"Queue\((.*)\)(\s*(?:;.*)?)", line,
        )
        if not match:
            output.append(line)
            continue
        args = _split_arguments(match[2])
        queue = args[0]
        if queue not in {config.ivr.queue_name, config.special_queue.name}:
            output.append(line)
            continue
        ring, retry = timing if queue == config.ivr.queue_name else (19, 1)
        output.extend((BEGIN, "; original: " + line,
                       match[1] + "AGI(/opt/kienzlefon/venv/bin/kienzlefon-queue-dispatch,"
                       f"enter,--config,/etc/kienzlefon/kienzlefon.toml,--queue,{queue},"
                       f"--ring,{ring},--retry,{retry})",
                       f" same => n,Queue({match[2]}){match[3]}", END))
    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


def decorate_members(text: str, config: AppConfig) -> str:
    text = unwrap(text, MEMBER_BEGIN, MEMBER_END)
    section = re.search(r"^\[" + re.escape(config.ivr.queue_name)
                        + r"\]\n(?P<body>.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if section is None:
        raise ValueError("Praxisqueue fuer Rufzyklen fehlt")
    first = config.asterisk.first_queue_extension
    allowed = {str(n) for n in range(first, first + config.asterisk.queue_extension_count)}
    output = []
    seen = set()
    for line in section["body"].splitlines():
        match = re.fullmatch(r"\s*member\s*=>\s*([^;]*?)(\s*(?:;.*)?)", line)
        if match is None:
            output.append(line)
            continue
        fields = [field.strip() for field in match[1].split(",")]
        if not fields[0].startswith("PJSIP/") or fields[0][6:] not in allowed:
            raise ValueError("Praxisqueue hat ein unbekanntes Mitglied; Rufzyklen nicht installiert")
        extension = fields[0][6:]
        if extension in seen:
            raise ValueError("Praxisqueue enthaelt ein Telefon mehrfach")
        while len(fields) < 5:
            fields.append("")
        fields[1] = str(int(extension) - first)
        # The real phone's state prevents both normal and red queues from
        # attempting an employee already in a call. Keep the original complete
        # line in its marker for review; these are the managed phone settings.
        fields[3] = fields[0]
        fields[4] = "no"
        fields[0] = member_interface(extension)
        output.extend((MEMBER_BEGIN, "; original: " + line,
                       "member => " + ",".join(fields) + match[2], MEMBER_END))
        seen.add(extension)
    if seen != allowed:
        raise ValueError("Praxisqueue hat nicht alle konfigurierten Telefon-Mitglieder")
    body = "\n".join(output) + "\n"
    return text[:section.start("body")] + body + text[section.end("body"):]
