"""Optionale Google-Cloud-TTS-Engine (Chirp 3 HD)."""
import base64
import http.server
import json
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from kienzlefon.config import ConfigError, load_config
from kienzlefon.prompts import PromptGenerator
from kienzlefon.webadmin import (
    WebAdminError,
    _google_generator_available,
    _validate_save_request,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/google-tts/kienzlefon-google-tts-generate"


@pytest.fixture
def installed_google(app_config, tmp_path):
    generator = tmp_path / "google-generator"
    generator.write_text("#!/bin/sh\nexit 1\n")
    generator.chmod(0o755)
    settings = tmp_path / "google-tts.conf"
    settings.write_text("API_KEY=secret-one\nVOICE=de-DE-Chirp3-HD-Sulafat\nLANG=de-DE\nRATE=0.93\n")
    return replace(app_config, tts=replace(
        app_config.tts, engine="google", google_generator=generator, google_config=settings,
    ))


def test_google_engine_is_accepted_by_config(app_config):
    app_config.source.write_text(
        app_config.source.read_text().replace('engine = "kokoro"', 'engine = "google"')
    )
    config = load_config(app_config.source)
    assert config.tts.engine == "google"
    assert str(config.tts.google_generator).endswith("kienzlefon-google-tts-generate")
    assert str(config.tts.google_config) == "/etc/kienzlefon/google-tts.conf"


def test_unknown_engine_message_lists_google(app_config):
    app_config.source.write_text(
        app_config.source.read_text().replace('engine = "kokoro"', 'engine = "nope"')
    )
    with pytest.raises(ConfigError, match="google"):
        load_config(app_config.source)


@pytest.mark.parametrize("key", ["google_generator", "google_konfig"])
def test_relative_google_paths_rejected(app_config, key):
    text = app_config.source.read_text()
    text = re.sub(rf"^{key} = .*", f'{key} = "relative/path"', text, flags=re.M)
    if f"{key} = " not in text:
        text = text.replace("[tts]\n", f'[tts]\n{key} = "relative/path"\n', 1)
    app_config.source.write_text(text)
    with pytest.raises(ConfigError, match=key):
        load_config(app_config.source)


def test_google_command_uses_configured_file_without_exposing_key(installed_google, tmp_path):
    output = tmp_path / "ansage.wav"
    command = PromptGenerator(installed_google)._tts_command("Taste 6 ab 08:30 Uhr.", output)
    assert command[0] == str(installed_google.tts.google_generator)
    assert command[command.index("--config") + 1] == str(installed_google.tts.google_config)
    assert command[command.index("--text") + 1] == "Taste sechs ab acht Uhr dreißig."
    assert command[command.index("--output") + 1] == str(output)
    assert "secret-one" not in " ".join(command)


def test_missing_google_generator_or_config_never_falls_back(installed_google, tmp_path):
    installed_google.tts.google_config.unlink()
    with pytest.raises(RuntimeError, match="Konfiguration fehlt"):
        PromptGenerator(installed_google)._tts_command("Test", tmp_path / "a.wav")
    installed_google.tts.google_generator.unlink()
    with pytest.raises(RuntimeError, match="Google-TTS-Generator"):
        PromptGenerator(installed_google)._tts_command("Test", tmp_path / "a.wav")


def test_identity_follows_voice_but_not_api_key(installed_google):
    settings = installed_google.tts.google_config
    before = PromptGenerator(installed_google)._tts_identity()
    settings.write_text(settings.read_text().replace("secret-one", "secret-two"))
    assert PromptGenerator(installed_google)._tts_identity() == before
    settings.write_text(settings.read_text().replace("Sulafat", "Achernar"))
    assert PromptGenerator(installed_google)._tts_identity() != before


def test_web_accepts_google_only_when_configured(installed_google):
    config = installed_google
    job = {"config_hash": "a" * 64, "tts": {"engine": "google"}}
    assert _google_generator_available(config)
    assert _validate_save_request(job, config)["tts"]["engine"] == "google"
    config.tts.google_config.unlink()
    assert not _google_generator_available(config)
    with pytest.raises(WebAdminError, match="Google-TTS"):
        _validate_save_request(job, config)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
@pytest.mark.parametrize(("arguments", "rate"), [([], 0.93), (["--speaking-rate", "1.17"], 1.17)])
def test_generator_script_calls_api_and_writes_wav(tmp_path, arguments, rate):
    source = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(source)], check=True,
    )
    audio = base64.b64encode(source.read_bytes()).decode()
    seen = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["key"] = self.headers.get("X-Goog-Api-Key")
            seen["path"] = self.path
            payload = json.dumps({"audioContent": audio}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = tmp_path / "google.conf"
        settings.write_text(f"API_KEY=test-key\nENDPOINT=http://127.0.0.1:{server.server_port}\n")
        output = tmp_path / "out.wav"
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--config", str(settings),
             "--text", "Guten Tag", "--output", str(output), "--model-dir", "/x", "--speed", "1.0", *arguments],
            capture_output=True, text=True,
        )
    finally:
        server.shutdown()
    assert result.returncode == 0, result.stderr
    assert seen["path"] == "/v1/text:synthesize"
    assert seen["key"] == "test-key"
    assert seen["body"]["input"]["text"] == "Guten Tag"
    assert seen["body"]["voice"]["name"] == "de-DE-Chirp3-HD-Enceladus"
    assert seen["body"]["audioConfig"]["speakingRate"] == rate
    assert output.read_bytes()[:4] == b"RIFF"


