from __future__ import annotations

import sys
from dataclasses import replace
from functools import partial
from io import StringIO

import pytest

from kienzlefon import queue_dispatch as dispatch
from kienzlefon.agi import AgiChannel
from kienzlefon.asterisk import render_extensions, render_queues
from kienzlefon.queue_dialplan import (
    decorate_entries,
    decorate_members,
    practice_timing,
    render_rules,
    unwrap,
    validate_rules_include,
)
from kienzlefon.queue_dispatch import WaitingCall, ring_seconds


@pytest.fixture
def app_config(app_config):
    return replace(app_config, asterisk=replace(app_config.asterisk, queue_extension_count=3))


def test_two_arrivals_release_second_phone_before_oldest_second_cycle():
    first = WaitingCall("PJSIP/provider-a", 100)
    second = WaitingCall("PJSIP/provider-b", 102)
    first_timeout = ring_seconds(now=100.2, caller=first, head=first, ring=19, retry=1)
    second_timeout = ring_seconds(now=102.2, caller=second, head=first, ring=19, retry=1)
    assert first_timeout > 0 and second_timeout > 0
    assert 100.2 + first_timeout < 119
    assert 102.2 + second_timeout < 119
    assert ring_seconds(now=119.2, caller=first, head=first, ring=19, retry=1) == 0
    assert ring_seconds(now=120.2, caller=first, head=first, ring=19, retry=1) > 0
    assert ring_seconds(now=120.2, caller=second, head=first, ring=19, retry=1) == 0
    assert ring_seconds(now=140.2, caller=second, head=first, ring=19, retry=1) == 0
    # Native Queue removes an answered (or abandoned) head. B can immediately
    # receive an offer in its own current cycle; no need to end A's conversation.
    assert ring_seconds(now=125, caller=second, head=second, ring=19, retry=1) > 0


@pytest.mark.parametrize("now", [118.999, 119, 119.999, 120, 139, 140])
def test_no_younger_offer_can_overlap_a_cycle_boundary(now):
    first = WaitingCall("A", 100)
    second = WaitingCall("B", 102)
    timeout = ring_seconds(now=now, caller=second, head=first, ring=19, retry=1)
    assert timeout == 0 or now + timeout <= 119


def test_head_order_follows_queue_priority_not_oldest_timestamp():
    normal = WaitingCall("normal", 100)
    pharmacy = WaitingCall("pharmacy", 110)
    assert ring_seconds(now=131, caller=normal, head=pharmacy, ring=19, retry=1) == 0
    assert ring_seconds(now=131, caller=pharmacy, head=pharmacy, ring=19, retry=1) > 0


@pytest.mark.parametrize("entered", [float("nan"), float("inf"), float("-inf")])
def test_reject_nonfinite_clocks(entered):
    with pytest.raises(ValueError):
        ring_seconds(now=100, caller=WaitingCall("A", entered),
                     head=WaitingCall("A", entered), ring=19, retry=1)


def test_agI_offer_uses_actual_queue_head_and_all_agi_responses(app_config, monkeypatch):
    answers = ["praxis", "PJSIP/provider-b", "102", "19", "1", "",
               "PJSIP/provider-a", "100", "PJSIP/provider-a"]
    responses = "200 result=1\n" + "".join(f"200 result=1 ({value})\n" for value in answers)
    responses += "200 result=1\n"
    stdin = StringIO("agi_channel: Local/202@kienzlefon-queue-member-0001;2\n\n" + responses)
    stdout = StringIO()
    monkeypatch.setattr(dispatch, "AgiChannel", partial(AgiChannel, stdin, stdout))
    monkeypatch.setattr(dispatch, "load_config", lambda path: app_config)
    monkeypatch.setattr(dispatch.time, "time", lambda: 102.2)
    monkeypatch.setattr(sys, "argv", ["queue-dispatch", "offer", "--extension", "202"])
    dispatch.main()
    commands = stdout.getvalue().splitlines()
    assert "GET VARIABLE QUEUE_GET_CHANNEL(praxis,1)" in commands
    assert "GET VARIABLE IMPORT(PJSIP/provider-a,KF_QUEUE_ENTERED)" in commands
    assert commands[-1] == 'SET VARIABLE KF_QUEUE_RING_SECONDS "16"'
    assert not any("Hangup" in value or "TIMEOUT(absolute)" in value for value in commands)


