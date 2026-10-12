from __future__ import annotations

import sys
from dataclasses import replace
from functools import partial
from io import StringIO

import pytest

from kienzlefon import transfer_agi
from kienzlefon.agi import AgiChannel
from kienzlefon.config import StandaloneExtensionConfig
from kienzlefon.middleware import MiddlewareConfig

REQUEST_ID = "19fde016-4214-43e6-9cbf-d875e9ff4b59"


def transfer_config(app_config, *, direct_queue: bool = False, direct_red: bool = False):
    queue_route = replace(
        app_config.asterisk.direct_queue,
        enabled=direct_queue,
        use_for_outbound=direct_queue,
        did="4923319201" if direct_queue else "",
    )
    red_route = replace(
        app_config.asterisk.direct_red,
        enabled=direct_red,
        use_for_outbound=direct_red,
        did="4923319299" if direct_red else "",
    )
    return replace(
        app_config,
        middleware=replace(
            MiddlewareConfig(),
            enabled=True,
            extensions=("201", "202", "299", "300", "777", "8800", "8810"),
        ),
        asterisk=replace(
            app_config.asterisk,
            queue_extension_count=2,
            direct_queue=queue_route,
            direct_red=red_route,
        ),
        standalone_extensions=(StandaloneExtensionConfig("300", "test-secret"),),
        ai_integration=replace(
            app_config.ai_integration,
            enabled=True,
            extension_count=1,
            sip_passwords=("a" * 32,),
        ),
        dial_rules=replace(app_config.dial_rules, block_international=False),
    )


def agi_reply(value: str = "", *, present: bool = True) -> str:
    return f"200 result={1 if present else 0}" + (f" ({value})" if present else "") + "\n"


def request_replies(
    *,
    request_id: str = REQUEST_ID,
    client_id: str = "empfang-1",
    extension: str = "201",
    source_uid: str = "1712345678.42",
    mode: str = "attended",
    target_type: str = "external",
    target: str = "023311234567",
) -> list[str]:
    return [
        agi_reply(),
        agi_reply(request_id),
        agi_reply(client_id),
        agi_reply(extension),
        agi_reply(source_uid),
        agi_reply(mode),
        agi_reply(target_type),
        agi_reply(target),
    ]


def run_main(monkeypatch, config, *, dialed: str, replies: list[str]) -> list[str]:
    stdin = StringIO(
        "agi_request: kienzlefon-transfer-check\n"
        f"agi_extension: {dialed}\n"
        "agi_uniqueid: 1712345678.99\n\n"
        + "".join(replies)
    )
    stdout = StringIO()
    monkeypatch.setattr(transfer_agi, "AgiChannel", partial(AgiChannel, stdin, stdout))
    monkeypatch.setattr(transfer_agi, "load_config", lambda path: config)
    monkeypatch.setattr(
        sys,
        "argv",
        ["kienzlefon-transfer-check", "--config", str(config.source)],
    )

    transfer_agi.main()

    return stdout.getvalue().splitlines()


def test_internal_transfer_uses_dialplan_extension_and_releases_last(
    app_config, monkeypatch
) -> None:
    config = transfer_config(app_config)
    replies = request_replies(target_type="internal", target="202") + [agi_reply()] * 4

    commands = run_main(monkeypatch, config, dialed="202", replies=replies)

    assert commands == [
        'SET VARIABLE KF_TRANSFER_ALLOWED "0"',
        "GET VARIABLE KF_TRANSFER_ID",
        "GET VARIABLE KF_TRANSFER_CLIENT",
        "GET VARIABLE KF_TRANSFER_EXTENSION",
        "GET VARIABLE KF_TRANSFER_SOURCE_UID",
        "GET VARIABLE KF_TRANSFER_MODE",
        "GET VARIABLE KF_TRANSFER_TARGET_TYPE",
        "GET VARIABLE KF_TRANSFER_TARGET",
        'SET VARIABLE KF_TRANSFER_NUMBER "202"',
        'SET VARIABLE KZF_OUT_ENDPOINT "202"',
        'SET VARIABLE KZF_OUT_CALLERID ""',
        'SET VARIABLE KF_TRANSFER_ALLOWED "1"',
    ]
    assert not any("CHANNEL(endpoint)" in command for command in commands)


@pytest.mark.parametrize(
    ("extension", "direct_queue", "direct_red", "target", "endpoint", "caller_id"),
    [
        ("201", False, False, "023311234567", "kfx-phone-in-endpoint", "4923311234"),
        ("201", True, False, "023311234567", "kienzlefon-direct-queue-endpoint", "4923319201"),
        ("299", False, True, "023311234567", "kienzlefon-direct-red-endpoint", "4923319299"),
        ("300", False, False, "004923311234567", "kfx-phone-in-endpoint", "4923311234"),
    ],
    ids=["queue-main", "queue-direct", "red-direct", "standalone-original-0049"],
)
def test_external_transfer_selects_employee_provider_and_preserves_original_number(
    app_config,
    monkeypatch,
    extension,
    direct_queue,
    direct_red,
    target,
    endpoint,
    caller_id,
) -> None:
    config = transfer_config(
        app_config, direct_queue=direct_queue, direct_red=direct_red
    )
    replies = request_replies(extension=extension, target=target) + [agi_reply()] * 4

    commands = run_main(monkeypatch, config, dialed=target, replies=replies)

    assert commands[-4:] == [
        f'SET VARIABLE KF_TRANSFER_NUMBER "{target}"',
        f'SET VARIABLE KZF_OUT_ENDPOINT "{endpoint}"',
        f'SET VARIABLE KZF_OUT_CALLERID "{caller_id}"',
        'SET VARIABLE KF_TRANSFER_ALLOWED "1"',
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "missing-or-wrong"),
        ("client_id", ""),
        ("client_id", "x\r\nAction: Originate"),
        ("extension", ""),
        ("source_uid", ""),
        ("source_uid", "uid\r\nVariable: X=1"),
        ("mode", "consult"),
        ("target_type", "sip"),
        ("target", "1"),
        ("target", "123456789012345678901234567890123"),
        ("target", "20&Local/attack"),
    ],
)
def test_invalid_or_missing_metadata_fails_closed(
    app_config, monkeypatch, field, value
) -> None:
    config = transfer_config(app_config)
    values = {field: value}
    replies = request_replies(**values) + [agi_reply()]

    commands = run_main(
        monkeypatch,
        config,
        dialed=value if field == "target" else "023311234567",
        replies=replies,
    )

    assert commands[-1] == 'SET VARIABLE KF_TRANSFER_ALLOWED "0"'
    assert commands.count('SET VARIABLE KF_TRANSFER_ALLOWED "0"') == 2
    assert not any('KF_TRANSFER_ALLOWED "1"' in command for command in commands)
    assert not any("KF_TRANSFER_NUMBER" in command for command in commands)
    assert not any("KZF_OUT_" in command for command in commands)


