# kienzlefon
# Version: 1.6.2
# Changelog:
# - 1.6.2: AGI-Antwort 511 auf beendetem Kanal als regulaeren Hangup behandelt.
# - 1.5: Optionalen Signalton fuer administrative Ansagenaufnahmen ergaenzt.
# - 1.3: Mehrstellige, mit Raute abschliessbare DTMF-Eingabe ergaenzt.
# - 1.1: Aufnahmen starten mit der Asterisk-Option q ohne Signalton.
# - 1.0: Lokales AGI-Protokoll mit DTMF-, Aufnahme- und Routingbefehlen.

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .models import RecordingResult

RESPONSE = re.compile(r"^200 result=(-?\d+)(?: \((.*)\))?")


class AgiError(RuntimeError):
    pass


class AgiHangup(AgiError):
    pass


@dataclass(frozen=True)
class AgiResponse:
    result: int
    data: str
    raw: str


class AgiChannel:
    def __init__(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout):
        self.stdin = stdin
        self.stdout = stdout
        self.environment = self._read_environment()

    def _read_environment(self) -> dict[str, str]:
        result: dict[str, str] = {}
        while True:
            line = self.stdin.readline()
            if line == "":
                raise AgiHangup("AGI-Eingang vor Umgebungsdaten beendet")
            line = line.rstrip("\r\n")
            if not line:
                return result
            key, separator, value = line.partition(":")
            if separator:
                result[key.strip()] = value.strip()

    def command(self, command: str) -> AgiResponse:
        self.stdout.write(command + "\n")
        self.stdout.flush()
        line = self.stdin.readline()
        if line == "":
            raise AgiHangup(f"Kanal waehrend AGI-Befehl beendet: {command}")
        raw = line.rstrip("\r\n")
        if raw == "511" or raw.startswith("511 "):
            raise AgiHangup(f"AGI-Kanal ist bereits beendet: {command}: {raw}")
        match = RESPONSE.match(raw)
        if not match:
            raise AgiError(f"Unerwartete AGI-Antwort: {raw}")
        response = AgiResponse(int(match[1]), match[2] or "", raw)
        if response.result < 0:
            raise AgiHangup(f"AGI-Befehl meldet Hangup/Fehler: {command}: {raw}")
        return response

    @staticmethod
    def _quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def stream_file(self, filename: Path, escape_digits: str = "") -> str | None:
        response = self.command(
            f"STREAM FILE {self._quote(str(filename))} {self._quote(escape_digits)}"
        )
        return chr(response.result) if response.result > 0 else None

    def get_option(self, filename: Path, escape_digits: str, timeout_ms: int) -> str | None:
        response = self.command(
            f"GET OPTION {self._quote(str(filename))} {self._quote(escape_digits)} {timeout_ms}"
        )
        return chr(response.result) if response.result > 0 else None

    def get_variable(self, name: str) -> str:
        response = self.command(f"GET VARIABLE {name}")
        return response.data if response.result == 1 else ""

    def set_variable(self, name: str, value: str) -> None:
        self.command(f"SET VARIABLE {name} {self._quote(value)}")

    def exec(self, application: str, arguments: str = "") -> AgiResponse:
        suffix = f" {self._quote(arguments)}" if arguments else ""
        return self.command(f"EXEC {application}{suffix}")

    def goto(self, destination: str) -> None:
        self.exec("Goto", destination)

    def read_digits(
        self,
        variable: str,
        prompt: Path,
        maximum_digits: int,
        attempts: int = 1,
        timeout_seconds: int = 10,
    ) -> str:
        arguments = (
            f"{variable},{prompt},{maximum_digits},,,{attempts},{timeout_seconds}"
        )
        self.exec("Read", arguments)
        return self.get_variable(variable)

    def record(
        self,
        path: Path,
        *,
        silence_seconds: int,
        max_seconds: int,
        beep: bool = False,
    ) -> RecordingResult:
        options = "ky" if beep else "kqy"
        arguments = f"{path},{silence_seconds},{max_seconds},{options}"
        self.exec("Record", arguments)
        status = self.get_variable("RECORD_STATUS") or "UNKNOWN"
        present = path.is_file() and path.stat().st_size > 44
        return RecordingResult(path=path, status=status, present=present)
