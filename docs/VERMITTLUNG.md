# Vermittlung ab Kienzlefon 2.5.4

Umsetzung der [Uebergabe aus kienzlefon-t2med](https://github.com/thomaskien/kienzlefon-t2med/blob/main/docs/TRANSFER_HANDOFF.md).
Die Middleware bedient direkte Vermittlung, Rueckfrage, Abschluss und Abbruch.
Der Telefoninstaller erzeugt die dazu erforderlichen Asterisk-Kanaele und Routen.

## Einrichtung und Update

Den aktuellen `kienzlefon-installer.sh` wie gewohnt ausfuehren und bestehende
Middleware-Einstellungen beibehalten. Bei aktivierter Middleware wird Vermittlung
fuer die bereits ausgewaehlten physischen Telefone eingerichtet. Die Liste
`[middleware].nebenstellen` dient fuer Quell- und interne Zielberechtigungen;
interne Vermittlung zur eigenen Nebenstelle ist ausgeschlossen. KI-, Fax-,
Ansagen- und IVR-Nebenstellen sind keine Vermittlungsziele.

Der AMI-Benutzer, sein Secret, die Quell-IP-Regeln und die Netzwerkbindung werden
nicht fuer Vermittlung erweitert. Die vorhandene Schreibkategorie `call` deckt
`Getvar`, `BlindTransfer`, `Atxfer`, `CancelAtxfer` und `PlayDTMF` ab. Es wird kein
`command`-Recht vergeben und kein Ereignisfilter hinzugefuegt.
Der private TOML-Verbindungsexport erhaelt zusaetzlich:

```toml
[transfer]
enabled = true
context = "kienzlefon-transfer"
extensions = ["201", "202", "203"]
progress_schema_version = 1
```

Die Liste entspricht der tatsaechlichen Telefonkonfiguration. Ohne freigegebenes
physisches Telefon ist `enabled = false`. In der Middleware muss
`telephony.transfer_context = "kienzlefon-transfer"` gelten (Standard).

## Kanaele und Codes

Vor `Dial()` und `Queue()` wird die anrufende Seite geprueft. Nur ein erlaubter
PJSIP-Mitarbeiter erhaelt `T`. Der Pre-Dial-Hook `b()` bereitet den tatsaechlich
angerufenen Kanal vor; Telefone erhalten damit die fuer die angerufene Seite
erforderlichen Funktionen zu `t`. Ein externer Provider erhaelt kein `t`.
Nicht freigegebene Endpunkte und Local-Kanaele erhalten kein `KF_TRANSFER_READY=1`
und keine aktiven Transfer-Featurecodes. Bei einem Local-Zwischenweg erfolgt
die Vorbereitung beim anschliessenden Dial zur tatsaechlichen PJSIP-Nebenstelle
in den verwalteten Telefonkontexten. Individuelle Local-Ziele ausserhalb dieser
Kontexte muessen ebenfalls einen passenden Mitarbeiter-Pre-Dial-Hook enthalten;
die Middleware lehnt einen unvorbereiteten Mitarbeiterkanal ab.

Die Hooks setzen `KF_TRANSFER_READY=1` erst nach Endpunkt- und Codepruefung.
Bereits konfigurierte globale Codes in `features.conf` samt Includes werden
gelesen und erhalten. Fehlende Codes werden nur am Mitarbeiterkanal ergaenzt.
Ohne abweichende Belegung sind dies `atxfer=*2`, `atxferabort=*1` und
`atxfercomplete=*2`: Start und Abschluss werden in unterschiedlichen Phasen
ausgewertet. Konflikte mit bestehenden Codes werden beruecksichtigt; mehrdeutige
explizite Belegungen fuehren vor dem Schreiben zum Abbruch der Einrichtung.
Die Middleware liest die wirksamen Codes erneut am Kanal.

Bestehende `b()`-Hooks werden verkettet, andere Dial-Optionen und Queue-Ansagen
bleiben erhalten. `features.conf` wird nicht mit neuen globalen Codes ueberschrieben.
`atxferdropcall`, Timeout und native Rueckrufregeln bleiben unveraendert.
Abschliessen erfolgt durch `PlayDTMF` mit `Receive: true`, Abbrechen durch
`CancelAtxfer`, jeweils auf dem urspruenglichen Mitarbeiterkanal.

## Zielpruefung und Ereignisse

`kienzlefon-transfer` ist in keinem oeffentlichen Endpoint-/Eingangskontext
eingebunden. Nur Ziffernmuster von 2 bis 32 Stellen werden angenommen;
`h`, `i` und `t` fuehren keine erneute AGI-Pruefung aus.

`kienzlefon-transfer-check` prueft UUID, Clientformat, Mitarbeiter-Uniqueid,
Modus, Zieltyp, freigegebene Quelle und die Gleichheit von `KF_TRANSFER_TARGET`
mit dem tatsaechlichen Dialplan-Ziel. Die sieben von der Middleware vererbten
`KF_TRANSFER_*`-Variablen bleiben erhalten. Eine Pruefung des aktuellen Endpunkts
gegen den urspruenglichen Mitarbeiter waere hier falsch: Der Zielkontext laeuft
auf der Gegenstelle oder einem neuen Rueckfragekanal.

Interne Ziele werden nur als bekannte andere Mitarbeiternebenstelle gewaehlt.
Externe Ziele gehen nach Freigabe ueber `kienzlefon-outbound`. Provider und
Praxis-Absendernummer stammen von der urspruenglichen Mitarbeiternebenstelle;
Rufnummernsperren und Kapazitaetspruefung gelten wie bei normaler Wahl. Ein
AGI-Fehler kann keine Freigabe aus einem vorigen Wahlversuch wiederverwenden.

Unmittelbar vor dem echten `Dial()` wird `KienzlefonTransferProgress` mit
`SchemaVersion: 1`, Auftrags-UUID, urspruenglicher Mitarbeiter-Uniqueid,
`SourceUniqueid: ${UNIQUEID}` des waehlenden Kanals und `Phase: dialing_target`
gesendet. Ein vorgeschaltetes Goto sendet keinen verfruehten Wahlfortschritt.
Validierungs-/Routingablehnungen senden `failed`; normales Besetzt, Nichtmelden
oder `h` senden keinen nachtraeglichen terminalen Fehler. Native Transfer- und
Bridge-Ereignisse bestimmen den Gespraechsausgang in der Middleware.

## Installerpruefungen

Vor Asterisk-Aenderungen kontrolliert der Installer die erforderlichen AMI-Aktionen,
Kanal-Funktionen und Dial-/Queue-Pre-Dial-Hooks. Asterisk-CLI-Fehler werden auch
bei Exitcode 0 erkannt. Dateien werden zunaechst getrennt erzeugt und auf die
erforderlichen privaten Kontexte, Freigaben und erlaubte Hooks geprueft, dann
installiert. Vorhandene Dateien erhalten die ueblichen Sicherungskopien.
Nach Reload werden die geladenen Transfer-, Queue- und Ausgehkontexte kontrolliert.
Ein erneuter Lauf erzeugt dieselben Hooks; Middleware-Deaktivierung entfernt sie.

Manuelle lesende Pruefung auf dem Telefonserver:

```sh
/opt/kienzlefon/venv/bin/kienzlefon-transfer-setup preflight
/opt/kienzlefon/venv/bin/kienzlefon-transfer-setup verify
asterisk -rx 'manager show command BlindTransfer'
asterisk -rx 'manager show command Atxfer'
asterisk -rx 'manager show command CancelAtxfer'
asterisk -rx 'manager show command PlayDTMF'
asterisk -rx 'features show'
asterisk -rx 'dialplan show kienzlefon-transfer'
```

Die globalen Werte bei `features show` koennen von den ergaenzten Kanalwerten
abweichen. Die Middleware liest deshalb `FEATUREMAP(atxfer)` und `FEATURE(...)`
am konkreten Mitarbeiterkanal. Bestehende Gespraeche erhalten durch einen Reload
keine nachtraegliche Vorbereitung: Fuer die Abnahme neue Gespraeche beginnen.

## Live-Abnahme nach dem Update

1. Eingehender Queue-Anruf an 202: direkt nach 201, danach separat zu einer
   externen Testnummer vermitteln. Richtige Praxis-Absendernummer und Sprache
   in beiden Richtungen pruefen.
2. Rueckfrage intern und extern: Anrufer wartet, Ziel klingelt; nach Annahme
   Ruecksprache halten, einmal abschliessen und einmal zum Anrufer zurueckkehren.
3. Besetzt/Nichtmelden sowie Auflegen durch Ziel, Anrufer und Mitarbeiter testen.
   Native Rueckkehr-/Rueckrufregeln und richtige Middleware-Anzeige pruefen.
4. Ablaufe mit eingehendem Direktanruf, interner Verbindung, normalem ausgehendem
   Anruf, Click-to-Dial und vorhandenen Local-Zwischenkanaelen wiederholen.
   Externe Anrufer duerfen keine Mitarbeiter-Transferfunktion erhalten.
5. Doppelklick, Neuladen, Arbeitsplatzwechsel und AMI-Unterbrechung pruefen:
   kein doppelter Auftrag, keine fremden Gespraeche, keine Vermittlung eines
   bloss wartenden Queue-Eintrags. Bei ungewissem Ausgang nicht automatisch neu waehlen.

Automatisierte AGI-, Dialplan-, Installer- und Middleware-Vertragstests pruefen
die erzeugte Konfiguration und simulierte Protokollantworten. Sie ersetzen den
Gespraechstest gegen die installierte Asterisk-Anlage nicht.
