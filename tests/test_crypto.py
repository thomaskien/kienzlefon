# kienzlefon tests
# Version: 1.8.2
# Changelog:
# - 1.8.2: Dynamische Telepraxis-Versionskennung auf 1.8.2 aktualisiert.
# - 1.8.1: Modus 0660 und Zielverzeichnisgruppe der Telepraxis-Ausgabe getestet.
# - 1.8: Unverschluesselte atomare Demoausgabe ohne Public Key getestet.
# - 1.7.1: Dynamischen Telepraxis-user_agent fuer Version 1.7.1 abgesichert.
# - 1.7: Dynamischen Telepraxis-user_agent fuer Version 1.7 abgesichert.
# - 1.6.2: Dynamischen Telepraxis-user_agent fuer Version 1.6.2 abgesichert.
# - 1.6.1: Dynamischen Telepraxis-user_agent fuer Version 1.6.1 abgesichert.
# - 1.6: Dynamischen Telepraxis-user_agent fuer Version 1.6 abgesichert.
# - 1.5: Dynamischen Telepraxis-user_agent fuer Version 1.5 abgesichert.
# - 1.4: Dynamischen Telepraxis-user_agent fuer Version 1.4 abgesichert.
# - 1.3: Dynamischen Telepraxis-user_agent fuer Version 1.3 abgesichert.
# - 1.2: Dynamischen Telepraxis-user_agent fuer Version 1.2 abgesichert.
# - 1.1: Telepraxis-user_agent fuer Version 1.1 abgesichert.
# - 1.0: Telepraxis-Wrapper, RSA-Huelle, AES-CBC und SHA-256 verifiziert.

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from kienzlefon.crypto import TelepraxisEncryptor
from kienzlefon.crypto import EncryptionError
import pytest


def test_encrypted_file_decrypts_to_transport_record(app_config, private_key) -> None:
    encryptor = TelepraxisEncryptor(
        app_config.telepraxis.public_key,
        app_config.telepraxis.output_directory,
        app_config.practice.timezone,
    )
    target = encryptor.write_payload(
        {
            "typ": "termin",
            "id": "+4923311234",
            "telefon": "+4923311234",
            "zusammenfassung": "keine Zusammenfassung vorhanden",
            "grund": "Termin am Montag",
        },
        "20260711_114658_676879",
    )
    wrapper = json.loads(target.read_text(encoding="utf-8"))
    assert set(wrapper) == {"v", "created_at", "cipher", "sha256", "ek", "iv", "ct"}
    assert wrapper["v"] == 1
    assert wrapper["cipher"] == "AES-256-CBC"

    aes_key = private_key.decrypt(base64.b64decode(wrapper["ek"]), asymmetric_padding.PKCS1v15())
    decryptor = Cipher(
        algorithms.AES(aes_key), modes.CBC(base64.b64decode(wrapper["iv"]))
    ).decryptor()
    padded = decryptor.update(base64.b64decode(wrapper["ct"])) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    assert hashlib.sha256(plaintext).hexdigest() == wrapper["sha256"]
    record = json.loads(plaintext)
    assert record["remote_ip"] == ""
    assert record["user_agent"] == "kienzlefon/1.8.2"
    assert record["typ"] == "termin"
    assert record["payload"]["grund"] == "Termin am Montag"
    assert stat.S_IMODE(target.stat().st_mode) == 0o660
    assert target.stat().st_gid == target.parent.stat().st_gid


def test_php_openssl_open_can_decrypt_wrapper(app_config, private_key, tmp_path) -> None:
    if shutil.which("php") is None:
        return
    encryptor = TelepraxisEncryptor(
        app_config.telepraxis.public_key,
        app_config.telepraxis.output_directory,
        app_config.practice.timezone,
    )
    target = encryptor.write_payload(
        {"typ": "termin", "grund": "Kompatibilitaetstest"},
        "20260711_120000_000001",
    )
    key_path = tmp_path / "private.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    php = r"""
$w = json_decode(file_get_contents($argv[1]), true);
$key = openssl_pkey_get_private(file_get_contents($argv[2]));
$ok = openssl_open(base64_decode($w['ct']), $out, base64_decode($w['ek']), $key, $w['cipher'], base64_decode($w['iv']));
if (!$ok || hash('sha256', $out) !== $w['sha256']) { exit(2); }
echo $out;
"""
    result = subprocess.run(
        ["php", "-r", php, str(target), str(key_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["payload"]["grund"] == "Kompatibilitaetstest"


def test_existing_corrupt_output_is_not_silently_accepted(app_config) -> None:
    encryptor = TelepraxisEncryptor(
        app_config.telepraxis.public_key,
        app_config.telepraxis.output_directory,
        app_config.practice.timezone,
    )
    app_config.telepraxis.output_directory.mkdir(parents=True)
    target = app_config.telepraxis.output_directory / "corrupt.json.enc"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(EncryptionError):
        encryptor.write_payload({"typ": "termin"}, "corrupt")


def test_demo_output_is_plain_transport_json_without_public_key(app_config) -> None:
    writer = TelepraxisEncryptor(
        None,
        app_config.telepraxis.output_directory,
        app_config.practice.timezone,
        demo_mode=True,
    )
    target = writer.write_payload(
        {"typ": "termin", "grund": "Demonstration"},
        "20260713_120000_000001",
    )

    assert target.name == "20260713_120000_000001.json"
    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["user_agent"] == "kienzlefon/1.8.2"
    assert record["typ"] == "termin"
    assert record["payload"]["grund"] == "Demonstration"
    assert not (target.parent / "20260713_120000_000001.json.enc").exists()
    assert stat.S_IMODE(target.stat().st_mode) == 0o660
    assert target.stat().st_gid == target.parent.stat().st_gid

    os.chmod(target, 0o640)
    assert writer.write_payload(
        {"typ": "termin", "grund": "Demonstration"},
        "20260713_120000_000001",
    ) == target
    assert stat.S_IMODE(target.stat().st_mode) == 0o660

    error_payload = writer.error_payload(
        call_id="20260713_120000_000001",
        caller_id="unbekannt",
        phone="unbekannt",
        source_type="termin",
        error={
            "code": "TEST_ERROR",
            "phase": "test",
            "meldung": "Demofehler",
            "zeit": "2026-07-13T12:00:01+02:00",
        },
    )
    error_target = writer.write_payload(error_payload, "demo_error")
    assert error_target.suffix == ".json"
    assert json.loads(error_target.read_text(encoding="utf-8"))["typ"] == "kienzlefon_error"


def test_corrupt_existing_demo_output_is_not_silently_accepted(app_config) -> None:
    writer = TelepraxisEncryptor(
        None,
        app_config.telepraxis.output_directory,
        app_config.practice.timezone,
        demo_mode=True,
    )
    app_config.telepraxis.output_directory.mkdir(parents=True)
    target = app_config.telepraxis.output_directory / "corrupt-demo.json"
    target.write_text("{}", encoding="utf-8")

    with pytest.raises(EncryptionError):
        writer.write_payload({"typ": "termin"}, "corrupt-demo")


def test_root_writer_assigns_owner_and_output_directory_group(app_config, monkeypatch) -> None:
    ownership: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        os,
        "fchown",
        lambda _descriptor, owner, group: ownership.append((owner, group)),
    )
    writer = TelepraxisEncryptor(
        None,
        app_config.telepraxis.output_directory,
        app_config.practice.timezone,
        demo_mode=True,
    )

    writer.write_payload({"typ": "termin"}, "root-group-test")

    assert ownership == [(0, app_config.telepraxis.output_directory.stat().st_gid)]
