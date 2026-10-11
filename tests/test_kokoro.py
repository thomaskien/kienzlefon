from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tarfile
import tomllib
import wave
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from kienzlefon.config import ConfigError, load_config
from kienzlefon.kokoro import MODEL_FILES, MODEL_REVISION, phoneme_chunks, verify_model
from kienzlefon.migration import migrate_config
from kienzlefon.prompts import PromptGenerator
from kienzlefon.webadmin import (
    WebAdminError,
    _kokoro_generator_available,
    _validate_save_request,
)


@pytest.fixture
def installed_kokoro(app_config):
    generator = app_config.tts.kokoro_generator
    generator.write_text("#!/bin/sh\n# synthetic test generator\nexit 1\n")
    generator.chmod(0o755)
    for name in MODEL_FILES:
        path = app_config.tts.kokoro_model_directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic model")
    return app_config


def test_default_engine_without_explicit_value(app_config):
    text = app_config.source.read_text().replace('engine = "kokoro"\n', "")
    app_config.source.write_text(text)
    assert load_config(app_config.source).tts.engine == "kokoro"


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf"])
def test_invalid_kokoro_speed_rejected(app_config, value):
    app_config.source.write_text(
        app_config.source.read_text().replace("kokoro_speed = 1.0", f"kokoro_speed = {value}")
    )
    with pytest.raises(ConfigError, match="kokoro_speed"):
        load_config(app_config.source)


@pytest.mark.parametrize("key", ["kokoro_generator", "kokoro_modellverzeichnis"])
def test_relative_kokoro_paths_rejected(app_config, key):
    import re

    app_config.source.write_text(re.sub(
        rf"^{key} = .*", f'{key} = "relative/path"', app_config.source.read_text(), flags=re.M
    ))
    with pytest.raises(ConfigError, match=key):
        load_config(app_config.source)


@pytest.mark.parametrize("engine", ["piper", "qwen"])
def test_migration_preserves_explicit_old_engine(app_config, engine):
    lines = app_config.source.read_text().replace('engine = "kokoro"', f'engine = "{engine}"')
    lines = "\n".join(line for line in lines.splitlines() if not line.startswith("kokoro_"))
    app_config.source.write_text(lines + "\n")
    assert migrate_config(app_config.source, Path("config/kienzlefon.toml.example"))
    migrated = load_config(app_config.source)
    assert migrated.tts.engine == engine
    assert migrated.tts.kokoro_speed == 1.0
    assert not migrate_config(app_config.source, Path("config/kienzlefon.toml.example"))


def test_kokoro_routing_and_cache(installed_kokoro, tmp_path):
    config = installed_kokoro
    generator = PromptGenerator(config)
    output = tmp_path / "test.wav"
    assert generator._tts_command("Testansage", output) == [
        str(config.tts.kokoro_generator), "--text", "Testansage", "--output", str(output),
        "--model-dir", str(config.tts.kokoro_model_directory), "--speed", "1.0",
    ]
    original = generator._digest("greeting_open", "Testansage")
    assert PromptGenerator(config)._digest("greeting_open", "Testansage") == original
    for changes in ({"kokoro_speed": 1.2}, {"engine": "piper"}, {"engine": "qwen"}):
        modified = PromptGenerator(replace(config, tts=replace(config.tts, **changes)))
        assert modified._digest("greeting_open", "Testansage") != original
        assert modified._tts_identity() != generator._tts_identity()
    # Inactive engine settings do not force unnecessary Kokoro regeneration.
    changed_piper = replace(config, tts=replace(config.tts, length_scale=1.7))
    assert PromptGenerator(changed_piper)._digest("greeting_open", "Testansage") == original
    config.tts.kokoro_generator.write_text("#!/bin/sh\n# updated generator\nexit 1\n")
    assert PromptGenerator(config)._digest("greeting_open", "Testansage") != original


def test_unchanged_kokoro_is_not_synthesized(installed_kokoro, monkeypatch):
    generator = PromptGenerator(installed_kokoro)
    generator.manifest_path.parent.mkdir(parents=True)
    generator.manifest_path.write_text(json.dumps({
        "tts_identity": generator._tts_identity(),
        "prompts": {"greeting_open": {"sha256": generator._digest("greeting_open", "Hallo")}},
    }))
    monkeypatch.setattr("kienzlefon.prompts.rendered_prompts", lambda _: {"greeting_open": "Hallo"})
    monkeypatch.setattr(generator, "_outputs_exist", lambda _: True)
    monkeypatch.setattr(generator, "_run", lambda *_: pytest.fail("Keine Synthese erwartet"))
    assert generator.generate() == (0, 1)


