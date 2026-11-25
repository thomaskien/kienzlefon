"""Apply the Webadmin's device names to managed PJSIP endpoints."""

import re
import time
from contextlib import contextmanager
from pathlib import Path

from .middleware import phone_names, private_write
from .transfer_setup import _cli

BEGIN = "; kienzlefon endpoint names begin"
END = "; kienzlefon endpoint names end"


def _quoted(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_names(text: str, names: dict[str, str]) -> str:
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == END]
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise ValueError("Namensblock in pjsip.conf ist unvollständig oder mehrfach vorhanden")
        del lines[starts[0]:ends[0] + 1]
    base = "".join(lines)
    if not names:
        return base
    block = [BEGIN]
    for extension, name in sorted(phone_names(names).items()):
        if len(name.encode("utf-8")) > 79:
            raise ValueError(f"Gerätename für {extension} überschreitet die Asterisk-Grenze von 79 UTF-8-Bytes")
        value = _quoted(name).replace(";", r"\;")
        block.extend((f"[{extension}](+type=endpoint)", f"callerid={value} <{extension}>"))
    separator = "\n" if base and not base.endswith("\n") else ""
    return base + separator + "\n".join([*block, END, ""])


def _mismatches(names: dict[str, str]) -> dict[str, str]:
    pending = {}
    for ext, name in names.items():
        output = _cli(f"pjsip show endpoint {ext}")
        match = re.search(r"^[ \t]*callerid[ \t]*:[ \t]*(.*?)[ \t]*$", output, re.M)
        # Older Asterisk versions print embedded quotes without escaping.
        if not match or match[1] not in {f'{_quoted(name)} <{ext}>', f'"{name}" <{ext}>'}:
            pending[ext] = name
    return pending


@contextmanager
def apply_names(etc: Path, names: dict[str, str], *, force_reload: bool = False):
    path = (etc / "pjsip.conf").resolve(strict=True)
    original = path.read_bytes()
    desired = render_names(original.decode("utf-8"), names)
    changed = original != desired.encode("utf-8")
    mode = path.stat().st_mode & 0o777
    if changed:
        private_write(path, desired, mode)
    try:
        if changed or force_reload or _mismatches(names):
            _cli("pjsip reload")
            deadline = time.monotonic() + 5
            pending = _mismatches(names)
            while pending and time.monotonic() < deadline:
                time.sleep(0.2)
                pending = _mismatches(pending)
            if pending:
                raise ValueError("Asterisk hat den Gerätenamen nicht bestätigt für " + ", ".join(pending))
        yield
    except Exception:
        if changed:
            private_write(path, original.decode("utf-8"), mode)
            _cli("pjsip reload")
        raise
