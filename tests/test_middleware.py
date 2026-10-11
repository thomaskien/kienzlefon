from __future__ import annotations

import json
import stat
from dataclasses import replace

import pytest

from kienzlefon.config import ConfigError, StandaloneExtensionConfig, load_config
from kienzlefon.middleware import (
    MiddlewareConfig,
    listener_plan,
    manager_inventory,
    provision,
    telephone_extensions,
)
from kienzlefon.middleware_agi import validate_call
from kienzlefon.middleware_dialplan import render_middleware
from kienzlefon.middleware_setup import save_options


def enabled(app_config, **kwargs):
    return replace(app_config, middleware=replace(MiddlewareConfig(), enabled=True,
                   source_ip="192.168.10.9", server_ip="192.168.10.2", **kwargs))


def test_first_install_repeat_disable_and_reenable_preserve_secret_and_other_users(app_config, tmp_path):
    etc = tmp_path / "asterisk"
    etc.mkdir()
    original = "[general]\nenabled=yes\nbindaddr=0.0.0.0\nport=5038\nwebenabled=yes\n[existing]\nsecret=old\nread=call\n"
    (etc / "manager.conf").write_text(original)
    config = enabled(app_config)
    export = provision(config, etc)
    first = json.loads(export.read_text())
    manager = (etc / "manager.conf").read_text()
    assert original.rstrip() in manager
    assert "write=call,originate,reporting" in (etc / "manager_kienzlefon_middleware.conf").read_text()
    assert "permit=192.168.10.9/32" in (etc / "manager_kienzlefon_middleware.conf").read_text()
    assert "write=all" not in (etc / "manager_kienzlefon_middleware.conf").read_text()
    assert len(first["ami"]["secret"]) >= 40
    assert stat.S_IMODE(export.stat().st_mode) == 0o600
    assert stat.S_IMODE((export.parent / "middleware-secret").stat().st_mode) == 0o600
    provision(config, etc)
    assert manager == (etc / "manager.conf").read_text()
    assert json.loads(export.read_text())["ami"]["secret"] == first["ami"]["secret"]
    disabled = replace(config, middleware=replace(config.middleware, enabled=False))
    provision(disabled, etc)
    assert "secret=" not in (etc / "manager_kienzlefon_middleware.conf").read_text()
    assert "[existing]" in (etc / "manager.conf").read_text()
    assert not json.loads(export.read_text())["enabled"]
    provision(config, etc)
    assert json.loads(export.read_text())["ami"]["secret"] == first["ami"]["secret"]
    provision(config, etc, rotate=True)
    assert json.loads(export.read_text())["ami"]["secret"] != first["ami"]["secret"]


def test_new_listener_uses_exact_interface(app_config, tmp_path):
    etc = tmp_path / "asterisk"
    config = enabled(app_config)
    provision(config, etc)
    general, users = manager_inventory(etc / "manager.conf")
    assert general["bindaddr"] == "192.168.10.2"
    assert general["enabled"] == "yes"
    assert not users
    before = (etc / "manager.conf").read_text()
    provision(config, etc)
    assert (etc / "manager.conf").read_text() == before


@pytest.mark.parametrize("content", [
    "[general]\nenabled=yes\nbindaddr=127.0.0.1\n",
    "[general]\nenabled=yes\nbindaddr=0.0.0.0\nport=5040\n",
    "[general]\nenabled=yes\nbindaddr=0.0.0.0\ndisabledevents=VarSet\n",
    "[general]\n[kienzlefon-middleware]\nsecret=existing\n",
])
def test_conflicts_do_not_write_files(app_config, tmp_path, content):
    etc = tmp_path / "asterisk"
    etc.mkdir()
    manager = etc / "manager.conf"
    manager.write_text(content)
    with pytest.raises(ValueError):
        provision(enabled(app_config), etc)
    assert manager.read_text() == content
    assert not (etc / "manager_kienzlefon_middleware.conf").exists()
    assert not (app_config.source.parent / "middleware-secret").exists()


def test_include_collision_and_tls_are_preserved(tmp_path):
    manager = tmp_path / "manager.conf"
    manager.write_text('[general]\nenabled=yes\ntlsenable=yes\ntlsbindaddr=192.168.10.2:5039\ntlsprivatekey=/secret/key.pem\n#include "users.conf"\n')
    (tmp_path / "users.conf").write_text('[phone-monitor]\nread=call\n')
    config = replace(MiddlewareConfig(), enabled=True, transport="tls", server_ip="192.168.10.2", port=5039)
    assert listener_plan(config, manager) == manager.read_text()
    with pytest.raises(ValueError, match="existiert"):
        listener_plan(replace(config, username="phone-monitor"), manager)
    (tmp_path / "users.conf").write_text('#include "manager.conf"\n')
    with pytest.raises(ValueError, match="Zyklische"):
        listener_plan(config, manager)


