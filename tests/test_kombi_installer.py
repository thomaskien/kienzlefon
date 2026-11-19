"""Exercise the combined installer with local packages and isolated system boundaries."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = "kienzlefon-installer.sh"
WEB = "kienzlefon-webinterface-installer.sh"
INVENTORY = Path("scripts/package-files.txt")
PHP = Path("webinterface/admin.php")
QWEN = "install-kienzlefon-qwen3-tts-v1.5.sh"
MARKER = b"\n<!-- lokaler Pakettest A -->\n"


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    work = tmp_path_factory.mktemp("Paket mit Leerzeichen")
    source = work / "Arbeitsbaum ohne Git"
    for name in (ROOT / INVENTORY).read_text().splitlines():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    with (source / PHP).open("ab") as handle:
        handle.write(MARKER)
    additions = {
        "kienzlefon/neu.py": "flag = True",
        "kienzlefon/modul/__init__.py": "",
        "kienzlefon/modul/neu.py": "wert = 7",
        "webinterface/neu.php": "<?php return 7;",
        "scripts/lokaler-helfer.sh": "exit 0",
        "config/neu.toml.example": "wert = 7",
    }
    excluded = [
        "config/sms-queue-web.example.json", "config/sms-queue-worker.example.json",
        ".git/config", ".env", ".venv/bin/activate", "build/kienzlefon/alt.py",
        "config/kienzlefon.toml", "config/middleware-connection.toml", "config/middleware-secret",
        "config/tls.key", "webinterface/.env", "webinterface/config.local.php",
        "webinterface/sessions/probe.php", "scripts/kokoro/.venv/bin/lokal.py",
        "kienzlefon/__pycache__/alt.pyc", "runtime/gespraech.wav",
    ]
    for name, content in {**dict.fromkeys(excluded, "privat"), **additions}.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (source / "kienzlefon/verweis.py").symlink_to(source / ".env")
    archive = work / "kienzlefon.tar.gz"
    subprocess.run(["/bin/bash", source / "scripts/pack.sh", "--output", archive],
                   cwd=work, check=True)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        assert members[0].name == "kienzlefon" and members[0].isdir()
        assert all(m.name.startswith("kienzlefon/") and m.isfile() for m in members[1:])
        names = {m.name.removeprefix("kienzlefon/") for m in members[1:]}
        required = set((ROOT / INVENTORY).read_text().splitlines())
        assert names == required | additions.keys()
        assert set(bundle.extractfile(f"kienzlefon/{INVENTORY}").read().decode().splitlines()) == names
    return archive


@pytest.fixture
def unpacked(package, tmp_path):
    with tarfile.open(package) as bundle:
        bundle.extractall(tmp_path, filter="data")
    return tmp_path / "kienzlefon"


def fax_base(tmp_path):
    (tmp_path / "fax.env").write_text("KFX_PHONE_QUEUE_ENABLED=y\n")
    etc = tmp_path / "asterisk"
    etc.mkdir()
    (etc / "queues-kfx.conf").write_text("[praxis]\n")
    (etc / "extensions-kfx-telefonie.conf").write_text("[kfx-phone-in]\n[kfx-phone-queue]\n")
    (etc / "pjsip-kfx-telefonie.conf").write_text("[kfx-phone-in-endpoint]\ntype=endpoint\n")
    (etc / "extensions.conf").write_text("[kfx_external_capacity]\n")
    for name in ("pjsip.conf", "features.conf", "queues.conf"):
        (etc / name).touch()


def run_main(source, tmp_path, overrides="", args=("--kombi",)):
    # A command reaching the network, APT, or a question during preflight fails the test.
    script = r"""
