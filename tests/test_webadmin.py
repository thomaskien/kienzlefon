from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

import kienzlefon.webadmin as webadmin_module
from kienzlefon.config import load_config
from kienzlefon.prompts import PromptGenerator
from kienzlefon.webadmin import WebAdminWorker, export_state


def _web_config(path: Path, *, passwordless: bool = True) -> Path:
    target = path / "webinterface.json"
    target.write_text(
        json.dumps(
            {
                "passwordless": passwordless,
                "listen": "10.9.0.1",
                "port": 8088,
                "server": "standalone",
                "tls": False,
            }
        ),
        encoding="utf-8",
    )
    return target


def _worker(app_config, tmp_path: Path, *, prompts_command: str = "/usr/bin/true"):
    runtime = tmp_path / "web-runtime"
    return WebAdminWorker(
        config_path=app_config.source,
        defaults_path=Path("config/kienzlefon.toml.example"),
        web_config_path=_web_config(tmp_path),
        runtime_path=runtime,
        config_command="/usr/bin/true",
        prompts_command=prompts_command,
        php_binary=shutil.which("php") or "/usr/bin/php",
    )


def _queue(worker: WebAdminWorker, job_id: str, value: dict) -> Path:
    worker.inbox.mkdir(parents=True, exist_ok=True)
    value = {"id": job_id, **value}
    path = worker.inbox / f"job-{job_id}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_expired_override_is_not_effective(app_config) -> None:
    text = app_config.source.read_text(encoding="utf-8")
    text = text.replace("aktiv = false", "aktiv = true", 1)
    text = text.replace('ansage = ""', 'ansage = "Urlaubsansage"', 1)
    text = text.replace('ablauf = ""', 'ablauf = "2000-01-01T12:00"', 1)
    app_config.source.write_text(text, encoding="utf-8")

    loaded = load_config(app_config.source)

    assert loaded.override.active is True
    assert loaded.override_is_active() is False
    assert loaded.phone_is_open() is False  # Leere Test-Telefonzeiten bleiben geschlossen.


def test_explicit_tts_source_keeps_but_ignores_manual_file(app_config) -> None:
    manual = app_config.tts.upload_directory / "greeting_open.wav16"
    manual.parent.mkdir(parents=True, exist_ok=True)
    manual.write_bytes(b"manual")
    with app_config.source.open("a", encoding="utf-8") as handle:
        handle.write('\n[ansagen_quellen]\ngreeting_open = "tts"\n')
    loaded = load_config(app_config.source)

    assert manual.is_file()
    assert PromptGenerator(loaded)._manual_source("greeting_open") is None


def test_explicit_manual_source_requires_recording(app_config) -> None:
    with app_config.source.open("a", encoding="utf-8") as handle:
        handle.write('\n[ansagen_quellen]\ngreeting_open = "manuell"\n')
    loaded = load_config(app_config.source)

    with pytest.raises(RuntimeError, match="Manuelle Ansage fehlt"):
        PromptGenerator(loaded)._manual_source("greeting_open")


def test_export_state_contains_only_sanitized_web_values(app_config, tmp_path: Path) -> None:
    text = app_config.source.read_text(encoding="utf-8").replace(
        "[ansagen]\n",
        '[ansagen]\nai_assistant_intro = "Nicht mehr verwendete Alt-Ansage."\n',
        1,
    )
    app_config.source.write_text(
        text + '\n[webinterface]\npasswort = "sehr-geheim-123"\n',
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime"
    state = export_state(
        app_config.source,
        Path("config/kienzlefon.toml.example"),
        _web_config(tmp_path, passwordless=False),
        runtime / "state.json",
        runtime / "password.hash",
        php_binary=shutil.which("php") or "/usr/bin/php",
    )

    serialized = json.dumps(state, ensure_ascii=False)
    assert "sehr-geheim-123" not in serialized
    assert "CHANGE_ME_RED_PHONE_SECRET" not in serialized
    assert "ai_assistant_intro" not in serialized
    assert "Nicht mehr verwendete Alt-Ansage." not in serialized
    assert state["auth_required"] is True
    assert state["auth_ready"] is True
    assert (runtime / "password.hash").read_text().startswith("$")
    assert "777" not in state["extensions"]
    sources = {source["name"]: source for source in state["sources"]}
    assert sources["urgent_help"]["fields"][0]["name"] == "urgent_help"
    assert "Bereitschaftsdienst" in sources["urgent_help"]["tts_text"]
    assert [field["name"] for field in sources["opening_hours"]["fields"]] == [
        "opening_hours_prefix",
        "opening_hours_closed",
    ]
    assert state["tts"]["engine"] == "kokoro"
    assert state["tts"]["qwen_voice"] == "ryan"
    assert state["tts"]["qwen_available"] is False
    assert set(state["schedules"]) == {
        "oeffnungszeiten",
        "telefonzeiten",
        "apothekenzeiten",
        "fachstellenzeiten",
    }
    assert state["product"] == {
        "name": "kienzlefon.de",
        "version": "2.7",
        "author": "Dr. Thomas Kienzle",
        "url": "https://kienzlefon.de",
    }
    assert sources["urgent_help"]["mode"] == "immer"
    assert state["hold_music"] == {
        "installed": False,
        "mode": "klingelzeichen",
        "preview": False,
        "default_mode": "musik",
        "preview_extension": "",
    }

    first_hash = (runtime / "password.hash").read_text()
    export_state(
        app_config.source,
        Path("config/kienzlefon.toml.example"),
        _web_config(tmp_path, passwordless=False),
        runtime / "state.json",
        runtime / "password.hash",
        php_binary=shutil.which("php") or "/usr/bin/php",
    )
    assert (runtime / "password.hash").read_text() == first_hash


def test_worker_saves_hold_music_mode_and_only_reloads_asterisk(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    text = app_config.source.read_text(encoding="utf-8").replace(
        "[wartemusik]\n", "[wartemusik]\ninstalliert = true\n", 1
    ).replace("installiert = false\n", "", 1)
    app_config.source.write_text(text, encoding="utf-8")
    config = load_config(app_config.source)
    worker = _worker(config, tmp_path)
    calls: list[list[str]] = []

    def command(arguments: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr(webadmin_module, "_run_command", command)
    job_id = "3" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": hashlib.sha256(app_config.source.read_bytes()).hexdigest(),
            "hold_music": {"mode": "musik"},
        },
    )

    assert worker.run_once() is True
    assert load_config(app_config.source).hold_music.mode == "musik"
    assert ["/opt/kienzlefon/venv/bin/kienzlefon-asterisk", "--config", str(app_config.source)] in calls
    reloads = [call[-1] for call in calls if len(call) >= 3 and call[-2] == "-rx"]
    assert reloads == ["dialplan reload", "moh reload", "module reload app_queue.so"]
    assert not any("restart" in argument or "stop" in argument for call in calls for argument in call)


def test_export_exposes_installed_hold_music_from_fixed_protected_copy(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    text = app_config.source.read_text(encoding="utf-8").replace(
        "installiert = false", "installiert = true", 1
    )
    app_config.source.write_text(text, encoding="utf-8")
    music = tmp_path / "installed-hold-music.wav16"
    music.write_bytes(b"RIFF-protected-preview")
    monkeypatch.setattr(webadmin_module, "DEFAULT_BROWSER_WAV", music)
    runtime = tmp_path / "music-runtime"

    state = export_state(
        app_config.source,
        Path("config/kienzlefon.toml.example"),
        _web_config(tmp_path),
        runtime / "state.json",
        runtime / "password.hash",
        php_binary=shutil.which("php") or "/usr/bin/php",
    )

    assert state["hold_music"]["installed"] is True
    assert state["hold_music"]["preview"] is True
    assert state["hold_music"]["preview_extension"] == "8805"
    assert (runtime / "audio" / "hold-music.wav").read_bytes() == music.read_bytes()


def test_worker_applies_only_allowed_values_and_runs_generator(app_config, tmp_path: Path) -> None:
    worker = _worker(app_config, tmp_path)
    original_hash = hashlib.sha256(app_config.source.read_bytes()).hexdigest()
    job_id = "a" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": original_hash,
            "schedules": {
                "telefonzeiten": {
                    "montag": ["08:00-12:00"],
                    "dienstag": [],
                    "mittwoch": [],
                    "donnerstag": [],
                    "freitag": [],
                    "samstag": [],
                    "sonntag": [],
                }
            },
            "prompts": {"greeting_open": "Guten Tag aus dem Webinterface."},
        },
    )

    assert worker.run_once() is True
    with app_config.source.open("rb") as handle:
        updated = tomllib.load(handle)
    assert updated["telefonzeiten"]["montag"] == ["08:00-12:00"]
    assert updated["ansagen"]["greeting_open"] == "Guten Tag aus dem Webinterface."
    assert updated["asterisk"]["rotes_telefon_passwort"] == "test-red-secret"
    status = json.loads((worker.status_directory / f"{job_id}.json").read_text())
    assert status["code"] == "ansagen_aktuell"
    assert json.loads(worker.state_path.read_text())["config_hash"] == hashlib.sha256(
        app_config.source.read_bytes()
    ).hexdigest()


