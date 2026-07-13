# kienzlefon tests
# Version: 1.6.2
# Changelog:
# - 1.6.2: AGI 511 als Hangup und andere Protokollfehler weiterhin als Fehler getestet.
# - 1.5: Administrativen Signalton bei unveraendert stillen Patientenaufnahmen getestet.
# - 1.1: Signaltonfreie Record-Option q abgesichert.
# - 1.0: AGI-Protokoll und Record-Optionen fuer Stille, DTMF und Hangup getestet.

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from kienzlefon.agi import AgiChannel, AgiError, AgiHangup


def test_record_uses_keep_on_hangup_and_any_digit(tmp_path) -> None:
    stdin = StringIO("agi_callerid: +4923311234\n\n200 result=0\n200 result=1 (SILENCE)\n")
    stdout = StringIO()
    channel = AgiChannel(stdin, stdout)
    path = tmp_path / "vorname.wav"
    path.write_bytes(b"RIFF" + b"0" * 100)
    result = channel.record(path, silence_seconds=3, max_seconds=30)
    assert result.present is True
    assert result.status == "SILENCE"
    assert f'EXEC Record "{path},3,30,kqy"' in stdout.getvalue()


def test_stream_file_returns_pressed_digit(tmp_path) -> None:
    stdin = StringIO("agi_callerid: unknown\n\n200 result=54\n")
    stdout = StringIO()
    channel = AgiChannel(stdin, stdout)
    assert channel.stream_file(tmp_path / "menu", "12345689") == "6"


def test_record_can_enable_beep_for_announcement_recording(tmp_path) -> None:
    stdin = StringIO("agi_callerid: 201\n\n200 result=0\n200 result=1 (DTMF)\n")
    stdout = StringIO()
    channel = AgiChannel(stdin, stdout)
    path = tmp_path / "ansage.wav16"
    path.write_bytes(b"RIFF" + b"0" * 100)
    channel.record(path, silence_seconds=3, max_seconds=180, beep=True)
    assert f'EXEC Record "{path},3,180,ky"' in stdout.getvalue()


def test_dead_channel_response_is_a_regular_hangup() -> None:
    stdin = StringIO(
        "agi_callerid: +4923311234\n\n"
        "511 Command Not Permitted on a dead channel or intercept routine\n"
    )
    channel = AgiChannel(stdin, StringIO())

    with pytest.raises(AgiHangup, match="bereits beendet"):
        channel.stream_file(Path("completed"))


def test_other_unexpected_agi_response_remains_an_error() -> None:
    stdin = StringIO("agi_callerid: +4923311234\n\n510 Invalid or unknown command\n")
    channel = AgiChannel(stdin, StringIO())

    with pytest.raises(AgiError, match="Unerwartete AGI-Antwort"):
        channel.stream_file(Path("completed"))
