from __future__ import annotations

import subprocess
import sys
import tomllib
from dataclasses import replace
from functools import partial
from io import StringIO
from pathlib import Path

import pytest

from kienzlefon import asterisk, cli, transfer_setup
from kienzlefon.agi import AgiChannel
from kienzlefon.dialing import decide_number
from kienzlefon.middleware import provision


@pytest.fixture
def transfer_config(app_config):
    return replace(app_config, middleware=replace(app_config.middleware, enabled=True,
                   source_ip="10.0.83.120", server_ip="10.88.0.1", extensions=("201", "299")))


@pytest.fixture
def asterisk_etc(tmp_path):
    etc = tmp_path / "asterisk"
    etc.mkdir()
    for name in ("pjsip.conf", "extensions.conf", "queues.conf"):
        (etc / name).write_text("[general]\n")
    (etc / "features.conf").write_text(
        '[general]\natxferabort=*6\natxfercomplete=*7\natxferdropcall=no\n'
        'atxfercallbackretries=3\n[featuremap]\natxfer=*8\n')
    (etc / "queues-kfx.conf").write_text("[praxis]\nmember => PJSIP/201,0\n")
    (etc / "extensions-kfx-telefonie.conf").write_text("""[kfx-phone-in]
 same => n(accepted),Goto(kfx-phone-queue,s,1)
[kfx-phone-queue]
exten => s,1,NoOp(KienzleFax Telefoniewarteschlange)
 same => n,Queue(praxis,r,,kienzlefon/pharmacy_agent)
[kfx-phone-local]
exten => _X.,1,NoOp(KienzleFax Telefonie ausgehend)
 same => n(dial),Set(CALLERID(num)=4923311234)
 same => n,Dial(PJSIP/${EXTEN}@kfx-phone-in-endpoint,120)
""")
    return etc


def config_files(etc):
    return {file.name: file.read_bytes() for file in etc.glob("*.conf")}


def test_update_repeat_disable_keeps_features_and_manager(transfer_config, asterisk_etc):
    etc = asterisk_etc
    provision(transfer_config, etc)
    before = config_files(etc)
    secret = (transfer_config.source.parent / "middleware-secret").read_bytes()
    asterisk.install_asterisk_config(transfer_config, etc)
    first = config_files(etc)
    assert first["features.conf"].startswith(before["features.conf"])
    rendered = first["extensions-kienzlefon.conf"].decode()
    assert "Set(FEATUREMAP(atxfer)=*8)" in rendered
    assert "Set(FEATURE(atxferabort)=*6)" in rendered
    assert "Set(FEATURE(atxfercomplete)=*7)" in rendered
    assert "FEATURE(atxferdropcall)" not in rendered
    queue = first["extensions-kfx-telefonie.conf"].decode()
    assert "kienzlefon-transfer-caller" in queue
    assert "b(kienzlefon-transfer-prepare^s^1),,kienzlefon/pharmacy_agent" in queue
    assert first["manager.conf"] == before["manager.conf"]
    assert first["manager_kienzlefon_middleware.conf"] == before["manager_kienzlefon_middleware.conf"]
    asterisk.install_asterisk_config(transfer_config, etc)
    assert config_files(etc) == first
    provision(transfer_config, etc)
    assert (transfer_config.source.parent / "middleware-secret").read_bytes() == secret
    assert (etc / "manager_kienzlefon_middleware.conf").read_bytes() == before["manager_kienzlefon_middleware.conf"]
    exported = tomllib.loads((transfer_config.source.parent / "middleware-connection.toml").read_text())
    assert exported["transfer"] == {"enabled": True, "context": "kienzlefon-transfer",
                                    "extensions": ["201", "299"], "progress_schema_version": 1}
    disabled = replace(transfer_config, middleware=replace(transfer_config.middleware, enabled=False))
    asterisk.install_asterisk_config(disabled, etc)
    phone = (etc / "extensions-kfx-telefonie.conf").read_text()
    assert "kienzlefon transfer call" not in phone
    assert "Queue(praxis,r,,kienzlefon/pharmacy_agent)" in phone
    assert "KF_TRANSFER_READY" not in (etc / "extensions-kienzlefon.conf").read_text()
    assert (etc / "features.conf").read_bytes() == first["features.conf"]
    provision(disabled, etc)
    assert not tomllib.loads((transfer_config.source.parent / "middleware-connection.toml").read_text())["transfer"]["enabled"]


@pytest.mark.parametrize("bad", ["features", "public-include", "timed-include", "duplicate-context",
                                 "dynamic-options", "late-validation"])