def test_web_worker_streams_current_prompt_into_job_status(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    command = tmp_path / "prompt-progress"
    command.write_text(
        """#!/bin/sh
printf '%s\n' 'KIENZLEFON_FORTSCHRITT {"current":0,"total":2,"phase":"plan","name":"","label":""}'
printf '%s\n' 'KIENZLEFON_FORTSCHRITT {"current":1,"total":2,"phase":"generate","name":"greeting_open","label":""}'
printf '%s\n' 'KIENZLEFON_FORTSCHRITT {"current":2,"total":2,"phase":"qwen_restore","name":"","label":""}'
""",
        encoding="utf-8",
    )
    command.chmod(0o755)
    worker = _worker(app_config, tmp_path, prompts_command=str(command))
    statuses: list[tuple[str, str]] = []
    original_status = worker._status

    def capture_status(job_id: str, code: str, *, detail: str = "") -> None:
        statuses.append((code, detail))
        original_status(job_id, code, detail=detail)

    monkeypatch.setattr(worker, "_status", capture_status)

    worker._generate_prompts("1" * 32)

    assert (
        "ansagen_werden_aktualisiert",
        "[1/2] Automatische Ansage wird erzeugt: Begrüßung bei geöffneter Praxis",
    ) in statuses
    assert (
        "ansagen_werden_aktualisiert",
        "[2/2] Ansagen fertig; Whisper-Worker wird wieder gestartet.",
    ) in statuses
    assert statuses[-1] == ("ansagen_aktuell", "")


def test_web_worker_requests_new_qwen_variant_for_only_selected_prompt(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    text = app_config.source.read_text(encoding="utf-8")
    app_config.source.write_text(
        text.replace('engine = "kokoro"', 'engine = "qwen"', 1),
        encoding="utf-8",
    )
    worker = _worker(app_config, tmp_path)
    requested: list[tuple[str, tuple[str, ...]]] = []

    def generate(job_id: str, *, arguments: tuple[str, ...] = ()) -> None:
        requested.append((job_id, arguments))

    monkeypatch.setattr(worker, "_generate_prompts", generate)
    monkeypatch.setattr(worker, "export", lambda: {})
    job_id = "9" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "regenerate_prompt",
            "config_hash": hashlib.sha256(app_config.source.read_bytes()).hexdigest(),
            "prompt": "first_name",
        },
    )

    assert worker.run_once() is True
    assert requested == [
        (job_id, ("--prompt", "first_name", "--new-variant"))
    ]


def test_worker_rejects_non_allowlisted_fields_without_changing_config(
    app_config, tmp_path: Path
) -> None:
    worker = _worker(app_config, tmp_path)
    before = app_config.source.read_bytes()
    job_id = "b" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": hashlib.sha256(before).hexdigest(),
            "asterisk": {"rotes_telefon_passwort": "angriff"},
        },
    )

    assert worker.run_once() is True
    assert app_config.source.read_bytes() == before
    status = json.loads((worker.status_directory / f"{job_id}.json").read_text())
    assert status["code"] == "auftrag_abgelehnt"


def test_worker_rejects_empty_announcement_before_replacing_config(
    app_config, tmp_path: Path
) -> None:
    worker = _worker(app_config, tmp_path)
    before = app_config.source.read_bytes()
    job_id = "e" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": hashlib.sha256(before).hexdigest(),
            "prompts": {"greeting_open": "   "},
        },
    )

    assert worker.run_once() is True
    assert app_config.source.read_bytes() == before
    status = json.loads((worker.status_directory / f"{job_id}.json").read_text())
    assert status["code"] == "auftrag_abgelehnt"
    assert "darf nicht leer sein" in status["detail"]


