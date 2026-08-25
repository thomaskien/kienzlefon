# kienzlefon tests
# Version: 2.4.0
# Changelog:
# - 2.4.0: Zeitunabhaengiges Super-Priority-Handoff und stabile Parallelpruefung ergaenzt.
# - 1.1: Call-Result-Persistenz, Einmalverbrauch, Policy und Races getestet.
# - 1.0: Push-Freimeldung, not_free-Widerruf, TTL und atomare Lease-Vergabe getestet.

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from kienzlefon.admission import (
    CALL_POLICY_PROTOCOL,
    CALL_RESULT_PROTOCOL,
    PROTOCOL,
    create_server,
    send_command,
)
from kienzlefon.config import AIIntegrationConfig, AppConfig


def _config() -> AIIntegrationConfig:
    return AIIntegrationConfig(
        enabled=True,
        listener_mode="local",
        listener_ip="127.0.0.1",
        listener_port=0,
        extension_count=2,
        lease_ttl_ms=5000,
        publisher_timeout_ms=7000,
        sip_passwords=("a" * 24, "b" * 24),
    )


class RunningListener:
    def __init__(
        self,
        result_directory: Path | None = None,
        *,
        policy_provider=None,
        result_ttl_seconds: float = 30.0,
        result_wait_seconds: float = 0.2,
    ) -> None:
        base = _config()
        self._temporary = None
        if result_directory is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="kienzlefon-results-")
            result_directory = Path(self._temporary.name)
        self.result_directory = result_directory
        self.server = create_server(
            base,
            result_directory,
            policy_provider=policy_provider,
            result_ttl_seconds=result_ttl_seconds,
            result_wait_seconds=result_wait_seconds,
        )
        self.config = replace(base, listener_port=int(self.server.server_address[1]))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.publisher = socket.create_connection(
            (self.config.listener_ip, self.config.listener_port), timeout=1.0
        )
        self.publisher_reader = self.publisher.makefile("rb")

    def close(self) -> None:
        self.publisher_reader.close()
        self.publisher.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        if self._temporary is not None:
            self._temporary.cleanup()

    def publish(self, message: dict[str, Any]) -> dict[str, Any]:
        self.publisher.sendall(
            json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        return json.loads(self.publisher_reader.readline())

    def hello(self) -> dict[str, Any]:
        return self.publish(
            {
                "protocol": PROTOCOL,
                "command": "publisher_hello",
                "publisher_id": "ai-test-01",
                "slot_count": 2,
            }
        )

    def snapshot(
        self, sequence: int, first: dict[str, Any], second: dict[str, Any]
    ) -> dict[str, Any]:
        return self.publish(
            {
                "protocol": PROTOCOL,
                "command": "capacity_snapshot",
                "sequence": sequence,
                "slots": [
                    {"slot_id": "ai-slot-00", **first},
                    {"slot_id": "ai-slot-01", **second},
                ],
            }
        )


def _free(lease: str, ttl_ms: int = 5000) -> dict[str, Any]:
    return {"state": "free", "lease_id": lease, "ttl_ms": ttl_ms}


def _not_free(reason: str = "no_capacity") -> dict[str, Any]:
    return {"state": "not_free", "reason": reason}


def _claim(config: AIIntegrationConfig, request_id: str) -> dict[str, Any]:
    return send_command(
        config,
        {"protocol": PROTOCOL, "command": "claim_any", "request_id": request_id},
    )


def _call_result(
    request_id: str,
    lease_id: str,
    target: str = "classic",
    **changes: str,
) -> dict[str, str]:
    result = {
        "protocol": CALL_RESULT_PROTOCOL,
        "request_id": request_id,
        "lease_id": lease_id,
        "outcome": "handoff_requested",
        "handoff_target": target,
        "commit_status": "not_committed",
    }
    result.update(changes)
    return result


def _publish_result(listener: RunningListener, result: dict[str, Any]) -> dict[str, Any]:
    return listener.publish(
        {"protocol": PROTOCOL, "command": "publish_call_result", "result": result}
    )


def _consume_result(
    listener: RunningListener, request_id: str, lease_id: str
) -> dict[str, Any]:
    return send_command(
        listener.config,
        {
            "protocol": PROTOCOL,
            "command": "consume_call_result",
            "request_id": request_id,
            "lease_id": lease_id,
        },
        timeout=1.0,
    )


def _accepted_claim(
    listener: RunningListener,
    request_id: str = "result-request-0001",
    lease_id: str = "result-lease-0000000001",
) -> dict[str, Any]:
    assert listener.hello()["accepted"] is True
    listener.snapshot(1, _free(lease_id), _not_free())
    claim = _claim(listener.config, request_id)
    assert claim["accepted"] is True
    return claim


def test_only_explicit_free_lease_can_be_claimed_once() -> None:
    listener = RunningListener()
    try:
        assert listener.hello()["accepted"] is True
        result = listener.snapshot(
            1,
            _free("lease-0000000000000001"),
            _not_free(),
        )
        assert result["free_slots"] == 1

        accepted = _claim(listener.config, "request-0001")
        assert accepted["accepted"] is True
        assert accepted["slot_id"] == "ai-slot-00"
        assert accepted["extension"] == "8810"
        assert accepted["lease_id"] == "lease-0000000000000001"

        assert _claim(listener.config, "request-0002") == {
            "protocol": PROTOCOL,
            "command": "claim_result",
            "accepted": False,
            "request_id": "request-0002",
            "reason": "no_capacity",
        }
        assert _claim(listener.config, "request-0001") == accepted
    finally:
        listener.close()


def test_not_free_snapshot_revokes_unconsumed_offer() -> None:
    listener = RunningListener()
    try:
        listener.hello()
        listener.snapshot(
            1,
            _free("lease-0000000000000001"),
            _not_free(),
        )
        response = listener.snapshot(2, _not_free("maintenance"), _not_free())
        assert response["accepted"] is True
        assert response["free_slots"] == 0
        assert _claim(listener.config, "request-0003")["accepted"] is False
    finally:
        listener.close()


def test_disconnect_and_expired_ttl_fail_closed() -> None:
    listener = RunningListener()
    try:
        listener.hello()
        listener.snapshot(
            1,
            _free("lease-0000000000000001", ttl_ms=20),
            _not_free(),
        )
        time.sleep(0.04)
        assert _claim(listener.config, "request-0004")["accepted"] is False

        listener.snapshot(
            2,
            _free("lease-0000000000000002"),
            _not_free(),
        )
        listener.publisher_reader.close()
        listener.publisher.close()
        time.sleep(0.05)
        assert _claim(listener.config, "request-0005")["reason"] == "publisher_unavailable"
    finally:
        listener.server.shutdown()
        listener.server.server_close()
        listener.thread.join(timeout=2.0)


def test_parallel_claims_never_receive_same_lease() -> None:
    listener = RunningListener()
    try:
        listener.hello()
        listener.snapshot(
            1,
            _free("lease-0000000000000001"),
            _not_free(),
        )
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda index: _claim(listener.config, f"parallel-request-{index:02d}"),
                    range(8),
                )
            )
        accepted = [result for result in results if result["accepted"]]
        assert len(accepted) == 1
        assert accepted[0]["lease_id"] == "lease-0000000000000001"
    finally:
        listener.close()


