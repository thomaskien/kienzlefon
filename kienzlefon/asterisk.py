# kienzlefon
# Version: 2.5.5
# Changelog:
# - 2.4.4: KI-Endpunkte dauerhaft auf G.722 mit lokaler Codec-Praeferenz festgelegt.
# - 2.4.0: Lautlosen AI-Neuversuch ueber Taste 0 im klassischen Hauptmenue ergaenzt.
# - 2.3.2: AI-Medienbridge sofort gestartet und Taste 0 als direkter AI-Shortcut belegt.
# - 2.3: AI-Handoff, Menue-Admission, Assistentenansage und DTMF-Rueckkehr integriert.
# - 2.2: AI-Nebenstellen, interne Ziele und lease-gesteuertes Routing integriert.
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
import tempfile
from datetime import datetime
from pathlib import Path

from .config import AppConfig, SipLineConfig
from .hold_music import MUSIC_CLASS
from .middleware_dialplan import render_middleware
from .queue_dialplan import (
    RULE_NAME,
    decorate_entries,
    decorate_members,
    practice_timing,
    render_rules,
    unwrap,
    validate_rules_include,
)
from .queue_dispatch import member_interface, render_member_context
from .queue_prompts import ASTERISK_QUEUE_LANGUAGE, QUEUE_PHRASES, phrase_path
from .transfer_dialplan import decorate_calls, render_transfer
from .transfer_features import DEFAULT_TRANSFER_FEATURES, resolve_transfer_features


class AsteriskConfigError(RuntimeError):
    pass


AI_DTMF_FEATURES = tuple(
    (f"kzf_ai_dtmf_{digit}", digit, digit) for digit in "0123456789"
) + (
    ("kzf_ai_dtmf_star", "*", "*"),
    ("kzf_ai_dtmf_hash", "#", "#"),
)


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
    ai_endpoints = "\n".join(
        _ai_endpoint(extension, password, config.asterisk.phone_transport)
        for extension, password in zip(
            config.ai_integration.extensions,
            config.ai_integration.sip_passwords,
            strict=True,
        )
    )
    return f"""; kienzlefon
; Version: 2.5.5
; Changelog:
; - 2.4.4: Nur KI-Endpunkte nutzen G.722 und local_first fuer beide Anrufrichtungen.
; - 2.3: PJSIP-Endpunkte fuer den lokalen Handoff-Pfad freigegeben.
; - 2.2: AI-Slotendpunkte mit Busy-on-Busy und deaktiviertem direct_media ergaenzt.
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

{ai_endpoints}

{_registration("kienzlefon-direct-queue", "kienzlefon-direct-queue-in", config.asterisk.direct_queue)}
{_registration("kienzlefon-direct-red", "kienzlefon-direct-red-in", config.asterisk.direct_red)}
"""


def render_features() -> str:
    entries = "\n".join(
        f'{name} = {activation},self,Gosub,"kienzlefon-ai-dtmf,s,1({digit})"'
        for name, activation, digit in AI_DTMF_FEATURES
    )
    return f"""; kienzlefon
; Version: 2.3
; Changelog:
; - 2.3: Alle DTMF-Zeichen im AI-Gespraech auf den klassischen Menuepfad gelegt.

[applicationmap]
{entries}
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


def _ai_endpoint(extension: str, password: str, transport: str) -> str:
    return f"""[{extension}-auth]
type=auth
auth_type=userpass
username={extension}
password={_asterisk_value(password)}

[{extension}]
type=aor
max_contacts=1
remove_existing=yes
qualify_frequency=10

