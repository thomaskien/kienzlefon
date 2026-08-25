# kienzlefon
# Version: 1.1
# Changelog:
# - 1.1: Dauerhafte Call-Results, atomaren Handoff-Verbrauch und Call-Policy ergaenzt.
# - 1.0: Push-basierte KI-Freimeldungen, atomare Lease-Vergabe und AGI-Client eingefuehrt.

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import socket
import socketserver
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .agi import AgiChannel, AgiHangup
from .config import AIIntegrationConfig, AppConfig, WeeklySchedule, load_config
from .prompts import rendered_prompts

PROTOCOL = "kienzlefon-ai-admission-v1"
CALL_RESULT_PROTOCOL = "kienzlefon-ai-call-result-v1"
CALL_POLICY_PROTOCOL = "kienzlefon-ai-call-policy-v1"
CALL_RESULT_STORE_PROTOCOL = "kienzlefon-ai-call-result-store-v1"
MAX_MESSAGE_BYTES = 65_536
DEFAULT_RESULT_DIRECTORY = Path("/var/lib/kienzlefon/ai-call-results")
CALL_RESULT_TTL_SECONDS = 30.0
CALL_RESULT_WAIT_SECONDS = 2.0
POLICY_VALID_FOR_MS = 1000
ACCEPTED_CLAIM_TTL_SECONDS = 4 * 60 * 60
REJECTED_CLAIM_TTL_SECONDS = 300.0
MAX_CLAIM_RECORDS = 4096
MAX_RESULT_RECORDS = 1024
IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
LEASE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
CALL_RESULT_FIELDS = frozenset(
    {"protocol", "request_id", "lease_id", "outcome", "handoff_target", "commit_status"}
)
HANDOFF_TARGETS = frozenset(
    {"classic", "practice_queue", "pharmacy_queue", "super_priority"}
)
PUBLISHER_NOT_FREE_REASONS = frozenset(
    {
        "in_call",
        "draining",
        "no_capacity",
        "not_ready",
        "maintenance",
        "service_unavailable",
        "slot_disabled",
    }
)


class AdmissionProtocolError(ValueError):
    """A protocol message is invalid or unsafe to apply."""


@dataclass
class SlotState:
    slot_id: str
    extension: str
    state: str = "not_free"
    reason: str = "publisher_disconnected"
    lease_id: str | None = None
    expires_at: float = 0.0


@dataclass
class ClaimRecord:
    response: dict[str, Any]
    expires_at: float
    result_hash: str | None = None


@dataclass
class CallResultRecord:
    result: dict[str, str]
    publisher_id: str
    stored_at: float
    expires_at: float
    consumed: bool = False
    consume_reason: str = ""


