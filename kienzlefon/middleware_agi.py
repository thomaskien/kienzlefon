"""Validate a click-to-dial request before using the existing outbound route."""
from __future__ import annotations

import argparse
import re
import uuid

from .agi import AgiChannel, AgiHangup
from .config import AppConfig, load_config
from .dialing import decide_number


def validate_call(config: AppConfig, *, request_id: str, client_id: str,
                  extension: str, endpoint: str, number: str) -> tuple[str, str, str]:
    options = config.middleware
    if not options.enabled or not options.click_to_dial:
        raise ValueError("Click-to-Dial deaktiviert")
    if extension not in options.extensions or endpoint != extension:
        raise ValueError("Nebenstelle nicht freigegeben oder Kanal passt nicht")
    if str(uuid.UUID(request_id)) != request_id.lower():
        raise ValueError("Ungueltige RequestId")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", client_id):
        raise ValueError("Ungueltige Client-ID")
    if not re.fullmatch(r"\+?[0-9]{3,32}", number):
        raise ValueError("Ungueltige Zielrufnummer")
    if number in config.local_extensions:
        raise ValueError("Click-to-Dial erwartet eine externe Zielrufnummer")
    decision = decide_number(config.dial_rules, number)
    if not decision.allowed:
        raise ValueError("Zielrufnummer nicht freigegeben")
    first = config.asterisk.first_queue_extension
    queue = {str(n) for n in range(first, first + config.asterisk.queue_extension_count)}
    route = config.asterisk.direct_queue if extension in queue else (
        config.asterisk.direct_red if extension == config.ivr.red_extension else None
    )
    if route is not None and route.enabled and route.use_for_outbound:
        prefix = "kienzlefon-direct-queue" if extension in queue else "kienzlefon-direct-red"
        return decision.normalized, prefix + "-endpoint", route.did
    return decision.normalized, config.asterisk.main_outbound_endpoint, config.asterisk.main_outbound_number


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/kienzlefon/kienzlefon.toml")
    args = parser.parse_args()
    channel = AgiChannel()
    try:
        channel.set_variable("KF_C2D_ALLOWED", "0")
        config = load_config(args.config)
        number, endpoint, caller_id = validate_call(
            config,
            request_id=channel.get_variable("KF_C2D_ID"),
            client_id=channel.get_variable("KF_C2D_CLIENT"),
            extension=channel.get_variable("KF_C2D_EXTENSION"),
            endpoint=channel.get_variable("CHANNEL(endpoint)"),
            number=channel.get_variable("KF_C2D_TARGET"),
        )
        channel.set_variable("KF_C2D_NUMBER", number)
        channel.set_variable("KZF_OUT_ENDPOINT", endpoint)
        channel.set_variable("KZF_OUT_CALLERID", caller_id)
        channel.set_variable("KF_C2D_ALLOWED", "1")
    except AgiHangup:
        return
    except Exception:
        # No patient number, AMI secret or full exception containing data in logs.
        try:
            channel.set_variable("KF_C2D_ALLOWED", "0")
        except AgiHangup:
            pass
