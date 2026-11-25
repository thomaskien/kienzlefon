<!--
kienzlefon
Version: 2.7
Changelog:
- 2.4.1: Kokoro-Thorsten als Standard fuer lokale Ansagen ergaenzt.
- 2.4.0: Integriertes Webinterface und gemeinsame TTS-Erzeugungslogik dokumentiert.
- 1.9.3: Worker-Abschluss ohne Telepraxis-Datei fuer vollstaendig leere Anrufe dokumentiert.
- 1.9.2: Erfolgreichen Nicht-Demo-Zweig der Updatekonfiguration dokumentiert.
- 1.9.1: Fehlerfreie wav16-Vorpruefung vor dem Worker-Neustart dokumentiert.
- 1.9: Ausgabeseitige Rufnummernanonymisierung des Demomodus dokumentiert.
- 1.8.3: Unabhaengige Verarbeitung leerer und befuellter Einzelaufnahmen dokumentiert.
- 1.8.1: Rechte und systemd-Gruppe der Telepraxis-Ausgabe dokumentiert.
- 1.8: Demoausgabe und sicheres Verwerfen leerer Abbrueche dokumentiert.
- 1.7.1: Rotes Telefon als bedingtes Mitglied der Sonderqueue dokumentiert.
- 1.7: Sonderqueue, Penalty-Initialisierung und Caller-ID-Anzeige dokumentiert.
- 1.6: Feldabhaengige Mehrmodell-Ladung und Gesundheitspruefung dokumentiert.
- 1.5: wav16-Aufnahme und gemeinsame Lautheitsmasterung dokumentiert.
- 1.4: Interne Erreichbarkeit ohne PIN und konservative Audiobereinigung dokumentiert.
- 1.3: Ansagenverwaltung, Zusatztelefone und Wahlpruefung dokumentiert.
- 1.2: Dokumentationsstand auf Kienzlefon 1.2 aktualisiert.
- 1.1: TTS-Pausen und Fallback des roten Telefons dokumentiert.
- 1.0: Erstfassung der technischen Architektur.
-->

# Architektur

## Komponenten

`Asterisk` uebernimmt SIP, RTP, DTMF, Queue, Routing, Wiedergabe und Aufnahme.
Das lokale AGI `kienzlefon-agi` liest die zentrale TOML-Datei und steuert den
freigegebenen IVR-Ablauf. Fachliche Kategorien entstehen ausschliesslich aus
der Tastenauswahl.

`kienzlefon-worker` ist ein einzelner, dauerhaft laufender systemd-Dienst. Er
laedt ueber `faster-whisper` und CTranslate2 jede unterschiedliche, in TOML
konfigurierte Modellvariante genau einmal in den Arbeitsspeicher und haelt sie
dort. Vor- und Nachname, Medikamente sowie alle uebrigen Felder besitzen
getrennte Modellzuordnungen. Sind alle Zuordnungen gleich, existiert nur eine
Modellinstanz. CPU-Threads sind konfigurierbar. Der Worker verarbeitet
vollstaendige Vorgangsordner nacheinander.

Innerhalb eines Vorgangs werden die Audiodateien unabhaengig voneinander
verarbeitet. Eine Aufnahme ohne erkannten Text erhaelt den fehlerfreien Status
`empty`; nachfolgende Aufnahmen werden weiterhin transkribiert. Erfolgreiche
Transkripte werden in das normale JSON uebernommen, fehlende Felder bleiben leer.
Enthaelt ein fehlerfreier Vorgang nach Verarbeitung aller Aufnahmen kein einziges
nicht leeres Transkript, wird er intern als `ready` abgeschlossen, ohne eine
Telepraxis-Datei zu erzeugen.

Vor- und Nachnamen werden mit `language="de"`, `task="transcribe"`,
`beam_size=5` und ihrem jeweiligen editierbaren Initial-Prompt transkribiert.
Medikamente besitzen einen eigenen Prompt, der Medikamentenname oder Wirkstoff,
Wirkstaerke und Packungsgroesse beschreibt. Die Modellwahl folgt ausschliesslich
dem bereits strukturierten Feldtyp des Transkriptionsauftrags.

`kienzlefon-ansagen` erzeugt aus den TOML-Texten lokale Master-WAVs und die
Asterisk-Formate. CLI und integriertes Webinterface verwenden dieselbe
Erzeugungslogik. Eine gleichnamige menschliche WAV-Datei im konfigurierten
Upload-Verzeichnis hat Vorrang vor der automatischen TTS-Ansage.

Standard ist Kokoro-Thorsten auf CPU. Der Installer richtet eine separate,
nach Inhalt versionierte Python-Umgebung ein und aktiviert den Generator erst
nach einer erfolgreichen lokalen Testansage. Modellrevision und SHA-256-Werte
stehen in `scripts/kokoro/model_manifest.json`, die Abhaengigkeiten in der
benachbarten CPU-Lockdatei. Der Download wird nur beim Einrichten benoetigt;
der Generator arbeitet offline. Er liefert 24-kHz-Mono-PCM, anschliessend
entstehen wie bisher normalisierte 16-kHz-Master und Telefonieformate.
Kokoro-Fehler brechen den Generierungslauf ab; Piper ist eine explizite Auswahl.

`length_scale` und `sentence_silence` werden an Piper uebergeben. Marker wie
`{pause:800}` werden vor der Synthese strukturiert zerlegt und als exakte
PCM-Stille zwischen gleichformatigen WAV-Segmenten eingefuegt.

