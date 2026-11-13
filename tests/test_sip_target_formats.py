"""Provider-facing SIP target formats must not change dialing authorization."""
from dataclasses import replace

import pytest

from kienzlefon.asterisk import render_extensions
from kienzlefon.config import ConfigError, load_config
from kienzlefon.dialing import decide_number, format_sip_target


def _rules(app_config):
    return replace(
        app_config.dial_rules,
        sip_target_formats={"kfx-phone-in-endpoint": "e164_plus"},
    )


def test_default_preserves_existing_format(app_config):
    rules = app_config.dial_rules
    assert rules.sip_target_formats == {}
    decision = decide_number(rules, "017612345678")
    assert format_sip_target(rules, decision, "kfx-phone-in-endpoint") == "4917612345678"


@pytest.mark.parametrize(
    "dialed",
    ["017612345678", "+4917612345678", "004917612345678", "4917612345678"],
)
def test_plus_format_is_specific_to_the_outbound_endpoint(app_config, dialed):
    rules = _rules(app_config)
    decision = decide_number(rules, dialed)
    assert decision.allowed
    assert decision.normalized == "4917612345678"
    assert format_sip_target(rules, decision, "kfx-phone-in-endpoint") == "+4917612345678"
    assert format_sip_target(rules, decision, "different-trunk") == "4917612345678"


@pytest.mark.parametrize("dialed", ["110", "112", "116116", "116117"])
def test_emergency_and_service_numbers_keep_their_dialed_format(app_config, dialed):
    rules = _rules(app_config)
    decision = decide_number(rules, dialed)
    assert decision.allowed
    assert format_sip_target(rules, decision, "kfx-phone-in-endpoint") == dialed


def test_foreign_calls_respect_dial_policy(app_config):
    rules = _rules(app_config)
    blocked = decide_number(rules, "+441234567890")
    assert not blocked.allowed
    with pytest.raises(ValueError):
        format_sip_target(rules, blocked, "kfx-phone-in-endpoint")
    permitted = decide_number(replace(rules, block_international=False), "+441234567890")
    assert permitted.allowed
    assert permitted.normalized == "00441234567890"
    assert format_sip_target(rules, permitted, "kfx-phone-in-endpoint") == "+441234567890"


def test_explicit_digits_format_does_not_convert(app_config):
    rules = replace(app_config.dial_rules, sip_target_formats={"trunk": "digits"})
    decision = decide_number(rules, "017612345678")
    assert format_sip_target(rules, decision, "trunk") == "4917612345678"


@pytest.mark.parametrize(
    "replacement",
    [
        'sip_zielformate = { "kfx-phone-in-endpoint" = "unsupported" }',
        'sip_zielformate = { "bad endpoint" = "e164_plus" }',
        'sip_zielformate = ["e164_plus"]',
    ],
)
def test_invalid_format_mapping_is_rejected(app_config, replacement):
    path = app_config.source
    text = path.read_text(encoding="utf-8")
    assert "sip_zielformate = {}" in text
    path.write_text(text.replace("sip_zielformate = {}", replacement), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_shared_outbound_route_uses_provider_specific_target(app_config):
    extensions = render_extensions(app_config)
    assert "Dial(PJSIP/${KZF_SIP_TARGET}@${KZF_OUT_ENDPOINT},120)" in extensions
    assert "Dial(PJSIP/${KZF_DIAL_NUMBER}@${KZF_OUT_ENDPOINT},120)" not in extensions