def test_worker_saves_prompt_modes_without_changing_prompt_texts(
    app_config, tmp_path: Path
) -> None:
    worker = _worker(app_config, tmp_path)
    before_prompt = app_config.prompts["emergency"]
    job_id = "6" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": hashlib.sha256(app_config.source.read_bytes()).hexdigest(),
            "prompt_modes": {
                "emergency": "deaktiviert",
                "no_selection_open": "deaktiviert",
            },
        },
    )

    assert worker.run_once() is True
    updated = load_config(app_config.source)
    assert updated.prompt_mode("emergency") == "deaktiviert"
    assert updated.prompt_mode("no_selection_open") == "deaktiviert"
    assert updated.prompts["emergency"] == before_prompt


def test_worker_changes_global_qwen_voice_only_when_generator_is_allowlisted(
    app_config, tmp_path: Path
) -> None:
    generator = tmp_path / "kienzlefon-qwen3-tts-generate"
    generator.write_text("#!/bin/sh\n# kienzlefon-worker.service\n", encoding="utf-8")
    generator.chmod(0o755)
    text = app_config.source.read_text(encoding="utf-8")
    text = text.replace(
        'qwen_generator = "/usr/local/bin/kienzlefon-qwen3-tts-generate"',
        f'qwen_generator = "{generator}"',
    )
    app_config.source.write_text(text, encoding="utf-8")
    worker = _worker(load_config(app_config.source), tmp_path)
    job_id = "f" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": hashlib.sha256(app_config.source.read_bytes()).hexdigest(),
            "tts": {"engine": "qwen", "qwen_voice": "serena"},
        },
    )

    assert worker.run_once() is True
    with app_config.source.open("rb") as handle:
        updated = tomllib.load(handle)
    assert updated["tts"]["engine"] == "qwen"
    assert updated["tts"]["qwen_stimme"] == "serena"


def test_worker_does_not_follow_symlinked_job(app_config, tmp_path: Path) -> None:
    worker = _worker(app_config, tmp_path)
    before = app_config.source.read_bytes()
    worker.inbox.mkdir(parents=True, exist_ok=True)
    job_id = "d" * 32
    (worker.inbox / f"job-{job_id}.json").symlink_to(app_config.source)

    assert worker.run_once() is True
    assert app_config.source.read_bytes() == before
    status = json.loads((worker.status_directory / f"{job_id}.json").read_text())
    assert status["code"] == "auftrag_abgelehnt"


def test_candidate_activation_preserves_previous_manual_as_archive(
    app_config, tmp_path: Path
) -> None:
    worker = _worker(app_config, tmp_path)
    upload = app_config.tts.upload_directory
    upload.mkdir(parents=True, exist_ok=True)
    active = upload / "greeting_open.wav16"
    candidate = upload / "kandidaten" / "greeting_open.wav16"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"old-binary-audio\x00\xff")
    candidate.write_bytes(b"new-binary-audio\xff\x00")
    job_id = "c" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "activate_candidate",
            "config_hash": hashlib.sha256(app_config.source.read_bytes()).hexdigest(),
            "prompt": "greeting_open",
        },
    )

    assert worker.run_once() is True
    assert active.read_bytes() == b"new-binary-audio\xff\x00"
    assert not candidate.exists()
    archives = list((upload / "inaktiv").glob("greeting_open_*.wav16"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == b"old-binary-audio\x00\xff"
    with app_config.source.open("rb") as handle:
        updated = tomllib.load(handle)
    assert updated["ansagen_quellen"]["greeting_open"] == "manuell"


def test_failed_candidate_generation_restores_config_and_manual(
    app_config, tmp_path: Path
) -> None:
    worker = _worker(app_config, tmp_path, prompts_command="/usr/bin/false")
    upload = app_config.tts.upload_directory
    upload.mkdir(parents=True, exist_ok=True)
    active = upload / "greeting_open.wav16"
    candidate = upload / "kandidaten" / "greeting_open.wav16"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"old")
    candidate.write_bytes(b"new")
    before = app_config.source.read_bytes()
    job_id = "e" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "activate_candidate",
            "config_hash": hashlib.sha256(before).hexdigest(),
            "prompt": "greeting_open",
        },
    )

    assert worker.run_once() is True
    assert app_config.source.read_bytes() == before
    assert active.read_bytes() == b"old"
    assert candidate.read_bytes() == b"new"
    status = json.loads((worker.status_directory / f"{job_id}.json").read_text())
    assert status["code"] == "ansagenerzeugung_fehlgeschlagen"


def test_export_copies_audio_previews_and_named_override_presets(
    app_config, tmp_path: Path
) -> None:
    masters = app_config.paths.prompt_masters
    masters.mkdir(parents=True, exist_ok=True)
    (masters / "urgent_help.wav").write_bytes(b"active-audio")
    candidate = app_config.tts.upload_directory / "kandidaten" / "urgent_help.wav16"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"candidate-audio")
    preset_id = "1" * 32
    preset = masters / "sonderansagen" / preset_id
    preset.mkdir(parents=True)
    (preset / "metadata.json").write_text(
        json.dumps(
            {
                "name": "Quartalsanfang",
                "announcement": "Bitte lesen Sie Ihre Versichertenkarte ein.",
                "active": True,
                "priority": 200,
                "valid_from": "2000-01-01T00:00",
                "expires_at": "2000-04-01T00:00",
                "block_phone_hours": False,
                "position": "nach_begruessung",
            }
        ),
        encoding="utf-8",
    )
    (preset / "tts.wav").write_bytes(b"preset-tts")
    (preset / "manuell.wav").write_bytes(b"preset-manual")
    runtime = tmp_path / "preview-runtime"

    state = export_state(
        app_config.source,
        Path("config/kienzlefon.toml.example"),
        _web_config(tmp_path),
        runtime / "state.json",
        runtime / "password.hash",
        php_binary=shutil.which("php") or "/usr/bin/php",
    )

    source = next(item for item in state["sources"] if item["name"] == "urgent_help")
    assert source["active_preview"] is True
    assert source["candidate_preview"] is True
    assert (runtime / "audio" / "active-urgent_help.wav").read_bytes() == b"active-audio"
    assert (runtime / "audio" / "candidate-urgent_help.wav").read_bytes() == b"candidate-audio"
    saved = state["override_presets"][0]
    assert saved["name"] == "Quartalsanfang"
    assert saved["position"] == "nach_begruessung"
    assert saved["past"] is True
    assert saved["future"] is False
    assert saved["tts_preview"] is True
    assert saved["manual_preview"] is True


