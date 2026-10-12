"""Read-only Asterisk capability and loaded-dialplan checks for the installer."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from .config import AppConfig, load_config
from .transfer_agi import staff_extensions
from .transfer_features import resolve_transfer_features

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CLI_ERROR = re.compile(
    r"^\s*(?:"
    r"No such command\b.*|"
    r"Unable to connect to remote asterisk\b.*|"
    r"Your application\(s\) is \(are\) not registered\.?|"
    r"No function by that name registered\.?|"
    r"No such (?:context|function|application)\b.*|"
    r"There is no existence of .+ (?:context|extension)(?: in all contexts)?|"
    r"Command '.+' failed\."
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _cli_diagnostic(output: str, error: re.Match[str] | None, returncode: int) -> str:
    detail = error.group(0).strip() if error else next(
        (line.strip() for line in output.splitlines() if line.strip()), "keine CLI-Ausgabe"
    )
    detail = re.sub(
        r"(?i)\b(password|secret|token|api[-_ ]?key)\s*([:=])\s*\S+",
        r"\1\2<ausgeblendet>",
        detail,
    )
    if len(detail) > 200:
        detail = detail[:199] + "…"
    status = f"Exitcode {returncode}; " if returncode else ""
    return status + detail


def _cli(command: str) -> str:
    result = subprocess.run(["asterisk", "-rx", command], capture_output=True,
                            text=True, timeout=20, check=False)
    output = _ANSI_ESCAPE.sub("", "\n".join(part for part in (result.stdout, result.stderr) if part))
    error = _CLI_ERROR.search(output)
    if result.returncode or error:
        diagnostic = _cli_diagnostic(output, error, result.returncode)
        raise ValueError(f"Asterisk-Vorpruefung fehlgeschlagen: {command} ({diagnostic})")
    return output


def preflight(config: AppConfig, etc: Path = Path("/etc/asterisk")) -> None:
    if not config.middleware.enabled:
        return
    resolve_transfer_features(etc)
    for action in ("Getvar", "BlindTransfer", "Atxfer", "CancelAtxfer", "PlayDTMF"):
        output = _cli("manager show command " + action)
        if not re.search(r"Action:\s*" + action + r"\b", output, re.IGNORECASE):
            raise ValueError(f"AMI-Aktion fehlt: {action}")
        if action == "PlayDTMF" and "Receive" not in output:
            raise ValueError("AMI PlayDTMF unterstuetzt Receive nicht")
    for function in ("FEATURE", "FEATUREMAP", "CHANNEL", "DIALPLAN_EXISTS", "REGEX", "FILTER"):
        if function + "(" not in _cli("core show function " + function):
            raise ValueError(f"Asterisk-Funktion fehlt: {function}")
    for application in ("Dial", "Queue"):
        output = _cli("core show application " + application)
        if application + "(" not in output or "b(" not in output:
            raise ValueError(f"Asterisk-{application} ohne erforderlichen Pre-Dial-Hook")
    _cli("features show")


def verify(config: AppConfig) -> None:
    if not config.middleware.enabled:
        return
    contexts = {
        "kienzlefon-transfer": ("kienzlefon-transfer-check", "_XX"),
        "kienzlefon-transfer-prepare": ("CHANNEL(endpoint)", "KF_TRANSFER_READY=1"),
        "kienzlefon-transfer-caller": ("KF_TRANSFER_CALLER_OPTION=T",),
        "kienzlefon-transfer-progress": ("KienzlefonTransferProgress", "SourceUniqueid", "dialing_target"),
        "kienzlefon-outbound": ("kienzlefon-transfer-progress", "KZF_DIAL_ALLOWED=0"),
        "kfx-phone-queue": ("kienzlefon-transfer-caller", "b(kienzlefon-transfer-"),
    }
    for context, markers in contexts.items():
        output = _cli("dialplan show " + context)
        if not all(marker in output for marker in markers):
            raise ValueError(f"Geladener Vermittlungs-Dialplan unvollstaendig: {context}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Asterisk-Vermittlung pruefen")
    parser.add_argument("mode", choices=("preflight", "verify"))
    parser.add_argument("--config", default="/etc/kienzlefon/kienzlefon.toml")
    parser.add_argument("--etc", default="/etc/asterisk")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        if args.mode == "preflight":
            preflight(config, Path(args.etc))
        else:
            verify(config)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Vermittlungspruefung: {exc}\n")
    if config.middleware.enabled:
        phones = ", ".join(staff_extensions(config)) or "keine freigegeben"
        print(f"Vermittlung: {args.mode} erfolgreich; Mitarbeiter: {phones}")
