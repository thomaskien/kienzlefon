"""Keep the working G.722 AI bridge configuration across installer releases."""

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from kienzlefon.asterisk import render_pjsip
from kienzlefon.cli import asterisk_main
from kienzlefon.config import StandaloneExtensionConfig, load_config
from kienzlefon.migration import migrate_config

AI_CODECS = [
    "disallow=all", "allow=g722",
    "incoming_call_offer_pref=local_first", "outgoing_call_offer_pref=local_first",
]


def endpoint_codecs(text):
    sections = re.findall(r"(?ms)^\[([^\]\n]+)\]\n(.*?)(?=^\[|\Z)", text)
    return {
        name: [line for line in body.splitlines() if line.startswith(
            ("disallow=", "allow=", "incoming_call_offer_pref=", "outgoing_call_offer_pref=")
        )]
        for name, body in sections if "type=endpoint" in body.splitlines()
    }


@pytest.mark.parametrize("count", [1, 2, 3])
def test_only_ai_endpoints_require_g722_and_local_preference(app_config, count):
    provider = replace(app_config.asterisk.direct_queue, enabled=True,
                       did="4923312000", user="test", password="secret", domain="sip.example.test")
    config = replace(
        app_config,
        ai_integration=replace(app_config.ai_integration, enabled=True, extension_count=count,
                               sip_passwords=tuple("a" * 24 for _ in range(count))),
        asterisk=replace(app_config.asterisk, direct_queue=provider, direct_red=provider),
        standalone_extensions=(StandaloneExtensionConfig("300", "test-secret"),),
    )
    endpoints = endpoint_codecs(render_pjsip(config))
    ai = {str(8810 + index) for index in range(count)}
    assert set(endpoints) == ai | {
        "299", "300", "kienzlefon-direct-queue-endpoint", "kienzlefon-direct-red-endpoint",
    }
    for name, codecs in endpoints.items():
        assert codecs == (AI_CODECS if name in ai else ["disallow=all", "allow=g722,alaw,ulaw"])


@pytest.mark.parametrize("existing", ["new", "legacy_g711", "server_fixed_g722"])
def test_install_update_and_regeneration_keep_ai_fix_and_existing_settings(
    app_config, tmp_path, monkeypatch, existing,
):
    source = app_config.source.read_text().replace("anzahl_nebenstellen = 0", "anzahl_nebenstellen = 3")
    source = source.replace("[ki_integration]\naktiv = false", "[ki_integration]\naktiv = true")
    source = source.replace("sip_passwoerter = []", "sip_passwoerter = " + json.dumps(
        ["a" * 24, "b" * 24, "c" * 24]
    ))
    source = source.replace("ansage_pause_ms = 700", "ansage_pause_ms = 1000")
    if existing != "new":
        source = source.replace("# Version: 2.5.4", "# Version: 2.4.3", 1)
    app_config.source.write_text(source)
    before = load_config(app_config.source)
    migrate_config(app_config.source, Path("config/kienzlefon.toml.example"))
    assert app_config.source.read_text() == source

    etc = tmp_path / "asterisk"
    etc.mkdir()
    # Existing provider and phone endpoints belong to Kienzlefax, not this generator.
    foreign_pjsip = (
        "[provider]\ntype=endpoint\ndisallow=all\nallow=alaw,ulaw\n\n"
        "[201]\ntype=endpoint\ndisallow=all\nallow=alaw,ulaw\n"
    )
    foreign = etc / "pjsip-kfx-telefonie.conf"
    foreign.write_text(foreign_pjsip)
    for name in ("pjsip", "extensions", "queues", "features"):
        (etc / f"{name}.conf").write_text("[general]\n")
    (etc / "extensions-kfx-telefonie.conf").write_text(
        "[kfx-phone-in]\n same => n(accepted),Goto(kfx-phone-queue,s,1)\n"
        "[kfx-phone-queue]\nexten => s,1,NoOp(KienzleFax Telefoniewarteschlange)\n"
        " same => n,Queue(praxis,r)\n"
        "[kfx-phone-local]\nexten => _X.,1,NoOp(KienzleFax Telefonie ausgehend)\n"
        " same => n,Dial(PJSIP/${EXTEN}@kfx-phone-in-endpoint,120)\n"
    )
    target = etc / "pjsip-kienzlefon.conf"
    if existing != "new":
        codecs = ["disallow=all", "allow=alaw,ulaw"] if existing == "legacy_g711" else AI_CODECS
        target.write_text("\n".join(
            f"[{extension}]\ntype=endpoint\n" + "\n".join(codecs)
            for extension in ("8810", "8811", "8812")
        ) + "\n")
    monkeypatch.setattr(sys, "argv", ["kienzlefon-asterisk", "--config", str(app_config.source),
                                      "--etc", str(etc)])
    asterisk_main()
    generated = target.read_bytes()
    endpoints = endpoint_codecs(generated.decode())
    for extension in ("8810", "8811", "8812"):
        assert endpoints[extension] == AI_CODECS
    assert endpoints["299"] == ["disallow=all", "allow=g722,alaw,ulaw"]
    asterisk_main()
    assert target.read_bytes() == generated
    assert foreign.read_text() == foreign_pjsip
    assert app_config.source.read_text() == source
    after = load_config(app_config.source)
    assert after.tts == before.tts
    assert after.tts.engine == "kokoro"
    assert after.ivr.announcement_pause_ms == 1000