class AdmissionRegistry:
    """Thread-safe state owned by the main Kienzlefon listener."""

    def __init__(
        self,
        config: AIIntegrationConfig,
        result_directory: Path,
        *,
        policy_provider: Callable[[], AppConfig] | None = None,
        result_ttl_seconds: float = CALL_RESULT_TTL_SECONDS,
        result_wait_seconds: float = CALL_RESULT_WAIT_SECONDS,
    ) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._result_condition = threading.Condition(self._lock)
        self._result_directory = result_directory
        self._policy_provider = policy_provider
        self._result_ttl_seconds = result_ttl_seconds
        self._result_wait_seconds = result_wait_seconds
        self._slots = {
            slot_id: SlotState(slot_id=slot_id, extension=extension)
            for slot_id, extension in zip(config.slot_ids, config.extensions, strict=True)
        }
        self._publisher_session: str | None = None
        self._publisher_id: str | None = None
        self._publisher_last_seen = 0.0
        self._last_sequence = -1
        self._last_snapshot_hash = ""
        self._claims: dict[str, ClaimRecord] = {}
        self._consumed_leases: dict[str, float] = {}
        self._call_results: dict[str, CallResultRecord] = {}
        self._prepare_result_directory()
        self._load_call_results()

    def _base(self, command: str) -> dict[str, Any]:
        return {"protocol": PROTOCOL, "command": command}

    def _prepare_result_directory(self) -> None:
        self._result_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._result_directory, 0o700)

    def _result_path(self, request_id: str) -> Path:
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return self._result_directory / f"{digest}.json"

    def _record_payload(self, record: CallResultRecord) -> dict[str, Any]:
        return {
            "storage_protocol": CALL_RESULT_STORE_PROTOCOL,
            "publisher_id": record.publisher_id,
            "stored_at": record.stored_at,
            "expires_at": record.expires_at,
            "consumed": record.consumed,
            "consume_reason": record.consume_reason,
            "result": record.result,
        }

    def _write_call_result(self, record: CallResultRecord) -> None:
        request_id = record.result["request_id"]
        target = self._result_path(request_id)
        temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
        payload = json.dumps(
            self._record_payload(record), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            directory_flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                directory_flags |= os.O_DIRECTORY
            directory_descriptor = os.open(self._result_directory, directory_flags)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def _remove_call_result_file(self, request_id: str) -> None:
        self._result_path(request_id).unlink(missing_ok=True)

    def _load_call_results(self) -> None:
        now = time.time()
        for path in self._result_directory.glob("*.json"):
            try:
                if path.is_symlink() or path.stat().st_size > MAX_MESSAGE_BYTES:
                    raise AdmissionProtocolError("Ungueltige Call-Result-Datei")
                raw = json.loads(path.read_text(encoding="utf-8"))
                record = _stored_call_result(raw)
                expected_path = self._result_path(record.result["request_id"])
                if path != expected_path or record.expires_at <= now:
                    raise AdmissionProtocolError("Abgelaufene oder falsch benannte Call-Result-Datei")
                self._call_results[record.result["request_id"]] = record
            except (AdmissionProtocolError, OSError, json.JSONDecodeError, TypeError, ValueError):
                path.unlink(missing_ok=True)

    def _cleanup_call_results(self, now: float) -> None:
        expired = [
            request_id
            for request_id, record in self._call_results.items()
            if record.expires_at <= now
        ]
        for request_id in expired:
            self._call_results.pop(request_id, None)
            self._remove_call_result_file(request_id)

    def cleanup(self) -> None:
        with self._lock:
            self._cleanup(time.monotonic(), time.time())

    def _invalidate_slots(self, reason: str) -> None:
        for slot in self._slots.values():
            slot.state = "not_free"
            slot.reason = reason
            slot.lease_id = None
            slot.expires_at = 0.0

    def _cleanup(self, now: float, wall_now: float | None = None) -> None:
        if (
            self._publisher_session is not None
            and now - self._publisher_last_seen
            > self.config.publisher_timeout_ms / 1000.0
        ):
            self._invalidate_slots("publisher_timeout")
            self._publisher_session = None
            self._publisher_id = None
        for slot in self._slots.values():
            if slot.state == "free" and slot.expires_at <= now:
                slot.state = "not_free"
                slot.reason = "lease_expired"
                slot.lease_id = None
                slot.expires_at = 0.0
        self._claims = {
            key: record for key, record in self._claims.items() if record.expires_at > now
        }
        self._consumed_leases = {
            key: expiry for key, expiry in self._consumed_leases.items() if expiry > now
        }
        self._cleanup_call_results(time.time() if wall_now is None else wall_now)

    def publisher_hello(self, session_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        publisher_id = _identifier(message.get("publisher_id"), "publisher_id")
        slot_count = _integer(message.get("slot_count"), "slot_count", minimum=1)
        if slot_count != self.config.extension_count:
            return {
                **self._base("publisher_hello_result"),
                "accepted": False,
                "reason": "slot_count_mismatch",
                "configured_slot_count": self.config.extension_count,
            }
        with self._lock:
            self._invalidate_slots("publisher_disconnected")
            self._publisher_session = session_id
            self._publisher_id = publisher_id
            self._publisher_last_seen = time.monotonic()
            self._last_sequence = -1
            self._last_snapshot_hash = ""
        return {
            **self._base("publisher_hello_result"),
            "accepted": True,
            "configured_slot_count": self.config.extension_count,
            "slot_ids": list(self.config.slot_ids),
            "lease_ttl_ms": self.config.lease_ttl_ms,
            "publisher_timeout_ms": self.config.publisher_timeout_ms,
        }

    def capacity_snapshot(
        self, session_id: str | None, message: Mapping[str, Any]
    ) -> dict[str, Any]:
        sequence = _integer(message.get("sequence"), "sequence", minimum=0)
        entries = message.get("slots")
        if not isinstance(entries, list):
            raise AdmissionProtocolError("slots muss eine Liste sein")
        parsed: dict[str, dict[str, Any]] = {}
        free_lease_ids: set[str] = set()
        for raw in entries:
            if not isinstance(raw, Mapping):
                raise AdmissionProtocolError("Jeder Slot muss ein Objekt sein")
            slot_id = _identifier(raw.get("slot_id"), "slot_id")
            if slot_id not in self._slots or slot_id in parsed:
                raise AdmissionProtocolError("Unbekannter oder doppelter slot_id")
            state = raw.get("state")
            if state == "free":
                lease_id = _lease_identifier(raw.get("lease_id"))
                if lease_id in free_lease_ids:
                    raise AdmissionProtocolError("lease_id darf nur einem Slot gehoeren")
                free_lease_ids.add(lease_id)
                ttl_ms = _integer(raw.get("ttl_ms"), "ttl_ms", minimum=1)
                if ttl_ms > self.config.lease_ttl_ms:
                    raise AdmissionProtocolError("ttl_ms ueberschreitet die konfigurierte TTL")
                parsed[slot_id] = {
                    "state": "free",
                    "lease_id": lease_id,
                    "ttl_ms": ttl_ms,
                }
            elif state == "not_free":
                reason = str(raw.get("reason", "unknown"))
                if reason not in PUBLISHER_NOT_FREE_REASONS:
                    raise AdmissionProtocolError("Unbekannter not_free-Grund")
                parsed[slot_id] = {"state": "not_free", "reason": reason}
            else:
                raise AdmissionProtocolError("state muss free oder not_free sein")
        if set(parsed) != set(self._slots):
            raise AdmissionProtocolError("Snapshot muss alle konfigurierten Slots enthalten")

        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            if session_id is None or session_id != self._publisher_session:
                return {
                    **self._base("capacity_snapshot_result"),
                    "accepted": False,
                    "sequence": sequence,
                    "reason": "publisher_not_active",
                }
            if sequence < self._last_sequence:
                return {
                    **self._base("capacity_snapshot_result"),
                    "accepted": False,
                    "sequence": sequence,
                    "reason": "stale_sequence",
                }
            if sequence == self._last_sequence:
                accepted = snapshot_hash == self._last_snapshot_hash
                return {
                    **self._base("capacity_snapshot_result"),
                    "accepted": accepted,
                    "sequence": sequence,
                    "duplicate": accepted,
                    **({} if accepted else {"reason": "sequence_conflict"}),
                }
            for slot_id, entry in parsed.items():
                slot = self._slots[slot_id]
                if entry["state"] == "not_free":
                    slot.state = "not_free"
                    slot.reason = str(entry["reason"])
                    slot.lease_id = None
                    slot.expires_at = 0.0
                    continue
                lease_id = str(entry["lease_id"])
                if lease_id in self._consumed_leases:
                    slot.state = "not_free"
                    slot.reason = "lease_consumed"
                    slot.lease_id = None
                    slot.expires_at = 0.0
                    continue
                slot.state = "free"
                slot.reason = ""
                slot.lease_id = lease_id
                slot.expires_at = now + int(entry["ttl_ms"]) / 1000.0
            self._publisher_last_seen = now
            self._last_sequence = sequence
            self._last_snapshot_hash = snapshot_hash
            free_count = sum(slot.state == "free" for slot in self._slots.values())
        return {
            **self._base("capacity_snapshot_result"),
            "accepted": True,
            "sequence": sequence,
            "free_slots": free_count,
        }

    def claim(self, message: Mapping[str, Any], specific: bool) -> dict[str, Any]:
        request_id = _identifier(message.get("request_id"), "request_id")
        requested_slot = (
            _identifier(message.get("slot_id"), "slot_id") if specific else None
        )
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            previous = self._claims.get(request_id)
            if previous is not None:
                return dict(previous.response)
            if len(self._claims) >= MAX_CLAIM_RECORDS:
                return {
                    **self._base("claim_result"),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "claim_store_full",
                }
            if self._publisher_session is None:
                response = {
                    **self._base("claim_result"),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "publisher_unavailable",
                }
            else:
                candidates = (
                    [self._slots[requested_slot]]
                    if requested_slot in self._slots
                    else []
                    if specific
                    else [self._slots[key] for key in sorted(self._slots)]
                )
                slot = next((entry for entry in candidates if entry.state == "free"), None)
                if slot is None:
                    response = {
                        **self._base("claim_result"),
                        "accepted": False,
                        "request_id": request_id,
                        "reason": "slot_not_free" if specific else "no_capacity",
                    }
                else:
                    lease_id = str(slot.lease_id)
                    remaining_ms = max(1, int((slot.expires_at - now) * 1000))
                    slot.state = "assigned"
                    slot.reason = ""
                    self._consumed_leases[lease_id] = now + ACCEPTED_CLAIM_TTL_SECONDS
                    response = {
                        **self._base("claim_result"),
                        "accepted": True,
                        "request_id": request_id,
                        "publisher_id": self._publisher_id,
                        "slot_id": slot.slot_id,
                        "extension": slot.extension,
                        "lease_id": lease_id,
                        "expires_in_ms": remaining_ms,
                    }
            claim_ttl = (
                ACCEPTED_CLAIM_TTL_SECONDS
                if response.get("accepted") is True
                else REJECTED_CLAIM_TTL_SECONDS
            )
            self._claims[request_id] = ClaimRecord(
                response=dict(response), expires_at=now + claim_ttl
            )
            return response

    def release(self, message: Mapping[str, Any]) -> dict[str, Any]:
        request_id = _identifier(message.get("request_id"), "request_id")
        lease_id = _lease_identifier(message.get("lease_id"))
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            record = self._claims.get(request_id)
            accepted = bool(
                record
                and record.response.get("accepted") is True
                and record.response.get("lease_id") == lease_id
            )
            if accepted:
                record.response = {
                    **self._base("claim_result"),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "released",
                }
                record.expires_at = now + REJECTED_CLAIM_TTL_SECONDS
        return {
            **self._base("release_result"),
            "accepted": accepted,
            "request_id": request_id,
            **({} if accepted else {"reason": "claim_not_found"}),
        }

    def publish_call_result(
        self, session_id: str | None, message: Mapping[str, Any]
    ) -> dict[str, Any]:
        command = "publish_call_result_result"
        if set(message) != {"protocol", "command", "result"}:
            return {**self._base(command), "accepted": False, "reason": "invalid_call_result"}
        try:
            result = _call_result(message.get("result"))
        except AdmissionProtocolError:
            return {**self._base(command), "accepted": False, "reason": "invalid_call_result"}
        request_id = result["request_id"]
        lease_id = result["lease_id"]
        canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
        result_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        monotonic_now = time.monotonic()
        wall_now = time.time()
        with self._result_condition:
            self._cleanup(monotonic_now, wall_now)
            if session_id is None or session_id != self._publisher_session:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "publisher_not_active",
                }
            claim = self._claims.get(request_id)
            if claim is None or claim.response.get("accepted") is not True:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "claim_not_found",
                }
            if claim.response.get("publisher_id") != self._publisher_id:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "publisher_mismatch",
                }
            if claim.response.get("lease_id") != lease_id:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "lease_mismatch",
                }
            previous = self._call_results.get(request_id)
            if claim.result_hash is not None:
                if claim.result_hash != result_hash:
                    return {
                        **self._base(command),
                        "accepted": False,
                        "request_id": request_id,
                        "reason": "result_conflict",
                    }
                if previous is None:
                    return {
                        **self._base(command),
                        "accepted": False,
                        "request_id": request_id,
                        "reason": "result_expired",
                    }
                return {
                    **self._base(command),
                    "accepted": True,
                    "request_id": request_id,
                    "duplicate": True,
                }
            if previous is not None:
                previous_hash = _call_result_hash(previous.result)
                if previous_hash != result_hash:
                    return {
                        **self._base(command),
                        "accepted": False,
                        "request_id": request_id,
                        "reason": "result_conflict",
                    }
                claim.result_hash = result_hash
                return {
                    **self._base(command),
                    "accepted": True,
                    "request_id": request_id,
                    "duplicate": True,
                }
            if len(self._call_results) >= MAX_RESULT_RECORDS:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "result_store_full",
                }
            record = CallResultRecord(
                result=result,
                publisher_id=str(self._publisher_id),
                stored_at=wall_now,
                expires_at=wall_now + self._result_ttl_seconds,
            )
            try:
                self._write_call_result(record)
            except OSError as exc:
                logging.error(
                    "Call-Result konnte nicht dauerhaft gespeichert werden: %s",
                    type(exc).__name__,
                )
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "result_persistence_failed",
                }
            self._call_results[request_id] = record
            claim.result_hash = result_hash
            self._result_condition.notify_all()
            return {
                **self._base(command),
                "accepted": True,
                "request_id": request_id,
                "duplicate": False,
            }

    def consume_call_result(self, message: Mapping[str, Any]) -> dict[str, Any]:
        command = "consume_call_result_result"
        try:
            if set(message) != {"protocol", "command", "request_id", "lease_id"}:
                raise AdmissionProtocolError("Ungueltige Call-Result-Abfrage")
            request_id = _identifier(message.get("request_id"), "request_id")
            lease_id = _lease_identifier(message.get("lease_id"))
        except AdmissionProtocolError:
            return {**self._base(command), "accepted": False, "reason": "invalid_query"}
        deadline = time.monotonic() + self._result_wait_seconds
        with self._result_condition:
            while True:
                monotonic_now = time.monotonic()
                self._cleanup(monotonic_now, time.time())
                record = self._call_results.get(request_id)
                if record is not None:
                    if record.result["lease_id"] != lease_id:
                        return {
                            **self._base(command),
                            "accepted": False,
                            "request_id": request_id,
                            "reason": "lease_mismatch",
                        }
                    if record.consumed:
                        return {
                            **self._base(command),
                            "accepted": True,
                            "execute": False,
                            "request_id": request_id,
                            "reason": record.consume_reason or "already_consumed",
                        }
                    allowed = self._handoff_target_allowed(record.result["handoff_target"])
                    record.consumed = True
                    record.consume_reason = "already_consumed" if allowed else "target_not_available"
                    try:
                        self._write_call_result(record)
                    except OSError as exc:
                        record.consumed = False
                        record.consume_reason = ""
                        logging.error(
                            "Call-Result-Verbrauch konnte nicht gespeichert werden: %s",
                            type(exc).__name__,
                        )
                        return {
                            **self._base(command),
                            "accepted": False,
                            "request_id": request_id,
                            "reason": "result_persistence_failed",
                        }
                    if not allowed:
                        return {
                            **self._base(command),
                            "accepted": True,
                            "execute": False,
                            "request_id": request_id,
                            "reason": "target_not_available",
                        }
                    return {
                        **self._base(command),
                        "accepted": True,
                        "execute": True,
                        "request_id": request_id,
                        "result": dict(record.result),
                    }
                claim = self._claims.get(request_id)
                if claim is not None and claim.result_hash is not None:
                    return {
                        **self._base(command),
                        "accepted": False,
                        "request_id": request_id,
                        "reason": "result_expired",
                    }
                remaining = deadline - monotonic_now
                if remaining <= 0:
                    return {
                        **self._base(command),
                        "accepted": False,
                        "request_id": request_id,
                        "reason": "result_not_found",
                    }
                self._result_condition.wait(timeout=remaining)

    def _handoff_target_allowed(self, target: str) -> bool:
        if target == "classic":
            return True
        if self._policy_provider is None:
            return False
        try:
            config = self._policy_provider()
            evaluated_at = config.now()
            if target == "practice_queue":
                return config.phone_is_open(evaluated_at)
            if target == "pharmacy_queue":
                return config.pharmacy_is_available(evaluated_at)
            if target == "super_priority":
                return True
        except Exception as exc:
            logging.warning(
                "Call-Policy konnte nicht ausgewertet werden: %s", type(exc).__name__
            )
        return False

    def get_call_policy(
        self, session_id: str | None, message: Mapping[str, Any]
    ) -> dict[str, Any]:
        command = "get_call_policy_result"
        try:
            if set(message) != {"protocol", "command", "request_id", "lease_id"}:
                raise AdmissionProtocolError("Ungueltige Call-Policy-Abfrage")
            request_id = _identifier(message.get("request_id"), "request_id")
            lease_id = _lease_identifier(message.get("lease_id"))
        except AdmissionProtocolError:
            return {**self._base(command), "accepted": False, "reason": "invalid_query"}
        with self._lock:
            self._cleanup(time.monotonic(), time.time())
            if session_id is None or session_id != self._publisher_session:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "publisher_not_active",
                }
            claim = self._claims.get(request_id)
            if claim is None or claim.response.get("accepted") is not True:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "claim_not_found",
                }
            if claim.response.get("publisher_id") != self._publisher_id:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "publisher_mismatch",
                }
            if claim.response.get("lease_id") != lease_id:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "lease_mismatch",
                }
            if self._policy_provider is None:
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "policy_unavailable",
                }
            try:
                policy = _call_policy(self._policy_provider())
            except Exception as exc:
                logging.warning(
                    "Call-Policy konnte nicht geladen werden: %s", type(exc).__name__
                )
                return {
                    **self._base(command),
                    "accepted": False,
                    "request_id": request_id,
                    "reason": "policy_unavailable",
                }
            return {
                **self._base(command),
                "accepted": True,
                "request_id": request_id,
                "lease_id": lease_id,
                "policy": policy,
            }

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            states: dict[str, int] = {}
            for slot in self._slots.values():
                states[slot.state] = states.get(slot.state, 0) + 1
            return {
                **self._base("status_result"),
                "enabled": self.config.enabled,
                "publisher_connected": self._publisher_session is not None,
                "publisher_id": self._publisher_id,
                "configured_slots": len(self._slots),
                "states": states,
            }

    def disconnect_publisher(self, session_id: str) -> None:
        with self._lock:
            if session_id != self._publisher_session:
                return
            self._invalidate_slots("publisher_disconnected")
            self._publisher_session = None
            self._publisher_id = None


