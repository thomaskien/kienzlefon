from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import kienzlefon.webadmin as webadmin_module
from kienzlefon.config import load_config
from kienzlefon.webadmin import WebAdminWorker, export_state


def _web_config(tmp_path: Path) -> Path:
    path = tmp_path / "webinterface.json"
    path.write_text(
        json.dumps(
            {
                "passwordless": True,
                "listen": "10.9.0.1",
                "port": 8088,
                "server": "standalone",
                "tls": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _configured_ai(app_config):
    text = app_config.source.read_text(encoding="utf-8")
    text = text.replace("[ki_integration]\naktiv = false", "[ki_integration]\naktiv = true", 1)
    text = text.replace("anzahl_nebenstellen = 0", "anzahl_nebenstellen = 1", 1)
    text = text.replace(
        "sip_passwoerter = []",
        'sip_passwoerter = ["assistant-test-password-0001"]',
        1,
    )
    app_config.source.write_text(text, encoding="utf-8")
    return load_config(app_config.source)


def _worker(app_config, tmp_path: Path) -> WebAdminWorker:
    return WebAdminWorker(
        config_path=app_config.source,
        defaults_path=Path("config/kienzlefon.toml.example"),
        web_config_path=_web_config(tmp_path),
        runtime_path=tmp_path / "web-runtime",
        config_command="/usr/bin/true",
        prompts_command="/usr/bin/false",
        php_binary=shutil.which("php") or "/usr/bin/php",
    )


def _queue(worker: WebAdminWorker, job_id: str, payload: dict) -> None:
    worker.inbox.mkdir(parents=True, exist_ok=True)
    path = worker.inbox / f"job-{job_id}.json"
    path.write_text(json.dumps({"id": job_id, **payload}), encoding="utf-8")


def _config_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status(worker: WebAdminWorker, job_id: str) -> dict:
    return json.loads((worker.status_directory / f"{job_id}.json").read_text())


def test_export_reports_assistant_as_configured_enabled_or_unconfigured(
    app_config, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime-unconfigured"
    state = export_state(
        app_config.source,
        Path("config/kienzlefon.toml.example"),
        _web_config(tmp_path),
        runtime / "state.json",
        runtime / "password.hash",
        php_binary=shutil.which("php") or "/usr/bin/php",
    )

    assert state["assistant"] == {"configured": False, "enabled": False}

    configured = _configured_ai(app_config)
    runtime = tmp_path / "runtime-configured"
    state = export_state(
        configured.source,
        Path("config/kienzlefon.toml.example"),
        _web_config(tmp_path),
        runtime / "state.json",
        runtime / "password.hash",
        php_binary=shutil.which("php") or "/usr/bin/php",
    )

    assert state["assistant"] == {"configured": True, "enabled": True}
    serialized = json.dumps(state)
    assert "assistant-test-password-0001" not in serialized
    assert "listener_ip" not in serialized


def test_assistant_only_save_toggles_without_tts_or_service_restart(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    configured = _configured_ai(app_config)
    worker = _worker(configured, tmp_path)
    original = tomllib.loads(configured.source.read_text(encoding="utf-8"))["ki_integration"]
    calls: list[list[str]] = []

    def command(arguments: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    def unexpected_tts(*_args, **_kwargs) -> None:
        raise AssertionError("Reiner KI-Schalter darf keine TTS-Erzeugung starten")

    monkeypatch.setattr(webadmin_module, "_run_command", command)
    monkeypatch.setattr(worker, "_generate_prompts", unexpected_tts)

    for index, enabled in enumerate((False, True), start=1):
        job_id = str(index) * 32
        _queue(
            worker,
            job_id,
            {
                "action": "save",
                "config_hash": _config_hash(configured.source),
                "assistant": {"enabled": enabled},
            },
        )

        assert worker.run_once() is True
        loaded = load_config(configured.source)
        assert loaded.ai_integration.assistant_enabled is enabled
        assert json.loads(worker.state_path.read_text())["assistant"]["enabled"] is enabled
        assert _status(worker, job_id)["code"] == "einstellungen_aktuell"

    updated = tomllib.loads(configured.source.read_text(encoding="utf-8"))["ki_integration"]
    assert {key: value for key, value in updated.items() if key != "assistent_aktiv"} == {
        key: value for key, value in original.items() if key != "assistent_aktiv"
    }
    operational_calls = [call for call in calls if call[0] != worker.config_command]
    assert operational_calls == [
        [worker.asterisk_config_command, "--config", str(configured.source)],
        [worker.asterisk_command, "-rx", "dialplan reload"],
        [worker.asterisk_config_command, "--config", str(configured.source)],
        [worker.asterisk_command, "-rx", "dialplan reload"],
    ]
    assert not any(
        "restart" in argument or "pjsip" in argument.lower()
        for call in operational_calls
        for argument in call
    )


def test_combined_assistant_save_keeps_tts_and_then_reloads_dialplan(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    configured = _configured_ai(app_config)
    worker = _worker(configured, tmp_path)
    generated: list[tuple[str, bool]] = []
    calls: list[list[str]] = []

    def generate(
        job_id: str, *, arguments: tuple[str, ...] = (), final_status: bool = True
    ) -> None:
        assert arguments == ()
        generated.append((job_id, final_status))

    def command(arguments: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr(worker, "_generate_prompts", generate)
    monkeypatch.setattr(webadmin_module, "_run_command", command)
    job_id = "3" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": _config_hash(configured.source),
            "assistant": {"enabled": False},
            "prompts": {"greeting_open": "Guten Tag mit ausgeschaltetem Assistenten."},
        },
    )

    assert worker.run_once() is True
    assert generated == [(job_id, False)]
    operational_calls = [call for call in calls if call[0] != worker.config_command]
    assert operational_calls == [
        [worker.asterisk_config_command, "--config", str(configured.source)],
        [worker.asterisk_command, "-rx", "dialplan reload"],
    ]
    assert _status(worker, job_id)["code"] == "ansagen_aktuell"
    loaded = load_config(configured.source)
    assert loaded.ai_integration.assistant_enabled is False
    assert loaded.prompts["greeting_open"] == "Guten Tag mit ausgeschaltetem Assistenten."


def test_assistant_reload_failure_is_reported_and_state_stays_current(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    configured = _configured_ai(app_config)
    worker = _worker(configured, tmp_path)

    def command(arguments: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        returncode = 1 if arguments[-1] == "dialplan reload" else 0
        return subprocess.CompletedProcess(arguments, returncode, b"", b"reload kaputt")

    monkeypatch.setattr(webadmin_module, "_run_command", command)
    job_id = "4" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": _config_hash(configured.source),
            "assistant": {"enabled": False},
        },
    )

    assert worker.run_once() is True
    assert _status(worker, job_id)["code"] == "auftrag_abgelehnt"
    assert "reload kaputt" in _status(worker, job_id)["detail"]
    assert json.loads(worker.state_path.read_text())["assistant"] == {
        "configured": True,
        "enabled": False,
    }


def test_assistant_save_rejects_invalid_payloads_and_stale_hash(
    app_config, tmp_path: Path
) -> None:
    worker = _worker(app_config, tmp_path)
    before = app_config.source.read_bytes()
    valid_hash = hashlib.sha256(before).hexdigest()
    payloads = (
        {"assistant": None, "config_hash": valid_hash},
        {"assistant": {}, "config_hash": valid_hash},
        {"assistant": {"enabled": "false"}, "config_hash": valid_hash},
        {"assistant": {"enabled": False, "extra": True}, "config_hash": valid_hash},
        {"assistant": {"enabled": True}, "config_hash": valid_hash},
        {"assistant": {"enabled": False}, "config_hash": "0" * 64},
    )

    for index, payload in enumerate(payloads, start=5):
        job_id = f"{index:x}" * 32
        _queue(worker, job_id, {"action": "save", **payload})
        assert worker.run_once() is True
        assert _status(worker, job_id)["code"] == "auftrag_abgelehnt"
        assert app_config.source.read_bytes() == before