def test_ipv6_acl(app_config, tmp_path):
    config = replace(app_config, middleware=replace(MiddlewareConfig(), enabled=True, source_ip="::1", server_ip="::1"))
    provision(config, tmp_path / "asterisk")
    text = (tmp_path / "asterisk/manager_kienzlefon_middleware.conf").read_text()
    assert "permit=::1/128" in text
    assert "deny=0.0.0.0/0" in text and "deny=::/0" in text


@pytest.mark.parametrize("value", [
    {"aktiv": "false"}, {"quell_ip": "0.0.0.0"}, {"server_ip": "224.0.0.1"},
    {"benutzer": "x\nwrite=all"}, {"benutzer": "general"}, {"port": 0},
    {"nebenstellen": ["201", "201"]}, {"nebenstellen": ["PJSIP/201"]},
    {"transport": "http"}, {"klingel_timeout_ms": 0},
])
def test_invalid_configuration(value):
    with pytest.raises((ValueError, TypeError)):
        MiddlewareConfig.parse(value)


def test_persistence_and_telephone_inventory(app_config):
    config = replace(app_config, standalone_extensions=(StandaloneExtensionConfig("300", "secret"),),
                     ai_integration=replace(app_config.ai_integration, enabled=True, extension_count=2,
                                            sip_passwords=("a" * 32, "b" * 32)))
    assert set(telephone_extensions(config)) == {"201", "299", "300", "8810", "8811"}
    options = replace(MiddlewareConfig(), enabled=True, extensions=("201", "299"))
    before = app_config.source.read_text()
    save_options(app_config.source, options)
    assert load_config(app_config.source).middleware == options
    save_options(app_config.source, options)
    assert app_config.source.read_text().count("[middleware]") == 1
    assert before.split("[middleware]")[0] in app_config.source.read_text()
    invalid = replace(options, extensions=("777",))
    save_options(app_config.source, invalid)
    with pytest.raises(ConfigError, match="Telefon-Nebenstellen"):
        load_config(app_config.source)


def test_lookup_has_finite_budget_and_is_disabled_without_module(app_config):
    config = enabled(app_config, lookup=True, lookup_available=True)
    text = render_middleware(config)
    assert "BudgetMs: 1000" in text
    assert 'KF_PHONE_REMAINING}<=0]?timeout)' in text
    assert 'WaitForCondition(#,#["#{LOOKUP_DONE}"="1"],${KF_PHONE_REMAINING},0.01)' in text
    assert text.count('STRFTIME(,,%s%3q)}>=${KF_PHONE_DEADLINE}') == 3
    assert text.index('Set(KF_PHONE_LOOKUP_STARTED=1)') < text.index('UserEvent(KienzlefonLookupRequest')
    assert 'Set(CALLERID(num)' not in text
    finished = text.split('UserEvent(KienzlefonLookupFinished', 1)[1].split('\n')[0]
    assert 'NAME' not in finished
    assert 'WaitForCondition' not in render_middleware(enabled(app_config, lookup=True))


def good_request(config):
    return dict(request_id="19fde016-4214-43e6-9cbf-d875e9ff4b59", client_id="empfang-1",
                extension="201", endpoint="201", number="023311234567")


def test_c2d_uses_real_endpoint_and_correct_provider(app_config):
    config = enabled(app_config, click_to_dial=True, extensions=("201", "299"))
    number, provider, callerid = validate_call(config, **good_request(config))
    assert number.isdecimal()
    assert provider == config.asterisk.main_outbound_endpoint
    assert callerid == config.asterisk.main_outbound_number
    direct = replace(config.asterisk.direct_queue, enabled=True, use_for_outbound=True, did="4923319988")
    config = replace(config, asterisk=replace(config.asterisk, direct_queue=direct))
    assert validate_call(config, **good_request(config))[1:] == ("kienzlefon-direct-queue-endpoint", "4923319988")


@pytest.mark.parametrize("field,value", [
    ("endpoint", "299"), ("extension", "777"), ("request_id", "bad"),
    ("number", "201"), ("number", "SIP/user@example.org"), ("number", "0233&Local/x"),
    ("number", "0900123456"), ("client_id", "x\r\nAction: Originate"),
])
def test_c2d_rejects_invalid_or_forbidden_requests(app_config, field, value):
    config = enabled(app_config, click_to_dial=True, extensions=("201",))
    request = good_request(config)
    request[field] = value
    with pytest.raises(ValueError):
        validate_call(config, **request)


