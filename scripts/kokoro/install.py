"""Install the isolated CPU generator; never change running TTS services."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
RUNTIME = SOURCE.parent.parent / "kienzlefon" / "kokoro.py"
INSTALL_ROOT = Path("/opt/kienzlefon/kokoro")
MODEL_FILES = ("config.json", "model.pth", "voices/thorsten.pt")


def run(command):
    subprocess.run([str(value) for value in command], check=True)


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_directory(path):
    if not path.is_absolute() or path.resolve() != path:
        raise RuntimeError(f"Unsicheres Kokoro-Verzeichnis: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o755)
    path.chmod(0o755)


def prepare_models(directory, manifest, download=urllib.request.urlopen):
    safe_directory(directory)
    for name in MODEL_FILES:
        target = directory / name
        safe_directory(target.parent)
        if target.is_symlink():
            raise RuntimeError("Unsichere Kokoro-Modelldatei")
        expected = manifest["files"][name]["sha256"]
        if target.exists():
            if checksum(target) != expected:
                raise RuntimeError(f"Vorhandenes Kokoro-Modell hat falsche Pruefsumme: {name}")
            target.chmod(0o644)
            continue
        url = f"https://huggingface.co/{manifest['repo']}/resolve/{manifest['revision']}/{name}"
        fd, filename = tempfile.mkstemp(prefix=".download-", dir=target.parent)
        staged = Path(filename)
        try:
            with os.fdopen(fd, "wb") as output, download(url, timeout=120) as response:
                shutil.copyfileobj(response, output)
            if checksum(staged) != expected:
                raise RuntimeError(f"Kokoro-Download hat falsche Pruefsumme: {name}")
            staged.chmod(0o644)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)


def choose_python():
    for candidate in ("python3.12", "python3.11", "python3"):
        executable = shutil.which(candidate)
        if executable and subprocess.run(
            [executable, "-c", "import sys; sys.exit(not ((3,11) <= sys.version_info[:2] < (3,13)))"],
            check=False,
        ).returncode == 0:
            return executable
    raise RuntimeError("Kokoro benoetigt Python 3.11 oder 3.12 samt venv-Paket")


def install(config_path):
    if os.geteuid() != 0:
        raise RuntimeError("Kokoro-Installation benoetigt root")
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise RuntimeError("Das Kokoro-CPU-Paket ist fuer Linux x86_64 vorbereitet")
    with config_path.open("rb") as stream:
        tts = tomllib.load(stream)["tts"]
    generator = Path(tts["kokoro_generator"])
    model_dir = Path(tts["kokoro_modellverzeichnis"])
    if not generator.is_absolute() or generator.is_symlink():
        raise RuntimeError("Unsicherer Kokoro-Generatorpfad")
    safe_directory(generator.parent)
    requirements = SOURCE / "requirements-cpu.lock.txt"
    manifest_path = SOURCE / "model_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    identity = hashlib.sha256(
        RUNTIME.read_bytes() + requirements.read_bytes() + manifest_path.read_bytes()
    ).hexdigest()[:16]
    # Content-specific paths keep an earlier working environment intact on failure.
    destination = INSTALL_ROOT / f"2.4.1-{identity}"
    safe_directory(destination)
    environment = destination / "venv"
    if environment.is_symlink():
        raise RuntimeError("Unsichere Kokoro-Python-Umgebung")
    python = environment / "bin/python"
    if not python.exists():
        run([choose_python(), "-m", "venv", environment])
    marker = destination / ".dependencies-ready"
    if not marker.exists():
        run([python, "-m", "pip", "install", "-r", requirements,
             "--extra-index-url", "https://download.pytorch.org/whl/cpu"])
        run([python, "-m", "pip", "check"])
        marker.write_text(identity + "\n")
    else:
        run([python, "-m", "pip", "check"])
    prepare_models(model_dir, manifest)
    program = destination / "generate.py"
    program.write_bytes(RUNTIME.read_bytes())
    (destination / "model_manifest.json").write_bytes(manifest_path.read_bytes())
    for path in [destination, *destination.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    with tempfile.TemporaryDirectory(prefix="kienzlefon-kokoro-test-") as temp:
        run([python, program, "--model-dir", model_dir, "--speed", tts.get("kokoro_speed", 1.0),
             "--text", "Kienzlefon ist bereit.", "--output", Path(temp) / "test.wav"])
    wrapper = (
        "#!/bin/sh\n# Kienzlefon Kokoro-Thorsten 2.4.1; " + identity + "\n"
        "export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false\n"
        f"exec {shlex.quote(str(python))} {shlex.quote(str(program))} \"$@\"\n"
    )
    fd, filename = tempfile.mkstemp(prefix=".kokoro-", dir=generator.parent)
    staged = Path(filename)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(wrapper)
        staged.chmod(0o755)
        os.replace(staged, generator)
    finally:
        staged.unlink(missing_ok=True)
    print("Kokoro-Thorsten CPU: Modellpruefsummen und lokale Testansage erfolgreich")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kokoro-Thorsten fuer Kienzlefon 2.4.1 installieren")
    parser.add_argument("--config", required=True, type=Path)
    arguments = parser.parse_args()
    install(arguments.config)
