from __future__ import annotations

from dataclasses import replace

import pytest

from kienzlefon.asterisk import render_extensions
from kienzlefon.config import StandaloneExtensionConfig
from kienzlefon.middleware import MiddlewareConfig
from kienzlefon.transfer_dialplan import decorate_calls
from kienzlefon.transfer_features import DEFAULT_TRANSFER_FEATURES


def transfer_config(app_config):
    return replace(
        app_config,
        middleware=replace(
            MiddlewareConfig(),
            enabled=True,
            click_to_dial=True,
            extensions=("201", "202", "299", "300", "777", "8800", "8810"),
        ),
        asterisk=replace(app_config.asterisk, queue_extension_count=2),
        standalone_extensions=(StandaloneExtensionConfig("300", "test-secret"),),
        ai_integration=replace(
            app_config.ai_integration,
            enabled=True,
            extension_count=1,
            sip_passwords=("a" * 32,),
        ),
    )


def context(text: str, name: str) -> str:
    return text.split(f"[{name}]\n", 1)[1].split("\n[", 1)[0]


def test_real_render_has_private_exact_transfer_route_and_safe_special_extensions(
    app_config,
) -> None:
    rendered = render_extensions(transfer_config(app_config))
    route = context(rendered, "kienzlefon-transfer")

    assert rendered.count("[kienzlefon-transfer]\n") == 1
    assert "include => kienzlefon-transfer" not in rendered
    assert "exten => _.," not in route
    assert [
        line.split(",", 2)[0]
        for line in route.splitlines()
        if line.startswith("exten => _")
    ] == ["exten => _" + "X" * length for length in range(2, 33)]
    assert "exten => h,1,NoOp(Kienzlefon Vermittlung beendet)" in route
    assert "exten => i,1,Hangup(21)" in route
    assert "exten => t,1,Hangup(21)" in route
    assert "kienzlefon-transfer-progress,s,1(failed)" not in route.split(
        "exten => h,1", 1
    )[1]


def test_only_configured_physical_phones_become_transfer_ready(app_config) -> None:
    rendered = render_extensions(transfer_config(app_config))
    prepare = context(rendered, "kienzlefon-transfer-prepare")
    caller = context(rendered, "kienzlefon-transfer-caller")

    assert 'CHANNEL(channeltype)}"!="PJSIP"' in prepare
    assert 'REGEX("^(201|202|299|300)$" ${CHANNEL(endpoint)})' in prepare
    for forbidden in ("777", "8800", "8810"):
        assert forbidden not in prepare
    assert "Set(KF_TRANSFER_READY=0)" in prepare
    assert prepare.index("Set(FEATURE(inherit)=yes)") < prepare.index(
        "Set(KF_TRANSFER_READY=1)"
    )
    assert "n(untrusted),Set(FEATUREMAP(atxfer)=)" in prepare
    assert "Set(FEATUREMAP(blindxfer)=)" in prepare
    assert 'KF_TRANSFER_READY}"="1"' in caller
    assert "Set(KF_TRANSFER_CALLER_OPTION=T)" in caller


def test_render_uses_requested_channel_local_feature_codes(app_config) -> None:
    features = {"atxfer": "#7", "atxferabort": "#8", "atxfercomplete": "#9"}
    prepare = context(render_extensions(transfer_config(app_config), features),
                      "kienzlefon-transfer-prepare")

    assert "Set(FEATUREMAP(atxfer)=#7)" in prepare
    assert "Set(FEATURE(atxferabort)=#8)" in prepare
    assert "Set(FEATURE(atxfercomplete)=#9)" in prepare
    assert "Set(FEATURE(inherit)=yes)" in prepare


def test_disabled_middleware_renders_no_transfer_route_or_hooks(app_config) -> None:
    rendered = render_extensions(app_config)

    assert "[kienzlefon-transfer]" not in rendered
    assert "; kienzlefon transfer call begin" not in rendered
    assert "kienzlefon-transfer-progress" not in rendered


