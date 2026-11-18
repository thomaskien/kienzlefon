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


def test_http_api_scopes_commands_and_known_replays(enabled, tmp_path):
    config, journal, plant = enabled
    config = replace(config, control_api=replace(config.control_api, port=0))
    token, other = tmp_path / "first.token", tmp_path / "second.token"
    register(config, "first", ["empfang-1"], token)
    register(config, "other", ["empfang-2"], other)
    service = ControlService(config, journal, plant)
    service.controller.refresh(config)
    service.epoch = journal.load()["epoch"]
    request = command(journal.load(), "201")
    with ControlServer(service) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def exchange(method, path, secret, body=None):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            try:
                conn.request(method, path, body=body, headers={"Content-Type": "application/json",
                             "Authorization": "Bearer " + secret.read_text().strip()})
                response = conn.getresponse()
                assert response.getheader("Cache-Control") == "no-store"
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        try:
            assert exchange("GET", "/control/v1/capabilities", token)[1]["pbx_id"] == "synthetic-pbx"
            assert exchange("GET", "/control/v1/state", token)[1]["routing_control"]["available"]
            assert exchange("GET", "/api/v1/telephony", token)[0] == 404
            path = "/control/v1/routing/requests"
            assert exchange("POST", path, other, json.dumps(request))[0] == 403
            assert exchange("POST", path, token, json.dumps(request))[0] == 202
            service.controller.refresh(config)
            assert exchange("POST", path, token, json.dumps(request))[1]["request"]["state"] == "applied"
            assert exchange("GET", f"{path}/{request['request_id']}", other)[0] == 404
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
