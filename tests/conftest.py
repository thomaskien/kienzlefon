# kienzlefon tests
# Version: 1.5
# Changelog:
# - 1.5: Isoliertes Uploadverzeichnis fuer wav16-Ansagenaufnahmen ergaenzt.
# - 1.0: Isolierte Testkonfiguration und RSA-Schluesselbereitstellung.

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kienzlefon.config import AppConfig, load_config


@pytest.fixture
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def app_config(tmp_path: Path, private_key: rsa.RSAPrivateKey) -> AppConfig:
    public_key = tmp_path / "telepraxis-public.pem"
    public_key.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    source = Path("config/kienzlefon.toml.example").read_text(encoding="utf-8")
    replacements = {
        "/var/spool/asterisk/kienzlefon": str(tmp_path / "spool"),
        "/run/kienzlefon": str(tmp_path / "run"),
        "/var/lib/asterisk/sounds/kienzlefon": str(tmp_path / "prompts"),
        "/var/lib/kienzlefon/ansagen-master": str(tmp_path / "masters"),
        "/var/lib/kienzlefon/models": str(tmp_path / "models"),
        "/srv/telepraxis/dahl/inbox": str(tmp_path / "inbox"),
        "/etc/kienzlefon/telepraxis-public.pem": str(public_key),
        "/var/lib/kienzlefon/piper-voices": str(tmp_path / "voices"),
        "/var/lib/kienzlefon/ansagen-upload": str(tmp_path / "uploads"),
        "CHANGE_ME_RED_PHONE_SECRET": "test-red-secret",
        "CHANGE_ME_MAIN_NUMBER": "4923311234",
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    config_path = tmp_path / "kienzlefon.toml"
    config_path.write_text(source, encoding="utf-8")
    return load_config(config_path)