def test_snapshot_rejects_same_free_lease_for_multiple_slots() -> None:
    listener = RunningListener()
    try:
        listener.hello()
        response = listener.snapshot(
            1,
            _free("duplicate-lease-00000001"),
            _free("duplicate-lease-00000001"),
        )

        assert response["accepted"] is False
        assert response["command"] == "error"
        assert response["reason"] == "invalid_message"
        assert _claim(listener.config, "request-after-duplicate")["accepted"] is False
    finally:
        listener.close()


def test_call_result_is_durable_idempotent_and_conflict_safe() -> None:
    listener = RunningListener()
    try:
        claim = _accepted_claim(listener)
        result = _call_result(claim["request_id"], claim["lease_id"], "practice_queue")
        first = _publish_result(listener, result)
        assert first["accepted"] is True
        assert first["duplicate"] is False
        files = list(listener.result_directory.glob("*.json"))
        assert len(files) == 1
        assert files[0].stat().st_mode & 0o777 == 0o600
        stored = json.loads(files[0].read_text(encoding="utf-8"))
        assert stored["result"] == result

        duplicate = _publish_result(listener, result)
        assert duplicate["accepted"] is True
        assert duplicate["duplicate"] is True

        conflicting = _publish_result(
            listener,
            _call_result(claim["request_id"], claim["lease_id"], "pharmacy_queue"),
        )
        assert conflicting["accepted"] is False
        assert conflicting["reason"] == "result_conflict"
    finally:
        listener.close()


