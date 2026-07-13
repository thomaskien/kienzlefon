# kienzlefon
# Version: 1.8
# Changelog:
# - 1.8: Versionsstand der erzeugten Asterisk-Dateien aktualisiert.
# - 1.7.1: Aktiviertes rotes Telefon als Mitglied der Sonderqueue aufgenommen.
# - 1.7: Sonderqueue, Penalty-Initialisierung und Caller-ID-Anzeige ergaenzt.
# - 1.6: Generierte Konfigurationskoepfe auf Kienzlefon 1.6 aktualisiert.
# - 1.5: Versionsstand der hochwertigen Ansagenaufnahme aktualisiert.
# - 1.4: Versionsstand des PIN-freien internen Ansagen-IVR aktualisiert.
# - 1.3: Internes Ansagen-IVR, Zusatztelefone und zentrale Wahlpruefung ergaenzt.
# - 1.2: Versionsstand der erzeugten Asterisk-Dateien aktualisiert.
# - 1.1: Aufnahmeabschluss und priorisierter Fallback des roten Telefons umgesetzt.
# - 1.0: Kienzlefax-kompatible PJSIP- und Dialplanfragmente eingefuehrt.

from __future__ import annotations

import os
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from .config import AppConfig, SipLineConfig


class AsteriskConfigError(RuntimeError):
    pass


def _asterisk_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;")


def _registration(name: str, context: str, line: SipLineConfig) -> str:
    if not line.enabled:
        return f"; {name}: keine separate externe Rufnummer konfiguriert.\n"
    proxy = ""
    if line.outbound_proxy:
        value = line.outbound_proxy
        if not value.startswith("sip:"):
            value = f"sip:{value}"
        proxy = f"outbound_proxy={value}\\;lr\n"
    return (
        f"""
[{name}-registration]
type=registration
transport=transport-udp
outbound_auth={name}-auth
server_uri=sip:{line.domain}
client_uri=sip:{line.user}@{line.domain}
contact_user={line.did}
retry_interval=60
forbidden_retry_interval=600
expiration={line.expiration}
line=yes
endpoint={name}-endpoint
{proxy}
[{name}-auth]
type=auth
auth_type=userpass
username={line.user}
password={_asterisk_value(line.password)}

[{name}-aor]
type=aor
contact=sip:{line.domain}

[{name}-endpoint]
type=endpoint
transport=transport-udp
context={context}
disallow=all
allow=g722,alaw,ulaw
outbound_auth={name}-auth
aors={name}-aor
direct_media=no
rewrite_contact=yes
rtp_symmetric=yes
force_rport=yes
from_user={line.user}
from_domain={line.domain}
send_pai=yes
send_rpid=yes
trust_id_inbound=yes
trust_id_outbound=yes
{proxy}""".strip()
        + "\n"
    )


def render_pjsip(config: AppConfig) -> str:
    red = config.ivr.red_extension
    red_endpoint = ""
    if config.ivr.red_enabled:
        red_endpoint = _local_endpoint(
            red,
            config.asterisk.red_password,
            "kienzlefon-red-local",
            "Rotes Telefon",
            config.asterisk.phone_transport,
        )
    else:
        red_endpoint = "; Rotes Telefon ist deaktiviert.\n"
    standalone = "\n".join(
        _local_endpoint(
            entry.extension,
            entry.password,
            "kienzlefon-standalone-local",
            f"Telefon {entry.extension}",
            config.asterisk.phone_transport,
        )
        for entry in config.standalone_extensions
    )
    return f"""; kienzlefon
; Version: 1.8
; Changelog:
; - 1.8: Versionsstand fuer Kienzlefon 1.8 aktualisiert.
; - 1.7.1: Rotes Telefon als zusaetzliches Sonderqueue-Mitglied vorbereitet.
; - 1.7: Rotes Telefon optional und Caller-ID-Routing vorbereitet.
; - 1.6: Versionsstand auf Kienzlefon 1.6 aktualisiert.
; - 1.5: Versionsstand auf Kienzlefon 1.5 aktualisiert.
; - 1.4: Interne Ansagenverwaltung ohne PIN aktualisiert.
; - 1.3: Zusaetzliche interne Telefone ausserhalb der Queue ergaenzt.
; - 1.2: Versionsstand auf Kienzlefon 1.2 aktualisiert.
; - 1.1: Versionsstand der PJSIP-Konfiguration aktualisiert.
; - 1.0: Rotes Telefon und optionale direkte Provider-Registrierungen.

{red_endpoint}

{standalone}

{_registration("kienzlefon-direct-queue", "kienzlefon-direct-queue-in", config.asterisk.direct_queue)}
{_registration("kienzlefon-direct-red", "kienzlefon-direct-red-in", config.asterisk.direct_red)}
"""