def test_piper_update_replaces_existing_audio_without_force(installed_kokoro, monkeypatch):
    config = installed_kokoro
    old = PromptGenerator(replace(config, tts=replace(config.tts, engine="piper")))
    new = PromptGenerator(config)
    rendered = {"greeting_open": "Guten Tag.", "greeting_closed": "Guten Abend."}
    old.manifest_path.parent.mkdir(parents=True)
    config.paths.prompts.mkdir(parents=True)
    old.manifest_path.write_text(json.dumps({
        "tts_identity": old._tts_identity(),
        "prompts": {
            name: {"sha256": old._digest(name, text), "text": text}
            for name, text in rendered.items()
        },
    }))
    for name in rendered:
        (config.paths.prompt_masters / f"{name}.wav").write_bytes(b"old Piper master")
        for suffix in ("sln16", "g722", "alaw", "ulaw"):
            (config.paths.prompts / f"{name}.{suffix}").write_bytes(b"old Piper audio")
    monkeypatch.setattr("kienzlefon.prompts.rendered_prompts", lambda _: rendered)
    generated = []

    def synthesize(name, text, staging):
        generated.append(name)
        assert new._tts_command(text, staging / "source.wav")[0] == str(config.tts.kokoro_generator)
        for folder, extensions in (("masters", ("wav",)), ("prompts", ("sln16", "g722", "alaw", "ulaw"))):
            (staging / folder).mkdir(exist_ok=True)
            for extension in extensions:
                (staging / folder / f"{name}.{extension}").write_bytes(b"new Kokoro audio")

    monkeypatch.setattr(new, "_generate_one", synthesize)
    assert new.generate(force=False) == (2, 0)
    assert set(generated) == set(rendered)
    for name in rendered:
        assert (config.paths.prompt_masters / f"{name}.wav").read_bytes() == b"new Kokoro audio"
        for suffix in ("sln16", "g722", "alaw", "ulaw"):
            assert (config.paths.prompts / f"{name}.{suffix}").read_bytes() == b"new Kokoro audio"
    assert json.loads(new.manifest_path.read_text())["tts_identity"] == new._tts_identity()
    assert new.generate(force=False) == (0, 2)
    assert len(generated) == 2


def test_missing_kokoro_never_falls_back(app_config, tmp_path):
    with pytest.raises(RuntimeError, match="Kokoro-Thorsten ist nicht installiert"):
        PromptGenerator(app_config)._tts_command("Test", tmp_path / "test.wav")


def test_web_rejects_missing_model_and_accepts_installed_kokoro(installed_kokoro):
    config = installed_kokoro
    job = {"config_hash": "a" * 64, "tts": {"engine": "kokoro"}}
    assert _kokoro_generator_available(config)
    assert _validate_save_request(job, config)["tts"]["engine"] == "kokoro"
    (config.tts.kokoro_model_directory / "model.pth").unlink()
    assert not _kokoro_generator_available(config)
    with pytest.raises(WebAdminError, match="Kokoro-Thorsten"):
        _validate_save_request(job, config)
    with pytest.raises(RuntimeError, match="Modell fehlt"):
        PromptGenerator(config)._tts_command("Test", Path("unused.wav"))
    assert _validate_save_request({**job, "tts": {"engine": "piper"}}, config)


def test_long_announcements_keep_every_word():
    text = " ".join(f"Wort{index}" for index in range(600)) + ". Ende."
    chunks = list(phoneme_chunks(text, lambda value: (value, None)))
    assert len(chunks) > 2
    assert all(len(chunk) <= 510 for chunk in chunks)
    assert " ".join(chunks) == text
    assert list(phoneme_chunks("ʏ", lambda _: ("ʏ", None))) == ["y"]
    with pytest.raises(RuntimeError, match="Phonemlimit"):
        list(phoneme_chunks("x" * 511, lambda text: (text, None)))


