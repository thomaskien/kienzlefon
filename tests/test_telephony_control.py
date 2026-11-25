from __future__ import annotations

import hashlib
import http.client
import json
import socketserver
import threading
import time
from dataclasses import replace
from uuid import uuid4

import pytest

from kienzlefon.asterisk import render_extensions, render_queues
from kienzlefon.control_api import ControlServer, ControlService, credentials, principal
from kienzlefon.control_setup import register, render_policy, write_policy
from kienzlefon.queue_dialplan import decorate_members
from kienzlefon.telephony_ami import AmiSettings, AsteriskPlant
from kienzlefon.telephony_control import ControlError, Controller, Journal, QueueInventory, SourceError, parse_command, stamp
from kienzlefon.telephony_live import Identifiers, LiveMonitor, classify
from kienzlefon.telephony_policy import ControlConfig, Membership, RoutingPolicy, policy_for


class Plant:
    def __init__(self):
        self.connected = True
        self.routing_generation = 0
        self.process = "linux:123:456"
        self.members = {"normal": {}, "specialist": {}}
        self.changes = []
        self.readiness = None
        self.lose_reply = False

    def process_key(self):
        return self.process

    def inventory(self, _config):
        if not self.connected:
            raise SourceError("Getrennt")
        return QueueInventory({route: members.copy() for route, members in self.members.items()}, self.routing_generation)

    def ready(self, value):
        self.readiness = value

    def change(self, _config, route, extension, penalty):
        self.changes.append((route, extension, penalty))
        if penalty is None:
            self.members[route].pop(extension)
        else:
            self.members[route][extension] = penalty
        self.routing_generation += 1
        if self.lose_reply:
            self.connected = False
            raise SourceError("Antwort unterbrochen")


@pytest.fixture
def enabled(app_config, tmp_path):
    groups = {"201": {"normal": Membership(True, True, True, True), "specialist": Membership()},
              "202": {"normal": Membership(True, True, True, True, 1),
                      "specialist": Membership(True, True, True, True)}}
    config = replace(app_config,
        control_api=ControlConfig(enabled=True, pbx_id="synthetic-pbx", credentials_file=tmp_path / "credentials.json"),
        asterisk=replace(app_config.asterisk, queue_extension_count=2),
        routing_policy=RoutingPolicy(True, groups),
    )
    return config, Journal(tmp_path / "journal"), Plant()


def command(state, extension, route="normal", *, member=False):
    return parse_command({"request_id": str(uuid4()), "client_id": "empfang-1", "extension": extension,
                          "route": route, "member": member, "expected_revision": f"r1:{state['epoch']}:{state['revision']}",
                          "pbx_epoch": state["epoch"], "expires_at": stamp(time.time() + 25)})


def rejection(code, call):
    with pytest.raises(ControlError) as error:
        call()
    assert error.value.code == code


def test_concurrent_revision_cannot_remove_the_last_member_and_rot_is_independent(enabled):
    config, journal, plant = enabled
    controller = Controller(journal, plant)
    controller.refresh(config)
    state = journal.load()
    first, second = command(state, "201"), command(state, "202")
    assert controller.submit("test", {"empfang-1"}, first)["state"] == "accepted"
    assert controller.submit("test", {"empfang-1"}, second)["state"] == "accepted"
    controller.refresh(config)
    controller.refresh(config)
    assert plant.members == {"normal": {"202": 1}, "specialist": {"202": 0}}
    assert controller.result("test", {"empfang-1"}, first["request_id"])["state"] == "applied"
    assert controller.result("test", {"empfang-1"}, second["request_id"])["error"]["code"] == "revision_conflict"
    rejection("last_member", lambda: controller.submit("test", {"empfang-1"}, command(journal.load(), "202")))


def test_lost_ami_reply_is_reconciled_without_reapplying(enabled):
    config, journal, plant = enabled
    controller = Controller(journal, plant)
    controller.refresh(config)
    plant.changes.clear()
    request = command(journal.load(), "201")
    controller.submit("test", {"empfang-1"}, request)
    plant.lose_reply = True
    controller.refresh(config)
    assert controller.result("test", {"empfang-1"}, request["request_id"])["state"] == "unknown"
    plant.lose_reply = False
    plant.connected = True
    controller = Controller(journal, plant)
    controller.refresh(config)
    assert controller.submit("test", {"empfang-1"}, request)["state"] == "applied"
    assert plant.changes == [("normal", "201", None)]
    rejection("request_id_conflict", lambda: controller.submit("test", {"empfang-1"}, {**request, "member": True}))
    rejection("request_not_found", lambda: controller.result("different", {"empfang-1"}, request["request_id"]))