def test_agi_enter_initializes_inherited_metadata_and_native_penalty(app_config, monkeypatch):
    stdin = StringIO("agi_channel: PJSIP/provider-0001\n\n" + "200 result=1\n" * 7)
    stdout = StringIO()
    monkeypatch.setattr(dispatch, "AgiChannel", partial(AgiChannel, stdin, stdout))
    monkeypatch.setattr(dispatch, "load_config", lambda _: app_config)
    monkeypatch.setattr(dispatch.time, "time", lambda: 100.25)
    monkeypatch.setattr(sys, "argv", ["queue-dispatch", "enter", "--queue", "praxis"])
    dispatch.main()
    assert stdout.getvalue().splitlines() == [
        'SET VARIABLE KF_QUEUE_RING_SECONDS "0"',
        'SET VARIABLE QUEUE_RAISE_PENALTY "0"',
        'SET VARIABLE __KF_QUEUE_NAME "praxis"',
        'SET VARIABLE __KF_QUEUE_CALLER "PJSIP/provider-0001"',
        'SET VARIABLE __KF_QUEUE_ENTERED "100.250000"',
        'SET VARIABLE __KF_QUEUE_RING "19"',
        'SET VARIABLE __KF_QUEUE_RETRY "1"',
    ]


class Channel:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def get_variable(self, name):
        self.calls.append(name)
        result = self.values.get(name, "")
        if isinstance(result, list):
            return result.pop(0)
        return result


def offer_values():
    return {"KF_QUEUE_NAME": "praxis", "KF_QUEUE_CALLER": "PJSIP/b",
            "KF_QUEUE_ENTERED": "102", "KF_QUEUE_RING": "19", "KF_QUEUE_RETRY": "1",
            "QUEUE_GET_CHANNEL(praxis,1)": "PJSIP/a", "IMPORT(PJSIP/a,KF_QUEUE_ENTERED)": "100"}


def test_red_queue_blocks_normal_offer_without_hanging_up_any_channel(app_config):
    values = offer_values()
    values[f"QUEUE_GET_CHANNEL({app_config.special_queue.name},1)"] = "PJSIP/red"
    channel = Channel(values)
    assert dispatch.offer(channel, app_config, "202") == 0
    assert "QUEUE_GET_CHANNEL(praxis,1)" not in channel.calls


def test_head_answer_during_snapshot_is_retried(app_config, monkeypatch):
    values = offer_values()
    values["QUEUE_GET_CHANNEL(praxis,1)"] = ["PJSIP/a", "PJSIP/b", "PJSIP/b", "PJSIP/b"]
    values["IMPORT(PJSIP/b,KF_QUEUE_ENTERED)"] = "102"
    monkeypatch.setattr(dispatch.time, "time", lambda: 125)
    assert dispatch.offer(Channel(values), app_config, "202") > 0


def test_missing_old_call_marker_does_not_guess_or_overtake(app_config):
    values = offer_values()
    values.pop("IMPORT(PJSIP/a,KF_QUEUE_ENTERED)")
    with pytest.raises(ValueError, match="Zeitstempel"):
        dispatch.offer(Channel(values), app_config, "202")


def test_queue_member_gate_is_private_preserves_transfer_and_no_call_lifetime(app_config):
    config = replace(app_config, middleware=replace(app_config.middleware, enabled=True,
                                                  extensions=("201", "202", "203")))
    text = render_extensions(config)
    member = text.split("[kienzlefon-queue-member]\n", 1)[1].split("\n[", 1)[0]
    assert "Dial(PJSIP/${EXTEN},${KF_QUEUE_RING_SECONDS}," in member
    assert "t" + "b(kienzlefon-transfer-prepare^s^1)" in member
    assert "TIMEOUT(absolute)" not in member
    assert "SoftHangup" not in member
    assert "include => kienzlefon-queue-member" not in text
    assert "context=kienzlefon-queue-member" not in text
    assert "Set(QUEUE_PRIO=10)" in text and "Set(QUEUE_PRIO=100)" in text
    queue = render_queues(config)
    assert "weight=100" in queue and "ringinuse=no" in queue and "autofill=yes" in queue
    assert "member => Local/201@kienzlefon-queue-member,0,Telefon 201,PJSIP/201" in queue


def test_member_conversion_preserves_penalty_state_and_other_queues(app_config):
    original = ("[praxis]\nstrategy=ringall\nautofill=yes\nringinuse=no\n"
                "member => PJSIP/201,0,Empfang 1,PJSIP/201,no\n"
                "member => PJSIP/202,1,Empfang 2,PJSIP/202,no\n"
                "member => PJSIP/203,2,Empfang 3,PJSIP/203,no\n"
                "[other]\nmember => PJSIP/999,8\n")
    result = decorate_members(original, app_config)
    assert "member => Local/202@kienzlefon-queue-member,1,Empfang 2,PJSIP/202,no" in result
    assert result.endswith("[other]\nmember => PJSIP/999,8\n")
    assert decorate_members(result, app_config) == result


