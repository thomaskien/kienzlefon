# kienzlefon tests
# Version: 1.9.1
# Changelog:
# - 1.9.1: Asterisk-wav16-Pruefung ohne falschnegatives pipefail getestet.
# - 1.9: Demo-Anonymisierung bei Neuinstallation und Updateabfrage getestet.
# - 1.8.3: Installerfreigabe fuer Version 1.8.3 aktualisiert.
# - 1.8.2: Installerfreigabe fuer Version 1.8.2 aktualisiert.
# - 1.8.1: Dynamische Worker-Gruppe, UMask und Installerfreigabe getestet.
# - 1.8: Demo-Warnung, Demo-TOML und Installerfreigabe fuer Version 1.8 getestet.
# - 1.7.1: Installerfreigabe und Rottelefon-Hinweis fuer die Sonderqueue getestet.
# - 1.7: Rottelefonfrage und Auswahl der Sonderqueue-Mitglieder getestet.
# - 1.6.2: Installerfreigabe fuer das AGI-Hangup-Patchrelease aktualisiert.
# - 1.6.1: FFmpeg-Filterpruefung ohne falschnegatives pipefail getestet.
# - 1.6: Modellbereichsauswahl, RAM-Warnung und TOML-Ausgabe getestet.
# - 1.5: Installerfreigabe und Audioziele der Version 1.5 getestet.
# - 1.4: PIN-freien Installer und Versionsfreigabe 1.4 getestet.
# - 1.3: Installerfreigabe und neue 1.3-Konfigurationswerte getestet.
# - 1.2: Zeitkopien, Updateabfrage und ausschliessliches Zeitupdate getestet.
# - 1.1: Neue TTS-, IVR- und Notfallwerte des Installers getestet.
# - 1.0: Shellsyntax und sichere TOML-Erzeugung des Installers getestet.

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path


def test_installer_shell_syntax() -> None:
    subprocess.run(["bash", "-n", "kienzlefon-installer.sh"], check=True)


def test_embedded_config_writer_preserves_secrets_and_schedules(tmp_path: Path) -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    marker = "# kienzlefon installer config writer"
    start = installer.index(marker)
    end = installer.index("\nPY\n", start)
    writer = tmp_path / "writer.py"
    writer.write_text(installer[start:end] + "\n", encoding="utf-8")
    target = tmp_path / "kienzlefon.toml"
    target.write_text(Path("config/kienzlefon.toml.example").read_text(encoding="utf-8"))
    environment = dict(os.environ)
    environment.update(
        {
            "SOURCE_TARGET": str(Path.cwd()),
            "CONFIG_FILE": str(target),
            "PUBLIC_KEY_FILE": str(tmp_path / "public.pem"),
            "KZF_PRACTICE_NAME": "Praxis Test",
            "KZF_RED_ENABLED": "y",
            "KZF_RED_EXTENSION": "299",
            "KZF_CPU_THREADS": "4",
            "KZF_MODEL_STANDARD": "large-v3-turbo",
            "KZF_MODEL_NAMES": "large-v3",
            "KZF_MODEL_MEDICATIONS": "large-v3-turbo",
            "KZF_CHANNEL": "dahl",
            "KZF_OUTPUT_DIR": "/srv/telepraxis/dahl/inbox",
            "KZF_DEMO_MODE": "n",
            "KZF_DEMO_ANONYMIZE": "n",
            "KZF_TTS_VOICE": "de_DE-thorsten-high",
            "KZF_TTS_LENGTH_SCALE": "1.4",
            "KZF_TTS_SENTENCE_SILENCE": "0.9",
            "KZF_ANNOUNCEMENT_PAUSE_MS": "750",
            "KZF_RED_PASSWORD": "a#b;c",
            "KZF_RED_RING_SECONDS": "25",
            "KZF_RED_PRIORITY": "120",
            "KZF_MAIN_ENDPOINT": "kfx-phone-in-endpoint",
            "KZF_MAIN_NUMBER": "4923311234",
            "KZF_OUT_COUNTS": "y",
            "KZF_FIRST_EXTENSION": "201",
            "KZF_EXTENSION_COUNT": "3",
            "KZF_AREA_CODE": "02331",
            "KZF_PRACTICE_NUMBER": "123456",
        }
    )
    for prefix in ("KZF_OPEN", "KZF_PHONE", "KZF_PHARMACY", "KZF_SPECIALIST"):
        for day in (
            "MONTAG",
            "DIENSTAG",
            "MITTWOCH",
            "DONNERSTAG",
            "FREITAG",
            "SAMSTAG",
            "SONNTAG",
        ):
            environment[f"{prefix}_{day}"] = ""
    environment["KZF_OPEN_MONTAG"] = "08:00-12:00,14:00-17:00"
    for prefix in ("KZF_QUEUE_LINE", "KZF_RED_LINE"):
        environment.update(
            {
                f"{prefix}_AKTIV": "n",
                f"{prefix}_DID": "",
                f"{prefix}_USER": "",
                f"{prefix}_PASSWORD": "",
                f"{prefix}_DOMAIN": "",
                f"{prefix}_PROXY": "",
                f"{prefix}_EXPIRATION": "300",
                f"{prefix}_OUTBOUND": "n",
            }
        )
    subprocess.run([os.sys.executable, str(writer)], check=True, env=environment)
    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert result["praxis"]["name"] == "Praxis Test"
    assert result["oeffnungszeiten"]["montag"] == [
        "08:00-12:00",
        "14:00-17:00",
    ]
    assert result["asterisk"]["rotes_telefon_passwort"] == "a#b;c"
    assert result["tts"]["length_scale"] == 1.4
    assert result["tts"]["sentence_silence"] == 0.9
    assert result["tts"]["ziel_lautheit_lufs"] == -19.0
    assert result["tts"]["max_true_peak_db"] == -2.0
    assert result["whisper"]["modell_standard"] == "large-v3-turbo"
    assert result["whisper"]["modell_namen"] == "large-v3"
    assert result["whisper"]["modell_medikamente"] == "large-v3-turbo"
    assert result["telepraxis"]["demo"] is False
    assert result["telepraxis"]["anrufernummern_anonymisieren"] is False
    assert result["telepraxis"]["public_key"] == str(tmp_path / "public.pem")
    assert result["ivr"]["ansage_pause_ms"] == 750
    assert result["ivr"]["rotes_telefon_klingeldauer_sekunden"] == 25
    assert result["ivr"]["rotes_telefon_queue_prioritaet"] == 120
    assert result["ivr"]["rotes_telefon_aktiv"] is True
    assert result["sonderqueue"]["gewicht"] == 120
    assert result["wahlregeln"]["ortsvorwahl"] == "02331"
    assert result["wahlregeln"]["praxisrufnummer"] == "123456"
    assert "pin" not in result["ansagen_ivr"]

    environment["KZF_DEMO_MODE"] = "y"
    environment["KZF_DEMO_ANONYMIZE"] = "y"
    subprocess.run([os.sys.executable, str(writer)], check=True, env=environment)
    with target.open("rb") as handle:
        demo_result = tomllib.load(handle)
    assert demo_result["telepraxis"]["demo"] is True
    assert demo_result["telepraxis"]["anrufernummern_anonymisieren"] is True
    assert demo_result["telepraxis"]["public_key"] == ""


