from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from kienzlefon import queue_setup
from kienzlefon.prompts import PromptGenerator
from kienzlefon.queue_prompts import QUEUE_PHRASES, phrase_output_paths


def test_preflight_checks_queue_support_even_without_middleware(monkeypatch):
    commands = []
    def cli(command):
        commands.append(command)
        if command == "core show channeltypes":
            return "Local Local Proxy Channel Driver"
        return command.rsplit(" ", 1)[1] + "(arguments)"
    monkeypatch.setattr(queue_setup, "_cli", cli)
    queue_setup.preflight()
    assert "core show function QUEUE_GET_CHANNEL" in commands
    assert "core show function IMPORT" in commands
    assert "core show application Dial" in commands


@pytest.mark.parametrize("output", ["", "No such module app_queue.so", "Module reload declined"])
def test_reload_does_not_silently_accept_failure(monkeypatch, output):
    monkeypatch.setattr(queue_setup, "_cli", lambda _: output)
    with pytest.raises(ValueError, match="Neuladen"):
        queue_setup.reload_queues()


def test_audio_report_shows_actual_text_paths_and_rejects_stale_manifest(app_config):
    manifest = {"prompts": {}}
    for name in QUEUE_PHRASES:
        manifest["prompts"][name] = {"text": app_config.prompts.values[name]}
        for path in phrase_output_paths(app_config.paths.prompts, name):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"generated audio")
    path = PromptGenerator(app_config).manifest_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))
    report = "\n".join(queue_setup.audio_report(app_config))
    assert "queue_thereare: Sie sind auf Position" in report
    assert "queue_callswaiting: in der Warteschlange." in report
    assert str(app_config.paths.prompts / "queue" / "queue_thereare") in report
    manifest["prompts"]["queue_thereare"]["text"] = "Vor Ihnen warten noch"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="nicht aktuell"):
        queue_setup.audio_report(app_config)


def test_installer_preflights_before_audio_and_verifies_queue_reload():
    installer = Path("kienzlefon-installer.sh").read_text()
    main = installer.split("main(){", 1)[1]
    assert main.index('kienzlefon-transfer-setup" preflight') < main.index("install_models_and_prompts")
    assert main.index('kienzlefon-queue-setup" preflight') < main.index("install_models_and_prompts")
    configure = installer.split("configure_asterisk(){", 1)[1].split("\n}\n", 1)[0]
    assert configure.index('kienzlefon-queue-setup" reload') < configure.index('kienzlefon-queue-setup" verify')
    assert 'module reload app_queue.so" || true' not in installer
    assert '"Wartemusik von Johannes Plachetka installieren?"' in installer


@pytest.mark.parametrize("fault", ["", "penalty", "ringinuse", "weight", "rules", "duplicate", "extra"])
def test_verify_loaded_queue_topology(app_config, monkeypatch, fault):
    config = replace(app_config, asterisk=replace(app_config.asterisk, queue_extension_count=3),
                     special_queue=replace(app_config.special_queue, weight=80))
    def cli(command):
        if command.startswith("dialplan show"):
            return "kienzlefon-queue-dispatch enter de_kienzlefon KF_QUEUE_RING_SECONDS Dial(PJSIP/"
        if command.startswith("queue show rules"):
            rules = "Rule: kienzlefon-progressive\n" + "\n".join(
                f"After {i * 20 - (0 if fault == 'rules' else 1)} seconds, "
                "adjust QUEUE_MAX_PENALTY by 0, adjust QUEUE_MIN_PENALTY by 0 and "
                f"adjust QUEUE_RAISE_PENALTY to {i}" for i in (1, 2))
            return rules * (2 if fault == "duplicate" else 1) + ("\nAfter 1 seconds, old rule" if fault == "extra" else "")
        normal = command.endswith("praxis")
        weight = 0 if normal or fault == "weight" else config.special_queue.weight
        result = f"in 'ringall' strategy W:{weight}, C:0\n"
        for i in range(3):
            penalty = i if normal and fault != "penalty" else 0
            result += (f"Local/{201+i}@kienzlefon-queue-member with penalty {penalty} "
                       f"(ringinuse {'enabled' if fault == 'ringinuse' else 'disabled'})\n")
        return result
    monkeypatch.setattr(queue_setup, "_cli", cli)
    monkeypatch.setattr(queue_setup, "practice_timing", lambda *_: (19, 1))
    monkeypatch.setattr(queue_setup, "audio_report", lambda _: [])
    if fault:
        with pytest.raises(ValueError):
            queue_setup.verify(config)
    else:
        queue_setup.verify(config)
