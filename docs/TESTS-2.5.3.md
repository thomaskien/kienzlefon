# Releasepruefung 2.5.3

Stand: 12.10.2026. Lokale Releasepruefung vor dem GitHub-Upload.

- **380 Tests bestanden** (30,15 Sekunden), gesamte Kienzlefon-Release-Suite.
  Die separat vorhandenen, noch nicht veroeffentlichten SMS-Arbeiten und ihre
  fuenf Testdateien gehoeren nicht zu diesem Release und wurden ausgeschlossen.
- **16 neue Regressionstests** fuer Click-to-Dial: echter `AgiChannel` mit
  simulierten Asterisk-Protokollantworten, vollstaendiger `main()`-Ablauf und
  konkrete Pruefung von `GET VARIABLE CHANNEL(endpoint)`. Variablenzugriff,
  Antwortparser und Freigabelogik werden dabei nicht durch Test-Doubles ersetzt.
- Freigegebene Nebenstelle 202 mit Endpunkt 202, nationale und +49-Ziele,
  Normalisierung, Haupt-/Direktprovider und Caller-ID geprueft. Die Freigabe
  wird erst nach den Rufparametern gesetzt.
- Fehlender, leerer oder abweichender Endpunkt, nicht freigegebene Nebenstelle,
  ungueltiges/gesperrtes Ziel sowie deaktivierte Middleware/Click-to-Dial bleiben
  abgelehnt. AGI-Hangup-Antworten 511, EOF und -1 fuehren zu keiner Freigabe.
- Der generierte Dialplan enthaelt vier Rufnummern-Einstiege statt `_.` und
  behandelt `h` separat nur mit `NoOp`. Ausgehroute und Fortschrittsereignis
  liegen hinter der Freigabepruefung. Aktivierter und deaktivierter Zustand getestet.
- **Gegencheck mit unveraenderter 2.5.2:** Dieselben neuen Tests melden
  7 erwartete Fehler und 9 bestandene Faelle. Die Fehler betreffen die falsche
  Endpunktabfrage und den pauschalen Dialplan-Einstieg; die Regressionstests
  erkennen somit die ausgelieferten Fehler.
- Sol-Worker: unabhaengiges Review und 58 gezielte Tests bestanden, keine
  offenen Befunde. Der Lead hat den Diff selbst geprueft und die Tests im
  vollstaendigen Release-Lauf erneut ausgefuehrt.
- Wheel `kienzlefon-2.5.3-py3-none-any.whl` gebaut, Versions-/MIT-Metadaten,
  CLI-Einstieg und beide Korrekturen im Paket kontrolliert. Zusaetzlich wurde
  dieses Wheel in ein temporaeres Verzeichnis installiert und dessen echter
  `kienzlefon-c2d-check`-CLI mit echter TOML-Konfiguration und simuliertem
  AGI-Eingabedialog ausgefuehrt: Endpunkt 202 erlaubt, 203 und leer abgewiesen.
- Bash-Syntax beider Installer, PHP-Syntax, Ruff (F/I) fuer geaenderte
  Click-to-Dial-Module und neue Tests sowie `git diff --check` bestanden.

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

Es wurde kein Live-Deployment und kein produktiver Anruf ausgefuehrt. Die
AGI-Tests verwenden simulierte Antworten; Dialplantests pruefen die erzeugte
Konfiguration. Ein laufendes Asterisk stand lokal nicht zur Verfuegung.

1. Aktuellen Hauptinstaller ausfuehren: Python-Paket und generierter Dialplan
   muessen gemeinsam aktualisiert werden. Vorhandene Konfiguration beibehalten.
2. Click-to-Dial fuer eine freigegebene Nebenstelle, zum Beispiel 202, ausloesen:
   Nebenstelle klingelt, abheben, Endpunkt 202 wird gelesen, `KF_C2D_ALLOWED=1`.
3. Fortschrittsereignis `dialing_target`, Wechsel zu `kienzlefon-outbound` und
   externes `Dial()` beobachten. Ziel klingelt und nimmt an; Sprache in beide
   Richtungen pruefen. Mit nationalem und +49-Ziel testen.
4. Auflegen darf keine weitere Click-to-Dial-AGI-Pruefung fuer `h` ausloesen.
   Leere/falsche Endpunkte und nicht freigegebene Nebenstellen bleiben abgewiesen.

Details siehe [MIDDLEWARE.md](MIDDLEWARE.md#korrektur-und-live-test-ab-253).