@pytest.mark.parametrize(
    "reply_index",
    range(1, 8),
    ids=["request-id", "client", "extension", "source-uid", "mode", "target-type", "target"],
)
def test_each_missing_agi_variable_fails_closed(
    app_config, monkeypatch, reply_index
) -> None:
    config = transfer_config(app_config)
    replies = request_replies()
    replies[reply_index] = agi_reply(present=False)
    replies.append(agi_reply())

    commands = run_main(monkeypatch, config, dialed="023311234567", replies=replies)

    assert commands[-1] == 'SET VARIABLE KF_TRANSFER_ALLOWED "0"'
    assert not any('KF_TRANSFER_ALLOWED "1"' in command for command in commands)


def test_dialplan_target_must_match_signed_target(app_config, monkeypatch) -> None:
    config = transfer_config(app_config)
    replies = request_replies(target="023311234567") + [agi_reply()]

    commands = run_main(monkeypatch, config, dialed="023319999999", replies=replies)

    assert commands[-1] == 'SET VARIABLE KF_TRANSFER_ALLOWED "0"'
    assert not any("KF_TRANSFER_NUMBER" in command for command in commands)


@pytest.mark.parametrize(
    ("extension", "target_type", "target"),
    [
        ("201", "internal", "201"),
        ("201", "internal", "777"),
        ("201", "internal", "8800"),
        ("201", "internal", "8810"),
        ("777", "external", "023311234567"),
        ("8800", "external", "023311234567"),
        ("8810", "external", "023311234567"),
        ("201", "external", "0900123456"),
    ],
    ids=[
        "self",
        "announcement-service",
        "ivr-service",
        "ai-target",
        "announcement-source",
        "ivr-source",
        "ai-source",
        "blocked-number",
    ],
)
def test_non_employee_sources_and_forbidden_targets_are_rejected(
    app_config, monkeypatch, extension, target_type, target
) -> None:
    config = transfer_config(app_config)
    replies = request_replies(
        extension=extension, target_type=target_type, target=target
    ) + [agi_reply()]

    commands = run_main(monkeypatch, config, dialed=target, replies=replies)

    assert commands[-1] == 'SET VARIABLE KF_TRANSFER_ALLOWED "0"'
    assert not any('KF_TRANSFER_ALLOWED "1"' in command for command in commands)
    assert not any("KZF_OUT_" in command for command in commands)


def test_middleware_or_employee_permission_must_be_enabled(app_config, monkeypatch) -> None:
    config = transfer_config(app_config)
    config = replace(
        config,
        middleware=replace(config.middleware, enabled=False, extensions=()),
    )
    replies = request_replies() + [agi_reply()]

    commands = run_main(monkeypatch, config, dialed="023311234567", replies=replies)

    assert commands[-1] == 'SET VARIABLE KF_TRANSFER_ALLOWED "0"'
    assert not any('KF_TRANSFER_ALLOWED "1"' in command for command in commands)


@pytest.mark.parametrize(
    "disconnect",
    ["511 Command Not Permitted on a dead channel\n", "200 result=-1\n", ""],
    ids=["dead-channel", "negative-result", "eof"],
)
def test_agi_disconnect_stops_without_late_release(
    app_config, monkeypatch, disconnect
) -> None:
    config = transfer_config(app_config)
    replies = request_replies()[:4] + [disconnect]

    commands = run_main(monkeypatch, config, dialed="023311234567", replies=replies)

    assert commands[-1] == "GET VARIABLE KF_TRANSFER_SOURCE_UID"
    assert not any('KF_TRANSFER_ALLOWED "1"' in command for command in commands)
    assert not any("KZF_OUT_" in command for command in commands)


def test_configuration_failure_fails_closed(monkeypatch) -> None:
    stdin = StringIO("agi_extension: 202\n\n" + agi_reply() + agi_reply())
    stdout = StringIO()
    monkeypatch.setattr(transfer_agi, "AgiChannel", partial(AgiChannel, stdin, stdout))
    monkeypatch.setattr(
        transfer_agi,
        "load_config",
        lambda path: (_ for _ in ()).throw(ValueError("broken config")),
    )
    monkeypatch.setattr(sys, "argv", ["kienzlefon-transfer-check"])

    transfer_agi.main()

    assert stdout.getvalue().splitlines() == [
        'SET VARIABLE KF_TRANSFER_ALLOWED "0"',
        'SET VARIABLE KF_TRANSFER_ALLOWED "0"',
    ]
