"""Bounded, asynchronous AMI lookup; no network call in the dialplan."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppConfig


def render_middleware(config: AppConfig) -> str:
    options = config.middleware
    lookup = options.enabled and options.lookup and options.lookup_available
    # Keep a harmless return context even when disabled, so a dialplan reload
    # never leaves a previously entered external route pointing at a missing sub.
    hook = """[kienzlefon-lookup]
exten => s,1,Return()
"""
    if lookup:
        hook = r'''[kienzlefon-lookup]
exten => s,1,GotoIf($["${KF_PHONE_LOOKUP_STARTED}"="1"]?return)
 same => n,Set(KF_PHONE_LOOKUP_STARTED=1)
 same => n,GotoIf($[${REGEX("^prohib" ${CALLERID(num-pres)})}]?return)
 same => n,GotoIf($[${REGEX("^[+]?[0-9]+$" ${CALLERID(num)})}=0]?return)
 same => n,Set(KF_PHONE_REQUEST_ID=${UNIQUEID})
 same => n,Set(KF_PHONE_APPLIED=0)
 same => n,Set(KF_PHONE_STATUS=error)
 same => n,Set(LOOKUP_NAME=)
 same => n,Set(LOOKUP_STATUS=pending)
 same => n,Set(LOOKUP_RESULT_ID=)
 same => n,Set(LOOKUP_DONE=0)
 same => n,Set(KF_PHONE_DEADLINE=$[${STRFTIME(,,%s%3q)}+1000])
 same => n,UserEvent(KienzlefonLookupRequest,SchemaVersion: 1,RequestId: ${KF_PHONE_REQUEST_ID},SourceChannel: ${CHANNEL},SourceUniqueid: ${UNIQUEID},SourceLinkedid: ${CHANNEL(linkedid)},Number: ${CALLERID(num)},BudgetMs: 1000)
 same => n,Set(KF_PHONE_REMAINING=$[(${KF_PHONE_DEADLINE}-${STRFTIME(,,%s%3q)})/1000.0])
 same => n,GotoIf($[${KF_PHONE_REMAINING}<=0]?timeout)
 same => n,ExecIf($[${KF_PHONE_REMAINING}>1]?Set(KF_PHONE_REMAINING=1))
 same => n,TryExec(WaitForCondition(#,#["#{LOOKUP_DONE}"="1"],${KF_PHONE_REMAINING},0.01))
 same => n,GotoIf($["${TRYSTATUS}"!="SUCCESS"]?finish)
 same => n,GotoIf($[${STRFTIME(,,%s%3q)}>=${KF_PHONE_DEADLINE}]?timeout)
 same => n,GotoIf($["${WAITFORCONDITIONSTATUS}"="TIMEOUT"]?timeout)
 same => n,GotoIf($["${WAITFORCONDITIONSTATUS}"!="TRUE"]?finish)
 same => n,Set(KF_PHONE_RESULT_ID=${FILTER(0-9A-Za-z_.\-,${LOOKUP_RESULT_ID})})
 same => n,GotoIf($[${LEN(${KF_PHONE_RESULT_ID})}!=${LEN(${LOOKUP_RESULT_ID})}]?finish)
 same => n,GotoIf($["${KF_PHONE_RESULT_ID}"!="${KF_PHONE_REQUEST_ID}"]?finish)
 same => n,Set(KF_PHONE_RESULT_STATUS=${FILTER(a-z_,${LOOKUP_STATUS})})
 same => n,GotoIf($[${LEN(${KF_PHONE_RESULT_STATUS})}!=${LEN(${LOOKUP_STATUS})}]?finish)
 same => n,GotoIf($["${KF_PHONE_RESULT_STATUS}"="not_found"]?negative)
 same => n,GotoIf($["${KF_PHONE_RESULT_STATUS}"="ambiguous"]?negative)
 same => n,GotoIf($["${KF_PHONE_RESULT_STATUS}"="error"]?negative)
 same => n,GotoIf($["${KF_PHONE_RESULT_STATUS}"!="resolved"]?finish)
 same => n,GotoIf($[${LEN(${LOOKUP_NAME})}=0]?finish)
 same => n,Set(KF_PHONE_NAME=${LOOKUP_NAME})
 same => n,GotoIf($[${STRFTIME(,,%s%3q)}>=${KF_PHONE_DEADLINE}]?timeout)
 same => n,Set(CALLERID(name)=${KF_PHONE_NAME})
 same => n,Set(KF_PHONE_STATUS=resolved)
 same => n,Set(KF_PHONE_APPLIED=1)
 same => n,Goto(finish)
 same => n(negative),GotoIf($[${STRFTIME(,,%s%3q)}>=${KF_PHONE_DEADLINE}]?timeout)
 same => n,Set(KF_PHONE_STATUS=${KF_PHONE_RESULT_STATUS})
 same => n,Goto(finish)
 same => n(timeout),Set(KF_PHONE_STATUS=timeout)
 same => n(finish),Set(KF_PHONE_LOOKUP_CLOSED=1)
 same => n,UserEvent(KienzlefonLookupFinished,SchemaVersion: 1,RequestId: ${KF_PHONE_REQUEST_ID},SourceUniqueid: ${UNIQUEID},Status: ${KF_PHONE_STATUS},Applied: ${KF_PHONE_APPLIED})
 same => n(return),Return()
'''
    c2d = """[kienzlefon-click-to-dial]
exten => _.,1,Hangup(21)
"""
    if options.enabled and options.click_to_dial:
        c2d = r'''[kienzlefon-click-to-dial]
exten => _.,1,Set(KF_C2D_ALLOWED=0)
 same => n,Set(KF_C2D_TARGET=${EXTEN})
 same => n,AGI(/opt/kienzlefon/venv/bin/kienzlefon-c2d-check,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,GotoIf($["${KF_C2D_ALLOWED}"="1"]?approved)
 same => n,Hangup(21)
 same => n(approved),UserEvent(KienzlefonClickToDialProgress,SchemaVersion: 1,RequestId: ${KF_C2D_ID},Phase: dialing_target,SourceUniqueid: ${UNIQUEID})
 same => n,Goto(kienzlefon-outbound,${KF_C2D_NUMBER},1)
'''
    return "\n; Kienzlefon Middleware v1 / 2.5.1\n" + r'''[kienzlefon-middleware-in]
exten => s,1,AGI(/opt/kienzlefon/venv/bin/kienzlefon-callerid,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,Gosub(kienzlefon-lookup,s,1)
 same => n,Goto(kienzlefon-entry,s,1)

''' + r'''[kienzlefon-middleware-queue-in]
exten => s,1,AGI(/opt/kienzlefon/venv/bin/kienzlefon-callerid,--config,/etc/kienzlefon/kienzlefon.toml)
 same => n,Gosub(kienzlefon-lookup,s,1)
 same => n,Goto(kfx-phone-queue,s,1)

''' + hook + "\n" + c2d