def _local_endpoint(
    extension: str, password: str, context: str, caller_name: str, transport: str
) -> str:
    return f"""[{extension}-auth]
type=auth
auth_type=userpass
username={extension}
password={_asterisk_value(password)}

[{extension}]
type=aor
max_contacts=1
remove_existing=yes
qualify_frequency=30

[{extension}]
type=endpoint
transport={transport}
context={context}
disallow=all
allow=g722,alaw,ulaw
auth={extension}-auth
aors={extension}
callerid={caller_name} <{extension}>
direct_media=no
rewrite_contact=yes
rtp_symmetric=yes
force_rport=yes
device_state_busy_at=1
"""


def _outbound_route(config: AppConfig, endpoint: str, caller_id: str) -> str:
    capacity = ""
    if config.asterisk.outbound_counts_capacity:
        capacity = """ same => n,Gosub(kfx_external_capacity,primary-phone,1)
 same => n,GotoIf($[\"${KFX_CAPACITY_OK}\"=\"1\"]?dial)
 same => n,Hangup(17)
"""
    return f"""exten => _XXX,1,NoOp(Kienzlefon ausgehend)
 same => n,Set(KZF_OUT_ENDPOINT={endpoint})
 same => n,Set(KZF_OUT_CALLERID={caller_id})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)
exten => _XXX.,1,NoOp(Kienzlefon ausgehend)
 same => n,Set(KZF_OUT_ENDPOINT={endpoint})
 same => n,Set(KZF_OUT_CALLERID={caller_id})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)
exten => _+X.,1,NoOp(Kienzlefon ausgehend)
 same => n,Set(KZF_OUT_ENDPOINT={endpoint})
 same => n,Set(KZF_OUT_CALLERID={caller_id})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)

[kienzlefon-outbound]
exten => _X.,1,AGI(/opt/kienzlefon/venv/bin/kienzlefon-wahlpruefung,--config,/etc/kienzlefon/kienzlefon.toml,--number,${{EXTEN}})
 same => n,GotoIf($["${{KZF_DIAL_ALLOWED}}"="1"]?capacity)
 same => n,Playback(kienzlefon/blocked_destination)
 same => n,Hangup()
 same => n(capacity),NoOp(Kienzlefon freigegebene Rufnummer ${{KZF_DIAL_NUMBER}})
{capacity} same => n(dial),Set(CALLERID(num)=${{KZF_DIAL_CALLERID}})
 same => n,Dial(PJSIP/${{KZF_DIAL_NUMBER}}@${{KZF_OUT_ENDPOINT}},120)
 same => n,Hangup()
"""