def test_worker_saves_updates_and_recoverably_deletes_named_override_preset(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    worker = _worker(app_config, tmp_path)
    syntheses = 0

    def fake_synthesis(_generator, text: str, output: Path, name: str) -> None:
        nonlocal syntheses
        syntheses += 1
        assert text == "Hinweis zum Quartalsanfang."
        assert name.startswith("sonderansage-")
        output.write_bytes(b"generated-tts")

    monkeypatch.setattr(PromptGenerator, "synthesize_text_file", fake_synthesis)
    first_job = "6" * 32
    _queue(
        worker,
        first_job,
        {
            "action": "save_override_preset",
            "name": "Quartalsanfang",
            "announcement": "Hinweis zum Quartalsanfang.",
            "active": True,
            "priority": 200,
            "valid_from": "2026-01-01T00:00",
            "expires_at": "2027-01-01T00:00",
            "block_phone_hours": False,
            "position": "nach_begruessung",
            "source": "tts",
        },
    )

    assert worker.run_once() is True
    assert syntheses == 1
    state = json.loads(worker.state_path.read_text())
    assert len(state["override_presets"]) == 1
    preset = state["override_presets"][0]
    preset_id = preset["id"]
    assert preset["tts_available"] is True
    assert preset["manual_available"] is False
    assert preset["position"] == "nach_begruessung"
    assert preset["priority"] == 200
    assert preset["active"] is True
    assert json.loads(
        (worker.status_directory / f"{first_job}.json").read_text()
    )["code"] == "vorlage_gespeichert"

    preset_directory = app_config.paths.prompt_masters / "sonderansagen" / preset_id
    (preset_directory / "manuell.wav").write_bytes(b"manual-preserved")
    update_job = "7" * 32
    _queue(
        worker,
        update_job,
        {
            "action": "save_override_preset",
            "name": "Quartalsanfang",
            "announcement": "Hinweis zum Quartalsanfang.",
            "active": True,
            "priority": 200,
            "valid_from": "2026-01-01T00:00",
            "expires_at": "2027-01-01T00:00",
            "block_phone_hours": False,
            "position": "nach_begruessung",
            "source": "manuell",
        },
    )
    assert worker.run_once() is True
    assert syntheses == 1
    assert (preset_directory / "manuell.wav").read_bytes() == b"manual-preserved"
    assert json.loads(worker.state_path.read_text())["override_presets"][0][
        "manual_available"
    ] is True

    collision_job = "a" * 32
    _queue(
        worker,
        collision_job,
        {
            "action": "save_override_preset",
            "name": "Andere aktive Ansage",
            "announcement": "Ein anderer Text.",
            "active": True,
            "priority": 200,
            "valid_from": "",
            "expires_at": "",
            "block_phone_hours": False,
            "position": "statt_begruessung",
            "source": "tts",
        },
    )
    assert worker.run_once() is True
    assert json.loads(
        (worker.status_directory / f"{collision_job}.json").read_text()
    )["code"] == "auftrag_abgelehnt"
    assert len(json.loads(worker.state_path.read_text())["override_presets"]) == 1

    delete_job = "0" * 32
    _queue(
        worker,
        delete_job,
        {"action": "delete_override_preset", "preset_id": preset_id},
    )
    assert worker.run_once() is True
    assert json.loads(worker.state_path.read_text())["override_presets"] == []
    deleted = app_config.paths.prompt_masters / "sonderansagen" / ".geloescht"
    assert len(list(deleted.glob(f"{preset_id}-*"))) == 1


def test_worker_loads_saved_manual_override_without_deleting_preset(
    app_config, tmp_path: Path
) -> None:
    worker = _worker(app_config, tmp_path)
    preset_id = "8" * 32
    preset = app_config.paths.prompt_masters / "sonderansagen" / preset_id
    preset.mkdir(parents=True)
    (preset / "metadata.json").write_text(
        json.dumps(
            {
                "name": "Weihnachten",
                "announcement": "Wir wünschen frohe Weihnachten.",
                "block_phone_hours": True,
                "position": "nach_begruessung",
            }
        ),
        encoding="utf-8",
    )
    (preset / "tts.wav").write_bytes(b"tts-kept")
    (preset / "manuell.wav").write_bytes(b"manual-kept")
    job_id = "9" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save",
            "config_hash": hashlib.sha256(app_config.source.read_bytes()).hexdigest(),
            "override": {
                "active": True,
                "announcement": "Wir wünschen frohe Weihnachten.",
                "expires_at": "",
                "block_phone_hours": True,
                "position": "nach_begruessung",
                "manual_preset_id": preset_id,
            },
            "sources": {"override": "manuell"},
        },
    )

    assert worker.run_once() is True
    assert (app_config.tts.upload_directory / "override.wav16").read_bytes() == b"manual-kept"
    assert (preset / "tts.wav").read_bytes() == b"tts-kept"
    assert (preset / "manuell.wav").read_bytes() == b"manual-kept"
    with app_config.source.open("rb") as handle:
        updated = tomllib.load(handle)
    assert updated["override"]["position"] == "nach_begruessung"
    assert updated["ansagen_quellen"]["override"] == "manuell"


def test_named_override_save_copies_current_manual_candidate(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    worker = _worker(app_config, tmp_path)
    candidate = app_config.tts.upload_directory / "kandidaten" / "override.wav16"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"current-manual-candidate")

    def fake_synthesis(_generator, _text: str, output: Path, _name: str) -> None:
        output.write_bytes(b"stored-tts")

    monkeypatch.setattr(PromptGenerator, "synthesize_text_file", fake_synthesis)
    job_id = "5" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "save_override_preset",
            "name": "Manuell vorbereitet",
            "announcement": "Der zugehörige TTS-Text.",
            "active": False,
            "priority": 150,
            "valid_from": "",
            "expires_at": "",
            "block_phone_hours": False,
            "position": "nach_begruessung",
            "source": "manuell",
        },
    )

    assert worker.run_once() is True
    saved = json.loads(worker.state_path.read_text())["override_presets"][0]
    directory = app_config.paths.prompt_masters / "sonderansagen" / saved["id"]
    assert (directory / "tts.wav").read_bytes() == b"stored-tts"
    assert (directory / "manuell.wav").read_bytes() == b"current-manual-candidate"
    assert saved["source"] == "manuell"
    assert saved["manual_available"] is True