[{extension}]
type=endpoint
transport={transport}
context=kienzlefon-ai-endpoint-in
disallow=all
allow=g722
incoming_call_offer_pref=local_first
outgoing_call_offer_pref=local_first
auth={extension}-auth
aors={extension}
callerid=Kienzlefon AI {extension} <{extension}>
direct_media=no
rewrite_contact=yes
rtp_symmetric=yes
force_rport=yes
device_state_busy_at=1
"""


def _outbound_route(config: AppConfig, endpoint: str, caller_id: str) -> str:
    capacity = ""
    transfer_failed = (
        " same => n,Gosub(kienzlefon-transfer-progress,s,1(failed))\n"
        if config.middleware.enabled else ""
    )
    if config.asterisk.outbound_counts_capacity:
        capacity = """ same => n,Gosub(kfx_external_capacity,primary-phone,1)
 same => n,GotoIf($[\"${KFX_CAPACITY_OK}\"=\"1\"]?dial)
""" + transfer_failed + " same => n,Hangup(17)\n"
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
exten => _X.,1,Set(KZF_DIAL_ALLOWED=0)
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-wahlpruefung,--config,/etc/kienzlefon/kienzlefon.toml,--number,${{EXTEN}})
 same => n,GotoIf($["${{KZF_DIAL_ALLOWED}}"="1"]?capacity)
{transfer_failed} same => n,Playback(kienzlefon/blocked_destination)
 same => n,Hangup()
 same => n(capacity),NoOp(Kienzlefon freigegebene Rufnummer ${{KZF_DIAL_NUMBER}})
{capacity} same => n(dial),Set(CALLERID(num)=${{KZF_DIAL_CALLERID}})
 same => n,Dial(PJSIP/${{KZF_DIAL_NUMBER}}@${{KZF_OUT_ENDPOINT}},120)
 same => n,Hangup()
"""


def _queue_options(config: AppConfig, options: str = "r") -> str:
    if config.hold_music.mode == "musik":
        return options.replace("r", "").replace("R", "")
    return options


def render_extensions(config: AppConfig, features: dict[str, str] | None = None,
                      timing: tuple[int, int] = (19, 1)) -> str:
    red = config.ivr.red_extension
    specialist_description = (
        "Kienzlefon Fachstelle zum roten Telefon"
        if config.ivr.red_enabled
        else "Kienzlefon Fachstelle direkt in priorisierte Sonderqueue"
    )
    specialist_dial = f"Dial(PJSIP/{red},{config.ivr.red_ring_seconds})"
    queue_options = _queue_options(config)
    specialist_queue = f"Queue({config.special_queue.name},{queue_options})"
    if config.ivr.specialist_announcement:
        specialist_dial = (
            f"Dial(PJSIP/{red},{config.ivr.red_ring_seconds},U(kienzlefon-specialist-agent))"
        )
        specialist_queue = (
            f"Queue({config.special_queue.name},{queue_options},,kienzlefon/specialist_agent)"
        )
    red_attempt = ""
    if config.ivr.red_enabled:
        red_attempt = f""" same => n,{specialist_dial}
 same => n,GotoIf($[\"${{DIALSTATUS}}\"=\"ANSWER\"]?done)
"""
    specialist_route = f"""{red_attempt} same => n,Set(QUEUE_PRIO={config.ivr.red_fallback_priority})
 same => n,Set(CHANNEL(language)={ASTERISK_QUEUE_LANGUAGE})
 same => n,{specialist_queue}
 same => n,Gosub(kienzlefon-ai-queue-fallback,s,1)
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
    internal_targets = [str(value) for value in range(8800, 8805)]
    if config.hold_music.installed:
        internal_targets.append("8805")
    internal_targets.extend(config.ai_integration.extensions)
    ai_local_routes = "".join(
        f"exten => {extension},1,Goto(kienzlefon-internal-targets,{extension},1)\n"
        for extension in internal_targets
    )
    ai_specific_routes = "".join(
        f"""exten => {extension},1,NoOp(Kienzlefon AI Direktwahl {slot_id})
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-admission,--config,/etc/kienzlefon/kienzlefon.toml,--selection,specific,--slot-id,{slot_id})
 same => n,GotoIf($["${{KZF_AI_ACCEPTED}}"="1"]?dial:busy)
 same => n(dial),Gosub(kienzlefon-ai-dial,s,1)
 same => n,GotoIf($["${{KZF_AI_DTMF_HANDOFF}}"="1"]?classic)
 same => n,GotoIf($["${{KZF_AI_DIAL_FAILED}}"="1"]?busy:done)
 same => n(classic),Set(KZF_IVR_INITIAL_DIGIT=${{KZF_AI_DTMF_DIGIT}})
 same => n,Set(__KZF_AI_HANDOFF_DONE=1)
 same => n,Goto(kienzlefon-classic-menu,s,1)
 same => n(busy),Busy(1)
 same => n(done),Hangup()
"""
        for slot_id, extension in zip(
            config.ai_integration.slot_ids, config.ai_integration.extensions, strict=True
        )
    )
    ai_enabled = "1" if config.ai_integration.admission_enabled else "0"
    ai_dtmf_features = "#".join(name for name, _activation, _digit in AI_DTMF_FEATURES)
    queue_failure_checks = "\n".join(
        f' same => n,GotoIf($["${{QUEUESTATUS}}"="{status}"]?fallback)'
        for status in (
            "TIMEOUT",
            "FULL",
            "JOINEMPTY",
            "LEAVEEMPTY",
            "JOINUNAVAIL",
            "LEAVEUNAVAIL",
        )
    )
    preview_route = ""
    if config.hold_music.installed:
        preview_route = f"""exten => 8805,1,Answer()
 same => n,MusicOnHold({MUSIC_CLASS})
 same => n,Hangup()
"""
    rendered = f"""; kienzlefon
; Version: 2.4.0
; Changelog:
; - 2.4.0: Taste 0 im Hauptmenue versucht AI ohne Ansage und ohne AI-Rekursion.
; - 2.3.2: AI-Medienbridge sofort gestartet und Taste 0 als direkter AI-Shortcut belegt.
; - 2.3: AI erst vor dem Hauptmenue zugelassen und sichere Handoffs ergaenzt.
; - 2.2: Interne Ziele 8800 bis 8804 und lease-gesteuerte AI-Ziele ergaenzt.
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

[kienzlefon-entry]
exten => s,1,NoOp(Kienzlefon vollstaendiger Eingang 8800)
 same => n,Set(CHANNEL(language)=de)
 same => n,Set(AGISIGHUP=no)
 same => n,Set(AGIEXITONHANGUP=no)
 same => n,Answer()
 same => n,GotoIf($["${{KZF_AI_HANDOFF_DONE}}"="1"]?classic-full)
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-agi,--config,/etc/kienzlefon/kienzlefon.toml,--phase,opening)
 same => n,GotoIf($["${{KZF_IVR_OPENING_OK}}"!="1"]?done)
 same => n,GotoIf($["${{KZF_IVR_INITIAL_DIGIT}}"="0"]?ai-shortcut)
 same => n,GotoIf($["${{KZF_IVR_INITIAL_DIGIT}}"!="none"]?classic-menu)
 same => n,GotoIf($["{ai_enabled}"="1"]?admission:classic-menu)
 same => n(ai-shortcut),Set(KZF_IVR_INITIAL_DIGIT=none)
 same => n,GotoIf($["{ai_enabled}"="1"]?admission:classic-menu)
 same => n(admission),AGI(/opt/kienzlefon/venv/bin/kienzlefon-admission,--config,/etc/kienzlefon/kienzlefon.toml,--selection,any)
 same => n,GotoIf($["${{KZF_AI_ACCEPTED}}"="1"]?dial:classic-menu)
 same => n(dial),Gosub(kienzlefon-ai-dial,s,1)
 same => n,GotoIf($["${{KZF_AI_DTMF_HANDOFF}}"="1"]?classic-dtmf)
 same => n,GotoIf($["${{KZF_AI_DIAL_FAILED}}"="1"]?classic-menu:done)
 same => n(classic-dtmf),Set(KZF_IVR_INITIAL_DIGIT=${{KZF_AI_DTMF_DIGIT}})
 same => n,Set(__KZF_AI_HANDOFF_DONE=1)
 same => n,Goto(classic-menu)
 same => n(classic-menu),Goto(kienzlefon-classic-menu,s,1)
 same => n(classic-full),Goto(kienzlefon-in,s,1)
 same => n(done),Hangup()

