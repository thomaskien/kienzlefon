# kienzlefon tests
# Version: 2.5.2
# Changelog:
# - 2.4.0: Integriertes Webinterface und einheitliche Versionsfuehrung getestet.
# - 2.3.2: Patchrelease fuer die sofortige AI-Medienbridge freigegeben.
# - 2.3.1: Patchrelease fuer die DTMF-leere Eingangsphase freigegeben.
# - 2.3: Geschuetzten Result-Speicher und Asterisk-Feature-Reload getestet.
# - 2.2: AI-Admission-Abfragen und Releasekennung getestet.
# - 2.1.2: Patchrelease fuer den Webinterface-Boot-Refresh freigegeben.
# - 2.1.1: Optionale Webinterface-Installation und ihre Erfolgswege getestet.
# - 1.9.3: Installerfreigabe fuer die Leeranrufunterdrueckung aktualisiert.
# - 1.9.2: Demo- und Nicht-Demo-Zweig der Update-Anonymisierungsabfrage ausgefuehrt.
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

import pytest


@pytest.mark.parametrize("function", ["install_packages", "install_kokoro_tts"])
@pytest.mark.parametrize("apt_status", [0, 100])
def test_package_install_waits_for_lock_and_stops_on_failure(
    tmp_path: Path, function: str, apt_status: int,
) -> None:
    source = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    start = source.index(f"{function}(){{")
    end = source.index("\n}\n", start) + 3
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    apt = bin_dir / "apt-get"
    apt.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$APT_LOG"\n'
        '[ "$1" != update ] || exit 0\n'
        '[ "$1" = -o ] && [ "$2" = DPkg::Lock::Timeout=300 ] '
        '&& [ "$3" = install ] && [ "$4" = -y ] || exit 99\n'
        'exit "$APT_STATUS"\n',
        encoding="utf-8",
    )
    apt.chmod(0o755)
    (bin_dir / "python").symlink_to(os.sys.executable)
    config = tmp_path / "config.toml"
    config.write_text('[tts]\nengine = "kokoro"\n', encoding="utf-8")
    runtime = tmp_path / "scripts" / "kokoro" / "install.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        'import os\nfrom pathlib import Path\nPath(os.environ["MODEL_STARTED"]).touch()\n',
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "APT_LOG": str(tmp_path / "apt.log"),
        "APT_STATUS": str(apt_status),
        "MODEL_STARTED": str(tmp_path / "model-started"),
        "VENV": str(tmp_path),
        "SOURCE_TARGET": str(tmp_path),
        "CONFIG_FILE": str(config),
    }
    script = (
        "set -euo pipefail\n"
        "ffmpeg_supports_filter(){ return 0; }\n"
        "python3(){ return 0; }\n"
        + source[start:end] + f"\n{function}\nprintf 'PACKAGES_READY\\n'\n"
    )
    result = subprocess.run(
        ["bash", "-c", script], env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == apt_status
    assert ("PACKAGES_READY" in result.stdout) is (apt_status == 0)
    assert (tmp_path / "model-started").exists() is (
        function == "install_kokoro_tts" and apt_status == 0
    )
    calls = (tmp_path / "apt.log").read_text().splitlines()
    installs = [call for call in calls if call != "update"]
    assert len(installs) == 1
    assert installs[0].startswith("-o DPkg::Lock::Timeout=300 install -y ")


def test_installer_shell_syntax() -> None:
    subprocess.run(["bash", "-n", "kienzlefon-installer.sh"], check=True)


def test_installer_asks_for_ai_extensions_and_exact_listener_binding() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    assert "Soll Kienzlefon AI angebunden werden?" in installer
    assert "Anzahl der anzulegenden KI-Nebenstellen" in installer
    assert "Konkrete WireGuard-IP" in installer
    assert "Konkrete LAN-IP" in installer
    assert "Wildcard- und Multicast-Bindungen sind nicht erlaubt" in installer
    assert "kienzlefon-admission-listener.service" in installer
    assert "/var/lib/kienzlefon/ai-call-results" in installer
    assert "UMask=0077" in installer
    assert "ReadWritePaths=/var/lib/kienzlefon/ai-call-results" in installer
    assert 'asterisk -rx "features reload"' in installer


def test_ai_config_updater_preserves_existing_passwords(tmp_path: Path) -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    marker = "# kienzlefon installer AI config updater"
    start = installer.index(marker)
    end = installer.index("\nPY\n", start)
    updater = tmp_path / "ai_updater.py"
    updater.write_text(installer[start:end] + "\n", encoding="utf-8")
    target = tmp_path / "kienzlefon.toml"
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    source = source.replace(
        "sip_passwoerter = []", 'sip_passwoerter = ["aaaaaaaaaaaaaaaaaaaaaaaa"]'
    )
    source = source.replace("anzahl_nebenstellen = 0", "anzahl_nebenstellen = 1")
    target.write_text(source, encoding="utf-8")
    environment = dict(os.environ)
    environment.update(
        {
            "CONFIG_FILE": str(target),
            "KZF_AI_ENABLED": "y",
            "KZF_AI_COUNT": "3",
            "KZF_AI_LISTENER_MODE": "lan",
            "KZF_AI_LISTENER_IP": "192.168.10.20",
            "KZF_AI_LISTENER_PORT": "8190",
        }
    )

    subprocess.run([os.sys.executable, str(updater)], check=True, env=environment)

    with target.open("rb") as handle:
        result = tomllib.load(handle)["ki_integration"]
    assert result["aktiv"] is True
    assert result["anzahl_nebenstellen"] == 3
    assert result["listener_bindung"] == "lan"
    assert result["listener_ip"] == "192.168.10.20"
    assert result["sip_passwoerter"][0] == "a" * 24
    assert len(result["sip_passwoerter"]) == 3
    assert all(len(password) >= 24 for password in result["sip_passwoerter"])


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
            "KZF_TTS_ENGINE": "qwen",
            "KZF_QWEN_VOICE": "serena",
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
    assert result["tts"]["engine"] == "qwen"
    assert result["tts"]["qwen_stimme"] == "serena"
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
    assert "Version: 2.5.2" in result.stdout
    assert "Installation nicht gestartet." in result.stdout


def _run_webinterface_offer(
    tmp_path: Path,
    choice: str,
    installer_status: int = 0,
    *,
    existing: bool = False,
) -> subprocess.CompletedProcess[str]:
    installer_source = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    start = installer_source.index("install_or_update_webinterface(){")
    end = installer_source.index("\n}\n", start) + 3
    function = installer_source[start:end]
    existing_marker = tmp_path / "existing-webinterface.json"
    function = function.replace(
        "/etc/kienzlefon/webinterface.json", str(existing_marker)
    )
    if existing:
        existing_marker.write_text("{}", encoding="utf-8")

    source_target = tmp_path / "source"
    (source_target / "webinterface").mkdir(parents=True)
    (source_target / "webinterface" / "admin.php").write_text(
        "<?php declare(strict_types=1);",
        encoding="utf-8",
    )
    web_installer = source_target / "kienzlefon-webinterface-installer.sh"
    web_installer.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" > "$CALL_LOG"\n'
        'exit "$WEB_INSTALLER_STATUS"\n',
        encoding="utf-8",
    )
    web_installer.chmod(0o755)

    runner = tmp_path / "run-offer.sh"
    runner.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        + function
        + "\n"
        + 'ask_yes_no(){ printf -v "$1" \'%s\' "$WEB_CHOICE"; }\n'
        + "die(){ printf 'ERROR: %s\\n' \"$*\" >&2; exit 1; }\n"
        + "install_or_update_webinterface\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment.update(
        {
            "SOURCE_TARGET": str(source_target),
            "CALL_LOG": str(tmp_path / "call.log"),
            "WEB_CHOICE": choice,
            "WEB_INSTALLER_STATUS": str(installer_status),
        }
    )
    return subprocess.run(
        ["bash", str(runner)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_installer_can_skip_webinterface_update(tmp_path: Path) -> None:
    result = _run_webinterface_offer(tmp_path, "n")

    assert result.returncode == 0, result.stderr
    assert "Aktivierung uebersprungen" in result.stdout
    assert not (tmp_path / "call.log").exists()


def test_installer_runs_webinterface_update_after_confirmation(tmp_path: Path) -> None:
    result = _run_webinterface_offer(tmp_path, "y")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "call.log").read_text(encoding="utf-8").strip() == "--from-main-installer"


def test_installer_updates_existing_webinterface_without_separate_prompt(
    tmp_path: Path,
) -> None:
    result = _run_webinterface_offer(tmp_path, "n", existing=True)

    assert result.returncode == 0, result.stderr
    assert "mit der Hauptversion aktualisiert" in result.stdout
    assert (tmp_path / "call.log").read_text(encoding="utf-8").strip() == "--from-main-installer"


def test_main_installer_always_reaches_webinterface_offer() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    main = installer[installer.index("main(){") : installer.rindex('\nmain "$@"')]

    assert 'sep "Administrations-Webinterface"' in main
    assert "install_or_update_webinterface" in main
    assert main.index("install_or_update_webinterface") < main.rindex("trap - ERR")


def test_installer_reports_failed_webinterface_update(tmp_path: Path) -> None:
    result = _run_webinterface_offer(tmp_path, "y", installer_status=17)

    assert result.returncode != 0
    assert "Webinterface-Installation oder -Aktualisierung ist fehlgeschlagen" in result.stderr


def test_installer_pins_the_tested_qwen_v15_bootstrap() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")

    assert (
        'QWEN_INSTALLER_URL="https://raw.githubusercontent.com/thomaskien/'
        'kienzlefon-ai/refs/heads/main/install-kienzlefon-qwen3-tts-v1.5.sh"'
    ) in installer
    assert (
        'QWEN_INSTALLER_SHA256="2dd36de682e797f52486352a6ae395559dbeacdb6a47abfa9e82990c8c72dcc3"'
    ) in installer
    assert '"$installer" --offline-only' in installer
    assert 'prompt_arguments+=(--all)' in installer


def test_installer_contains_explicit_demo_warning_and_confirmation() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    assert "AUF KEINEN FALL fuer echte Patientendaten" in installer
    assert "Demo-Modus trotz unverschluesselter Ausgabe wirklich aktivieren?" in installer
    assert "Anrufernummern in den Demo-JSON-Dateien anonymisieren?" in installer
    assert "configure_demo_anonymization" in installer
    assert "Audiodateien und in Freitexten genannte Rufnummern" in installer
    assert 'if [[ "$KZF_DEMO_MODE" != "y" ]]; then' in installer


def test_demo_anonymization_update_skips_non_demo_with_success(tmp_path: Path) -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    start = installer.index("configure_demo_anonymization(){")
    end = installer.index("\n}\n", start) + 3
    function = installer[start:end]
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    python = binary_directory / "python"
    python.write_text("#!/bin/sh\nprintf 'n\\n'\n", encoding="utf-8")
    python.chmod(0o755)
    migration = binary_directory / "kienzlefon-migration"
    migration.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    migration.chmod(0o755)
    script = f"""set -Eeuo pipefail
VENV={str(tmp_path)!r}
CONFIG_FILE={str(tmp_path / 'kienzlefon.toml')!r}
{function}
configure_demo_anonymization
"""

    result = subprocess.run(["bash", "-c", script], check=False)

    assert result.returncode == 0


def test_demo_anonymization_update_runs_for_demo(tmp_path: Path) -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    start = installer.index("configure_demo_anonymization(){")
    end = installer.index("\n}\n", start) + 3
    function = installer[start:end]
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    python = binary_directory / "python"
    python.write_text("#!/bin/sh\nprintf 'y\\n'\n", encoding="utf-8")
    python.chmod(0o755)
    arguments = tmp_path / "migration-arguments"
    migration = binary_directory / "kienzlefon-migration"
    migration.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {str(arguments)!r}\n",
        encoding="utf-8",
    )
    migration.chmod(0o755)
    script = f"""set -Eeuo pipefail
VENV={str(tmp_path)!r}
CONFIG_FILE={str(tmp_path / 'kienzlefon.toml')!r}
SOURCE_TARGET={str(tmp_path)!r}
ask_yes_no() {{ printf -v "$1" 'y'; }}
{function}
configure_demo_anonymization
"""

    result = subprocess.run(["bash", "-c", script], check=False)

    assert result.returncode == 0
    assert "--demo-anonymize\ntrue\n" in arguments.read_text(encoding="utf-8")


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