def test_worker_keeps_tts_and_accepted_wav_for_recorded_override_preset(
    app_config, tmp_path: Path, monkeypatch
) -> None:
    worker = _worker(app_config, tmp_path)

    def fake_synthesis(_generator, _text: str, output: Path, _name: str) -> None:
        output.write_bytes(b"tts-version")

    def fake_record(job_id: str, name: str, extension: str, _config) -> str:
        assert job_id == "2" * 32
        assert name.startswith("preset_")
        assert extension == app_config.local_extensions[0]
        candidate = app_config.tts.upload_directory / "kandidaten" / f"{name}.wav16"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"manual-version")
        return "aufnahme_gespeichert"

    monkeypatch.setattr(PromptGenerator, "synthesize_text_file", fake_synthesis)
    monkeypatch.setattr(worker, "_record_candidate", fake_record)
    job_id = "2" * 32
    _queue(
        worker,
        job_id,
        {
            "action": "record_override_preset",
            "name": "Weihnachten",
            "announcement": "Unsere Weihnachtsansage.",
            "active": False,
            "priority": 100,
            "valid_from": "",
            "expires_at": "",
            "block_phone_hours": True,
            "position": "statt_begruessung",
            "source": "manuell",
            "extension": app_config.local_extensions[0],
        },
    )

    assert worker.run_once() is True
    preset = json.loads(worker.state_path.read_text())["override_presets"][0]
    directory = app_config.paths.prompt_masters / "sonderansagen" / preset["id"]
    assert (directory / "tts.wav").read_bytes() == b"tts-version"
    assert (directory / "manuell.wav").read_bytes() == b"manual-version"
    assert preset["tts_available"] is True
    assert preset["manual_available"] is True
    assert json.loads(
        (worker.status_directory / f"{job_id}.json").read_text()
    )["code"] == "vorlage_gespeichert"