[kienzlefon-classic-menu]
exten => s,1,NoOp(Kienzlefon klassisches Hauptmenue)
 same => n,Set(KZF_IVR_AI_REQUESTED=0)
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-agi,--config,/etc/kienzlefon/kienzlefon.toml,--phase,menu,--initial-digit,${{KZF_IVR_INITIAL_DIGIT}})
 same => n,GotoIf($["${{KZF_IVR_AI_REQUESTED}}"!="1"]?done)
 same => n,GotoIf($["${{KZF_AI_HANDOFF_DONE}}"="1"]?retry-menu)
 same => n,GotoIf($["{ai_enabled}"="1"]?ai-shortcut:retry-menu)
 same => n(ai-shortcut),Goto(kienzlefon-entry,s,ai-shortcut)
 same => n(retry-menu),Set(KZF_IVR_INITIAL_DIGIT=none)
 same => n,Goto(s,1)
 same => n(done),Hangup()

[kienzlefon-ai-dial]
exten => s,1,NoOp(Kienzlefon AI Lease ${{KZF_AI_SLOT_ID}})
 same => n,Set(__KZF_AI_REQUEST_ID=${{KZF_AI_REQUEST_ID}})
 same => n,Set(__KZF_AI_LEASE_ID=${{KZF_AI_LEASE_ID}})
 same => n,Set(__KZF_AI_SLOT_ID=${{KZF_AI_SLOT_ID}})
 same => n,Set(__KZF_AI_EXTENSION=${{KZF_AI_EXTENSION}})
 same => n,Set(KZF_AI_DIAL_FAILED=0)
 same => n,Set(KZF_AI_DTMF_HANDOFF=0)
 same => n,Set(KZF_AI_DTMF_DIGIT=)
 same => n,Set(KZF_AI_PREVIOUS_DYNAMIC_FEATURES=${{DYNAMIC_FEATURES}})
 same => n,Set(DYNAMIC_FEATURES={ai_dtmf_features})
 same => n,Dial(PJSIP/${{KZF_AI_EXTENSION}},120,gb(kienzlefon-ai-headers^s^1))
 same => n,Set(DYNAMIC_FEATURES=${{KZF_AI_PREVIOUS_DYNAMIC_FEATURES}})
 same => n,GotoIf($["${{KZF_AI_DTMF_DIGIT}}"!=""]?dtmf)
 same => n,GotoIf($["${{DIALSTATUS}}"="ANSWER"]?result)
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-admission,--config,/etc/kienzlefon/kienzlefon.toml,--selection,release,--request-id,${{KZF_AI_REQUEST_ID}},--lease-id,${{KZF_AI_LEASE_ID}})
 same => n,Set(KZF_AI_DIAL_FAILED=1)
 same => n,Goto(done)
 same => n(dtmf),Set(KZF_AI_DTMF_HANDOFF=1)
 same => n,Goto(done)
 same => n(result),AGI(/opt/kienzlefon/venv/bin/kienzlefon-admission,--config,/etc/kienzlefon/kienzlefon.toml,--selection,call-result,--request-id,${{KZF_AI_REQUEST_ID}},--lease-id,${{KZF_AI_LEASE_ID}})
 same => n,GotoIf($["${{KZF_AI_HANDOFF_ALLOWED}}"!="1"]?done)
 same => n,GotoIf($["${{KZF_AI_HANDOFF_TARGET}}"="classic"]?handoff-classic)
 same => n,GotoIf($["${{KZF_AI_HANDOFF_TARGET}}"="practice_queue"]?handoff-practice)
 same => n,GotoIf($["${{KZF_AI_HANDOFF_TARGET}}"="pharmacy_queue"]?handoff-pharmacy)
 same => n,GotoIf($["${{KZF_AI_HANDOFF_TARGET}}"="super_priority"]?handoff-super)
 same => n,Goto(done)
 same => n(handoff-classic),Goto(kienzlefon-ai-handoff,classic,1)
 same => n(handoff-practice),Goto(kienzlefon-ai-handoff,practice,1)
 same => n(handoff-pharmacy),Goto(kienzlefon-ai-handoff,pharmacy,1)
 same => n(handoff-super),Goto(kienzlefon-ai-handoff,super,1)
 same => n(done),Return()

