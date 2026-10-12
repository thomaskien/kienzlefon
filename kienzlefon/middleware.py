"""Version 2.5.3: optional AMI access and its public configuration contract.

AMI grants action categories, not per-variable/per-context capabilities. The
middleware is a trusted server; browser/workstation credentials must never be
AMI credentials. KF_PHONE_* names are a protocol convention, not an ACL.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppConfig

CONNECTION_FILENAME = "middleware-connection.toml"
LEGACY_CONNECTION_FILENAME = "middleware-connection.json"

MANAGED = "manager_kienzlefon_middleware.conf"
START = "; kienzlefon middleware listener begin"
END = "; kienzlefon middleware listener end"


@dataclass(frozen=True)
class MiddlewareConfig:
    enabled: bool = False
    source_ip: str = "127.0.0.1"
    server_ip: str = "127.0.0.1"
    port: int = 5038
    username: str = "kienzlefon-middleware"
    transport: str = "tcp"
    lookup: bool = False
    lookup_available: bool = False
    click_to_dial: bool = False
    extensions: tuple[str, ...] = ()
    ring_timeout_ms: int = 20000

    @property
    def all_sources(self) -> bool:
        return self.source_ip == "*"

    @classmethod
    def parse(cls, raw: Mapping) -> MiddlewareConfig:
        if not isinstance(raw, dict):
            raise ValueError("[middleware] muss eine Tabelle sein")
        for key in ("aktiv", "namensaufloesung", "lookup_verfuegbar", "click_to_dial"):
            if key in raw and not isinstance(raw[key], bool):
                raise ValueError(f"[middleware].{key} muss true oder false sein")
        for key in ("port", "klingel_timeout_ms"):
            if key in raw and type(raw[key]) is not int:
                raise ValueError(f"[middleware].{key} muss eine ganze Zahl sein")
        values = raw.get("nebenstellen", [])
        if not isinstance(values, list) or any(
            not isinstance(x, str) or not re.fullmatch(r"[0-9]{2,8}", x) for x in values
        ) or len(set(values)) != len(values):
            raise ValueError("[middleware].nebenstellen: eindeutige Telefonnummern erwartet")
        result = cls(
            enabled=raw.get("aktiv", False),
            source_ip=str(raw.get("quell_ip", "127.0.0.1")),
            server_ip=str(raw.get("server_ip", "127.0.0.1")),
            port=int(raw.get("port", 5038)),
            username=str(raw.get("benutzer", "kienzlefon-middleware")),
            transport=str(raw.get("transport", "tcp")),
            lookup=raw.get("namensaufloesung", False),
            lookup_available=raw.get("lookup_verfuegbar", False),
            click_to_dial=raw.get("click_to_dial", False),
            extensions=tuple(values),
            ring_timeout_ms=int(raw.get("klingel_timeout_ms", 20000)),
        )
        addresses = [("server_ip", result.server_ip)]
        if not result.all_sources:
            addresses.append(("quell_ip", result.source_ip))
        for name, value in addresses:
            address = ipaddress.ip_address(value)
            if address.is_unspecified or address.is_multicast or str(address) == "255.255.255.255":
                raise ValueError(f"[middleware].{name}: konkrete Unicast-IP erforderlich")
        if not result.all_sources and (
            ipaddress.ip_address(result.source_ip).version != ipaddress.ip_address(result.server_ip).version
        ):
            raise ValueError("Middleware-Quelle und AMI-Ziel muessen dieselbe IP-Familie verwenden")
        if not 1 <= result.port <= 65535 or not 1000 <= result.ring_timeout_ms <= 120000:
            raise ValueError("Middleware-Port oder Klingel-Timeout ausserhalb des erlaubten Bereichs")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", result.username):
            raise ValueError("Ungueltiger AMI-Benutzername")
        if result.username.lower() == "general" or result.transport not in {"tcp", "tls"}:
            raise ValueError("Ungueltiger AMI-Benutzer oder Transport")
        return result


def telephone_extensions(config: AppConfig) -> dict[str, str]:
    result = {
        str(n): "Telefon (Praxisqueue)"
        for n in range(config.asterisk.first_queue_extension,
                       config.asterisk.first_queue_extension + config.asterisk.queue_extension_count)
    }
    if config.ivr.red_enabled:
        result[config.ivr.red_extension] = "Rotes Telefon"
    result.update({entry.extension: "Zusaetzliches Telefon" for entry in config.standalone_extensions})
    result.update({extension: "KI-Nebenstelle" for extension in config.ai_integration.extensions})
    return result


def private_write(path: Path, content: str, mode: int = 0o600) -> None:
    """Never create a world-readable temporary copy of a secret."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        if path.exists():
            stat = path.stat()
            if os.geteuid() == 0:
                os.fchown(fd, stat.st_uid, stat.st_gid)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def backup(path: Path) -> None:
    if path.exists():
        target = path.with_name(path.name + ".bak." + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
        private_write(target, path.read_text(encoding="utf-8"))


def manager_inventory(path: Path, seen: frozenset[Path] = frozenset()) -> tuple[dict[str, str], set[str]]:
    """Inspect includes without executing #exec. Refuse ambiguous dynamic configuration."""
    lines: list[str] = []

    def expand(current: Path, visited: frozenset[Path]) -> None:
        resolved = current.resolve()
        if resolved in visited:
            raise ValueError("Zyklische AMI-Includes: " + str(current))
        if not current.exists():
            return
        for line in current.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#exec"):
                raise ValueError("AMI verwendet #exec; Listener vorab manuell konfigurieren")
            match = re.match(r'^#(tryinclude|include)\s+["<]?([^">]+)[">]?\s*$', stripped)
            if match:
                value = match[2].strip()
                include = Path(value)
                if not include.is_absolute():
                    include = current.parent / include
                import glob
                paths = sorted(Path(p) for p in glob.glob(str(include)))
                if not paths and match[1] == "include":
                    raise ValueError("AMI-Include fehlt: " + str(include))
                for child in paths:
                    if child.name != MANAGED:
                        expand(child, visited | {resolved})
                continue
            lines.append(line)

    expand(path, seen)
    general: dict[str, str] = {}
    users: set[str] = set()
    section = ""
    for line in lines:
        line = line.split(";", 1)[0].strip()
        header = re.match(r"^\[([^]]+)\](.*)$", line)
        if header:
            section = header[1]
            if section.lower() != "general":
                users.add(section)
            continue
        if section.lower() == "general" and "=" in line:
            key, value = line.split("=", 1)
            general[key.strip().lower()] = value.lstrip(">").strip()
    return general, users


def _bound_to(binding: str, address: str) -> bool:
    try:
        bound = ipaddress.ip_address(binding)
        target = ipaddress.ip_address(address)
        return bound == target or (bound.is_unspecified and bound.version == target.version)
    except ValueError:
        return False


def _tls_address(binding: str) -> tuple[str, int]:
    if binding.startswith("["):
        host, _, port = binding[1:].partition("]:")
    else:
        host, _, port = binding.rpartition(":")
    return host, int(port or 5039)


def _check_all_source_bindings(config: MiddlewareConfig, general: Mapping[str, str],
                               tcp_binding: str) -> None:
    """The user ACL applies to every AMI transport, including HTTP and TLS."""
    if not config.all_sources:
        return
    truth = {"yes", "true", "on", "1"}
    if general.get("webenabled", "no").lower() in truth:
        raise ValueError('quell_ip="*" erfordert deaktiviertes Web-AMI (webenabled=no)')
    bindings = [tcp_binding]
    if general.get("tlsenable", "no").lower() in truth:
        # Asterisk defaults TLS to bindaddr with port 5039.
        tls_binding = general.get("tlsbindaddr")
        bindings.append(_tls_address(tls_binding)[0] if tls_binding else tcp_binding)
    target = ipaddress.ip_address(config.server_ip)
    for binding in bindings:
        try:
            matches = ipaddress.ip_address(binding) == target
        except ValueError:
            matches = False
        if not matches:
            raise ValueError(
                'quell_ip="*" erfordert alle AMI-Listener ausschliesslich an server_ip '
                f'({config.server_ip}); vorhandene Bindadresse {binding} zuerst abstimmen'
            )


def listener_plan(config: MiddlewareConfig, manager: Path) -> str:
    original = manager.read_text(encoding="utf-8") if manager.exists() else "[general]\n"
    general, users = manager_inventory(manager)
    if config.username in users:
        raise ValueError("AMI-Benutzer existiert ausserhalb der verwalteten Datei: " + config.username)
    truth = {"yes", "true", "on", "1"}
    enabled = general.get("enabled", "no").lower() in truth
    if general.get("disabledevents", "").strip():
        raise ValueError("Globale AMI-disabledevents pruefen: benoetigte Ereignisse duerfen nicht fehlen")
    tcp_binding = general.get("bindaddr", "0.0.0.0") if enabled or users else config.server_ip
    _check_all_source_bindings(config, general, tcp_binding)
    if config.transport == "tls":
        if not enabled or general.get("tlsenable", "no").lower() not in truth:
            raise ValueError("AMI-TLS muss bereits mit gueltigem Zertifikat eingerichtet sein")
        binding = general.get("tlsbindaddr")
        host, port = _tls_address(binding) if binding else (tcp_binding, 5039)
        if not _bound_to(host, config.server_ip) or port != config.port:
            raise ValueError("AMI-Ziel passt nicht zum vorhandenen TLS-Listener")
        return original
    if enabled:
        if int(general.get("port", "5038")) != config.port or not _bound_to(
            general.get("bindaddr", "0.0.0.0"), config.server_ip
        ):
            raise ValueError(
                "Bestehender AMI-Listener passt nicht zum gewaehlten Ziel. "
                "Bindadresse/Port vorab fuer alle vorhandenen Clients abstimmen; keine automatische Umstellung."
            )
        return original
    # A disabled listener with configured users must not silently change their address/port.
    if users and (int(general.get("port", "5038")) != config.port or not _bound_to(
        general.get("bindaddr", "0.0.0.0"), config.server_ip
    )):
        raise ValueError("Vorhandene AMI-Benutzer: Listener-Konflikt vor Aktivierung aufloesen")
    binding = general.get("bindaddr", config.server_ip) if users else config.server_ip
    block = f"{START}\n[general](+)\nenabled=yes\nport={config.port}\nbindaddr={binding}\n{END}"
    clean = re.sub(re.escape(START) + r".*?" + re.escape(END), "", original, flags=re.DOTALL).rstrip()
    if not re.search(r"^\[general\]", clean, re.MULTILINE):
        clean += "\n[general]\n"
    return clean + "\n\n" + block + "\n"


def read_connection(directory: Path) -> dict | None:
    """Read TOML preferentially; accept the 2.5.0 JSON only for migration."""
    target = directory / CONNECTION_FILENAME
    legacy = directory / LEGACY_CONNECTION_FILENAME
    if target.exists():
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    elif legacy.exists():
        data = json.loads(legacy.read_text(encoding="utf-8"))
    else:
        return None
    if not isinstance(data, dict):
        raise ValueError("Middleware-Uebergabedatei muss eine Konfigurationstabelle enthalten")
    return data


def render_connection(data: Mapping) -> str:
    """Serialize the small versioned export schema without a new runtime dependency."""
    def literal(value):
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, list):
            return "[" + ", ".join(literal(item) for item in value) + "]"
        raise ValueError("Nicht unterstuetzter Datentyp im Middleware-Export")

    def key(value):
        return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else literal(value)

    lines = ["# Kienzlefon AMI-Konfiguration; enthaelt geheime Zugangsdaten."]
    def table(values, prefix=()):
        for name, value in values.items():
            # TOML has no null; missing optional ufw_rule has the same meaning.
            if not isinstance(value, Mapping) and value is not None:
                lines.append(f"{key(name)} = {literal(value)}")
        for name, value in values.items():
            if isinstance(value, Mapping):
                path = (*prefix, name)
                lines.extend(("", "[" + ".".join(key(part) for part in path) + "]"))
                table(value, path)
    table(data)
    result = "\n".join(lines) + "\n"
    tomllib.loads(result)
    return result


