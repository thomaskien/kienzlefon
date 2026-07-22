# kienzlefon tests
# Version: 1.9
# Changelog:
# - 1.9: Demo-Anonymisierung konservativ migriert und boolesch aktualisiert.
# - 1.8.2: Notruf- und Fallback-Standardtexte konservativ migriert.
# - 1.8: Fehlenden Demomodus konservativ als deaktiviert migriert.
# - 1.7: Optionales Rottelefon und Sonderqueue konservativ migriert.
# - 1.6: Konservative Migration des bisherigen Whisper-Modells getestet.
# - 1.5: Neue Audioziele und Signalton-Standardtext migriert.
# - 1.4: Entfernung der PIN und konservative Textmigration getestet.
# - 1.3: Konservative TOML-Migration fehlender 1.3-Werte getestet.

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from kienzlefon.migration import migrate_config, set_boolean, set_string


def test_migration_adds_missing_values_without_overwriting(tmp_path: Path) -> None:
    template = Path("config/kienzlefon.toml.example")
    source = template.read_text(encoding="utf-8")
    source = re.sub(r"\n\[ansagen_ivr\].*?(?=\n\[sip_direkte_queue\])", "", source, flags=re.S)
    source = source.replace("length_scale = 1.3", "length_scale = 1.7")
    source = re.sub(r"^ziel_lautheit_lufs\s*=.*\n", "", source, flags=re.M)
    source = re.sub(r"^max_true_peak_db\s*=.*\n", "", source, flags=re.M)
    source = source.replace("rotes_telefon_aktiv = true\n", "")
    source = source.replace("demo = false\n", "")
    source = source.replace("anrufernummern_anonymisieren = false\n", "")
    source = re.sub(r"\n\[sonderqueue\].*?(?=\n\[wahlregeln\])", "", source, flags=re.S)
    source = source.replace(
        'blocked_destination = "Dieses Anrufziel ist gesperrt."\n', ""
    )
    target = tmp_path / "kienzlefon.toml"
    target.write_text(source, encoding="utf-8")

    assert migrate_config(target, template) is True
    assert migrate_config(target, template) is False
    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert result["tts"]["length_scale"] == 1.7
    assert result["tts"]["ziel_lautheit_lufs"] == -19.0
    assert result["tts"]["max_true_peak_db"] == -2.0
    assert result["ansagen_ivr"]["nebenstelle"] == "777"
    assert result["ansagen"]["blocked_destination"] == "Dieses Anrufziel ist gesperrt."
    assert result["ivr"]["rotes_telefon_aktiv"] is True
    assert result["sonderqueue"]["name"] == "kienzlefon-sonder"
    assert result["sonderqueue"]["zusaetzliche_nebenstellen"] == []
    assert result["telepraxis"]["demo"] is False
    assert result["telepraxis"]["anrufernummern_anonymisieren"] is False


def test_migration_removes_pin_and_only_replaces_old_defaults(tmp_path: Path) -> None:
    template = Path("config/kienzlefon.toml.example")
    source = template.read_text(encoding="utf-8")
    source = source.replace(
        'nebenstelle = "777"\n',
        'nebenstelle = "777"\npin = "654321"\npin_versuche = 3\n',
    )
    source = source.replace(
        'admin_main = "Sie befinden sich in der internen Verwaltung der Telefonansagen. Für die Verwaltung einzelner Ansagen drücken Sie 1. Für die Feiertags- und Sonderansage drücken Sie 2. Zum Beenden drücken Sie 0."',
        'admin_main = "Für die Ansagenverwaltung drücken Sie 1. Für die Override-Steuerung drücken Sie 2. Zum Beenden drücken Sie 0."',
    )
    source = source.replace(
        'admin_invalid = "Diese Eingabe ist nicht verfügbar. Bitte versuchen Sie es erneut."',
        'admin_invalid = "Eigener Hinweis der Praxis."',
    )
    source = source.replace(
        'admin_record = "Sprechen Sie nach dem Signalton. Beenden Sie die Aufnahme mit einer beliebigen Taste oder durch eine längere Sprechpause."',
        'admin_record = "Sprechen Sie nach dem Ende dieser Ansage. Die Aufnahme beginnt sofort und ohne Signalton. Beenden Sie die Aufnahme mit einer beliebigen Taste oder durch eine längere Sprechpause."',
    )
    source = source.replace(
        'emergency = "Bei lebensbedrohlichen Notfällen wählen Sie bitte sofort die eins eins zwei."',
        'emergency = "Bei lebensbedrohlichen Notfällen wählen Sie bitte sofort die 112."',
    )
    source = source.replace(
        'urgent_help = "Bei dringenden Beschwerden außerhalb unserer Sprechzeiten wenden Sie sich bitte an den ärztlichen Bereitschaftsdienst unter eins eins sechs, eins eins sieben."',
        'urgent_help = "Bei dringenden Beschwerden außerhalb unserer Sprechzeiten wenden Sie sich bitte an den ärztlichen Bereitschaftsdienst unter 116117."',
    )
    source = source.replace("Nachname und Geburtstag und", "Nachname und Geburtsdatum und")
    source += '\nadmin_pin = "Bitte PIN eingeben."\n'
    target = tmp_path / "old.toml"
    target.write_text(source, encoding="utf-8")

    assert migrate_config(target, template) is True
    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert "pin" not in result["ansagen_ivr"]
    assert "pin_versuche" not in result["ansagen_ivr"]
    assert "admin_pin" not in result["ansagen"]
    assert "Override-Steuerung" not in result["ansagen"]["admin_main"]
    assert result["ansagen"]["admin_invalid"] == "Eigener Hinweis der Praxis."
    assert "nach dem Signalton" in result["ansagen"]["admin_record"]
    assert "eins eins zwei" in result["ansagen"]["emergency"]
    assert "eins eins sechs, eins eins sieben" in result["ansagen"]["urgent_help"]
    assert "Geburtstag" in result["ansagen"]["no_selection_closed"]
    assert "Geburtstag" in result["ansagen"]["personal_data_fallback"]


