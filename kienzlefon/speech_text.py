"""Deterministic German number and time spelling before local speech synthesis."""

from __future__ import annotations

import re

SPEECH_TEXT_VERSION = "de-numbers-1"

_SMALL = (
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
    "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn",
    "siebzehn", "achtzehn", "neunzehn",
)
_TENS = ("", "", "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig",
         "achtzig", "neunzig")


def _integer(value: int) -> str:
    if value < 20:
        return _SMALL[value]
    if value < 100:
        tens, unit = divmod(value, 10)
        return (("ein" if unit == 1 else _SMALL[unit]) + "und" if unit else "") + _TENS[tens]
    for scale, singular, plural in (
        (10**12, "eine Billion", "Billionen"),
        (10**9, "eine Milliarde", "Milliarden"),
        (10**6, "eine Million", "Millionen"),
        (1000, "eintausend", "tausend"),
        (100, "einhundert", "hundert"),
    ):
        if value >= scale:
            count, rest = divmod(value, scale)
            separator = " " if scale >= 10**6 else ""
            prefix = singular if count == 1 else _integer(count) + separator + plural
            return prefix + (separator + _integer(rest) if rest else "")
    raise AssertionError("Unreachable number range")


def _number(value: str) -> str:
    whole, comma, fraction = value.replace(".", "").partition(",")
    # Leading zeroes denote digit sequences (e.g. phone numbers), not quantities.
    # Bound integer conversion for arbitrarily long user-supplied text as well.
    if (len(whole) > 1 and whole.startswith("0")) or len(whole) > 15:
        spoken = " ".join(_SMALL[int(digit)] for digit in whole)
    else:
        spoken = _integer(int(whole))
    if comma:
        spoken += " Komma " + " ".join(_SMALL[int(digit)] for digit in fraction)
    return spoken


# Ordered alternatives preserve pause controls and recognize clocks before numbers.
# A dot is a clock separator only with an explicit Uhr suffix; otherwise it may
# be a thousands separator or punctuation.
_TOKENS = re.compile(
    r"(?P<pause>\{pause:[0-9]+\})"
    r"|(?P<midnight>(?<![\w:])24(?::00(?![0-9:])(?:\s*Uhr\b)?|\.00\s*Uhr\b))"
    r"|(?<![\w:])(?P<colon_hour>[01]?[0-9]|2[0-3]):(?P<colon_minute>[0-5][0-9])"
    r"(?![0-9:])(?:\s*Uhr\b)?"
    r"|(?<![\w.])(?P<dot_hour>[01]?[0-9]|2[0-3])\."
    r"(?P<dot_minute>[0-5][0-9])\s*Uhr\b"
    r"|(?<!\w)(?P<hour>[01]?[0-9]|2[0-4])\s*Uhr\b"
    r"(?:\s+(?P<minute>[0-5][0-9])(?![0-9]))?"
    r"|(?P<number>[0-9]{1,3}(?:\.[0-9]{3})+(?![0-9])(?:,[0-9]+)?|[0-9]+(?:,[0-9]+)?)",
    re.IGNORECASE,
)


def normalize_german_speech(text: str) -> str:
    """Spell numbers and 24-hour clock times; keep pause markers unchanged.

    The editable source text remains unchanged. This function is shared by
    synthesis and cache calculation so existing digit-based audio is refreshed.
    """
    def replace(match: re.Match[str]) -> str:
        if match.group("pause") is not None:
            return match.group()
        if match.group("number") is not None:
            return _number(match.group("number"))
        if match.group("midnight") is not None:
            return "vierundzwanzig Uhr"
        hour = int(match.group("colon_hour") or match.group("dot_hour") or match.group("hour"))
        minute = int(
            match.group("colon_minute") or match.group("dot_minute") or match.group("minute") or 0
        )
        spoken = ("ein" if hour == 1 else _integer(hour)) + " Uhr"
        return spoken + (" " + _integer(minute) if minute else "")

    return _TOKENS.sub(replace, text)
