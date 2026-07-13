# kienzlefon
# Version: 1.5
# Changelog:
# - 1.5: 16-kHz-Master und gemeinsame zweistufige Lautheitsnormalisierung eingefuehrt.
# - 1.4: PIN-Bausteine durch klare deutsche Administrationsansagen ersetzt.
# - 1.3: Stabile Ansagenummern und gemeinsame Wochenend-Telefonzeit ergaenzt.
# - 1.2: Gemeinsame Werktagszeiten und geschlossene Wochenenden zusammengefasst.
# - 1.1: Piper-Parameter, Pausenmarker und globale Praxisnamen-Ersetzung ergaenzt.
# - 1.0: Piper-basierte Ansagenerzeugung mit atomarem Formatwechsel eingefuehrt.

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppConfig, TimeWindow, WEEKDAYS, WeeklySchedule
from .spool import write_json_atomic

LOGGER = logging.getLogger(__name__)
PAUSE_MARKER = re.compile(r"\{pause:(\d+)\}")

# Nummern bleiben releaseuebergreifend stabil; neue Bausteine werden nur angehaengt.
PROMPT_CATALOG = (
    "appointment", "birth_date", "callback_number", "callback_reason", "completed",
    "emergency", "first_medication", "first_name", "greeting_closed", "greeting_open",
    "invalid", "last_name", "medication_choice", "menu_closed", "menu_intro", "menu_open",
    "next_medication", "no_selection_closed", "no_selection_open", "opening_hours",
    "opening_hours_choice", "other", "override", "personal_data_fallback",
    "pharmacy_access", "pharmacy_agent", "phone_hours", "prescription_information",
    "recording_hint", "referral_reason", "specialist_access", "specialist_agent", "specialty",
    "submenu_five", "urgent_help", "whisper_failure", "blocked_destination", "admin_main",
    "admin_prompt_select", "admin_current_prompt", "admin_prompt_actions", "admin_record",
    "admin_record_ready", "admin_no_recording", "admin_activated", "admin_generated",
    "admin_special_menu", "admin_special_keep", "admin_special_block",
    "admin_special_disabled", "admin_invalid", "admin_special_status_disabled",
    "admin_special_status_keep", "admin_special_status_block",
)


def _spoken_time(value: Any) -> str:
    if value.minute == 0:
        return f"{value.hour} Uhr"
    return f"{value.hour} Uhr {value.minute:02d}"


def weekly_schedule_text(schedule: WeeklySchedule, prefix: str, closed_template: str) -> str:
    sentences = [prefix.rstrip()]
    for weekday, windows in zip(WEEKDAYS, schedule.days, strict=True):
        sentences.append(_day_schedule_text(weekday, windows, closed_template))
    return " ".join(sentences)


def _ranges_text(windows: tuple[TimeWindow, ...]) -> str:
    ranges = [
        f"von {_spoken_time(window.start)} bis {_spoken_time(window.end)}" for window in windows
    ]
    if len(ranges) == 1:
        return ranges[0]
    return ", ".join(ranges[:-1]) + " und " + ranges[-1]


def _day_schedule_text(weekday: str, windows: tuple[TimeWindow, ...], closed_template: str) -> str:
    day = weekday.capitalize()
    if not windows:
        return closed_template.format(tag=day)
    return f"{day} {_ranges_text(windows)}."


def opening_hours_text(schedule: WeeklySchedule, prefix: str, closed_template: str) -> str:
    sentences = [prefix.rstrip()]
    weekdays = schedule.days[:5]
    common_morning = (
        weekdays[0][0]
        if weekdays[0] and all(windows and windows[0] == weekdays[0][0] for windows in weekdays)
        else None
    )
    if common_morning is None:
        for weekday, windows in zip(WEEKDAYS[:5], weekdays, strict=True):
            sentences.append(_day_schedule_text(weekday, windows, closed_template))
    else:
        sentences.append(f"Jeden Werktag vormittags {_ranges_text((common_morning,))}.")
        for weekday, windows in zip(WEEKDAYS[:5], weekdays, strict=True):
            afternoons = windows[1:]
            if afternoons:
                sentences.append(f"{weekday.capitalize()} nachmittags {_ranges_text(afternoons)}.")

    saturday, sunday = schedule.days[5:]
    if not saturday and not sunday:
        sentences.append("An Wochenenden ist die Praxis geschlossen.")
    else:
        sentences.append(_day_schedule_text("samstag", saturday, closed_template))
        sentences.append(_day_schedule_text("sonntag", sunday, closed_template))
    return " ".join(sentences)


