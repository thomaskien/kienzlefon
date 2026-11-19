"""Exercise the producer and the receipt protocol using a disposable RSA recipient."""
import base64
import hashlib
import io
import json
import wave
from dataclasses import replace
from zipfile import ZIP_STORED, ZipFile

import pytest
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kienzlefon.delivery import ERROR
from kienzlefon.models import CallState, CallType, FieldName
from kienzlefon.spool import WorkingCall
from kienzlefon.worker import Worker


def record_call(worker):
    call = worker.spool.create_call(CallType.APPOINTMENT, "unbekannt", "test")
    wav = call.begin_audio(FieldName.REASON, "grund.wav")
    with wave.open(str(wav), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", ""))
        audio.writeframes(b"\x00\x01" * 160)
    data = wav.read_bytes()
    worker.spool.finish_recording(call, "abgeschlossen")
    claimed = worker.spool.claim_next()
    assert claimed is not None
    worker.process(WorkingCall(claimed.path, worker.config.practice.timezone))
    ready, = worker.spool.calls(CallState.READY)
    return ready, data


class Transcriber:
    def transcribe(self, path, field):
        return "Testtermin"


def receipt(directory, target, identifier, status, *, digest=None):
    digest = digest or hashlib.sha256(target.read_bytes()).hexdigest()
    directory.mkdir(exist_ok=True)
    doc = {"v": 1, "vorgang_id": identifier, "datei": target.name, "sha256": digest, "status": status}
    (directory / f"{identifier}.{digest}.{status}.ack.json").write_text(json.dumps(doc))


def decode_fallback(target, key):
    wrapper = json.loads(target.read_bytes())
    assert wrapper["v"] == 1 and wrapper["cipher"] == "AES-256-CBC"
    aes_key = key.decrypt(base64.b64decode(wrapper["ek"]), rsa_padding.PKCS1v15())
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(base64.b64decode(wrapper["iv"]))).decryptor()
    padded = cipher.update(base64.b64decode(wrapper["ct"])) + cipher.finalize()
    unpad = padding.PKCS7(128).unpadder()
    data = unpad.update(padded) + unpad.finalize()
    assert hashlib.sha256(data).hexdigest() == wrapper["sha256"]
    return json.loads(data)["payload"]


@pytest.mark.parametrize("needs_fallback", [False, True])
def test_encrypted_audio_waits_for_receipt_matching_the_delivered_file(app_config, private_key, needs_fallback):
    config = replace(app_config, telepraxis=replace(app_config.telepraxis, attach_audio=True))
    worker = Worker(config, Transcriber())
    call, data = record_call(worker)
    wav = call.audio_directory / "grund.wav"
    output = config.telepraxis.output_directory
    target = output / f"{call.call_id}.kienzlepaket"
    original = target.read_bytes()
    header, wrapped, nonce, ciphertext, tag = original.split(b".")
    def decode(segment):
        return base64.urlsafe_b64decode(segment + b"=" * (-len(segment) % 4))
    assert json.loads(decode(header)) == {"typ": "kienzlefon-paket-v1+jwe", "cty": "application/zip",
                                         "alg": "RSA-OAEP-256", "enc": "A256GCM"}
    key = private_key.decrypt(decode(wrapped), rsa_padding.OAEP(
        mgf=rsa_padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    archive = AESGCM(key).decrypt(decode(nonce), decode(ciphertext) + decode(tag), header)
    with ZipFile(io.BytesIO(archive)) as package:
        assert package.namelist() == ["vorgang.json", "audio/grund.wav"]
        assert all(item.compress_type == ZIP_STORED for item in package.infolist())
        assert package.read("audio/grund.wav") == data
        payload = json.loads(package.read("vorgang.json"))["payload"]
        assert payload["_kienzlefon"]["vorgang_id"] == call.call_id
        assert payload["grund"] == "Testtermin"

    # A restart and an acknowledgement for other bytes cannot release the source.
    worker = Worker(config, Transcriber())
    receipts = worker.delivery.receipts
    receipt(receipts, target, call.call_id, "abgelegt", digest="1" * 64)
    worker._poll_delivery_receipts()
    assert wav.read_bytes() == data and target.read_bytes() == original
    confirmed = target
    if needs_fallback:
        receipt(receipts, target, call.call_id, "ersatz_json_noetig")
        worker._poll_delivery_receipts()
        confirmed = output / f"{call.call_id}.json.enc"
        fallback = decode_fallback(confirmed, private_key)
        assert fallback["grund"] == payload["grund"]
        assert fallback["_kienzlefon"]["vorgang_id"] == call.call_id
        assert fallback["_kienzlefon"]["audio"] == []
        assert fallback["_kienzlefon"]["audio_beilage"] == ERROR
        previous = confirmed.read_bytes()
        worker._poll_delivery_receipts()
        assert confirmed.read_bytes() == previous and wav.exists()
    receipt(receipts, confirmed, call.call_id, "abgelegt")
    worker._poll_delivery_receipts()
    worker._poll_delivery_receipts()
    assert not any(path.exists() for path in (wav, target, confirmed, call.path / "lieferung.json"))


@pytest.mark.parametrize("attach", [False, True])
def test_local_inbox_has_only_requested_audio_and_the_spool_is_cleared(app_config, attach):
    config = replace(app_config, telepraxis=replace(app_config.telepraxis, demo=True, attach_audio=attach))
    worker = Worker(config, Transcriber())
    call, data = record_call(worker)
    inbox = config.telepraxis.output_directory
    payload = json.loads((inbox / f"{call.call_id}.json").read_bytes())["payload"]
    wav = inbox / call.call_id / "audio/grund.wav"
    assert payload["grund"] == "Testtermin"
    assert "audio_beilage" not in payload["_kienzlefon"]
    if attach:
        assert wav.read_bytes() == data
        assert [a["datei"] for a in payload["_kienzlefon"]["audio"]] == ["audio/grund.wav"]
    else:
        assert not wav.exists() and payload["_kienzlefon"]["audio"] == []
    assert not list(call.audio_directory.glob("*.wav"))
