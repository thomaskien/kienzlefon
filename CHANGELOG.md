<!--
kienzlefon
Version: 1.9.2
Changelog:
- 1.9.2: Abbruch bestehender Nicht-Demo-Installationen bei der Updateabfrage korrigiert.
- 1.9.1: Falschnegative Asterisk-wav16-Pruefung des Installers korrigiert.
- 1.9: Optionale Anonymisierung der Anrufernummern in Demoausgaben ergaenzt.
- 1.8.3: Leere Einzelfelder ohne Abbruch nachfolgender Transkriptionen verarbeitet.
- 1.8.2: Bereitschaftsdienst-Zeitlogik und gesprochene Ansagetexte korrigiert.
- 1.8.1: Gruppen-Schreibrecht der Telepraxis-Ausgabedateien korrigiert.
- 1.8: Gewarnten Demomodus und Bereinigung vollstaendig leerer Abbrueche ergaenzt.
- 1.7.1: Aktiviertes rotes Telefon als Mitglied der Sonderqueue ergaenzt.
- 1.7: Sonderqueue, Queue-Penalty-Fix und eingehende Caller-ID-Anzeige umgesetzt.
- 1.6.2: Falschpositive IVR-Fehler bei normalem Auflegen nach Aufnahmen korrigiert.
- 1.6.1: Falschnegative FFmpeg-loudnorm-Pruefung des Installers korrigiert.
- 1.6: Feldabhaengige Whisper-Modellwahl und Initial-Prompts umgesetzt.
- 1.5: 16-kHz-Ansagenaufnahme, Signalton und Lautheitsnormalisierung umgesetzt.
- 1.4: PIN entfernt und Sprachfuehrung des Ansagen-IVR korrigiert.
- 1.3: Interne Ansagenverwaltung, Zusatztelefone und Wahlregeln umgesetzt.
- 1.2: Zeitkonfiguration und Zeitansagen korrigiert.
- 1.1: Freigegebene TTS-, IVR-, Transkriptions- und Installeranpassungen umgesetzt.
- 1.0: Erstfassung des projektweiten Changelogs.
-->

# Changelog

## 1.9.2

- bestehende Nicht-Demo-Konfigurationen ueberspringen die Demo-Anonymisierungsabfrage mit Rueckgabestatus `0`
- der Installer setzt danach Verzeichnis-, Modell-, Ansagen-, Asterisk- und Worker-Installation regulaer fort
- bestehende Demo-Konfigurationen fragen die optionale Anonymisierung weiterhin mit dem bisherigen Wert als Vorgabe ab
- Laufzeittests decken beide Updatezweige ab

## 1.9.1

- Asterisk-Formatliste wird vor der Suche nach `wav16` vollstaendig eingelesen
- kein falschnegativer Installer-Abbruch mehr durch `grep -q` in Verbindung mit `pipefail`
- der Installer erreicht dadurch wieder die Installation und den Neustart des Whisper-Workers
- bei aktivierter Demo-Anonymisierung verwendet der neu gestartete Worker die aktuelle TOML-Konfiguration und ersetzt `id` und `telefon` wie vorgesehen

## 1.9

- neue TOML-Option `[telepraxis].anrufernummern_anonymisieren`
- ausschliesslich im Demomodus aktivierbar; Produktivausgaben bleiben unveraendert
- ersetzt in normalen und Fehler-Demo-JSONs die Felder `id` und `telefon` durch `#anonymisiert demo#`
- veraendert weder interne Spooldaten noch Audiodateien oder Rufnummern innerhalb von Freitexten
- Installer fragt die Option bei neuen Demo-Installationen ab
- bei Ueberinstallation einer bestehenden Demo-Konfiguration wird die Option ebenfalls mit dem bisherigen Wert als Vorgabe abgefragt
- Migration ergaenzt den fehlenden Wert konservativ als `false`, ohne vorhandene Einstellungen zu ueberschreiben

## 1.8.3

