"""Drive the delivery menu over a terminal, including a complete multiline paste."""
import errno
import json
import os
import pty
import select
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa


MODE = "Auswahl (1 oder 2)"
METHOD = "Auswahl [1]:"
PASTE = "bis einschließlich -----END PUBLIC KEY-----."
FILE = "Pfad zur Telepraxis-Public-Key-PEM-Datei"
AUDIO = "Audio beilegen? Bei Nein wird nur JSON ausgegeben."
SCRIPT = r'''
source "$1"
CONFIG_DIR="$2/config"
PUBLIC_KEY_FILE="$CONFIG_DIR/telepraxis-public.pem"
CONFIG_FILE="$CONFIG_DIR/kienzlefon.toml"
VENV="$2"
collect_delivery_configuration
printf 'Ergebnis|%s|%s|%s\n' "$KZF_DELIVERY_PUBLIC_KEY" "$KZF_ATTACH_AUDIO" "$KZF_DEMO_MODE"
'''


def public_pem(key):
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


@pytest.fixture
def dialog(tmp_path):
    binary = tmp_path / "bin/python"
    binary.parent.mkdir()
    binary.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    binary.chmod(0o755)
    (tmp_path / "config").mkdir()

    def interact(steps, *, observe=None):
        master, slave = pty.openpty()
        root = Path.cwd()
        process = subprocess.Popen(["bash", "-c", SCRIPT, "test", root / "kienzlefon-installer.sh", tmp_path],
                                   stdin=slave, stdout=slave, stderr=slave,
                                   env={**os.environ, "PYTHONPATH": str(root)})
        os.close(slave)
        pending = b""
        transcript = b""
        try:
            for prompt, reply in steps:
                marker = prompt.encode()
                limit = time.monotonic() + 6
                while marker not in pending:
                    assert select.select([master], [], [], max(0, limit - time.monotonic()))[0], prompt
                    try:
                        chunk = os.read(master, 4096)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        chunk = b""
                    assert chunk, f"Installer endete vor {prompt!r}: {pending!r}"
                    transcript += chunk
                    pending += chunk
                pending = pending.split(marker, 1)[1]
                if observe:
                    observe(prompt)
                if reply is not None:
                    os.write(master, reply)
            assert process.wait(timeout=6) == 0
            return transcript.decode()
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()
    return interact


def test_paste_stops_at_footer_and_leaves_next_answer_for_installer(dialog, tmp_path):
    # The practice-side app installer generates a 4096-bit RSA key.
    pem = public_pem(rsa.generate_private_key(public_exponent=65537, key_size=4096))
    target = tmp_path / "config/telepraxis-public.pem"
    transcript = dialog([(MODE, b"2\n"), (METHOD, b"\n"), (PASTE, pem),
                         (AUDIO, b"j\n"), ("unterstützt Vorgangspaket v1 und Quittungen?", b"j\n"),
                         (f"Ergebnis|{target}|y|n", None)])
    assert "Der App-Installer gibt ihn bei der Einrichtung der App mit Abholer aus." in transcript
    assert target.read_bytes() == pem


def test_invalid_block_and_file_retry_then_import_from_path(dialog, tmp_path, private_key):
    target = tmp_path / "config/telepraxis-public.pem"
    target.write_bytes(b"bisherige ungueltige Datei\n")
    original = target.read_bytes()
    good = tmp_path / "Schlüssel mit Leerzeichen.pem"
    pem = public_pem(private_key)
    good.write_bytes(pem)
    ec_public = tmp_path / "ec.pem"
    ec_public.write_bytes(public_pem(ec.generate_private_key(ec.SECP256R1())))
    too_short = public_pem(rsa.generate_private_key(public_exponent=65537, key_size=1024))
    bad = b"-----BEGIN PUBLIC KEY-----\ndefekt\n-----END PUBLIC KEY-----\n"

    def still_unchanged(prompt):
        if prompt == METHOD:
            assert target.read_bytes() == original

    transcript = dialog([
        (MODE, b"\n"), (METHOD, b"1\n"), (PASTE, bad), (METHOD, b"1\n"), (PASTE, too_short),
        (METHOD, b"2\n"), (FILE, b"/nonexistent/key.pem\n"),
        (METHOD, b"2\n"), (FILE, os.fsencode(ec_public) + b"\n"),
        (METHOD, b"2\n"), (FILE, os.fsencode(good) + b"\n"),
        (AUDIO, b"n\n"), (f"Ergebnis|{target}|n|n", None),
    ], observe=still_unchanged)
    assert "keinen gültigen öffentlichen PEM-Schlüssel" in transcript
    assert "mindestens 2048 Bit" in transcript
    assert "PEM-Datei fehlt oder ist nicht lesbar" in transcript
    assert "kein RSA-Schlüssel" in transcript
    assert target.read_bytes() == pem


@pytest.mark.parametrize("custom_path", [False, True])
def test_encrypted_update_reuses_valid_key_without_rewriting(dialog, tmp_path, private_key, custom_path):
    config = tmp_path / "config"
    target = tmp_path / "bestehender Schlüssel.pem" if custom_path else config / "telepraxis-public.pem"
    target.write_bytes(public_pem(private_key))
    if custom_path:
        (config / "kienzlefon.toml").write_text('[telepraxis]\npublic_key = ' + json.dumps(str(target)))
    before = target.stat()
    transcript = dialog([(MODE, b"\n"), (AUDIO, b"n\n"), (f"Ergebnis|{target}|n|n", None)])
    assert METHOD not in transcript
    assert (target.stat().st_ino, target.stat().st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_local_delivery_skips_key_dialog(dialog, tmp_path):
    transcript = dialog([(MODE, b"1\n"), (AUDIO, b"n\n"), ("Ergebnis||n|y", None)])
    assert "RSA-Public-Key" not in transcript
    assert not (tmp_path / "config/telepraxis-public.pem").exists()
