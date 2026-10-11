from __future__ import annotations

import stat
import tomllib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from kienzlefon import middleware_setup as setup
from kienzlefon.config import load_config
from kienzlefon.middleware import (
    MiddlewareConfig,
    manager_inventory,
    provision,
    read_connection,
    write_connection,
)


def source_config(app_config, source: str = "*", server: str = "10.88.0.1", **kwargs):
    options = replace(
        MiddlewareConfig(),
        enabled=True,
        source_ip=source,
        server_ip=server,
        **kwargs,
    )
    return replace(app_config, middleware=options)


@pytest.mark.parametrize(
    ("raw", "source", "server", "all_sources"),
    [
        ({"aktiv": True, "quell_ip": "*", "server_ip": "10.88.0.1"}, "*", "10.88.0.1", True),
        (
            {"aktiv": True, "quell_ip": "192.0.2.19", "server_ip": "192.0.2.1"},
            "192.0.2.19",
            "192.0.2.1",
            False,
        ),
        ({"aktiv": True, "quell_ip": "*", "server_ip": "fd00::1"}, "*", "fd00::1", True),
    ],
)
def test_source_parsing_accepts_star_or_one_exact_address(raw, source, server, all_sources):
    parsed = MiddlewareConfig.parse(raw)

    assert parsed.source_ip == source
    assert parsed.server_ip == server
    assert parsed.all_sources is all_sources


@pytest.mark.parametrize(
    "raw",
    [
        {"quell_ip": "**", "server_ip": "10.88.0.1"},
        {"quell_ip": "10.88.0.0/24", "server_ip": "10.88.0.1"},
        {"quell_ip": "*", "server_ip": "0.0.0.0"},
        {"quell_ip": "*", "server_ip": "::"},
        {"quell_ip": "*", "server_ip": "224.0.0.1"},
        {"quell_ip": "*", "server_ip": "255.255.255.255"},
        {"quell_ip": "*", "server_ip": "not-an-address"},
        {"quell_ip": "192.0.2.19", "server_ip": "fd00::1"},
    ],
)
def test_source_parsing_rejects_non_exact_source_and_invalid_server(raw):
    with pytest.raises(ValueError):
        MiddlewareConfig.parse(raw)


@pytest.mark.parametrize(
    ("server", "permit", "other_family"),
    [
        ("10.88.0.1", "permit=0.0.0.0/0", "permit=::/0"),
        ("fd00::1", "permit=::/0", "permit=0.0.0.0/0"),
    ],
)
def test_all_sources_acl_opens_only_listener_address_family(
    app_config, tmp_path, server, permit, other_family
):
    config = source_config(app_config, server=server)

    export = provision(config, tmp_path / "asterisk")
    managed = (tmp_path / "asterisk/manager_kienzlefon_middleware.conf").read_text()

    assert "deny=0.0.0.0/0" in managed
    assert "deny=::/0" in managed
    assert permit in managed
    assert other_family not in managed
    connection = tomllib.loads(export.read_text())
    assert connection["schema_version"] == 1
    assert connection["allowed_source_ip"] == "*"
    assert connection["ami"]["host"] == server