def test_invalid_plan_does_not_change_any_config(transfer_config, asterisk_etc, monkeypatch, bad):
    etc = asterisk_etc
    if bad == "features":
        (etc / "features.conf").write_text("[general]\natxferabort=*1\natxfercomplete=*1\n")
    if bad == "public-include":
        (etc / "extensions.conf").write_text("[incoming]\ninclude => kienzlefon-transfer\n")
    if bad == "timed-include":
        (etc / "extensions.conf").write_text("[incoming]\ninclude => kienzlefon-transfer,9:00-17:00,mon-fri,*,*\n")
    if bad == "duplicate-context":
        (etc / "extensions.conf").write_text("[kienzlefon-transfer]\nexten => _.,1,NoOp(unsafe)\n")
    if bad == "dynamic-options":
        path = etc / "extensions-kfx-telefonie.conf"
        path.write_text(path.read_text().replace("Queue(praxis,r,", "Queue(praxis,${UNSAFE},"))
    if bad == "late-validation":
        def reject(*args):
            raise ValueError("simulierte ungueltige Konfiguration")
        monkeypatch.setattr(asterisk, "_validate_transfer_plan", reject)
    before = config_files(etc)
    with pytest.raises((ValueError, asterisk.AsteriskConfigError)):
        asterisk.install_asterisk_config(transfer_config, etc)
    assert config_files(etc) == before
    assert len(list(etc.iterdir())) == len(before)


def successful_cli(command):
    name = command.rsplit(" ", 1)[1]
    if command.startswith("manager show command"):
        return f"[Syntax]\nAction: {name}\nReceive: yes\nPrivilege: call\n"
    if command.startswith("core show function"):
        return f"[Syntax]\n{name}(argument)\n"
    if command.startswith("core show application"):
        return f"[Syntax]\n{name}(...)\n[Arguments]\nb(context^exten^priority)\n"
    return "Feature codes\n"


def completed_cli(command, *, stdout=None, stderr="", returncode=0):
    return subprocess.CompletedProcess(
        ["asterisk", "-rx", command],
        returncode,
        stdout=successful_cli(command) if stdout is None else stdout,
        stderr=stderr,
    )


def test_preflight_is_read_only_and_checks_actions_hooks_and_features(transfer_config, asterisk_etc, monkeypatch):
    commands = []
    def cli(command):
        commands.append(command)
        return successful_cli(command)
    monkeypatch.setattr(transfer_setup, "_cli", cli)
    before = config_files(asterisk_etc)
    transfer_setup.preflight(transfer_config, asterisk_etc)
    assert "manager show command CancelAtxfer" in commands
    assert "manager show command PlayDTMF" in commands
    assert "core show application Queue" in commands
    assert "core show function FEATUREMAP" in commands
    assert config_files(asterisk_etc) == before


def test_preflight_accepts_realistic_dial_help_with_not_registered(
    transfer_config, asterisk_etc, monkeypatch
):
    commands = []
    dial_help = """
\x1b[1;35m  -= Info about Application 'Dial' =- \x1b[0m

[Description]
This application sets DIALSTATUS to CHANUNAVAIL when the endpoint is not registered.
Normal documentation may contain No such context without reporting a CLI failure.

[Syntax]
Dial(Technology/Resource[,timeout[,options]])

[Arguments]
b(context^exten^priority)
"""

    def run(args, **kwargs):
        assert kwargs == {"capture_output": True, "text": True, "timeout": 20, "check": False}
        command = args[2]
        commands.append(command)
        output = dial_help if command == "core show application Dial" else successful_cli(command)
        return completed_cli(command, stdout=output)

    monkeypatch.setattr(subprocess, "run", run)
    transfer_setup.preflight(transfer_config, asterisk_etc)
    assert "core show application Dial" in commands
    assert commands[-1] == "features show"


@pytest.mark.parametrize("missing", ["manager show command Atxfer", "manager show command PlayDTMF",
                                     "core show function FEATURE", "core show application Queue"])
def test_preflight_rejects_missing_capabilities(transfer_config, asterisk_etc, monkeypatch, missing):
    monkeypatch.setattr(transfer_setup, "_cli", lambda command: "" if command == missing else successful_cli(command))
    with pytest.raises(ValueError):
        transfer_setup.preflight(transfer_config, asterisk_etc)


@pytest.mark.parametrize("output,code", [
    ("No such command 'manager show command Atxfer'", 0),
    ("Unable to connect to remote asterisk (does /run/asterisk/asterisk.ctl exist?)", 0),
    ("Your application(s) is (are) not registered", 0),
    ("No function by that name registered.", 0),
    ("There is no existence of 'missing' context", 0),
    ("failure", 1),
])
def test_cli_detects_asterisk_errors_even_with_exit_zero(monkeypatch, output, code):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, code, stdout=output, stderr=""))
    with pytest.raises(ValueError, match="Asterisk-Vorpruefung fehlgeschlagen"):
        transfer_setup._cli("manager show command Atxfer")


