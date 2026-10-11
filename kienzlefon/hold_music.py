"""Installation der optionalen, nur fuer Kienzlefon verwendeten Wartemusik."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from .config import AppConfig, load_config
from .prompts import PromptGenerator

MUSIC_CLASS = "kienzlefon-wartemusik"
SOURCE_FILENAME = "johannes-plachetka-warteschlange.wav"
DEFAULT_MOH_DIRECTORY = Path("/var/lib/asterisk/moh") / MUSIC_CLASS
DEFAULT_BROWSER_WAV = DEFAULT_MOH_DIRECTORY / "wartemusik.wav16"
FORMAT_OPTIONS = {
    "sln16": ("-ar", "16000", "-ac", "1", "-f", "s16le", "-c:a", "pcm_s16le"),
    "g722": ("-ar", "16000", "-ac", "1", "-c:a", "g722", "-f", "g722"),
    "alaw": ("-ar", "8000", "-ac", "1", "-c:a", "pcm_alaw", "-f", "alaw"),
    "ulaw": ("-ar", "8000", "-ac", "1", "-c:a", "pcm_mulaw", "-f", "mulaw"),
}


class HoldMusicError(RuntimeError):
    """Die Wartemusik konnte nicht sicher installiert werden."""


def render_musiconhold(directory: Path = DEFAULT_MOH_DIRECTORY, *, enabled: bool = True) -> str:
    header = "; Von Kienzlefon verwaltete, additive Music-on-Hold-Klasse.\n"
    if not enabled:
        return header + "; Wartemusik ist nicht installiert.\n"
    return (
        header
        + f"\n[{MUSIC_CLASS}]\n"
        + "mode=files\n"
        + f"directory={directory}\n"
        + "sort=alpha\n"
    )


def install_media(
    source: Path,
    target: Path = DEFAULT_MOH_DIRECTORY,
    *,
    target_lufs: float = -23.0,
    peak_db: float = -2.0,
) -> dict[str, Path]:
    """Normalisiert die Quelle und installiert alle Asterisk-/Browserformate atomar."""
    source = source.resolve()
    if not source.is_file() or source.is_symlink():
        raise HoldMusicError(f"Wartemusik-Quelldatei fehlt oder ist unzulaessig: {source}")
    if shutil.which("ffmpeg") is None:
        raise HoldMusicError("FFmpeg fehlt; Wartemusik wurde nicht installiert")

    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kienzlefon-wartemusik-", dir=target) as name:
        staging = Path(name)
        normalized = staging / "wartemusik.wav"
        try:
            PromptGenerator.normalize_audio_file(
                source,
                normalized,
                "wartemusik",
                target_lufs=target_lufs,
                peak_db=peak_db,
            )
        except RuntimeError as exc:
            raise HoldMusicError(str(exc)) from exc

        staged = {"wav16": normalized}
        for suffix, options in FORMAT_OPTIONS.items():
            output = staging / f"wartemusik.{suffix}"
            _run_ffmpeg(normalized, output, options)
            if not output.is_file() or output.stat().st_size == 0:
                raise HoldMusicError(f"FFmpeg erzeugte keine verwendbare .{suffix}-Datei")
            staged[suffix] = output
        _validate_browser_wav(normalized)

        installed: dict[str, Path] = {}
        for suffix, source_path in staged.items():
            destination = target / f"wartemusik.{suffix}"
            temporary = destination.with_name(
                f".{destination.name}.new.{os.getpid()}.{secrets.token_hex(4)}"
            )
            try:
                shutil.copyfile(source_path, temporary)
                os.chmod(temporary, 0o644)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            installed[suffix] = destination
    return installed


def _run_ffmpeg(source: Path, output: Path, options: tuple[str, ...]) -> None:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                *options,
                str(output),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise HoldMusicError(f"FFmpeg konnte nicht gestartet werden: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HoldMusicError(f"Wartemusik-Konvertierung fehlgeschlagen: {detail}")


def _validate_browser_wav(path: Path) -> None:
    try:
        with wave.open(str(path), "rb") as handle:
            valid = (
                handle.getframerate() == 16000
                and handle.getnchannels() == 1
                and handle.getsampwidth() == 2
                and handle.getnframes() > 0
            )
    except (OSError, wave.Error) as exc:
        raise HoldMusicError(f"Browser-WAV ist unlesbar: {exc}") from exc
    if not valid:
        raise HoldMusicError("Browser-WAV ist nicht PCM 16 Bit, mono, 16 kHz")


def install_config(
    config: AppConfig,
    etc: Path = Path("/etc/asterisk"),
    directory: Path = DEFAULT_MOH_DIRECTORY,
) -> None:
    """Installiert nur die eigene MOH-Datei und den einmaligen Include."""
    from .asterisk import AsteriskConfigError, _atomic_install, _ensure_include

    target = etc / "musiconhold-kienzlefon.conf"
    _atomic_install(target, render_musiconhold(directory, enabled=config.hold_music.installed))
    main = etc / "musiconhold.conf"
    if not main.is_file():
        if config.hold_music.installed:
            raise AsteriskConfigError(f"Asterisk-Music-on-Hold-Konfiguration fehlt: {main}")
        return
    _ensure_include(main, '#include "/etc/asterisk/musiconhold-kienzlefon.conf"')


def main() -> None:
    parser = argparse.ArgumentParser(description="Optionale Kienzlefon-Wartemusik installieren")
    parser.add_argument("--config", default="/etc/kienzlefon/kienzlefon.toml")
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", default=str(DEFAULT_MOH_DIRECTORY))
    arguments = parser.parse_args()
    config = load_config(arguments.config)
    if not config.hold_music.installed:
        print("Wartemusik ist deaktiviert; keine Mediendateien installiert.")
        return
    installed = install_media(
        Path(arguments.source),
        Path(arguments.target),
        target_lufs=config.tts.target_loudness_lufs,
        peak_db=config.tts.max_true_peak_db,
    )
    print("Wartemusik installiert: " + ", ".join(str(path) for path in installed.values()))


if __name__ == "__main__":
    main()
