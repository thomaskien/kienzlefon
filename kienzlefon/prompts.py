# kienzlefon
# Version: 2.0
# Changelog:
# - 2.0: Live-Fortschritt fuer Planung, aktuelle Ansage und Qwen-Wartungsphasen ergaenzt.
# - 2.0: Differenzielle Qwen3-TTS-Erzeugung mit globaler Sprecherwahl ergaenzt.
# - 1.5: 16-kHz-Master und gemeinsame zweistufige Lautheitsnormalisierung eingefuehrt.
# - 1.4: PIN-Bausteine durch klare deutsche Administrationsansagen ersetzt.
# - 1.3: Stabile Ansagenummern und gemeinsame Wochenend-Telefonzeit ergaenzt.
# - 1.2: Gemeinsame Werktagszeiten und geschlossene Wochenenden zusammengefasst.
# - 1.1: Piper-Parameter, Pausenmarker und globale Praxisnamen-Ersetzung ergaenzt.
# - 1.0: Piper-basierte Ansagenerzeugung mit atomarem Formatwechsel eingefuehrt.

from __future__ import annotations

import fcntl
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
import time
import wave
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig, TimeWindow, WEEKDAYS, WeeklySchedule
from .health import worker_is_healthy
from .spool import write_json_atomic

LOGGER = logging.getLogger(__name__)
PAUSE_MARKER = re.compile(r"\{pause:(\d+)\}")
PROMPT_PROGRESS_PREFIX = "KIENZLEFON_FORTSCHRITT "

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
    "webadmin_record", "webadmin_record_actions", "webadmin_record_saved",
    "webadmin_record_discarded",
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
    for scheduled in config.scheduled_overrides:
        values[scheduled.prompt_name] = scheduled.announcement.replace(
            "{praxisname}", config.practice.name
        )
    values["opening_hours"] = opening_hours_text(
        config.opening_hours,
        values.pop("opening_hours_prefix"),
        values.pop("opening_hours_closed"),
    )
    additional_phone_hours = values["phone_hours"].strip()
    rendered_phone_hours = phone_hours_text(
        config.phone_hours,
        values.pop("phone_hours_prefix"),
        values.pop("phone_hours_closed"),
    )
    if additional_phone_hours:
        rendered_phone_hours = f"{rendered_phone_hours} {additional_phone_hours}"
    values["phone_hours"] = rendered_phone_hours
    return values