def test_rights_removal_before_application_and_new_process_reset(enabled):
    config, journal, plant = enabled
    controller = Controller(journal, plant)
    controller.refresh(config)
    request = command(journal.load(), "201")
    controller.submit("test", {"empfang-1"}, request)
    changed = replace(config, routing_policy=replace(config.routing_policy, remote_enabled=False))
    controller.refresh(changed)
    result = controller.result("test", {"empfang-1"}, request["request_id"])
    assert result["state"] == "rejected"
    assert set(plant.members["normal"]) == {"201", "202"}
    controller.refresh(config)
    another = command(journal.load(), "201")
    controller.submit("test", {"empfang-1"}, another)
    controller.refresh(config)
    old_epoch = journal.load()["epoch"]
    assert set(plant.members["normal"]) == {"202"}
    # Asterisk may reload dynamic entries from AstDB. Only the defaults must survive.
    plant.process = "linux:124:999"
    controller.refresh(config)
    assert journal.load()["epoch"] != old_epoch
    assert set(plant.members["normal"]) == {"201", "202"}
    assert controller.result("test", {"empfang-1"}, another["request_id"])["state"] == "applied"


def test_runtime_drift_disables_snapshot_and_is_reconciled(enabled):
    config, journal, plant = enabled
    controller = Controller(journal, plant)
    controller.refresh(config)
    previous = journal.load()
    plant.members["normal"]["201"] = -1
    plant.routing_generation += 1
    assert not controller.view(config, previous["epoch"])[0]["available"]
    controller.refresh(config)
    assert plant.members["normal"]["201"] == 0
    assert journal.load()["revision"] == previous["revision"] + 1


def test_legacy_member_config_migration_and_dialplan_controls(enabled):
    config, _journal, _plant = enabled
    text = "[praxis]\nmember => PJSIP/201\nmember => PJSIP/202\n[other]\nmember => PJSIP/999\n"
    first = decorate_members(text, config)
    assert decorate_members(first, config) == first
    assert [line for line in first.splitlines() if line.startswith("member")] == ["member => PJSIP/999"]
    assert "member =>" not in render_queues(config)
    dialplan = render_extensions(config)
    start = dialplan.partition("[kienzlefon-specialist]\n")[2].partition("\n[")[0]
    if config.ivr.red_enabled:
        assert start.index("Dial(PJSIP/") < start.index("Gosub(kienzlefon-control-ready,s,1)") < start.index("\n same => n,Queue(")
    without_red = render_extensions(replace(config, ivr=replace(config.ivr, red_enabled=False)))
    assert "Dial(PJSIP/" not in without_red.partition("[kienzlefon-specialist]\n")[2].partition("\n[")[0]
    assert len(policy_for(config).defaults()["specialist"]) == 1


def test_live_counts_bridge_phases_and_ignores_child_leg_after_hangup():
    call = str(uuid4())
    channels = {"root": {"channel": "PJSIP/trunk-00000001"},
                "ai": {"channel": "PJSIP/8810-00000002"},
                "human": {"channel": "PJSIP/201-00000003"},
                "L1": {"channel": "Local/201@queue-00000001;1"},
                "L2": {"channel": "Local/201@queue-00000001;2"}}
    marks = {uid: Identifiers(call, uid == "root", "ivr" if uid == "root" else "") for uid in channels}
    assert classify(channels, marks, {}, set(), {"8810"}) == {"waiting": 0, "ivr": 1, "ai": 0}
    assert classify(channels, marks, {"bridge": {"root", "ai"}}, set(), {"8810"})["ai"] == 1
    assert classify(channels, marks, {}, {"root", "L1"}, {"8810"}) == {"waiting": 1, "ivr": 0, "ai": 0}
    assert classify(channels, marks, {"a": {"root", "ai", "L1"}, "b": {"L2", "human"}}, {"root"}, {"8810"}) == {
        "waiting": 0, "ivr": 0, "ai": 0,
    }
    marks["root"] = Identifiers(call, False)
    assert classify(channels, marks, {}, {"L1"}, {"8810"}) == {"waiting": 0, "ivr": 0, "ai": 0}