def test_call_result_rejects_wrong_claim_lease_publisher_and_payload() -> None:
    listener = RunningListener()
    try:
        claim = _accepted_claim(listener)
        unknown = _publish_result(
            listener,
            _call_result("unknown-request-01", claim["lease_id"]),
        )
        assert unknown["reason"] == "claim_not_found"

        wrong_lease = _publish_result(
            listener,
            _call_result(claim["request_id"], "wrong-lease-000000001"),
        )
        assert wrong_lease["reason"] == "lease_mismatch"

        with socket.create_connection(
            (listener.config.listener_ip, listener.config.listener_port), timeout=1.0
        ) as other:
            message = {
                "protocol": PROTOCOL,
                "command": "publish_call_result",
                "result": _call_result(claim["request_id"], claim["lease_id"]),
            }
            other.sendall(json.dumps(message).encode("utf-8") + b"\n")
            with other.makefile("rb") as reader:
                other_result = json.loads(reader.readline())
        assert other_result["reason"] == "publisher_not_active"

        invalid_cases = [
            _call_result(claim["request_id"], claim["lease_id"], "8800"),
            _call_result(claim["request_id"], claim["lease_id"], "8810"),
            _call_result(
                claim["request_id"], claim["lease_id"], commit_status="committed"
            ),
        ]
        with_content = _call_result(claim["request_id"], claim["lease_id"])
        with_content["transcript"] = "darf nicht gespeichert werden"
        invalid_cases.append(with_content)
        for invalid in invalid_cases:
            response = _publish_result(listener, invalid)
            assert response["accepted"] is False
            assert response["reason"] == "invalid_call_result"
        assert list(listener.result_directory.glob("*.json")) == []

        with socket.create_connection(
            (listener.config.listener_ip, listener.config.listener_port), timeout=1.0
        ) as replacement:
            replacement_reader = replacement.makefile("rb")
            replacement.sendall(
                json.dumps(
                    {
                        "protocol": PROTOCOL,
                        "command": "publisher_hello",
                        "publisher_id": "ai-test-02",
                        "slot_count": 2,
                    }
                ).encode("utf-8")
                + b"\n"
            )
            assert json.loads(replacement_reader.readline())["accepted"] is True
            replacement.sendall(
                json.dumps(
                    {
                        "protocol": PROTOCOL,
                        "command": "publish_call_result",
                        "result": _call_result(claim["request_id"], claim["lease_id"]),
                    }
                ).encode("utf-8")
                + b"\n"
            )
            mismatch = json.loads(replacement_reader.readline())
            assert mismatch["accepted"] is False
            assert mismatch["reason"] == "publisher_mismatch"
            replacement_reader.close()
    finally:
        listener.close()


def test_call_result_is_persisted_before_positive_ack(monkeypatch) -> None:
    listener = RunningListener()
    try:
        claim = _accepted_claim(listener)
        persisted = threading.Event()
        may_ack = threading.Event()
        original = listener.server.registry._write_call_result

        def delayed_ack(record) -> None:
            original(record)
            persisted.set()
            assert may_ack.wait(timeout=2.0)

        monkeypatch.setattr(listener.server.registry, "_write_call_result", delayed_ack)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                _publish_result,
                listener,
                _call_result(claim["request_id"], claim["lease_id"]),
            )
            assert persisted.wait(timeout=1.0)
            assert list(listener.result_directory.glob("*.json"))
            assert future.done() is False
            may_ack.set()
            assert future.result(timeout=1.0)["accepted"] is True
    finally:
        listener.close()


def test_call_result_consume_is_atomic_and_survives_listener_restart(tmp_path: Path) -> None:
    result_directory = tmp_path / "results"
    listener = RunningListener(result_directory)
    claim = _accepted_claim(listener)
    result = _call_result(claim["request_id"], claim["lease_id"])
    assert _publish_result(listener, result)["accepted"] is True
    listener.close()

    restarted = RunningListener(result_directory)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(
                pool.map(
                    lambda _index: _consume_result(
                        restarted, claim["request_id"], claim["lease_id"]
                    ),
                    range(4),
                )
            )
        assert sum(response.get("execute") is True for response in responses) == 1
        assert all(response["accepted"] is True for response in responses)
    finally:
        restarted.close()


