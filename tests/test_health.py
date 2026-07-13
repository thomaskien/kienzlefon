# kienzlefon tests
# Version: 1.6
# Changelog:
# - 1.6: Mehrmodell-Heartbeat und exakte Modellmengenpruefung getestet.

from __future__ import annotations

import json

from kienzlefon.health import Heartbeat, worker_is_healthy


def test_health_requires_all_configured_models(tmp_path) -> None:
    path = tmp_path / "whisper-health.json"
    models = ("large-v3-turbo", "large-v3")
    heartbeat = Heartbeat(path, models, 5)
    heartbeat.set_ready(True)

    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["version"] == "1.6"
    assert value["models"] == list(models)
    assert worker_is_healthy(path, models, 20) is True
    assert worker_is_healthy(path, ("large-v3-turbo",), 20) is False