def test_control_credentials_store_hashes_and_no_other_client_can_use_them(enabled, tmp_path):
    config, _journal, _plant = enabled
    token_path = tmp_path / "first.token"
    register(config, "test-id", ["empfang-1"], token_path)
    token = token_path.read_text().strip()
    assert principal(config.control_api.credentials_file, "Bearer " + token) == ("test-id", {"empfang-1"})
    assert credentials(config.control_api.credentials_file)["test-id"][0] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in config.control_api.credentials_file.read_text()
    rejection("unauthenticated", lambda: principal(config.control_api.credentials_file, "Bearer " + "a" * 64))


def test_policy_toml_round_trip_retains_existing_other_tables(enabled):
    config, journal, plant = enabled
    text = '[testroute]\nk = "bleibt erhalten"\n[routing_policy]\nremote_enabled = false\n[konfig]\nxx = 9\n'
    updated = render_policy(text, config.routing_policy)
    assert '[testroute]\nk = "bleibt erhalten"' in updated and '[konfig]\nxx = 9' in updated
    controller = Controller(journal, plant)
    controller.refresh(config)
    data = config.routing_policy.export()
    data["members"]["202"]["specialist"] = {"eligible": False, "default_member": False,
                                              "can_enable": False, "can_disable": False, "penalty": 0}
    with pytest.raises(ValueError, match="Rufgruppenmitglied"):
        write_policy(config, RoutingPolicy.parse(data), journal.directory)


def test_scope_rotation_revocation_and_legacy_empty_list(enabled, tmp_path):
    from kienzlefon.control_api import encode_credentials

    config, journal, plant = enabled
    token = tmp_path / "practice.token"
    register(config, "middleware", None, token)
    service = ControlService(config, journal, plant)
    service.controller.refresh(config)
    request = command(journal.load(), "201")
    service.controller.submit("middleware", None, request)
    register(config, "middleware", ["limited"], tmp_path / "replacement.token")
    service.controller.refresh(config)
    assert service.controller.result("middleware", None, request["request_id"])["error"]["code"] == "client_forbidden"
    assert "201" in plant.members["normal"]
    register(config, "middleware", None, tmp_path / "rotation.token")
    path = config.control_api.credentials_file
    assert credentials(path)["middleware"][1] == {"limited"}
    path.write_text(encode_credentials({"reader": ("1" * 64, set())}))
    register(config, "reader", None, tmp_path / "reader.token")
    assert credentials(path)["reader"][1] == set()
    with pytest.raises(ValueError):
        register(config, "t2med-counters", None, tmp_path / "bad.token")
    path.write_text(encode_credentials({"t2med-counters": ("1" * 64, {"old-place"})}))
    register(config, "t2med-counters", None, tmp_path / "legacy-rotation.token")
    assert credentials(path)["t2med-counters"][1] == {"old-place"}
    with pytest.raises(ValueError):
        register(config, "t2med-counters", ["another-place"], tmp_path / "denied.token")
    invalid = {"id": "reader", "allowed_clients": None, "token_sha256": "1" * 64}
    for version, identity in ((1, invalid), (2, {**invalid, "id": "t2med-counters"})):
        path.write_text(json.dumps({"schema_version": version, "identities": [identity]}))
        with pytest.raises(ValueError):
            credentials(path)