def test_call_result_expiry_and_result_bye_race_are_fail_closed(tmp_path: Path) -> None:
    expired = RunningListener(
        tmp_path / "expired", result_ttl_seconds=0.03, result_wait_seconds=0.03
    )
    try:
        claim = _accepted_claim(expired)
        assert _publish_result(
            expired, _call_result(claim["request_id"], claim["lease_id"])
        )["accepted"] is True
        time.sleep(0.05)
        response = _consume_result(expired, claim["request_id"], claim["lease_id"])
        assert response["accepted"] is False
        assert response["reason"] == "result_expired"
    finally:
        expired.close()

    racing = RunningListener(tmp_path / "racing", result_wait_seconds=0.5)
    try:
        claim = _accepted_claim(
            racing, request_id="race-request-0001", lease_id="race-lease-00000000001"
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                _consume_result, racing, claim["request_id"], claim["lease_id"]
            )
            time.sleep(0.03)
            _publish_result(
                racing, _call_result(claim["request_id"], claim["lease_id"])
            )
            response = future.result(timeout=1.0)
        assert response["execute"] is True
    finally:
        racing.close()


def test_call_policy_uses_current_classic_rules_and_schedules(
    app_config: AppConfig, monkeypatch
) -> None:
    evaluated_at = datetime(2026, 8, 10, 9, 0, tzinfo=app_config.practice.timezone)
    monkeypatch.setattr(type(app_config), "now", lambda _self: evaluated_at)
    listener = RunningListener(policy_provider=lambda: app_config)
    try:
        claim = _accepted_claim(listener)
        response = listener.publish(
            {
                "protocol": PROTOCOL,
                "command": "get_call_policy",
                "request_id": claim["request_id"],
                "lease_id": claim["lease_id"],
            }
        )
        assert response["accepted"] is True
        policy = response["policy"]
        assert policy["protocol"] == CALL_POLICY_PROTOCOL
        assert policy["timezone"] == "Europe/Berlin"
        assert policy["dtmf"]["mode"] == "classic_handoff"
        assert policy["dtmf"]["digits"] == list("0123456789") + ["*", "#"]
        assert len(policy["opening_hours"]) == 7
        assert len(policy["phone_hours"]) == 7
        assert "Praxis" in policy["spoken_information"]["opening_hours"]
        assert "Telefonzeiten" in policy["spoken_information"]["phone_hours"]
    finally:
        listener.close()


def test_super_priority_executes_outside_specialist_hours_and_only_once(
    app_config: AppConfig,
) -> None:
    listener = RunningListener(policy_provider=lambda: app_config)
    try:
        claim = _accepted_claim(listener)
        result = _call_result(claim["request_id"], claim["lease_id"], "super_priority")
        assert _publish_result(listener, result)["accepted"] is True
        response = _consume_result(listener, claim["request_id"], claim["lease_id"])
        assert response["accepted"] is True
        assert response["execute"] is True
        assert response["result"]["handoff_target"] == "super_priority"
        repeated = _consume_result(listener, claim["request_id"], claim["lease_id"])
        assert repeated["execute"] is False
        assert repeated["reason"] == "already_consumed"
    finally:
        listener.close()


@pytest.mark.parametrize("target", ["practice_queue", "pharmacy_queue"])
def test_time_bound_handoff_target_is_consumed_without_execution(
    app_config: AppConfig, target: str
) -> None:
    listener = RunningListener(policy_provider=lambda: app_config)
    try:
        claim = _accepted_claim(listener)
        result = _call_result(claim["request_id"], claim["lease_id"], target)
        assert _publish_result(listener, result)["accepted"] is True
        response = _consume_result(listener, claim["request_id"], claim["lease_id"])
        assert response == {
            "protocol": PROTOCOL,
            "command": "consume_call_result_result",
            "accepted": True,
            "execute": False,
            "request_id": claim["request_id"],
            "reason": "target_not_available",
        }
    finally:
        listener.close()


@pytest.mark.parametrize(
    "target", ["practice_queue", "pharmacy_queue", "super_priority"]
)
def test_nonclassic_handoff_fails_closed_without_policy_provider(target: str) -> None:
    listener = RunningListener()
    try:
        claim = _accepted_claim(listener)
        result = _call_result(claim["request_id"], claim["lease_id"], target)
        assert _publish_result(listener, result)["accepted"] is True

        response = _consume_result(listener, claim["request_id"], claim["lease_id"])

        assert response["accepted"] is True
        assert response["execute"] is False
        assert response["reason"] == "target_not_available"
    finally:
        listener.close()