def test_generator_script_refuses_missing_key_and_remote_http(tmp_path):
    settings = tmp_path / "google.conf"
    settings.write_text("VOICE=x\n")
    missing = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--config", str(settings),
         "--text", "x", "--output", str(tmp_path / "o.wav")], capture_output=True, text=True,
    )
    assert missing.returncode == 2 and "API_KEY" in missing.stderr
    settings.write_text("API_KEY=k\nENDPOINT=http://evil.example\n")
    remote = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--config", str(settings),
         "--text", "x", "--output", str(tmp_path / "o.wav")], capture_output=True, text=True,
    )
    assert remote.returncode != 0 and "Hostname" in remote.stderr


INSTALLER = Path(__file__).resolve().parents[1] / "kienzlefon-installer.sh"


def _installer_run(tmp_path, answers, *, existing_key=None, endpoint=None, custom_path=False):
    """Fuehrt die Google-Funktionen des Installers in einer Sandbox aus."""
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if not (bin_dir / "python").exists():
        (bin_dir / "python").symlink_to(sys.executable)
    source = tmp_path / "src" / "scripts" / "google-tts"
    source.mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, source / SCRIPT.name)
    default_config = tmp_path / "google-tts.conf"
    config = default_config
    if custom_path:
        config = tmp_path / "Google Stimmen.conf"
        (tmp_path / "kienzlefon.toml").write_text('[tts]\ngoogle_konfig = ' + json.dumps(str(config)))
    if existing_key:
        config.write_text(f'API_KEY = "{existing_key}"\nVOICE=old\nRATE=1.0\n')
        if endpoint:
            with config.open("a") as handle:
                handle.write(f"ENDPOINT={endpoint}\n")
    script = f"""
source "$1"
chown(){{ test "$1" = root:root && test -f "$2"; }}
VENV='{tmp_path}/venv'; SOURCE_TARGET='{tmp_path}/src'
GOOGLE_GENERATOR='{tmp_path}/gen'; GOOGLE_CONFIG='{default_config}'; CONFIG_FILE='{tmp_path}/kienzlefon.toml'
KZF_TTS_ENGINE=google
collect_google_tts_configuration
install_google_tts
"""
    result = subprocess.run(["bash", "-c", script, "test", INSTALLER], input=answers,
                            capture_output=True, text=True, timeout=10)
    return result, config