class PromptGenerator:
    def __init__(
        self,
        config: AppConfig,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.config = config
        self.progress = progress
        self.manifest_path = config.paths.prompt_masters / "manifest.json"
        self._scheduled_tts_overrides: dict[str, Path] = {}
        self._cached_qwen_identity: str | None = None
        self._maintenance_depth = 0

    def generate(
        self,
        force: bool = False,
        *,
        only: set[str] | None = None,
        new_qwen_variant: bool = False,
    ) -> tuple[int, int]:
        self.config.paths.prompt_masters.mkdir(parents=True, exist_ok=True)
        lock_path = self.config.paths.prompt_masters / ".generation.lock"
        with lock_path.open("a+b") as generation_lock:
            os.chmod(lock_path, 0o640)
            try:
                fcntl.flock(
                    generation_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                )
            except BlockingIOError as exc:
                raise RuntimeError("Eine andere Ansagenerzeugung laeuft bereits") from exc
            return self._generate_locked(force, only, new_qwen_variant)

    def _generate_locked(
        self,
        force: bool,
        only: set[str] | None,
        new_qwen_variant: bool,
    ) -> tuple[int, int]:
        self._scheduled_tts_overrides.clear()
        self.config.paths.prompts.mkdir(parents=True, exist_ok=True)
        manifest = self._load_manifest()
        updated = dict(manifest.get("prompts", {}))
        rendered = rendered_prompts(self.config)
        selected = set(rendered) if only is None else set(only)
        unknown = sorted(selected - set(rendered))
        if unknown:
            raise RuntimeError("Unbekannte Ansage(n): " + ", ".join(unknown))
        tts_identity = self._tts_identity()
        scheduled_tts_to_refresh = {
            entry.prompt_name
            for entry in self.config.scheduled_overrides
            if entry.prompt_name in selected
            and (
                force
                or manifest.get("tts_identity") != tts_identity
                or updated.get(entry.prompt_name, {}).get("text")
                != rendered.get(entry.prompt_name)
                or entry.tts_path is None
                or not entry.tts_path.is_file()
            )
        }
        removed = sorted(set(updated) - set(rendered))
        for name in removed:
            updated.pop(name, None)
        changed: list[str] = []
        planned: list[tuple[str, str, str, Path | None, int, bool]] = []
        skipped = 0
        for name, prompt_text in sorted(rendered.items()):
            if name not in selected:
                continue
            human_source = self._manual_source(name)
            automated_qwen = self._is_automated_qwen_source(name, human_source)
            previous = updated.get(name, {})
            qwen_variant = self._manifest_qwen_variant(previous)
            if new_qwen_variant and automated_qwen:
                qwen_variant += 1
            digest = self._digest(name, prompt_text, qwen_variant=qwen_variant)
            if (
                not force
                and previous.get("sha256") == digest
                and self._outputs_exist(name)
            ):
                skipped += 1
                continue
            planned.append(
                (
                    name,
                    prompt_text,
                    digest,
                    human_source,
                    qwen_variant,
                    automated_qwen,
                )
            )

        total = len(scheduled_tts_to_refresh) + len(planned)
        self._progress(0, total, "plan")
        qwen_work = self.config.tts.engine == "qwen" and (
            bool(scheduled_tts_to_refresh)
            or any(
                automated_qwen
                for _name, _text, _digest, _source, _variant, automated_qwen in planned
            )
        )
        if qwen_work:
            self._progress(0, total, "qwen_prepare")
        with self._qwen_maintenance(qwen_work):
            if qwen_work:
                self._progress(0, total, "qwen_ready")
            with tempfile.TemporaryDirectory(
                prefix="kienzlefon-prompts-", dir=self.config.paths.prompt_masters
            ) as staging_name:
                staging = Path(staging_name)
                current = 0
                if scheduled_tts_to_refresh:
                    current = self._stage_scheduled_tts(
                        rendered,
                        staging,
                        scheduled_tts_to_refresh,
                        qwen_variants={
                            name: variant
                            for name, _text, _digest, _source, variant, _auto in planned
                        },
                        current=current,
                        total=total,
                    )
                for (
                    name,
                    prompt_text,
                    digest,
                    human_source,
                    qwen_variant,
                    automated_qwen,
                ) in planned:
                    current += 1
                    if human_source is not None:
                        self._progress(current, total, "manual", name=name)
                        LOGGER.warning(
                            "Gespeicherte WAV-Datei hat Vorrang vor neuer TTS-Erzeugung: %s",
                            human_source,
                        )
                    else:
                        self._progress(current, total, "generate", name=name)
                    qwen_seed = (
                        self._effective_qwen_seed(qwen_variant)
                        if automated_qwen
                        else None
                    )
                    if qwen_seed is None:
                        self._generate_one(name, prompt_text, staging)
                    else:
                        self._generate_one(
                            name,
                            prompt_text,
                            staging,
                            qwen_seed=qwen_seed,
                        )
                    # Bei gespeicherten TTS-Sonderansagen zeigt _manual_source
                    # jetzt auf die gerade erzeugte Staging-Datei. Deshalb wird
                    # der Digest nach der Erzeugung noch einmal aus der finalen
                    # Quelle gebildet.
                    final_digest = self._digest(
                        name,
                        prompt_text,
                        qwen_variant=qwen_variant,
                    )
                    updated[name] = {
                        "sha256": final_digest,
                        "text": prompt_text,
                        "qwen_variant": qwen_variant,
                    }
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
                for entry in self.config.scheduled_overrides:
                    staged_tts = self._scheduled_tts_overrides.get(entry.prompt_name)
                    if staged_tts is not None and entry.tts_path is not None:
                        self._replace(staged_tts, entry.tts_path)
                        LOGGER.info("TTS-Fassung der Sonderansage aktualisiert: %s", entry.name)
                for name in removed:
                    (self.config.paths.prompt_masters / f"{name}.wav").unlink(missing_ok=True)
                    for suffix in ("sln16", "g722", "alaw", "ulaw"):
                        (self.config.paths.prompts / f"{name}.{suffix}").unlink(missing_ok=True)
                    LOGGER.info("Nicht mehr verwendete Ansage entfernt: %s", name)
            if qwen_work:
                self._progress(total, total, "qwen_restore")
        self._progress(total, total, "complete")
        write_json_atomic(
            self.manifest_path,
            {
                "version": "2.0",
                "changelog": [
                    "2.0: Qwen3-TTS und globale Sprecherwahl differenziell beruecksichtigt.",
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
                "qwen_voice": self.config.tts.qwen_voice,
                "qwen_language": self.config.tts.qwen_language,
                "qwen_seed": self.config.tts.qwen_seed,
                "tts_identity": tts_identity,
                "length_scale": self.config.tts.length_scale,
                "sentence_silence": self.config.tts.sentence_silence,
                "target_loudness_lufs": self.config.tts.target_loudness_lufs,
                "max_true_peak_db": self.config.tts.max_true_peak_db,
                "prompts": updated,
            },
        )
        return len(changed), skipped

    def _generate_one(
        self,
        name: str,
        text: str,
        staging: Path,
        *,
        qwen_seed: int | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix=f"kienzlefon-prompt-{name}-", dir=staging
        ) as temporary_name:
            temporary = Path(temporary_name)
            source_wav = temporary / "source.wav"
            master_wav = temporary / f"{name}.wav"
            parts = split_pause_markers(text)
            human_source = self._manual_source(name)
            if human_source is not None:
                shutil.copyfile(human_source, source_wav)
            else:
                self._synthesize(
                    parts,
                    source_wav,
                    temporary,
                    name,
                    qwen_seed=qwen_seed,
                )
            self.normalize_audio(source_wav, master_wav, name)
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
        self.normalize_audio_file(
            source,
            output,
            name,
            target_lufs=self.config.tts.target_loudness_lufs,
            peak_db=self.config.tts.max_true_peak_db,
        )

    def synthesize_text_file(
        self,
        text: str,
        output: Path,
        name: str,
        *,
        qwen_seed: int | None = None,
    ) -> None:
        """Create one normalized browser-compatible WAV without changing active prompts."""
        with self._qwen_maintenance(self.config.tts.engine == "qwen"):
            self.config.paths.prompt_masters.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=f"kienzlefon-preview-{name}-",
                dir=self.config.paths.prompt_masters,
            ) as temporary_name:
                temporary = Path(temporary_name)
                source_wav = temporary / "source.wav"
                self._synthesize(
                    split_pause_markers(text),
                    source_wav,
                    temporary,
                    name,
                    qwen_seed=qwen_seed,
                )
                self.normalize_audio(source_wav, output, name)

    @contextmanager
    def _qwen_maintenance(self, needed: bool):
        if not needed or self.config.tts.engine != "qwen" or self._maintenance_depth:
            yield
            return
        if shutil.which("systemctl") is None:
            yield
            return
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", "kienzlefon-worker.service"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
        if not active:
            yield
            return
        if os.geteuid() != 0:
            raise RuntimeError("Qwen3-TTS mit aktivem Whisper-Worker erfordert root")

        runtime = self.config.paths.runtime
        runtime.mkdir(parents=True, exist_ok=True)
        admission_lock_path = runtime / "asr-admission.lock"
        # Dieser eigene Marker bleibt ueber die gesamte Sammelerzeugung liegen.
        # Der unveraenderte Qwen-v1.5-Generator verwaltet parallel dazu seinen
        # kurzlebigen Marker ``asr-maintenance`` fuer jeden Einzelaufruf.
        marker = runtime / "tts-maintenance"
        stopped = False
        self._maintenance_depth += 1
        try:
            with admission_lock_path.open("a+b") as admission_lock:
                fcntl.flock(admission_lock.fileno(), fcntl.LOCK_EX)
                self._create_maintenance_marker(marker)
                try:
                    busy = {
                        state: len(tuple((self.config.paths.spool / state).glob("*/")))
                        for state in ("recording", "processing")
                    }
                    if busy["recording"] or busy["processing"]:
                        raise RuntimeError(
                            "Qwen3-TTS wurde nicht gestartet: "
                            f"{busy['recording']} Aufnahme(n), "
                            f"{busy['processing']} ASR-Auftrag/Auftraege aktiv"
                        )
                    result = self._run_systemctl("stop", timeout=90)
                    if result.returncode != 0:
                        raise RuntimeError(
                            "Whisper-Worker konnte nicht beendet werden: "
                            + self._systemctl_error(result)
                        )
                    stopped = True
                except Exception:
                    marker.unlink(missing_ok=True)
                    raise
            yield
        finally:
            try:
                if stopped:
                    with admission_lock_path.open("a+b") as admission_lock:
                        fcntl.flock(admission_lock.fileno(), fcntl.LOCK_EX)
                        result = self._run_systemctl("start", timeout=90)
                        if result.returncode != 0:
                            raise RuntimeError(
                                "Whisper-Worker konnte nach Qwen3-TTS nicht gestartet werden: "
                                + self._systemctl_error(result)
                            )
                        deadline = time.monotonic() + 300
                        while time.monotonic() < deadline:
                            if worker_is_healthy(
                                runtime / "whisper-health.json",
                                self.config.whisper.models,
                                self.config.whisper.stale_heartbeat_seconds,
                            ) and self._worker_heartbeat_matches_service(
                                runtime / "whisper-health.json"
                            ):
                                marker.unlink(missing_ok=True)
                                break
                            time.sleep(1)
                        else:
                            raise RuntimeError(
                                "Whisper-Worker wurde nach Qwen3-TTS nicht wieder bereit; "
                                f"Wartungsmarker bleibt bestehen: {marker}"
                            )
            finally:
                self._maintenance_depth -= 1

    @staticmethod
    def _create_maintenance_marker(marker: Path) -> None:
        try:
            with marker.open("x", encoding="utf-8") as handle:
                handle.write(
                    f"kienzlefon-prompt-generation pid={os.getpid()} "
                    f"started={datetime.now().astimezone().isoformat(timespec='seconds')}\n"
                )
            os.chmod(marker, 0o644)
        except FileExistsError as exc:
            raise RuntimeError(
                f"Ein anderer ASR-Wartungsvorgang laeuft bereits: {marker}"
            ) from exc

    @staticmethod
    def _run_systemctl(action: str, *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                ["systemctl", action, "kienzlefon-worker.service"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"systemctl {action} fehlgeschlagen: {exc}") from exc

    @staticmethod
    def _systemctl_error(result: subprocess.CompletedProcess[bytes]) -> str:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        return detail[-1000:] or f"Rueckgabecode {result.returncode}"

    @staticmethod
    def _worker_heartbeat_matches_service(heartbeat: Path) -> bool:
        """Akzeptiert nur den Heartbeat des aktuell von systemd gefuehrten Prozesses."""
        try:
            result = subprocess.run(
                [
                    "systemctl",
                    "show",
                    "kienzlefon-worker.service",
                    "--property=MainPID",
                    "--value",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                return False
            main_pid = int(result.stdout.decode("ascii", errors="strict").strip())
            with heartbeat.open("r", encoding="utf-8") as handle:
                heartbeat_pid = int(json.load(handle).get("pid", 0))
            return main_pid > 0 and heartbeat_pid == main_pid
        except (
            OSError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
        ):
            return False

    def _stage_scheduled_tts(
        self,
        rendered: dict[str, str],
        staging: Path,
        names: set[str],
        *,
        qwen_variants: dict[str, int],
        current: int,
        total: int,
    ) -> int:
        for entry in self.config.scheduled_overrides:
            if entry.prompt_name not in names:
                continue
            text = rendered.get(entry.prompt_name)
            if text is None:
                continue
            current += 1
            self._progress(
                current,
                total,
                "scheduled_tts",
                name=entry.prompt_name,
                label=entry.name,
            )
            target = staging / "scheduled-tts" / f"{entry.identifier}.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            qwen_seed = (
                self._effective_qwen_seed(qwen_variants.get(entry.prompt_name, 0))
                if self.config.tts.engine == "qwen" and entry.source == "tts"
                else None
            )
            self.synthesize_text_file(
                text,
                target,
                f"sonderansage-{entry.identifier[:8]}",
                qwen_seed=qwen_seed,
            )
            self._scheduled_tts_overrides[entry.prompt_name] = target
        return current

    def _progress(
        self,
        current: int,
        total: int,
        phase: str,
        *,
        name: str = "",
        label: str = "",
    ) -> None:
        if self.progress is None:
            return
        self.progress(
            {
                "current": current,
                "total": total,
                "phase": phase,
                "name": name,
                "label": label,
            }
        )

    @staticmethod
    def normalize_audio_file(
        source: Path,
        output: Path,
        name: str,
        *,
        target_lufs: float,
        peak_db: float,
    ) -> None:
        target = target_lufs
        peak = peak_db
        base_filter = f"loudnorm=I={target}:LRA=7:TP={peak}"
        analysis = PromptGenerator._run_capture(
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
        measured = PromptGenerator._parse_loudnorm(analysis.stderr, name)
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
            PromptGenerator._run_capture(
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
            PromptGenerator._validate_wav16(temporary, name)
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

    def _digest(self, name: str, text: str, *, qwen_variant: int = 0) -> str:
        human_source = self._manual_source(name)
        human_digest = ""
        if human_source is not None:
            human_digest = hashlib.sha256(human_source.read_bytes()).hexdigest()
        if self.config.tts.engine == "piper":
            # Das Piper-Schema bleibt absichtlich kompatibel zum 1.9-Manifest.
            # Eine unveraenderte Drueberinstallation erzeugt daher nichts neu.
            parts = (
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
        else:
            parts = (
                text,
                self.config.tts.engine,
                self.config.tts.qwen_voice,
                self.config.tts.qwen_language,
                str(self.config.tts.qwen_seed),
                self._qwen_generator_identity(),
                str(self.config.tts.target_loudness_lufs),
                str(self.config.tts.max_true_peak_db),
                human_digest,
            )
            # Variante 0 bleibt absichtlich mit vorhandenen 2.0-Manifesten
            # kompatibel. Erst eine ausdrueckliche neue Variante erweitert den
            # Digest und loest dadurch keine ungewollte Komplettgenerierung aus.
            if qwen_variant:
                parts = (*parts, f"qwen-variant:{qwen_variant}")
        value = "\0".join(parts)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _manifest_qwen_variant(entry: Any) -> int:
        if not isinstance(entry, dict):
            return 0
        value = entry.get("qwen_variant", 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 0
        return value

    def _effective_qwen_seed(self, variant: int) -> int:
        # Der Generator akzeptiert nichtnegative Ganzzahlen. Der Variantenzaehler
        # bleibt im Manifest erhalten, waehrend die wirksame Seed-Zahl kompakt
        # und fuer jedes erneute Erzeugen verschieden bleibt.
        return (self.config.tts.qwen_seed + variant) % (2**31)

    def _tts_identity(self) -> str:
        if self.config.tts.engine == "piper":
            parts = (
                "piper",
                self.config.tts.voice,
                str(self.config.tts.volume),
                str(self.config.tts.length_scale),
                str(self.config.tts.sentence_silence),
            )
        else:
            parts = (
                "qwen",
                self.config.tts.qwen_voice,
                self.config.tts.qwen_language,
                str(self.config.tts.qwen_seed),
                self._qwen_generator_identity(),
            )
        return hashlib.sha256(
            "\0".join(
                (
                    "kienzlefon-prompts-2.0",
                    *parts,
                    str(self.config.tts.target_loudness_lufs),
                    str(self.config.tts.max_true_peak_db),
                )
            ).encode("utf-8")
        ).hexdigest()

    def _qwen_generator_identity(self) -> str:
        if self._cached_qwen_identity is not None:
            return self._cached_qwen_identity
        generator = self.config.tts.qwen_generator
        if not generator.is_file():
            self._cached_qwen_identity = f"missing:{generator}"
            return self._cached_qwen_identity
        try:
            digest = hashlib.sha256(generator.read_bytes())
            install_info = Path("/var/lib/kienzlefon/qwen3-tts/offline-install-info.txt")
            if install_info.is_file():
                digest.update(b"\0")
                # Der v1.5-Installer schreibt bei jeder identischen Installation
                # lediglich diesen Zeitstempel neu. Nur technische Aenderungen
                # (z. B. Git-Commit oder Backend) sollen Audio neu erzeugen.
                digest.update(
                    b"\n".join(
                        line
                        for line in install_info.read_bytes().splitlines()
                        if not line.startswith(b"installed_at=")
                    )
                )
            self._cached_qwen_identity = digest.hexdigest()
            return self._cached_qwen_identity
        except OSError as exc:
            raise RuntimeError(f"Qwen3-TTS-Generator ist nicht lesbar: {generator}: {exc}") from exc

    def _is_automated_qwen_source(
        self, name: str, source: Path | None
    ) -> bool:
        if self.config.tts.engine != "qwen":
            return False
        scheduled = next(
            (
                entry
                for entry in self.config.scheduled_overrides
                if entry.prompt_name == name
            ),
            None,
        )
        if scheduled is not None:
            return scheduled.source == "tts"
        return source is None

    def _manual_source(self, name: str) -> Path | None:
        scheduled = next(
            (
                entry
                for entry in self.config.scheduled_overrides
                if entry.prompt_name == name
            ),
            None,
        )
        if scheduled is not None:
            source = scheduled.manual_path if scheduled.source == "manuell" else (
                self._scheduled_tts_overrides.get(name) or scheduled.tts_path
            )
            if source is None or not source.is_file() or source.is_symlink():
                raise RuntimeError(f"Gespeicherte Audioquelle fehlt: {name}")
            return source
        configured = self.config.prompt_sources.get(name)
        if configured == "tts":
            return None
        for suffix in ("wav16", "wav"):
            candidate = self.config.tts.upload_directory / f"{name}.{suffix}"
            if candidate.is_file():
                return candidate
        if configured == "manuell":
            raise RuntimeError(f"Manuelle Ansage fehlt: {name}")
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
        *,
        qwen_seed: int | None = None,
    ) -> None:
        if len(parts) == 1 and isinstance(parts[0], str):
            self._run(
                self._tts_command(parts[0], output, qwen_seed=qwen_seed),
                f"{self.config.tts.engine}-Erzeugung fehlgeschlagen fuer {name}",
            )
            return

        audio_parts: dict[int, Path] = {}
        for index, part in enumerate(parts):
            if not isinstance(part, str):
                continue
            path = temporary / f"segment-{index:03d}.wav"
            segment_seed = None if qwen_seed is None else qwen_seed + index
            self._run(
                self._tts_command(part, path, qwen_seed=segment_seed),
                f"{self.config.tts.engine}-Erzeugung fehlgeschlagen fuer {name}, "
                f"Segment {index + 1}",
            )
            audio_parts[index] = path
        self._join_with_pauses(parts, audio_parts, output, name)

    def _tts_command(
        self, text: str, output: Path, *, qwen_seed: int | None = None
    ) -> list[str]:
        if self.config.tts.engine == "qwen":
            return self._qwen_command(text, output, seed=qwen_seed)
        return self._piper_command(text, output)

    def _qwen_command(
        self, text: str, output: Path, *, seed: int | None = None
    ) -> list[str]:
        generator = self.config.tts.qwen_generator
        if not generator.is_file() or not os.access(generator, os.X_OK):
            raise RuntimeError(
                "Qwen3-TTS ist nicht installiert oder nicht ausfuehrbar: "
                f"{generator}"
            )
        return [
            str(generator),
            "--text",
            text,
            "--speaker",
            self.config.tts.qwen_voice,
            "--language",
            self.config.tts.qwen_language,
            "--seed",
            str(self.config.tts.qwen_seed if seed is None else seed),
            "--output",
            str(output),
        ]

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
