# Kienzlefon 2.6.0 · Lokale Prüfung vom 19. November 2026

Die Prüfungen verwenden synthetische Vorgänge, temporäre Zielverzeichnisse,
Testschlüssel und lokale Testdienste. Der Ausgangsstand vor den Beiträgen ist
mit `v2.5.5` markiert. Die Beiträge bis `0e1f11c`, die vier lokalen
Entwicklungscommits bis `2ff0664` und der Kombi-Installer sind in `main` integriert.

| Funktion | Automatisierte Prüfung | Grenze der Prüfung |
| --- | --- | --- |
| Installation, Update und Neukonfiguration | `test_installer.py` führt den Konfigurationsdialog für alle drei Wege aus. Geprüft werden beide Direktnummern, Commander-IP, unabhängige Auswahl von Ablage und Audio, die Abholerfrage und der Erhalt bestehender SIP-Zugangsdaten. `test_kombi_installer.py` verwendet das entpackte Archiv und prüft Vorbedingungen sowie Webinstaller-Fehler. | Systempakete, Dienste und Zielrechte auf einem Linux-Praxisserver stehen für die Systemabnahme aus. |
| Direktnummern und ROT | `test_asterisk.py` prüft Direktregistrierungen, Kapazitätsprüfung und direkten Eintritt ohne IVR-Zeitprofil. Bei aktiviertem roten Telefon steht der Einzelruf vor dem Gruppenruf, bei deaktiviertem beginnt die Sonderqueue sofort. | Generierter Dialplan, ohne SIP-Anschluss. |
| Rufgruppen, Admin und externe Rechte | `test_telephony_control.py` und `test_webadmin.py` prüfen Normal und ROT, Einzelrechte, gleichzeitige Abschaltungen, letztes Mitglied, Neustart und Wiederholungen. Synthetische AMI-Antworten und ein lokaler HTTP-Server bedienen die Tests. | Die Verbindung von App und Middleware zur Praxisanlage ist eine gemeinsame Systemabnahme. |
| IVR, Ansagen und Anrufbaum | `test_release_ivr_statistics.py`, `test_ivr.py` und `test_webadmin.py` prüfen Umbelegung, Deaktivierung, doppelte Tasten, Ansagetexte sowie Admin-Ausgabe. | Gesprochene Eigenaufnahmen müssen zur gewählten Belegung passen. |
| Anrufstatistik | `test_release_ivr_statistics.py` prüft den Eingang vor der Kapazitätsprüfung, externe Identität und die Auswertung des KI-Brückenendes bei Rückkehr oder Auflegen. `test_telephony_control.py` prüft getrennt die Live-Zähler. | Maßgeblich für den KI-Tagesweg ist die von Asterisk nach der Brücke gesetzte Dauer. Zeitpunkt und Übermittlung des Ereignisses auf der Anlage bleiben offen. Die Tagesaggregation liegt in der Middleware. |
| Commander und CPU | `test_worker.py` prüft erfolgreiche Commander-Erkennung und lokalen Rückfall mit derselben WAV und demselben Feld. | Simulierter Commander und Transkribierer, ohne Server oder Modellmessung. |
| Mehrere Anliegen | `test_ivr.py`, `test_worker.py` und `test_ai_import.py` prüfen Wiederholungen desselben Anliegentyps, stabile IDs, abgebrochene Folgeanliegen und die Trennung verschiedener Patienten. | Der Import verarbeitet bereitgestellte KI-Ergebnisse. Die Originalaufnahme im separaten KI-Projekt folgt dort dessen eigenem Lebenszyklus. |
| Audio, Fehler-JSON und Spool | `test_delivery.py` prüft JSON-only, das lokale Begleitverzeichnis und die Entschlüsselung des Pakets. Eine falsche Quittung lässt die Quelle bestehen. Bei angeforderter Ersatz-JSON werden Inhalt, Audiofehler und bytegleiche Wiederholung geprüft. Erst eine passende Ablagebestätigung bereinigt Paket und WAV. | Der Test erzeugt die Quittungen auf Empfängerseite. Installation und SSH-Betrieb des Praxis-Abholers gehören zum App-Projekt. |
| Google TTS und SIP-Zielformate | `test_google_tts.py`, `test_sip_target_formats.py`, `test_migration.py` und `test_transfer_dialplan.py` prüfen simulierte Synthese, Konfigurationsübernahme und anbieterspezifische Wahlformate. | Die Provider-Auswahl für Fonial und voip2gsm gehört zu Kienzlefax. |
| Paket und Verträge | Paket aus dem lokalen Commit bauen und frisch entpacken. Pflichtliste, Dateiinhalte, Shell-/PHP-Syntax, Python-Wheel und dessen Kommando-Einstiegspunkte prüfen. Der Telefonievertragsvalidator kontrolliert die gültigen und ungültigen Beispieldaten. | Der Pakettest verwendet lokale Werkzeuge und Modellattrappen. |

Die Release-Suite wird im exportierten Quellstand mit `python -m pytest -q`
ausgeführt. Für die isolierten Sockettests muss der Testprozess lokale
Unix- und Loopback-Sockets öffnen können. Der Packer erwartet einen absoluten
Ausgabepfad, zum Beispiel `bash scripts/pack.sh --output /tmp/kienzlefon-2.6.0.tar.gz`.