def phone_hours_text(schedule: WeeklySchedule, prefix: str, closed_template: str) -> str:
    weekdays = schedule.days[:5]
    if not weekdays[0] or not all(windows == weekdays[0] for windows in weekdays[1:]):
        return weekly_schedule_text(schedule, prefix, closed_template)

    sentences = [f"Unsere Telefonzeiten sind werktäglich {_ranges_text(weekdays[0])}."]
    saturday, sunday = schedule.days[5:]
    if not saturday and not sunday:
        sentences.append("Am Wochenende sind wir telefonisch nicht erreichbar.")
    else:
        sentences.append(_day_schedule_text("samstag", saturday, closed_template))
        sentences.append(_day_schedule_text("sonntag", sunday, closed_template))
    return " ".join(sentences)


def rendered_prompts(config: AppConfig) -> dict[str, str]:
    values = {
        key: value.replace("{praxisname}", config.practice.name)
        for key, value in config.prompts.values.items()
    }
    override = config.override.announcement or values["greeting_closed"]
    values["override"] = override.replace("{praxisname}", config.practice.name)
    values["opening_hours"] = opening_hours_text(
        config.opening_hours,
        values.pop("opening_hours_prefix"),
        values.pop("opening_hours_closed"),
    )
    values["phone_hours"] = phone_hours_text(
        config.phone_hours,
        values.pop("phone_hours_prefix"),
        values.pop("phone_hours_closed"),
    )
    return values