def test_existing_flat_members_get_progressive_penalties_and_real_device_state(app_config):
    original = "[praxis]\n" + "".join(f"member => PJSIP/{n},0,Phone,hint:wrong,yes\n"
                                       for n in (201, 202, 203))
    result = decorate_members(original, app_config)
    for penalty, n in enumerate((201, 202, 203)):
        assert f"member => Local/{n}@kienzlefon-queue-member,{penalty},Phone,PJSIP/{n},no" in result


def test_rules_take_effect_at_second_and_third_cycle_in_asterisk_head_path(app_config):
    rules = render_rules(app_config, (19, 1))
    assert "penaltychange => 19,,,1" in rules
    assert "penaltychange => 39,,,2" in rules
    for elapsed, expected in ((0, 0), (19, 0), (20, 1), (39, 1), (40, 2)):
        active = 0
        for boundary, penalty in ((19, 1), (39, 2)):
            if elapsed > boundary:  # app_queue's head path uses strictly >.
                active = penalty
        assert active == expected
    assert "penaltychange => 30,,,1" in render_rules(app_config, (29, 2))


def test_entry_wrappers_preserve_queue_arguments_and_labels(app_config):
    original = "[kfx-phone-queue]\n same => n(queue),Queue(praxis,rTt,,agent,120,,,,rule,2)\n"
    result = decorate_entries(original, app_config, (29, 2))
    assert "same => n(queue),AGI(" in result
    assert "--ring,29,--retry,2)" in result
    assert "same => n,Queue(praxis,rTt,,agent,120,,,,rule,2)" in result
    assert decorate_entries(result, app_config, (29, 2)) == result
    assert unwrap(result) == original


def test_timing_uses_existing_queue_configuration(app_config, tmp_path):
    path = tmp_path / "queues.conf"
    path.write_text("[praxis]\ntimeout=29\nretry=2\n[other]\ntimeout=99\n")
    assert practice_timing(path, "praxis") == (29, 2)
    path.write_text("[praxis]\ntimeout=0\n")
    with pytest.raises(ValueError):
        practice_timing(path, "praxis")


@pytest.mark.parametrize("extra", ["", "direct", "included", "duplicate", "glob", "cycle"])
def test_rule_include_graph_rejects_collisions_before_publishing(app_config, tmp_path, extra):
    from kienzlefon.asterisk import install_asterisk_config
    planned = {
        "queuerules.conf": '#include "/etc/asterisk/queuerules-kienzlefon.conf"\n',
        "queuerules-kienzlefon.conf": render_rules(app_config, (19, 1)),
    }
    if extra == "direct":
        planned["queuerules.conf"] += "[kienzlefon-progressive]\npenaltychange => 20,,,1\n"
    elif extra == "included":
        planned["queuerules.conf"] += '#include "old.conf"\n'
        (tmp_path / "old.conf").write_text("[kienzlefon-progressive]\npenaltychange => 20,,,1\n")
    elif extra == "duplicate":
        planned["queuerules.conf"] += '#tryinclude <queuerules-kienzlefon.conf>\n'
    elif extra == "glob":
        planned["queuerules.conf"] += '#include "queuerules-kienz*.conf"\n'
    elif extra == "cycle":
        planned["queuerules.conf"] += '#include "queuerules.conf"\n'
    if extra:
        with pytest.raises(ValueError, match="Queue-Regel"):
            validate_rules_include(tmp_path, planned)
    else:
        validate_rules_include(tmp_path, planned)
    # Full installer must reject a foreign rule before publishing any file.
    if extra == "direct":
        for name, text in {
            "queuerules.conf": "[kienzlefon-progressive]\npenaltychange => 20,,,1\n",
            "queues-kfx.conf": "[praxis]\n" + "".join(f"member => PJSIP/{n},0\n" for n in (201, 202, 203)),
            "extensions-kfx-telefonie.conf": (
                "[kfx-phone-in]\n same => n(accepted),Goto(kfx-phone-queue,s,1)\n"
                "[kfx-phone-queue]\nexten => s,1,NoOp(KienzleFax Telefoniewarteschlange)\n"
                " same => n,Queue(praxis,r)\n[kfx-phone-local]\n"
                "exten => _X.,1,NoOp(KienzleFax Telefonie ausgehend)\n"
                " same => n(dial),Set(CALLERID(num)=4923311234)\n"
                " same => n,Dial(PJSIP/${EXTEN}@kfx-phone-in-endpoint,120)\n"
            ),
            "pjsip.conf": "", "extensions.conf": "", "queues.conf": "", "features.conf": "",
        }.items():
            (tmp_path / name).write_text(text)
        before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
        with pytest.raises(ValueError, match="fremd belegt"):
            install_asterisk_config(app_config, tmp_path)
        assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