def test_revoke_only_own_connected_sessions():
    from kienzlefon.middleware_setup import session_fds
    text = (
        'Username IP Address Start Elapsed FileDes HttpCnt ReadPerms WritePerms\n'
        'kienzlefon-midd 192.168.10.9 123 10 42 0 31 31\n'
        'other 192.168.10.10 123 10 43 0 31 31\n'
    )
    assert session_fds(text, 'kienzlefon-middleware', {'other'}) == [42]
    with pytest.raises(ValueError, match='mehrdeutig'):
        session_fds(text, 'kienzlefon-middleware', {'kienzlefon-middle-other'})


def test_external_main_and_overflow_update_without_internal_hook(tmp_path):
    from kienzlefon.asterisk import _patch_kienzlefax_ivr_route, _patch_middleware_overflow
    path = tmp_path / "extensions.conf"
    original = ("[kfx-phone-in]\n same => n(accepted),Goto(kienzlefon-entry,s,1)\n"
                "[kfx-phone-overflow-in]\n same => n(accepted),Goto(kfx-phone-queue,s,1)\n"
                "[internal]\nexten => 8802,1,Goto(kfx-phone-queue,s,1)\n")
    path.write_text(original)
    for enabled in (True, True, False):
        _patch_kienzlefax_ivr_route(path, enabled)
        _patch_middleware_overflow(path, enabled)
        text = path.read_text()
        assert text.endswith("[internal]\nexten => 8802,1,Goto(kfx-phone-queue,s,1)\n")
        assert ("Goto(kienzlefon-middleware-in,s,1)" in text) == enabled
        assert ("Goto(kienzlefon-middleware-queue-in,s,1)" in text) == enabled
    assert path.read_text() == original


def test_firewall_changes_only_own_rule_and_retains_tracking_when_inactive(app_config, monkeypatch):
    from types import SimpleNamespace

    from kienzlefon import middleware_setup as setup
    config = enabled(app_config)
    export = config.source.parent / "middleware-connection.json"
    export.write_text('{"enabled": true}')
    old = ["allow", "proto", "tcp", "from", "192.168.10.8", "to", "192.168.10.2",
           "port", "5038", "comment", "kienzlefon-middleware"]
    calls = []
    active = False
    monkeypatch.setattr(setup.shutil, "which", lambda _: "/usr/sbin/ufw")
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="Status: active\n" if active else "Status: inactive\n")
    monkeypatch.setattr(setup.subprocess, "run", run)
    setup.update_firewall(config, {"ufw_rule": old})
    assert json.loads(export.read_text())["ufw_rule"] == old
    assert calls == [["ufw", "status"]]
    active = True
    calls.clear()
    setup.update_firewall(config, {"ufw_rule": old})
    assert calls[-1] == ["ufw", "--force", "delete", *old]
    assert calls[1][5] == "192.168.10.9"
    assert json.loads(export.read_text())["ufw_rule"][4] == "192.168.10.9"


def test_configure_asks_each_phone_once_with_ai_default_no(app_config, tmp_path, monkeypatch):
    import tomllib

    from kienzlefon import middleware_setup as setup
    source = app_config.source.read_text().replace('anzahl_nebenstellen = 0', 'anzahl_nebenstellen = 2')
    source = source.replace('[ki_integration]\naktiv = false', '[ki_integration]\naktiv = true')
    source = source.replace('sip_passwoerter = []', 'sip_passwoerter = ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]')
    source = source.replace('[zusaetzliche_nebenstellen]\nnebenstellen = []\npasswoerter = []',
                            '[zusaetzliche_nebenstellen]\nnebenstellen = ["300"]\npasswoerter = ["telephone-password"]')
    app_config.source.write_text(source)
    seen = []
    def yes(prompt, default):
        seen.append((prompt, default))
        return True if prompt.startswith('Middleware-Schnittstelle') else default
    monkeypatch.setattr(setup, 'yes', yes)
    monkeypatch.setattr(setup, 'ask', lambda prompt, default: default)
    monkeypatch.setattr(setup, 'application_available', lambda name: True)
    monkeypatch.setattr(setup.subprocess, 'check_output', lambda *a, **kw: '[{"addr_info":[{"local":"127.0.0.1"}]}]')
    setup.configure(app_config.source, tmp_path / 'asterisk')
    phones = [(p.split(' – ')[0], default) for p, default in seen if 'fuer Click-to-Dial freigeben' in p]
    assert phones == [('201', True), ('299', True), ('300', True), ('8810', False), ('8811', False)]
    assert tomllib.loads(app_config.source.read_text())['middleware']['nebenstellen'] == ['201', '299', '300']
    assert load_config(app_config.source).middleware.lookup_available
