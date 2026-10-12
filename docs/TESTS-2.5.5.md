# Releasepruefung 2.5.5

Stand: 12.10.2026, vor dem GitHub-Upload. Getrennte Release-Arbeitskopie ohne
die unabhaengigen, unveroeffentlichten SMS-Arbeiten.

- Gesamte Python-Suite: **551 Tests bestanden**. Enthalten sind vollstaendige
  AGI-Protokolldialoge fuer Queue-Eintritt und Rufangebot, Zyklusgrenzen,
  Kopfwechsel, Prioritaeten, fehlende Metadaten und Schutz angenommener Anrufe.
- Installer: Fehlererkennung mit realistischem Asterisk-Dial-Hilfetext,
  echte CLI-Fehler und Diagnose, Vorpruefung vor Audioerzeugung, gepruefter
  Queue-Reload, verwaltete Rufregeln/Mitglieder und idempotente Installation.
  Gleichnamige fremde Regeln, doppelte relative/absolute Includes, Glob-Includes
  und Include-Zyklen werden vor der Publikation abgewiesen; die geladenen Regeln
  muessen genau einem vollstaendigen erwarteten Regelblock entsprechen.
- Audio: Migration bekannter alter Standardtexte, Erhalt eigener Texte und
  Aufnahmen, Veroeffentlichung der Queue-Dateien in allen vier Telefonieformaten,
  aktive Dateipfade und Erzeugungsstand aus dem Manifest.
- **46 bestehende PHP-Middleware-Tests bestanden**, darunter Local-Kanalpaare,
  tatsaechlich verbundene Mitarbeiter-/Patientenkanaele und Vermittlung durch
  Local-Zwischenkanaele. Die Middleware wurde dabei nicht veraendert.
- Ruff `F,I`, Bash-Syntax beider Installer und `git diff --check` bestanden.
- Unabhaengiger Sol-Review mit 125 gezielten Tests; die Befunde zu Regelgrenzen,
  Queue-Voraussetzungen und gleichnamigen Regelkollisionen wurden korrigiert
  und durch das abschliessende Lead-Review und Regressionstests abgesichert.
- Wheel `kienzlefon-2.5.5-py3-none-any.whl` gebaut und auf Version, MIT-Metadaten,
  Queue-Module und die beiden neuen CLI-Einstiege geprueft. Separat installiert
  und den tatsaechlichen Queue-AGI-Einstieg mit TOML und simuliertem AGI-Dialog
  ausgefuehrt; die installierten Queue-Module entsprechen dem finalen Quellstand.

## Test mit echter Asterisk-Engine

Offizielle Asterisk-Quelle **20.21.0** separat unter einem temporaeren Verzeichnis
gebaut. Die Testinstanz hatte keine SIP-, AMI- oder HTTP-Netzwerkschnittstelle;
Bedienung ausschliesslich ueber ihren eigenen lokalen CLI-Socket. Empfangstelefone
wurden durch Local-Kanaele und Custom-Device-States simuliert. Queue, Dial,
AGI, Kanalvariablen und Gespraechsbruecken liefen in der echten Asterisk-Engine.

Im ersten Lauf mit den alten Grenzen 20/40 zeigte sich eine verspaetete dritte
Rufstufe. Nach Korrektur auf 19/39 wurde folgender Ablauf beobachtet:

| Zeitpunkt ab erstem Angebot | Beobachtung |
| --- | --- |
| 0 s | A klingelt auf 201 |
| 2 s | B klingelt auf 202 |
| 18 s | Beide unbeantworteten Rufversuche enden |
| 20 s | A klingelt auf 201 und 202; B wartet |
| 40 s | A klingelt auf 201, 202 und 203; B wartet |
| 42 s | A wird auf 203 angenommen; B klingelt auf 201 und 202 |

Zweiter Ablauf: B wurde bereits im ersten Zyklus angenommen. Ein spaeterer
Apothekenanruf stand auf Position 1 vor A. Der rote Fallback erhielt das naechste
freie Telefon 201; nach seiner Annahme klingelte die Apotheke erneut auf 203.
Die Gespraeche von B und Rot blieben ueber ihre urspruenglichen Klingelgrenzen
hinaus verbunden. Die Testinstanz wurde anschliessend sauber beendet.

Die Queue-/Dial-Engine wurde nicht geaendert. Fuer den lokalen macOS-Build wurde
ein falsch erkannter, zur Laufzeit fehlender Systemaufruf `pipe2` deaktiviert;
XML-Hilfetexte und PJSIP wurden in dieser minimalen Testinstanz nicht gebaut.
Die Installer-Hilfetextpruefungen sind deshalb separate Regressionstests.

## Reproduzierbare Repository-Pruefungen

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
ruff check --no-cache --select F,I kienzlefon/asterisk.py kienzlefon/queue_*.py kienzlefon/transfer_setup.py tests/test_queue_*.py tests/test_transfer_setup.py
bash -n kienzlefon-installer.sh
bash -n kienzlefon-webinterface-installer.sh
git diff --check
python -m pip wheel --no-deps . --wheel-dir /tmp/kienzlefon-dist
```

Die Admission-Tests benoetigen lokale Loopback-Sockets und wurden mit dieser
Berechtigung ausgefuehrt. Es gab im abgeschlossenen Gesamtlauf keine ausgelassenen
Tests.

## Noch live zu pruefen

Keine Installation auf dem produktiven Server und keine Anrufe an echten
Telefonen ausgefuehrt. Reale PJSIP-Signalisierung, FRITZ!Fon-Anzeige, hoerbare
TTS-/Aufnahmeausgabe, Codecs und Vermittlung mit dem Provider bleiben Teil der
[Live-Abnahme nach dem Update](WARTESCHLANGE.md#live-abnahme).