def test_installer_writes_private_config_and_validates_input(tmp_path):
    key = "AIzaSyTESTTESTTESTTESTTEST1234567"
    result, config = _installer_run(tmp_path, f"kurz\n{key}\n\n5\n0.9\n")
    assert result.returncode == 0, result.stderr
    assert config.read_text() == (
        f"API_KEY={key}\nVOICE=de-DE-Chirp3-HD-Enceladus\nLANG=de-DE\nRATE=0.9\n"
    )
    assert oct(config.stat().st_mode & 0o777) == "0o600"
    assert (tmp_path / "gen").stat().st_mode & 0o111
    assert "(schon gesetzt)" not in result.stdout
    assert key not in result.stdout + result.stderr


@pytest.mark.parametrize("custom_path", [False, True])
def test_installer_keeps_existing_key(tmp_path, custom_path):
    key = "AIzaSyKEEPKEEPKEEPKEEPKEEP1234567"
    endpoint = "eu-texttospeech.googleapis.com"
    result, config = _installer_run(
        tmp_path, "\nneueStimme\n1.1\n", existing_key=key, endpoint=endpoint, custom_path=custom_path,
    )
    assert result.returncode == 0, result.stderr
    assert config.read_text().startswith(f"API_KEY={key}\nVOICE=neueStimme\n")
    assert f"ENDPOINT={endpoint}\n" in config.read_text()
    assert "Google-API-Schlüssel (schon gesetzt)" in result.stdout
    assert key not in result.stdout + result.stderr
    if custom_path:
        assert not (tmp_path / "google-tts.conf").exists()


@pytest.mark.parametrize(("answers", "expected"), [
    ("", "Sulafat"),
    ("11", "Enceladus"),
    ("31\n0\n01", "Achernar"),
    ("30", "Zubenelgenubi"),
])
def test_numbered_voices_preserve_or_change_existing_selection(tmp_path, answers, expected):
    config = tmp_path / "google-tts.conf"
    config.write_text("API_KEY=test-key\nVOICE=de-DE-Chirp3-HD-Sulafat\n")
    result, _ = _installer_run(tmp_path, f"\n{answers}\n\n")
    assert result.returncode == 0, result.stderr
    assert f"VOICE=de-DE-Chirp3-HD-{expected}" in config.read_text().splitlines()
    entries = re.findall(r"^\s*(\d+)  (de-DE-Chirp3-HD-\w+)(.*)$", result.stdout, re.M)
    assert [int(number) for number, _, _ in entries] == list(range(1, 31))
    assert entries[10] == ("11", "de-DE-Chirp3-HD-Enceladus", " (Standard)")
    assert entries[25] == ("26", "de-DE-Chirp3-HD-Sulafat", "")


def test_saved_key_survives_interruption_and_can_be_replaced(tmp_path):
    first = "test-first-google-key-123456"
    second = "test-next-google-key-789012"
    interrupted, config = _installer_run(tmp_path, first + "\n")
    assert interrupted.returncode != 0
    assert config.read_text().splitlines()[0] == "API_KEY=" + first
    assert config.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "gen").exists()

    invalid, _ = _installer_run(tmp_path, "n\nkurz\n")
    assert invalid.returncode != 0
    assert config.read_text().splitlines()[0] == "API_KEY=" + first
    replaced, _ = _installer_run(tmp_path, f"n\n{second}\n\n\n")
    assert replaced.returncode == 0, replaced.stderr
    assert "(schon gesetzt)" in replaced.stdout
    assert config.read_text().splitlines()[0] == "API_KEY=" + second
    for run in (interrupted, invalid, replaced):
        assert first not in run.stdout + run.stderr and second not in run.stdout + run.stderr


def test_installer_adopts_saved_web_tempo(tmp_path):
    source = tmp_path / "kienzlefon.toml"
    source.write_text('[tts]\ngoogle_sprechtempo = "1.18"\n')
    result, config = _installer_run(tmp_path, "\n\n\n", existing_key="synthetic-key-already-configured")
    assert result.returncode == 0, result.stderr
    assert "RATE=1.18\n" in config.read_text()
    assert 'google_sprechtempo = ""' in source.read_text()