def render_extensions(config: AppConfig) -> str:
    red = config.ivr.red_extension
    specialist_description = (
        "Kienzlefon Fachstelle zum roten Telefon"
        if config.ivr.red_enabled
        else "Kienzlefon Fachstelle direkt in priorisierte Sonderqueue"
    )
    specialist_dial = f"Dial(PJSIP/{red},{config.ivr.red_ring_seconds})"
    specialist_queue = f"Queue({config.special_queue.name},r)"
    if config.ivr.specialist_announcement:
        specialist_dial = (
            f"Dial(PJSIP/{red},{config.ivr.red_ring_seconds},U(kienzlefon-specialist-agent))"
        )
        specialist_queue = f"Queue({config.special_queue.name},r,,kienzlefon/specialist_agent)"
    red_attempt = ""
    if config.ivr.red_enabled:
        red_attempt = f""" same => n,{specialist_dial}
 same => n,GotoIf($[\"${{DIALSTATUS}}\"=\"ANSWER\"]?done)
"""
    specialist_route = f"""{red_attempt} same => n,Set(QUEUE_PRIO={config.ivr.red_fallback_priority})
 same => n,{specialist_queue}
 same => n(done),Hangup()
"""
    red_endpoint = (
        "kienzlefon-direct-red-endpoint"
        if config.asterisk.direct_red.use_for_outbound
        else config.asterisk.main_outbound_endpoint
    )
    red_number = (
        config.asterisk.direct_red.did
        if config.asterisk.direct_red.use_for_outbound
        else config.asterisk.main_outbound_number
    )
    internal_routes = []
    first = config.asterisk.first_queue_extension
    for extension in range(first, first + config.asterisk.queue_extension_count):
        internal_routes.append(
            f"""exten => {extension},1,Dial(PJSIP/{extension},120)
 same => n,Hangup()
"""
        )
    all_local = [entry.extension for entry in config.standalone_extensions]
    if config.ivr.red_enabled:
        all_local.insert(0, config.ivr.red_extension)
    local_routes = "".join(
        f"exten => {extension},1,Dial(PJSIP/{extension},120)\n same => n,Hangup()\n"
        for extension in all_local
    )
    admin_route = f"""exten => {config.announcement_ivr.extension},1,Answer()
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-ansagen-ivr,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,Hangup()
"""
    return f"""; kienzlefon
; Version: 1.8
; Changelog:
; - 1.8: Versionsstand fuer Kienzlefon 1.8 aktualisiert.
; - 1.7.1: Fallback auf Sonderqueue einschliesslich rotem Telefon aktualisiert.
; - 1.7: Sonderqueue, Penalty-Initialisierung und Caller-ID-Anzeige ergaenzt.
; - 1.6: Versionsstand auf Kienzlefon 1.6 aktualisiert.
; - 1.5: Versionsstand auf Kienzlefon 1.5 aktualisiert.
; - 1.4: Interne Ansagenverwaltung ohne PIN aktualisiert.
; - 1.3: Ansagen-IVR 777, Zusatztelefone und Wahlpruefung ergaenzt.
; - 1.2: Versionsstand auf Kienzlefon 1.2 aktualisiert.
; - 1.1: Abschluss nach Aufnahme und Fallback des roten Telefons.
; - 1.0: IVR, Apothekenprioritaet, Fachstellen- und Direktrouting.

[kienzlefon-in]
exten => s,1,NoOp(Kienzlefon IVR)
 same => n,Set(CHANNEL(language)=de)
 same => n,Set(AGISIGHUP=no)
 same => n,Set(AGIEXITONHANGUP=no)
 same => n,Answer()
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-agi,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,Hangup()

[kienzlefon-pharmacy-queue]
exten => s,1,NoOp(Kienzlefon Apotheke in bestehende Praxisqueue)
 same => n,Set(QUEUE_PRIO={config.ivr.pharmacy_priority})
 same => n,Set(QUEUE_RAISE_PENALTY=0)
 same => n,Queue({config.ivr.queue_name},r,,kienzlefon/pharmacy_agent)
 same => n,Hangup()

[kienzlefon-specialist]
exten => s,1,NoOp({specialist_description})
{specialist_route}

[kienzlefon-specialist-agent]
exten => s,1,Playback(kienzlefon/specialist_agent)
 same => n,Return()

[kienzlefon-direct-queue-in]
exten => _X.,1,Gosub(kfx_external_capacity,primary-phone,1)
 same => n,GotoIf($[\"${{KFX_CAPACITY_OK}}\"=\"1\"]?accepted)
 same => n,Hangup(17)
 same => n(accepted),AGI(/opt/kienzlefon/venv/bin/kienzlefon-callerid,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,Goto(kfx-phone-queue,s,1)
exten => s,1,Goto(kienzlefon-direct-queue-in,{config.asterisk.direct_queue.did or "inbound-calls"},1)
exten => inbound-calls,1,Goto(kienzlefon-direct-queue-in,{config.asterisk.direct_queue.did or "inbound-calls"},1)

[kienzlefon-direct-red-in]
exten => _X.,1,Gosub(kfx_external_capacity,primary-phone,1)
 same => n,GotoIf($[\"${{KFX_CAPACITY_OK}}\"=\"1\"]?accepted)
 same => n,Hangup(17)
 same => n(accepted),AGI(/opt/kienzlefon/venv/bin/kienzlefon-callerid,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,Answer()
{specialist_route}
exten => s,1,Goto(kienzlefon-direct-red-in,{config.asterisk.direct_red.did or "inbound-calls"},1)
exten => inbound-calls,1,Goto(kienzlefon-direct-red-in,{config.asterisk.direct_red.did or "inbound-calls"},1)

[kienzlefon-red-local]
{"".join(internal_routes)}
{local_routes}
{admin_route}
{_outbound_route(config, red_endpoint, red_number)}

[kienzlefon-standalone-local]
{"".join(internal_routes)}
{local_routes}
{admin_route}
exten => _XXX,1,Set(KZF_OUT_ENDPOINT={config.asterisk.main_outbound_endpoint})
 same => n,Set(KZF_OUT_CALLERID={config.asterisk.main_outbound_number})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)
exten => _XXX.,1,Set(KZF_OUT_ENDPOINT={config.asterisk.main_outbound_endpoint})
 same => n,Set(KZF_OUT_CALLERID={config.asterisk.main_outbound_number})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)
exten => _+X.,1,Set(KZF_OUT_ENDPOINT={config.asterisk.main_outbound_endpoint})
 same => n,Set(KZF_OUT_CALLERID={config.asterisk.main_outbound_number})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)
"""


