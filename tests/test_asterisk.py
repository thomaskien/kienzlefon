# kienzlefon tests
# Version: 1.8
# Changelog:
# - 1.8: Erzeugte Asterisk-Dateien fuer Release 1.8 getestet.
# - 1.7.1: Rotes Telefon als bedingtes Mitglied der Sonderqueue getestet.
# - 1.7: Sonderqueue, Penalty-Fix, optionales Rottelefon und Caller-ID-Patch getestet.
# - 1.3: Ansagen-IVR, Wahlpruefung, Zusatztelefone und idempotente Patches getestet.
# - 1.1: Abschluss nach AGI und Notfalltelefon-Fallback abgesichert.
# - 1.0: Kienzlefax-Uebergabepunkt und rote Nebenstelle abgesichert.

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from kienzlefon.asterisk import (
    install_asterisk_config,
    render_extensions,
    render_pjsip,
    render_queues,
)
from kienzlefon.config import SipLineConfig, StandaloneExtensionConfig


def test_render_keeps_red_phone_as_dedicated_endpoint(app_config) -> None:
    pjsip = render_pjsip(app_config)
    extensions = render_extensions(app_config)
    assert "[299]" in pjsip
    assert "context=kienzlefon-red-local" in pjsip
    assert "member => PJSIP/299" not in pjsip
    assert "Set(QUEUE_PRIO=10)" in extensions
    assert "Set(QUEUE_RAISE_PENALTY=0)" in extensions
    assert "Queue(praxis,r,,kienzlefon/pharmacy_agent)" in extensions
    assert "Dial(PJSIP/299,20)" in extensions
    assert 'GotoIf($["${DIALSTATUS}"="ANSWER"]?done)' in extensions
    assert "Set(QUEUE_PRIO=100)" in extensions
    assert "Queue(kienzlefon-sonder,r)" in extensions
    assert (
        "AGI(/opt/kienzlefon/venv/bin/kienzlefon-agi,--config,"
        "/etc/kienzlefon/kienzlefon.toml)\n same => n,Hangup()"
    ) in extensions
    assert "exten => 777,1,Answer()" in extensions
    assert "kienzlefon-wahlpruefung" in extensions
    assert "Playback(kienzlefon/blocked_destination)" in extensions
    assert "exten => _XXX,1" in extensions
    assert "exten => _XXX.,1" in extensions


def test_special_queue_rings_all_normal_and_selected_additional_phones(app_config) -> None:
    config = replace(
        app_config,
        standalone_extensions=(StandaloneExtensionConfig("300", "secret-300"),),
        special_queue=replace(app_config.special_queue, additional_extensions=("300",)),
    )
    queues = render_queues(config)
    assert "strategy=ringall" in queues
    assert "weight=100" in queues
    assert "member => PJSIP/201,0,Telefon 201,PJSIP/201" in queues
    assert "member => PJSIP/300,0,Telefon 300,PJSIP/300" in queues
    assert "member => PJSIP/299,0,Telefon 299,PJSIP/299" in queues


def test_disabled_red_phone_routes_directly_to_special_queue(app_config) -> None:
    config = replace(app_config, ivr=replace(app_config.ivr, red_enabled=False))
    assert "[299]" not in render_pjsip(config)
    extensions = render_extensions(config)
    specialist = extensions.split("[kienzlefon-specialist]", 1)[1].split(
        "[kienzlefon-specialist-agent]", 1
    )[0]
    assert "Dial(PJSIP/299" not in specialist
    assert "Queue(kienzlefon-sonder,r)" in specialist
    assert "PJSIP/299" not in render_queues(config)


def test_installer_patches_only_known_kienzlefax_route(app_config, tmp_path: Path) -> None:
    etc = tmp_path / "asterisk"
    etc.mkdir()
    (etc / "pjsip.conf").write_text("[system]\ntype=system\n", encoding="utf-8")
    (etc / "extensions.conf").write_text("[general]\nstatic=yes\n", encoding="utf-8")
    (etc / "queues.conf").write_text("[general]\n", encoding="utf-8")
    kfx_queues = "[praxis]\nstrategy=ringall\nmember => PJSIP/201,0\n"
    (etc / "queues-kfx.conf").write_text(kfx_queues, encoding="utf-8")
    (etc / "extensions-kfx-telefonie.conf").write_text(
        """[kfx-phone-in]
 same => n(accepted),Goto(kfx-phone-queue,s,1)
[kfx-phone-queue]
exten => s,1,NoOp(KienzleFax Telefoniewarteschlange)
 same => n,Set(QUEUE_RAISE_PENALTY=0)
 same => n,Queue(praxis,r)
[kfx-phone-local]
exten => _X.,1,NoOp(KienzleFax Telefonie ausgehend)
 same => n(dial),Set(CALLERID(num)=4923311234)
 same => n,Dial(PJSIP/${EXTEN}@kfx-phone-in-endpoint,120)
""",
        encoding="utf-8",
    )
    install_asterisk_config(app_config, etc)
    kfx = (etc / "extensions-kfx-telefonie.conf").read_text(encoding="utf-8")
    assert "Goto(kienzlefon-in,s,1)" in kfx
    assert "; kienzlefon internal routes begin" in kfx
    assert "exten => 299,1,Dial(PJSIP/299,120)" in kfx
    assert "kienzlefon-callerid" in kfx
    assert (etc / "queues-kienzlefon.conf").is_file()
    assert '#include "/etc/asterisk/queues-kienzlefon.conf"' in (
        etc / "queues.conf"
    ).read_text(encoding="utf-8")
    assert (etc / "queues-kfx.conf").read_text(encoding="utf-8") == kfx_queues
    assert '#tryinclude "/etc/asterisk/extensions-kienzlefon.conf"' in (
        etc / "extensions.conf"
    ).read_text(encoding="utf-8")