source "$1"
shift
KFX_ENV="$TEST_ROOT/fax.env"
ASTERISK_DIR="$TEST_ROOT/asterisk"
CONFIG_DIR="$TEST_ROOT/config"
CONFIG_FILE="$CONFIG_DIR/kienzlefon.toml"
INSTALL_ROOT="$TEST_ROOT/opt"
SOURCE_TARGET="$INSTALL_ROOT/src"
VENV="$INSTALL_ROOT/venv"
require_root(){ :; }
unexpected(){ echo "UNERWARTET: $*" >&2; exit 99; }
download(){ unexpected download "$@"; }
curl(){ unexpected curl "$@"; }
ask_yes_no(){ unexpected Frage "$@"; }
install_packages(){ unexpected APT; }
""" + overrides + '\nmain "$@"\n'
    return subprocess.run(["bash", "-c", script, "test", source / INSTALLER, *args],
                          env={**os.environ, "TEST_ROOT": str(tmp_path)},
                          cwd=tmp_path, capture_output=True, input="", text=True)


@pytest.mark.parametrize(("file", "contents", "message"), [
    ("fax.env", None, "Kienzlefax-Grundinstallation"),
    ("fax.env", "KFX_PHONE_QUEUE_ENABLED=n\n", "nicht aktiviert"),
    ("asterisk/queues-kfx.conf", None, "queues-kfx.conf"),
    ("asterisk/queues-kfx.conf", "[andere]\n", "[praxis]"),
    ("asterisk/extensions-kfx-telefonie.conf", None, "Telefoniedialplan"),
    ("asterisk/extensions-kfx-telefonie.conf", "[kfx-phone-queue]\n", "[kfx-phone-in]"),
    ("asterisk/pjsip-kfx-telefonie.conf", "", "PJSIP-Konfiguration"),
    ("asterisk/extensions.conf", "[default]\n", "Kapazitaetsguard"),
    ("asterisk/pjsip.conf", None, "pjsip.conf"),
])
def test_missing_fax_prerequisite_aborts_before_apt_or_download(tmp_path, file, contents, message):
    fax_base(tmp_path)
    path = tmp_path / file
    if contents is None:
        path.unlink()
    else:
        path.write_text(contents)
    result = run_main(ROOT, tmp_path)
    assert result.returncode == 1 and message in result.stderr, result.stderr
    assert "UNERWARTET" not in result.stderr


@pytest.mark.parametrize("missing", [
    INVENTORY, "pyproject.toml", PHP, WEB, "config/kienzlefon.toml.example", "kienzlefon/worker.py",
    "kienzlefon/neu.py", "kienzlefon/control_api.py", "kienzlefon/delivery.py",
    "kienzlefon/ai_import.py", "scripts/google-tts/kienzlefon-google-tts-generate",
    "scripts/kokoro/python_manifest.json", QWEN,
    "johannes-plachetka-warteschlange.wav",
])
def test_incomplete_package_stops_before_system_changes(tmp_path, unpacked, missing):
    (unpacked / missing).unlink()
    result = run_main(unpacked, tmp_path)
    assert result.returncode == 1 and str(missing) in result.stderr, result.stderr
    assert "UNERWARTET" not in result.stderr


@pytest.mark.parametrize(("update", "t2med", "web_status"), [
    (False, False, 0), (True, False, 0), (False, True, 0), (True, True, 0),
    (False, False, 17), (True, True, 23),
])
def test_package_reaches_webinstaller_and_propagates_status(
    tmp_path, unpacked, update, t2med, web_status,
):
    fax_base(tmp_path)
    # Both supported locations of the capacity context must work.
    if update:
        (tmp_path / "asterisk/extensions.conf").write_text("[default]\n")
        with (tmp_path / "asterisk/extensions-kfx-telefonie.conf").open("a") as plan:
            plan.write("[kfx_external_capacity]\n")
    config = tmp_path / "config/kienzlefon.toml"
    config.parent.mkdir()
    if update:
        config.write_text("[middleware]\naktiv = true\n")
        previous = tmp_path / "opt/src" / PHP
        previous.parent.mkdir(parents=True)
        shutil.copy2(unpacked / PHP, previous)
        old_stat = previous.stat()
        previous.write_bytes(previous.read_bytes().replace(MARKER, MARKER.replace(b"A", b"B")))
        os.utime(previous, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    commands = tmp_path / "opt/venv/bin"
    commands.mkdir(parents=True)
    # Simulate the virtualenv's pip, config CLI and system integrations.
    for name in ["python", "kienzlefon-config", "kienzlefon-transfer-setup", "kienzlefon-queue-setup",
                 "kienzlefon-ansagen", "kienzlefon-migration"]:
        binary = commands / name
        binary.write_text('#!/bin/sh\n[ "$1" != -c ] || echo y\n')
        binary.chmod(0o755)
    middleware = commands / "kienzlefon-middleware"
    middleware.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_ROOT/ami.calls"\n')
    middleware.chmod(0o755)
    overrides = """
