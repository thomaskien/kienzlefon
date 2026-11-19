"""Generate the published Kienzlefon call-statistics dialplan hooks."""

from __future__ import annotations

import re

from .agi import AgiChannel


ENTRY = "Gosub(kienzlefon-statistics-entry,s,1"
CALL_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
ENTERED_AT = re.compile(r"[0-9]{1,12}")


def render_hooks() -> str:
    return """[kienzlefon-statistics-entry]
exten => s,1,GotoIf($["${KF_STATS_CALL_ID}"!=""]?done)
 same => n,Set(__KF_STATS_PBX_ID=${ARG1})
 same => n,Set(__KF_STATS_ENTERED_AT=${EPOCH})
 same => n,Set(__KF_STATS_CALL_ID=${UUID()})
 same => n,GotoIf($["${KF_STATS_CALL_ID}"=""]?done)
 same => n,Set(KF_LIVE_OWNER=1)
 same => n,Set(KF_LIVE_STAGE=other)
 same => n,Set(CHANNEL(hangup_handler_push)=kienzlefon-statistics-ai-end,s,1)
 same => n,UserEvent(KienzlefonCallEntered,SchemaVersion: 1,PbxId: ${KF_STATS_PBX_ID},CallId: ${KF_STATS_CALL_ID},EnteredAt: ${KF_STATS_ENTERED_AT})
 same => n(done),Return()

[kienzlefon-statistics-route]
exten => s,1,GotoIf($["${KF_STATS_CALL_ID}"=""]?done)
 same => n,UserEvent(KienzlefonCallRoute,SchemaVersion: 1,PbxId: ${KF_STATS_PBX_ID},CallId: ${KF_STATS_CALL_ID},EnteredAt: ${KF_STATS_ENTERED_AT},Route: ${ARG1})
 same => n(done),Return()

[kienzlefon-statistics-ai-end]
exten => s,1,GotoIf($["${KF_STATS_AI_DIAL}"!="1"]?done)
 same => n,Set(KF_STATS_AI_DIAL=0)
 same => n,GotoIf($["${ANSWEREDTIME_MS}"=""]?done)
 same => n,Gosub(kienzlefon-statistics-route,s,1(ai))
 same => n(done),Return()
"""


def entry_statement(pbx_id: str) -> str:
    return f"{ENTRY}({pbx_id}))"


def route_statement(route: str) -> str:
    return f"Gosub(kienzlefon-statistics-route,s,1({route}))"


def emit_agi_route(channel: AgiChannel, pbx_id: str, route: str) -> None:
    call_id = channel.get_variable("KF_STATS_CALL_ID")
    if not CALL_ID.fullmatch(call_id):
        return
    entered_at = channel.get_variable("KF_STATS_ENTERED_AT")
    if not ENTERED_AT.fullmatch(entered_at):
        return
    channel.exec(
        "UserEvent",
        f"KienzlefonCallRoute,SchemaVersion: 1,PbxId: {pbx_id},"
        f"CallId: {call_id},EnteredAt: {entered_at},Route: {route}",
    )


def patch_external_ingress(text: str, pbx_id: str) -> str:
    text = re.sub(r"^ same => n,Gosub\(kienzlefon-statistics-entry,s,1\([^\n]*\)\)\n",
                  "", text, flags=re.M)
    if not pbx_id:
        return text
    for context in ("kfx-phone-in", "kfx-phone-overflow-in"):
        match = re.search(rf"^\[{context}\]\n(?P<body>.*?)(?=^\[|\Z)", text, re.M | re.S)
        if match is None and context.endswith("overflow-in"):
            continue
        body = match["body"] if match else ""
        anchor = re.search(r"^exten => s,1,NoOp\([^\n]+\)\n", body, re.M)
        if match is None or anchor is None:
            raise ValueError(f"Statistik-Eingang [{context}] nicht eindeutig gefunden")
        start = match.start("body") + anchor.end()
        text = text[:start] + f" same => n,{entry_statement(pbx_id)}\n" + text[start:]
    return text


def patch_queue_statements(text: str, pbx_id: str) -> str:
    hook = f" same => n,Set(KF_LIVE_STAGE=other)\n same => n,{route_statement('queue')}\n"
    text = text.replace(hook, "")
    if pbx_id:
        text = re.sub(r"^ same => n,Queue\(", hook + " same => n,Queue(", text, flags=re.M)
    return text
