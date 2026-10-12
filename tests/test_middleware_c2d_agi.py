from __future__ import annotations

import sys
from dataclasses import replace
from functools import partial
from io import StringIO

import pytest

from kienzlefon import middleware_agi
from kienzlefon.agi import AgiChannel
from kienzlefon.middleware import MiddlewareConfig
from kienzlefon.middleware_dialplan import render_middleware

REQUEST_ID = "19fde016-4214-43e6-9cbf-d875e9ff4b59"


def c2d_config(
    app_config,
    *,
    enabled: bool = True,
    click_to_dial: bool = True,
    direct: bool = False,
):
    route = replace(
        app_config.asterisk.direct_queue,
        enabled=direct,
        use_for_outbound=direct,
        did="4923319988" if direct else "",
    )
    return replace(
        app_config,
        middleware=replace(
            MiddlewareConfig(),
            enabled=enabled,
            click_to_dial=click_to_dial,
            extensions=("202",),
        ),
        asterisk=replace(
            app_config.asterisk,
            queue_extension_count=2,
            direct_queue=route,
        ),
        dial_rules=replace(app_config.dial_rules, block_international=False),
    )


def agi_reply(value: str) -> str:
    return f"200 result=1 ({value})\n"


def run_main(monkeypatch, config, replies: list[str]) -> list[str]:
    stdin = StringIO("agi_request: kienzlefon-c2d-check\n\n" + "".join(replies))
    stdout = StringIO()

    monkeypatch.setattr(
        middleware_agi,
        "AgiChannel",
        partial(AgiChannel, stdin, stdout),
    )
    monkeypatch.setattr(middleware_agi, "load_config", lambda path: config)
    monkeypatch.setattr(
        sys,
        "argv",
        ["kienzlefon-c2d-check", "--config", str(config.source)],
    )
    middleware_agi.main()
    return stdout.getvalue().splitlines()


def complete_replies(*, endpoint: str = "200 result=1 (202)\n", target: str):
    return [
        "200 result=1\n",
        agi_reply(REQUEST_ID),
        agi_reply("empfang-1"),
        agi_reply("202"),
        endpoint,
        agi_reply(target),
    ]


@pytest.mark.parametrize(
    ("target", "direct", "expected_endpoint", "expected_caller_id"),
    [
        ("023311234567", False, "kfx-phone-in-endpoint", "4923311234"),
        (
            "+4923311234567",
            True,
            "kienzlefon-direct-queue-endpoint",
            "4923319988",
        ),
    ],
)
def test_main_allows_matching_endpoint_and_sets_route_last(
    app_config,
    monkeypatch,
    target,
    direct,
    expected_endpoint,
    expected_caller_id,
):
    config = c2d_config(app_config, direct=direct)
    replies = complete_replies(target=target) + ["200 result=1\n"] * 4

    commands = run_main(monkeypatch, config, replies)

    assert commands == [
        'SET VARIABLE KF_C2D_ALLOWED "0"',
        "GET VARIABLE KF_C2D_ID",
        "GET VARIABLE KF_C2D_CLIENT",
        "GET VARIABLE KF_C2D_EXTENSION",
        "GET VARIABLE CHANNEL(endpoint)",
        "GET VARIABLE KF_C2D_TARGET",
        'SET VARIABLE KF_C2D_NUMBER "4923311234567"',
        f'SET VARIABLE KZF_OUT_ENDPOINT "{expected_endpoint}"',
        f'SET VARIABLE KZF_OUT_CALLERID "{expected_caller_id}"',
        'SET VARIABLE KF_C2D_ALLOWED "1"',
    ]
    assert "CHANNEL(pjsip,endpoint)" not in "\n".join(commands)


@pytest.mark.parametrize(
    "endpoint_reply",
    ["200 result=0\n", "200 result=1 ()\n", "200 result=1 (203)\n"],
    ids=["missing", "empty", "different"],
)
def test_main_rejects_missing_empty_or_different_endpoint(
    app_config, monkeypatch, endpoint_reply
):
    config = c2d_config(app_config)
    replies = complete_replies(
        endpoint=endpoint_reply,
        target="023311234567",
    ) + ["200 result=1\n"]

    commands = run_main(monkeypatch, config, replies)

    assert commands[-1] == 'SET VARIABLE KF_C2D_ALLOWED "0"'
    assert commands.count('SET VARIABLE KF_C2D_ALLOWED "0"') == 2
    assert not any("KF_C2D_ALLOWED \"1\"" in command for command in commands)
    assert not any("KF_C2D_NUMBER" in command for command in commands)
    assert not any("KZF_OUT_" in command for command in commands)