def test_all_sources_create_repeat_and_return_to_exact_source_preserve_state(app_config, tmp_path):
    etc = tmp_path / "asterisk"
    etc.mkdir()
    manager = etc / "manager.conf"
    original = (
        "[general]\n"
        "enabled=yes\n"
        "bindaddr=10.88.0.1\n"
        "port=5038\n"
        "[existing-monitor]\n"
        "secret=foreign\n"
        "read=call\n"
    )
    manager.write_text(original)
    config = source_config(app_config)

    export = provision(config, etc)
    first = tomllib.loads(export.read_text())
    first_manager = manager.read_text()
    first_managed = (etc / "manager_kienzlefon_middleware.conf").read_text()
    provision(config, etc)

    assert manager.read_text() == first_manager
    assert (etc / "manager_kienzlefon_middleware.conf").read_text() == first_managed
    assert tomllib.loads(export.read_text())["ami"]["secret"] == first["ami"]["secret"]
    assert original.rstrip() in first_manager
    assert manager_inventory(manager)[1] == {"existing-monitor"}
    assert stat.S_IMODE(export.stat().st_mode) == 0o600
    assert stat.S_IMODE((app_config.source.parent / "middleware-secret").stat().st_mode) == 0o600
    assert stat.S_IMODE((etc / "manager_kienzlefon_middleware.conf").stat().st_mode) == 0o640

    exact = replace(config, middleware=replace(config.middleware, source_ip="10.88.0.9"))
    provision(exact, etc)
    switched = tomllib.loads(export.read_text())
    switched_managed = (etc / "manager_kienzlefon_middleware.conf").read_text()

    assert switched["allowed_source_ip"] == "10.88.0.9"
    assert switched["ami"]["secret"] == first["ami"]["secret"]
    assert "permit=10.88.0.9/32" in switched_managed
    assert "permit=0.0.0.0/0" not in switched_managed
    assert original.rstrip() in manager.read_text()


@pytest.mark.parametrize(
    "manager_text",
    [
        "[general]\nenabled=yes\nbindaddr=0.0.0.0\nport=5038\n",
        "[general]\nenabled=yes\nbindaddr=10.88.0.2\nport=5038\n",
        (
            "[general]\nenabled=yes\nbindaddr=10.88.0.1\nport=5038\n"
            "tlsenable=yes\ntlsbindaddr=0.0.0.0:5039\n"
        ),
        (
            "[general]\nenabled=yes\nbindaddr=10.88.0.1\nport=5038\n"
            "tlsenable=yes\ntlsbindaddr=10.88.0.2:5039\n"
        ),
        "[general]\nenabled=yes\nbindaddr=10.88.0.1\nport=5038\nwebenabled=yes\n",
        "[general]\nenabled=no\nbindaddr=0.0.0.0\n[foreign-user]\nsecret=x\n",
    ],
)
def test_all_sources_listener_conflicts_fail_before_any_file_is_written(
    app_config, tmp_path, manager_text
):
    etc = tmp_path / "asterisk"
    etc.mkdir()
    manager = etc / "manager.conf"
    manager.write_text(manager_text)

    with pytest.raises(ValueError):
        provision(source_config(app_config), etc)

    assert manager.read_text() == manager_text
    assert not (etc / "manager_kienzlefon_middleware.conf").exists()
    assert not (app_config.source.parent / "middleware-secret").exists()
    assert not (app_config.source.parent / "middleware-connection.toml").exists()


@pytest.mark.parametrize("transport", ["tcp", "tls"])
def test_all_sources_accepts_exact_tcp_and_inherited_tls_binding(
    app_config, tmp_path, transport
):
    etc = tmp_path / "asterisk"
    etc.mkdir()
    manager = etc / "manager.conf"
    manager.write_text(
        "[general]\n"
        "enabled=yes\n"
        "bindaddr=10.88.0.1\n"
        "port=5038\n"
        "tlsenable=yes\n"
        "[foreign-user]\n"
        "secret=x\n"
    )
    port = 5038 if transport == "tcp" else 5039
    config = source_config(app_config, transport=transport, port=port)

    provision(config, etc)

    assert "[foreign-user]" in manager.read_text()
    assert tomllib.loads((app_config.source.parent / "middleware-connection.toml").read_text())[
        "ami"
    ]["transport"] == transport