def test_pair_routing_without_promoting_counter_or_legacy_identity(app_config, tmp_path, monkeypatch):
    from kienzlefon import t2med_counters as pairing
    from kienzlefon.config import load_config
    from kienzlefon.control_setup import enable_local, ensure_credentials
    from kienzlefon.webadmin import _set_toml_value

    source = app_config.source
    path = tmp_path / "credentials.json"
    source.write_text(_set_toml_value(source.read_text(), "control_api", "credentials_file", str(path)))
    enable_local(load_config(source), "praxis-test")
    config = load_config(source)
    ensure_credentials(config)
    monkeypatch.setattr(pairing, "verify_dialplan", lambda _: None)

    def prepare(name, routing_digest=None):
        work = tmp_path / name
        work.mkdir(mode=0o700)
        (work / "fon-info.json").write_text(json.dumps({"pbx_id": "praxis-test", "already_enabled": True}))
        (work / "control.sha256").write_text("c" * 64)
        if routing_digest:
            (work / "routing.sha256").write_text(routing_digest)
            (work / "routing.sha256").chmod(0o600)
        pairing.plan(source, work)
        return work

    pairing.publish(prepare("old-installer"), False)
    before = path.read_bytes()
    assert credentials(path)["t2med-counters"] == ("c" * 64, set())
    work = prepare("new-installer", "d" * 64)
    pairing.publish(work, False)
    assert credentials(path)["t2med-routing"] == ("d" * 64, None)
    assert credentials(path)["t2med-counters"] == ("c" * 64, set())
    assert not (prepare("repeat", "d" * 64) / "identities.new").exists()
    pairing.publish(work, True)
    assert path.read_bytes() == before
    with pytest.raises(pairing.SetupError, match="eigener Praxiszugang"):
        prepare("reader-collision", "c" * 64)
    register(config, "external", ["platz-1"], tmp_path / "limited.token")
    with pytest.raises(pairing.SetupError, match="weiterverwenden"):
        prepare("preserve-restriction", "e" * 64)
    digest, clients = credentials(path)["external"]
    assert clients == {"platz-1"}
    assert not (prepare("reuse-restriction", digest) / "identities.new").exists()


