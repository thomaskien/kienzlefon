"""Private transfer route and reversible employee-side Dial/Queue hooks."""
from __future__ import annotations

import hashlib
import re

from .config import AppConfig
from .transfer_agi import staff_extensions

BEGIN = "; kienzlefon transfer call begin"
END = "; kienzlefon transfer call end"
WRAPPERS = "; kienzlefon transfer wrappers begin"


def render_transfer(config: AppConfig, features: dict[str, str]) -> str:
    if not config.middleware.enabled:
        return ""
    staff = "|".join(staff_extensions(config)) or "never"
    feature_lines = "\n".join(
        f' same => n,Set({function}={features[key]})'
        for key, function in (("atxfer", "FEATUREMAP(atxfer)"),
                              ("atxferabort", "FEATURE(atxferabort)"),
                              ("atxfercomplete", "FEATURE(atxfercomplete)"))
    )
    feature_checks = "\n".join(
        ' same => n,GotoIf($[${REGEX("^[0-9*#]{1,8}$" ${' + function + '})}=0]?done)'
        for function in ("FEATUREMAP(atxfer)", "FEATURE(atxferabort)",
                         "FEATURE(atxfercomplete)")
    )
    route = r'''Set(KF_TRANSFER_ATTEMPT=1)
 same => n,Set(KF_TRANSFER_DIAL_STARTED=0)
 same => n,Set(KF_TRANSFER_ALLOWED=0)
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-transfer-check,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,GotoIf($["${KF_TRANSFER_ALLOWED}"="1"]?approved)
 same => n,Gosub(kienzlefon-transfer-progress,s,1(failed))
 same => n,Hangup(21)
 same => n(approved),GotoIf($["${KF_TRANSFER_TARGET_TYPE}"="internal"]?internal)
 same => n,Set(CALLERID(name)=${KZF_OUT_CALLERID})
 same => n,Goto(kienzlefon-outbound,${KF_TRANSFER_NUMBER},1)
 same => n(internal),Dial(PJSIP/${KF_TRANSFER_NUMBER},120)
 same => n,Hangup()
'''
    targets = "\n".join(f"exten => _{'X' * length},1,{route}" for length in range(2, 33))
    return rf'''
; Private AMI route; deliberately absent from endpoint/public includes.
[kienzlefon-transfer]
{targets}
exten => h,1,NoOp(Kienzlefon Vermittlung beendet)
exten => i,1,Hangup(21)
exten => t,1,Hangup(21)

[kienzlefon-transfer-prepare]
exten => s,1,Set(KF_TRANSFER_READY=0)
 same => n,GotoIf($["${{CHANNEL(channeltype)}}"!="PJSIP"]?untrusted)
 same => n,GotoIf($[${{REGEX("^({staff})$" ${{CHANNEL(endpoint)}})}}=0]?untrusted)
{feature_lines}
{feature_checks}
 same => n,Set(FEATURE(inherit)=yes)
 same => n,Set(KF_TRANSFER_READY=1)
 same => n,Return()
 same => n(untrusted),Set(FEATUREMAP(atxfer)=)
 same => n,Set(FEATUREMAP(blindxfer)=)
 same => n(done),Return()

[kienzlefon-transfer-caller]
exten => s,1,Set(KF_TRANSFER_CALLER_OPTION=)
 same => n,Gosub(kienzlefon-transfer-prepare,s,1)
 same => n,ExecIf($["${{KF_TRANSFER_READY}}"="1"]?Set(KF_TRANSFER_CALLER_OPTION=T))
 same => n,Return()

[kienzlefon-transfer-progress]
exten => s,1,GotoIf($["${{KF_TRANSFER_ATTEMPT}}"!="1"]?done)
 same => n,GotoIf($["${{KF_TRANSFER_DIAL_STARTED}}"="1"]?done)
 same => n,GotoIf($["${{ARG1}}"="failed"]?failed)
 same => n,GotoIf($["${{KF_TRANSFER_ALLOWED}}"!="1"]?done)
 same => n,Set(KF_TRANSFER_DIAL_STARTED=1)
 same => n,UserEvent(KienzlefonTransferProgress,SchemaVersion: 1,RequestId: ${{KF_TRANSFER_ID}},TransfererUniqueid: ${{KF_TRANSFER_SOURCE_UID}},SourceUniqueid: ${{UNIQUEID}},Phase: dialing_target)
 same => n,Return()
 same => n(failed),Set(KF_TRANSFER_ATTEMPT=0)
 same => n,UserEvent(KienzlefonTransferProgress,SchemaVersion: 1,RequestId: ${{FILTER(0-9a-fA-F\-,${{KF_TRANSFER_ID}})}},TransfererUniqueid: ${{FILTER(0-9A-Za-z_.:\-,${{KF_TRANSFER_SOURCE_UID}})}},SourceUniqueid: ${{UNIQUEID}},Phase: failed)
 same => n(done),Return()
'''