def test_installer_requires_explicit_start_confirmation() -> None:
    bash = "/bin/bash" if Path("/bin/bash").is_file() else shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "kienzlefon-installer.sh"],
        input="n\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Version: 1.9.1" in result.stdout
    assert "Installation nicht gestartet." in result.stdout


def test_installer_contains_explicit_demo_warning_and_confirmation() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    assert "AUF KEINEN FALL fuer echte Patientendaten" in installer
    assert "Demo-Modus trotz unverschluesselter Ausgabe wirklich aktivieren?" in installer
    assert "Anrufernummern in den Demo-JSON-Dateien anonymisieren?" in installer
    assert "configure_demo_anonymization" in installer
    assert "Audiodateien und in Freitexten genannte Rufnummern" in installer
    assert 'if [[ "$KZF_DEMO_MODE" != "y" ]]; then' in installer


def test_worker_uses_output_directory_group_and_restrictive_umask() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    assert "output_gid=\"$(stat -c '%g' -- \"$output\")\"" in installer
    assert "Group=${output_group}" in installer
    assert "UMask=0007" in installer


def test_update_writer_changes_only_schedules(tmp_path: Path) -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    marker = "# kienzlefon installer time updater"
    start = installer.index(marker)
    end = installer.index("\nPY\n", start)
    updater = tmp_path / "updater.py"
    updater.write_text(installer[start:end] + "\n", encoding="utf-8")

    target = tmp_path / "kienzlefon.toml"
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace('name = "Praxisname"', 'name = "Praxis Unveraendert"')
    target.write_text(source, encoding="utf-8")
    environment = dict(os.environ)
    environment["CONFIG_FILE"] = str(target)
    for prefix in ("KZF_OPEN", "KZF_PHONE", "KZF_PHARMACY", "KZF_SPECIALIST"):
        for day in (
            "MONTAG",
            "DIENSTAG",
            "MITTWOCH",
            "DONNERSTAG",
            "FREITAG",
            "SAMSTAG",
            "SONNTAG",
        ):
            environment[f"{prefix}_{day}"] = ""
    for day in ("MONTAG", "DIENSTAG", "MITTWOCH", "DONNERSTAG", "FREITAG"):
        environment[f"KZF_OPEN_{day}"] = "08:00-12:00"
        environment[f"KZF_PHONE_{day}"] = "08:00-10:00"
        environment[f"KZF_PHARMACY_{day}"] = "08:00-12:00"
        environment[f"KZF_SPECIALIST_{day}"] = "08:00-12:00"

    subprocess.run([os.sys.executable, str(updater)], check=True, env=environment)
    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert result["praxis"]["name"] == "Praxis Unveraendert"
    assert result["oeffnungszeiten"]["montag"] == ["08:00-12:00"]
    assert result["telefonzeiten"]["freitag"] == ["08:00-10:00"]
    assert result["apothekenzeiten"] == result["oeffnungszeiten"]
    assert result["fachstellenzeiten"] == result["oeffnungszeiten"]
    assert "Zeitprofile jetzt neu konfigurieren?" in installer
    assert "copy_schedule KZF_OPEN KZF_PHARMACY" in installer
    assert "copy_schedule KZF_OPEN KZF_SPECIALIST" in installer