[kienzlefon-ai-dtmf]
exten => s,1,Set(__KZF_AI_DTMF_DIGIT=${{ARG1}})
 same => n,SoftHangup(${{BRIDGEPEER}})
 same => n,Return()

[kienzlefon-ai-handoff]
exten => classic,1,Set(__KZF_AI_HANDOFF_DONE=1)
 same => n,Goto(kienzlefon-internal-targets,8801,1)
exten => practice,1,Set(__KZF_AI_HANDOFF_DONE=1)
 same => n,Set(__KZF_AI_HANDOFF_ACTIVE=1)
 same => n,Set(__KZF_AI_HANDOFF_FALLBACK_USED=0)
 same => n,Goto(kienzlefon-internal-targets,8802,1)
exten => pharmacy,1,Set(__KZF_AI_HANDOFF_DONE=1)
 same => n,Set(__KZF_AI_HANDOFF_ACTIVE=1)
 same => n,Set(__KZF_AI_HANDOFF_FALLBACK_USED=0)
 same => n,Goto(kienzlefon-internal-targets,8803,1)
exten => super,1,Set(__KZF_AI_HANDOFF_DONE=1)
 same => n,Set(__KZF_AI_HANDOFF_ACTIVE=1)
 same => n,Set(__KZF_AI_HANDOFF_FALLBACK_USED=0)
 same => n,Goto(kienzlefon-internal-targets,8804,1)

[kienzlefon-ai-queue-fallback]
exten => s,1,GotoIf($["${{KZF_AI_HANDOFF_ACTIVE}}"!="1"]?done)
 same => n,GotoIf($["${{KZF_AI_HANDOFF_FALLBACK_USED}}"="1"]?done)
{queue_failure_checks}
 same => n,Goto(done)
 same => n(fallback),Set(__KZF_AI_HANDOFF_FALLBACK_USED=1)
 same => n,Goto(kienzlefon-internal-targets,8801,1)
 same => n(done),Return()

[kienzlefon-ai-headers]
exten => s,1,Set(PJSIP_HEADER(add,X-Kienzlefon-Protocol)={"kienzlefon-ai-admission-v1"})
 same => n,Set(PJSIP_HEADER(add,X-Kienzlefon-Request-ID)=${{KZF_AI_REQUEST_ID}})
 same => n,Set(PJSIP_HEADER(add,X-Kienzlefon-Lease-ID)=${{KZF_AI_LEASE_ID}})
 same => n,Set(PJSIP_HEADER(add,X-Kienzlefon-Slot-ID)=${{KZF_AI_SLOT_ID}})
 same => n,Return()