def render_queues(config: AppConfig) -> str:
    first = config.asterisk.first_queue_extension
    members = [
        str(extension) for extension in range(first, first + config.asterisk.queue_extension_count)
    ]
    if config.ivr.red_enabled:
        members.append(config.ivr.red_extension)
    members.extend(config.special_queue.additional_extensions)
    rendered_members = "\n".join(
        f"member => PJSIP/{extension},0,Telefon {extension},PJSIP/{extension}"
        for extension in dict.fromkeys(members)
    )
    return f"""; kienzlefon
; Version: 1.8
; Changelog:
; - 1.8: Versionsstand fuer Kienzlefon 1.8 aktualisiert.
; - 1.7.1: Aktiviertes rotes Telefon mit Penalty 0 in die Sonderqueue aufgenommen.
; - 1.7: Priorisierte Ringall-Sonderqueue fuer Fachstellen-Fallback eingefuehrt.

[{config.special_queue.name}]
strategy=ringall
weight={config.special_queue.weight}
autofill=yes
ringinuse=no
joinempty=yes
leavewhenempty=no
timeout=19
retry=1
{rendered_members}
"""


def install_asterisk_config(config: AppConfig, etc: Path = Path("/etc/asterisk")) -> None:
    pjsip_target = etc / "pjsip-kienzlefon.conf"
    extensions_target = etc / "extensions-kienzlefon.conf"
    queues_target = etc / "queues-kienzlefon.conf"
    _atomic_install(pjsip_target, render_pjsip(config))
    _atomic_install(extensions_target, render_extensions(config))
    _atomic_install(queues_target, render_queues(config))
    _ensure_include(etc / "pjsip.conf", '#tryinclude "/etc/asterisk/pjsip-kienzlefon.conf"')
    _ensure_include(
        etc / "extensions.conf", '#tryinclude "/etc/asterisk/extensions-kienzlefon.conf"'
    )
    _ensure_include(etc / "queues.conf", '#include "/etc/asterisk/queues-kienzlefon.conf"')
    _patch_kienzlefax_ivr_route(etc / "extensions-kfx-telefonie.conf")
    _patch_kienzlefax_queue_callerid(etc / "extensions-kfx-telefonie.conf")
    _patch_internal_routes(config, etc / "extensions-kfx-telefonie.conf")
    _patch_direct_did_routes(config, etc / "extensions-kfx-telefonie.conf", "kfx-phone-in")
    _patch_direct_did_routes(config, etc / "extensions.conf", "kfx-provider-in")
    _patch_queue_outbound(config, etc / "extensions-kfx-telefonie.conf")