def test_installer_checks_wav16_and_loudnorm_support() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    assert "ffmpeg_supports_filter loudnorm" in installer
    assert "ffmpeg -hide_banner -filters 2>/dev/null | grep -q" not in installer
    assert "core show file formats" in installer
    assert "Aufnahmeformat wav16" in installer


def test_asterisk_format_check_is_safe_with_pipefail() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    start = installer.index("asterisk_supports_format(){")
    end = installer.index("\n}\n", start) + 3
    function = installer[start:end]
    script = f"""set -o pipefail
asterisk() {{
  printf '%s\\n' \\
    'Format     Name       Extensions' \\
    '------     ----       ----------' \\
    'slin16     wav16      wav16'
}}
{function}
asterisk_supports_format wav16
"""
    result = subprocess.run(["bash", "-c", script], check=False)
    assert result.returncode == 0


def test_ffmpeg_filter_check_is_safe_with_pipefail() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    start = installer.index("ffmpeg_supports_filter(){")
    end = installer.index("\n}\n", start) + 3
    function = installer[start:end]
    script = f"""set -o pipefail
ffmpeg() {{
  printf '%s\\n' 'Filters:' ' ... loudnorm          A->A       EBU R128'
}}
{function}
ffmpeg_supports_filter loudnorm
"""
    result = subprocess.run(["bash", "-c", script], check=False)
    assert result.returncode == 0


def test_installer_explains_model_choices_and_ram_warning() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    assert "etwa dreimal so schnell wie large-v3" in installer
    assert "Mit 8 GB ist die Verwendung beider Modelle moeglich, aber nicht empfohlen" in installer
    assert "Beide Modelle trotzdem verwenden?" in installer
    assert "Whisper-Modell fuer Vor- und Nachnamen" in installer
    assert "Whisper-Modell fuer Medikamente und Wirkstoffe" in installer
    assert "Whisper-Modell fuer alle uebrigen Aufnahmen" in installer


def test_installer_asks_for_red_phone_and_explains_special_queue() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    assert "Wird ein rotes Telefon verwendet?" in installer
    assert "Wenn nein, fuehrt Taste 9 direkt zur priorisierten Sonderqueue" in installer
    assert "besetzt, nicht erreichbar oder nicht angenommen" in installer
    assert "bei Nutzung auch das rote Telefon" in installer
    assert "Sollen zusaetzliche Nebenstellen in der Sonderqueue mitklingeln?" in installer


def test_special_queue_updater_validates_known_additional_extensions(tmp_path: Path) -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    marker = "# kienzlefon installer special queue updater"
    start = installer.index(marker)
    end = installer.index("\nPY\n", start)
    updater = tmp_path / "special_queue_updater.py"
    updater.write_text(installer[start:end] + "\n", encoding="utf-8")

    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace("nebenstellen = []", 'nebenstellen = ["300", "301"]', 1)
    source = source.replace("passwoerter = []", 'passwoerter = ["secret-300", "secret-301"]', 1)
    target = tmp_path / "kienzlefon.toml"
    target.write_text(source, encoding="utf-8")
    environment = dict(os.environ)
    environment.update(
        {
            "CONFIG_FILE": str(target),
            "KZF_RED_ENABLED": "n",
            "KZF_SPECIAL_MEMBERS": "300,301",
        }
    )
    subprocess.run([os.sys.executable, str(updater)], check=True, env=environment)
    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert result["ivr"]["rotes_telefon_aktiv"] is False
    assert result["sonderqueue"]["zusaetzliche_nebenstellen"] == ["300", "301"]


def test_additional_extension_updater_preserves_following_toml_sections(tmp_path: Path) -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    marker = "# kienzlefon installer extension updater"
    start = installer.index(marker)
    end = installer.index("\nPY\n", start)
    updater = tmp_path / "extension_updater.py"
    updater.write_text(installer[start:end] + "\n", encoding="utf-8")
    target = tmp_path / "kienzlefon.toml"
    target.write_text(Path("config/kienzlefon.toml.example").read_text(encoding="utf-8"))
    environment = dict(os.environ)
    environment.update({"CONFIG_FILE": str(target), "KZF_EXTRA_COUNT": "2"})

    subprocess.run([os.sys.executable, str(updater)], check=True, env=environment)
    with target.open("rb") as handle:
        result = tomllib.load(handle)
    assert result["zusaetzliche_nebenstellen"]["nebenstellen"] == ["300", "301"]
    assert len(result["zusaetzliche_nebenstellen"]["passwoerter"]) == 2
    assert result["sonderqueue"]["name"] == "kienzlefon-sonder"
    assert result["wahlregeln"]["landesvorwahl"] == "49"
