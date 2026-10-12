"""Read and plan channel-local Asterisk attended-transfer feature codes."""

from __future__ import annotations

import glob
import itertools
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

DEFAULT_TRANSFER_FEATURES = {
    "atxfer": "*2",
    "atxferabort": "*1",
    "atxfercomplete": "*2",
}

_ASTERISK_CONTROL_DEFAULTS = {
    "atxferabort": "*1",
    "atxfercomplete": "*2",
    "atxferthreeway": "*3",
    "atxferswap": "*4",
}
_CONTROL_NAMES = tuple(_ASTERISK_CONTROL_DEFAULTS)
_DTMF_CODE = re.compile(r"[0-9*#]{1,8}\Z")
_INCLUDE = re.compile(r"#(include|tryinclude|exec)\b(.*)\Z", re.IGNORECASE)
_SECTION = re.compile(r"\[([^]]+)]\s*(?:\(([^)]*)\))?\s*\Z")
_SETTING = re.compile(r"([^=]+?)\s*(?:=>|=)\s*(.*)\Z")
_RELEVANT_SECTIONS = frozenset({"featuremap", "general"})
_CANDIDATE_ALPHABET = "0123456789*#"


def resolve_transfer_features(etc: Path) -> dict[str, str]:
    """Return safe channel-local transfer codes derived from ``features.conf``.

    The function only reads configuration. Includes use Asterisk's configuration
    directory as their base and are expanded in deterministic lexical order.
    """

    etc = Path(etc)
    settings = {section: {} for section in _RELEVANT_SECTIONS}
    _read_config(etc / "features.conf", etc, settings, [])

    featuremap = settings["featuremap"]
    general = settings["general"]
    _validate_codes(featuremap.values())
    _validate_codes(general[name] for name in _CONTROL_NAMES if name in general)

    configured_atxfer = featuremap.get("atxfer", "")
    occupied = {value for name, value in {"blindxfer": "#", **featuremap}.items()
                if name != "atxfer" and value}
    if configured_atxfer:
        if configured_atxfer in occupied:
            raise ValueError("Konfigurierter atxfer-Code ist bereits durch ein anderes Feature belegt.")
        atxfer = configured_atxfer
    else:
        atxfer = _choose_code(DEFAULT_TRANSFER_FEATURES["atxfer"], occupied, prefixes=False)

    fixed_controls: dict[str, str] = {}
    planned_names: list[str] = []
    for name in _CONTROL_NAMES:
        if name in {"atxferabort", "atxfercomplete"} and not general.get(name, ""):
            planned_names.append(name)
            continue
        value = general.get(name, _ASTERISK_CONTROL_DEFAULTS[name])
        if value:
            fixed_controls[name] = value

    _ensure_unambiguous(fixed_controls)
    controls = dict(fixed_controls)
    unresolved_names: list[str] = []
    for name in planned_names:
        default = _ASTERISK_CONTROL_DEFAULTS[name]
        if all(not _conflicts(default, code, prefixes=True) for code in controls.values()):
            controls[name] = default
        else:
            unresolved_names.append(name)
    for name in unresolved_names:
        controls[name] = _choose_code(
            _ASTERISK_CONTROL_DEFAULTS[name], controls.values(), prefixes=True
        )

    return {
        "atxfer": atxfer,
        "atxferabort": controls["atxferabort"],
        "atxfercomplete": controls["atxfercomplete"],
    }


