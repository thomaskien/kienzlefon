"""Classify only confirmed external callers using one complete AMI view."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from .config import AppConfig
from .telephony_ami import AsteriskPlant, PJSIP
from .telephony_control import MAX_AGE_MS, UUID, SourceError, stamp

INGRESS = {"kfx-phone-in", "kfx-phone-overflow-in", "kienzlefon-direct-queue-in", "kienzlefon-direct-red-in"}


@dataclass(frozen=True)
class Identifiers:
    call: str
    owner: bool
    stage: str = ""


def classify(channels: dict[str, dict], identities: dict[str, Identifiers], bridge_members: dict[str, set[str]],
             waiting: set[str], ai_endpoints: set[str]) -> dict[str, int]:
    owners = {}
    for uniqueid, item in identities.items():
        if item.owner:
            if not UUID.fullmatch(item.call) or item.call in owners or item.stage not in {"ivr", "other"}:
                raise SourceError("Mehrdeutige Kennzeichnung eines externen Eingangs")
            owners[item.call] = uniqueid
    links = defaultdict(set)
    for peers in bridge_members.values():
        if not peers <= channels.keys():
            raise SourceError("Brücke und Kanalbestand widersprechen sich")
        for channel in peers:
            links[channel].update(peers - {channel})
    local_channels = defaultdict(set)
    for uniqueid, channel in channels.items():
        name = channel["channel"]
        if name.startswith("Local/") and name.endswith((";1", ";2")):
            local_channels[name[:-2]].add(uniqueid)
    for pair in local_channels.values():
        for channel in pair:
            links[channel].update(pair - {channel})
    if not waiting <= channels.keys():
        raise SourceError("Wartende Kanäle fehlen in der Kanalübersicht")
    waiting_calls = {identities[uid].call for uid in waiting if identities[uid].call}
    counters = {"waiting": 0, "ivr": 0, "ai": 0}
    for call_id, owner in owners.items():
        frontier = list(links[owner])
        visited = {owner}
        ai = human = False
        while frontier:
            uid = frontier.pop()
            if uid in visited:
                continue
            visited.add(uid)
            name = channels[uid]["channel"]
            if name.startswith("Local/"):
                frontier.extend(links[uid] - visited)
                continue
            match = PJSIP.fullmatch(name)
            if match and match[1] in ai_endpoints:
                ai = True
            elif name.startswith(("PJSIP/", "SIP/", "DAHDI/", "IAX2/")):
                human = True
            elif not name.startswith(("Announcer/", "Recorder/", "CBAnn/", "ConfBridge/")):
                raise SourceError("Unbekannter Brückenteilnehmer eines externen Eingangs")
        if human:
            continue
        if ai:
            counters["ai"] += 1
        elif call_id in waiting_calls:
            counters["waiting"] += 1
        elif identities[owner].stage == "ivr":
            counters["ivr"] += 1
    return counters


@dataclass(frozen=True)
class LiveSample:
    epoch: str
    generation: int
    monotonic: float
    wall: float
    counters: dict[str, int]


class LiveMonitor:
    def __init__(self, plant: AsteriskPlant):
        self.plant = plant
        self.snapshot: LiveSample | None = None
        self.reason = "synchronizing"

    def collect(self, config: AppConfig, epoch: str, process: str) -> None:
        started = time.monotonic()
        wall = time.time()
        generation = self.plant.topology_generation
        channels = self.plant.channels()
        identities = {}
        for uniqueid, channel in channels.items():
            name = channel["channel"]
            try:
                call_id = self.plant.variable(name, "KF_STATS_CALL_ID")
                owner = self.plant.variable(name, "KF_LIVE_OWNER")
                stage = self.plant.variable(name, "KF_LIVE_STAGE") if owner == "1" else ""
            except SourceError:
                _, changes = self.plant.events_since(generation)
                if ("hangup", uniqueid) in changes:
                    continue
                raise
            if (call_id and not UUID.fullmatch(call_id)) or owner not in {"", "1"}:
                raise SourceError("Unerwartete Kennzeichnung in der Kanalübersicht")
            endpoint = PJSIP.fullmatch(name)
            trunk = endpoint and (endpoint[1] in {config.asterisk.main_outbound_endpoint,
                  "kfx-phone-in-endpoint", "kfx-phone-overflow-in-endpoint", "kienzlefon-direct-queue-endpoint",
                  "kienzlefon-direct-red-endpoint"})
            if not owner and (channel.get("context") in INGRESS or (trunk and not call_id)):
                outbound = self.plant.variable(name, "KF_LIVE_OUTBOUND")
                if outbound != "1" and channel.get("context") not in {"kienzlefon-outbound", "kfx-phone-out", "kfx-phone-internal"}:
                    raise SourceError("Unmarkierter externer Kanal im Anlagenbestand")
            identities[uniqueid] = Identifiers(call_id, owner == "1", stage)
            if time.monotonic() - started >= 2:
                raise SourceError("Kanalbestand konnte nicht rechtzeitig bestätigt werden")
        waits = set()
        for queue in self.plant.queue_data(config).values():
            for row in queue:
                if row.get("event") == "QueueEntry":
                    if not row.get("uniqueid"):
                        raise SourceError("Unvollständiger Warteschlangeneintrag")
                    waits.add(row["uniqueid"])
        bridge_ids = {channel.get("bridgeid") for channel in channels.values()} - {None, ""}
        bridge_list = self.plant.bridges()
        bridges = {bridge: self.plant.bridge_members(bridge) for bridge in bridge_ids & bridge_list}
        version, events = self.plant.events_since(generation)
        ended = {uid for event, uid in events if event == "hangup" and uid}
        # Terminal events can be reconciled directly. For other transitions a
        # fresh complete read avoids blending queue and bridge states from two moments.
        if any(uid not in ended or event not in {"hangup", "bridgeleave", "queuecallerleave", "queuecallerabandon"}
               for event, uid in events):
            raise SourceError("Anlagenzustand hat sich während der Erfassung geändert")
        if ended:
            channels = {uid: channel for uid, channel in channels.items() if uid not in ended}
            identities = {uid: item for uid, item in identities.items() if uid not in ended}
            waits.difference_update(ended)
            bridges = {bridge: members - ended for bridge, members in bridges.items()}
        if any(uid not in bridges.get(bridge, set()) for uid, ch in channels.items() if (bridge := ch.get("bridgeid"))):
            raise SourceError("Brückenbestand hat sich während der Erfassung geändert")
        counters = classify(channels, identities, bridges, waits, set(config.ai_integration.extensions))
        if (version != self.plant.topology_generation or self.plant.process_key() != process
                or time.monotonic() - started >= 2):
            raise SourceError("Anlagenzustand hat sich während der Erfassung geändert")
        self.snapshot = LiveSample(epoch, version, started, wall, counters)

    def view(self, epoch: str | None) -> dict:
        sample = self.snapshot
        if not self.plant.connected:
            return self._unavailable(epoch, "source_disconnected")
        if sample and sample.epoch == epoch and sample.generation == self.plant.topology_generation:
            age = int((time.monotonic() - sample.monotonic) * 1000)
            if age < MAX_AGE_MS:
                return {"status": "current", "reason_code": None, "pbx_epoch": epoch, "as_of": stamp(sample.wall),
                        "age_ms": age, "max_age_ms": MAX_AGE_MS, **sample.counters}
            return self._unavailable(epoch, "stale")
        return self._unavailable(epoch, self.reason)

    @staticmethod
    def _unavailable(epoch: str | None, reason: str) -> dict:
        return {"status": "unavailable", "reason_code": reason, "pbx_epoch": epoch, "as_of": None,
                "age_ms": None, "max_age_ms": MAX_AGE_MS, "waiting": None, "ivr": None, "ai": None}