@pytest.fixture
def installer_module():
    spec = importlib.util.spec_from_file_location("kokoro_install", "scripts/kokoro/install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_selection_reuses_supported_system_python(installer_module, monkeypatch):
    module = installer_module
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(module, "python_usable", lambda path: path.endswith("python3.11"))
    monkeypatch.setattr(module, "prepare_python", lambda _: pytest.fail("Kein Download erwartet"))
    assert module.choose_python() == "/usr/bin/python3.11"


def test_python_selection_bootstraps_when_only_debian_13_python_exists(installer_module, monkeypatch):
    module = installer_module
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None)
    monkeypatch.setattr(module, "python_usable", lambda _: False)
    prepared = []

    def prepare(manifest):
        prepared.append(manifest)
        return "/opt/kienzlefon/kokoro/python/managed/bin/python3.12"

    monkeypatch.setattr(module, "prepare_python", prepare)
    assert module.choose_python().endswith("/managed/bin/python3.12")
    assert prepared[0]["version"] == "3.12.15"
    assert len(prepared[0]["sha256"]) == 64


@pytest.mark.parametrize("version, usable", [("3.11.10", True), ("3.12.15", True), ("3.13.5", False)])
def test_python_probe_checks_supported_versions_and_venv(installer_module, monkeypatch, version, usable):
    original_run = subprocess.run

    def probe(command, **kwargs):
        # Execute the real probe using the local interpreter, simulating the
        # candidate's version while keeping ssl/venv/ensurepip imports real.
        prefix = "import ssl, venv, ensurepip, sys; "
        prefix += f"sys.version_info = {tuple(map(int, version.split('.')))!r}; "
        prefix += f"sys.version = {version!r}; "
        return original_run([sys.executable, "-I", "-c", prefix + command[3], command[4]], **kwargs)

    monkeypatch.setattr(installer_module.subprocess, "run", probe)
    assert installer_module.python_usable("candidate") is usable
    assert not installer_module.python_usable("candidate", "0.0.0")


