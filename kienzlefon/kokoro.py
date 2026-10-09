"""Offline Kokoro-Thorsten synthesis for Kienzlefon 2.4.1.

Uses the pinned German model and forks from kienzlefon-ai 2.6, on CPU.
Heavy dependencies are imported only in the separately installed generator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import wave
from pathlib import Path

MODEL_REVISION = "734e593d320a3d876bede7020f773dfd481a0cc7"
MODEL_FILES = ("config.json", "model.pth", "voices/thorsten.pt")
RUNTIME_VERSION = "2.4.1"


def verify_model(directory: Path, manifest: dict) -> None:
    if manifest.get("revision") != MODEL_REVISION:
        raise RuntimeError("Kokoro-Modellrevision stimmt nicht ueberein")
    for name in MODEL_FILES:
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Lokale Kokoro-Modelldatei fehlt oder ist unsicher: {name}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != manifest["files"][name]["sha256"]:
            raise RuntimeError(f"Kokoro-Pruefsumme stimmt nicht ueberein: {name}")


def phoneme_chunks(text: str, g2p):
    """Split before inference; the upstream non-English path truncates at 510.

    Preserve every word, including unusually long multi-sentence announcements.
    Reject an overlong single token instead of silently losing speech.
    """
    for sentence in re.split(r"(?<=[.!?;:])\s+|\n+", text.strip()):
        if not sentence.strip():
            continue
        phonemes, _ = g2p(sentence)
        phonemes = phonemes.replace("ʏ", "y").strip()
        if len(phonemes) <= 510:
            if phonemes:
                yield phonemes
            continue
        words = sentence.split()
        if len(words) < 2:
            raise RuntimeError("Kokoro: einzelnes Wort ueberschreitet das Phonemlimit")
        midpoint = len(words) // 2
        yield from phoneme_chunks(" ".join(words[:midpoint]), g2p)
        yield from phoneme_chunks(" ".join(words[midpoint:]), g2p)


def synthesize(text: str, output: Path, model_dir: Path, speed: float, manifest: dict) -> None:
    if not text.strip():
        raise ValueError("Kokoro benoetigt einen nichtleeren Text")
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("Kokoro-Speed muss endlich und groesser als 0 sein")
    verify_model(model_dir, manifest)
    # No lazy network downloads or text/phoneme logging during generation.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    from loguru import logger

    logger.disable("kokoro")
    logger.disable("misaki")
    logging.getLogger("phonemizer").setLevel(logging.CRITICAL)
    import numpy as np
    import torch
    from kokoro import KModel, KPipeline
    from misaki.de import normalize_text_de

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.manual_seed(1234)
    model = KModel(
        repo_id="hexgrad/Kokoro-82M",
        config=str(model_dir / "config.json"),
        model=str(model_dir / "model.pth"),
    ).to("cpu").eval()
    pipeline = KPipeline(lang_code="d", repo_id="hexgrad/Kokoro-82M", model=model)
    voice = torch.load(model_dir / "voices/thorsten.pt", map_location="cpu", weights_only=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".kokoro-", suffix=".wav", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        frames = 0
        with wave.open(str(temporary), "wb") as wav, torch.inference_mode():
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            for phonemes in phoneme_chunks(normalize_text_de(text), pipeline.g2p):
                for result in pipeline.generate_from_tokens(phonemes, voice=voice, speed=speed):
                    audio = result.audio.detach().cpu().numpy()
                    if not np.isfinite(audio).all():
                        raise RuntimeError("Kokoro hat ungueltige Audiodaten erzeugt")
                    pcm = np.clip(audio * 32767, -32768, 32767).astype("<i2").tobytes()
                    wav.writeframes(pcm)
                    frames += len(pcm) // 2
        if not frames:
            raise RuntimeError("Kokoro hat keine Audiodaten erzeugt")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lokale Kokoro-Thorsten-Ansage auf CPU erzeugen")
    parser.add_argument("--version", action="version", version=RUNTIME_VERSION)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name("model_manifest.json").read_text())
    try:
        synthesize(args.text, args.output, args.model_dir, args.speed, manifest)
    except Exception:  # noqa: BLE001 — external errors can contain private source text
        # Third-party exceptions may include source text. Keep normal logs private.
        raise SystemExit("Kokoro-Erzeugung fehlgeschlagen; lokale Installation/Modelle pruefen") from None


if __name__ == "__main__":
    main()