Das interne AGI `kienzlefon-ansagen-ivr` ist ausschliesslich aus lokalen
Telefonkontexten ueber Nebenstelle `777` erreichbar und verwendet keine PIN.
Neue WAV-Dateien werden zuerst als Kandidat gespeichert und
erst nach erfolgreicher Konvertierung atomar aktiviert. Vorherige manuelle
Dateien bleiben im Unterordner `inaktiv` erhalten. Administrative Aktionen
werden als JSON-Zeilen protokolliert.
Menueanweisungen werden bei ausbleibender Eingabe nach fuenf Sekunden
unbegrenzt wiederholt. Aus dem Ansagenkatalog entfernte generierte Dateien
werden beim naechsten Erzeugungslauf aus den Telefonieformaten entfernt.

Neue Telefonaufnahmen aus dem Ansagen-IVR werden nach einem Signalton direkt
als `wav16` erfasst. Dadurch bleibt ein ausgehandelter G.722-Sprachkanal bis
zur 16-kHz-PCM-Datei breitbandig. Vor Vorschau und Aktivierung misst FFmpeg die
integrierte Lautheit und normalisiert in einem zweiten Durchlauf standardmaessig
auf `-19 LUFS` bei hoechstens `-2 dB` True Peak. Dieselbe Masterung wird auf
Kokoro-, Piper- und Qwen-Quellen angewandt. Erst danach entstehen G.722, A-law und mu-law.

Alte manuelle `.wav`-Dateien bleiben als Eingabe kompatibel. `wav16` hat bei
gleichnamigen Quellen Vorrang. Aktivierung und Rueckschaltung sichern beide
Varianten und stellen sie bei einem Fehler gemeinsam wieder her.

## Annahmesperre

Ein eigener Heartbeat-Thread aktualisiert
`/run/kienzlefon/whisper-health.json`, auch waehrend einer Transkription. Erst
nach vollstaendig geladener konfigurierter Modellmenge ist `ready=true`. Ein veralteter oder
negativer Heartbeat fuehrt vor jeder Nachrichtenaufnahme zur Stoerungsansage
und danach direkt zur bestehenden Praxisqueue.

Fehlt auch die konfigurierte Dateiausgabe, meldet der Worker sich ebenfalls
nicht bereit. Bereits erfasste Daten bleiben im Spool und werden erneut
verarbeitet. Neue Nachrichten werden nicht still aufgestaut.

## Atomare Verarbeitung

`call.json` wird stets in eine neue temporaere Datei geschrieben, mit `fsync`
gesichert und per `os.replace` aktiviert. Die Dateiausgabe unterstützt lokale JSON-Dateien, verschlüsselte JSON-Dateien und verschlüsselte Pakete mit WAV-Beilage. Die optionale Anonymisierung ersetzt bekannte Nummern in den Feldern `id` und `telefon` der lokalen JSON-Ausgabe. Aufnahmen und Spooldaten können die ursprünglichen Angaben enthalten. [Ablage und Formate](TELEPRAXIS.md)

Vorgangsordner wechseln nur per atomarem
Verzeichnis-Rename zwischen `recording`, `queue`, `processing`, `ready` und
`error`.

Beim Workerstart werden liegengebliebene `processing`-Vorgaenge erneut
eingereiht. Alte, nach einem Abbruch nicht abgeschlossene Aufnahmeordner werden
nach der konfigurierten Zeit ebenfalls wieder eingereiht.

Ein regulaerer Anrufabbruch vor jeder verwertbaren Audiodatei wird nur dann
vollstaendig verworfen, wenn im Vorgang kein technischer Fehler erfasst wurde.
Vorhandene Audiodaten und Fehler verhindern diese Bereinigung.

Telepraxis-Zieldateien erhalten vor dem atomaren Umbenennen Modus `0660`.
Bei Root-Ausfuehrung werden Eigentumer `root` und die Gruppe des Zielverzeichnisses
gesetzt. Die erzeugte systemd-Einheit nutzt dieselbe Gruppe als Primaergruppe
und `UMask=0007`. Die internen Spooldateien bleiben bei `0640`.

## Implementierungsstand 2.7

| Bereich | In Kienzlefon 2.7 |
| --- | --- |
| IVR | Menütasten und Ansagenreihenfolge sind konfigurierbar. Ein Anruf kann mehrere Anliegen derselben Person erfassen. [IVR-Ablauf](IVR.md) |
| Telefonie | Zwei optionale Direktnummern führen zeitunabhängig zur Praxisqueue oder zu ROT. Der Steuerungsdienst verwaltet die Rufgruppen über Asterisk und liefert Live-Zähler. Die Middleware verarbeitet die Ereignisse für die Tagesstatistik. [Anlagensteuerung](ANLAGENSTEUERUNG.md) |
| Transkription | Bei eingerichteter Commander-IP versucht der Worker die Erkennung für die Aufnahme über `POST /v1/asr/final-block` auf Port 8185. Schlägt der Versuch fehl, übernimmt das lokale CPU-Modell. |
| Audioübergabe | JSON und optionale WAVs gehen an die lokale Inbox oder werden der Praxis zur verschlüsselten Abholung bereitgestellt. [Audiovertrag](vorgang-v1/AUDIO.md) |

