"""Administrative routing settings and the protected plant API configuration."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppConfig

PBX_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
CLIENT = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
EXTENSION = re.compile(r"[0-9]{2,8}")
ROUTES = {"normal": "Normal", "specialist": "ROT"}


def boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("Für Rufgruppen ist ein Wahrheitswert erforderlich")
    return value


@dataclass(frozen=True)
class ControlConfig:
    enabled: bool = False
    bind: str = "127.0.0.1"
    port: int = 8767
    allowed_networks: tuple[str, ...] = ("127.0.0.1/32",)
    credentials_file: Path = Path("/etc/kienzlefon/control-identities.json")
    pbx_id: str = ""

    @classmethod
    def parse(cls, raw: object) -> ControlConfig:
        if not isinstance(raw, Mapping) or raw.keys() - cls.__dataclass_fields__.keys():
            raise ValueError("Unbekannte Einstellung unter [control_api]")
        values = cls()
        enabled = boolean(raw.get("enabled", values.enabled))
        bind = ipaddress.ip_address(raw.get("bind", values.bind))
        if bind.is_unspecified or bind.is_multicast or bind.is_global or bind.is_link_local:
            raise ValueError("Der Steuerungsdienst benötigt eine konkrete private oder Loopback-Adresse")
        port = raw.get("port", values.port)
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("Ungültiger Port für den Steuerungsdienst")
        networks = raw.get("allowed_networks", list(values.allowed_networks))
        if not isinstance(networks, list) or not networks or any(type(item) is not str for item in networks):
            raise ValueError("Quellnetze für den Steuerungsdienst fehlen")
        parsed = tuple(ipaddress.ip_network(item) for item in networks)
        if any(net.version != bind.version or net.prefixlen == 0 or not net.is_private for net in parsed):
            raise ValueError("Quellnetze müssen privat sein und zur Listener-Adresse passen")
        credentials = Path(raw.get("credentials_file", values.credentials_file))
        if not credentials.is_absolute():
            raise ValueError("Control-Schlüsseldatei muss einen absoluten Pfad haben")
        pbx_id = raw.get("pbx_id", values.pbx_id)
        if not isinstance(pbx_id, str) or ((enabled or pbx_id) and not PBX_ID.fullmatch(pbx_id)):
            raise ValueError("Stabile Anlagenkennung für den Steuerungsdienst erforderlich")
        return cls(enabled, str(bind), port, tuple(map(str, parsed)), credentials, pbx_id)


@dataclass(frozen=True)
class Membership:
    eligible: bool = False
    default_member: bool = False
    can_enable: bool = False
    can_disable: bool = False
    penalty: int = 0

    @classmethod
    def parse(cls, value: object, route: str) -> Membership:
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Rufgruppenfreigabe ist unvollständig")
        penalty = value["penalty"]
        if type(penalty) is not int or not 0 <= penalty <= (1000 if route == "normal" else 0):
            raise ValueError("Ungültige Rufstufe für " + ROUTES[route])
        membership = cls(**{key: boolean(value[key]) for key in cls.__dataclass_fields__ if key != "penalty"},
                         penalty=penalty)
        if not membership.eligible and (membership.default_member or membership.can_enable or membership.can_disable):
            raise ValueError("Eine gesperrte Nebenstelle darf keine Teilnahme oder Freigaben haben")
        return membership


@dataclass(frozen=True)
class RoutingPolicy:
    remote_enabled: bool = False
    members: Mapping[str, Mapping[str, Membership]] = field(default_factory=dict)
    workplace_mode: str = "all"
    workplace_ids: tuple[str, ...] = ()

    def permitted_clients(self, identity_clients: set[str] | None) -> set[str] | None:
        if self.workplace_mode == "all":
            return identity_clients
        selected = set(self.workplace_ids)
        return selected if identity_clients is None else selected.intersection(identity_clients)

    @classmethod
    def parse(cls, value: object) -> RoutingPolicy:
        if not isinstance(value, Mapping) or value.keys() - {"remote_enabled", "members", "workplace_mode", "workplace_ids"}:
            raise ValueError("Unbekannte Routing-Einstellung")
        members = value.get("members", {})
        if not isinstance(members, Mapping):
            raise ValueError("Rufgruppen-Mitgliedschaften müssen nach Nebenstelle gegliedert sein")
        parsed = {}
        for extension, routes in members.items():
            if not isinstance(extension, str) or not EXTENSION.fullmatch(extension):
                raise ValueError("Ungültige Nebenstelle in den Rufgruppen")
            if not isinstance(routes, Mapping) or set(routes) != ROUTES.keys():
                raise ValueError("Normal und ROT müssen je Nebenstelle angegeben werden")
            parsed[extension] = {route: Membership.parse(data, route) for route, data in routes.items()}
        mode = value.get("workplace_mode", "all")
        ids = value.get("workplace_ids", [])
        if (mode not in ("all", "selected") or not isinstance(ids, list) or len(ids) > 1024
                or any(not isinstance(client, str) or not CLIENT.fullmatch(client) for client in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("Ungültige Arbeitsplatz-Auswahl oder doppelte Platz-ID")
        return cls(boolean(value.get("remote_enabled", False)), parsed, mode, tuple(sorted(ids)))

    def export(self) -> dict:
        return {"remote_enabled": self.remote_enabled, "workplace_mode": self.workplace_mode,
                "workplace_ids": list(self.workplace_ids), "members": {
            extension: {route: asdict(member) for route, member in routes.items()}
            for extension, routes in self.members.items()
        }}

    def defaults(self) -> dict[str, set[str]]:
        return {route: {extension for extension, routes in self.members.items() if routes[route].default_member}
                for route in ROUTES}


def managed_phones(config: AppConfig) -> dict[str, str]:
    from .middleware import telephone_extensions

    labels = telephone_extensions(config)
    return {extension: label for extension, label in labels.items()
            if extension not in config.ai_integration.extensions}


def policy_for(config: AppConfig) -> RoutingPolicy:
    """Snapshot the installed defaults when the feature is first enabled."""
    policy = config.routing_policy
    phones = managed_phones(config)
    first = config.asterisk.first_queue_extension
    normal = {str(extension) for extension in range(first, first + config.asterisk.queue_extension_count)}
    specialist = normal | set(config.special_queue.additional_extensions)
    if config.ivr.red_enabled:
        specialist.add(config.ivr.red_extension)
    unknown = policy.members.keys() - phones.keys()
    if unknown:
        raise ValueError("Unbekannte Telefonnebenstelle in der Rufgruppenrichtlinie")
    members = {}
    for extension in phones:
        is_normal = extension in normal
        is_specialist = not policy.members and extension in specialist
        members[extension] = policy.members.get(extension, {
            "normal": Membership(eligible=is_normal, default_member=is_normal,
                                 penalty=int(extension) - first if is_normal else 0),
            "specialist": Membership(eligible=is_specialist, default_member=is_specialist),
        })
    result = RoutingPolicy(policy.remote_enabled, members, policy.workplace_mode, policy.workplace_ids)
    if config.control_api.enabled and any(not members for members in result.defaults().values()):
        raise ValueError("Normal und ROT brauchen jeweils mindestens ein Standardmitglied")
    return result
