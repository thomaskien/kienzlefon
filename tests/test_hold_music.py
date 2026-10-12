from __future__ import annotations

import shutil
import subprocess
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from kienzlefon.asterisk import install_asterisk_config, render_extensions, render_queues
from kienzlefon.config import ConfigError, load_config
from kienzlefon.hold_music import (
    DEFAULT_BROWSER_WAV,
    MUSIC_CLASS,
    install_media,
    render_musiconhold,
)


def test_preview_route_and_music_queue_options_are_conditional(app_config) -> None:
    ringing = replace(
        app_config,
        hold_music=replace(app_config.hold_music, installed=True, mode="klingelzeichen"),
    )
    music = replace(ringing, hold_music=replace(ringing.hold_music, mode="musik"))
    assert "exten => 8805,1,Answer()" in render_extensions(ringing)
    assert f"MusicOnHold({MUSIC_CLASS})" in render_extensions(ringing)
    assert "Queue(praxis,r,,kienzlefon/pharmacy_agent)" in render_extensions(ringing)
    assert "Queue(praxis,,,kienzlefon/pharmacy_agent)" in render_extensions(music)
    assert f"musicclass={MUSIC_CLASS}" in render_queues(music)
    assert "exten => 8805" not in render_extensions(app_config)


def test_additive_moh_configuration_has_no_general_default(tmp_path: Path) -> None:
    rendered = render_musiconhold(tmp_path)
    assert f"[{MUSIC_CLASS}]" in rendered
    assert f"directory={tmp_path}" in rendered
    assert "[general]" not in rendered
    assert "default" not in rendered


def test_hold_music_config_defaults_and_rejects_uninstalled_music(app_config) -> None:
    text = app_config.source.read_text(encoding="utf-8")
    without_section = text[: text.index("[wartemusik]")] + text[text.index("[wahlregeln]") :]
    app_config.source.write_text(without_section, encoding="utf-8")
    assert load_config(app_config.source).hold_music.installed is False
    assert load_config(app_config.source).hold_music.mode == "klingelzeichen"

    app_config.source.write_text(text.replace('modus = "klingelzeichen"', 'modus = "musik"'))
    with pytest.raises(ConfigError, match="erfordert installiert=true"):
        load_config(app_config.source)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
def test_real_audio_is_converted_to_all_formats(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
            "-ar", "44100", "-ac", "2", str(source),
        ],
        check=True,
    )
    installed = install_media(source, tmp_path / "moh")
    assert set(installed) == {"wav16", "sln16", "g722", "alaw", "ulaw"}
    assert all(path.stat().st_size > 0 for path in installed.values())
    assert installed["wav16"].name == "wartemusik.wav16"
    assert not (tmp_path / "moh" / "wartemusik.wav").exists()
    assert DEFAULT_BROWSER_WAV.name == "wartemusik.wav16"
    with wave.open(str(installed["wav16"]), "rb") as handle:
        assert (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) == (
            16000, 1, 2
        )


def test_queue_patch_is_repeatable_and_restores_original_options(
    app_config, tmp_path: Path
) -> None:
    etc = tmp_path / "asterisk"
    etc.mkdir()
    for name, content in {
        "pjsip.conf": "[system]\n",
        "extensions.conf": "[general]\n",
        "queues.conf": "[general]\n",
        "features.conf": "[general]\n",
        "musiconhold.conf": "[default]\nmode=files\n",
        "queues-kfx.conf": "[praxis]\nstrategy=ringall\nmusicclass=fremd\nmember => PJSIP/201,0\n",
        "extensions-kfx-telefonie.conf": (
            "[kfx-phone-in]\n same => n(accepted),Goto(kfx-phone-queue,s,1)\n"
            "[kfx-phone-queue]\nexten => s,1,NoOp(KienzleFax Telefoniewarteschlange)\n"
            " same => n,Set(QUEUE_RAISE_PENALTY=0)\n"
            " same => n,Queue(praxis,rWt)\n same => n,Hangup()\n"
            "[kfx-phone-local]\nexten => _X.,1,NoOp(KienzleFax Telefonie ausgehend)\n"
            " same => n,Dial(PJSIP/${EXTEN}@provider,120)\n"
        ),
    }.items():
        (etc / name).write_text(content, encoding="utf-8")
    music = replace(
        app_config,
        hold_music=replace(app_config.hold_music, installed=True, mode="musik"),
    )
    install_asterisk_config(music, etc)
    install_asterisk_config(music, etc)
    phone = (etc / "extensions-kfx-telefonie.conf").read_text(encoding="utf-8")
    queues = (etc / "queues-kfx.conf").read_text(encoding="utf-8")
    assert phone.count("; kienzlefon queue option begin") == 1
    assert "Queue(praxis,Wt)" in phone
    assert "musicclass=fremd" in queues
    assert queues.count(f"musicclass={MUSIC_CLASS}") == 1

    ringing = replace(music, hold_music=replace(music.hold_music, mode="klingelzeichen"))
    install_asterisk_config(ringing, etc)
    phone = (etc / "extensions-kfx-telefonie.conf").read_text(encoding="utf-8")
    queues = (etc / "queues-kfx.conf").read_text(encoding="utf-8")
    assert "Queue(praxis,rWt)" in phone
    assert "; kienzlefon queue option begin" not in phone
    assert "musicclass=fremd" in queues
    assert f"musicclass={MUSIC_CLASS}" not in queues


@pytest.mark.parametrize('section,expected', [
    ('', {'installiert': True, 'modus': 'musik'}),
    ('[wartemusik]\ninstalliert = false\nmodus = "klingelzeichen"\n',
     {'installiert': False, 'modus': 'klingelzeichen'}),
    ('[wartemusik]\ninstalliert = true\nmodus = "klingelzeichen"\n',
     {'installiert': True, 'modus': 'klingelzeichen'}),
    ('[wartemusik]\ninstalliert = false\n',
     {'installiert': False, 'modus': 'klingelzeichen'}),
])
def test_music_migration_uses_new_defaults_only_for_missing_decisions(tmp_path, section, expected):
    import tomllib

    from kienzlefon.migration import migrate_config
    template = Path('config/kienzlefon.toml.example')
    assert tomllib.loads(template.read_text())['wartemusik'] == {'installiert': True, 'modus': 'musik'}
    source = template.read_text()
    start, end = source.index('[wartemusik]'), source.index('[wahlregeln]')
    source = source[:start] + section + '\n' + source[end:]
    # The new assistant switch must also retain an explicit off preference.
    source = source.replace('assistent_aktiv = true', 'assistent_aktiv = false')
    target = tmp_path / 'config.toml'
    target.write_text(source)
    migrate_config(target, template)
    values = tomllib.loads(target.read_text())
    assert values['wartemusik'] == expected
    assert values['ki_integration']['assistent_aktiv'] is False
    assert not migrate_config(target, template)