- Vorname, Nachname, Geburtsdatum und gegebenenfalls Rueckrufnummer werden auch nach einem schweigend uebersprungenen Feld weiter abgefragt
- das anschliessende Vorgangsfeld wird unabhaengig von fehlenden Personendaten aufgenommen
- leere Einzelaufnahmen und leere Whisper-Transkripte gelten als fehlendes Feld, nicht als technischer Fehler
- jede vorhandene Aufnahme wird der Reihe nach verarbeitet; ein leeres Feld blockiert keine spaetere Transkription
- das normale Telepraxis-JSON enthaelt alle erkannten Inhalte und laesst nicht genannte Felder leer
- fuer schweigend uebersprungene Felder entstehen keine wiederholten Fehlerdatensaetze

## 1.8.2

- Bereitschaftsdienst-Hinweis wird auch vor der ersten Oeffnungszeit des Tages gesprochen
- zwischen zwei Oeffnungsbloecken, insbesondere in der Mittagspause, bleibt der Hinweis aus
- nach der letzten Oeffnungszeit und an vollstaendig geschlossenen Tagen bleibt er aktiv
- `112` wird als `eins eins zwei` gesprochen
- `116117` wird als `eins eins sechs, eins eins sieben` gesprochen
- beide Fallback-Ansagen verwenden `Geburtstag` statt `Geburtsdatum`
- bestehende exakt alte Standardtexte werden migriert; eigene Texte bleiben erhalten

## 1.8.1

- Telepraxis-Ausgabedateien werden vor dem atomaren Umbenennen mit Modus `0660` versehen
- bei Root-Ausfuehrung erhalten sie Eigentumer `root` und die Gruppe des Ausgabeverzeichnisses
- bereits vorhandene gueltige Zieldateien werden bei erneutem Zugriff ebenfalls auf `0660` korrigiert
- Worker-`Group` wird aus der Gruppe des Ausgabeverzeichnisses erzeugt
- systemd-Worker verwendet zusaetzlich `UMask=0007`
- interne Spool-, Konfigurations- und Verwaltungsdateien behalten ihre bisherigen restriktiven Rechte

## 1.8

- Installer fragt bei einer neuen oder vollstaendig neu konfigurierten Installation nach dem Demo-Modus
- doppelte Warnung vor unverschluesselter Ablage und ausdrueckliche Bestaetigung erforderlich
- Demo-Modus fragt keinen Telepraxis-Public-Key ab und schreibt regulaere sowie Fehlerdatensaetze atomar als Klartext-`.json`
- Produktivmodus bleibt Standard und schreibt weiterhin ausschliesslich verschluesselte `.json.enc`
- Updates bestehender Konfigurationen erhalten automatisch `demo = false`, ohne vorhandene Werte zu ueberschreiben
- Auflegen vor jeder verwertbaren Aufnahme verwirft den leeren Vorgang vollstaendig
- vorhandene Audiodaten und technische Fehler werden weiterhin immer eingereiht und ausgegeben

## 1.7.1

- aktiviertes rotes Telefon ist mit Penalty `0` Mitglied der Sonderqueue
- nach dem exklusiven 20-Sekunden-Versuch kann es gemeinsam mit allen anderen Mitgliedern weiterklingeln
- bei besetztem oder nicht verfuegbarem roten Telefon klingeln die uebrigen Sonderqueue-Mitglieder sofort
- ohne aktiviertes rotes Telefon wird weiterhin kein Rottelefon-Mitglied erzeugt

## 1.7

- Installer fragt ausdruecklich, ob ein rotes Telefon verwendet wird
- eigene priorisierte Ringall-Sonderqueue mit allen normalen Queue-Telefonen
- optionale Auswahl bekannter Zusatznebenstellen fuer die Sonderqueue
- Taste 9 geht ohne rotes Telefon direkt in die Sonderqueue
- besetztes, unerreichbares oder nicht angenommenes rotes Telefon faellt in die Sonderqueue
- bestehende Kienzlefax-Queue `praxis` und ihre Konfiguration bleiben unveraendert
- Taste 8 initialisiert `QUEUE_RAISE_PENALTY=0`, damit Kienzlefax-Penalty-Regeln wieder wirken
- deutsche eingehende Rufnummern werden an allen Telefonen national mit fuehrender Null angezeigt
- auslaendische eingehende Rufnummern werden mit `00` angezeigt
- Telepraxis-Vorgaenge behalten die urspruenglich uebertragene Caller-ID
- fehlende 1.7-TOML-Werte werden bei Updates ohne Ueberschreiben vorhandener Werte ergaenzt
- Zusatznebenstellen- und Sonderqueue-Auswahl aktualisieren TOML atomar und zeilenweise

