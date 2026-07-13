# kienzlefon tests
# Version: 1.7
# Changelog:
# - 1.7: Anzeigeformat deutscher und auslaendischer eingehender Rufnummern getestet.
# - 1.3: Freigegebene Normalisierung, Notrufausnahmen und Sperrlisten getestet.

from __future__ import annotations

from dataclasses import replace

from kienzlefon.dialing import decide_number, normalize_incoming_caller_id


def test_german_numbers_are_normalized(app_config) -> None:
    rules = app_config.dial_rules
    assert decide_number(rules, "1234567").normalized == "4923311234567"
    assert decide_number(rules, "023311234567").normalized == "4923311234567"
    assert decide_number(rules, "4923311234567").normalized == "4923311234567"


def test_emergency_exceptions_and_blocked_destinations(app_config) -> None:
    rules = app_config.dial_rules
    for number in ("110", "112", "116116", "116117"):
        decision = decide_number(rules, number)
        assert decision.allowed is True
        assert decision.normalized == number
    for number in ("0900123456", "0137123456", "11833", "0190123456", "0044123456"):
        assert decide_number(rules, number).allowed is False


def test_optional_categories_remain_allowed_by_default(app_config) -> None:
    rules = app_config.dial_rules
    assert decide_number(rules, "0180123456").allowed is True
    assert decide_number(rules, "0700123456").allowed is True
    assert decide_number(rules, "032123456").allowed is True
    assert decide_number(replace(rules, block_0180=True), "0180123456").allowed is False


def test_incoming_caller_ids_are_normalized_for_phone_display() -> None:
    for value in ("492331123456", "+492331123456", "00492331123456"):
        assert normalize_incoming_caller_id(value) == "02331123456"
    for value in ("481234567", "+481234567", "00481234567"):
        assert normalize_incoming_caller_id(value) == "00481234567"
    assert normalize_incoming_caller_id("02331123456") == "02331123456"


def test_incoming_internal_and_anonymous_values_are_unchanged() -> None:
    for value in ("201", "777", "anonymous", "unknown"):
        assert normalize_incoming_caller_id(value, local_extensions=("201", "777")) == value