class PromptGenerator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.manifest_path = config.paths.prompt_masters / "manifest.json"

    def generate(self, force: bool = False) -> tuple[int, int]:
        self.config.paths.prompt_masters.mkdir(parents=True, exist_ok=True)
        self.config.paths.prompts.mkdir(parents=True, exist_ok=True)
        manifest = self._load_manifest()
        updated = dict(manifest.get("prompts", {}))
        rendered = rendered_prompts(self.config)
        removed = sorted(set(updated) - set(rendered))
        for name in removed:
            updated.pop(name, None)
        changed: list[str] = []
        skipped = 0
        with tempfile.TemporaryDirectory(
            prefix="kienzlefon-prompts-", dir=self.config.paths.prompt_masters
        ) as staging_name:
            staging = Path(staging_name)
            for name, text in sorted(rendered.items()):
                human_source = self._manual_source(name)
                if human_source is not None:
                    LOGGER.warning(
                        "Manuelle WAV-Datei hat Vorrang vor Text und Praxisname: %s",
                        human_source,
                    )
                digest = self._digest(name, text)
                if (
                    not force
                    and updated.get(name, {}).get("sha256") == digest
                    and self._outputs_exist(name)
                ):
                    skipped += 1
                    continue
                self._generate_one(name, text, staging)
                updated[name] = {"sha256": digest, "text": text}
                changed.append(name)
            for name in changed:
                self._replace(
                    staging / "masters" / f"{name}.wav",
                    self.config.paths.prompt_masters / f"{name}.wav",
                )
                for suffix in ("sln16", "g722", "alaw", "ulaw"):
                    self._replace(
                        staging / "prompts" / f"{name}.{suffix}",
                        self.config.paths.prompts / f"{name}.{suffix}",
                    )
                LOGGER.info("Ansage erzeugt: %s", name)
            for name in removed:
                (self.config.paths.prompt_masters / f"{name}.wav").unlink(missing_ok=True)
                for suffix in ("sln16", "g722", "alaw", "ulaw"):
                    (self.config.paths.prompts / f"{name}.{suffix}").unlink(missing_ok=True)
                LOGGER.info("Nicht mehr verwendete Ansage entfernt: %s", name)
        write_json_atomic(
            self.manifest_path,
            {
                "version": "1.5",
                "changelog": [
                    "1.5: 16-kHz-Master und gemeinsame Lautheitsnormalisierung eingefuehrt.",
                    "1.4: PIN-freie deutsche Administrationsansagen eingefuehrt.",
                    "1.3: Ansagenkatalog und Telefonzeit-Wochenende erweitert.",
                    "1.2: Zeitansagen fuer Werktage und Wochenenden zusammengefasst.",
                    "1.1: Piper-Parameter und Pausenmarker im Ansagenmanifest beruecksichtigt.",
                    "1.0: Erstfassung der generierten Ansagen.",
                ],
                "generated_at": datetime.now(self.config.practice.timezone).isoformat(
                    timespec="seconds"
                ),
                "engine": self.config.tts.engine,
                "voice": self.config.tts.voice,
                "length_scale": self.config.tts.length_scale,
                "sentence_silence": self.config.tts.sentence_silence,
                "target_loudness_lufs": self.config.tts.target_loudness_lufs,
                "max_true_peak_db": self.config.tts.max_true_peak_db,
                "prompts": updated,
            },
        )
        return len(changed), skipped

    def _generate_one(self, name: str, text: str, staging: Path) -> None:
        with tempfile.TemporaryDirectory(
            prefix=f"kienzlefon-prompt-{name}-", dir=staging
        ) as temporary_name:
            temporary = Path(temporary_name)
            piper_wav = temporary / "piper.wav"
            master_wav = temporary / f"{name}.wav"
            parts = split_pause_markers(text)
            human_source = self._manual_source(name)
            if human_source is not None:
                shutil.copyfile(human_source, piper_wav)
            else:
                self._synthesize(parts, piper_wav, temporary, name)
            self.normalize_audio(piper_wav, master_wav, name)
            conversions = {
                f"{name}.sln16": ["-ar", "16000", "-ac", "1", "-f", "s16le", "-c:a", "pcm_s16le"],
                f"{name}.g722": ["-ar", "16000", "-ac", "1", "-c:a", "g722", "-f", "g722"],
                f"{name}.alaw": ["-ar", "8000", "-ac", "1", "-c:a", "pcm_alaw", "-f", "alaw"],
                f"{name}.ulaw": ["-ar", "8000", "-ac", "1", "-c:a", "pcm_mulaw", "-f", "mulaw"],
            }
            for filename, options in conversions.items():
                output = temporary / filename
                self._run(
                    [
                        "ffmpeg",
                        "-nostdin",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(master_wav),
                        *options,
                        str(output),
                    ],
                    f"Asterisk-Audioformat fehlgeschlagen fuer {name}",
                )
            staged_master = staging / "masters" / f"{name}.wav"
            staged_master.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(master_wav, staged_master)
            for filename in conversions:
                staged_prompt = staging / "prompts" / filename
                staged_prompt.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(temporary / filename, staged_prompt)

    @staticmethod
    def _run(command: list[str], message: str) -> None:
        PromptGenerator._run_capture(command, message)

    @staticmethod
    def _run_capture(command: list[str], message: str) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"{message}: Programm fehlt: {command[0]}") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"{message}: {detail}") from exc

    def normalize_audio(self, source: Path, output: Path, name: str) -> None:
        target = self.config.tts.target_loudness_lufs
        peak = self.config.tts.max_true_peak_db
        base_filter = f"loudnorm=I={target}:LRA=7:TP={peak}"
        analysis = self._run_capture(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "info",
                "-i",
                str(source),
                "-af",
                f"{base_filter}:print_format=json",
                "-f",
                "null",
                "-",
            ],
            f"Lautheitsmessung fehlgeschlagen fuer {name}",
        )
        measured = self._parse_loudnorm(analysis.stderr, name)
        normalized_filter = (
            f"{base_filter}:measured_I={measured['input_i']}:"
            f"measured_LRA={measured['input_lra']}:measured_TP={measured['input_tp']}:"
            f"measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:"
            "linear=true:print_format=summary"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(
            f".{output.stem}.normalized.{os.getpid()}.{secrets.token_hex(4)}{output.suffix}"
        )
        try:
            self._run_capture(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-af",
                    normalized_filter,
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    "-f",
                    "wav",
                    str(temporary),
                ],
                f"Lautheitsnormalisierung fehlgeschlagen fuer {name}",
            )
            self._validate_wav16(temporary, name)
            os.chmod(temporary, 0o640)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _parse_loudnorm(stderr: bytes, name: str) -> dict[str, str]:
        text = stderr.decode("utf-8", errors="replace")
        matches = re.findall(r'\{\s*"input_i".*?\}', text, re.S)
        if not matches:
            raise RuntimeError(f"Lautheitsmessung ohne Messwerte fuer {name}")
        value = json.loads(matches[-1])
        keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        result = {key: str(value[key]) for key in keys}
        if any(not math.isfinite(float(item)) for item in result.values()):
            raise RuntimeError(f"Lautheitsmessung unbrauchbar fuer {name}")
        return result

    @staticmethod
    def _validate_wav16(path: Path, name: str) -> None:
        try:
            with wave.open(str(path), "rb") as wav_file:
                valid = (
                    wav_file.getframerate() == 16000
                    and wav_file.getnchannels() == 1
                    and wav_file.getsampwidth() == 2
                    and wav_file.getnframes() > 0
                )
        except (OSError, wave.Error) as exc:
            raise RuntimeError(f"16-kHz-WAV unlesbar fuer {name}: {exc}") from exc
        if not valid:
            raise RuntimeError(f"16-kHz-WAV hat ungueltige Audiodaten fuer {name}")

    @staticmethod
    def _replace(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f".{target.name}.new.{os.getpid()}")
        try:
            shutil.copyfile(source, staged)
            os.chmod(staged, 0o644)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)

    def _outputs_exist(self, name: str) -> bool:
        master = self.config.paths.prompt_masters / f"{name}.wav"
        outputs = [
            self.config.paths.prompts / f"{name}.{suffix}"
            for suffix in ("sln16", "g722", "alaw", "ulaw")
        ]
        return master.is_file() and all(path.is_file() for path in outputs)

    def _digest(self, name: str, text: str) -> str:
        human_source = self._manual_source(name)
        human_digest = ""
        if human_source is not None:
            human_digest = hashlib.sha256(human_source.read_bytes()).hexdigest()
        value = "\0".join(
            (
                text,
                self.config.tts.engine,
                self.config.tts.voice,
                str(self.config.tts.volume),
                str(self.config.tts.length_scale),
                str(self.config.tts.sentence_silence),
                str(self.config.tts.target_loudness_lufs),
                str(self.config.tts.max_true_peak_db),
                human_digest,
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _manual_source(self, name: str) -> Path | None:
        for suffix in ("wav16", "wav"):
            candidate = self.config.tts.upload_directory / f"{name}.{suffix}"
            if candidate.is_file():
                return candidate
        return None

    def _load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            return {}
        try:
            with self.manifest_path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ansagenmanifest ist nicht lesbar: {exc}") from exc

    def _synthesize(
        self,
        parts: list[str | int],
        output: Path,
        temporary: Path,
        name: str,
    ) -> None:
        if len(parts) == 1 and isinstance(parts[0], str):
            self._run(
                self._piper_command(parts[0], output),
                f"Piper fehlgeschlagen fuer {name}",
            )
            return

        audio_parts: dict[int, Path] = {}
        for index, part in enumerate(parts):
            if not isinstance(part, str):
                continue
            path = temporary / f"segment-{index:03d}.wav"
            self._run(
                self._piper_command(part, path),
                f"Piper fehlgeschlagen fuer {name}, Segment {index + 1}",
            )
            audio_parts[index] = path
        self._join_with_pauses(parts, audio_parts, output, name)

    def _piper_command(self, text: str, output: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            "piper",
            "-m",
            self.config.tts.voice,
            "--data-dir",
            str(self.config.tts.voice_directory),
            "--volume",
            str(self.config.tts.volume),
            "--length-scale",
            str(self.config.tts.length_scale),
            "--sentence-silence",
            str(self.config.tts.sentence_silence),
            "-f",
            str(output),
            "--",
            text,
        ]

    @staticmethod
    def _join_with_pauses(
        parts: list[str | int],
        audio_parts: dict[int, Path],
        output: Path,
        name: str,
    ) -> None:
        first_path = next(iter(audio_parts.values()), None)
        if first_path is None:
            raise RuntimeError(f"Ansage {name} enthaelt keinen sprechbaren Text")
        with wave.open(str(first_path), "rb") as first:
            channels = first.getnchannels()
            sample_width = first.getsampwidth()
            sample_rate = first.getframerate()
            compression = first.getcomptype()
        if compression != "NONE":
            raise RuntimeError(f"Piper-WAV fuer {name} ist nicht unkomprimiert")

        with wave.open(str(output), "wb") as target:
            target.setnchannels(channels)
            target.setsampwidth(sample_width)
            target.setframerate(sample_rate)
            for index, part in enumerate(parts):
                if isinstance(part, int):
                    frames = round(sample_rate * part / 1000)
                    target.writeframes(bytes(frames * channels * sample_width))
                    continue
                with wave.open(str(audio_parts[index]), "rb") as source:
                    current = (
                        source.getnchannels(),
                        source.getsampwidth(),
                        source.getframerate(),
                        source.getcomptype(),
                    )
                    expected = (channels, sample_width, sample_rate, "NONE")
                    if current != expected:
                        raise RuntimeError(f"Piper-Segmente fuer {name} haben verschiedene Formate")
                    target.writeframes(source.readframes(source.getnframes()))


def split_pause_markers(text: str) -> list[str | int]:
    parts: list[str | int] = []
    position = 0
    for match in PAUSE_MARKER.finditer(text):
        spoken = text[position : match.start()].strip()
        if spoken:
            parts.append(spoken)
        milliseconds = int(match.group(1))
        if milliseconds < 1:
            raise ValueError("Pausenmarker muss mindestens 1 Millisekunde enthalten")
        parts.append(milliseconds)
        position = match.end()
    spoken = text[position:].strip()
    if spoken:
        parts.append(spoken)
    remainder = PAUSE_MARKER.sub("", text)
    if "{pause:" in remainder:
        raise ValueError(f"Ungueltiger Pausenmarker in Ansagetext: {text!r}")
    if not any(isinstance(part, str) for part in parts):
        raise ValueError("Ansagetext enthaelt keinen sprechbaren Text")
    return parts