[kienzlefon-internal-targets]
exten => 8800,1,Goto(kienzlefon-entry,s,1)
exten => 8801,1,Goto(kienzlefon-in,s,1)
exten => 8802,1,Goto(kfx-phone-queue,s,1)
exten => 8803,1,Goto(kienzlefon-pharmacy-queue,s,1)
exten => 8804,1,Goto(kienzlefon-specialist,s,1)
{preview_route}
{ai_specific_routes}

[kienzlefon-ai-endpoint-in]
exten => _X.,1,Hangup(21)

[kienzlefon-pharmacy-queue]
exten => s,1,NoOp(Kienzlefon Apotheke in bestehende Praxisqueue)
 same => n,Set(QUEUE_PRIO={config.ivr.pharmacy_priority})
 same => n,Set(QUEUE_RAISE_PENALTY=0)
 same => n,Set(CHANNEL(language)={ASTERISK_QUEUE_LANGUAGE})
 same => n,Queue({config.ivr.queue_name},{queue_options},,kienzlefon/pharmacy_agent)
 same => n,Gosub(kienzlefon-ai-queue-fallback,s,1)
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
 same => n,Gosub(kienzlefon-lookup,s,1)
 same => n,Goto(kfx-phone-queue,s,1)
exten => s,1,Goto(kienzlefon-direct-queue-in,{config.asterisk.direct_queue.did or "inbound-calls"},1)
exten => inbound-calls,1,Goto(kienzlefon-direct-queue-in,{config.asterisk.direct_queue.did or "inbound-calls"},1)

