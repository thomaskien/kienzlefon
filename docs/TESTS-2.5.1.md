# Releasepruefung 2.5.1

Stand: 11.10.2026. Lokale Releasepruefung vor dem GitHub-Upload.

- **334 Tests bestanden** (27,67 Sekunden), gesamte Kienzlefon-Release-Suite.
  Die separat vorhandenen, noch nicht veroeffentlichten SMS-Arbeiten und ihre
  fuenf Testdateien gehoeren nicht zu diesem Release und wurden ausgeschlossen.
- Bash-Syntax beider Installer, PHP-Syntax des Webinterfaces und die geaenderten
  Python-Module mit Ruff (F/I) geprueft; `git diff --check` ohne Fehler.
- Python-Wheel `kienzlefon-2.5.1-py3-none-any.whl` erfolgreich gebaut;
  Version, MIT-Lizenzmetadaten und neue Laufzeitfunktionen kontrolliert.
- Installer-Tests fuehren die Wartemusik-Abfrage mit Bash aus: neue Einrichtung
  waehlt Melodie vor, gespeichertes Klingelzeichen und abgelehnte Installation
  bleiben auch bei wiederholtem Lauf erhalten. Migrationen sind idempotent.
- AMI-Export nach TOML inklusive JSON-Migration, stabiler Secrets, eigener
  Firewallregel, Dateirechten 0600, geschuetzter Sicherung und TOML-Vorrang
  geprueft. Der aktive alte JSON-Pfad wird nach erfolgreicher Sicherung entfernt.
- KI-Schalter: strikte Eingabepruefung, Schutz vor veralteten Schreibauftraegen,
  Erhalt der SIP-Konfiguration, keine neuen Zulassungen bei ausgeschalteter KI,
  weiterhin moegliche Rueckgaben laufender Anrufe und Fehler bei fehlgeschlagenem
  Reload getestet. Reines Umschalten startet keine TTS-Erzeugung und keinen Dienst neu.
- Browser-Test mit echtem PHP-Webinterface und Webadmin-Worker in lokaler
  Testumgebung: Aus- und Wiedereinschalten gespeichert; Status und Checkbox
  wurden nach Abschluss automatisch aktualisiert. Die Konfigurations- und
  Asterisk-Kommandos waren dabei durch erfolgreiche Testkommandos ersetzt;
  die Ansagenerzeugung war absichtlich auf ein fehlschlagendes Testkommando gesetzt.

Reproduzierbarer Suite-Aufruf:

```sh
python -m pytest -q \
  --ignore=tests/test_telepraxis_sms.py \
  --ignore=tests/test_telepraxis_sms_auto_reply.py \
  --ignore=tests/test_telepraxis_sms_cleanup.py \
  --ignore=tests/test_telepraxis_sms_queue.py \
  --ignore=tests/test_telepraxis_sms_web_queue.py
```

## Noch auf der Telefonanlage pruefen

Es wurde kein Live-Deployment und kein produktiver Anruf ausgefuehrt.

1. Update mit beiden Installern durchfuehren. Eine gespeicherte Wartemusik-Auswahl
   muss erhalten bleiben; Melodie und Klingelzeichen im Webinterface probeweise
   wechseln. Die interne Musik-Hoerprobe bleibt unter 8805 erreichbar.
2. In der Webinterface-Uebersicht den KI-Assistenten ausschalten und speichern.
   Neue Anrufe muessen dem klassischen Ablauf folgen; Taste 0 und interne
   KI-Direktwahl duerfen keine neue KI-Zulassung erhalten. Ein bereits laufendes
   KI-Gespraech einschliesslich Rueckgabe darf nicht unterbrochen werden.
3. Wieder einschalten, neue KI-Annahme pruefen und durch erneuten Installerlauf
   kontrollieren, dass die gespeicherte Schalterstellung bestehen bleibt.
4. Das separate Middleware-Modul mit dem TOML-Export verbinden. Secret und
   AMI-Zugang muessen gegenueber 2.5.0 unveraendert bleiben; den Dateileser der
   Middleware auf TOML umstellen. Anlagentests siehe [MIDDLEWARE.md](MIDDLEWARE.md).
