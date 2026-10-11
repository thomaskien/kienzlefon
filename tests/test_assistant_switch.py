"""The operation switch stops new AI admissions without tearing down existing calls."""
from dataclasses import replace

import pytest

from kienzlefon import admission
from kienzlefon.asterisk import render_extensions, render_pjsip
from kienzlefon.config import ConfigError, load_config


def configured(config, enabled=True):
    return replace(config, ai_integration=replace(config.ai_integration, enabled=True,
                   assistant_enabled=enabled, extension_count=1, sip_passwords=('s' * 32,)))


def test_disabled_assistant_retains_endpoints_but_uses_classic_flow(app_config):
    active = configured(app_config)
    inactive = configured(app_config, False)
    assert render_pjsip(active) == render_pjsip(inactive)
    assert 'GotoIf($["0"="1"]?admission:classic-menu)' in render_extensions(inactive)
    assert 'GotoIf($["0"="1"]?ai-shortcut:retry-menu)' in render_extensions(inactive)
    assert not inactive.ai_integration.admission_enabled
    assert active.ai_integration.admission_enabled
    assert not replace(active.ai_integration, enabled=False).admission_enabled


@pytest.mark.parametrize('choice', ['any', 'specific'])
def test_disabled_claim_never_contacts_listener_and_clears_stale_lease(app_config, monkeypatch, choice):
    config = configured(app_config, False)
    state = {'KZF_AI_ACCEPTED': '1', 'KZF_AI_LEASE_ID': 'stale'}
    class Channel:
        environment = {'agi_uniqueid': 'call-123'}
        def set_variable(self, key, value):
            state[key] = value
    monkeypatch.setattr(admission, 'load_config', lambda _: config)
    monkeypatch.setattr(admission, 'AgiChannel', Channel)
    monkeypatch.setattr(admission, 'send_command', lambda *a, **kw: pytest.fail('Disabled claim used network'))
    monkeypatch.setattr('sys.argv', ['admission', '--selection', choice, '--slot-id', 'ai-slot-00'])
    admission.admission_agi_main()
    assert state['KZF_AI_ACCEPTED'] == '0'
    assert state['KZF_AI_REASON'] == 'assistant_disabled'
    assert state['KZF_AI_REQUEST_ID'] == 'call-123'
    assert state['KZF_AI_LEASE_ID'] == state['KZF_AI_SLOT_ID'] == state['KZF_AI_EXTENSION'] == ''


@pytest.mark.parametrize('choice,command', [('release', 'release'), ('call-result', 'consume_call_result')])
def test_existing_calls_can_finish_when_assistant_disabled(app_config, monkeypatch, choice, command):
    config = configured(app_config, False)
    called = []
    class Channel:
        environment = {'agi_uniqueid': 'call-123'}
        def set_variable(self, key, value):
            pass
    monkeypatch.setattr(admission, 'load_config', lambda _: config)
    monkeypatch.setattr(admission, 'AgiChannel', Channel)
    def send(config, message, **kw):
        called.append(message['command'])
        return {'accepted': True, 'execute': False}
    monkeypatch.setattr(admission, 'send_command', send)
    monkeypatch.setattr('sys.argv', ['admission', '--selection', choice, '--lease-id', 'lease-123'])
    admission.admission_agi_main()
    assert called == [command]


def test_assistant_flag_is_strict_and_missing_flag_preserves_previous_behavior(app_config):
    path = app_config.source
    original = path.read_text()
    path.write_text(original.replace('assistent_aktiv = true\n', ''))
    assert load_config(path).ai_integration.assistant_enabled is True
    path.write_text(original.replace('assistent_aktiv = true', 'assistent_aktiv = "false"'))
    with pytest.raises(ConfigError, match='assistent_aktiv'):
        load_config(path)