def test_configure_all_sources_defaults_repeat_and_transitions(app_config, tmp_path, monkeypatch):
    manager = tmp_path / "asterisk/manager.conf"
    manager.parent.mkdir()
    manager.write_text("[general]\n")
    mode = {"value": "all"}
    yes_calls = []
    ask_calls = []
    address_checks = []

    def choose(prompt, default):
        yes_calls.append((mode["value"], prompt, default))
        if prompt.startswith("Middleware-Schnittstelle"):
            return True
        if prompt.startswith("Laeuft die Middleware"):
            return mode["value"] == "local"
        if prompt.startswith("Alle ueber das VPN"):
            return mode["value"] in {"all", "repeat"}
        if prompt.startswith("Namensaufloesung") or prompt.startswith("Click-to-Dial"):
            return False
        return default

    def answer(prompt, default):
        ask_calls.append((mode["value"], prompt, default))
        if prompt.startswith("VPN-IP"):
            return "10.88.0.1"
        if prompt.startswith("Exakte Quell-IP"):
            return "10.88.0.9"
        return default

    def addresses(*args, **kwargs):
        address_checks.append((args, kwargs))
        return '[{"addr_info":[{"local":"127.0.0.1"},{"local":"10.88.0.1"}]}]'

    monkeypatch.setattr(setup, "yes", choose)
    monkeypatch.setattr(setup, "ask", answer)
    monkeypatch.setattr(setup, "application_available", lambda name: True)
    monkeypatch.setattr(setup.subprocess, "check_output", addresses)
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("all-sources configuration must not route via '*'")
    )

    setup.configure(app_config.source, manager.parent)
    configured = load_config(app_config.source).middleware
    assert configured.source_ip == "*"
    assert configured.server_ip == "10.88.0.1"
    assert any(prompt.startswith("VPN-IP") for _, prompt, _ in ask_calls)
    assert not any(prompt.startswith("Exakte Quell-IP") for _, prompt, _ in ask_calls)
    assert len(address_checks) == 1
    all_prompt = next(call for call in yes_calls if call[1].startswith("Alle ueber das VPN"))
    assert all_prompt[2] is False

    mode["value"] = "repeat"
    setup.configure(app_config.source, manager.parent)
    assert load_config(app_config.source).middleware.source_ip == "*"
    repeat_local = [call for call in yes_calls if call[0] == "repeat" and call[1].startswith("Laeuft")]
    repeat_all = [call for call in yes_calls if call[0] == "repeat" and call[1].startswith("Alle")]
    assert repeat_local[-1][2] is False
    assert repeat_all[-1][2] is True

    mode["value"] = "single"
    setup.configure(app_config.source, manager.parent)
    configured = load_config(app_config.source).middleware
    assert configured.source_ip == "10.88.0.9"
    assert configured.server_ip == "10.88.0.1"
    source_prompt = next(
        call for call in ask_calls if call[0] == "single" and call[1].startswith("Exakte Quell-IP")
    )
    assert source_prompt[2] == ""

    mode["value"] = "local"
    setup.configure(app_config.source, manager.parent)
    configured = load_config(app_config.source).middleware
    assert configured.source_ip == "127.0.0.1"
    assert configured.server_ip == "127.0.0.1"
    assert not any(
        call[0] == "local" and call[1].startswith("Alle ueber das VPN") for call in yes_calls
    )


def firewall_rule(source: str) -> list[str]:
    return [
        "allow",
        "proto",
        "tcp",
        "from",
        source,
        "to",
        "10.88.0.1",
        "port",
        "5038",
        "comment",
        "kienzlefon-middleware",
    ]


@pytest.mark.parametrize(
    ("old_source", "new_source", "enabled", "expected_source"),
    [
        ("any", "10.88.0.9", True, "10.88.0.9"),
        ("10.88.0.9", "*", True, "any"),
        ("any", "*", False, None),
    ],
)
def test_firewall_switches_sources_or_disables_only_the_tracked_rule(
    app_config, monkeypatch, old_source, new_source, enabled, expected_source
):
    old_rule = firewall_rule(old_source)
    write_connection(
        app_config.source.parent,
        {"schema_version": 1, "enabled": True, "ufw_rule": old_rule},
    )
    config = source_config(app_config, source=new_source)
    if not enabled:
        config = replace(config, middleware=replace(config.middleware, enabled=False))
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="Status: active\n")

    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/sbin/ufw")
    monkeypatch.setattr(setup.subprocess, "run", run)

    setup.update_firewall(config, {"ufw_rule": old_rule})

    assert calls[0] == ["ufw", "status"]
    expected_rule = firewall_rule(expected_source) if expected_source else None
    if expected_rule:
        assert calls[1] == ["ufw", *expected_rule]
    assert calls[-1] == ["ufw", "--force", "delete", *old_rule]
    assert read_connection(app_config.source.parent).get("ufw_rule") == expected_rule


