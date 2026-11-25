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
AFTER_CONCERN = {
    "weiteres_anliegen": ("1", "Weiteres Anliegen aufnehmen"),
    "anliegen_fertig": ("2", "Aufnahme abschließen"),
}
MENUS = (MAIN, SUBMENU, MEDICATION, AFTER_CONCERN)
DEFAULTS = {name: value[0] for menu in MENUS for name, value in menu.items()}
GENERATED_PROMPTS = {
    "menu_open", "menu_closed", "opening_hours_choice", "pharmacy_access",
    "specialist_access", "submenu_five", "medication_choice", "more_concern", "concern_types",
}


MENU_PROMPTS = ("menu_intro", "menu_open", "menu_closed", "opening_hours_choice",
                "pharmacy_access", "specialist_access", "phone_hours")
MENU_CHOICES = ("praxis", "rezept", "ueberweisung", "termin", "weitere")


def validated_order(value: object, choices: tuple[str, ...]) -> tuple[str, ...]:
    if (not isinstance(value, (tuple, list)) or len(value) != len(choices)
            or any(not isinstance(item, str) for item in value) or set(value) != set(choices)):
        raise ValueError("Die Reihenfolge muss jede Ansage genau einmal enthalten")
    return tuple(value)


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


def generated_texts(keys: Mapping[str, str], order: tuple[str, ...] = MENU_CHOICES) -> dict[str, str]:
    def sentence(name: str, words: str) -> str:
        key = keys[name]
        spoken = {"*": "Stern", "#": "Raute"}.get(key, key)
        return f"{words} drücken Sie {spoken}." if key else ""

    def combined(choices: dict[str, str]) -> str:
        return " ".join(filter(None, (sentence(name, words) for name, words in choices.items())))

    concern_menu = {
        "rezept": "Für ein Rezept",
        "ueberweisung": "Für eine Überweisung",
        "termin": "Für einen Termin",
        "weitere": "Für eine Rückrufbitte oder ein sonstiges Anliegen",
    }
    menu = {"praxis": "Um mit der Praxis zu sprechen", **concern_menu}
    closed = combined({name: menu[name] for name in order if name != "praxis"})
    additional = dict(concern_menu)
    if not (keys["rueckruf"] or keys["sonstiges"]):
        additional.pop("weitere")
    opened = combined({name: menu[name] for name in order})
    return {
        "menu_open": opened or "Bitte bleiben Sie in der Leitung.",
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
        "more_concern": " ".join(filter(None, (
            "Haben Sie noch ein weiteres Anliegen?",
            sentence("weiteres_anliegen", "Für ein weiteres Anliegen"),
            sentence("anliegen_fertig", "Zum Abschließen"),
        ))),
        "concern_types": combined(additional) or "Vielen Dank.",
    }


FOLLOWUP_PROMPTS = {name: value for name, value in generated_texts(DEFAULTS).items()
                    if name in {"more_concern", "concern_types"}}
