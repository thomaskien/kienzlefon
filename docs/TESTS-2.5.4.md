# Releasepruefung 2.5.4

Stand: 12.10.2026, vor dem GitHub-Upload.

- Gesamte Release-Suite: **499 Tests bestanden**, 35,23 Sekunden. Isolierter
  Release-Worktree ohne die unabhaengigen, unveroeffentlichten SMS-Arbeiten.
- **110 Transfer-Tests**: vollstaendiges AGI-Protokoll mit echtem `AgiChannel`,
  interne/externe Ziele, Mitarbeiter-/Providerwahl, fehlende und falsche
  Metadaten, numerische Client-ID, verbotene Funktions-/KI-Ziele, AGI-Abbruch,
  private Kontexte und Kanalvorbereitung, Fortschrittsereignisse nach Pruefungen,
  native Fehler-/Hangup-Wege, Featurecodeplanung und Includes.
- Installer-Integration: Konfiguration zuerst getrennt planen/validieren,
  keine Datei-Aenderung bei Ablehnung, idempotente Wiederholung und Abschaltung,
  Erhalt vorhandener Hooks/Queueparameter, globaler Featurecodes und AMI-Secrets,
  Benutzerrechte/ACL unveraendert, additive TOML-Uebergabe.
- Nationale, `+49`- und `0049`-Schreibweise, Auslandssperre und freigegebene
  Auslandsnummern nach mehrfacher Wahlpruefung getestet. Die gemeinsame
  Ausgeh-AGI setzt die Freigabe erst nach Nummer und Praxis-Absendernummer.
- Wartepositionskorrektur mit Migration: alte Standardpaare werden gemeinsam
  ersetzt, eigene Texte und manuelle Aufnahmen bleiben erhalten.
- Unabhaengiger Sol-Review: 187 gezielte Tests und 6 zusaetzliche Migrationstests
  bestanden, keine offenen P1/P2-Befunde. Asterisk-20-Dokumentation und aktuelle
  Kienzlefax-Telefonievorlage abgeglichen. Abschliessendes Lead-Review und
  vollstaendiger Testlauf einschliesslich spaeter ergaenzter Freigabetests erfolgt.
- Wheel `kienzlefon-2.5.4-py3-none-any.whl` gebaut; MIT-Metadaten und beide neuen
  CLI-Einstiege kontrolliert. Paket in temporaeren Pfad installiert und echte
  Transfer-AGI-CLI mit TOML-Konfiguration und simuliertem Asterisk-Eingabedialog
  ausgefuehrt: intern/extern erlaubt, Zielabweichung/Funktionsziel abgewiesen.
- Ruff `F,I`, Bash-Syntax beider Installer, PHP-Syntax des Webinterfaces und
  `git diff --check` bestanden.

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
ruff check --no-cache --select F,I kienzlefon/transfer_*.py tests/test_transfer_*.py
bash -n kienzlefon-installer.sh
bash -n kienzlefon-webinterface-installer.sh
php -l webinterface/admin.php
```

Die Netzwerk-Admission-Tests brauchen lokale Loopback-Sockets. Der erste
Sandbox-Lauf wurde deshalb mit entsprechender Berechtigung wiederholt;
im endgueltigen Gesamtlauf gab es keine ausgelassenen oder fehlgeschlagenen Tests.

## Noch live zu pruefen

Lokal steht kein laufender Asterisk zur Verfuegung. Es wurden keine produktiven
Anrufe und kein Live-Deployment ausgefuehrt. Die Tests pruefen Protokolldialoge
und generierte Konfigurationen; reale Bruecken, Audiosignale, Transferabschluss,
Rueckkehr/Rueckruf und Providerverhalten prueft die anschliessende
[Live-Abnahme](VERMITTLUNG.md#live-abnahme-nach-dem-update) nach dem Installerupdate.