@pytest.mark.parametrize("ufw_available", [False, True])
def test_firewall_unavailable_or_inactive_retains_tracked_any_rule(
    app_config, monkeypatch, ufw_available
):
    old_rule = firewall_rule("any")
    write_connection(
        app_config.source.parent,
        {"schema_version": 1, "enabled": True, "ufw_rule": old_rule},
    )
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="Status: inactive\n")

    monkeypatch.setattr(
        setup.shutil, "which", lambda name: "/usr/sbin/ufw" if ufw_available else None
    )
    monkeypatch.setattr(setup.subprocess, "run", run)

    setup.update_firewall(source_config(app_config), {"ufw_rule": old_rule})

    assert calls == ([['ufw', 'status']] if ufw_available else [])
    assert read_connection(app_config.source.parent)["ufw_rule"] == old_rule


@pytest.mark.parametrize(("old_source", "new_source"), [("10.88.0.9", "*"), ("*", "10.88.0.9")])
def test_install_disconnects_existing_session_when_source_policy_changes(
    app_config, tmp_path, monkeypatch, old_source, new_source
):
    options = source_config(app_config, source=new_source).middleware
    setup.save_options(app_config.source, options)
    etc = tmp_path / "asterisk"
    etc.mkdir()
    (etc / "manager.conf").write_text(
        "[general]\n"
        "enabled=yes\n"
        "bindaddr=10.88.0.1\n"
        "port=5038\n"
        "[foreign-user]\n"
        "secret=foreign\n"
    )
    write_connection(
        app_config.source.parent,
        {
            "schema_version": 1,
            "enabled": True,
            "allowed_source_ip": old_source,
            "ami": {
                "host": "10.88.0.1",
                "port": 5038,
                "transport": "tcp",
                "username": "kienzlefon-middleware",
                "secret": "a" * 40,
                "events": "on",
            },
        },
    )
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        command = args[-1]
        if command == "manager show connected":
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "Username IP Address Start Elapsed FileDes HttpCnt ReadPerms WritePerms\n"
                    "kienzlefon-midd 10.88.0.9 1 2 77 0 31 31\n"
                    "foreign-user 10.88.0.8 1 2 88 0 31 31\n"
                ),
            )
        if command == "manager show settings":
            return SimpleNamespace(returncode=0, stdout="Manager (AMI): Yes\n")
        return SimpleNamespace(returncode=0, stdout="")

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    socket_calls = []

    def connect(address, timeout):
        socket_calls.append((address, timeout))
        return Connection()

    monkeypatch.setattr(setup, "application_available", lambda name: False)
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup.subprocess, "run", run)
    monkeypatch.setattr(setup.socket, "create_connection", connect)

    setup.install(app_config.source, etc)

    assert ["asterisk", "-rx", "manager reload"] in commands
    assert ["asterisk", "-rx", "manager show connected"] in commands
    assert ["asterisk", "-rx", "manager kick session 77"] in commands
    assert ["asterisk", "-rx", "manager show settings"] in commands
    assert ["asterisk", "-rx", "manager kick session 88"] not in commands
    assert not any("restart" in " ".join(command).lower() for command in commands)
    assert not any("sip" in " ".join(command).lower() for command in commands)
    assert socket_calls == [(('10.88.0.1', 5038), 5)]
    assert read_connection(app_config.source.parent)["allowed_source_ip"] == new_source
