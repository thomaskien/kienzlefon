# kienzlefon tests
# Version: 2.4.0
# Changelog:
# - 2.4.0: Taste 0 im klassischen Hauptmenue und Rekursionsschutz getestet.
# - 2.3.2: Sofortige AI-Medienbridge und Taste 0 als direkter AI-Shortcut abgesichert.
# - 2.3: Menue-Admission, Call-Result-Handoff und DTMF-Rueckkehr getestet.
# - 1.8: Erzeugte Asterisk-Dateien fuer Release 1.8 getestet.
# - 1.7.1: Rotes Telefon als bedingtes Mitglied der Sonderqueue getestet.
# - 1.7: Sonderqueue, Penalty-Fix, optionales Rottelefon und Caller-ID-Patch getestet.
# - 1.3: Ansagen-IVR, Wahlpruefung, Zusatztelefone und idempotente Patches getestet.
# - 1.1: Abschluss nach AGI und Notfalltelefon-Fallback abgesichert.
# - 1.0: Kienzlefax-Uebergabepunkt und rote Nebenstelle abgesichert.

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from kienzlefon.asterisk import (
    install_asterisk_config,
    render_extensions,
    render_features,
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
    assert extensions.count("Set(CHANNEL(language)=de_kienzlefon)") >= 2
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
    (etc / "features.conf").write_text("[general]\n", encoding="utf-8")
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
    assert "Goto(kienzlefon-entry,s,1)" in kfx
    assert "; kienzlefon internal routes begin" in kfx
    assert "exten => 299,1,Dial(PJSIP/299,120)" in kfx
    assert "exten => 8800,1,Goto(kienzlefon-internal-targets,8800,1)" in kfx
    assert "kienzlefon-callerid" in kfx
    assert kfx.count("Set(CHANNEL(language)=de_kienzlefon)") == 1
    assert (etc / "queues-kienzlefon.conf").is_file()
    assert '#include "/etc/asterisk/queues-kienzlefon.conf"' in (
        etc / "queues.conf"
    ).read_text(encoding="utf-8")
    patched_queues = (etc / "queues-kfx.conf").read_text(encoding="utf-8")
    assert patched_queues.startswith(kfx_queues)
    assert "queue-thankyou=kienzlefon/queue_thankyou" in patched_queues
    assert '#tryinclude "/etc/asterisk/extensions-kienzlefon.conf"' in (
        etc / "extensions.conf"
    ).read_text(encoding="utf-8")
    assert f'#include "{etc}/features-kienzlefon.conf"' in (
        etc / "features.conf"
    ).read_text(encoding="utf-8")
    assert kfx.count("Gosub(kienzlefon-ai-queue-fallback,s,1)") == 1


def test_ai_slots_are_push_admitted_and_busy_on_busy(app_config) -> None:
    ai = replace(
        app_config.ai_integration,
        enabled=True,
        extension_count=3,
        sip_passwords=("a" * 24, "b" * 24, "c" * 24),
    )
    config = replace(app_config, ai_integration=ai)

    pjsip = render_pjsip(config)
    extensions = render_extensions(config)

    assert "[8810-auth]" in pjsip
    assert "username=8810" in pjsip
    assert "[8812]" in pjsip
    assert "device_state_busy_at=1" in pjsip
    assert "direct_media=no" in pjsip
    assert "exten => 8800,1,Goto(kienzlefon-entry,s,1)" in extensions
    assert "exten => 8801,1,Goto(kienzlefon-in,s,1)" in extensions
    assert "exten => 8802,1,Goto(kfx-phone-queue,s,1)" in extensions
    assert "exten => 8803,1,Goto(kienzlefon-pharmacy-queue,s,1)" in extensions
    assert "exten => 8804,1,Goto(kienzlefon-specialist,s,1)" in extensions
    assert "--selection,specific,--slot-id,ai-slot-02" in extensions
    assert (
        "Dial(PJSIP/${KZF_AI_EXTENSION},120,"
        "gb(kienzlefon-ai-headers^s^1))"
    ) in extensions
    assert "A(:kienzlefon/ai_assistant_intro)" not in extensions
    assert "X-Kienzlefon-Lease-ID" in extensions
    assert "SIP `REFER`" not in extensions
    assert "--phase,opening" in extensions
    zero_shortcut = 'GotoIf($["${KZF_IVR_INITIAL_DIGIT}"="0"]?ai-shortcut)'
    classic_digit = 'GotoIf($["${KZF_IVR_INITIAL_DIGIT}"!="none"]?classic-menu)'
    assert zero_shortcut in extensions
    assert "n(ai-shortcut),Set(KZF_IVR_INITIAL_DIGIT=none)" in extensions
    assert extensions.index(zero_shortcut) < extensions.index(classic_digit)
    assert "--phase,menu,--initial-digit,${KZF_IVR_INITIAL_DIGIT}" in extensions
    classic_menu = extensions.split("[kienzlefon-classic-menu]", 1)[1].split(
        "[kienzlefon-ai-dial]", 1
    )[0]
    assert "Set(KZF_IVR_AI_REQUESTED=0)" in classic_menu
    assert '${KZF_IVR_AI_REQUESTED}"!="1' in classic_menu
    assert '${KZF_AI_HANDOFF_DONE}"="1' in classic_menu
    assert "Goto(kienzlefon-entry,s,ai-shortcut)" in classic_menu
    assert "--selection,call-result" in extensions
    assert 'GotoIf($["${KZF_AI_HANDOFF_TARGET}"="classic"]?handoff-classic)' in extensions
    assert "Goto(kienzlefon-internal-targets,8801,1)" in extensions
    assert "Goto(kienzlefon-internal-targets,8810,1)" not in extensions.split(
        "[kienzlefon-ai-handoff]", 1
    )[1].split("[kienzlefon-ai-queue-fallback]", 1)[0]
    handoff = extensions.split("[kienzlefon-ai-handoff]", 1)[1].split(
        "[kienzlefon-ai-queue-fallback]", 1
    )[0]
    for logical, extension in (
        ("classic", "8801"),
        ("practice", "8802"),
        ("pharmacy", "8803"),
        ("super", "8804"),
    ):
        route = handoff.split(f"exten => {logical},1", 1)[1].split("exten =>", 1)[0]
        assert f"Goto(kienzlefon-internal-targets,{extension},1)" in route
    assert "${KZF_AI_HANDOFF_TARGET}" not in handoff
    fallback = extensions.split("[kienzlefon-ai-queue-fallback]", 1)[1].split(
        "[kienzlefon-ai-headers]", 1
    )[0]
    assert fallback.count("Goto(kienzlefon-internal-targets,8801,1)") == 1

    features = render_features()
    for digit in "0123456789":
        assert f"kzf_ai_dtmf_{digit} = {digit},self,Gosub" in features
    assert "kzf_ai_dtmf_star = *,self,Gosub" in features
    assert "kzf_ai_dtmf_hash = #,self,Gosub" in features
    assert "SoftHangup(${BRIDGEPEER})" in extensions
    assert "Set(DYNAMIC_FEATURES=kzf_ai_dtmf_0#" in extensions
    assert "Set(__DYNAMIC_FEATURES=" not in extensions
    direct = extensions.split("exten => 8810,1", 1)[1].split("exten => 8811,1", 1)[0]
    assert direct.index("--selection,specific") < direct.index("Gosub(kienzlefon-ai-dial")
    assert direct.index("Gosub(kienzlefon-ai-dial") < direct.index("Busy(1)")


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
    (etc / "features.conf").write_text("[general]\n", encoding="utf-8")
    (etc / "extensions-kfx-telefonie.conf").write_text(
        """[kfx-phone-in]
exten => _X.,1,Goto(s,1)
 same => n(accepted),Goto(kfx-phone-queue,s,1)
[kfx-phone-queue]
exten => s,1,NoOp(KienzleFax Telefoniewarteschlange)
 same => n,Queue(praxis,r)
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
    (etc / "features.conf").write_text("[general]\n", encoding="utf-8")
    (etc / "extensions-kfx-telefonie.conf").write_text(
        """[kfx-phone-in]
 same => n(accepted),Goto(kfx-phone-queue,s,1)
[kfx-phone-queue]
exten => s,1,NoOp(KienzleFax Telefoniewarteschlange)
 same => n,Queue(praxis,r)
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
    assert phone.count("Set(CHANNEL(language)=de_kienzlefon)") == 1
    assert "exten => 300,1,Dial(PJSIP/300,120)" in phone
    assert "exten => 777,1,Goto(kienzlefon-red-local,777,1)" in phone
