# Zweite Commit-Analyse vom 17.11.2026

Gepruefter Bereich: `52823bf..0e1f11c`. Die beiden neuen Merge-Commits bringen
insgesamt 17 Commits inklusive ihrer Implementierungscommits mit: 14 Dateien,
603 hinzugefuegte und zehn entfernte Zeilen. Download per `git fetch origin`,
Review und Tests in einem temporaeren Worktree. Der Hauptcheckout bleibt auf
`799378b`; vorhandene lokale SMS-Arbeiten und Dokumentationsaenderungen bleiben
erhalten.

| Beitrag | Merge | Inhalt | Bewertung |
| --- | --- | --- | --- |
| [PR #3](https://github.com/thomaskien/kienzlefon/pull/3) | `f174903` | SIP-Zielformat `national` | Keine neuen Funktionsfehler festgestellt; bestehende SIP-Nacharbeiten bleiben offen |
| [PR #4](https://github.com/thomaskien/kienzlefon/pull/4) | `0e1f11c` | Optionale Google-Cloud-TTS-Engine | Vier neue Befunde, darunter ein Blocker fuer die Erzeugung im Webinterface |

## SIP-Zielformat national

Der neue Modus wandelt deutsche Ziele wie `49176...` in `0176...` um.
Er ist je Endpunkt konfigurierbar, etwa fuer voip2gsm. Erlaubte auslaendische
Ziele behalten `00...`, Notruf-/Servicenummern bleiben unveraendert. Die
Wahlberechtigung wird weiterhin vor der Formatierung geprueft.

Alle 23 SIP-Tests bestehen, darunter acht neue Nationalformat-Faelle.
Elf ergaenzende Offline-Proben pruefen Ortsnummern, Auslandsziele, erneute
Wahlpruefung nach Formatierung, Auslandsperre und Premiumsperre. Kein neuer
Fehler gefunden. Die vier veralteten Transfer-Tests und der bereits bekannte
Migrationsfehler mit `[wahlregeln.sip_zielformate]` sind weiterhin vorhanden.

## Google Cloud TTS

Der Beitrag ergaenzt die Engine-Auswahl im Installer und Webinterface, einen
Python-Generator, eine separate Datei fuer den API-Schluessel sowie
Cache-Identitaeten fuer Stimme, Sprache und Tempo. Ansagetexte werden zur
Erzeugung an den konfigurierten Dienst gesendet; die erzeugten Audiodateien
werden anschliessend lokal genutzt. API-Schluesselwechsel allein invalidieren
den Cache nicht. Kokoro bleibt die Standardeinstellung.

Die ausgewaehlte Stimme `de-DE-Chirp3-HD-Sulafat` und die verwendete
Tempo-Steuerung sind in der offiziellen Google-Dokumentation aufgefuehrt:
[Stimmen](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types),
[Chirp-3-HD-Steuerung](https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd).
Es wurden keine echten API-Schluessel verwendet und keine Google-Syntheseaufrufe
ausgeloest.

### P1: Google-Erzeugung im installierten Webinterface wird vom Dienst blockiert

Der Google-Modus wird in `kienzlefon/webadmin.py:910` freigegeben, sobald Generator
und Konfigurationsdatei existieren. Die Erzeugung startet aber als Unterprozess
des Webinterface-Workers. Dessen systemd-Einheit erlaubt unveraendert nur
`RestrictAddressFamilies=AF_UNIX`
(`kienzlefon-webinterface-installer.sh:344`). Der Google-Generator benoetigt
AF_INET beziehungsweise AF_INET6 fuer HTTPS.

Damit kann die Erzeugung beim manuellen Installerlauf funktionieren, waehrend
spaetere Textaenderungen oder der Engine-Wechsel im Webinterface scheitern.
Es handelt sich um eine aus dem Aufrufpfad und der Dienstkonfiguration
abgeleitete Integrationssperre; ein echter Linux-systemd-Lauf wurde auf diesem
macOS-Rechner nicht ausgefuehrt. Die Wirkung der Allowlist bestaetigt die
[systemd-Dokumentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#RestrictAddressFamilies=).

Abhilfe: Netzwerkzugriff fuer den vorgesehenen Cloud-Erzeugungspfad gezielt
ermoeglichen und die Funktion innerhalb der installierten Diensteinheit testen.
Bestehende Schutzmassnahmen fuer die lokalen Engines dabei beruecksichtigen.

### P2: Konfigurierter Google-Konfigurationspfad wird nicht uebergeben

`[tts].google_konfig` wird geladen, auf Existenz geprueft und fuer die
Cache-Identitaet gelesen. `_google_command()` uebergibt den Pfad jedoch nicht
an den Generator (`kienzlefon/prompts.py:1146`). Dessen Argumentparser faellt
deshalb immer auf `/etc/kienzlefon/google-tts.conf` zurueck
(`scripts/google-tts/kienzlefon-google-tts-generate:59`).

Mit einem abweichenden Pfad scheitert die Erzeugung oder verwendet die falsche
Stimme, Zugangsdaten und Endpunktkonfiguration. Der Cache kann dabei die
Identitaet der ausgewaehlten Datei speichern, obwohl eine andere verwendet wird.
Reproduktion: temporaere alternative Konfiguration, echten Aufruf erzeugen,
Generator mit exakt diesen Argumenten starten und ausschliesslich den
Dateileser mocken. Dieser erhaelt den Standardpfad, nicht den konfigurierten Pfad.

Abhilfe: `--config` mit `config.tts.google_config` uebergeben und einen Test
hinzufuegen, der die tatsaechlich gelesene Datei kontrolliert.

### P2: Installer entfernt einen konfigurierten API-Endpunkt

`ENDPOINT` ist eine dokumentierte Option der Google-Konfiguration. Der Installer
liest und schreibt jedoch nur API_KEY, VOICE, LANG und RATE
(`kienzlefon-installer.sh:157` und `:1767`). Beim naechsten Update mit Google als
Engine wird die vorhandene Datei ersetzt und ENDPOINT geht verloren.

Reproduziert mit `ENDPOINT=eu-texttospeech.googleapis.com`: Nach dem Installerlauf
fehlt die Zeile; der Generator verwendet wieder `texttospeech.googleapis.com`.
Das veraendert eine bewusste Endpunktauswahl ohne Hinweis. Google dokumentiert
EU und global als unterschiedliche Ziele in seiner
[Endpunkt-Dokumentation](https://docs.cloud.google.com/text-to-speech/docs/endpoints).

Die Probe fuehrte die unveraenderten Erfassungs- und Installationsfunktionen mit
temporaeren Pfaden aus. Nur `chown` wurde fuer macOS ersetzt; keine API-Anfrage.
Abhilfe: Vorhandenen ENDPOINT erhalten und im Update-Test absichern.

### P2: HTTP-Ausnahme prueft nur einen Zeichenkettenpraefix

`endpoint_url()` soll unverschluesseltes HTTP auf Loopback beschraenken, prueft
aber nur `startswith("http://localhost")` beziehungsweise
`startswith("http://127.0.0.1")`
(`scripts/google-tts/kienzlefon-google-tts-generate:48`).

Offline bestaetigt: `http://localhost.example.invalid` und
`http://127.0.0.1@remote.example.invalid` werden akzeptiert, obwohl der von
`urlsplit()` bestimmte Zielhost kein Loopback ist. Bei einer solchen
ENDPOINT-Konfiguration wuerden Ansagetext und X-Goog-Api-Key unverschluesselt an
den externen Host gesendet. Die Standardkonfiguration mit HTTPS ist nicht
betroffen; die Probe hat keine Netzwerkverbindung aufgebaut.

Abhilfe: URL strukturiert parsen, Benutzerinformationen ausschliessen und den
Host exakt auf Loopback pruefen, oder die HTTP-Testausnahme ganz entfernen.

## Tests und Grenzen

Python 3.12.14, pytest 9.2.0, cryptography 49.0.0; ffmpeg vorhanden.
Die vollstaendige Suite wurde mit Berechtigung fuer lokale Test-Sockets gestartet.

| Pruefung | Ergebnis |
| --- | --- |
| Gesamtsuite `0e1f11c` | 594 Tests: 588 bestanden, sechs fehlgeschlagen, keine ausgelassen |
| Vier Transfer-Fehler | Bereits im ersten Review bekannt; veraltete Dialplan-/AGI-Erwartungen |
| Zwei neue Installer-Testfehler | `chown root:root` setzt Linux und Root-Rechte voraus; macOS meldet `illegal group name` |
| Dieselben zwei Tests mit isoliertem chown-Ersatz | Beide bestanden; echte Eigentuemeraenderung damit nicht getestet |
| Google-Testmodul | Zwoelf Tests: zehn direkt bestanden, zwei oben beschriebene Plattformfehler |
| SIP-Testmodul | Alle 23 bestanden |
| Ergaenzende Offline-Proben | Konfigurationspfad, Endpunktverlust und HTTP-Praefixfehler bestaetigt; elf Nationalformat-Proben bestanden |
| Vorherige AGI-/Migrationsproben | Acht AGI-Szenarien bestanden; TOML-Untersektionsfehler weiterhin reproduziert |
| Bash-Syntax beider Installer, PHP-Syntax, Diff-Whitespace | Bestanden |

Hauptbefehle im isolierten Checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider --tb=short
bash -n kienzlefon-installer.sh
bash -n kienzlefon-webinterface-installer.sh
php -l webinterface/admin.php
git diff --check 52823bf..0e1f11c
```

Die neuen Tests decken einen lokalen HTTP-Mock mit echter WAV-Ausgabe ab,
jedoch weder den systemd-Netzwerkschutz noch den benutzerdefinierten
Konfigurationspfad oder den Erhalt von ENDPOINT bei Updates.

Der vorgesehene separate Sol-Worker wurde gestartet, beendete sich aber vor
Arbeitsbeginn mit Exit-Code 1: `The 'gpt-5.6-sol' model is not supported when
using Codex with a ChatGPT account.` Der Lead hat das Review vollstaendig
selbst durchgefuehrt. Keine Modell-, Login- oder Account-Aenderung.

Keine Codekorrekturen, Commits, Pushes, produktiven Serveraenderungen oder echten
Provideranrufe. Die Befunde des [ersten Reviews](REVIEW-COMMITS-2026-11-17.md)
bleiben offen. Die vorgemerkte datensparsame Audioaufbewahrung wird durch keinen
der neuen Beitraege umgesetzt oder veraendert.