def test_separate_installer_and_php_have_valid_syntax() -> None:
    subprocess.run(["bash", "-n", "kienzlefon-webinterface-installer.sh"], check=True)
    php = shutil.which("php")
    if php:
        result = subprocess.run(
            [php, "-l", "webinterface/admin.php"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "No syntax errors" in result.stdout
    installer = Path("kienzlefon-webinterface-installer.sh").read_text(encoding="utf-8")
    assert 'VERSION="2.7"' in installer
    assert '--from-main-installer) confirmed="y"' in installer
    assert "d ${RUNTIME_DIR}/audio 0750 root ${WEB_GROUP} -" in installer
    assert "DirectoryNotEmpty=${RUNTIME_DIR}/inbox" in installer
    assert "ProtectSystem=strict" in installer
    assert "sites-available/kienzlefon-webinterface.conf" in installer
    assert "sites-available/kienzlefon-webinterface" in installer
    assert "kienzlefon-installer.sh" not in installer
    assert "trap 'installer_error" in installer
    assert "{print $1; exit}" not in installer
    assert "from kienzlefon.config import load_config" in installer
    assert "return 0" in installer
    assert '[[ "$TLS_ENABLED" == "true" ]] || return 0' in installer
    assert '"/proc/${ASTERISK_PID}/status"' in installer
    assert '"${VENV}/bin/kienzlefon-ansagen" --config "$CONFIG_FILE"' in installer
    assert "PrivateDevices=false" in installer
    assert "/run/kienzlefon -/var/lib/kienzlefon/qwen3-tts" in installer


def test_web_installer_skips_certificate_successfully_without_tls() -> None:
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [
            bash,
            "-c",
            'source "$1"; TLS_ENABLED=false; generate_certificate',
            "web-installer-test",
            "kienzlefon-webinterface-installer.sh",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("server", "addresses", "answers", "listen", "tls", "lan_notice", "choice"), [
    ("standalone", "10.0.83.85", "\n", "10.0.83.85", False, True, "\n"),
    ("standalone", "10.0.83.85", "\n", "10.0.83.85", False, True, "j\n"),
    ("standalone", "2001:db8::1 203.0.113.10 172.31.255.12", "\n", "172.31.255.12", False, True, "n\n"),
    ("standalone", "203.0.113.10", "\n", "127.0.0.1", False, False, "j\n"),
    ("standalone", "10.0.83.85", "0.0.0.0\n172.32.0.1\n192.168.1.999\n192.168.1.20\n",
     "192.168.1.20", False, True, "\n"),
    ("apache", "10.0.83.85", "\n", "10.0.83.85", True, True, "j\n"),
    ("nginx", "203.0.113.10", "\n", "203.0.113.10", True, False, ""),
])
def test_web_bind_address_without_wireguard(tmp_path, server, addresses, answers, listen, tls, lan_notice, choice):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/python").symlink_to(os.sys.executable)
    script = r'''
source "$1"
VENV="$2"; WEB_CONFIG="$2/web.json"; SERVER_MODE="$3"; PORT=8088
hostname(){ printf '%s\n' "$HOST_IPS"; }
wg(){ return 0; }
choose_wireguard
write_web_config
'''
    result = subprocess.run(
        ["bash", "-c", script, "test", Path("kienzlefon-webinterface-installer.sh").resolve(),
         tmp_path, server],
        env={**os.environ, "HOST_IPS": addresses}, input=answers + choice, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads((tmp_path / "web.json").read_text())
    assert config["listen"] == listen and config["tls"] is tls
    assert config["passwordless"] is (choice == "j\n")
    assert config["wireguard_interface"] == ""
    assert ("keinesfalls aus dem Internet erreichbar" in result.stdout) == lan_notice
    assert result.stdout.count("Bitte eine feste private IPv4-Adresse") == answers.count("\n") - 1


def test_passwordless_practice_reconfiguration(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/python").symlink_to(os.sys.executable)
    config = tmp_path / "kienzlefon.toml"
    config.write_text('[webinterface]\npasswort = ""\n')
    script = r'''
source "$1"
VENV="$2"; CONFIG_FILE="$2/kienzlefon.toml"; WEB_CONFIG="$2/web.json"; SERVER_MODE=standalone; PORT=8088
hostname(){ echo "10.0.83.85"; }
wg(){ return 0; }
choose_wireguard
configure_password
write_web_config
'''
    for answers, expected in [("\nj\n", True), ("\n\n", True),
                              ("10.0.83.86\n\nTestkennwort1\nTestkennwort1\n", False),
                              ("\nj\n", True), ("\nn\n\n", False)]:
        result = subprocess.run(["bash", "-c", script, "test", Path("kienzlefon-webinterface-installer.sh").resolve(), tmp_path],
                                input=answers, text=True, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert json.loads((tmp_path / "web.json").read_text())["passwordless"] is expected
    assert 'passwort = "Testkennwort1"' in config.read_text()


@pytest.mark.parametrize(("listen", "local", "peer", "wg", "allowed"), [
    ("10.0.83.85", "10.0.83.85", "192.168.5.1", "", True),
    ("10.0.83.85", "10.0.83.84", "10.0.83.10", "", False),
    ("10.0.83.85", "10.0.83.85", "203.0.113.10", "", False),
    ("203.0.113.20", "203.0.113.20", "10.0.83.10", "", False),
    ("127.0.0.1", "127.0.0.1", "127.0.0.1", "", True),
    ("127.0.0.1", "127.0.0.1", "10.0.83.10", "", False),
    ("10.9.0.1", "10.9.0.1", "100.64.8.2", "wg0", True),
])
def test_passwordless_php_access(tmp_path, listen, local, peer, wg, allowed):
    php = shutil.which("php")
    if not php:
        pytest.skip("PHP fehlt")
    (tmp_path / "sessions").mkdir()
    state = {"auth_required": False, "network": {"server": "standalone", "listen": listen, "wireguard_interface": wg}}
    (tmp_path / "state.json").write_text(json.dumps(state))
    result = subprocess.run([php, "-r", '$_GET["api"]="state"; require "webinterface/admin.php";'],
                            env={**os.environ, "KZF_WEB_RUNTIME": str(tmp_path), "REQUEST_METHOD": "GET",
                                 "SERVER_NAME": local, "REMOTE_ADDR": peer, "HTTP_HOST": listen,
                                 "HTTP_X_FORWARDED_FOR": "10.0.83.10"},
                            text=True, capture_output=True, check=True)
    if allowed:
        assert listen in result.stdout
    else:
        assert "für diese Verbindung gesperrt" in result.stdout


def test_web_installer_restores_volatile_state_on_every_boot() -> None:
    installer = Path("kienzlefon-webinterface-installer.sh").read_text(encoding="utf-8")
    refresh_start = installer.index(
        "cat >/etc/systemd/system/kienzlefon-webinterface-refresh.service"
    )
    refresh_end = installer.index(
        "cat >/etc/systemd/system/kienzlefon-webinterface-refresh.path",
        refresh_start,
    )
    refresh_unit = installer[refresh_start:refresh_end]
    standalone_start = installer.index(
        "cat >/etc/systemd/system/kienzlefon-webinterface.service"
    )
    standalone_end = installer.index("systemctl disable --now", standalone_start)
    standalone_unit = installer[standalone_start:standalone_end]

    assert "After=systemd-tmpfiles-setup.service" in refresh_unit
    assert "Before=kienzlefon-webinterface.service apache2.service nginx.service" in (
        refresh_unit
    )
    assert "[Install]\nWantedBy=multi-user.target" in refresh_unit
    assert "Wants=network-online.target kienzlefon-webinterface-refresh.service" in (
        standalone_unit
    )
    assert (
        "systemctl enable --now kienzlefon-webinterface-worker.path "
        "kienzlefon-webinterface-refresh.path kienzlefon-webinterface-refresh.service"
        in installer
    )


@pytest.mark.parametrize("tts_engine", ["kokoro", "piper", "qwen"])
def test_php_renders_passwordless_dashboard_only_on_configured_address(
    tmp_path: Path, tts_engine: str,
) -> None:
    php = shutil.which("php")
    if not php:
        pytest.skip("PHP ist für den Rendertest nicht installiert")
    runtime = tmp_path / "php-runtime"
    for name in ("inbox", "sessions", "status", "audio"):
        (runtime / name).mkdir(parents=True)
    state = {
        "config_hash": "a" * 64,
        "practice": "Praxis Test",
        "ivr_keys": {"ki": "7", "rot": ""},
        "routing_policy": {"remote_enabled": True, "labels": {"201": "Empfang"}, "members": {"201": {
            "normal": {"eligible": True, "default_member": True, "can_enable": True, "can_disable": False, "penalty": 0},
            "specialist": {"eligible": True, "default_member": True, "can_enable": False, "can_disable": False, "penalty": 0},
        }}},
        "product": {
            "name": "kienzlefon.de",
            "version": "2.7",
            "author": "Dr. Thomas Kienzle",
            "url": "https://kienzlefon.de",
        },
        "auth_required": False,
        "auth_ready": True,
        "network": {"listen": "10.9.0.1", "port": 8088, "server": "standalone"},
        "prompts": [
            {
                "name": "urgent_help",
                "label": "Ärztlicher Bereitschaftsdienst",
                "group": "hauptansagen",
                "primary": True,
                "value": "Bereitschaftsdienst anrufen.",
                "default": "Bereitschaftsdienst anrufen.",
            }
        ],
        "sources": [
            {
                "name": "urgent_help",
                "label": "Ärztlicher Bereitschaftsdienst",
                "group": "hauptansagen",
                "primary": True,
                "tts_text": "Bereitschaftsdienst anrufen.",
                "fields": [
                    {
                        "name": "urgent_help",
                        "label": "Ärztlicher Bereitschaftsdienst",
                        "value": "Bereitschaftsdienst anrufen.",
                        "default": "Bereitschaftsdienst anrufen.",
                    }
                ],
                "source": "tts",
                "mode": "immer",
                "default_mode": "immer",
                "manual_available": False,
                "candidate_available": False,
                "active_preview": True,
                "candidate_preview": False,
            }
        ],
        "tts": {
            "engine": tts_engine,
            "kokoro_available": True,
            "qwen_voice": "serena",
            "qwen_available": True,
            "qwen_voices": ["ryan", "serena"],
            "defaults": {"engine": "kokoro", "qwen_voice": "ryan"},
        },
        "schedules": {},
        "schedule_defaults": {},
        "override": {
            "active": False,
            "effective": False,
            "position": "statt_begruessung",
            "active_preview": False,
            "candidate_preview": False,
            "defaults": {"position": "statt_begruessung"},
        },
        "override_presets": [
            {
                "id": "1" * 32,
                "name": "Quartalsanfang",
                "announcement": "Bitte Versichertenkarte einlesen.",
                "active": True,
                "effective": True,
                "past": False,
                "future": False,
                "priority": 200,
                "valid_from": "2000-07-01T00:00",
                "expires_at": "2099-10-01T00:00",
                "block_phone_hours": False,
                "position": "vor_begruessung",
                "source": "manuell",
                "tts_available": True,
                "manual_available": True,
                "tts_preview": True,
                "manual_preview": True,
            },
            {
                "id": "2" * 32,
                "name": "Entwurf",
                "announcement": "Noch nicht aktiv.",
                "active": False,
                "effective": False,
                "past": False,
                "future": False,
                "priority": 100,
                "valid_from": "",
                "expires_at": "",
                "block_phone_hours": True,
                "position": "statt_begruessung",
                "source": "tts",
            },
            {
                "id": "3" * 32,
                "name": "Vergangener Feiertag",
                "announcement": "Diese Ansage ist abgelaufen.",
                "active": True,
                "effective": False,
                "past": True,
                "future": False,
                "priority": 50,
                "valid_from": "2025-12-24T00:00",
                "expires_at": "2025-12-27T00:00",
                "block_phone_hours": False,
                "position": "nach_begruessung",
                "source": "tts",
            },
        ],
        "current_override": {
            "id": "1" * 32,
            "name": "Quartalsanfang",
            "priority": 200,
            "legacy": False,
        },
        "extensions": ["201"],
    }
    (runtime / "state.json").write_text(json.dumps(state), encoding="utf-8")
    environment = dict(os.environ)
    environment.update(
        {
            "KZF_WEB_RUNTIME": str(runtime),
            "REQUEST_METHOD": "GET",
            "REQUEST_URI": "/",
            "REMOTE_ADDR": "10.9.0.2",
            "SERVER_NAME": "10.9.0.1",
            "HTTP_HOST": "nicht-vertrauenswuerdig.example:8088",
        }
    )

    result = subprocess.run(
        [php, "webinterface/admin.php"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert '<div class="shell">' in result.stdout
    assert "Praxis Test" in result.stdout
    assert "Öffnungszeiten" in result.stdout
    assert "Zeiten care_service" in result.stdout
    assert "Zeiten professional_urgent" in result.stdout
    assert "Anrufsbaum" in result.stdout
    assert 'data-ivr-key="ki" maxlength="1" pattern="[0-9*#]?" size="2" value="7"' in result.stdout
    assert 'data-ivr-key="rot"' in result.stdout
    assert 'data-page="routing">Rufgruppen</button>' in result.stdout
    assert 'data-routing-extension="201" data-routing-route="specialist"' in result.stdout
    assert 'value="all" checked' in result.stdout and 'Nur ausgewählte Arbeitsplätze' in result.stdout
    assert 'data-phone-name="201" maxlength="128" required value="Empfang"' in result.stdout
    assert 'kein nutzbarer Schaltzugang' in result.stdout
    assert "Keine Taste" in result.stdout
    assert "Kienzlefon 2.7" in result.stdout
    assert "kienzlefon.de" in result.stdout
    assert "Dr. Thomas Kienzle" in result.stdout
    assert "Genau diese Ansage aufnehmen" in result.stdout
    assert "Genau diese Sonderansage aufnehmen" in result.stdout
    assert "Neue Sonderansage aufnehmen" in result.stdout
    assert "Quartalsanfang" in result.stdout
    assert ">Löschen<" in result.stdout
    assert "preset_manual" in result.stdout
    assert "Derzeit verwendete Ansage anhören" in result.stdout
    assert "Anstelle der Begrüßungsansage" in result.stdout
    assert "Vor der Begrüßungsansage" in result.stdout
    assert "Nach der Begrüßungsansage" in result.stdout
    assert 'id="tts-engine"' in result.stdout
    assert 'id="qwen-voice"' in result.stdout
    assert "Serena (serena)" in result.stdout
    assert 'id="override-preset-position"' in result.stdout
    assert 'id="override-preset-block"' in result.stdout
    assert "Normale Telefonzeiten sperren" in result.stdout
    assert "Aktiv – wird aktuell angesagt" in result.stdout
    assert "Inaktiv" in result.stdout
    assert "Vergangenheit" in result.stdout
    assert 'class="preset-card status-active"' in result.stdout
    assert 'class="preset-card status-inactive"' in result.stdout
    assert 'class="preset-card status-past"' in result.stdout
    (runtime / "audio" / "active-urgent_help.wav").write_bytes(b"browser-audio")
    audio = subprocess.run(
        [
            php,
            "-r",
            'parse_str("api=audio&kind=active&name=urgent_help", $_GET); require "webinterface/admin.php";',
        ],
        check=True,
        capture_output=True,
        env=environment,
    )
    assert audio.stdout == b"browser-audio"
    assert "Auf TTS umschalten" in result.stdout
    assert ("Noch einmal neu generieren" in result.stdout) is (tts_engine == "qwen")
    assert re.search(rf'<option value="{tts_engine}" selected', result.stdout)
    assert 'data-default="kokoro"' in result.stdout
    assert "Kokoro · Thorsten (Standard)" in result.stdout
    node = shutil.which("node")
    if node:
        match = re.search(r'<script nonce="[^"]+">\n(.*?)\n</script>', result.stdout, re.S)
        assert match is not None
        subprocess.run(
            [node, "--check"],
            input=match.group(1),
            check=True,
            capture_output=True,
            text=True,
        )


def test_routing_admin_saves_shared_name_and_scope_without_changing_members(app_config, tmp_path, monkeypatch):
    from kienzlefon import control_setup, phone_callerid
    from kienzlefon.middleware import telephone_extensions
    from kienzlefon.middleware_setup import raw_telephones
    from kienzlefon.telephony_control import Controller, Journal
    from kienzlefon.webadmin import _set_toml_value
    from tests.test_telephony_control import Plant

    source = app_config.source
    local = _set_toml_value(source.read_text(), "control_api", "credentials_file", str(tmp_path / "credentials"))
    source.write_text(local.replace("queue_nebenstellen_anzahl = 1", "queue_nebenstellen_anzahl = 2"))
    control_setup.enable_local(load_config(source), "test-pbx")
    config = load_config(source)
    control_setup.ensure_credentials(config)
    control_setup.register(config, "middleware", ["empfang-1"], tmp_path / "test.token")
    worker = _worker(config, tmp_path)
    journal = Journal(tmp_path / "control")
    plant = Plant()
    controller = Controller(journal, plant)
    controller.refresh(config)
    writer = control_setup.write_policy
    pjsip = tmp_path / "pjsip.conf"
    pjsip.write_text("; Asterisk\n")
    active = {}

    def cli(command):
        if command == "pjsip reload":
            active.update({ext: value for value, ext in re.findall(r'callerid=(".*?" <(\d+)>)', pjsip.read_text())})
            return ""
        return " callerid : " + active[command.split()[-1]]

    monkeypatch.setattr(phone_callerid, "_cli", cli)
    monkeypatch.setattr(control_setup, "write_policy", lambda cfg, p, **kw: writer(
        cfg, p, journal.directory, asterisk_dir=tmp_path, **kw))
    state = worker.export()
    view = state["routing_policy"]
    assert view["writing_access"] == {"middleware": ["empfang-1"]}
    assert view["workplace_mode"] == "all"
    members = view["members"]
    members["201"]["normal"].update(can_enable=True, can_disable=True)
    policy = {"remote_enabled": True, "members": members, "workplace_mode": "selected", "workplace_ids": ["platz-2"]}
    action = {"action": "save_routing_policy", "policy": policy}
    _queue(worker, "a" * 32, {**action, "config_hash": state["config_hash"]})
    worker.run_once()
    config = load_config(source)
    assert config.routing_policy.workplace_ids == ("platz-2",)
    controller.refresh(config)
    controller.set_local_member(config, controller.view(config, journal.load()["epoch"])[0]["revision"], "normal", "201", False)
    before = journal.load()
    old_tab = {**action, "policy": {"members": members, "remote_enabled": True}}
    _queue(worker, "b" * 32, {**old_tab, "config_hash": worker.export()["config_hash"],
                              "names": {"201": "Empfang"}})
    worker.run_once()
    saved = load_config(source)
    assert saved.phone_names == {"201": "Empfang"}
    assert active["201"] == '"Empfang" <201>'
    assert saved.routing_policy == config.routing_policy
    assert telephone_extensions(saved)["201"] == raw_telephones(tomllib.loads(source.read_text()))["201"] == "Empfang"
    controller = Controller(journal, plant)
    controller.refresh(saved)
    assert journal.load() == before
    ext = next(item for item in controller.view(saved, before["epoch"])[1] if item["id"] == "201")
    assert ext["label"] == worker.export()["routing_policy"]["labels"]["201"] == "Empfang"
    assert ext["routing"]["normal"] is False and ext["routing"]["permissions"]["normal"]["can_enable"]
    original = source.read_bytes()
    for index, names in enumerate(({"201": " "}, {"201": "Empfang\nEG"}, {"11111111": "Fremd"}), start=1):
        _queue(worker, str(index) * 32, {**action, "config_hash": worker.export()["config_hash"], "names": names})
        worker.run_once()
        assert source.read_bytes() == original


def test_admin_saves_practice_and_both_menu_orders(app_config, tmp_path):
    from kienzlefon.ivr_keys import MENU_PROMPTS, MENU_CHOICES
    from kienzlefon.prompts import rendered_prompts

    worker = _worker(app_config, tmp_path)
    state = worker.export()
    job = {"action": "save", "practice_name": 'Praxis "Test" am Ring',
           "menu_order": list(reversed(MENU_PROMPTS)), "menu_choices": list(reversed(MENU_CHOICES)),
           "config_hash": state["config_hash"]}
    _queue(worker, "a" * 32, job)
    worker.run_once()
    saved = load_config(app_config.source)
    assert saved.practice.name == job["practice_name"]
    assert saved.menu_order == tuple(job["menu_order"]) and saved.menu_choices == tuple(job["menu_choices"])
    assert saved.practice.name in rendered_prompts(saved)["greeting_open"]
    for field, value in (("menu_order", ["menu_intro"] * len(MENU_PROMPTS)), ("practice_name", "Praxis\nTest")):
        unchanged = app_config.source.read_bytes()
        _queue(worker, "b" * 32, {**job, "config_hash": worker.export()["config_hash"], field: value})
        worker.run_once()
        assert json.loads((worker.status_directory / ("b"*32 + ".json")).read_text())["code"] == "auftrag_abgelehnt"
        assert app_config.source.read_bytes() == unchanged


def test_google_rate_preview_and_save_are_separate(app_config, tmp_path, monkeypatch):
    import wave
    from kienzlefon.webadmin import _set_toml_value

    settings = tmp_path / "google.conf"
    settings.write_text("API_KEY=synthetic-secret\nVOICE=de-DE-Chirp3-HD-Enceladus\nRATE=0.93\n")
    settings.chmod(0o600)
    generator = tmp_path / "generate"
    generator.touch(mode=0o700)
    text = _set_toml_value(app_config.source.read_text(), "tts", "google_generator", str(generator))
    app_config.source.write_text(_set_toml_value(text, "tts", "google_konfig", str(settings)))
    worker = _worker(app_config, tmp_path, prompts_command="/usr/bin/false")
    state = worker.export()
    seen = []
    def run(command, *, timeout):
        if "--output" not in command:
            return subprocess.CompletedProcess(command, 0, b"", b"")
        seen.append(command)
        with wave.open(command[command.index("--output")+1], "wb") as stream:
            stream.setparams((1, 2, 24000, 0, "NONE", ""))
            stream.writeframes(bytes(480))
        return subprocess.CompletedProcess(command, 0, b"", b"")
    monkeypatch.setattr(webadmin_module, "_run_command", run)
    base = {"config_hash": state["config_hash"], "rate": 1.2, "previous_rate": state["tts"]["google_rate"],
            "voice": state["tts"]["google_voice"]}
    before = settings.read_bytes()
    for digit, action in (("a", "preview_google_rate"), ("b", "save_google_rate"), ("c", "save_google_rate")):
        _queue(worker, digit * 32, {**base, "action": action})
        worker.run_once()
        status = json.loads((worker.status_directory / (digit * 32 + ".json")).read_text())
        if digit == "a":
            assert status["code"] == "hoerprobe_bereit"
            assert (worker.runtime_path / "audio" / ("google-" + digit*32 + ".wav")).is_file()
            assert settings.read_bytes() == before
        else:
            assert status["code"] == ("einstellungen_aktuell" if digit == "b" else "auftrag_abgelehnt")
    assert settings.read_bytes() == before
    saved = load_config(app_config.source)
    assert saved.tts.google_rate == 1.2
    speech = PromptGenerator(saved)._google_command("Praxis", tmp_path / "out.wav")
    assert speech[speech.index("--speaking-rate") + 1] == "1.2"
    assert settings.stat().st_mode & 0o777 == 0o600
    assert len(seen) == 1 and seen[0][seen[0].index("--speaking-rate") + 1] == "1.2"
    assert "synthetic-secret" not in worker.state_path.read_text()
