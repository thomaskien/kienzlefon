"""Validate installer answers and update the weekly schedules of an existing installation."""

import json
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path

from .config import ConfigError, WEEKDAYS, parse_schedule_input, parse_time_windows


SCHEDULES = {
    "oeffnungszeiten": "KZF_OPEN",
    "telefonzeiten": "KZF_PHONE",
    "apothekenzeiten": "KZF_PHARMACY",
    "fachstellenzeiten": "KZF_SPECIALIST",
}


def corrected_day(label: str) -> list[str]:
    # Bash continues reading this same stream for the SIP dialog. Buffered input
    # can consume its next answers when the installer receives piped input.
    with open(sys.stdin.fileno(), "rb", buffering=0, closefd=False) as answers:
        while True:
            print(f"{label} korrigieren (z.B. 08:00-12:00, leer=geschlossen): ", end="", flush=True)
            line = answers.readline()
            if not line:
                raise EOFError("Eingabe beendet.")
            try:
                return parse_schedule_input(line.decode(), label)
            except ConfigError as exc:
                print(exc, file=sys.stderr)


def replace_day(text: str, section: str, day: str, values: list[str]) -> str:
    header = re.search(rf"^\[{section}\][^\n]*\n", text, re.M)
    if header is None:
        raise ConfigError(f"Fehlender Abschnitt [{section}]")
    end = re.search(r"^\s*\[\w", text[header.end():], re.M)
    limit = header.end() + end.start() if end else len(text)
    line = re.compile(rf"^[ \t]*{day}[ \t]*=[ \t]*", re.M).search(text, header.end(), limit)
    if line is None:
        raise ConfigError(f"Fehlendes Zeitprofil [{section}].{day}")
    # A TOML array can span several lines. Replace only this assignment.
    start = line.end()
    for boundary in re.finditer(r"\n|\Z", text[start:limit]):
        stop = start + boundary.start()
        try:
            tomllib.loads("value = " + text[start:stop])
        except tomllib.TOMLDecodeError:
            continue
        return text[:start] + json.dumps(values) + text[stop:]
    raise ConfigError(f"Zeitprofil [{section}].{day} konnte nicht gelesen werden")


def update_times(target: Path, repair_only: bool) -> None:
    original = target.read_text(encoding="utf-8")
    expected = tomllib.loads(original)
    text = original
    for section, prefix in SCHEDULES.items():
        for day in WEEKDAYS:
            label = f"[{section}].{day}"
            previous = expected[section].get(day, [])
            if repair_only:
                try:
                    parse_time_windows(previous, label)
                    continue
                except ConfigError as exc:
                    print(f"Gespeichertes Zeitprofil ungültig: {exc}", file=sys.stderr)
                values = corrected_day(label)
            else:
                values = parse_schedule_input(os.environ[f"{prefix}_{day.upper()}"], label)
            if values != previous:
                text = replace_day(text, section, day, values)
                expected[section][day] = values
    if text == original:
        return
    if tomllib.loads(text) != expected:
        raise ConfigError("Die korrigierten Zeitprofile konnten nicht übernommen werden.")
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text)
        if target.read_text(encoding="utf-8") != original:
            raise ConfigError("Die Konfiguration wurde zwischenzeitlich geändert. Bitte erneut aufrufen.")
        temporary.chmod(target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"validate", "repair", "update"}:
        sys.exit("Aufruf: installer_times validate EINGABE | repair DATEI | update DATEI")
    if sys.argv[1] == "validate":
        try:
            parse_schedule_input(sys.argv[2], "in der Eingabe")
        except ConfigError as exc:
            print(f"{exc}. Bitte Zeitfenster wie 08:00-12:00 eingeben.", file=sys.stderr)
            sys.exit(2)
    else:
        try:
            update_times(Path(sys.argv[2]), repair_only=sys.argv[1] == "repair")
        except (ConfigError, EOFError) as exc:
            sys.exit(f"Zeitprofile konnten nicht gespeichert werden: {exc}")