def test_migration_preserves_custom_fallback_prompt(tmp_path: Path) -> None:
    template = Path("config/kienzlefon.toml.example")
    source = template.read_text(encoding="utf-8").replace(
        'no_selection_closed = "Bitte sagen Sie Vorname, Nachname und Geburtstag und sagen Sie uns, worum es geht. Wir können Sie auch zurückrufen. Bitte nennen Sie uns gegebenenfalls eine Rückrufnummer. Danach einfach auflegen."',
        'no_selection_closed = "Eigener Fallbacktext der Praxis."',
    )
    target = tmp_path / "custom.toml"
    target.write_text(source, encoding="utf-8")

    assert migrate_config(target, template) is False
    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert result["ansagen"]["no_selection_closed"] == "Eigener Fallbacktext der Praxis."


def test_migration_preserves_legacy_whisper_model_as_standard(tmp_path: Path) -> None:
    template = Path("config/kienzlefon.toml.example")
    source = template.read_text(encoding="utf-8")
    source = re.sub(
        r'^modell_standard = .*\nmodell_namen = .*\nmodell_medikamente = .*$',
        'modell = "large-v3"',
        source,
        flags=re.M,
    )
    source = re.sub(r"^initial_prompt_(vorname|nachname|medikamente) = .*\n", "", source, flags=re.M)
    target = tmp_path / "legacy.toml"
    target.write_text(source, encoding="utf-8")

    assert migrate_config(target, template) is True
    assert migrate_config(target, template) is False
    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert "modell" not in result["whisper"]
    assert result["whisper"]["modell_standard"] == "large-v3"
    assert result["whisper"]["modell_namen"] == "large-v3"
    assert result["whisper"]["modell_medikamente"] == "large-v3-turbo"
    assert "Wirkstoff" in result["whisper"]["initial_prompt_medikamente"]


def test_set_string_preserves_following_toml_sections(tmp_path: Path) -> None:
    target = tmp_path / "kienzlefon.toml"
    target.write_text(Path("config/kienzlefon.toml.example").read_text(encoding="utf-8"))

    set_string(target, "whisper", "modell_standard", "large-v3")
    set_string(target, "whisper", "modell_namen", "large-v3-turbo")
    set_string(target, "whisper", "modell_medikamente", "large-v3")

    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert result["whisper"]["modell_standard"] == "large-v3"
    assert result["whisper"]["modell_namen"] == "large-v3-turbo"
    assert result["whisper"]["modell_medikamente"] == "large-v3"
    assert result["telepraxis"]["kanal"] == "dahl"
    assert "ansagen" in result


def test_set_boolean_updates_demo_anonymization_only(tmp_path: Path) -> None:
    target = tmp_path / "kienzlefon.toml"
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace("demo = false", "demo = true")
    source = source.replace(
        'public_key = "/etc/kienzlefon/telepraxis-public.pem"', 'public_key = ""'
    )
    target.write_text(source, encoding="utf-8")

    set_boolean(target, "telepraxis", "anrufernummern_anonymisieren", True)

    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert result["telepraxis"]["demo"] is True
    assert result["telepraxis"]["anrufernummern_anonymisieren"] is True
    assert result["telepraxis"]["public_key"] == ""
    assert result["whisper"]["modell_standard"] == "large-v3-turbo"