def test_render_decorates_queue_internal_outbound_direct_and_click_to_dial_flows(
    app_config,
) -> None:
    rendered = render_extensions(transfer_config(app_config))

    internal = context(rendered, "kienzlefon-red-local")
    queue = context(rendered, "kienzlefon-pharmacy-queue")
    outbound = context(rendered, "kienzlefon-outbound")
    click_to_dial = context(rendered, "kienzlefon-click-to-dial")

    assert "; original: exten => 201,1,Dial(PJSIP/201,120)" in internal
    assert "Dial(PJSIP/201,120,${KF_TRANSFER_CALLER_OPTION}tb(" in internal
    assert "; original:  same => n,Queue(praxis,r,,kienzlefon/pharmacy_agent)" in queue
    assert "Queue(praxis,r${KF_TRANSFER_CALLER_OPTION}tb(" in queue
    assert "kienzlefon/pharmacy_agent" in queue
    assert "; original:  same => n,Dial(PJSIP/${KZF_DIAL_NUMBER}" in outbound
    assert "${KF_TRANSFER_CALLER_OPTION}b(kienzlefon-transfer-prepare^s^1)" in outbound
    assert "${KF_TRANSFER_CALLER_OPTION}tb(" not in outbound
    assert "Goto(kienzlefon-outbound,${KF_C2D_NUMBER},1)" in click_to_dial


def test_external_progress_is_on_dial_channel_after_checks_and_capacity(app_config) -> None:
    outbound = context(render_extensions(transfer_config(app_config)),
                       "kienzlefon-outbound")

    validation = 'GotoIf($["${KZF_DIAL_ALLOWED}"="1"]?capacity)'
    capacity = 'GotoIf($["${KFX_CAPACITY_OK}"="1"]?dial)'
    progress = "Gosub(kienzlefon-transfer-progress,s,1(dialing_target))"
    dial = "\n same => n,Dial(PJSIP/${KZF_DIAL_NUMBER}@${KZF_OUT_ENDPOINT},120"
    assert outbound.index(validation) < outbound.index(capacity)
    assert outbound.index(capacity) < outbound.index(progress) < outbound.index(dial)
    assert outbound.count(progress) == 1


def test_failed_is_only_emitted_for_rejection_not_normal_dial_results(app_config) -> None:
    rendered = render_extensions(transfer_config(app_config))
    outbound = context(rendered, "kienzlefon-outbound")
    progress = context(rendered, "kienzlefon-transfer-progress")

    dial_tail = outbound.split("Dial(PJSIP/${KZF_DIAL_NUMBER}", 1)[1]
    assert "kienzlefon-transfer-progress,s,1(failed)" not in dial_tail
    assert "DIALSTATUS" not in outbound
    assert 'GotoIf($["${ARG1}"="failed"]?failed)' in progress
    assert "n(failed),Set(KF_TRANSFER_ATTEMPT=0)" in progress
    assert "Phase: failed" in progress
    assert "exten => h" not in progress


def test_foreign_kfx_local_and_queue_flows_are_decorated_selectively() -> None:
    original = """[unrelated]
exten => s,1,Dial(PJSIP/999,20,T)
[kfx-phone-local]
exten => _X.,1,Dial(PJSIP/${EXTEN}@provider,120,T)
[kfx-phone-queue]
exten => s,1,Queue(praxis,r,,welcome)
[kfx-other]
exten => s,1,Dial(PJSIP/998,20,T)
"""

    decorated = decorate_calls(original, enabled=True, foreign=True)

    assert decorated.count("; kienzlefon transfer call begin") == 2
    assert "Dial(PJSIP/999,20,T)" in decorated
    assert "Dial(PJSIP/998,20,T)" in decorated
    local = context(decorated, "kfx-phone-local")
    queue = context(decorated, "kfx-phone-queue")
    assert "Dial(PJSIP/${EXTEN}@provider,120,${KF_TRANSFER_CALLER_OPTION}b(" in local
    assert "Queue(praxis,r${KF_TRANSFER_CALLER_OPTION}tb(" in queue
    assert ",,welcome)" in queue


