"""Eigene deutsche Zahlenbausteine fuer Asterisk-Queue-Positionen."""

from __future__ import annotations

from pathlib import Path

ASTERISK_QUEUE_LANGUAGE = "de_kienzlefon"

# Die Dateinamen entsprechen exakt ast_say_number_full_de in Asterisk say.c.
# Die Reihenfolge ist zugleich die stabile Fortsetzung des Ansagenkatalogs.
QUEUE_NUMBER_PROMPTS = {
    **{f"queue_digit_{number}": str(number) for number in range(20)},
    **{f"queue_digit_{number}_and": f"{number}-and" for number in range(1, 10)},
    **{f"queue_digit_{number}": str(number) for number in range(20, 100, 10)},
    "queue_digit_one_neuter": "1N",
    "queue_digit_one_feminine": "1F",
    "queue_digit_hundred": "hundred",
    "queue_digit_thousand": "thousand",
    "queue_digit_million": "million",
    "queue_digit_millions": "millions",
    "queue_digit_milliard": "milliard",
    "queue_digit_milliards": "milliards",
}

QUEUE_NUMBER_TEXTS = {
    "queue_digit_0": "Null",
    "queue_digit_1": "Eins",
    "queue_digit_2": "Zwei",
    "queue_digit_3": "Drei",
    "queue_digit_4": "Vier",
    "queue_digit_5": "Fünf",
    "queue_digit_6": "Sechs",
    "queue_digit_7": "Sieben",
    "queue_digit_8": "Acht",
    "queue_digit_9": "Neun",
    "queue_digit_10": "Zehn",
    "queue_digit_11": "Elf",
    "queue_digit_12": "Zwölf",
    "queue_digit_13": "Dreizehn",
    "queue_digit_14": "Vierzehn",
    "queue_digit_15": "Fünfzehn",
    "queue_digit_16": "Sechzehn",
    "queue_digit_17": "Siebzehn",
    "queue_digit_18": "Achtzehn",
    "queue_digit_19": "Neunzehn",
    "queue_digit_1_and": "Einund",
    "queue_digit_2_and": "Zweiund",
    "queue_digit_3_and": "Dreiund",
    "queue_digit_4_and": "Vierund",
    "queue_digit_5_and": "Fünfund",
    "queue_digit_6_and": "Sechsund",
    "queue_digit_7_and": "Siebenund",
    "queue_digit_8_and": "Achtund",
    "queue_digit_9_and": "Neunund",
    "queue_digit_20": "Zwanzig",
    "queue_digit_30": "Dreißig",
    "queue_digit_40": "Vierzig",
    "queue_digit_50": "Fünfzig",
    "queue_digit_60": "Sechzig",
    "queue_digit_70": "Siebzig",
    "queue_digit_80": "Achtzig",
    "queue_digit_90": "Neunzig",
    "queue_digit_one_neuter": "Ein",
    "queue_digit_one_feminine": "Eine",
    "queue_digit_hundred": "Hundert",
    "queue_digit_thousand": "Tausend",
    "queue_digit_million": "Million",
    "queue_digit_millions": "Millionen",
    "queue_digit_milliard": "Milliarde",
    "queue_digit_milliards": "Milliarden",
}

if QUEUE_NUMBER_PROMPTS.keys() != QUEUE_NUMBER_TEXTS.keys():
    raise RuntimeError("Queue-Zahlenkatalog und Standardtexte sind nicht deckungsgleich")


def digit_directory(prompts_directory: Path) -> Path:
    """Leitet den eigenen Asterisk-Sprachordner aus dem Sounds-Pfad ab."""
    return prompts_directory.parent / ASTERISK_QUEUE_LANGUAGE / "digits"


def digit_output_paths(prompts_directory: Path, prompt_name: str) -> tuple[Path, ...]:
    filename = QUEUE_NUMBER_PROMPTS.get(prompt_name)
    if filename is None:
        return ()
    directory = digit_directory(prompts_directory)
    return tuple(directory / f"{filename}.{suffix}" for suffix in ("sln16", "g722", "alaw", "ulaw"))


def german_number_files(number: int) -> tuple[str, ...]:
    """Spiegelt die Dateiauswahl von ast_say_number_full_de fuer Tests/Dokumentation."""
    if number < 0 or number > 2_147_483_647:
        raise ValueError("Queue-Position muss zwischen 0 und INT_MAX liegen")
    if number == 0:
        return ("0",)

    result: list[str] = []
    remainder = number
    composed = False
    while remainder:
        if remainder < 20:
            result.append(str(remainder))
            remainder = 0
        elif remainder < 100:
            ones = remainder % 10
            if ones:
                result.append(f"{ones}-and")
                remainder -= ones
            else:
                result.append(str(remainder))
                remainder = 0
        elif remainder == 100 and not composed:
            result.append("hundred")
            remainder = 0
        elif remainder < 1000:
            hundreds, remainder = divmod(remainder, 100)
            result.extend(("1N" if hundreds == 1 else str(hundreds), "hundred"))
        elif remainder == 1000 and not composed:
            result.append("thousand")
            remainder = 0
        elif remainder < 1_000_000:
            thousands, remainder = divmod(remainder, 1000)
            composed = True
            if thousands == 1:
                result.extend(("1N", "thousand"))
            else:
                result.extend((*german_number_files(thousands), "thousand"))
        elif remainder < 1_000_000_000:
            millions, remainder = divmod(remainder, 1_000_000)
            composed = True
            if millions == 1:
                result.extend(("1F", "million"))
            else:
                result.extend((*german_number_files(millions), "millions"))
        else:
            milliards, remainder = divmod(remainder, 1_000_000_000)
            composed = True
            if milliards == 1:
                result.extend(("1F", "milliard"))
            else:
                result.extend((*german_number_files(milliards), "milliards"))
    return tuple(result)