def python_archive(name="python/bin/python3.12", *, link=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        member = tarfile.TarInfo(name)
        member.mode = 0o755
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = link
            bundle.addfile(member)
        else:
            content = b"synthetic interpreter"
            member.size = len(content)
            bundle.addfile(member, io.BytesIO(content))
    return output.getvalue()


def python_manifest(content):
    return {"version": "3.12.15", "url": "https://example.invalid/python.tar.gz",
            "sha256": hashlib.sha256(content).hexdigest()}


def test_managed_python_is_atomic_reusable_and_accessible(installer_module, monkeypatch, tmp_path):
    module = installer_module
    monkeypatch.setattr(module, "INSTALL_ROOT", tmp_path / "kokoro")
    monkeypatch.setattr(module, "python_usable", lambda path, version: (
        path.read_bytes() == b"synthetic interpreter" and version == "3.12.15"
    ))
    content = python_archive()
    manifest = python_manifest(content)
    old_umask = os.umask(0o077)
    try:
        executable = Path(module.prepare_python(manifest, lambda *_a, **_k: io.BytesIO(content)))
    finally:
        os.umask(old_umask)
    assert executable.stat().st_mode & 0o777 == 0o755
    for parent in (executable.parent, executable.parent.parent, executable.parent.parent.parent,
                   module.INSTALL_ROOT):
        assert parent.stat().st_mode & 0o777 == 0o755
    assert module.prepare_python(manifest, lambda *_a, **_k: pytest.fail("Erneuter Download")) == str(executable)
    assert not list((module.INSTALL_ROOT / "python").glob(".python-*"))


@pytest.mark.parametrize("failure", ["checksum", "runtime", "download"])
def test_managed_python_failure_is_retryable(installer_module, monkeypatch, tmp_path, failure):
    module = installer_module
    monkeypatch.setattr(module, "INSTALL_ROOT", tmp_path / "kokoro")
    monkeypatch.setattr(module, "python_usable", lambda *_: failure != "runtime")
    content = python_archive()
    manifest = python_manifest(content)

    def download(*_args, **_kwargs):
        if failure == "download":
            raise OSError("Download unterbrochen")
        return io.BytesIO(b"bad" if failure == "checksum" else content)

    with pytest.raises((RuntimeError, OSError)):
        module.prepare_python(manifest, download)
    assert not list((module.INSTALL_ROOT / "python").iterdir())
    monkeypatch.setattr(module, "python_usable", lambda *_: True)
    assert Path(module.prepare_python(manifest, lambda *_a, **_k: io.BytesIO(content))).is_file()


@pytest.mark.parametrize("name, link", [
    ("../outside", None), ("python/../../outside", None),
    ("python/bin/python3.12", "../../../outside"),
])
def test_managed_python_rejects_escaping_archives(installer_module, monkeypatch, tmp_path, name, link):
    module = installer_module
    monkeypatch.setattr(module, "INSTALL_ROOT", tmp_path / "kokoro")
    monkeypatch.setattr(module, "python_usable", lambda *_: pytest.fail("Archiv darf nicht starten"))
    content = python_archive(name, link=link)
    with pytest.raises((RuntimeError, tarfile.FilterError)):
        module.prepare_python(python_manifest(content), lambda *_a, **_k: io.BytesIO(content))
    assert not list((module.INSTALL_ROOT / "python").iterdir())


def test_managed_python_rejects_symlink_destination(installer_module, monkeypatch, tmp_path):
    module = installer_module
    monkeypatch.setattr(module, "INSTALL_ROOT", tmp_path / "kokoro")
    manifest = python_manifest(python_archive())
    root = module.INSTALL_ROOT / "python"
    root.mkdir(parents=True)
    destination = root / f"cpython-{manifest['version']}-{manifest['sha256'][:16]}"
    destination.symlink_to(tmp_path / "outside")
    with pytest.raises(RuntimeError, match="Unsicheres"):
        module.prepare_python(manifest, lambda *_a, **_k: pytest.fail("Kein Download erwartet"))


def model_manifest():
    return {"repo": "Thorsten-Voice/Kokoro", "revision": MODEL_REVISION, "files": {
        name: {"sha256": hashlib.sha256(name.encode()).hexdigest()} for name in MODEL_FILES
    }}


def test_pinned_download_reuse_and_corruption(installer_module, tmp_path):
    manifest = model_manifest()
    calls = []

    def download(url, timeout):
        calls.append(url)
        assert MODEL_REVISION in url
        return io.BytesIO(url.split(MODEL_REVISION + "/")[1].encode())

    models = tmp_path / "models"
    installer_module.prepare_models(models, manifest, download)
    assert len(calls) == 3
    verify_model(models, manifest)
    installer_module.prepare_models(models, manifest, lambda *_: pytest.fail("Redownload"))
    (models / "model.pth").write_bytes(b"corrupted")
    with pytest.raises(RuntimeError, match="Pruefsumme"):
        verify_model(models, manifest)
    with pytest.raises(RuntimeError, match="Pruefsumme"):
        installer_module.prepare_models(models, manifest, download)
    assert (models / "model.pth").read_bytes() == b"corrupted"


def test_bad_download_never_published(installer_module, tmp_path):
    with pytest.raises(RuntimeError, match="Pruefsumme"):
        installer_module.prepare_models(
            tmp_path / "models", model_manifest(), lambda *_args, **_kwargs: io.BytesIO(b"bad")
        )
    assert not list((tmp_path / "models").glob("*"))


@pytest.mark.parametrize("success", [False, True])
def test_installer_publishes_only_after_successful_synthesis(
    installer_module, installed_kokoro, monkeypatch, tmp_path, success
):
    module = installer_module
    config = installed_kokoro
    before = config.tts.kokoro_generator.read_bytes()
    monkeypatch.setattr(module, "INSTALL_ROOT", tmp_path / "install")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(module, "choose_python", lambda: sys.executable)
    monkeypatch.setattr(module, "prepare_models", lambda *_: None)
    commands = []

    def run(command):
        commands.append([str(item) for item in command])
        if "venv" in command:
            directory = command[-1] / "bin"
            directory.mkdir(parents=True)
            (directory / "python").touch()
        if "--text" in command and not success:
            raise RuntimeError("synthetic inference failure")

    monkeypatch.setattr(module, "run", run)
    if success:
        module.install(config.source)
        assert config.tts.kokoro_generator.read_bytes() != before
        assert os.access(config.tts.kokoro_generator, os.X_OK)
        assert "HF_HUB_OFFLINE=1" in config.tts.kokoro_generator.read_text()
        assert any("https://download.pytorch.org/whl/cpu" in command for command in commands)
        assert any("check" in command for command in commands)
    else:
        with pytest.raises(RuntimeError, match="inference failure"):
            module.install(config.source)
        assert config.tts.kokoro_generator.read_bytes() == before


@pytest.mark.parametrize("existing, choice, expected", [
    (None, "", "kokoro"), ("piper", "", "kokoro"),
    ("piper", "2", "piper"), ("qwen", "", "qwen"), ("kokoro", "", "kokoro"),
])
def test_interactive_installer_tts_choices(tmp_path, existing, choice, expected):
    source = Path("kienzlefon-installer.sh").read_text()
    start = source.index("collect_tts_configuration(){")
    end = source.index("\n}\n", start) + 3
    config = tmp_path / "config.toml"
    if existing:
        config.write_text(f'[tts]\nengine = "{existing}"\n')
    qwen = tmp_path / "qwen"
    qwen.write_text("#!/bin/sh\n# kienzlefon-worker.service\n")
    qwen.chmod(0o755)
    script = "\n".join([
        "set -euo pipefail", source[start:end],
        f"CONFIG_FILE={shlex.quote(str(config))}",
        f"VENV={shlex.quote(str(Path(sys.executable).parent.parent))}",
        f"QWEN_GENERATOR={shlex.quote(str(qwen))}",
        "KZF_INSTALL_QWEN=n",
        'ask_yes_no(){ printf -v "$1" n; }',
        'ask_value(){ local answer="$3"; if [[ "$1" == engine_choice && -n "$CHOICE" ]]; then answer="$CHOICE"; fi; printf -v "$1" %s "$answer"; }',
        "qwen_choice_from_voice(){ printf 1; }",
        "qwen_voice_from_choice(){ printf ryan; }",
        "qwen_generator_knows_worker(){ return 0; }",
        "collect_tts_configuration", 'printf "RESULT=%s\\n" "$KZF_TTS_ENGINE"',
    ])
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={**os.environ, "CHOICE": choice}, check=True,
    )
    assert f"RESULT={expected}" in result.stdout