def write_connection(directory: Path, data: Mapping) -> Path:
    target = directory / CONNECTION_FILENAME
    private_write(target, render_connection(data))
    legacy = directory / LEGACY_CONNECTION_FILENAME
    if legacy.exists():
        # Retain a root-only recovery copy; never leave an active, stale JSON export.
        backup(legacy)
        legacy.unlink()
    return target


def provision(config: AppConfig, etc: Path = Path("/etc/asterisk"), *, rotate: bool = False) -> Path:
    options = config.middleware
    config_dir = config.source.parent
    export = config_dir / CONNECTION_FILENAME
    previous = read_connection(config_dir)
    secret_path = config_dir / "middleware-secret"
    manager = etc / "manager.conf"
    managed = etc / MANAGED
    manager_existed = manager.exists()
    if not options.enabled:
        if managed.exists():
            private_write(managed, "; Kienzlefon-Middleware deaktiviert.\n", 0o640)
        if previous is not None:
            previous["enabled"] = False
            write_connection(config_dir, previous)
        return export
    planned = listener_plan(options, manager)  # Validate BEFORE writing secrets or changing listener.
    saved_secret = (previous or {}).get("ami", {}).get("secret")
    if secret_path.exists():
        saved_secret = secret_path.read_text().strip()
    secret = saved_secret if saved_secret and not rotate else secrets.token_urlsafe(32)
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", secret):
        raise ValueError("Ungueltiges gespeichertes Middleware-Secret; ausdruecklich erneuern")
    if options.all_sources:
        # Keep the other address family denied; the listener is bound to one exact IP.
        acl = "0.0.0.0/0" if ipaddress.ip_address(options.server_ip).version == 4 else "::/0"
    else:
        source = ipaddress.ip_address(options.source_ip)
        acl = f"{source}/{source.max_prefixlen}"
    content = (
        "; Verwaltet von Kienzlefon; Zugangsdaten nicht protokollieren.\n"
        f"[{options.username}]\nsecret={secret}\n"
        "deny=0.0.0.0/0\ndeny=::/0\n"
        f"permit={acl}\nread=system,call,agent,user,dialplan\n"
        "write=call,originate,reporting\n"
    )
    include = f'#include "{managed}"'
    # Remove only our exact include forms, then add exactly one absolute include.
    planned = re.sub(r'^\s*#(?:tryinclude|include)\s+["<]?(?:[^\n"<>]*/)?'
                     + re.escape(MANAGED) + r'[">]?\s*$', "", planned, flags=re.MULTILINE).rstrip()
    planned += "\n\n" + include + "\n"
    private_write(secret_path, secret + "\n")
    if not managed.exists() or managed.read_text() != content:
        backup(managed)
        private_write(managed, content, 0o640)
    if not manager.exists() or manager.read_text() != planned:
        backup(manager)
        private_write(manager, planned, (manager.stat().st_mode & 0o777) if manager.exists() else 0o640)
    if os.geteuid() == 0:
        # Follow the Asterisk configuration's group, never make the secret world-readable.
        import grp
        try:
            gid = grp.getgrnam("asterisk").gr_gid
        except KeyError:
            gid = (etc / "asterisk.conf").stat().st_gid if (etc / "asterisk.conf").exists() else etc.stat().st_gid
        os.chown(managed, 0, gid)
        # A newly created manager.conf has no foreign ownership to preserve.
        if not manager_existed:
            os.chown(manager, manager.stat().st_uid, gid)
    data = {
        "schema_version": 1, "enabled": True,
        "ami": {"host": options.server_ip, "port": options.port, "transport": options.transport,
                "username": options.username, "secret": secret, "events": "on"},
        "allowed_source_ip": options.source_ip,
        "lookup": {"enabled": options.lookup and options.lookup_available, "budget_ms": 1000},
        "click_to_dial": {"enabled": options.click_to_dial,
                          "context": "kienzlefon-click-to-dial", "extensions": list(options.extensions),
                          "ring_timeout_ms": options.ring_timeout_ms},
    }
    if previous and previous.get("ufw_rule"):
        data["ufw_rule"] = previous["ufw_rule"]
    write_connection(config_dir, data)
    return export
