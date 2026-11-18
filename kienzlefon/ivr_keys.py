"""The configurable caller choices shared by the AGI, prompts and admin tree."""

from collections.abc import Mapping


MAIN = {
    "ki": ("0", "KI-Assistent"),
    "praxis": ("1", "Praxiswarteschlange"),
    "rezept": ("2", "Rezept"),
    "ueberweisung": ("3", "Überweisung"),
    "termin": ("4", "Termin"),
    "weitere": ("5", "Rückruf oder sonstiges Anliegen"),
    "oeffnungszeiten": ("6", "Öffnungszeiten"),
    "apotheke": ("8", "Apotheke"),
    "rot": ("9", "ROT"),
}
SUBMENU = {
    "rueckruf": ("1", "Rückrufbitte"),
    "sonstiges": ("2", "Sonstiges Anliegen"),
}
MEDICATION = {
    "weiteres_medikament": ("1", "Ein weiteres Medikament"),
    "rezept_fertig": ("2", "Bestellung abschließen"),
}
MENUS = (MAIN, SUBMENU, MEDICATION)
DEFAULTS = {name: value[0] for menu in MENUS for name, value in menu.items()}
GENERATED_PROMPTS = {
    "menu_open", "menu_closed", "opening_hours_choice", "pharmacy_access",
    "specialist_access", "submenu_five", "medication_choice",
}


def validate_keys(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping) or raw.keys() - DEFAULTS.keys():
        raise ValueError("Unbekannte IVR-Funktion")
    result = {**DEFAULTS, **raw}
    for menu in MENUS:
        used = set()
        for action in menu:
            key = result[action]
            if not isinstance(key, str) or key not in {"", *"0123456789*#"}:
                raise ValueError(f"IVR-Taste für {menu[action][1]} ist ungültig")
            if key and key in used:
                raise ValueError(f"IVR-Taste {key} ist innerhalb eines Menüs doppelt belegt")
            used.add(key)
    return result


def generated_texts(keys: Mapping[str, str]) -> dict[str, str]:
    def sentence(name: str, words: str) -> str:
        key = keys[name]
        spoken = {"*": "Stern", "#": "Raute"}.get(key, key)
        return f"{words} drücken Sie {spoken}." if key else ""

    def combined(choices: dict[str, str]) -> str:
        return " ".join(filter(None, (sentence(name, words) for name, words in choices.items())))

    closed = combined({
        "rezept": "Für ein Rezept",
        "ueberweisung": "Für eine Überweisung",
        "termin": "Für einen Termin",
        "weitere": "Für eine Rückrufbitte oder ein sonstiges Anliegen",
    })
    opened = combined({"praxis": "Um mit der Praxis zu sprechen"})
    return {
        "menu_open": " ".join(filter(None, (opened, closed))) or "Bitte bleiben Sie in der Leitung.",
        "menu_closed": closed or "Bitte bleiben Sie in der Leitung.",
        "opening_hours_choice": sentence("oeffnungszeiten", "Für unsere Öffnungszeiten") or "Bitte bleiben Sie in der Leitung.",
        "pharmacy_access": sentence("apotheke", "Apotheken") or "Bitte bleiben Sie in der Leitung.",
        "specialist_access": sentence("rot", "Krankenhäuser, Rettungsdienste, Notärzte und ärztliche Kollegen")
        or "Bitte bleiben Sie in der Leitung.",
        "submenu_five": combined({"rueckruf": "Für eine Rückrufbitte", "sonstiges": "Für ein sonstiges Anliegen"})
        or "Bitte bleiben Sie in der Leitung.",
        "medication_choice": combined({
            "weiteres_medikament": "Für ein weiteres Medikament",
            "rezept_fertig": "Zum Abschluss der Bestellung",
        }) or "Vielen Dank.",
    }
