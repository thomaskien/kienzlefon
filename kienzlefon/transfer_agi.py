"""Authorize middleware transfers on the transferee/consultation channel."""
from __future__ import annotations

import argparse
import re
import uuid
from dataclasses import dataclass

from .agi import AgiChannel, AgiHangup
from .config import AppConfig, load_config
from .dialing import decide_number


def staff_extensions(config: AppConfig) -> tuple[str, ...]:
    """Only enabled, explicitly approved physical employee phones; no AI/service/fax."""
    first = config.asterisk.first_queue_extension
    phones = {str(n) for n in range(first, first + config.asterisk.queue_extension_count)}
    phones.update(entry.extension for entry in config.standalone_extensions)
    if config.ivr.red_enabled:
        phones.add(config.ivr.red_extension)
    return tuple(sorted(phones.intersection(config.middleware.extensions)))


@dataclass(frozen=True)
class TransferRoute:
    number: str
    endpoint: str
    caller_id: str


def validate_transfer(config: AppConfig, *, request_id: str, client_id: str,
                      extension: str, source_uid: str, mode: str,
                      target_type: str, target: str, dialed: str) -> TransferRoute:
    if not config.middleware.enabled or extension not in staff_extensions(config):
        raise ValueError("Mitarbeiter-Nebenstelle nicht fuer Vermittlung freigegeben")
    if str(uuid.UUID(request_id)) != request_id.lower():
        raise ValueError("Ungueltige RequestId")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", client_id):
        raise ValueError("Ungueltige Client-ID")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", source_uid):
        raise ValueError("Ungueltige Mitarbeiter-Uniqueid")
    if mode not in {"blind", "attended"} or target_type not in {"internal", "external"}:
        raise ValueError("Ungueltiger Vermittlungsmodus oder Zieltyp")
    if not re.fullmatch(r"[0-9]{2,32}", target) or target != dialed:
        raise ValueError("Vermittlungsziel stimmt nicht mit dem Dialplan-Ziel ueberein")
    if target_type == "internal":
        if target == extension or target not in staff_extensions(config):
            raise ValueError("Interne Zielnebenstelle nicht freigegeben")
        return TransferRoute(target, target, "")
    if target in config.local_extensions or not decide_number(config.dial_rules, target).allowed:
        raise ValueError("Externe Zielrufnummer nicht freigegeben")
    first = config.asterisk.first_queue_extension
    queue = {str(n) for n in range(first, first + config.asterisk.queue_extension_count)}
    route = config.asterisk.direct_queue if extension in queue else (
        config.asterisk.direct_red if extension == config.ivr.red_extension else None
    )
    if route is not None and route.enabled and route.use_for_outbound:
        prefix = "kienzlefon-direct-queue" if extension in queue else "kienzlefon-direct-red"
        return TransferRoute(target, prefix + "-endpoint", route.did)
    # Keep the original 00 prefix: the common outbound route normalizes exactly once.
    return TransferRoute(target, config.asterisk.main_outbound_endpoint,
                         config.asterisk.main_outbound_number)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/kienzlefon/kienzlefon.toml")
    args = parser.parse_args()
    channel = None
    try:
        channel = AgiChannel()
        channel.set_variable("KF_TRANSFER_ALLOWED", "0")
        config = load_config(args.config)
        route = validate_transfer(
            config,
            request_id=channel.get_variable("KF_TRANSFER_ID"),
            client_id=channel.get_variable("KF_TRANSFER_CLIENT"),
            extension=channel.get_variable("KF_TRANSFER_EXTENSION"),
            source_uid=channel.get_variable("KF_TRANSFER_SOURCE_UID"),
            mode=channel.get_variable("KF_TRANSFER_MODE"),
            target_type=channel.get_variable("KF_TRANSFER_TARGET_TYPE"),
            target=channel.get_variable("KF_TRANSFER_TARGET"),
            dialed=channel.environment.get("agi_extension", ""),
        )
        channel.set_variable("KF_TRANSFER_NUMBER", route.number)
        channel.set_variable("KZF_OUT_ENDPOINT", route.endpoint)
        channel.set_variable("KZF_OUT_CALLERID", route.caller_id)
        channel.set_variable("KF_TRANSFER_ALLOWED", "1")
    except AgiHangup:
        return
    except Exception:
        # Fail closed without including numbers or AMI credentials in logs.
        if channel is None:
            return
        try:
            channel.set_variable("KF_TRANSFER_ALLOWED", "0")
        except AgiHangup:
            pass