## 1.6.2

- AGI-Antwort `511 Command Not Permitted on a dead channel` gilt als regulaerer Hangup
- vorhandene Aufnahmen werden beim unmittelbaren Auflegen weiterhin normal eingereiht
- kein zusaetzlicher `kienzlefon_error` vom Typ `IVR_ERROR` fuer diesen Abschlussweg
- andere unerwartete AGI-Antworten bleiben technische Fehler

## 1.6.1

- FFmpeg-Filterliste wird vor der Auswertung vollstaendig eingelesen
- kein falschnegativer `loudnorm`-Fehler mehr durch `grep -q` und `pipefail`
- ein tatsaechlich fehlender oder nicht abfragbarer Filter bleibt ein Installationsfehler

## 1.6

- getrennte TOML-Modellwahl fuer Namen, Medikamente und alle uebrigen Aufnahmen
- `large-v3` als Standardwahl fuer Vor- und Nachnamen
- `large-v3-turbo` als Standardwahl fuer Medikamente und sonstige Felder
- editierbare Initial-Prompts fuer Vorname, Nachname sowie Medikamente und Wirkstoffe
- Vor- und Nachnamen werden mit deutscher Transkription und `beam_size=5` verarbeitet
- jedes unterschiedliche konfigurierte Modell wird einmal geladen und dauerhaft gehalten
- Worker-Heartbeat und Status melden die vollstaendige konfigurierte Modellmenge
- kein stiller Modell-Fallback bei Lade- oder Transkriptionsfehlern
- Installer fragt alle drei Modellbereiche getrennt ab und erklaert Geschwindigkeit und Eignung
- RAM-Erkennung mit Warnung und ausdruecklicher Freigabe fuer zwei Modelle unter 16 GB
- konservative Migration des bisherigen `[whisper].modell` nach `modell_standard`
- Installer laedt jede unterschiedliche konfigurierte Modellvariante

## 1.5

- telefonische Ansagenaufnahmen verwenden Asterisks echtes `wav16`-Format
- Signalton unmittelbar vor Beginn einer neuen Ansagenaufnahme
- Patienten- und Datenaufnahmen bleiben weiterhin signaltonfrei
- Kandidaten werden vor der Vorschau als Mono-PCM mit 16 kHz aufbereitet
- gemeinsame zweistufige FFmpeg-Lautheitsnormalisierung für manuelle und Piper-Ansagen
- Standardziel `-19 LUFS` und maximaler True Peak `-2 dB`
- Lautheitswerte zentral und menschenlesbar unter `[tts]` konfigurierbar
- Vorschau verwendet bereits die normalisierte Fassung
- ältere manuelle `.wav`-Ansagen bleiben kompatibel und werden bei Aktivierung archiviert
- Aktivierung und Rückschaltung sichern `.wav16` und `.wav` gemeinsam gegen Fehler ab

## 1.4

- unzulässige PIN-Abfrage vollständig aus Ansagen-IVR, TOML und Installer entfernt
- Nebenstelle `777` bleibt ausschließlich aus internen Telefonkontexten erreichbar
- „Override“ in gesprochenen Texten durch „Feiertags- und Sonderansage“ ersetzt
- Haupt-, Auswahl-, Aktions- und Sonderansagenmenü sprachlich präzisiert
- fehlende Eingabe wiederholt nach fünf Sekunden unbegrenzt das jeweilige Menü
- keine Trennung aufgrund ausbleibender Menüeingaben
- eigener Hinweis, wenn noch keine neue Aufnahme vorliegt
- Update ersetzt nur unveränderte 1.3-Standardtexte und erhält individuelle Texte
- nicht mehr verwendete generierte PIN-Ansagen werden entfernt

