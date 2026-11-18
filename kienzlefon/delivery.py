"""Vorgangspaket v1 and source cleanup after acknowledged delivery."""

from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import io
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .crypto import EncryptionError, TelepraxisEncryptor
from .spool import WorkingCall, write_json_atomic

ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
WAV_PATH = re.compile(r"audio/[A-Za-z0-9_-]+\.wav")
HEADER = {
    "typ": "kienzlefon-paket-v1+jwe",
    "cty": "application/zip",
    "alg": "RSA-OAEP-256",
    "enc": "A256GCM",
}
MAX_AUDIO_BYTES = 32 * 1024 * 1024
ERROR = {"schema_version": 1, "status": "fehler", "fehlercode": "audio_uebergabe_fehlgeschlagen"}


def _base64url(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_file(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(prefix=".kienzlefon-", dir=path.parent, delete=False) as out:
        pending = Path(out.name)
        try:
            out.write(data)
            out.flush()
            os.fchmod(out.fileno(), 0o660)
            os.fsync(out.fileno())
            os.replace(pending, path)
            _sync_directory(path.parent)
        finally:
            pending.unlink(missing_ok=True)


class Delivery:
    """Only writes in the configured output directory and the claimed call."""

    def __init__(self, encryptor: TelepraxisEncryptor):
        self.encryptor = encryptor
        self.output = encryptor.output_directory
        self.receipts = self.output / ".kienzlefon-ack"

    @staticmethod
    def _audio(call: WorkingCall, record: dict) -> tuple[dict, dict[str, bytes]]:
        payload = copy.deepcopy(record)
        files = {}
        entries = []
        remaining = MAX_AUDIO_BYTES
        if call.audio_directory.is_symlink():
            raise ValueError("Ungueltiges Audioverzeichnis")
        for entry in payload["_kienzlefon"]["audio"]:
            path = entry.get("datei")
            if entry.get("datei_vorhanden") is False or entry.get("status") == "empty":
                continue
            if not isinstance(path, str) or not WAV_PATH.fullmatch(path) or path in files:
                raise ValueError("Ungueltiger Audioverweis")
            source = call.path / path
            if source.is_symlink() or not source.is_file():
                raise ValueError("Audio fehlt")
            with source.open("rb") as handle:
                data = handle.read(remaining + 1)
            if len(data) > remaining:
                raise ValueError("Audio-Paket zu gross")
            if len(data) <= 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                raise ValueError("Ungueltige WAV")
            remaining -= len(data)
            files[path] = data
            entries.append(entry)
        payload["_kienzlefon"]["audio"] = entries
        return payload, files

    @staticmethod
    def _without_audio(record: dict, *, failed: bool = False) -> dict:
        payload = copy.deepcopy(record)
        metadata = payload["_kienzlefon"]
        metadata["audio"] = []
        if failed:
            metadata["audio_beilage"] = ERROR.copy()
        return payload

    @staticmethod
    def remove_source_audio(call: WorkingCall) -> None:
        if call.audio_directory.is_symlink():
            raise ValueError("Ungueltiges Audioverzeichnis")
        if call.audio_directory.is_dir():
            for file in call.audio_directory.glob("*.wav"):
                if file.is_file() or file.is_symlink():
                    file.unlink()
            _sync_directory(call.audio_directory)

    def _seal(self, json_bytes: bytes, files: dict[str, bytes]) -> bytes:
        archive = io.BytesIO()
        with ZipFile(archive, "w", ZIP_STORED) as bundle:
            bundle.writestr("vorgang.json", json_bytes)
            for name, data in files.items():
                bundle.writestr(name, data)
        protected = _base64url(json.dumps(HEADER, separators=(",", ":")).encode("ascii"))
        key = AESGCM.generate_key(bit_length=256)
        nonce = secrets.token_bytes(12)
        wrapped = self.encryptor.public_key.encrypt(
            key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        ciphertext = AESGCM(key).encrypt(nonce, archive.getbuffer(), protected)
        return b".".join([protected, *map(_base64url, (wrapped, nonce, ciphertext[:-16], ciphertext[-16:]))])

    def _write_local(self, identifier: str, payload: dict, files: dict[str, bytes]) -> None:
        # Same advisory lock as PHP mutations, including moving to the trash.
        with (self.output / ".telepraxis-inbox.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            target = self.output / f"{identifier}.json"
            trash = self.output / "papierkorb" / target.name
            if target.exists() or trash.exists():
                return
            audio_dir = self.output / identifier / "audio"
            if audio_dir.is_symlink() or audio_dir.parent.is_symlink():
                raise ValueError("Ungueltiges Inbox-Audioverzeichnis")
            if files:
                audio_dir.mkdir(mode=0o770, parents=True, exist_ok=True)
                for name, data in files.items():
                    _write_file(audio_dir / Path(name).name, data)
            self.encryptor.write_payload(payload, identifier)

    def publish(self, call: WorkingCall, record: dict, *, attach: bool) -> None:
        try:
            self._publish(call, record, attach=attach)
        except (OSError, ValueError) as exc:
            raise EncryptionError("Vorgangsausgabe fehlgeschlagen") from exc

    def _publish(self, call: WorkingCall, record: dict, *, attach: bool) -> None:
        identifier = call.call_id
        if not ID.fullmatch(identifier) or record["_kienzlefon"]["vorgang_id"] != identifier:
            raise ValueError("Ungueltige Vorgangs-ID")
        self.output.mkdir(parents=True, exist_ok=True)
        if not attach:
            payload = self._without_audio(record)
            if self.encryptor.demo_mode:
                self._write_local(identifier, payload, {})
            elif payload["_kienzlefon"].get("audio_beilage") == ERROR:
                self._write_fallback(call, payload)
                return
            else:
                self.encryptor.write_payload(payload, identifier)
            self.remove_source_audio(call)
            return
        state_path = call.path / "lieferung.json"
        if state_path.is_file():
            return
        try:
            payload, files = self._audio(call, record)
        except ValueError:
            payload = self._without_audio(record, failed=True)
            if self.encryptor.demo_mode:
                self._write_local(identifier, payload, {})
                self.remove_source_audio(call)
            else:
                self._write_fallback(call, payload)
            return
        if not files:
            if self.encryptor.demo_mode:
                self._write_local(identifier, payload, {})
            else:
                self.encryptor.write_payload(payload, identifier)
            self.remove_source_audio(call)
            return
        if self.encryptor.demo_mode:
            self._write_local(identifier, payload, files)
            self.remove_source_audio(call)
            return
        filename = f"{identifier}.kienzlepaket"
        target = self.output / filename
        if not target.is_file():
            _write_file(target, self._seal(self.encryptor.build_plaintext_record(payload), files))
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        write_json_atomic(state_path, {"paket": digest})

    def _write_fallback(self, call: WorkingCall, payload: dict, *, state: dict | None = None) -> None:
        state_path = call.path / "lieferung.json"
        if state is None:
            if state_path.exists():
                return
            state = {}
        target = self.encryptor.write_payload(payload, call.call_id)
        state["ersatz"] = hashlib.sha256(target.read_bytes()).hexdigest()
        write_json_atomic(state_path, state)

    def _receipt(self, identifier: str, filename: str, digest: str, status: str) -> Path | None:
        receipt = self.receipts / f"{identifier}.{digest}.{status}.ack.json"
        try:
            with receipt.open("rb") as handle:
                document = json.loads(handle.read(4097))
        except (FileNotFoundError, ValueError):
            return None
        if document == {"v": 1, "vorgang_id": identifier, "datei": filename,
                        "sha256": digest, "status": status}:
            return receipt
        return None

    def receive_ack(self, call: WorkingCall) -> None:
        state_path = call.path / "lieferung.json"
        if not state_path.is_file():
            return
        state = json.loads(state_path.read_bytes())
        identifier = call.call_id
        package = f"{identifier}.kienzlepaket"
        fallback = f"{identifier}.json.enc"
        stored = self._receipt(identifier, package, state["paket"], "abgelegt") if "paket" in state else None
        if not stored and "ersatz" in state:
            stored = self._receipt(identifier, fallback, state["ersatz"], "abgelegt")
        if stored or state.get("abgelegt"):
            if not state.get("abgelegt"):
                state["abgelegt"] = True
                write_json_atomic(state_path, state)
            self.remove_source_audio(call)
            (self.output / package).unlink(missing_ok=True)
            if "ersatz" in state:
                (self.output / fallback).unlink(missing_ok=True)
            for suffix in ("abgelegt", "ersatz_json_noetig", "ueberholt"):
                for digest in (state.get("paket"), state.get("ersatz")):
                    if digest:
                        (self.receipts / f"{identifier}.{digest}.{suffix}.ack.json").unlink(missing_ok=True)
            _sync_directory(self.output)
            state_path.unlink(missing_ok=True)
            return
        if "ersatz" not in state and self._receipt(identifier, package, state["paket"], "ersatz_json_noetig"):
            self._write_fallback(call, self._without_audio(call.load(), failed=True), state=state)