def test_direct_numbers_get_registration_and_capacity_routes(app_config, tmp_path: Path) -> None:
    direct_queue = SipLineConfig(
        enabled=True,
        did="4923312000",
        user="4923312000",
        password="queue-secret",
        domain="sip.example.test",
        outbound_proxy="",
        expiration=300,
        use_for_outbound=True,
    )
    direct_red = replace(direct_queue, did="4923312999", user="4923312999", use_for_outbound=False)
    config = replace(
        app_config,
        asterisk=replace(app_config.asterisk, direct_queue=direct_queue, direct_red=direct_red),
    )
    assert "line=yes" in render_pjsip(config)
    assert "context=kienzlefon-direct-red-in" in render_pjsip(config)

    etc = tmp_path / "asterisk-direct"
    etc.mkdir()
    (etc / "pjsip.conf").write_text("[system]\ntype=system\n", encoding="utf-8")
    (etc / "extensions.conf").write_text(
        "[kfx-provider-in]\nexten => 1,1,NoOp()\n", encoding="utf-8"
    )
    (etc / "queues.conf").write_text("[general]\n", encoding="utf-8")
    (etc / "extensions-kfx-telefonie.conf").write_text(
        """[kfx-phone-in]
exten => _X.,1,Goto(s,1)
 same => n(accepted),Goto(kfx-phone-queue,s,1)
[kfx-phone-local]
exten => _X.,1,NoOp(KienzleFax Telefonie ausgehend)
 same => n(dial),Set(CALLERID(num)=4923311234)
 same => n,Dial(PJSIP/${EXTEN}@kfx-phone-in-endpoint,120)
""",
        encoding="utf-8",
    )
    install_asterisk_config(config, etc)
    phone = (etc / "extensions-kfx-telefonie.conf").read_text(encoding="utf-8")
    provider = (etc / "extensions.conf").read_text(encoding="utf-8")
    assert "4923312000,1,Goto(kienzlefon-direct-queue-in" in phone
    assert "4923312999,1,Goto(kienzlefon-direct-red-in" in provider
    assert "Set(KZF_OUT_ENDPOINT=kienzlefon-direct-queue-endpoint)" in phone


def test_additional_phones_are_outside_queue_and_patch_is_repeatable(app_config, tmp_path: Path) -> None:
    config = replace(
        app_config,
        standalone_extensions=(StandaloneExtensionConfig("300", "secret-300"),),
    )
    pjsip = render_pjsip(config)
    assert "[300-auth]" in pjsip
    assert "context=kienzlefon-standalone-local" in pjsip
    assert "member => PJSIP/300" not in pjsip

    etc = tmp_path / "asterisk-repeat"
    etc.mkdir()
    (etc / "pjsip.conf").write_text("[system]\ntype=system\n", encoding="utf-8")
    (etc / "extensions.conf").write_text("[general]\nstatic=yes\n", encoding="utf-8")
    (etc / "queues.conf").write_text("[general]\n", encoding="utf-8")
    (etc / "extensions-kfx-telefonie.conf").write_text(
        """[kfx-phone-in]
 same => n(accepted),Goto(kfx-phone-queue,s,1)
[kfx-phone-local]
exten => _X.,1,NoOp(KienzleFax Telefonie ausgehend)
 same => n(dial),Set(CALLERID(num)=4923311234)
 same => n,Dial(PJSIP/${EXTEN}@kfx-phone-in-endpoint,120)
""",
        encoding="utf-8",
    )
    install_asterisk_config(config, etc)
    install_asterisk_config(config, etc)
    phone = (etc / "extensions-kfx-telefonie.conf").read_text(encoding="utf-8")
    assert phone.count("; kienzlefon internal routes begin") == 1
    assert phone.count("; kienzlefon outbound routes begin") == 1
    assert "exten => 300,1,Dial(PJSIP/300,120)" in phone
    assert "exten => 777,1,Goto(kienzlefon-red-local,777,1)" in phone
