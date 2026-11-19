from dataclasses import replace
from unittest.mock import Mock

import pytest

from kienzlefon.asterisk import render_extensions
from kienzlefon.ivr_keys import validate_keys
from kienzlefon.prompts import rendered_prompts
from kienzlefon.statistics import emit_agi_route, patch_external_ingress


def test_reassign_and_disable_do_not_leave_announcement_of_old_digits(app_config):
    config = replace(app_config, ivr_keys=validate_keys({"ki": "7", "rezept": "*", "rot": ""}))
    prompts = rendered_prompts(config)
    assert "Für ein Rezept drücken Sie Stern." in prompts["menu_open"]
    assert "drücken Sie 2" not in prompts["menu_open"]
    assert "drücken" not in prompts["specialist_access"]
    assert '"${KZF_IVR_INITIAL_DIGIT}"="7"]?ai-shortcut' in render_extensions(config)
    with pytest.raises(ValueError, match="doppelt"):
        validate_keys({"praxis": "2"})


def test_ingress_marks_original_external_channel_before_any_capacity_check(app_config):
    original = """[kfx-phone-in]
exten => s,1,NoOp(Hauptprovider)
 same => n,Gosub(kfx_external_capacity,primary-phone,1)
[fax-in]
exten => 123,1,Answer()
"""
    marked = patch_external_ingress(original, "synthetic-pbx")
    assert marked.index("statistics-entry") < marked.index("kfx_external_capacity")
    assert marked.partition("[fax-in]")[2] == original.partition("[fax-in]")[2]
    assert patch_external_ingress(marked, "synthetic-pbx") == marked
    assert patch_external_ingress(marked, "") == original
    rendered = render_extensions(replace(app_config, statistics_pbx_id="synthetic-pbx"))
    assert rendered.count("Gosub(kienzlefon-statistics-entry,s,1(synthetic-pbx))") == 2
    assert "${UUID()}" in rendered and "UserEvent(KienzlefonCallEntered," in rendered


def test_agi_reports_route_only_for_an_identified_external_call():
    values = {"KF_STATS_CALL_ID": "c8717a1d-70a2-4dc3-ae06-7afaaea53457", "KF_STATS_ENTERED_AT": "1795000000"}
    channel = Mock()
    channel.get_variable.side_effect = values.get

    emit_agi_route(channel, "synthetic-pbx", "prescription")

    channel.exec.assert_called_once_with(
        "UserEvent",
        "KienzlefonCallRoute,SchemaVersion: 1,PbxId: synthetic-pbx,"
        "CallId: c8717a1d-70a2-4dc3-ae06-7afaaea53457,EnteredAt: 1795000000,Route: prescription",
    )
    channel.exec.reset_mock()
    values["KF_STATS_CALL_ID"] = ""
    emit_agi_route(channel, "synthetic-pbx", "prescription")
    channel.exec.assert_not_called()


def test_ai_route_uses_the_same_bridge_result_on_return_and_caller_hangup(app_config):
    dialplan = render_extensions(replace(app_config, statistics_pbx_id="synthetic-pbx"))
    assert "Set(CHANNEL(hangup_handler_push)=kienzlefon-statistics-ai-end,s,1)" in dialplan
    dial = dialplan.partition("[kienzlefon-ai-dial]\n")[2].partition("\n[")[0]
    assert dial.index("Set(ANSWEREDTIME_MS=)") < dial.index("Set(KF_STATS_AI_DIAL=1)") < dial.index("Dial(PJSIP/")
    assert dial.index("Dial(PJSIP/") < dial.index("Gosub(kienzlefon-statistics-ai-end,s,1)") < dial.index("n(result)")
    handler = dialplan.partition("[kienzlefon-statistics-ai-end]\n")[2].partition("\n[")[0]
    assert handler.index('"${KF_STATS_AI_DIAL}"!="1"') < handler.index("Set(KF_STATS_AI_DIAL=0)")
    assert handler.index('"${ANSWEREDTIME_MS}"=""') < handler.index("Gosub(kienzlefon-statistics-route,s,1(ai))")
    assert dialplan.count("Gosub(kienzlefon-statistics-route,s,1(ai))") == 1
    assert "kienzlefon-statistics-ai-end" not in render_extensions(replace(app_config, statistics_pbx_id=""))