def test_main_rejects_unapproved_extension_despite_matching_endpoint(
    app_config, monkeypatch
):
    config = c2d_config(app_config)
    config = replace(
        config,
        middleware=replace(config.middleware, extensions=("201",)),
    )
    replies = complete_replies(target="023311234567") + ["200 result=1\n"]

    commands = run_main(monkeypatch, config, replies)

    assert commands[-1] == 'SET VARIABLE KF_C2D_ALLOWED "0"'
    assert not any("KF_C2D_ALLOWED \"1\"" in command for command in commands)
    assert not any("KZF_OUT_" in command for command in commands)


@pytest.mark.parametrize(
    "endpoint_reply",
    [
        "511 Command Not Permitted on a dead channel\n",
        "200 result=-1\n",
        "",
    ],
    ids=["dead-channel", "negative-result", "eof"],
)
def test_main_treats_endpoint_query_disconnect_as_regular_end(
    app_config, monkeypatch, endpoint_reply
):
    config = c2d_config(app_config)
    replies = complete_replies(
        endpoint=endpoint_reply,
        target="023311234567",
    )[:5]

    commands = run_main(monkeypatch, config, replies)

    assert commands[-1] == "GET VARIABLE CHANNEL(endpoint)"
    assert not any("KF_C2D_ALLOWED \"1\"" in command for command in commands)
    assert not any("KF_C2D_NUMBER" in command for command in commands)
    assert not any("KZF_OUT_" in command for command in commands)


@pytest.mark.parametrize("target", ["12", "123x", "0900123456"])
def test_main_rejects_invalid_or_blocked_target(app_config, monkeypatch, target):
    config = c2d_config(app_config)
    replies = complete_replies(target=target) + ["200 result=1\n"]

    commands = run_main(monkeypatch, config, replies)

    assert commands[-1] == 'SET VARIABLE KF_C2D_ALLOWED "0"'
    assert not any("KF_C2D_ALLOWED \"1\"" in command for command in commands)
    assert not any("KZF_OUT_" in command for command in commands)


@pytest.mark.parametrize(
    ("enabled", "click_to_dial"),
    [(False, True), (True, False)],
    ids=["middleware-disabled", "feature-disabled"],
)
def test_main_rejects_when_click_to_dial_is_disabled(
    app_config, monkeypatch, enabled, click_to_dial
):
    config = c2d_config(
        app_config,
        enabled=enabled,
        click_to_dial=click_to_dial,
    )
    replies = complete_replies(target="023311234567") + ["200 result=1\n"]

    commands = run_main(monkeypatch, config, replies)

    assert commands[-1] == 'SET VARIABLE KF_C2D_ALLOWED "0"'
    assert not any("KF_C2D_ALLOWED \"1\"" in command for command in commands)
    assert not any("KZF_OUT_" in command for command in commands)


def dialplan_blocks(text: str) -> tuple[list[str], list[str]]:
    context = text.split("[kienzlefon-click-to-dial]\n", 1)[1]
    lines = context.splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith("exten =>")]
    blocks = [
        "\n".join(lines[start:stop])
        for start, stop in zip(starts, starts[1:] + [len(lines)])
    ]
    return lines, blocks


@pytest.mark.parametrize("active", [True, False], ids=["active", "inactive"])
def test_generated_c2d_dialplan_has_only_number_entries_and_safe_hangup(
    app_config, active
):
    config = c2d_config(app_config, click_to_dial=active)
    lines, blocks = dialplan_blocks(render_middleware(config))

    assert not any(line.startswith("exten => _.,") for line in lines)
    assert lines[0] == "exten => h,1,NoOp(Kienzlefon Click-to-Dial beendet)"
    assert lines[1].startswith("exten => _XXX,1,")
    assert not any(
        line.startswith(("exten => s,", "exten => i,", "exten => t,"))
        for line in lines
    )

    number_blocks = blocks[1:]
    assert [block.split(",", 2)[1] for block in number_blocks] == ["1"] * 4
    assert [block.split(",", 1)[0] for block in number_blocks] == [
        "exten => _XXX",
        "exten => _XXX.",
        "exten => _+XXX",
        "exten => _+XXX.",
    ]
    flows = [block.split(",", 2)[2] for block in number_blocks]
    assert len(set(flows)) == 1

    if active:
        flow = flows[0]
        allowed_check = 'GotoIf($["${KF_C2D_ALLOWED}"="1"]?approved)'
        assert flow.count("kienzlefon-c2d-check") == 1
        assert flow.index(allowed_check) < flow.index(
            "UserEvent(KienzlefonClickToDialProgress"
        ) < flow.index("Goto(kienzlefon-outbound,${KF_C2D_NUMBER},1)")
    else:
        assert flows == ["Hangup(21)"] * 4
        assert "AGI(" not in "\n".join(lines)
        assert "UserEvent(" not in "\n".join(lines)
        assert "Goto(kienzlefon-outbound" not in "\n".join(lines)
