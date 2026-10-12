"""Coordinate unanswered Queue member calls without touching answered channels.

Queue remains responsible for ordering, penalties, announcements and bridging.
Local members use Dial's *ringing* timeout to release phones before the oldest
caller's next cycle. No AMI Hangup or absolute channel lifetime is used.
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import time
from dataclasses import dataclass

from .agi import AgiChannel, AgiError, AgiHangup
from .config import AppConfig, load_config

LOGGER = logging.getLogger(__name__)
CHANNEL_NAME = re.compile(r"[A-Za-z0-9_./@;:+-]{1,255}")
MEMBER_CONTEXT = "kienzlefon-queue-member"


@dataclass(frozen=True)
class WaitingCall:
    channel: str
    entered: float


def ring_seconds(*, now: float, caller: WaitingCall, head: WaitingCall,
                 ring: int, retry: int) -> int:
    """Initial parallel offers share the head's deadline; later offers serialize.

    Round down to full seconds so an offer cannot overrun the common deadline.
    The retry interval leaves time for SIP CANCEL/device-state propagation before
    the head's next offer. Answering removes that caller from the native queue.
    """
    if ring < 2 or retry < 1 or not all(math.isfinite(value) for value in
                                     (now, caller.entered, head.entered)):
        raise ValueError("Ungueltige Queue-Zeitwerte")
    if head.entered > now or caller.entered > now:
        return 0
    cycle = ring + retry
    age = now - head.entered
    if caller.channel != head.channel and age >= ring:
        return 0
    # Every member, including the head itself, observes the same cycle boundary.
    remaining = ring - (age % cycle)
    return max(0, min(ring, math.floor(remaining)))


def member_interface(extension: str) -> str:
    # Optimize the Local channel away on answer: the physical PJSIP employee
    # channel keeps its transfer hooks and becomes the caller's direct peer.
    return f"Local/{extension}@{MEMBER_CONTEXT}"


def queue_members(config: AppConfig) -> set[str]:
    first = config.asterisk.first_queue_extension
    members = {str(value) for value in range(first, first + config.asterisk.queue_extension_count)}
    members.update(config.special_queue.additional_extensions)
    if config.ivr.red_enabled:
        members.add(config.ivr.red_extension)
    return members


def _head(channel: AgiChannel, queue: str) -> WaitingCall | None:
    name = channel.get_variable(f"QUEUE_GET_CHANNEL({queue},1)")
    if not name:
        return None
    if not CHANNEL_NAME.fullmatch(name):
        raise ValueError("Ungueltiger Queue-Kanalname")
    value = channel.get_variable(f"IMPORT({name},KF_QUEUE_ENTERED)")
    if not value:
        # A pre-update call has no marker. Hold new offers until it has left;
        # don't accidentally overtake it using a guessed timestamp.
        raise ValueError("Wartender Kanal ohne Queue-Zeitstempel")
    return WaitingCall(name, float(value))


def enter(channel: AgiChannel, config: AppConfig, queue: str, ring: int, retry: int) -> None:
    if queue not in {config.ivr.queue_name, config.special_queue.name}:
        raise ValueError("Unbekannte Warteschlange")
    name = channel.environment.get("agi_channel", "")
    if not CHANNEL_NAME.fullmatch(name) or not 2 <= ring <= 600 or not 1 <= retry <= 60:
        raise ValueError("Ungueltige Queue-Parameter")
    channel.set_variable("QUEUE_RAISE_PENALTY", "0")
    for key, value in {
        "KF_QUEUE_NAME": queue, "KF_QUEUE_CALLER": name,
        "KF_QUEUE_ENTERED": f"{time.time():.6f}",
        "KF_QUEUE_RING": str(ring), "KF_QUEUE_RETRY": str(retry),
    }.items():
        channel.set_variable("__" + key, value)


def offer(channel: AgiChannel, config: AppConfig, extension: str) -> int:
    if extension not in queue_members(config):
        raise ValueError("Telefon ist kein Queue-Mitglied")
    queue = channel.get_variable("KF_QUEUE_NAME")
    if queue not in {config.ivr.queue_name, config.special_queue.name}:
        raise ValueError("Unbekannte Warteschlange")
    caller = WaitingCall(channel.get_variable("KF_QUEUE_CALLER"),
                         float(channel.get_variable("KF_QUEUE_ENTERED")))
    if not CHANNEL_NAME.fullmatch(caller.channel):
        raise ValueError("Ungueltiger Anruferkanal")
    ring = int(channel.get_variable("KF_QUEUE_RING"))
    retry = int(channel.get_variable("KF_QUEUE_RETRY"))
    if not 2 <= ring <= 600 or not 1 <= retry <= 60:
        raise ValueError("Ungueltige Queue-Zeiten")
    for _attempt in range(3):
        # These are the same shared phones as in the native higher-weight queue.
        # A newly arrived red fallback must also block a still-starting offer.
        if queue == config.ivr.queue_name and channel.get_variable(
            f"QUEUE_GET_CHANNEL({config.special_queue.name},1)"
        ):
            return 0
        head = _head(channel, queue)
        if head is None:
            return 0
        if channel.get_variable(f"QUEUE_GET_CHANNEL({queue},1)") != head.channel:
            continue
        return ring_seconds(now=time.time(), caller=caller, head=head, ring=ring, retry=retry)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Unbeantwortete Queue-Rufzyklen koordinieren")
    parser.add_argument("mode", choices=("enter", "offer"))
    parser.add_argument("--config", default="/etc/kienzlefon/kienzlefon.toml")
    parser.add_argument("--queue", default="")
    parser.add_argument("--ring", type=int, default=19)
    parser.add_argument("--retry", type=int, default=1)
    parser.add_argument("--extension", default="")
    args = parser.parse_args()
    try:
        channel = AgiChannel()
        channel.set_variable("KF_QUEUE_RING_SECONDS", "0")
        config = load_config(args.config)
        if args.mode == "enter":
            enter(channel, config, args.queue, args.ring, args.retry)
        else:
            seconds = offer(channel, config, args.extension)
            channel.set_variable("KF_QUEUE_RING_SECONDS", str(seconds))
    except AgiHangup:
        pass
    except (ValueError, OSError, AgiError) as exc:
        LOGGER.error("Queue-Rufversuch nicht freigegeben: %s", exc)


def render_member_context() -> str:
    return f"""
; Local channels only bound the unanswered Dial attempt, never an active call.
[{MEMBER_CONTEXT}]
exten => _X.,1,Set(KF_QUEUE_RING_SECONDS=0)
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-queue-dispatch,offer,--config,/etc/kienzlefon/kienzlefon.toml,--extension,${{EXTEN}})
 same => n,GotoIf($[${{KF_QUEUE_RING_SECONDS}}>0]?dial)
 same => n,Hangup(19)
 same => n(dial),Dial(PJSIP/${{EXTEN}},${{KF_QUEUE_RING_SECONDS}})
 same => n,Hangup()
exten => h,1,NoOp(Kienzlefon Queue-Rufversuch beendet)
"""