def test_http_api_scopes_commands_and_known_replays(enabled, tmp_path):
    config, journal, plant = enabled
    config.routing_policy.members["201"]["specialist"] = Membership(eligible=True)
    config = replace(config, control_api=replace(config.control_api, port=0))
    token, other = tmp_path / "first.token", tmp_path / "second.token"
    register(config, "first", ["empfang-1"], token)
    register(config, "other", ["empfang-2"], other)
    reader = tmp_path / "reader.token"
    reader.write_text("c" * 64)
    reader.chmod(0o600)
    path = config.control_api.credentials_file
    identities = json.loads(path.read_text())
    identities["identities"].append({"id": "t2med-counters", "token_sha256": hashlib.sha256(reader.read_bytes()).hexdigest(), "allowed_clients": []})
    path.write_text(json.dumps(identities))
    practice = tmp_path / "practice.token"
    register(config, "t2med-routing", None, practice)
    service = ControlService(config, journal, plant)
    service.controller.refresh(config)
    service.epoch = journal.load()["epoch"]
    request = command(journal.load(), "201")
    with ControlServer(service) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def exchange(method, path, secret, body=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            try:
                conn.request(method, path, body=body, headers={"Content-Type": "application/json",
                             "Authorization": "Bearer " + secret.read_text().strip(), **(headers or {})})
                response = conn.getresponse()
                assert response.getheader("Cache-Control") == "no-store"
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        try:
            assert exchange("GET", "/control/v1/capabilities", token)[1]["pbx_id"] == "synthetic-pbx"
            assert exchange("GET", "/control/v1/state", token)[1]["routing_control"]["available"]
            assert "ai_enabled" not in exchange("GET", "/control/v1/state", reader)[1]
            display = {"X-Kienzlefon-Display": "1"}
            for enabled_flag in (True, False):
                service.config = replace(config, ai_integration=replace(config.ai_integration, enabled=enabled_flag, assistant_enabled=True))
                assert exchange("GET", "/control/v1/state", reader, headers=display)[1]["ai_enabled"] is enabled_flag
            service.config = config
            assert exchange("GET", "/api/v1/telephony", token)[0] == 404
            path = "/control/v1/routing/requests"
            assert exchange("GET", "/control/v1/state", reader)[0] == 200
            assert exchange("GET", "/control/v1/capabilities", reader)[0] == 200
            assert exchange("POST", path, reader, json.dumps(request))[0] == 403
            assert exchange("POST", path, other, json.dumps(request))[0] == 403
            assert exchange("POST", path, token, json.dumps(request))[0] == 202
            service.controller.refresh(config)
            assert exchange("POST", path, token, json.dumps(request))[1]["request"]["state"] == "applied"
            assert exchange("GET", f"{path}/{request['request_id']}", other)[0] == 404
            scope = "/control/v1/routing/workplaces"
            assert exchange("GET", scope, practice)[1] == {
                "schema_version": 1, "pbx_id": "synthetic-pbx", "remote_enabled": True,
                "mode": "all", "client_ids": []}
            assert exchange("GET", scope, token)[1]["client_ids"] == ["empfang-1"]
            assert exchange("GET", scope, reader)[1]["mode"] == "selected"
            assert exchange("GET", scope, reader)[1]["client_ids"] == []
            for workplace, member in (("platz-neu-1", True), ("platz-neu-2", False)):
                cmd = {**command(journal.load(), "201", member=member), "client_id": workplace}
                assert exchange("POST", path, practice, json.dumps(cmd))[0] == 202
                service.controller.refresh(config)
                assert exchange("GET", f"{path}/{cmd['request_id']}", practice)[1]["request"]["state"] == "applied"
                assert ("201" in plant.members["normal"]) is member
            for member in (True, False):
                cmd = {**command(journal.load(), "201", "specialist", member=member), "client_id": "platz-neu-2"}
                assert exchange("POST", path, practice, json.dumps(cmd))[1]["error"]["code"] == "admin_locked"
            ext = next(ext for ext in exchange("GET", "/control/v1/state", practice)[1]["extensions"] if ext["id"] == "201")
            rights = ext["routing"]["permissions"]
            assert rights["normal"]["can_enable"] and rights["normal"]["can_disable"]
            assert not rights["specialist"]["can_enable"] and not rights["specialist"]["can_disable"]
            for selected in (("platz-neu-1",), ()):
                limited = replace(config, routing_policy=replace(config.routing_policy,
                                  workplace_mode="selected", workplace_ids=selected))
                service.config = limited
                service.controller.refresh(limited)
                assert exchange("GET", scope, practice)[1]["client_ids"] == list(selected)
                assert exchange("GET", scope, practice)[1]["mode"] == "selected"
                assert exchange("GET", scope, token)[1]["client_ids"] == []
                cmd = {**command(journal.load(), "201", member=True), "client_id": "platz-neu-2"}
                assert exchange("POST", path, practice, json.dumps(cmd))[1]["error"]["code"] == "client_forbidden"
                if selected:
                    cmd["client_id"] = selected[0]
                    assert exchange("POST", path, practice, json.dumps(cmd))[0] == 202
                    service.controller.refresh(limited)
                    assert exchange("GET", f"{path}/{cmd['request_id']}", practice)[1]["request"]["state"] == "applied"
            assert exchange("GET", f"{path}/{request['request_id']}", token)[0] == 404
        finally:
            server.shutdown()
            thread.join(timeout=2)


class FakeAmiHandler(socketserver.StreamRequestHandler):
    softphones = {"201": "0", "202": "1"}

    def handle(self):
        self.wfile.write(b"Asterisk Call Manager/8.0.0\r\n")
        while True:
            values = {}
            while line := self.rfile.readline():
                if not line.strip():
                    break
                key, _, value = line.decode().strip().partition(":")
                values[key] = value.strip()
            if not values:
                return
            self.send(values, {"Response": "Success"})
            if values["Action"] == "QueueStatus":
                queue = values["Queue"]
                self.send(values, {"Event": "QueueParams", "Queue": queue})
                for extension, penalty in (self.softphones.items() if queue == "praxis" else {"202": "0"}.items()):
                    self.send(values, {"Event": "QueueMember", "Queue": queue, "Name": "Test",
                        "Location": f"Local/{extension}@kienzlefon-queue-member", "StateInterface": f"PJSIP/{extension}",
                        "Membership": "dynamic", "Penalty": penalty, "Paused": "0"})
                self.send(values, {"Event": "QueueStatusComplete", "EventList": "Complete"})
            elif values["Action"] == "CoreShowChannels":
                self.send(values, {"Event": "CoreShowChannelsComplete", "EventList": "Complete"})
            elif values["Action"] == "BridgeList":
                self.send(values, {"Event": "BridgeListComplete", "EventList": "Complete"})

    def send(self, values, message):
        packet = {**message, "ActionID": values["ActionID"]}
        self.wfile.write(("\r\n".join(f"{k}: {v}" for k, v in packet.items()) + "\r\n\r\n").encode())


def test_native_ami_inventory_and_confirmed_empty_live_snapshot(enabled, monkeypatch):
    config, _journal, _plant = enabled
    monkeypatch.setattr("kienzlefon.telephony_ami.process_key", lambda: "fake-process")
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeAmiHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        plant = AsteriskPlant(AmiSettings("127.0.0.1", server.server_address[1], "dummy", "synthetic"))
        try:
            plant.connect()
            assert plant.inventory(config).members == {"normal": {"201": 0, "202": 1}, "specialist": {"202": 0}}
            live = LiveMonitor(plant)
            epoch = str(uuid4())
            live.collect(config, epoch, "fake-process")
            assert live.view(epoch)["status"] == "current" and live.view(epoch)["waiting"] == 0
            plant.connection.close()
            assert live.view(epoch)["waiting"] is None
        finally:
            if plant.connection:
                plant.connection.close()
            server.shutdown()
            thread.join(timeout=2)


def test_local_setup_keeps_credentials_and_external_settings(app_config, tmp_path, monkeypatch):
    from kienzlefon.config import load_config
    from kienzlefon import control_setup as setup
    from kienzlefon.webadmin import _set_toml_value

    source = app_config.source
    text = _set_toml_value(source.read_text(), "control_api", "credentials_file", str(tmp_path / "control.json"))
    source.write_text(text)
    setup.enable_local(load_config(source), "praxis-test")
    config = load_config(source)
    assert config.control_api.enabled and config.control_api.bind == "127.0.0.1"
    assert not config.routing_policy.remote_enabled
    assert config.control_api.allowed_networks == ("127.0.0.1/32",)
    setup.ensure_credentials(config)
    token = tmp_path / "control-admin-lokal.token"
    initial = token.read_bytes(), config.control_api.credentials_file.read_bytes()
    assert token.stat().st_mode & 0o777 == 0o600
    assert principal(config.control_api.credentials_file, "Bearer " + token.read_text().strip())[0] == "admin-lokal"
    setup.ensure_credentials(config)
    assert initial == (token.read_bytes(), config.control_api.credentials_file.read_bytes())
    etc = tmp_path / "asterisk"
    etc.mkdir()
    (etc / "manager.conf").write_text("[general]\nenabled=no\n")
    recorded = []
    with monkeypatch.context() as mock:
        mock.setattr(setup, "write_policy", lambda *_: None)
        mock.setattr(setup.os, "geteuid", lambda: 0)
        mock.setattr(setup, "ensure_credentials", lambda _: None)
        mock.setattr(setup.os, "fchown", lambda *_: None)
        mock.setattr(setup.os, "chown", lambda p, uid, gid: recorded.append((p, gid)))
        def missing_group(_):
            raise KeyError("asterisk")
        mock.setattr(setup.grp, "getgrnam", missing_group)
        setup.provision(config, etc)
    assert (etc / setup.MANAGED, (etc / "manager.conf").stat().st_gid) in recorded
    external = _set_toml_value(source.read_text(), "control_api", "bind", "10.20.1.1")
    source.write_text(external)
    setup.enable_local(load_config(source), "other")
    assert source.read_text() == external


def test_current_local_participation_independent_of_remote_permissions(enabled):
    from kienzlefon.telephony_control import InventoryChanged

    config, journal, plant = enabled
    config = replace(config, routing_policy=replace(config.routing_policy, remote_enabled=False))
    controller = Controller(journal, plant)
    controller.refresh(config)
    confirmed = journal.directory / "members-confirmed.json"
    first = json.loads(confirmed.read_text())
    real_inventory = plant.inventory

    def queued_event(config):
        if "201" not in plant.members["normal"]:
            plant.inventory = real_inventory
            raise InventoryChanged("Queue-Ereignis")
        return real_inventory(config)
    plant.inventory = queued_event
    controller.set_local_member(config, first["revision"], "normal", "201", False)
    next_view = json.loads(confirmed.read_text())
    assert next_view["members"] == {"normal": ["202"], "specialist": ["202"]}
    assert config.routing_policy.members["201"]["normal"].default_member
    with pytest.raises(SourceError, match="geändert"):
        controller.set_local_member(config, first["revision"], "normal", "201", True)
    with pytest.raises(ValueError, match="letzte"):
        controller.set_local_member(config, next_view["revision"], "normal", "202", False)
    with pytest.raises(ValueError, match="zugelassen"):
        controller.set_local_member(config, next_view["revision"], "specialist", "201", True)