Die nachfolgenden Abschnitte „Geplant“ und „Vorgemerkt“ geben die Anforderungen und offenen Fragen **vom 17. und 18. November 2026** wieder. Für Installation, Konfiguration und die Prüfung der tatsächlich freigegebenen Funktionen gelten die [Anleitung](../README.md#installation) und das [Changelog zu 2.7](../CHANGELOG.md#27).

## Geplant: einzeln konfigurierbare und deaktivierbare IVR-Menuepunkte

Benutzerwunsch vom 17.11.2026 fuer IVR, Adminoberflaeche und Anrufbaum;
Teil der gesammelten Umsetzung, noch nicht implementiert. Gemeint sind die
Tastenbelegungen der IVR-Menuepunkte.

Aktuell sind die Ziffern im IVR-Code fest zugeordnet, einschliesslich des
AI-Shortcuts auf `0`, der Oeffnungszeiten auf `6` und des Untermenues auf `5`.
Auch die Menueansagen und der Anrufbaum im Webinterface enthalten feste
Tastenangaben. Eine reine Aenderung der sichtbaren Beschriftung reicht daher
nicht aus.

- Jeden Menuepunkt einzeln aktivieren/deaktivieren und seine Taste innerhalb
  des jeweiligen Haupt- oder Untermenues konfigurieren koennen.
- Funktion und fachliche Kategorie unabhaengig von der zugeordneten Ziffer
  halten: Ein Rezept bleibt ein Rezept, auch wenn sich seine Menue-Taste aendert.
- Im Adminbereich pro Menuepunkt Funktion, zugeordnete Taste und Aktivstatus
  bearbeiten. Doppelte aktive Belegungen innerhalb desselben Menues und
  ungueltige Eingaben vor dem Speichern ablehnen.
- Deaktivierte Punkte weder ansagen noch durch Tastendruck ausfuehren.
  Auch Eingaben waehrend der Begruessung, der AI-Rueckkehr und sonstige
  Tastenkurzwege muessen dieselbe aktive Belegung verwenden.
- IVR-Routing, Ansagen und Anrufbaum aus derselben Konfiguration ableiten.
  Im Anrufbaum die tatsaechliche Taste und den Aktivstatus darstellen;
  deaktivierte Punkte eindeutig als inaktiv kennzeichnen.
- Menueansagen bei Aenderungen passend zu den aktiven Punkten und Tasten
  erzeugen. Betroffene selbst aufgenommene Ansagen zur Anpassung kenntlich
  machen und bei der Aktivierung widerspruechliche Tastenanweisungen vermeiden.
- Vorhandene Belegungen bei der Migration uebernehmen. Das Deaktivieren eines
  Menuepunkts soll dessen Einstellungen fuer eine spaetere Reaktivierung
  erhalten. Zeit- und Verfuegbarkeitsregeln gelten auch bei geaenderter Taste.

Fuer die Umsetzung umbelegte und deaktivierte Tasten einschliesslich der
bisherigen Sonderfaelle `0`, `6` und Untermenue `5` pruefen. Leere Menues,
ungueltige beziehungsweise ausbleibende Eingaben und bestehende Fallbacks
muessen einen definierten Ablauf behalten. Die separat geplanten externen
Direktnummern werden unabhaengig von der IVR-Tastenbelegung konfiguriert.

## Geplant: Nebenstellen flexibel Rufgruppen zuordnen

Benutzerwunsch vom 17.11.2026; Teil der gesammelten Umsetzung, noch nicht
implementiert. Beispiel: Arbeitet eine MFA voruebergehend in einem ungenutzten
Sprechzimmer, soll dessen vorhandenes Telefon zur Telefoniegruppe hinzugenommen
werden koennen. Wird dort wieder behandelt, laesst es sich aus der Gruppe
herausnehmen.

Verbindliche Ergaenzung: Das Feature vor der Implementierung gemeinsam mit
der T2med-Middleware und der Kienzlefon-App abstimmen. Beide Schnittstellen,
Arbeitsplatzzuordnung, Status, Rechte, Schaltverhalten und Fehlerdarstellung
benoetigen einen gemeinsamen Vertrag. Zustaendigkeiten, offene Entscheidungen
und gemeinsame Abnahme stehen in der
[Rufgruppen-Abstimmung](RUFGRUPPEN-ABSTIMMUNG.md). Die Abstimmung ist damit
vorbereitet, noch nicht abgeschlossen.
Der App-Entwurf `ionos/docs/ABSTIMMUNG-NEBENSTELLENSTEUERUNG-2026-11-17.md`
ist einbezogen und um die Einzelrechte je Gruppe/Schaltrichtung sowie die
Unabhaengigkeit von der IVR-Tastennummer ergaenzt. Eine globale Freigabe fuer
die Fernbedienung ergaenzt diese Einzelrechte; sie ersetzt sie nicht. Ihre
Deaktivierung sperrt externe Aenderungen, erhaelt aber bestehende Zuordnungen
und die administrative Verwaltung.

Aktuell entstehen Queue-Mitglieder vor allem aus dem festen Bereich der
Praxis-Nebenstellen. Die Sonderqueue ergaenzt das aktivierte rote Telefon und
konfigurierte Zusatztelefone. Rufzyklen, Validierung und Installer-Pruefungen
setzen diese Zuordnung ebenfalls voraus; die neue Verwaltung muss diese
Stellen gemeinsam beruecksichtigen.

- Im Admininterface vorhandene Telefon-Nebenstellen mit Nummer, Bezeichnung
  beziehungsweise Raum und ihren Rufgruppenzugehoerigkeiten anzeigen.
- Nebenstellen je Rufgruppe einzeln hinzufuegen und herausnehmen koennen,
  insbesondere ein bisheriges Zusatz-/Sprechzimmertelefon in die Praxisqueue
  aufnehmen. Dafuer weder ein neues SIP-Konto noch eine Neuinstallation
  benoetigen; die Nebenstelle selbst wird beim Herausnehmen nicht geloescht.
- Eine dokumentierte, entsprechend den bestehenden Zugriffsregeln geschuetzte
  Schnittstelle zum Lesen und Aendern der Mitgliedschaften bereitstellen.
  Die T2med-Middleware soll diese ausdruecklich ohne Zugriff auf das
  Admininterface verwenden koennen. Adminoberflaeche und berechtigte Clients
  greifen auf dieselbe Verwaltung mit den jeweils erlaubten Aktionen zu.
  Wiederholtes Setzen desselben Zustands darf keine doppelten Eintraege oder
  unbeabsichtigten Wechsel erzeugen; keine blinde Umschaltoperation vorsehen.
- Aenderungen im laufenden Betrieb fuer nachfolgende Rufangebote wirksam
  machen, ohne angenommene Gespraeche zu unterbrechen. Den tatsaechlich
  uebernommenen Zustand anzeigen; fehlgeschlagene Aenderungen nicht als
  erfolgreich darstellen.
- Administrative Grundmitgliedschaften und Freigaben dauerhaft speichern
  und bei Update/Neukonfiguration erhalten. Gemaess der aktuellen
  Middleware-Abstimmung gelten Bedienaenderungen aus App/Middleware dagegen
  voruebergehend: Nach Anlagenneustart gelten wieder die Grundeinstellungen.
  Browser-/Middleware-Neustart setzt die Anlage nicht zurueck. Kienzlefax-Basis
  und Kienzlefon-Erweiterung duerfen die administrativen Vorgaben nicht
  gegenseitig ueberschreiben. Alte Bedienauftraege nicht erneut anwenden.
- Die Gruppen Normal und ROT unter `normal` und `specialist` unabhaengig
  abbilden; ROT ist die sichtbare Bezeichnung, unabhaengig von der IVR-Taste.
  Mitglieder nicht automatisch aus der normalen Gruppe in die Sondergruppe
  uebernehmen. Eine weitere
  Mitgliedschaft in der Sondergruppe muss separat erkennbar sein, auch wenn
  das Telefon aus der normalen Telefoniegruppe entfernt wird. Das Zusammenspiel
  mit dem bestaetigten Rottelefon-Fallback im Anrufbaum darstellen. Bestaetigt:
  Das ROT-Haekchen steuert das gemeinsame Klingeln. Ohne aktiviertes rotes
  Telefon beginnt dieses sofort; mit rotem Telefon nach dessen erfolglosem
  ersten Rufversuch. Dieser erste Versuch bleibt separat konfiguriert.
- Bestehende Rufstufen, Prioritaeten und Besetztbehandlung bei hinzugefuegten
  Telefonen beruecksichtigen. Das letzte konfigurierte Mitglied einer Gruppe
  darf nicht ausgeschaltet oder entfernt werden. Diese Pruefung bei der
  Aenderung gegen parallele Auftraege absichern; Besetzt-/Offline-Status ist
  kein Gruppenaustritt. Vorhandene Fallbacks fuer nicht erreichbare Mitglieder
  erhalten.

Praezisierung vom 17.11.2026: Status und delegierte Schaltrechte muessen
getrennt abgebildet werden, jeweils pro Kombination aus Nebenstelle und
Rufgruppe:

- Im Adminmenue festlegen, welche Mitgliedschaft die Middleware aktivieren
  beziehungsweise deaktivieren darf. Insbesondere das Deaktivierungsrecht
  fuer die normale Telefoniegruppe und fuer die Rufgruppe des roten Telefons
  (Sondergruppe) je Nebenstelle unabhaengig freigeben oder sperren. Die Rechte
  zum Aktivieren und Deaktivieren getrennt abbilden; so kann beispielsweise
  eine erneute Aktivierung erlaubt bleiben, waehrend das Abschalten gesperrt ist.
- Die Freigaben gelten fuer die betroffene Nebenstelle und Gruppe in App
  und Middleware-Telefonmenue; keine zusaetzliche Beschraenkung auf die eigene
  Arbeitsplatz-Nebenstelle einfuehren.
- Der autorisierten Middleware den aktuellen Mitgliedschaftsstatus sowie die
  erlaubten Aktionen und einen verstaendlichen Sperrgrund liefern. Eine
  gesperrte Aenderung macht den Status nicht unsichtbar. Mitgliedschaft und
  technische Erreichbarkeit/Besetztstatus des Telefons getrennt ausweisen.
- Freigaben serverseitig bei jedem Aenderungsauftrag fuer genau diese
  Nebenstelle, Rufgruppe und Aktion pruefen. Ein gesperrtes Deaktivieren auch
  bei direkten API-Aufrufen ablehnen und die Mitgliedschaft erhalten.
  Ausblenden oder Sperren eines Schalters in der Middleware allein reicht
  nicht aus. Gruppenaustritt und eine etwaige Pausierfunktion duerfen die
  Abschaltsperre nicht umgehen.
- Die Middleware darf Mitgliedschaften innerhalb ihrer Freigaben setzen,
  aber ihre Berechtigungen nicht selbst erweitern. Freigaben werden im
  Adminmenue verwaltet und zusammen mit den Mitgliedschaften bei Updates
  erhalten; fehlende Freigaben erlauben keine externen Aenderungen.
- Status nach Aenderungen neu auslesen koennen. Bei zwischenzeitlich
  geaenderten Freigaben oder Mitgliedschaften mit dem aktuellen Stand pruefen
  und Konflikte rueckmelden; fehlgeschlagene oder abgelehnte Auftraege duerfen
  nicht als erfolgreiche Umschaltung erscheinen.

Die vorhandenen AMI-Rechte wirken auf Aktionskategorien und setzen diese
feinen Regeln pro Nebenstelle/Rufgruppe nicht automatisch durch. Die geplante
Schnittstelle benoetigt daher eine zentrale Berechtigungspruefung; ein pauschal
erweitertes AMI-Schreibrecht fuer die Gruppenverwaltung ersetzt sie nicht.
Hier ist die Zugehoerigkeit zur Rufgruppe ROT gemeint: Sie klingelt ohne
rotes Telefon sofort und mit rotem Telefon als Fallback. Das Haekchen schaltet
weder das separate rote Telefon noch die zugehoerige Direktnummer global ab.

Abnahmefall: Sprechzimmertelefon hinzufuegen, Gruppenanruf dort annehmen,
waehrend des Gespraechs wieder aus der Gruppe nehmen und das Gespraech normal
beenden; danach keine neuen Rufangebote aus dieser Gruppe. Zusaetzlich
mehrfache Mitgliedschaften, wiederholte Aenderungsauftraege, Fehler bei der
Uebernahme sowie Erhalt der administrativen Vorgaben bei Update pruefen.
Nach Anlagenneustart muessen wieder die Grundeinstellungen gelten, ohne
alte temporaere Auftraege zu wiederholen; Browser-/Middleware-Neustart darf
die Anlage nicht zuruecksetzen. Konkreten API-Vertrag
und Zuordnung neuer Mitglieder zu den Rufstufen bei der Umsetzung festlegen.
Fuer die T2med-Middleware zusaetzlich Statuslesen ohne Adminsitzung, erlaubtes
Schalten, abgelehntes Deaktivieren trotz direktem API-Aufruf und unterschiedliche
Rechte fuer zwei Gruppen derselben Nebenstelle pruefen. Eine Aenderung von
Freigaben waehrend einer offenen Middleware-Ansicht muss wirksam werden.
Diese Faelle auch aus der Kienzlefon-App ueber die Middleware bis zur
tatsaechlichen Telefonanlage pruefen; Einzeltests einer Komponente ersetzen
die gemeinsame Abnahme nicht.

## Geplant: Anrufstatistik gemaess Middleware-Spezifikation

Benutzerauftrag vom 17.11.2026 fuer das gemeinsame Aenderungspaket.
Massgebliche Vorgabe ist `T2med-asterisk/docs/ANRUFSTATISTIK.md` im lokalen
Nachbarprojekt `kienzlefon-t2med`, zusammen mit dessen Referenz
`examples/asterisk-call-statistics.conf`. Dort sind Statistikverarbeitung,
API-Erweiterung und Tests bereits im lokalen Arbeitsstand vorbereitet.
Die benoetigten Ereignisse fehlen im hier geprueften Kienzlefon-Dialplan;
die gemeinsame Integration und Abnahme stehen noch aus.

- Jeden externen Telefoneingang genau einmal zaehlen, auch anonyme Anrufe,
  fruehe Abbrueche und wegen Kapazitaetsgrenzen abgewiesene Anrufe. Interne
  und ausgehende Anrufe sowie Faxwege erzeugen keinen neuen Eingang.
- Den Eingangsmarker an den tatsaechlichen externen Haupt-/Ueberlaufeingaengen
  in der eingebundenen `extensions-kfx-telefonie.conf` sowie an den direkten
  Queue- und Rottelefoneingaengen vor Kapazitaetspruefung, Annahme und Lookup
  setzen. Interne Funktionsnummern, Click-to-Dial und Vermittlung duerfen
  keinen neuen Eingangsmarker erzeugen. Die Trunk-Eingaenge bei der Abnahme
  auf der Anlage pruefen.
- Pro neuem externem Eingang eine zufaellige UUID v4 verwenden und zusammen
  mit stabiler Anlagenkennung und urspruenglicher Unix-Eingangszeit ueber
  `__KF_STATS_*` an Folgekanäle vererben. Wiederholte Hooks behalten die
  vorhandene Kennung. Telefonnummer, Anzeige-ID und Linkedid sind keine
  Statistikkennung.
- AMI-UserEvents `KienzlefonCallEntered` und `KienzlefonCallRoute` gemaess
  Schema 1 mit `PbxId`, `CallId`, `EnteredAt` und gegebenenfalls `Route`
  erzeugen. Verfuegbarkeit von `UUID()`, `UserEvent` und AMI-Leserecht `user`
  im Installer pruefen; Anlagenkennung mit der Middleware abstimmen und bei
  Updates erhalten. Die Telefonie darf nicht auf die Middleware warten.
- Die fachlichen Wege `ivr`, `ai`, `queue`, `prescription`, `referral`,
  `appointment`, `callback`, `other`, `opening_hours`, `pharmacy` und
  `specialist` an der jeweils gewaehlten/erreichten Stelle markieren.
  `ai` erst bei erreichter AI-Verbindung zaehlen, nicht bei abgewiesenem
  Versuch. Direkte Queue-Zugaenge und automatische Fallbacks einbeziehen.
  Die IDs bleiben bei geaenderter IVR-Tastenbelegung gleich; deaktivierte
  Menuepunkte erzeugen durch ungueltige Tastendruecke keinen Wegeeintrag.
- Ein Anruf kann mehrere Wege haben, aber jeden Weg nur einmal. Eingang und
  spaetere Wege dem urspruenglichen Eingangstag in `Europe/Berlin` zuordnen,
  einschliesslich Zeitumstellung. Ein gueltiger Wegeeintrag darf einen
  verpassten Eingang anhand der urspruenglichen Zeit ergaenzen.
- Die Middleware bleibt fuer SQLite-Zaehler und die Ausgabe unter
  `GET /api/v1/telephony` mit `call_statistics.today` zustaendig. Die App
  verwendet diese Werte mit Wegeaufschluesselung und Anzahl ohne erfassten
  Weg. `complete`, `partial` und `unavailable` sowie veraltete Werte korrekt
  darstellen; fehlende Erfassung ist keine gemessene Null. Keine eigene
  Zaehlung aus Browseraktionen oder JSON-Vorgaengen einfuehren.
- Keine Rufnummern, Patientendaten oder Gespraechsinhalte in der Statistik
  speichern. Statistikdaten bei FHIR-Import und Updates erhalten. Die
  Spezifikation sieht zunaechst keine automatische Loeschung technischer
  Zaehlschluessel vor; eine spaetere Frist muss Wiederholungen und noch aktive
  Anrufe beruecksichtigen. Erfassungsluecken bleiben als solche gekennzeichnet.

Gemeinsame Abnahme: Hauptanschluss und beide Direktnummern, anonyme/frueh
abgebrochene/kapazitaetsbedingt abgewiesene Anrufe, Ausschluss interner und
ausgehender Anrufe sowie Fax, Mehrfachmarker und mehrere Wege, AI-Erfolg und
AI-Fallback, umbelegte/deaktivierte IVR-Punkte, Tageswechsel/Zeitumstellung,
AMI-Unterbrechung und Wiederanlauf sowie Speicherfehler. Vorhandene
Middleware-Tests gezielt einbeziehen; echte Dialplan-Ereignisse separat pruefen.

## Vorgemerkt: datensparsame Audioaufbewahrung

Der Installer fragt bei Installation, Update und Neukonfiguration
nach lokaler Ablage in der Praxis oder verschluesselter Ablage zur
Abholung. Bei verschluesselter Ablage wird ein lokaler Abholer in der
Praxis eingerichtet. In beiden Faellen fragt der Installer separat
nach Audio-Beilage oder nur JSON.

Beigefuegte WAVs liegen dauerhaft ausschliesslich im Begleitverzeichnis
des Vorgangs in der Inbox. Ab dort verwaltet die App die
Aufbewahrung und Loeschung. Nach **Fertig** bleiben vorhandene WAVs
abspielbar. Der Papierkorb enthaelt die JSON. Die App loescht beim
Verschieben dorthin alle zugehoerigen WAVs.

Ohne Audio-Beilage bereinigt Kienzlefon die WAVs nach erfolgreicher
Erkennung und gesicherter JSON-Ausgabe. Bei Audio-Beilage sind Paket,
Fehler-JSON und Quellbereinigung im
[Audiovertrag v1](vorgang-v1/AUDIO.md)
beschrieben. Bei Erkennungs- oder Ausgabefehlern bleibt ein erneuter
Verarbeitungsversuch moeglich. Details zum App-Ablauf stehen in der
[Uebergabe zur App](UEBERGABE-KIENZLEFON-APP-2026-11-18.md).

## Geplant: kienzledoku-Commander mit lokalem CPU-Whisper-Fallback

Benutzerwunsch vom 17.11.2026; Teil der gesammelten Umsetzung fuer die naechste
Version, noch nicht implementiert.

- Bei Installation, Update und Neukonfiguration eine optionale Anbindung an
  einen vorhandenen kienzledoku-Commander anbieten und dessen IP-Adresse
  abfragen. Vorhandene Einstellungen als Vorgaben anzeigen und unveraendert
  uebernehmen koennen; eine bisherige Anbindung nicht stillschweigend entfernen.
- Den Commander bei eingerichteter Verbindung bevorzugt fuer die
  Spracherkennung verwenden. Ohne Commander lokal mit CPU-Whisper arbeiten.
- CPU-Whisper einschliesslich aller benoetigten lokalen Modelle immer
  installieren beziehungsweise erhalten und auf Betriebsbereitschaft pruefen.
  Die Commander-Auswahl darf den lokalen Fallback nicht abwaehlen oder einen
  Modelldownload erst beim Ausfall erforderlich machen.
- Bei Nichterreichbarkeit, Verarbeitungsfehlern oder ueberschrittenem
  Warte-/Verarbeitungszeitlimit automatisch denselben Audioblock lokal
  transkribieren. Auch ein beschaeftigter Commander darf die Verarbeitung
  nicht unbegrenzt aufhalten. Bei spaeteren Auftraegen die Commander-Verbindung
  wieder pruefen; einen Ausfall nicht bei jedem Feld durch lange Wartezeiten
  vervielfachen.
- Audio bis zum erfolgreichen Ergebnis beziehungsweise der definierten
  Fehlerbehandlung dem Vorgang zugeordnet halten. Pro Feld genau ein Ergebnis
  uebernehmen; verspaetete Remote-Ergebnisse duerfen keine doppelte
  JSON-Ausgabe erzeugen. Die geplante vorgangsbezogene Audiobereinigung gilt
  auch fuer diesen Weg; keine zusaetzliche dauerhafte Audioablage vorsehen.

Die lokal vorhandenen Commander-Quellen bieten bereits
`POST /v1/asr/final-block` fuer Multipart-Audio (`file`, optional `language`)
und `GET /health` beziehungsweise `GET /v1/runtime/status` fuer Statusabfragen.
Standardport ist `8185`; eine abweichende Port-/URL-Konfiguration soll moeglich
sein. Ein Bearer-Token ist nur bei entsprechend aktivierter Commander-
Authentifizierung erforderlich und dann geschuetzt zu hinterlegen.
Ein erfolgreiches `/health` allein bedeutet nicht, dass das ASR-Modell gerade
bereit ist: Geplante GPU-Pausen koennen ebenfalls HTTP 200 liefern.

Bei der Umsetzung die Antwortpruefung, feldabhaengige Erkennung fuer Namen
und Medikamente sowie geeignete Zeitlimits mit der Commander-Schnittstelle
abgleichen. Den lokalen Fallback und die Wiederaufnahme der Remote-Nutzung
mit simulierten Verbindungsfehlern, ungueltigen Antworten und Zeitueberschreitungen
pruefen. Es wurde bisher nur die vorhandene Schnittstelle im Quellcode geprueft,
keine Verbindung zu einem Server hergestellt.

## Kienzlefax

### Geplant: gemeinsame Provider-Vorlagen und voip2gsm

Planungsstand 17.11.2026: Teil der gesammelten Umsetzung fuer die naechste
Version; die Feature-Besprechung ist noch nicht abgeschlossen.

Anbieterprofile und Provider-Vorlagen sollen zentral in Kienzlefax gepflegt
werden. Dazu gehoeren Registrar, Proxy, Transport, Registrierung,
Authentifizierung, AOR, Endpunkt, Zuordnung eingehender Anrufe und das vom
Anbieter erwartete Rufnummernformat. Dies gilt auch fuer Fonial/Plusnet und
voip2gsm. Kienzlefon verwendet die bereitgestellten Providerdaten und setzt
die Formatvorgabe nach seiner Wahlberechtigungspruefung um. IVR, Ansagen,
Wahlregeln und die Kienzlefon-spezifischen Gespraechsablaeufe bleiben hier.
Die konkrete Uebergabe der Formatvorgabe ist vor der Umsetzung abzustimmen;
parallel gepflegte Provider-Vorlagen in beiden Projekten sind nicht das Ziel.

[Issue #2: Anbieter VOIP2GSM zur Auswahl hinzufuegen](https://github.com/thomaskien/kienzlefon/issues/2)
ist in das gemeinsame Aenderungspaket aufgenommen:

- Kienzlefax-Providerprofil fuer `b.vsip.eu`, einschliesslich Registrierung,
  passender Eingangszuordnung und getrennter Fax-/Telefon-Endpunkte.
- Nationale ausgehende Ziele ueber das bereits beigetragene SIP-Zielformat
  `national`; weitere Formatvarianten mit dem Providerprofil abstimmen.
- Eingehende Zielrufnummern mit und ohne fuehrendes `+` in der Kienzlefax-Basis
  auf dieselbe konfigurierte Rufnummer abbilden, bevor zu Fax oder Telefon
  verteilt wird.
- Providerfehler wie `404 Invalid phone number` in der Diagnose erkennbar machen.
- Vorlagen und generierte Konfiguration bei Updates erhalten; den im Issue
  beschriebenen fehlenden Fax-Endpunkt bei manueller Einrichtung beruecksichtigen.

Die vorlaeufig unter `config/pjsip-fonial.conf.example` abgelegte Fonial-Vorlage
ist die Referenz fuer die spaetere Integration in Kienzlefax. Es wurden bisher
keine Provider- oder Laufzeitkonfigurationen umgestellt.

### Geplant: direkte Rufnummern fuer Warteschlange und rotes Telefon

Benutzerwunsch vom 17.11.2026 fuer das gemeinsame Aenderungspaket:
Eine eigene externe Rufnummer soll ohne Zeitbeschraenkung direkt in die
Praxiswarteschlange fuehren. Zusaetzlich soll eine eigene externe Rufnummer
fuer den Rufweg ROT einrichtbar sein.

Im aktuellen Code sind beide Varianten bereits als optionale SIP-Leitungen
vorhanden: `[sip_direkte_queue]` und `[sip_rotes_telefon]`. Die Beispielkonfiguration
deaktiviert beide. Die direkten Eingangskontexte umgehen IVR und Zeitpruefungen;
die gemeinsame Kanalbegrenzung bleibt wirksam. Die Queue-Direktnummer fuehrt
nach `kfx-phone-queue`. Die Rot-Direktnummer ruft zuerst das rote Telefon und
wechselt bei Nichtannahme oder Besetzt wie der Fachstellenweg in die Sonderqueue.
Ob konkrete externe Nummern auf einem produktiven Server eingerichtet sind,
wurde nicht geprueft. Intern erreicht `8802` bereits direkt die Praxisqueue.

Fuer die gemeinsame Umsetzung festhalten:

- Beide externen Direktnummern unabhaengig und optional einrichtbar machen.
  Der geplante Rufweg ROT funktioniert auch ohne separates rotes Telefon;
  dann fuehrt er unmittelbar zum gemeinsamen Klingeln der ROT-Mitglieder.
- Zeitunabhaengigen Zugang zur Warteschlange erhalten, auch ausserhalb der
  Oeffnungs-/Telefonzeiten und bei aktiver zeitlicher Sperre im normalen IVR.
- Provider-Anbindung gemaess der gemeinsamen Planung in Kienzlefax pflegen;
  Zielzuordnung und Kienzlefon-Gespraechsablaeufe abstimmen. Vorhandene
  Direktnummern bei der Umstellung uebernehmen.
- Bei jeder Installation, jedem Update und jeder Neukonfiguration ausdruecklich
  abfragen, ob die Direktnummern eingerichtet oder geaendert werden sollen.
  Dies gilt auch beim Wiederverwenden einer bestehenden Konfiguration; diesen
  Fall ueberspringt der bisherige Installer. Beide Direktnummern anbieten,
  vorhandene Werte als Vorgaben verwenden und bei unveraenderter Uebernahme
  erhalten. Eine Entfernung muss ausdruecklich ausgewaehlt werden.
- Die geplante Eingangsnormalisierung mit/ohne `+` auch fuer Direktnummern
  beruecksichtigen.
- Bestaetigter Ablauf der ROT-Direktnummer: Mit aktiviertem rotem Telefon
  zuerst dieses allein rufen; bei Nichtannahme nach der eingestellten
  Klingeldauer oder bei Besetzt/Nichterreichbarkeit gemeinsam die aktiven
  ROT-Mitglieder laeuten lassen. Ohne rotes Telefon beginnt dieses gemeinsame
  Klingeln sofort. Das rote Telefon klingelt in der Gruppe nur mit, wenn es
  dort Mitglied ist. Keine automatische Uebernahme normaler Gruppenmitglieder.

Fuer die Umsetzung insbesondere die erneuten Installer-Abfragen mit bestehender
Konfiguration sowie den Wechsel vom exklusiven Rottelefon-Versuch zum
gemeinsamen Klingeln pruefen.

Der vorhandene Regressionstest fuer Registrierung und direkte DID-Routen
(`test_direct_numbers_get_registration_and_capacity_routes`) wurde erfolgreich
ausgefuehrt. Laufzeitverhalten und produktive Konfiguration wurden nicht geaendert.

### Bestehende Einbindung

Die Hauptleitung bleibt die von Kienzlefax registrierte Telefonnummer. Der
Kienzlefax-Kontext reserviert vor dem IVR atomar die globale Provider- und
Telefoniekapazitaet. Kienzlefon ersetzt nur den bekannten Uebergang von diesem
Kontext zur Queue durch den Uebergang zum IVR.

Taste 1 und Taste 8 enden in derselben unveraenderten Queue `praxis`. Taste 8
setzt zusaetzlich `QUEUE_PRIO`, initialisiert wie Kienzlefax
`QUEUE_RAISE_PENALTY=0` und verwendet eine nur fuer den Mitarbeiter hoerbare
`announceoverride`-Ansage. Damit koennen die bestehenden progressiven
Kienzlefax-Penalty-Regeln die freigegebenen Mitglieder wieder stufenweise
hinzunehmen.

Das rote Telefon ist optional und bleibt ein eigener PJSIP-Endpunkt. Kienzlefon
erzeugt getrennt von `praxis` die priorisierte Ringall-Sonderqueue
`kienzlefon-sonder`. Zur Anfangsbesetzung gehören die normalen Queue-Telefone, ein aktiviertes rotes Telefon und die ausgewählten Zusatztelefone, jeweils mit Penalty `0`. Bei aktiver Rufgruppenverwaltung klingeln die aktuell in ROT angemeldeten Mitglieder. Ohne rotes Telefon fuehrt Taste 9 direkt dorthin. Mit rotem Telefon
erfolgt zuerst der exklusive Waehlversuch. Nach standardmaessig 20 Sekunden oder
bei besetzt beziehungsweise nicht erreichbar folgt die Sonderqueue. Gehört das rote Telefon zu ROT und ist erreichbar, klingelt es in der Gruppe erneut. Ein hoeheres Queue-Gewicht gibt der Sonderqueue bei gemeinsam genutzten
Mitgliedern Vorrang.

Direkte externe Queue- und Rottelefonnummern sind optional. Auch deren
eingehende und ausgehende Kanaele verwenden den gemeinsamen
`kfx_external_capacity`-Guard.

Vor der Anzeige an internen Telefonen normalisiert ein AGI extern eingehende
deutsche E.164-Rufnummern in das nationale Format und auslaendische Nummern in
das Format mit `00`. Die im IVR vor dieser Anzeigeanpassung gelesene Caller-ID
bleibt als unveraenderte `id` fuer Telepraxis erhalten. Konfigurierte interne
Nebenstellen werden von der Normalisierung ausgenommen.

Zusaetzliche interne PJSIP-Endpunkte liegen wie das rote Telefon ausserhalb
der Queue. Exakte interne Nebenstellen werden vor externen Wahlmustern
ausgewertet. Unbekannte Nummern ab drei Ziffern laufen ueber
`kienzlefon-wahlpruefung`; erst nach Freigabe folgt der gemeinsame
Kapazitaetsguard und danach der Providerkanal. Gesperrte Wahlen belegen somit
keinen externen Kanal.