def test_release_versions_agree():
    from kienzlefon import __version__

    assert __version__ == "2.5.1"
    assert tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"] == __version__


@pytest.mark.parametrize("fail", [False, True])
def test_synthesis_writes_pcm_atomically_on_cpu(monkeypatch, tmp_path, fail):
    from kienzlefon.kokoro import synthesize

    models = tmp_path / "models"
    for name in MODEL_FILES:
        path = models / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    output = tmp_path / "output.wav"
    output.write_bytes(b"previous audio")
    calls = []

    class Model:
        def __init__(self, **kwargs):
            assert kwargs["model"] == str(models / "model.pth")
            assert kwargs["config"] == str(models / "config.json")

        def to(self, device):
            assert device == "cpu"
            return self

        def eval(self):
            return self

    class Audio:
        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self

        def __mul__(self, factor):
            assert factor == 32767
            return self

        def astype(self, dtype):
            assert dtype == "<i2"
            return self

        def tobytes(self):
            return b"\x00\x01" * 2400

    class Pipeline:
        def __init__(self, **kwargs):
            assert kwargs["lang_code"] == "d"
            self.g2p = lambda text: (text, None)

        def generate_from_tokens(self, phonemes, *, voice, speed):
            assert voice == "thorsten-test-tensor"
            assert speed == 1.0
            assert "ʏ" not in phonemes
            calls.append(phonemes)
            yield SimpleNamespace(audio=Audio())
            if fail:
                raise RuntimeError("synthetic failure after first chunk")

    def load_voice(path, **kwargs):
        assert path == models / "voices/thorsten.pt"
        assert kwargs == {"map_location": "cpu", "weights_only": True}
        return "thorsten-test-tensor"

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        set_num_threads=lambda _: None, set_num_interop_threads=lambda _: None,
        manual_seed=lambda _: None, inference_mode=nullcontext, load=load_voice,
    ))
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(
        clip=lambda audio, *_: audio, isfinite=lambda _: SimpleNamespace(all=lambda: True),
    ))
    monkeypatch.setitem(sys.modules, "kokoro", SimpleNamespace(KModel=Model, KPipeline=Pipeline))
    monkeypatch.setitem(sys.modules, "loguru", SimpleNamespace(logger=SimpleNamespace(disable=lambda _: None)))
    monkeypatch.setitem(sys.modules, "misaki.de", SimpleNamespace(normalize_text_de=lambda text: text))
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "TOKENIZERS_PARALLELISM"):
        monkeypatch.setenv(key, "initial")
    if fail:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            synthesize("Hallo ʏ.", output, models, 1.0, model_manifest())
        assert output.read_bytes() == b"previous audio"
    else:
        synthesize("Hallo ʏ.", output, models, 1.0, model_manifest())
        with wave.open(str(output)) as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
            assert wav.getnframes() == 2400
    assert calls == ["Hallo y."]
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert not list(tmp_path.glob(".kokoro-*"))