def test_prompt_workers_can_update_private_queue_digit_directory() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    web_installer = Path("kienzlefon-webinterface-installer.sh").read_text(
        encoding="utf-8"
    )
    assert 'queue_digits="${prompts%/*}/de_kienzlefon/digits"' in installer
    assert 'QUEUE_DIGITS_DIR="${PROMPTS_DIR%/*}/de_kienzlefon/digits"' in web_installer
    assert "${QUEUE_DIGITS_DIR}" in web_installer.split("ReadWritePaths=", 1)[1]


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


def test_music_on_hold_check_accepts_real_syntax_and_rejects_missing_module() -> None:
    installer = Path("kienzlefon-installer.sh").read_text(encoding="utf-8")
    start = installer.index("asterisk_supports_music_on_hold(){")
    end = installer.index("\n}\n", start) + 3
    function = installer[start:end]

    success = subprocess.run(
        [
            "bash", "-c",
            f"""asterisk() {{ printf '%s\\n' '[Syntax]' 'MusicOnHold(class)'; }}
{function}
asterisk_supports_music_on_hold
""",
        ],
        check=False,
    )
    missing = subprocess.run(
        [
            "bash", "-c",
            f"""asterisk() {{ printf '%s\\n' 'No application MusicOnHold registered.'; }}
{function}
asterisk_supports_music_on_hold
""",
        ],
        check=False,
    )

    assert success.returncode == 0
    assert missing.returncode != 0


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