class AdmissionRequestHandler(socketserver.StreamRequestHandler):
    server: "AdmissionTCPServer"

    def handle(self) -> None:
        session_id = str(uuid.uuid4())
        publisher = False
        try:
            while True:
                raw = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
                if not raw:
                    return
                if len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
                    self._write_error("message_too_large")
                    return
                try:
                    message = json.loads(raw)
                    if not isinstance(message, Mapping):
                        raise AdmissionProtocolError("Nachricht muss ein Objekt sein")
                    if message.get("protocol") != PROTOCOL:
                        raise AdmissionProtocolError("Falsche Protokollversion")
                    command = message.get("command")
                    if command == "publisher_hello":
                        response = self.server.registry.publisher_hello(session_id, message)
                        publisher = response.get("accepted") is True
                    elif command == "capacity_snapshot":
                        response = self.server.registry.capacity_snapshot(
                            session_id if publisher else None, message
                        )
                    elif command == "publish_call_result":
                        response = self.server.registry.publish_call_result(
                            session_id if publisher else None, message
                        )
                    elif command == "get_call_policy":
                        response = self.server.registry.get_call_policy(
                            session_id if publisher else None, message
                        )
                    elif command == "claim_any":
                        response = self.server.registry.claim(message, specific=False)
                    elif command == "claim_specific":
                        response = self.server.registry.claim(message, specific=True)
                    elif command == "release":
                        response = self.server.registry.release(message)
                    elif command == "consume_call_result":
                        response = self.server.registry.consume_call_result(message)
                    elif command == "status":
                        response = self.server.registry.status()
                    else:
                        raise AdmissionProtocolError("Unbekanntes Kommando")
                except (AdmissionProtocolError, json.JSONDecodeError, TypeError) as exc:
                    response = {
                        "protocol": PROTOCOL,
                        "command": "error",
                        "accepted": False,
                        "reason": "invalid_message",
                        "detail": str(exc),
                    }
                self.wfile.write(
                    json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                    + b"\n"
                )
                self.wfile.flush()
                if not publisher:
                    return
        finally:
            if publisher:
                self.server.registry.disconnect_publisher(session_id)

    def _write_error(self, reason: str) -> None:
        payload = {
            "protocol": PROTOCOL,
            "command": "error",
            "accepted": False,
            "reason": reason,
        }
        self.wfile.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")


class AdmissionTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        registry: AdmissionRegistry,
    ) -> None:
        self.registry = registry
        super().__init__(server_address, AdmissionRequestHandler)

    def service_actions(self) -> None:
        self.registry.cleanup()


def create_server(
    config: AIIntegrationConfig,
    result_directory: Path = DEFAULT_RESULT_DIRECTORY,
    *,
    policy_provider: Callable[[], AppConfig] | None = None,
    result_ttl_seconds: float = CALL_RESULT_TTL_SECONDS,
    result_wait_seconds: float = CALL_RESULT_WAIT_SECONDS,
) -> AdmissionTCPServer:
    server_class = AdmissionTCPServer
    if ":" in config.listener_ip:
        server_class = type(
            "AdmissionTCPServerIPv6",
            (AdmissionTCPServer,),
            {"address_family": socket.AF_INET6},
        )
    registry = AdmissionRegistry(
        config,
        result_directory,
        policy_provider=policy_provider,
        result_ttl_seconds=result_ttl_seconds,
        result_wait_seconds=result_wait_seconds,
    )
    return server_class((config.listener_ip, config.listener_port), registry)


def send_command(
    config: AIIntegrationConfig,
    message: Mapping[str, Any],
    timeout: float = 0.75,
) -> dict[str, Any]:
    payload = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise AdmissionProtocolError("Nachricht ist zu gross")
    with socket.create_connection(
        (config.listener_ip, config.listener_port), timeout=timeout
    ) as connection:
        connection.settimeout(timeout)
        connection.sendall(payload + b"\n")
        with connection.makefile("rb") as reader:
            raw = reader.readline(MAX_MESSAGE_BYTES + 1)
    if not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise AdmissionProtocolError("Admission-Listener lieferte keine gueltige Antwort")
    response = json.loads(raw)
    if not isinstance(response, dict) or response.get("protocol") != PROTOCOL:
        raise AdmissionProtocolError("Admission-Listener lieferte falsches Protokoll")
    return response


