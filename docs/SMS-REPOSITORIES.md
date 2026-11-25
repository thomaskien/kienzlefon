# Maßgeblicher SMS-Stand und gezielte Übernahme

Die SMS-Funktionen werden im Repository der Praxis-App gepflegt (lokales Projekt `ionos`). Die unten dokumentierte Übernahme stammt vom 29.09.2026. [Kienzlefon-App auf GitHub](https://github.com/thomaskien/kienzlefon-app)

Die reguläre `telepraxis-app.php`, ihre SMS-Konfiguration, Bibliotheken,
Worker und SMS-Tests werden dort weiterentwickelt. `kienzlefon` enthält eine
Demointegration und ausdrücklich keine automatisch synchronisierte zweite
Produktivversion. Änderungen zuerst in `ionos` implementieren und testen;
benötigte Bibliotheksänderungen anschließend gezielt in die Demo übernehmen.
Die beiden App-Dateien dürfen nicht gegenseitig vollständig ersetzt werden.

## Übernommener Stand

Ausgangspunkt in `ionos`: Commit `4c8c665` einschließlich der bereits lokal
vorliegenden Änderungen vom 29.09.2026, insbesondere der sichtbaren Bezeichnung
„kienzlefon app“. Die reguläre App behält Version 3.4.2 und ihren vollständigen
Changelog. Der datierte SMS-Eintrag dokumentiert die Änderung ohne neue Release-Freigabe.

| Aus `kienzlefon` | Maßgebliche Datei in `ionos` |
| --- | --- |
| `demo-webseite/telepraxis-sms.php` | `telepraxis-sms.php` |
| `demo-webseite/telepraxis-sms-queue.php` | `telepraxis-sms-queue.php` |
| `demo-webseite/telepraxis-sms-worker.php` | `telepraxis-sms-worker.php` |
| SMS-bezogene Änderungen in `demo-webseite/telepraxis-app-demo.php` | gezielt in `telepraxis-app.php` |
| `tests/test_telepraxis_sms*.py` | gleiche Tests mit angepassten Dateipfaden in `tests/` |
| `config/sms-queue-*.example.json`, Dienstvorlage | gleiche Pfade in `config/` |
| `docs/SMS-QUEUE.md` | Anleitung für die reguläre App unter gleichem Pfad |

Der geprüfte Übernahmestand mit 59 Tests und SHA-256-Prüfsummen ist in
`SMS-TRANSFER-2026-09-29.json` festgehalten. Die dortigen Pfade und Prüfsummen
bezeichnen die Ausgangsdateien in `kienzlefon`, nicht die danach angepassten
Zieldateien. Zusätzliche Integrationstests prüfen die reguläre App und Konfiguration.

`sms-config.php` wurde im IONOS-Stand um Queue-Auswahl und Einstellungen erweitert.
Die bisher dort enthaltenen Transportfunktionen bleiben wegen der bestehenden
Installer-Schnittstellen zunächst erhalten und werden gegen die Bibliothek
geprüft. TOTP-Änderungen müssen beide Versandoberflächen erreichen.

## Bewahrte Funktionen und Grenzen

Papierkorb, Wiederherstellung, Adminschutz bei endgültigem Löschen, Kommentare,
Platzbindung, Statuswechsel, Dringend-Markierung, Kopfzeile, Polling, Druck- und
Kopieransicht stammen aus der regulären App. Das sofortige endgültige Löschen
der Demo wurde nicht übertragen. Bestehende Credentials werden durch die
Codeübernahme weder ersetzt noch aktiviert; die Queue muss bewusst als Provider
ausgewählt werden.

Implementiert sind TOTP-Fix, persistente Ausgangsqueue, unabhängiger Worker,
gesonderte Löschaufträge und die konfigurierbare Liste mit zwei Antwort-SMS.
**SMS-Empfang, Zusammensetzen eingehender Teile und vollständiger Journalabgleich
der FRITZ!Box sind weiterhin offen.** Die Konfiguration allein löst keine
automatische Eingangsantwort aus.

Der Zielserver-Installer erhält die zusätzliche Queue-Bibliothek und die
PDO-SQLite-Abhängigkeit. Der SMS-Worker wird weiterhin separat nach
`SMS-QUEUE.md` eingerichtet; er wird durch diese Codeänderung weder installiert
noch gestartet. Webapp und Worker benötigen dieselbe lokale SQLite-Datei auf
dem Zielserver, getrennt vom Webroot und vom IONOS-Quellserver für verschlüsselte
Eingangsdaten.

## Getrennte Freigaben

Diese Übergabe umfasst lokale Dateien und Tests. Commit, Push und Installation
sind eigene, noch abzustimmende Schritte. Vor einem Commit vorhandene fremde
Änderungen getrennt reviewen und nur die vereinbarten Änderungen aufnehmen.
Vor Installation die tatsächlichen Pfade, Dienstbenutzer, gemeinsame Gruppe und
vorhandenen Provider-Einstellungen prüfen. Keine Zugangsdaten in Git aufnehmen.
