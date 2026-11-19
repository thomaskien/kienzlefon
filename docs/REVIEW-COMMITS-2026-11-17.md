# Commit-Analyse vom 17.11.2026

Geprueft: `799378b..52823bf` im Repository `thomaskien/kienzlefon`.
Die Commits wurden mit `git fetch origin` heruntergeladen und in einem
isolierten temporaeren Worktree getestet. Der lokale Hauptbranch und alle
vorhandenen Benutzerarbeiten wurden nicht mit dem neuen Stand zusammengefuehrt.

## Umfang

| Commit | Inhalt |
| --- | --- |
| `1a746c2` | Konfigurierbare SIP-Zielrufnummernformate je ausgehendem Endpunkt |
| `52823bf` | Merge von Pull Request #1 am 16.11.2026 |

Sieben Dateien, 176 hinzugefuegte und eine entfernte Zeile. Die GitHub-API lieferte
zum Pruefzeitpunkt genau einen Pull Request: den bereits gemergten
[PR #1](https://github.com/thomaskien/kienzlefon/pull/1). Keine offenen Pull Requests.

## Funktionale Einordnung

Die neue Einstellung `[wahlregeln].sip_zielformate` waehlt je PJSIP-Endpunkt
zwischen `digits` und `e164_plus`. Damit koennen Provider angesprochen werden,
die beispielsweise `+49176...` statt `49176...` erwarten.

- Ohne neue Einstellung bleibt die bisherige Nummernformatierung aktiv.
- Die Umformatierung erfolgt nach der Wahlberechtigungspruefung.
- `KZF_DIAL_NUMBER` bleibt die kanonische Nummer fuer die bestehende Verarbeitung;
  `KZF_SIP_TARGET` wird erst fuer das ausgehende `Dial(PJSIP/...)` verwendet.
- Sperrregeln, protokollierte Rufnummern und Absenderrufnummern bleiben erhalten.
- `110`, `112`, `116116` und `116117` werden nicht umformatiert.
- Normale externe Wahl, Click-to-Dial und externe Vermittlung nutzen laut
  Codepruefung den gemeinsamen Ausgangskontext.

Der Beitrag ist funktional sinnvoll. Vor einer Release-Freigabe sind die
folgenden beiden Punkte zu bearbeiten.

## Befunde

### P2: Gueltige TOML-Untersektion wird beim Update beschaedigt

Die Konfiguration akzeptiert sowohl eine Inline-Tabelle als auch diese
gleichwertige TOML-Schreibweise:

```toml
[wahlregeln.sip_zielformate]
"kfx-phone-in-endpoint" = "e164_plus"
```

`load_config()` laedt die Untersektion erfolgreich. `migrate_config()` erkennt
sie jedoch nicht als vorhandenen Schluessel in `[wahlregeln]` und fuegt dort
zusaetzlich `sip_zielformate = {}` ein. Die gespeicherte Datei ist anschliessend
ungueltig: `TOMLDecodeError: Cannot declare ('wahlregeln', 'sip_zielformate') twice`.
Das betrifft ein spaeteres Installer-Update mit dieser Schreibweise und kann
das Laden der Konfiguration verhindern.

Reproduziert mit der Beispielkonfiguration und einem isolierten Testschluessel:
Untersektion schreiben, `load_config()` erfolgreich ausfuehren,
`migrate_config()` aufrufen, erneutes `load_config()` schlaegt fehl.
Ursache: `kienzlefon/migration.py`, insbesondere die Schluesselerkennung ab
Zeile 107 und das Einfuegen ab Zeile 114. Die neue Vorlage fuehrt den betreffenden
Tabellenschluessel in `config/kienzlefon.toml.example`, Zeile 171 ein.

Empfehlung: Bei der Migration vorhandene TOML-Untertabellen beruecksichtigen
und das Ergebnis vor dem Ersetzen der Konfigurationsdatei parsen. Einen
Regressionstest fuer diese Schreibweise ergaenzen. Die im PR dokumentierte
Inline-Schreibweise wurde ebenfalls getestet und bleibt beim Update erhalten.

### P2: Vier bestehende Regressionstests wurden nicht angepasst

In `tests/test_transfer_dialplan.py` erwarten drei Tests weiterhin
`KZF_DIAL_NUMBER` im finalen `Dial()` statt `KZF_SIP_TARGET`:

- `test_render_decorates_queue_internal_outbound_direct_and_click_to_dial_flows`
- `test_external_progress_is_on_dial_channel_after_checks_and_capacity`
- `test_failed_is_only_emitted_for_rejection_not_normal_dial_results`

In `tests/test_transfer_setup.py` enthaelt
`test_common_outbound_agi_releases_only_after_number_and_callerid[False]`
noch den alten simulierten AGI-Antwortablauf. Antworten fuer die zusaetzlichen
Befehle `GET VARIABLE KZF_OUT_ENDPOINT` und `SET VARIABLE KZF_SIP_TARGET` fehlen.

Diese vier Fehler belegen veraltete Testerwartungen, keinen nachgewiesenen
Ausfall der Vermittlungsfunktion. Ergaenzende AGI-Pruefungen mit vollstaendigen
Antwortfolgen bestaetigen Zielformat, Erhalt der Caller-ID und Freigabe erst
nach dem Setzen aller Zielvariablen. Die bestehenden Tests muessen ihre
bisherigen Sicherheits- und Reihenfolgepruefungen mit dem neuen Ablauf behalten.

## Validierung

Umgebung: macOS, Python 3.12.14, pytest 9.2.0, cryptography 49.0.0;
isolierte virtuelle Umgebung unter `/private/tmp`.

| Pruefung | Ergebnis |
| --- | --- |
| Gesamtsuite auf `52823bf` | 574 Tests; zuerst 553 bestanden, 21 fehlgeschlagen |
| Davon 17 Admission-Tests | Zunaechst durch Sandbox-Socketverbot blockiert; mit Loopback-Berechtigung alle bestanden |
| Bereinigtes Gesamtergebnis ueber beide Laeufe | 570 bestanden, vier veraltete Testfaelle fehlgeschlagen, keine ausgelassen |
| Neue SIP-Tests | Alle 15 bestanden |
| Transfer-Testdateien auf Ausgangsstand `799378b` | Alle 59 bestanden |
| Zusaetzliche AGI-Pruefungen | Acht Szenarien bestanden: Endpunktauswahl, deutsche/lokale Nummern, Notruf, gesperrte Ziele und Caller-ID |
| Alte Konfiguration ohne neuen Schluessel | Erfolgreich geladen; Standard bleibt `{}` |
| Migration mit Inline-Tabelle | Einstellung bleibt erhalten |
| Migration mit TOML-Untersektion | Obiger Updatefehler reproduziert |
| `git diff --check 799378b..52823bf` | Bestanden |

Reproduzierbare Repository-Testbefehle, jeweils im passenden Checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_admission.py
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_transfer_dialplan.py tests/test_transfer_setup.py
git diff --check 799378b..52823bf
```

Keine echten Provideranrufe und kein Deployment ausgefuehrt. Die vom Autor
berichtete Fonial/Plusnet-Pruefung wurde nicht unabhaengig am SIP-Anschluss
wiederholt. Python-Paket und generierter Dialplan muessen beim spaeteren Update
zusammen aktualisiert werden, da der neue Dialplan `KZF_SIP_TARGET` erwartet.

## Einordnung fuer die naechste Version

- SIP-Zielformate nach Behebung des Migrationsfehlers und Anpassung der Tests
  in die Release-Abnahme aufnehmen; Versionsstand aktuell weiterhin 2.5.5.
- Die bereits lokal vorhandenen SMS-/Queue-Arbeiten sind nicht Bestandteil
  dieser beiden heruntergeladenen Commits und wurden hier nicht erneut bewertet.
- Die am 16.11. vorgemerkte datensparsame Audioaufbewahrung bleibt offen:
  Begleitverzeichnis zur JSON, strikt vorgangsbezogene Zuordnung und je nach
  Einstellung Verschiebung oder Bereinigung nach der Erkennung.
  Dieser Beitrag aendert die Audioaufbewahrung nicht.

Die Analyse nimmt keine Codekorrekturen, Commits, Pushes oder Serveraenderungen vor.