def listener_main() -> None:
    parser = argparse.ArgumentParser(description="Kienzlefon AI Admission-Listener")
    parser.add_argument("--config", default="/etc/kienzlefon/kienzlefon.toml")
    parser.add_argument("--version", action="version", version="%(prog)s 1.1")
    arguments = parser.parse_args()
    config_path = Path(arguments.config)
    config = load_config(config_path)
    if not config.ai_integration.enabled:
        raise SystemExit("KI-Integration ist deaktiviert")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = create_server(
        config.ai_integration,
        DEFAULT_RESULT_DIRECTORY,
        policy_provider=lambda: load_config(config_path),
    )
    logging.info(
        "Admission-Listener bereit auf %s:%s fuer %s Slots",
        config.ai_integration.listener_ip,
        config.ai_integration.listener_port,
        config.ai_integration.extension_count,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def admission_agi_main() -> None:
    parser = argparse.ArgumentParser(description="Kienzlefon AI Admission-AGI")
    parser.add_argument("--config", default="/etc/kienzlefon/kienzlefon.toml")
    parser.add_argument(
        "--selection",
        choices=("any", "specific", "release", "status", "call-result"),
        required=True,
    )
    parser.add_argument("--slot-id")
    parser.add_argument("--request-id")
    parser.add_argument("--lease-id")
    parser.add_argument("--version", action="version", version="%(prog)s 1.1")
    arguments = parser.parse_args()
    app_config: AppConfig = load_config(arguments.config)
    channel = AgiChannel()
    request_id = arguments.request_id or channel.environment.get("agi_uniqueid")
    strict_identifiers = arguments.selection in {"release", "call-result"}
    if not request_id or not IDENTIFIER.fullmatch(request_id):
        if strict_identifiers:
            try:
                channel.set_variable("KZF_AI_HANDOFF_ALLOWED", "0")
                channel.set_variable("KZF_AI_HANDOFF_REASON", "invalid_request_id")
            except AgiHangup:
                pass
            return
        request_id = str(uuid.uuid4())
    try:
        if arguments.selection == "call-result":
            channel.set_variable("KZF_AI_HANDOFF_ALLOWED", "0")
            channel.set_variable("KZF_AI_HANDOFF_TARGET", "")
            response = send_command(
                app_config.ai_integration,
                {
                    "protocol": PROTOCOL,
                    "command": "consume_call_result",
                    "request_id": request_id,
                    "lease_id": arguments.lease_id,
                },
                timeout=CALL_RESULT_WAIT_SECONDS + 1.0,
            )
            execute = response.get("accepted") is True and response.get("execute") is True
            reason = str(response.get("reason", "accepted"))
            if execute:
                result = _call_result(response.get("result"))
                execute = bool(
                    result["request_id"] == request_id
                    and result["lease_id"] == arguments.lease_id
                    and result["handoff_target"] in HANDOFF_TARGETS
                )
                if execute:
                    channel.set_variable("KZF_AI_HANDOFF_TARGET", result["handoff_target"])
                else:
                    reason = "result_mismatch"
            channel.set_variable("KZF_AI_HANDOFF_ALLOWED", "1" if execute else "0")
            channel.set_variable("KZF_AI_HANDOFF_REASON", reason)
            return
        if arguments.selection == "release":
            response = send_command(
                app_config.ai_integration,
                {
                    "protocol": PROTOCOL,
                    "command": "release",
                    "request_id": request_id,
                    "lease_id": arguments.lease_id,
                },
            )
            channel.set_variable(
                "KZF_AI_RELEASED", "1" if response.get("accepted") is True else "0"
            )
            return
        if arguments.selection == "status":
            response = send_command(
                app_config.ai_integration,
                {"protocol": PROTOCOL, "command": "status"},
            )
            channel.set_variable(
                "KZF_AI_PUBLISHER_CONNECTED",
                "1" if response.get("publisher_connected") is True else "0",
            )
            return
        command = "claim_any" if arguments.selection == "any" else "claim_specific"
        message: dict[str, Any] = {
            "protocol": PROTOCOL,
            "command": command,
            "request_id": request_id,
        }
        if arguments.selection == "specific":
            message["slot_id"] = arguments.slot_id
        response = send_command(app_config.ai_integration, message)
        accepted = response.get("accepted") is True
        channel.set_variable("KZF_AI_ACCEPTED", "1" if accepted else "0")
        channel.set_variable("KZF_AI_REQUEST_ID", request_id)
        channel.set_variable("KZF_AI_REASON", str(response.get("reason", "accepted")))
        if accepted:
            channel.set_variable("KZF_AI_SLOT_ID", str(response["slot_id"]))
            channel.set_variable("KZF_AI_EXTENSION", str(response["extension"]))
            channel.set_variable("KZF_AI_LEASE_ID", str(response["lease_id"]))
    except AgiHangup:
        return
    except Exception as exc:
        logging.warning("AI-Admission technisch nicht verfuegbar: %s", type(exc).__name__)
        try:
            if arguments.selection == "call-result":
                channel.set_variable("KZF_AI_HANDOFF_ALLOWED", "0")
                channel.set_variable("KZF_AI_HANDOFF_REASON", "listener_unavailable")
                return
            channel.set_variable("KZF_AI_ACCEPTED", "0")
            channel.set_variable("KZF_AI_REQUEST_ID", request_id)
            channel.set_variable("KZF_AI_REASON", "listener_unavailable")
        except AgiHangup:
            return


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise AdmissionProtocolError(f"{name} ist ungueltig")
    return value


def _lease_identifier(value: Any) -> str:
    if not isinstance(value, str) or not LEASE_IDENTIFIER.fullmatch(value):
        raise AdmissionProtocolError("lease_id ist ungueltig")
    return value


def _integer(value: Any, name: str, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise AdmissionProtocolError(f"{name} ist ungueltig")
    return value


def _call_result(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != CALL_RESULT_FIELDS:
        raise AdmissionProtocolError("Call-Result besitzt ungueltige Felder")
    result = {
        "protocol": str(value.get("protocol", "")),
        "request_id": _identifier(value.get("request_id"), "request_id"),
        "lease_id": _lease_identifier(value.get("lease_id")),
        "outcome": str(value.get("outcome", "")),
        "handoff_target": str(value.get("handoff_target", "")),
        "commit_status": str(value.get("commit_status", "")),
    }
    if result["protocol"] != CALL_RESULT_PROTOCOL:
        raise AdmissionProtocolError("Falsches Call-Result-Protokoll")
    if result["outcome"] != "handoff_requested":
        raise AdmissionProtocolError("Unzulaessiges Call-Result")
    if result["handoff_target"] not in HANDOFF_TARGETS:
        raise AdmissionProtocolError("Unbekanntes Handoff-Ziel")
    if result["commit_status"] != "not_committed":
        raise AdmissionProtocolError("Handoff nach Commit ist nicht zulaessig")
    return result


def _call_result_hash(result: Mapping[str, str]) -> str:
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stored_call_result(value: Any) -> CallResultRecord:
    expected = {
        "storage_protocol",
        "publisher_id",
        "stored_at",
        "expires_at",
        "consumed",
        "consume_reason",
        "result",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise AdmissionProtocolError("Ungueltiger Call-Result-Speicherstand")
    if value.get("storage_protocol") != CALL_RESULT_STORE_PROTOCOL:
        raise AdmissionProtocolError("Falscher Call-Result-Speicherstand")
    publisher_id = _identifier(value.get("publisher_id"), "publisher_id")
    stored_at = value.get("stored_at")
    expires_at = value.get("expires_at")
    consumed = value.get("consumed")
    consume_reason = value.get("consume_reason")
    if (
        not isinstance(stored_at, (int, float))
        or isinstance(stored_at, bool)
        or not math.isfinite(stored_at)
        or not isinstance(expires_at, (int, float))
        or isinstance(expires_at, bool)
        or not math.isfinite(expires_at)
        or expires_at <= stored_at
        or not isinstance(consumed, bool)
        or consume_reason not in {"", "already_consumed", "target_not_available"}
    ):
        raise AdmissionProtocolError("Ungueltige Call-Result-Metadaten")
    return CallResultRecord(
        result=_call_result(value.get("result")),
        publisher_id=publisher_id,
        stored_at=float(stored_at),
        expires_at=float(expires_at),
        consumed=consumed,
        consume_reason=str(consume_reason),
    )


def _schedule_payload(schedule: WeeklySchedule) -> list[dict[str, Any]]:
    return [
        {
            "weekday": weekday,
            "windows": [
                {
                    "start": window.start.strftime("%H:%M"),
                    "end": window.end.strftime("%H:%M"),
                }
                for window in schedule.windows_for(weekday - 1)
            ],
        }
        for weekday in range(1, 8)
    ]


def _call_policy(config: AppConfig) -> dict[str, Any]:
    evaluated_at: datetime = config.now()
    current_override = config.current_override(evaluated_at)
    override_blocks_phone_hours = bool(
        current_override is not None and current_override.block_phone_hours
    )
    practice_open = config.practice_is_open(evaluated_at)
    phone_open = config.phone_is_open(evaluated_at)
    pharmacy_allowed = config.pharmacy_is_available(evaluated_at)
    specialist_allowed = config.specialist_is_available(evaluated_at)
    spoken = rendered_prompts(config)
    return {
        "protocol": CALL_POLICY_PROTOCOL,
        "evaluated_at": evaluated_at.isoformat(),
        "valid_for_ms": POLICY_VALID_FOR_MS,
        "timezone": str(config.practice.timezone),
        "practice_open": practice_open,
        "phone_open": phone_open,
        "greeting_open": practice_open and not override_blocks_phone_hours,
        "urgent_help_active": config.urgent_help_is_active(evaluated_at)
        or override_blocks_phone_hours,
        "override_active": current_override is not None,
        "override_blocks_phone_hours": override_blocks_phone_hours,
        "practice_queue_allowed": phone_open,
        "pharmacy_transfer_allowed": pharmacy_allowed,
        "specialist_transfer_allowed": specialist_allowed,
        "opening_hours": _schedule_payload(config.opening_hours),
        "phone_hours": _schedule_payload(config.phone_hours),
        "spoken_information": {
            "opening_hours": spoken["opening_hours"],
            "phone_hours": spoken["phone_hours"],
        },
        "dtmf": {
            "mode": "classic_handoff",
            "digits": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "#"],
        },
    }