## 1.3

- internes, PIN-geschuetztes Ansagen-IVR auf Nebenstelle `777`
- stabile Ansagenummern mit Aufnahme, Vorschau, Aktivierung und Piper-Rueckschaltung
- Override-Steuerung mit optionaler Sperrung der Telefonzeiten und Statusansage
- vorherige manuelle Ansagen bleiben als inaktive WAV-Dateien erhalten
- optionale, fortlaufende PJSIP-Nebenstellen nach dem roten Telefon ausserhalb der Queue
- normale ausgehende Telefonie fuer rotes Telefon und Zusatztelefone
- deutsche Normalisierung unbekannter Rufnummern ab drei Ziffern
- internationale Ziele sowie `0900`, `0137`, `118` und `019` standardmaessig gesperrt
- `0180`, `0700` und `032` konfigurierbar und standardmaessig freigegeben
- `110`, `112`, `116116` und `116117` bleiben von Sperren ausgenommen
- gesperrte Ziele werden angesagt und ohne Providerkanal im Audit protokolliert
- konservative Update-Migration fehlender 1.3-TOML-Werte
- gemeinsame Telefonzeit-Ansage fuer ein geschlossenes Wochenende
- keine zusaetzliche Pause zwischen Feldansage und Aufnahme

## 1.2

- eingegebene Zeitprofile werden nach dem Schreiben aus TOML zurueckgelesen
- Update fragt separat, ob bestehende Zeitprofile neu konfiguriert werden sollen
- gemeinsame Vormittagsoeffnung Montag bis Freitag wird einmal abgefragt
- Nachmittagszeiten Montag bis Freitag werden einzeln erfasst
- identische Telefonzeiten Montag bis Freitag werden einmal abgefragt
- Samstag und Sonntag bleiben separat konfigurierbar
- Telefonzeiten werden bei Gleichheit als `werktäglich` zusammengefasst
- leeres Wochenende wird als geschlossene Praxis zusammengefasst
- Apotheken- und Fachstellenzeiten kopieren standardmaessig die Oeffnungszeiten

## 1.1

- `[tts].length_scale` mit Standardwert `1.3` ergaenzt
- `[tts].sentence_silence` mit Standardwert `0.8` ergaenzt
- exakte Pausenmarker im Format `{pause:800}` ergaenzt
- `{praxisname}` wird in allen Ansagetexten ersetzt
- manuelle WAV-Ueberschreibungen werden deutlich gemeldet
- neue IVR-Einleitungsansage und konfigurierbare Zwischenpause
- Aufnahmen starten ohne Signalton
- nach einer fertigen Aufnahme: „Vielen Dank und bis bald!“, danach Auflegen
- abschliessender Whisper-Punkt wird aus den Datenfeldern entfernt
- rotes Telefon faellt nach 20 Sekunden mit Queue-Prioritaet 100 zurueck
- Installer zeigt Version 1.1 und verlangt vor Aenderungen eine Bestaetigung
- Installer fragt alle neuen Werte ab und dokumentiert das Zeitformat eindeutiger
- Benutzer- und Rechteermittlung des angepassten Installers bleibt erhalten

## 1.0

- Kienzlefax-kompatibler Installer und Asterisk-Dialplan
- konfigurierbares IVR mit Oeffnungs-, Telefon- und Override-Zeiten
- strukturierte Einzelaufnahmen mit Stille-, DTMF- und Hangup-Abschluss
- dauerhafter Whisper-Worker mit `large-v3-turbo`
- atomarer JSON-/WAV-Ordnerspool
- OpenSSL-kompatible verschluesselte Telepraxis-Dateiausgabe
- verschluesselte Fehlerausgabe ohne stille Fehlerpfade
- lokale, erneut erzeugbare Piper-Ansagen
- separates rotes Telefon und optionale direkte Provider-Rufnummern
