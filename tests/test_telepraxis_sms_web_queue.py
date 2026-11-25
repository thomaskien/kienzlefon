"""Real PHP request/queue integration in temp directories; no router or network."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PHP = shutil.which("php")
SMS_TEXT = "Ihre SMS wurde an die Praxis weitergeleitet. Testbetrieb!"
LONG_SMS_TEXT = (
    "Ihre SMS wurde an die Praxis weitergeleitet. Testbetrieb! Fehlen Ihre persönlichen "
    "Daten, senden Sie bitte eine komplette SMS mit diesen Angaben. Vielen Dank!"
)


@unittest.skipUnless(PHP, "PHP CLI required")
class SmsWebQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "inbox").mkdir()
        (self.root / "sessions").mkdir()
        (self.root / "queue").mkdir(mode=0o770)
        for name in ("telepraxis-app-demo.php", "telepraxis-sms.php", "telepraxis-sms-queue.php"):
            shutil.copyfile(ROOT / "demo-webseite" / name, self.site / name)
        self.settings = {
            "default_provider": "queue",
            "sms": {"max_text_length": 160},
            "queue": {
                "database_path": str(self.root / "queue" / "outbox.sqlite"),
                "delivery_provider": "fritz",
            },
        }
        self.save_settings()
        self.card = self.site / "inbox" / "example.json"
        self.original = {
            "received_at": "2026-09-29T12:00:00+02:00", "typ": "sonstiges",
            "payload": {"typ": "sonstiges", "telefon": "+491700000000", "anliegen": "Test"},
            "app": {"status": "in_bearbeitung", "status_updated_arbeitsplatz": "testplatz",
                    "comments": [{"text": "Vorhandener Kommentar", "workplace": "testplatz",
                                  "created_at": "2026-09-29T12:01:00+02:00"}]},
        }
        self.card.write_text(json.dumps(self.original), encoding="utf-8")
        self.driver = self.root / "request.php"
        self.driver.write_text("""<?php
$input = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
chdir($argv[1]);
$_SERVER['DOCUMENT_ROOT'] = $argv[1];
$_SERVER['REQUEST_METHOD'] = isset($input['action']) ? 'POST' : 'GET';
$_POST = $input;
$_GET = isset($input['action']) ? [] : ['ajax' => 'list'];
$_REQUEST = array_merge($_GET, $_POST);
session_save_path($argv[2]);
session_id('telepraxis-queue-integration-test');
register_shutdown_function(static function () {
    fwrite(STDERR, 'HTTP:' . (http_response_code() ?: 200));
});
require './telepraxis-app-demo.php';
""", encoding="utf-8")
        self.csrf = self.request({})[1]["csrf"]

    def save_settings(self):
        (self.site / "sms-credentials.json").write_text(json.dumps(self.settings), encoding="utf-8")

    def request(self, fields):
        result = subprocess.run(
            [PHP, "-d", "display_errors=stderr", str(self.driver), str(self.site), str(self.root / "sessions")],
            input=json.dumps(fields), text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stderr, r"^HTTP:\d{3}$")
        return int(result.stderr.removeprefix("HTTP:")), json.loads(result.stdout)

    def send(self, request_id="a" * 32, text=SMS_TEXT, **overrides):
        return self.request({
            "action": "send_sms", "csrf": self.csrf, "file": "example.json",
            "workplace": "testplatz", "sms_text": text, "sms_request_id": request_id,
            **overrides,
        })

    def card_view(self):
        code, response = self.request({})
        self.assertEqual(code, 200)
        return response["entries"][0]

    def test_queue_provider_is_fast_durable_and_does_not_need_router_credentials(self):
        self.assertEqual(len(SMS_TEXT), 57)
        code, response = self.send()
        self.assertEqual(code, 202)
        self.assertTrue(response["queued"])
        self.assertEqual(response["provider"], "queue")
        self.assertNotIn("gesendet", response["message"])
        # App-file is not rewritten; existing comments and processing state survive.
        self.assertEqual(json.loads(self.card.read_text()), self.original)
        comments = self.card_view()["comments"]
        sms = next(comment for comment in comments if comment.get("sms_job_id"))
        self.assertEqual(sms["sms_job_id"], response["job_id"])
        self.assertEqual(sms["sms_status"], "pending")
        self.assertIn(SMS_TEXT, sms["text"])
        self.assertEqual(sms["workplace"], "testplatz")

    def test_retry_of_same_request_has_one_job_and_conflicting_body_is_rejected(self):
        _, first = self.send()
        code, second = self.send()
        self.assertEqual(code, 202)
        self.assertEqual(first["job_id"], second["job_id"])
        code, conflict = self.send(text="Anderer Inhalt")
        self.assertGreaterEqual(code, 400)
        self.assertFalse(conflict["ok"])
        self.assertEqual(len([c for c in self.card_view()["comments"] if c.get("sms_job_id")]), 1)

    def test_new_intent_allows_same_text_as_a_new_message(self):
        _, first = self.send()
        _, second = self.send(request_id="b" * 32)
        self.assertNotEqual(first["job_id"], second["job_id"])

    def test_status_from_worker_is_shown_after_a_new_request(self):
        self.send()
        # Inject a confirmed sender; this cannot contact any real router.
        settings = {**self.settings, "fritzbox": {
            "host": "http://example.invalid", "username": "dummy", "password": "dummy",
            "totp_secret": "JBSWY3DPEHPK3PXP",
        }}
        script = """
