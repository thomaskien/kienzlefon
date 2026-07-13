# kienzlefon
# Version: 1.8.1
# Changelog:
# - 1.8.1: Telepraxis-Ausgabedateien gruppenschreibbar mit 0660 angelegt.
# - 1.8: Atomare unverschluesselte JSON-Ausgabe fuer den expliziten Demomodus ergaenzt.
# - 1.1: Telepraxis-user_agent an die zentrale Paketversion gebunden.
# - 1.0: OpenSSL-kompatible Hybridverschluesselung und atomare json.enc-Ausgabe.

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import __version__


class EncryptionError(RuntimeError):
    pass


class TelepraxisEncryptor:
    def __init__(
        self,
        public_key_path: Path | None,
        output_directory: Path,
        timezone: ZoneInfo,
        *,
        demo_mode: bool = False,
    ):
        self.public_key_path = public_key_path
        self.output_directory = output_directory
        self.timezone = timezone
        self.demo_mode = demo_mode
        self.public_key = None if demo_mode else self._load_public_key()

    def _load_public_key(self) -> RSAPublicKey:
        if self.public_key_path is None:
            raise EncryptionError("Telepraxis-Public-Key fehlt im Produktivmodus")
        try:
            key = serialization.load_pem_public_key(self.public_key_path.read_bytes())
        except Exception as exc:
            raise EncryptionError(f"Ungueltiger Telepraxis-Public-Key: {exc}") from exc
        if not isinstance(key, RSAPublicKey):
            raise EncryptionError("Telepraxis-Public-Key ist kein RSA-Schluessel")
        if key.key_size < 2048:
            raise EncryptionError("Telepraxis-Public-Key muss mindestens 2048 Bit haben")
        return key

    def build_plaintext_record(self, payload: dict[str, Any]) -> bytes:
        typ = str(payload.get("typ", "unknown")) or "unknown"
        record = {
            "received_at": datetime.now(self.timezone).isoformat(timespec="seconds"),
            "remote_ip": "",
            "user_agent": f"kienzlefon/{__version__}",
            "typ": typ,
            "payload": payload,
        }
        return json.dumps(record, ensure_ascii=False, indent=4).encode("utf-8")

    def encrypt(self, plaintext: bytes) -> dict[str, Any]:
        if self.public_key is None:
            raise EncryptionError("Verschluesselung ist im Demomodus nicht aktiv")
        key = secrets.token_bytes(32)
        iv = secrets.token_bytes(16)
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded = padder.update(plaintext) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        encrypted_key = self.public_key.encrypt(key, asymmetric_padding.PKCS1v15())
        return {
            "v": 1,
            "created_at": datetime.now(self.timezone).isoformat(timespec="seconds"),
            "cipher": "AES-256-CBC",
            "sha256": hashlib.sha256(plaintext).hexdigest(),
            "ek": base64.b64encode(encrypted_key).decode("ascii"),
            "iv": base64.b64encode(iv).decode("ascii"),
            "ct": base64.b64encode(ciphertext).decode("ascii"),
        }

    def write_payload(self, payload: dict[str, Any], basename: str) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True)
        plaintext = self.build_plaintext_record(payload)
        if self.demo_mode:
            target = self.output_directory / f"{basename}.json"
            content = plaintext.decode("utf-8") + "\n"
            self._validate_existing_plaintext(target)
        else:
            target = self.output_directory / f"{basename}.json.enc"
            content = ""
        if target.exists():
            if not self.demo_mode:
                self._validate_existing_encrypted(target)
            self._apply_output_permissions(target)
            return target
        if not self.demo_mode:
            wrapper = self.encrypt(plaintext)
            content = json.dumps(wrapper, ensure_ascii=False, indent=4) + "\n"
        temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                self._apply_output_descriptor_permissions(handle.fileno())
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(self.output_directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception as exc:
            raise EncryptionError(
                f"Telepraxis-Datei konnte nicht geschrieben werden: {exc}"
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def _apply_output_permissions(self, target: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target, flags)
            try:
                self._apply_output_descriptor_permissions(descriptor)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise EncryptionError(
                f"Telepraxis-Dateirechte konnten nicht gesetzt werden: {exc}"
            ) from exc

    def _apply_output_descriptor_permissions(self, descriptor: int) -> None:
        if os.geteuid() == 0:
            os.fchown(descriptor, 0, self.output_directory.stat().st_gid)
        os.fchmod(descriptor, 0o660)

    @staticmethod
    def _validate_existing_plaintext(target: Path) -> None:
        if not target.exists():
            return
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EncryptionError(f"Vorhandene Zieldatei ist unbrauchbar: {target}") from exc
        required = {"received_at", "remote_ip", "user_agent", "typ", "payload"}
        if not isinstance(existing, dict) or not required.issubset(existing):
            raise EncryptionError(f"Vorhandene Zieldatei hat ein falsches Format: {target}")
        if not isinstance(existing.get("payload"), dict):
            raise EncryptionError(f"Vorhandene Zieldatei hat ein falsches Format: {target}")

    @staticmethod
    def _validate_existing_encrypted(target: Path) -> None:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EncryptionError(f"Vorhandene Zieldatei ist unbrauchbar: {target}") from exc
        required = {"v", "created_at", "cipher", "sha256", "ek", "iv", "ct"}
        if not isinstance(existing, dict) or set(existing) != required or existing.get("v") != 1:
            raise EncryptionError(f"Vorhandene Zieldatei hat ein falsches Format: {target}")

    @staticmethod
    def error_payload(
        *,
        call_id: str,
        caller_id: str,
        phone: str,
        source_type: str,
        error: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "typ": "kienzlefon_error",
            "ursprungstyp": source_type,
            "id": caller_id,
            "telefon": phone,
            "zusammenfassung": "keine Zusammenfassung vorhanden",
            "vorgang_id": call_id,
            "fehlercode": str(error.get("code", "UNKNOWN_ERROR")),
            "fehlerphase": str(error.get("phase", "unbekannt")),
            "fehlermeldung": str(error.get("meldung", "Unbekannter Fehler")),
            "zeit": str(error.get("zeit", "")),
        }