def _read_config(
    path: Path,
    etc: Path,
    settings: dict[str, dict[str, str]],
    stack: list[Path],
    current_section: str | None = None,
) -> str | None:
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ValueError("Asterisk-Pflichtkonfiguration fehlt oder ist nicht lesbar.") from None
    if canonical in stack:
        raise ValueError("Zyklischer Asterisk-Include erkannt.")
    if not canonical.is_file():
        raise ValueError("Asterisk-Pflichtkonfiguration ist keine normale Datei.")
    try:
        lines = canonical.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise ValueError("Asterisk-Konfiguration ist nicht sicher lesbar.") from None

    stack.append(canonical)
    try:
        for raw_line in lines:
            line = _strip_comment(raw_line).strip()
            if not line:
                continue

            directive = _INCLUDE.fullmatch(line)
            if directive:
                kind = directive.group(1).lower()
                if kind == "exec":
                    raise ValueError("Ausführbare Asterisk-Includes (#exec) sind nicht erlaubt.")
                pattern = _include_argument(directive.group(2))
                include_pattern = Path(pattern)
                if not include_pattern.is_absolute():
                    include_pattern = etc / include_pattern
                matches = sorted(Path(match) for match in glob.glob(str(include_pattern)))
                if not matches and kind == "include":
                    raise ValueError("Asterisk-Pflicht-Include wurde nicht gefunden.")
                for include_path in matches:
                    current_section = _read_config(
                        include_path, etc, settings, stack, current_section
                    )
                continue
            if line.startswith("#"):
                raise ValueError("Unbekannte Asterisk-Präprozessoranweisung.")

            if line.startswith("["):
                section_match = _SECTION.fullmatch(line)
                if not section_match:
                    raise ValueError("Asterisk-Sektionskopf ist nicht sicher interpretierbar.")
                current_section = section_match.group(1).strip().lower()
                modifier = section_match.group(2)
                if (
                    current_section in _RELEVANT_SECTIONS
                    and modifier is not None
                    and modifier.strip() != "+"
                ):
                    raise ValueError("Relevante Asterisk-Sektionsvererbung wird nicht unterstützt.")
                continue

            if current_section not in _RELEVANT_SECTIONS:
                continue
            setting = _SETTING.fullmatch(line)
            if not setting:
                raise ValueError("Relevante Asterisk-Einstellung ist nicht sicher interpretierbar.")
            name = setting.group(1).strip().lower()
            if not name or any(character.isspace() for character in name):
                raise ValueError("Relevanter Asterisk-Schlüssel ist ungültig.")
            settings[current_section][name] = setting.group(2).strip()
    finally:
        stack.pop()
    return current_section


def _strip_comment(line: str) -> str:
    quoted = False
    escaped = False
    for index, character in enumerate(line):
        if character == '"' and not escaped:
            quoted = not quoted
        if character == ";" and not quoted:
            return line[:index]
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    return line


def _include_argument(raw: str) -> str:
    argument = raw.strip()
    if len(argument) >= 2 and (
        (argument[0] == '"' and argument[-1] == '"')
        or (argument[0] == "<" and argument[-1] == ">")
    ):
        argument = argument[1:-1]
    elif any(character.isspace() for character in argument):
        raise ValueError("Asterisk-Include-Pfad ist nicht sicher interpretierbar.")
    if not argument or "\x00" in argument or "${" in argument:
        raise ValueError("Asterisk-Include-Pfad ist nicht sicher interpretierbar.")
    return argument


def _validate_codes(codes: Iterable[str]) -> None:
    for code in codes:
        if code and not _DTMF_CODE.fullmatch(code):
            raise ValueError("Asterisk-Featurecode muss 1 bis 8 Zeichen aus 0-9, * und # haben.")


def _ensure_unambiguous(codes: dict[str, str]) -> None:
    entries = list(codes.items())
    for index, (left_name, left_code) in enumerate(entries):
        for right_name, right_code in entries[index + 1 :]:
            if _conflicts(left_code, right_code, prefixes=True):
                raise ValueError(
                    "Konfigurierte Asterisk-Steuercodes sind gleich oder präfixmehrdeutig "
                    f"({left_name}, {right_name})."
                )


def _choose_code(preferred: str, occupied: Iterable[str], *, prefixes: bool) -> str:
    occupied_codes = tuple(occupied)
    for candidate in _code_candidates(preferred):
        if all(not _conflicts(candidate, code, prefixes=prefixes) for code in occupied_codes):
            return candidate
    raise ValueError("Kein freier Asterisk-Featurecode verfügbar.")


def _code_candidates(preferred: str) -> Iterator[str]:
    yield preferred
    preferred_candidates = (
        *(f"*{digit}" for digit in "1234567890"),
        *(f"#{digit}" for digit in "1234567890"),
        *tuple(_CANDIDATE_ALPHABET),
    )
    yielded = {preferred}
    for candidate in preferred_candidates:
        if candidate not in yielded:
            yielded.add(candidate)
            yield candidate
    for length in range(2, 9):
        for characters in itertools.product(_CANDIDATE_ALPHABET, repeat=length):
            candidate = "".join(characters)
            if candidate not in yielded:
                yield candidate


def _conflicts(left: str, right: str, *, prefixes: bool) -> bool:
    if left == right:
        return True
    return prefixes and (left.startswith(right) or right.startswith(left))