def _atomic_install(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    _backup(path)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


def _ensure_include(path: Path, line: str) -> None:
    if not path.is_file():
        raise AsteriskConfigError(f"Kienzlefax-Konfiguration fehlt: {path}")
    text = path.read_text(encoding="utf-8")
    if line in text.splitlines():
        return
    _atomic_install(path, text.rstrip() + "\n\n" + line + "\n")


def _patch_kienzlefax_ivr_route(path: Path) -> None:
    if not path.is_file():
        raise AsteriskConfigError(f"Kienzlefax-Telefoniedialplan fehlt: {path}")
    original = "same => n(accepted),Goto(kfx-phone-queue,s,1)"
    replacement = "same => n(accepted),Goto(kienzlefon-in,s,1)"
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return
    if original not in text:
        raise AsteriskConfigError("Kienzlefax-IVR-Uebergabepunkt wurde nicht eindeutig gefunden")
    _atomic_install(path, text.replace(original, replacement, 1))


def _patch_kienzlefax_queue_callerid(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = (
        " same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-callerid,--config,"
        "/etc/kienzlefon/kienzlefon.toml)"
    )
    if marker in text or "[kfx-phone-queue]" not in text:
        return
    anchor = "exten => s,1,NoOp(KienzleFax Telefoniewarteschlange)"
    if anchor not in text:
        raise AsteriskConfigError(
            "Kienzlefax-Queuekontext fuer die Caller-ID-Anzeige wurde nicht eindeutig gefunden"
        )
    _atomic_install(path, text.replace(anchor, anchor + "\n" + marker, 1))


def _patch_internal_routes(config: AppConfig, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "; kienzlefon internal routes begin"
    extensions = [entry.extension for entry in config.standalone_extensions]
    if config.ivr.red_enabled:
        extensions.insert(0, config.ivr.red_extension)
    routes = "".join(
        f"exten => {extension},1,Dial(PJSIP/{extension},120)\n same => n,Hangup()\n"
        for extension in extensions
    )
    route = (
        f"{marker}\n{routes}"
        f"exten => {config.announcement_ivr.extension},1,Goto(kienzlefon-red-local,{config.announcement_ivr.extension},1)\n"
        "; kienzlefon internal routes end\n\n"
    )
    existing = re.compile(
        r"; kienzlefon internal routes begin\n.*?; kienzlefon internal routes end\n\n",
        re.S,
    )
    if existing.search(text):
        _atomic_install(path, existing.sub(route, text, count=1))
        return
    text = re.sub(
        r"; kienzlefon red extension [0-9]+\n.*?\n\n", "", text, count=1, flags=re.S
    )
    anchor = "exten => _X.,1,NoOp(KienzleFax Telefonie ausgehend)"
    if anchor not in text:
        raise AsteriskConfigError("Kienzlefax-Kontext fuer lokale Telefone wurde nicht gefunden")
    _atomic_install(path, text.replace(anchor, route + anchor, 1))


def _patch_direct_did_routes(config: AppConfig, path: Path, context: str) -> None:
    original_text = path.read_text(encoding="utf-8")
    text = original_text
    heading = f"[{context}]"
    if heading not in text:
        return
    text = re.sub(
        r"; kienzlefon direct did routes begin\n.*?"
        r"; kienzlefon direct did routes end\n",
        "",
        text,
        flags=re.S,
    )
    routes: list[str] = []
    for line, target in (
        (config.asterisk.direct_queue, "kienzlefon-direct-queue-in"),
        (config.asterisk.direct_red, "kienzlefon-direct-red-in"),
    ):
        if line.enabled and f"exten => {line.did},1,Goto({target},{line.did},1)" not in text:
            routes.append(f"exten => {line.did},1,Goto({target},{line.did},1)")
    if not routes:
        if text != original_text:
            _atomic_install(path, text)
        return
    insertion = (
        heading
        + "\n; kienzlefon direct did routes begin\n"
        + "\n".join(routes)
        + "\n; kienzlefon direct did routes end"
    )
    _atomic_install(path, text.replace(heading, insertion, 1))


def _patch_queue_outbound(config: AppConfig, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"exten => _X\.,1,NoOp\(KienzleFax Telefonie ausgehend\).*?"
        r"same => n,Dial\(PJSIP/\$\{EXTEN\}@[A-Za-z0-9_-]+,120\)",
        re.S,
    )
    if config.asterisk.direct_queue.use_for_outbound:
        endpoint = "kienzlefon-direct-queue-endpoint"
        caller_id = config.asterisk.direct_queue.did
    else:
        endpoint = config.asterisk.main_outbound_endpoint
        caller_id = config.asterisk.main_outbound_number
    replacement = (
        "; kienzlefon outbound routes begin\n"
        "exten => _XXX,1,NoOp(KienzleFax Telefonie ausgehend)\n"
        f" same => n,Set(KZF_OUT_ENDPOINT={endpoint})\n"
        f" same => n,Set(KZF_OUT_CALLERID={caller_id})\n"
        " same => n,Goto(kienzlefon-outbound,${EXTEN},1)\n"
        "exten => _XXX.,1,NoOp(KienzleFax Telefonie ausgehend)\n"
        f" same => n,Set(KZF_OUT_ENDPOINT={endpoint})\n"
        f" same => n,Set(KZF_OUT_CALLERID={caller_id})\n"
        " same => n,Goto(kienzlefon-outbound,${EXTEN},1)\n"
        "exten => _+X.,1,NoOp(KienzleFax Telefonie ausgehend)\n"
        f" same => n,Set(KZF_OUT_ENDPOINT={endpoint})\n"
        f" same => n,Set(KZF_OUT_CALLERID={caller_id})\n"
        " same => n,Goto(kienzlefon-outbound,${EXTEN},1)\n"
        "; kienzlefon outbound routes end"
    )
    existing = re.compile(
        r"; kienzlefon outbound routes begin\n.*?; kienzlefon outbound routes end", re.S
    )
    if existing.search(text):
        updated = existing.sub(replacement, text, count=1)
    elif pattern.search(text):
        updated = pattern.sub(replacement, text, count=1)
    else:
        raise AsteriskConfigError("Kienzlefax-Ausgangsroute wurde nicht eindeutig gefunden")
    if updated != text:
        _atomic_install(path, updated)


def _backup(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.old.kienzlefon.{stamp}"))