@pytest.mark.parametrize("output", [
    "\n\x1b[32mDial(...,b(context^exten^priority))\x1b[0m\nendpoint is not registered\n",
    "[Description]\nA missing target can report No such application during a call.\n",
    "[Description]\nThe endpoint is not registered, so Dial sets CHANUNAVAIL.\n",
])
def test_cli_allows_normal_documentation_and_strips_ansi(monkeypatch, output):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=output, stderr=""),
    )
    assert "\x1b" not in transfer_setup._cli("core show application Dial")


def test_cli_error_diagnostic_is_bounded_and_redacts_secrets(monkeypatch):
    output = "secret=super-secret " + "x" * 300
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 2, stdout="", stderr=output),
    )
    with pytest.raises(ValueError) as raised:
        transfer_setup._cli("features show")
    message = str(raised.value)
    assert "super-secret" not in message
    assert "Exitcode 2" in message
    assert len(message) < 300


def test_verify_checks_loaded_contexts_and_detects_stale_outbound(transfer_config, asterisk_etc, monkeypatch):
    asterisk.install_asterisk_config(transfer_config, asterisk_etc)
    content = "\n".join(file.read_text() for file in asterisk_etc.glob("extensions*.conf"))
    def cli(command):
        context = command.rsplit(" ", 1)[1]
        return content.split(f"[{context}]\n", 1)[1].split("\n[", 1)[0]
    monkeypatch.setattr(transfer_setup, "_cli", cli)
    transfer_setup.verify(transfer_config)
    content = content.replace("Set(KZF_DIAL_ALLOWED=0)", "NoOp(stale)")
    with pytest.raises(ValueError, match="kienzlefon-outbound"):
        transfer_setup.verify(transfer_config)


def test_disabled_middleware_does_not_require_asterisk(app_config, tmp_path, monkeypatch):
    def unexpected(*args):
        pytest.fail("disabled middleware called Asterisk")
    monkeypatch.setattr(transfer_setup, "_cli", unexpected)
    transfer_setup.preflight(app_config, tmp_path)
    transfer_setup.verify(app_config)


def test_installer_preflight_precedes_manager_reload_and_verify_follows_dialplan_reload():
    installer = Path("kienzlefon-installer.sh").read_text()
    main = installer.split("main(){", 1)[1]
    assert main.index("kienzlefon-transfer-setup\" preflight") < main.index("kienzlefon-middleware\" install")
    configure = installer.split("configure_asterisk(){", 1)[1].split("\n}\n", 1)[0]
    assert configure.index('kienzlefon-asterisk"') < configure.index('"dialplan reload"') < configure.index('kienzlefon-transfer-setup" verify')


@pytest.mark.parametrize("number", ["004923311234567", "+4923311234567", "023311234567"])
def test_domestic_numbers_use_same_policy_in_international_notation(app_config, number):
    assert decide_number(app_config.dial_rules, number).normalized == "4923311234567"
    assert decide_number(app_config.dial_rules, number).allowed


@pytest.mark.parametrize("number", ["00441234567890", "+441234567890", "0033123456789"])
def test_foreign_number_keeps_country_and_block_policy_across_two_checks(app_config, number):
    rules = app_config.dial_rules
    assert not decide_number(rules, number).allowed
    rules = replace(rules, block_international=False)
    normalized = decide_number(rules, number).normalized
    assert normalized == ("00" + number[1:] if number.startswith("+") else number)
    assert decide_number(rules, normalized).normalized == normalized


@pytest.mark.parametrize("number", ["0900123456", "0049900123456", "+49900123456"])
def test_domestic_premium_blocks_survive_international_notation(app_config, number):
    assert not decide_number(app_config.dial_rules, number).allowed


@pytest.mark.parametrize("disconnect", [False, True])
def test_common_outbound_agi_releases_only_after_number_and_callerid(app_config, monkeypatch, disconnect):
    replies = '200 result=1\n' * 2 + (
        '511 Command Not Permitted on a dead channel\n' if disconnect else
        '200 result=1 (4923319999)\n200 result=1\n200 result=1\n')
    stdin = StringIO('agi_request: choice\nagi_callerid: 0044123456789\n\n' + replies)
    stdout = StringIO()
    monkeypatch.setattr(cli, 'AgiChannel', partial(AgiChannel, stdin, stdout))
    monkeypatch.setattr(cli, '_load', lambda path: app_config)
    monkeypatch.setattr(cli, 'audit_decision', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['kienzlefon-wahlpruefung', '--number', '004923311234567'])
    cli.dial_main()
    commands = stdout.getvalue().splitlines()
    if disconnect:
        assert not any('KZF_DIAL_ALLOWED "1"' in command for command in commands)
    else:
        assert commands[-3:] == ['GET VARIABLE KZF_OUT_CALLERID',
                                 'SET VARIABLE KZF_DIAL_CALLERID "4923319999"',
                                 'SET VARIABLE KZF_DIAL_ALLOWED "1"']
        assert 'SET VARIABLE KZF_DIAL_NUMBER "4923311234567"' in commands