define('TELEPRAXIS_APP', true);
require $argv[1];
require $argv[2];
$settings = json_decode(stream_get_contents(STDIN), true);
echo json_encode(tp_sms_queue_process_one($settings, static function () {
    return ['ok' => true, 'provider' => 'fritz', 'details' => ['message_uid' => 'confirmed-test']];
}));
"""
        result = subprocess.run(
            [PHP, "-r", script, str(self.site / "telepraxis-sms.php"), str(self.site / "telepraxis-sms-queue.php")],
            input=json.dumps(settings), text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "accepted")
        comment = next(c for c in self.card_view()["comments"] if c.get("sms_job_id"))
        self.assertEqual(comment["sms_status"], "accepted")
        self.assertIn("an FRITZ!Box übergeben", comment["text"])

    def test_csrf_and_workplace_restrictions_still_apply(self):
        for overrides in ({"csrf": "invalid"}, {"workplace": "andererplatz"}):
            with self.subTest(overrides=overrides):
                code, response = self.send(**overrides)
                self.assertGreaterEqual(code, 400)
                self.assertFalse(response["ok"])
        self.assertFalse(Path(self.settings["queue"]["database_path"]).exists())

    def test_length_validation_rejects_oversize_before_enqueue(self):
        code, response = self.send(text="x" * 161)
        self.assertGreaterEqual(code, 400)
        self.assertFalse(response["ok"])
        self.assertFalse(Path(self.settings["queue"]["database_path"]).exists())

    def test_fritz_rejects_long_reply_before_direct_send_or_enqueue(self):
        self.assertEqual(len(LONG_SMS_TEXT), 158)
        for provider in ("fritz", "queue"):
            with self.subTest(provider=provider):
                self.settings["default_provider"] = provider
                self.save_settings()
                code, response = self.send(text=LONG_SMS_TEXT)
                self.assertGreaterEqual(code, 400)
                self.assertIn("70 Zeichen", response["error"])
                self.assertFalse(Path(self.settings["queue"]["database_path"]).exists())
                self.assertEqual(json.loads(self.card.read_text()), self.original)

    def test_fritz_unicode_boundary_and_seven_long_messages(self):
        code, _ = self.send(text="ö" * 70)
        self.assertEqual(code, 202)
        code, response = self.send(request_id="b" * 32, text="ö" * 71)
        self.assertGreaterEqual(code, 400)
        self.assertIn("70 Zeichen", response["error"])
        self.settings["queue"]["delivery_provider"] = "seven"
        self.save_settings()
        code, _ = self.send(request_id="c" * 32, text=LONG_SMS_TEXT)
        self.assertEqual(code, 202)

    def test_missing_queue_directory_fails_without_success_or_app_mutation(self):
        self.settings["queue"]["database_path"] = str(self.root / "missing" / "queue.sqlite")
        self.save_settings()
        code, response = self.send()
        self.assertGreaterEqual(code, 400)
        self.assertFalse(response["ok"])
        self.assertEqual(json.loads(self.card.read_text()), self.original)

    def test_none_remains_disabled_and_does_not_enqueue(self):
        self.settings["default_provider"] = "none"
        self.save_settings()
        code, response = self.send()
        self.assertEqual(code, 400)
        self.assertIn("deaktiviert", response["error"])
        self.assertFalse(Path(self.settings["queue"]["database_path"]).exists())

    def test_seven_status_does_not_claim_fritzbox_delivery(self):
        self.settings["queue"]["delivery_provider"] = "seven"
        self.save_settings()
        code, result = self.send()
        self.assertEqual(code, 202)
        with sqlite3.connect(self.settings["queue"]["database_path"]) as db:
            db.execute("UPDATE sms_queue SET status='accepted' WHERE id=?", (result["job_id"],))
        comment = next(c for c in self.card_view()["comments"] if c.get("sms_job_id"))
        self.assertIn("an seven.io übergeben", comment["text"])
        self.assertNotIn("FRITZ!Box", comment["text"])


if __name__ == "__main__":
    unittest.main()