def _split_arguments(text: str) -> list[str]:
    """Split only top-level commas; keep nested Gosubs, functions and variables intact."""
    parts: list[str] = []
    depth = 0
    quoted = False
    escaped = False
    start = 0
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
        elif not quoted:
            if char in "({[":
                depth += 1
            elif char in ")}]":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(text[start:index])
                start = index + 1
        if depth < 0:
            raise ValueError("Ungueltige Dial/Queue-Argumente")
    if depth or quoted:
        raise ValueError("Nicht abgeschlossene Dial/Queue-Argumente")
    return [*parts, text[start:]]


def _options(options: str, wrappers: dict[str, str], *, callee: bool) -> str:
    """Remove only top-level t/T and compose a pre-existing b() without losing it."""
    output = ""
    index = 0
    predial = ""
    while index < len(options):
        char = options[index]
        end = index + 1
        if char == "$" and end < len(options) and options[end] in "{[":
            raise ValueError("Dynamische Dial/Queue-Optionen vor Transfer-Einrichtung aufloesen")
        if end < len(options) and options[end] == "(":
            depth = 1
            end += 1
            while end < len(options) and depth:
                if options[end] == "(":
                    depth += 1
                elif options[end] == ")":
                    depth -= 1
                end += 1
            if depth:
                raise ValueError("Nicht abgeschlossene Dial/Queue-Option")
        token = options[index:end]
        if char == "b":
            if predial or not token.startswith("b("):
                raise ValueError("Mehrdeutiger Pre-Dial-Hook")
            predial = token[2:-1]
        elif char not in "tT":
            output += token
        index = end
    hook = "kienzlefon-transfer-prepare^s^1"
    if predial:
        name = "kienzlefon-transfer-chain-" + hashlib.sha256(predial.encode()).hexdigest()[:12]
        wrappers[name] = predial.replace("^", ",")
        hook = name + "^s^1"
    return output + "${KF_TRANSFER_CALLER_OPTION}" + ("t" if callee else "") + f"b({hook})"


def decorate_calls(text: str, *, enabled: bool, foreign: bool = False) -> str:
    """Preserve exact original calls for idempotent updates and middleware disabling."""
    text = re.sub(r"\n" + re.escape(WRAPPERS) + r"\n.*?; kienzlefon transfer wrappers end",
                  "", text, flags=re.S)
    text = re.sub(re.escape(BEGIN) + r"\n; original: ([^\n]*)\n.*?" + re.escape(END),
                  lambda match: match[1], text, flags=re.S)
    if not enabled:
        return text
    wrappers: dict[str, str] = {}
    output: list[str] = []
    context = ""
    for line in text.splitlines():
        heading = re.fullmatch(r"\[([^]]+)\].*", line)
        if heading:
            context = heading[1]
        active = context in {"kfx-phone-local", "kfx-phone-queue"} if foreign else (
            context.startswith("kienzlefon-") and not context.startswith("kienzlefon-ai-")
        )
        match = re.fullmatch(
            r"(\s*(?:exten\s*=>\s*[^,]+,[^,]+,|same\s*=>\s*[^,]+,))"
            r"(Dial|Queue)\((.*)\)(\s*(?:;.*)?)", line,
        )
        if not active or match is None:
            output.append(line)
            continue
        prefix, application, arguments, comment = match.groups()
        args = _split_arguments(arguments)
        option_index = 2 if application == "Dial" else 1
        while len(args) <= option_index:
            args.append("")
        callee = application == "Queue" or "@" not in args[0] or args[0].startswith("Local/")
        args[option_index] = _options(args[option_index], wrappers, callee=callee)
        output.extend((BEGIN, "; original: " + line,
                       prefix + "Gosub(kienzlefon-transfer-caller,s,1)"))
        if application == "Dial":
            output.append(" same => n,Gosub(kienzlefon-transfer-progress,s,1(dialing_target))")
        output.extend((f" same => n,{application}({','.join(args)}){comment}", END))
    if wrappers:
        output.append(WRAPPERS)
        for name, gosub in sorted(wrappers.items()):
            output.extend((f"[{name}]", f"exten => s,1,Gosub({gosub})",
                           " same => n,Gosub(kienzlefon-transfer-prepare,s,1)",
                           " same => n,Return()"))
        output.append("; kienzlefon transfer wrappers end")
    return "\n".join(output) + ("\n" if text.endswith("\n") else "")