[kienzlefon-direct-red-in]
exten => _X.,1,Gosub(kfx_external_capacity,primary-phone,1)
 same => n,GotoIf($[\"${{KFX_CAPACITY_OK}}\"=\"1\"]?accepted)
 same => n,Hangup(17)
 same => n(accepted),AGI(/opt/kienzlefon/venv/bin/kienzlefon-callerid,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,Gosub(kienzlefon-lookup,s,1)
 same => n,Answer()
{specialist_route}
exten => s,1,Goto(kienzlefon-direct-red-in,{config.asterisk.direct_red.did or "inbound-calls"},1)
exten => inbound-calls,1,Goto(kienzlefon-direct-red-in,{config.asterisk.direct_red.did or "inbound-calls"},1)

[kienzlefon-red-local]
{"".join(internal_routes)}
{local_routes}
{admin_route}
{ai_local_routes}
{_outbound_route(config, red_endpoint, red_number)}

[kienzlefon-standalone-local]
{"".join(internal_routes)}
{local_routes}
{admin_route}
{ai_local_routes}
exten => _XXX,1,Set(KZF_OUT_ENDPOINT={config.asterisk.main_outbound_endpoint})
 same => n,Set(KZF_OUT_CALLERID={config.asterisk.main_outbound_number})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)
exten => _XXX.,1,Set(KZF_OUT_ENDPOINT={config.asterisk.main_outbound_endpoint})
 same => n,Set(KZF_OUT_CALLERID={config.asterisk.main_outbound_number})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)
exten => _+X.,1,Set(KZF_OUT_ENDPOINT={config.asterisk.main_outbound_endpoint})
 same => n,Set(KZF_OUT_CALLERID={config.asterisk.main_outbound_number})
 same => n,Goto(kienzlefon-outbound,${{EXTEN}},1)
{render_middleware(config)}
"""
    rendered += render_member_context()
    rendered = decorate_entries(rendered, config, timing)
    rendered += render_transfer(config, features or DEFAULT_TRANSFER_FEATURES)
    return decorate_calls(rendered, enabled=config.middleware.enabled)


def render_queues(config: AppConfig) -> str:
    first = config.asterisk.first_queue_extension
    members = [
        str(extension) for extension in range(first, first + config.asterisk.queue_extension_count)
    ]
    if config.ivr.red_enabled:
        members.append(config.ivr.red_extension)
    members.extend(config.special_queue.additional_extensions)
    rendered_members = "\n".join(
        f"member => {member_interface(extension)},0,Telefon {extension},PJSIP/{extension}"
        for extension in dict.fromkeys(members)
    )
    music_property = (
        f"musicclass={MUSIC_CLASS}"
        if config.hold_music.mode == "musik"
        else "; Eigene Wartemusik fuer diese Queue ist deaktiviert."
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
{music_property}
{rendered_members}
"""


def install_asterisk_config(config: AppConfig, etc: Path = Path("/etc/asterisk")) -> None:
    """Plan and validate every generated/updated file before publishing or reload."""
    features = resolve_transfer_features(etc) if config.middleware.enabled else None
    names = (
        "pjsip.conf", "extensions.conf", "queues.conf", "features.conf", "musiconhold.conf",
        "extensions-kfx-telefonie.conf", "queues-kfx.conf", "pjsip-kienzlefon.conf",
        "extensions-kienzlefon.conf", "queues-kienzlefon.conf", "features-kienzlefon.conf",
        "musiconhold-kienzlefon.conf", "queuerules.conf", "queuerules-kienzlefon.conf",
    )
    with tempfile.TemporaryDirectory(prefix="kienzlefon-asterisk-plan-") as name:
        staging = Path(name)
        for filename in names:
            source = etc / filename
            if source.exists():
                shutil.copy2(source, staging / filename)
        phone = staging / "extensions-kfx-telefonie.conf"
        if phone.is_file():
            phone.write_text(unwrap(decorate_calls(phone.read_text(), enabled=False)), encoding="utf-8")
        _install_asterisk_config(config, staging, features, etc / "features-kienzlefon.conf")
        phone.write_text(decorate_calls(decorate_entries(phone.read_text(), config,
                                        practice_timing(staging / "queues-kfx.conf", config.ivr.queue_name)),
                                        enabled=config.middleware.enabled, foreign=True), encoding="utf-8")
        planned = {filename: (staging / filename).read_text(encoding="utf-8")
                   for filename in names if (staging / filename).is_file()}
        _validate_transfer_plan(config, planned)
        validate_rules_include(etc, planned)
        for filename, text in planned.items():
            _atomic_install(etc / filename, text)


def _validate_transfer_plan(config: AppConfig, planned: dict[str, str]) -> None:
    if not config.middleware.enabled:
        return
    extensions = planned["extensions-kienzlefon.conf"]
    dialplans = "\n".join(text for name, text in planned.items() if name.startswith("extensions"))
    for name in ("kienzlefon-transfer", "kienzlefon-transfer-prepare",
                 "kienzlefon-transfer-caller", "kienzlefon-transfer-progress"):
        if len(re.findall(r"^\s*\[" + re.escape(name) + r"\]\s*(?:;[^\n]*)?$", dialplans, re.M)) != 1:
            raise AsteriskConfigError("Vermittlungskontext fehlt oder ist mehrfach vorhanden")
    for text in planned.values():
        if re.search(r"^\s*(?:include\s*=>|context\s*=)\s*kienzlefon-transfer(?:\s|,|;|$)", text, re.M):
            raise AsteriskConfigError("Privater Vermittlungskontext darf nicht eingebunden werden")
    route = extensions.split("[kienzlefon-transfer]\n", 1)[1].split("\n[", 1)[0]
    patterns = re.findall(r"^exten => (_[^,]+),1,", route, re.M)
    if patterns != ["_" + "X" * length for length in range(2, 33)]:
        raise AsteriskConfigError("Vermittlungsroute ist nicht abgesichert")
    for block in re.split(r"^exten => ", route, flags=re.M)[1:]:
        if block.startswith("_") and not (
            "Set(KF_TRANSFER_ALLOWED=0)" in block
            and "kienzlefon-transfer-check" in block
            and 'GotoIf($["${KF_TRANSFER_ALLOWED}"="1"]?approved)' in block
        ):
            raise AsteriskConfigError("Vermittlungsroute ohne vollstaendige Freigabepruefung")
    for text in (extensions, planned["extensions-kfx-telefonie.conf"]):
        if text.count("; kienzlefon transfer call begin") != text.count("; kienzlefon transfer call end"):
            raise AsteriskConfigError("Unvollstaendige Vermittlungs-Hooks")


def _install_asterisk_config(config: AppConfig, etc: Path,
                             features: dict[str, str] | None, features_include: Path) -> None:
    from .hold_music import install_config as install_hold_music_config

    pjsip_target = etc / "pjsip-kienzlefon.conf"
    extensions_target = etc / "extensions-kienzlefon.conf"
    queues_target = etc / "queues-kienzlefon.conf"
    features_target = etc / "features-kienzlefon.conf"
    timing = practice_timing(etc / "queues-kfx.conf", config.ivr.queue_name)
    _atomic_install(pjsip_target, render_pjsip(config))
    _atomic_install(extensions_target, render_extensions(config, features, timing))
    _atomic_install(queues_target, render_queues(config))
    _atomic_install(etc / "queuerules-kienzlefon.conf", render_rules(config, timing))
    if not (etc / "queuerules.conf").exists():
        _atomic_install(etc / "queuerules.conf", "; Kienzlefon Queue-Regeln\n")
    _ensure_include(etc / "queuerules.conf", '#include "/etc/asterisk/queuerules-kienzlefon.conf"')
    _atomic_install(features_target, render_features())
    install_hold_music_config(config, etc)
    _ensure_include(etc / "pjsip.conf", '#tryinclude "/etc/asterisk/pjsip-kienzlefon.conf"')
    _ensure_include(
        etc / "extensions.conf", '#tryinclude "/etc/asterisk/extensions-kienzlefon.conf"'
    )
    _ensure_include(etc / "queues.conf", '#include "/etc/asterisk/queues-kienzlefon.conf"')
    _ensure_include(
        etc / "features.conf", f'#include "{features_include}"'
    )
    _patch_kienzlefax_ivr_route(etc / "extensions-kfx-telefonie.conf", config.middleware.enabled)
    _patch_middleware_overflow(etc / "extensions-kfx-telefonie.conf", config.middleware.enabled)
    _patch_kienzlefax_queue_callerid(etc / "extensions-kfx-telefonie.conf")
    _patch_kienzlefax_queue_language(etc / "extensions-kfx-telefonie.conf")
    _patch_kienzlefax_queue_handoff_fallback(etc / "extensions-kfx-telefonie.conf")
    _patch_kienzlefax_queue_audio(config, etc / "extensions-kfx-telefonie.conf")
    _patch_kienzlefax_queue_properties(config, etc / "queues-kfx.conf")
    queue_path = etc / "queues-kfx.conf"
    if queue_path.is_file():
        _atomic_install(queue_path, decorate_members(queue_path.read_text(), config))
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


def _patch_kienzlefax_ivr_route(path: Path, middleware: bool = False) -> None:
    if not path.is_file():
        raise AsteriskConfigError(f"Kienzlefax-Telefoniedialplan fehlt: {path}")
    originals = (
        "same => n(accepted),Goto(kfx-phone-queue,s,1)",
        "same => n(accepted),Goto(kienzlefon-in,s,1)",
        "same => n(accepted),Goto(kienzlefon-entry,s,1)",
        "same => n(accepted),Goto(kienzlefon-middleware-in,s,1)",
    )
    destination = "kienzlefon-middleware-in" if middleware else "kienzlefon-entry"
    replacement = f"same => n(accepted),Goto({destination},s,1)"
    text = path.read_text(encoding="utf-8")
    context = re.search(r"^\[kfx-phone-in\]\n(?P<body>.*?)(?=^\[|\Z)", text, re.M | re.S)
    if context is None:
        raise AsteriskConfigError("Kienzlefax-Eingangskontext wurde nicht gefunden")
    body = context["body"]
    if replacement in body:
        return
    matches = [original for original in originals if original in body]
    if len(matches) != 1 or body.count(matches[0]) != 1:
        raise AsteriskConfigError("Kienzlefax-IVR-Uebergabepunkt wurde nicht eindeutig gefunden")
    body = body.replace(matches[0], replacement, 1)
    _atomic_install(path, text[:context.start("body")] + body + text[context.end("body"):])


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


def _patch_kienzlefax_queue_handoff_fallback(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = " same => n,Gosub(kienzlefon-ai-queue-fallback,s,1)"
    context = re.search(r"^\[kfx-phone-queue\]\n(?P<body>.*?)(?=^\[|\Z)", text, re.M | re.S)
    if context is None:
        raise AsteriskConfigError("Kienzlefax-Praxisqueue wurde nicht gefunden")
    if marker in context["body"]:
        return
    queue = re.search(r"^[ \t]*same => n,Queue\([^\n]+\)$", context["body"], re.M)
    if queue is None:
        raise AsteriskConfigError("Queue-Aufruf der Kienzlefax-Praxisqueue wurde nicht gefunden")
    insertion = context.start("body") + queue.end()
    _atomic_install(path, text[:insertion] + "\n" + marker + text[insertion:])


def _patch_kienzlefax_queue_language(path: Path) -> None:
    """Setzt nur beim Eintritt in die bestehende Praxisqueue die eigene Sprache."""
    text = path.read_text(encoding="utf-8")
    marker = f" same => n,Set(CHANNEL(language)={ASTERISK_QUEUE_LANGUAGE})"
    context = re.search(
        r"^\[kfx-phone-queue\]\n(?P<body>.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if context is None:
        raise AsteriskConfigError("Kienzlefax-Praxisqueue wurde nicht gefunden")
    if marker in context["body"]:
        return
    queue = re.search(
        r"^[ \t]*same => n,Queue\([^\n]+\)$", context["body"], re.MULTILINE
    )
    if queue is None:
        raise AsteriskConfigError("Queue-Aufruf der Kienzlefax-Praxisqueue wurde nicht gefunden")
    insertion = context.start("body") + queue.start()
    _atomic_install(path, text[:insertion] + marker + "\n" + text[insertion:])


def _patch_kienzlefax_queue_audio(config: AppConfig, path: Path) -> None:
    """Entfernt im Musikmodus nur r/R und kann die Originalzeile exakt wiederherstellen."""
    text = path.read_text(encoding="utf-8")
    managed = re.compile(
        r"; kienzlefon queue option begin\n"
        r"; original: (?P<original>[^\n]+)\n"
        r"[^\n]+\n"
        r"; kienzlefon queue option end",
    )
    existing = managed.search(text)
    if existing is not None:
        text = text[: existing.start()] + existing["original"] + text[existing.end() :]
    if config.hold_music.mode != "musik":
        if existing is not None:
            _atomic_install(path, text)
        return

    context = re.search(r"^\[kfx-phone-queue\]\n(?P<body>.*?)(?=^\[|\Z)", text, re.M | re.S)
    if context is None:
        raise AsteriskConfigError("Kienzlefax-Praxisqueue wurde nicht gefunden")
    queue_matches = list(
        re.finditer(r"^[ \t]*same => n,Queue\([^\n]+\)$", context["body"], re.M)
    )
    if len(queue_matches) != 1:
        raise AsteriskConfigError(
            "Queue-Aufruf der Kienzlefax-Praxisqueue wurde nicht eindeutig gefunden"
        )
    relative = queue_matches[0]
    original = relative.group(0)
    call = re.match(
        r"(?P<prefix>.*?Queue\([^,\n]+,)(?P<options>[^,\n)]*)(?P<suffix>.*)",
        original,
    )
    if call is None:
        raise AsteriskConfigError("Queue-Optionen der Kienzlefax-Praxisqueue sind ungueltig")
    options = call["options"].replace("r", "").replace("R", "")
    patched = call["prefix"] + options + call["suffix"]
    block = (
        "; kienzlefon queue option begin\n"
        f"; original: {original}\n"
        f"{patched}\n"
        "; kienzlefon queue option end"
    )
    start = context.start("body") + relative.start()
    end = context.start("body") + relative.end()
    _atomic_install(path, text[:start] + block + text[end:])


def _patch_kienzlefax_queue_properties(config: AppConfig, path: Path) -> None:
    """Ergaenzt nur eigene Queue-Werte; fremde Eigenschaften bleiben unangetastet."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"; kienzlefon queue properties begin\n.*?"
        r"; kienzlefon queue properties end\n?",
        "",
        text,
        flags=re.S,
    )
    context = re.search(r"^\[praxis\]\n(?P<body>.*?)(?=^\[|\Z)", text, re.M | re.S)
    if context is None:
        raise AsteriskConfigError("Kienzlefax-Queue [praxis] wurde nicht gefunden")
    values = [
        "; kienzlefon queue properties begin",
        "strategy=ringall", "autofill=yes", "ringinuse=no", "weight=0",
        f"defaultrule={RULE_NAME}",
        *(f"{name.replace('_', '-')}={phrase_path(config.paths.prompts, name)}"
          for name in QUEUE_PHRASES),
    ]
    if config.hold_music.mode == "musik":
        values.append(f"musicclass={MUSIC_CLASS}")
    values.append("; kienzlefon queue properties end")
    block = "\n".join(values) + "\n"
    insertion = context.end("body")
    body = context["body"].rstrip() + "\n" + block
    updated = text[: context.start("body")] + body + text[insertion:]
    _atomic_install(path, updated)


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
    internal_targets = [str(value) for value in range(8800, 8805)]
    if config.hold_music.installed:
        internal_targets.append("8805")
    internal_targets.extend(config.ai_integration.extensions)
    routes += "".join(
        f"exten => {extension},1,Goto(kienzlefon-internal-targets,{extension},1)\n"
        for extension in internal_targets
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


def _patch_middleware_overflow(path: Path, enabled: bool) -> None:
    text = path.read_text(encoding="utf-8")
    context = re.search(r"^\[kfx-phone-overflow-in\]\n(?P<body>.*?)(?=^\[|\Z)", text, re.M | re.S)
    if context is None:
        return
    target = "kienzlefon-middleware-queue-in" if enabled else "kfx-phone-queue"
    body, count = re.subn(
        r"same => n\(accepted\),Goto\((?:kfx-phone-queue|kienzlefon-middleware-queue-in),s,1\)",
        f"same => n(accepted),Goto({target},s,1)", context["body"], count=1,
    )
    if count != 1:
        raise AsteriskConfigError("Externer Ueberlauf-Eingang fuer Middleware nicht eindeutig gefunden")
    _atomic_install(path, text[:context.start("body")] + body + text[context.end("body"):])
