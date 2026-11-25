"""Print local phone provisioning details at the end of the installer."""

import configparser
import os
import re
import sys
from pathlib import Path

from .config import load_config


def _pjsip_value(section, key):
    raw = section.get(key, "")
    # Kienzlefax quotes backslashes and semicolons. An unquoted semicolon
    # starts an Asterisk comment, even directly after the value.
    value = re.match(r"(?:\\.|[^;\\])*", raw).group().rstrip()
    return re.sub(r"\\([;\\])", r"\1", value)


def print_accounts(config_file: Path, pjsip_file: Path) -> None:
    config = load_config(config_file)
    pjsip = configparser.ConfigParser(strict=False, interpolation=None, delimiters=("=",))
    try:
        with pjsip_file.open(encoding="utf-8") as handle:
            pjsip.read_file(handle)
    except (OSError, UnicodeError, configparser.Error):
        pjsip.clear()

    def row(extension, role, username, password):
        print(f"{extension:<12} {role:<22} {username:<17} {password or '[Kennwort nicht verfügbar]'}")

    print(f"{'Nebenstelle':<12} {'Verwendung':<22} {'SIP-Benutzername':<17} SIP-Passwort")
    first = int(os.environ.get("KFX_PHONE_FIRST_EXTENSION") or config.asterisk.first_queue_extension)
    count = int(os.environ.get("KFX_PHONE_COUNT") or config.asterisk.queue_extension_count)
    for number in range(first, first + count):
        extension = str(number)
        auth = pjsip[f"{extension}-auth"] if pjsip.has_section(f"{extension}-auth") else {}
        password = _pjsip_value(auth, "password") or os.environ.get(f"KFX_PHONE_ENDPOINT_{extension}_PASSWORD")
        row(extension, "Praxisqueue", _pjsip_value(auth, "username") or extension, password)
    if config.ivr.red_enabled:
        row(config.ivr.red_extension, "Rotes Telefon", config.ivr.red_extension, config.asterisk.red_password)
    for entry in config.standalone_extensions:
        row(entry.extension, "Zusatztelefon", entry.extension, entry.password)
    for slot, (extension, password) in enumerate(zip(
        config.ai_integration.extensions, config.ai_integration.sip_passwords, strict=True,
    )):
        row(extension, f"KI / ai-slot-{slot:02d}", extension, password)


if __name__ == "__main__":
    print_accounts(Path(sys.argv[1]), Path(sys.argv[2]))