@pytest.mark.parametrize('installed,mode,expected_prompts', [
    (True, 'musik', ['install:j', 'mode:2']),
    (True, 'klingelzeichen', ['install:j', 'mode:1']),
    (False, 'klingelzeichen', ['install:n']),
])
def test_music_installer_defaults_and_existing_choices(tmp_path, installed, mode, expected_prompts):
    source = Path('kienzlefon-installer.sh').read_text()
    start = source.index('configure_hold_music(){')
    end = source.index('\ninstall_hold_music(){', start)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'python').symlink_to(os.sys.executable)
    config = tmp_path / 'config.toml'
    config.write_text('[wartemusik]\ninstalliert = ' + str(installed).lower() + '\nmodus = "' + mode + '"\n')
    script = ('set -euo pipefail\n'
              'ask_yes_no(){ printf "install:%s\\n" "$3"; if [[ "$3" == j ]]; then printf -v "$1" y; else printf -v "$1" n; fi; }\n'
              'ask_value(){ printf "mode:%s\\n" "$3"; printf -v "$1" "%s" "$3"; }\n'
              + source[start:end] + '\nconfigure_hold_music\n')
    env = {**os.environ, 'VENV': str(tmp_path), 'CONFIG_FILE': str(config)}
    for _ in range(2):
        result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        prompts = [line for line in result.stdout.splitlines() if line.startswith(('install:', 'mode:'))]
        assert prompts == expected_prompts
        assert tomllib.loads(config.read_text())['wartemusik'] == {'installiert': installed, 'modus': mode}