def test_decorating_is_idempotent_and_disabling_restores_exact_input() -> None:
    original = """; preface
[kienzlefon-demo]
exten => s,1,Dial(PJSIP/201,20,TU(existing^s^1(tT))) ; keep
 same => n,Queue(praxis,rt,,agent_prompt,42)
"""

    once = decorate_calls(original, enabled=True)

    assert decorate_calls(once, enabled=True) == once
    assert decorate_calls(once, enabled=False) == original


@pytest.mark.parametrize("suffix", ["", "\n"])
@pytest.mark.parametrize("options", ["T", "Tb(custom^s^1)"])
def test_disabling_restores_input_with_or_without_trailing_newline_exactly(suffix, options) -> None:
    original = f"[kienzlefon-demo]\nexten => s,1,Dial(PJSIP/201,20,{options}){suffix}"

    decorated = decorate_calls(original, enabled=True)

    assert decorate_calls(decorated, enabled=False) == original
    assert decorate_calls(decorated, enabled=True) == decorated


def test_nested_options_and_existing_predial_are_composed_without_losing_arguments() -> None:
    original = """[kienzlefon-demo]
exten => s,1,Dial(PJSIP/201,20,U(notice^s^1(tT))Ttb(existing^s^1(alpha^beta))g)
"""

    decorated = decorate_calls(original, enabled=True)

    assert "U(notice^s^1(tT))" in decorated
    assert "U(notice^s^1())" not in decorated
    dial_line = decorated.split(" same => n,Dial", 1)[1].split("\n", 1)[0]
    assert "b(existing" not in dial_line
    assert "${KF_TRANSFER_CALLER_OPTION}tb(kienzlefon-transfer-chain-" in dial_line
    assert "Gosub(existing,s,1(alpha,beta))" in decorated
    assert "Gosub(kienzlefon-transfer-prepare,s,1)" in decorated


def test_queue_announcement_and_remaining_arguments_are_preserved() -> None:
    original = """[kienzlefon-demo]
 same => n,Queue(praxis,rTt,,kienzlefon/pharmacy_agent,30,agi.agi,macro,gsub,rule,4)
"""

    decorated = decorate_calls(original, enabled=True)

    queue_line = next(
        line for line in decorated.splitlines() if line.startswith(" same => n,Queue(")
    )
    assert ",,kienzlefon/pharmacy_agent,30,agi.agi,macro,gsub,rule,4)" in queue_line
    assert "r${KF_TRANSFER_CALLER_OPTION}tb(" in queue_line


def test_local_channel_is_treated_as_transferable_callee() -> None:
    original = """[kienzlefon-demo]
exten => s,1,Dial(Local/${EXTEN}@worker/n,20,T)
"""

    decorated = decorate_calls(original, enabled=True)

    assert "Dial(Local/${EXTEN}@worker/n,20,${KF_TRANSFER_CALLER_OPTION}tb(" in decorated


@pytest.mark.parametrize(
    "call",
    [
        "Dial(PJSIP/201,20,${DIAL_OPTIONS})",
        "Dial(PJSIP/201,20,r${DIAL_OPTIONS})",
        "Dial(PJSIP/201,20,b(one^s^1)b(two^s^1))",
        "Dial(PJSIP/201,20,b(unclosed)",
        "Queue(praxis,${QUEUE_OPTIONS},,prompt)",
    ],
)
def test_ambiguous_or_dynamic_options_fail_closed(call) -> None:
    text = f"[kienzlefon-demo]\nexten => s,1,{call}\n"

    with pytest.raises(ValueError):
        decorate_calls(text, enabled=True)


def test_default_features_are_used_by_real_render(app_config) -> None:
    prepare = context(render_extensions(transfer_config(app_config)),
                      "kienzlefon-transfer-prepare")

    assert f"Set(FEATUREMAP(atxfer)={DEFAULT_TRANSFER_FEATURES['atxfer']})" in prepare
    assert f"Set(FEATURE(atxferabort)={DEFAULT_TRANSFER_FEATURES['atxferabort']})" in prepare
    assert f"Set(FEATURE(atxfercomplete)={DEFAULT_TRANSFER_FEATURES['atxfercomplete']})" in prepare
