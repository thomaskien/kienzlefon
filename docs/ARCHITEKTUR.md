<!--
kienzlefon
Version: 1.9.2
Changelog:
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

Vor- und Nachnamen werden mit `language="de"`, `task="transcribe"`,
`beam_size=5` und ihrem jeweiligen editierbaren Initial-Prompt transkribiert.
Medikamente besitzen einen eigenen Prompt, der Medikamentenname oder Wirkstoff,
Wirkstaerke und Packungsgroesse beschreibt. Die Modellwahl folgt ausschliesslich
dem bereits strukturierten Feldtyp des Transkriptionsauftrags.

`kienzlefon-ansagen` erzeugt aus den TOML-Texten lokale Piper-Master-WAVs und
die Asterisk-Formate. CLI und ein spaeteres Webinterface verwenden dieselbe
Erzeugungslogik. Eine gleichnamige menschliche WAV-Datei im konfigurierten
Upload-Verzeichnis hat Vorrang vor Piper.

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
Piper-Quellen angewandt. Erst danach entstehen G.722, A-law und mu-law.

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
gesichert und per `os.replace` aktiviert. Auf dieselbe Weise wird die fertige
`*.json.enc`-Produktivdatei oder unverschluesselte `.json`-Demodatei geschrieben.
Eine aktivierte Demo-Anonymisierung arbeitet ausschliesslich auf einer Kopie des
fertigen Ausgabe-Payloads und ersetzt dort `id` und `telefon`. Die internen
Vorgangsdaten und produktive Ausgaben werden nicht veraendert.
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

## Kienzlefax

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
`kienzlefon-sonder`. Sie enthaelt alle normalen Queue-Telefone, ein aktiviertes
rotes Telefon sowie die im Installer ausgewaehlten Zusatztelefone jeweils mit
Penalty `0`. Ohne rotes Telefon fuehrt Taste 9 direkt dorthin. Mit rotem Telefon
erfolgt zuerst der exklusive Waehlversuch. Nach standardmaessig 20 Sekunden oder
bei besetzt beziehungsweise nicht erreichbar folgt die Sonderqueue. Ist das rote
Telefon dann verfuegbar, klingelt es dort gemeinsam mit allen anderen Mitgliedern
erneut. Ein hoeheres Queue-Gewicht gibt der Sonderqueue bei gemeinsam genutzten
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