install_packages(){ :; }
ln(){ :; }
collect_configuration(){ echo "$EXISTING_INSTALL" > "$TEST_ROOT/update"; }
"""
    for name in ("configure_hold_music", "collect_regeneration_choice", "prepare_directories",
                 "install_systemd_unit", "install_admission_listener_unit", "install_kokoro_tts",
                 "install_models_and_prompts", "install_hold_music", "configure_asterisk", "start_and_verify"):
        overrides += f"{name}(){{ :; }}\n"
    # Run the unmodified, packaged web installer's main in its own shell.
    # Simulate its host services and redirect the real install(1) to test files.
    probe = tmp_path / "web-probe.sh"
    probe.write_text(r'''set -eu
[[ "$2" == --from-main-installer && $# == 2 ]]
source "$1"
shift
VENV="$TEST_ROOT/opt/venv"
CONFIG_FILE="$TEST_ROOT/config/kienzlefon.toml"
PHP_FILE="$TEST_ROOT/installed.php"
DEFAULTS_FILE="$TEST_ROOT/defaults.toml"
check_prerequisites(){ :; }
choose_server(){ SERVER_MODE=standalone; }
choose_wireguard(){ TLS_ENABLED=false; PASSWORDLESS=false; LISTEN_IP=127.0.0.1; }
getent(){ :; }
install_python_commands(){ :; }
configure_password(){ :; }
read_paths(){ :; }
write_web_config(){ :; }
install_runtime_layout(){ :; }
install(){ command install "${@:5}"; }
install_worker_units(){ return "$WEB_STATUS"; }
generate_certificate(){ :; }
systemctl(){ :; }
install_standalone(){ :; }
main "$@" <<< ""
''')
    overrides += r'''
bash(){
  if [[ "$1" == "$SOURCE_TARGET/kienzlefon-webinterface-installer.sh" ]]; then
    command bash "$TEST_ROOT/web-probe.sh" "$@"
  else
    command bash "$@"
  fi
}
''' + f"export WEB_STATUS={web_status}\n"
    flags = ("--kombi", "--mit-t2med") if t2med else ("--kombi",)
    result = run_main(unpacked, tmp_path, overrides, flags)
    assert result.returncode == web_status, result.stderr
    assert ("ist installiert" in result.stdout) == (web_status == 0)
    assert (tmp_path / "update").read_text().strip() == ("y" if update else "n")
    assert (tmp_path / "installed.php").read_bytes() == (ROOT / PHP).read_bytes() + MARKER
    assert (tmp_path / "defaults.toml").read_bytes() == (unpacked / "config/kienzlefon.toml.example").read_bytes()
    actions = ["configure", "install"] if t2med else ["install"]
    assert (tmp_path / "ami.calls").read_text().splitlines() == [
        f"{action} --config {config} --kombi" for action in actions
    ]


@pytest.mark.parametrize("modified", [False, True])
def test_kombi_qwen_uses_only_pinned_package_file(tmp_path, unpacked, modified):
    helper = unpacked / QWEN
    pinned = hashlib.sha256(helper.read_bytes()).hexdigest()
    assert f'QWEN_INSTALLER_SHA256="{pinned}"' in (unpacked / INSTALLER).read_text()
    # Exercise verification and execution with a harmless local installer.
    helper.write_text("""#!/bin/sh
set -eu
[ "$#" = 1 ] && [ "$1" = --offline-only ] || exit 98
printf '#!/bin/sh\\n# kienzlefon-worker.service\\nexit 0\\n' > "$QWEN_GENERATOR"
chmod +x "$QWEN_GENERATOR"
""")
    test_checksum = hashlib.sha256(helper.read_bytes()).hexdigest()
    if modified:
        with helper.open("a") as handle:
            handle.write("\n# geaendert\n")
    script = r'''
source "$1"
SOURCE_TARGET="$2"
KOMBI=y
KZF_INSTALL_QWEN=y
QWEN_INSTALLER_SHA256="$3"
export QWEN_GENERATOR="$TMPDIR/generator"
download(){ exit 99; }
install_qwen_tts
'''
    result = subprocess.run(["bash", "-c", script, "test", unpacked / INSTALLER, unpacked, test_checksum],
                            env={**os.environ, "TMPDIR": str(tmp_path)}, text=True, capture_output=True)
    if modified:
        assert result.returncode == 1 and "SHA-256-Pruefsumme" in result.stderr
    else:
        assert result.returncode == 0 and "verifiziert" in result.stdout
    assert (tmp_path / "generator").exists() is (not modified)
    assert helper.exists()
