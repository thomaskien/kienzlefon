<!--
kienzlefon
Version: 2.7

- 2.4.4: G.722-Fix fuer KI-Endpunkte in Installation und Updates dauerhaft uebernommen.
- 2.4.3: Separate Kokoro-Python-Laufzeit fuer Systeme mit Python 3.13 ergaenzt.
- 2.4.2: Zahlen und Uhrzeiten vor der Spracherzeugung deutsch ausschreiben.
- 2.4.1: Kokoro-Thorsten als Standard fuer lokale Ansagen ergaenzt.
- 2.4.0: Integriertes Webinterface, Anrufsbaum, Ansagenmodi und Notfall-Handoff freigegeben.
- 2.3.2: Sofortige AI-Medienbridge korrigiert und obsolete Hauptserver-Ansage entfernt.
- 2.3.1: Eingangs- und Menuephase ohne DTMF-Eingabe korrigiert.
- 2.3: Sicheren AI-Handoff, Call-Policy, Assistentenansage und DTMF-Rueckkehr integriert.
- 2.2: Push-basierten AI-Admission-Listener und freigemeldete KI-Nebenstellen integriert.
- 2.1.2: Passwortloser WireGuard-Zugriff bleibt nach einem Systemneustart erhalten.
- 2.1.1: Hauptinstaller bietet Installation oder Aktualisierung des Webinterfaces immer an.
- 2.1: Gezielte neue Qwen-Varianten und WireGuard-KI-Client ergaenzt.
- 2.0: Lokales Qwen3-TTS, globale Sprecherwahl und differenzielle Ansagenerzeugung ergaenzt.
Changelog:
- 1.9.3: Unterdrueckung vollstaendig inhaltsloser fehlerfreier Telepraxis-Eintraege dokumentiert.
- 1.9.2: Fehlerfreie Updates bestehender Nicht-Demo-Konfigurationen dokumentiert.
- 1.9.1: Korrigierte Asterisk-wav16-Installationspruefung dokumentiert.
- 1.9: Optionale Anonymisierung der Anrufernummern in Demoausgaben dokumentiert.
- 1.8.3: Teiltranskription bei schweigend uebersprungenen Feldern dokumentiert.
- 1.8.2: Bereitschaftsdienst-Zeitlogik und Ziffernaussprache dokumentiert.
- 1.8.1: Gruppen-Schreibrecht der Telepraxis-Ausgabedateien dokumentiert.
- 1.8: Gewarnten Demomodus und leere Abbruchbereinigung dokumentiert.
- 1.7.1: Rotes Telefon als Mitglied der Sonderqueue dokumentiert.
- 1.7: Sonderqueue, Queue-Penalty-Fix und Rufnummernanzeige dokumentiert.
- 1.6.2: Regulaeres Auflegen nach Aufnahmen ohne falschpositiven IVR-Fehler dokumentiert.
- 1.6.1: Korrigierte FFmpeg-loudnorm-Pruefung des Installers dokumentiert.
- 1.6: Getrennte Whisper-Modellwahl fuer Namen, Medikamente und Standardfelder dokumentiert.
- 1.5: Breitbandige normalisierte Ansagenaufnahmen mit Signalton dokumentiert.
- 1.4: PIN-freies Ansagen-IVR und wiederholende deutsche Menues dokumentiert.
- 1.3: Ansagen-IVR, Zusatztelefone und sichere Wahlregeln dokumentiert.
- 1.2: Zeitabfragen, TOML-Pruefung und zusammengefasste Zeitansagen dokumentiert.
- 1.1: TTS-Pausen, IVR-Abschluss und Installerfreigabe dokumentiert.
- 1.0: Erstveroeffentlichung der Installation, Bedienung und Architektur.
-->

# kienzlefon


<img src="https://github.com/thomaskien/kienzlefon/blob/main/kienzlefon.png?raw=true" alt="drawing" width="400" />

`kienzlefon` ist ein konfigurationsgesteuertes Asterisk-Telefonsystem fuer
Arztpraxen. Es setzt auf der Telefoniebasis von Kienzlefax auf, nimmt Angaben
feldweise als WAV auf und transkribiert sie mit Whisper. Die Vorgänge werden
direkt in der Praxis abgelegt oder verschlüsselt zur Abholung bereitgestellt.

Demo-Server: https://kienzlefon.de

**Version 2.7** · [Installationspaket herunterladen](https://github.com/thomaskien/kienzlefon/releases/download/v2.7/kienzlefon-2.7.tar.gz) · [Änderungen seit 2.5.5](CHANGELOG.md#27) · [Installation](#installation)

Bei Installation und Update bietet der Installer die lokale Verwaltung der Rufgruppen Normal und ROT an. Im Admin-Menü stehen danach die aktuelle Teilnahme, die Standardbesetzung und die Freigaben für App und Middleware zur Verfügung. Der lokale Steuerungsdienst bindet sich bei der Ersteinrichtung an Loopback.

Unter **Rufgruppen** lassen sich Geräte umbenennen und externe Änderungen für alle authentifizierten Praxisarbeitsplätze oder nur für ausgewählte Plätze freigeben. Die Einrichtung des Schaltzugangs ist unter [Anlagensteuerung](docs/ANLAGENSTEUERUNG.md) beschrieben.

Die Hauptnummer für Begrüßung und IVR stammt aus der eingehenden Telefonieleitung der Kienzlefax-Basis. Im Kienzlefon-Menü werden davon getrennte Direktnummern für Praxisqueue und ROT vergeben. Bei 1&1 kann der Registrar frühere Kontakte bis zum Ablauf ihrer Registrierung führen. Der Installer meldet andere Geräte nicht ab.

Am Installationsende erscheint die SIP-Einrichtungsliste für die lokalen Endgeräte. Im Webinterface lassen sich Praxisname und Ansagenreihenfolge anpassen und das Google-Sprechtempo mit einer einzelnen Hörprobe testen. [Bedienung des Webinterfaces](webinterface/README.md#bedienung)


## Eigenschaften

- Asterisk-IVR mit getrennten Praxisoeffnungs- und Telefonzeiten
- vorhandene Kienzlefax-Queue `praxis` als Standardziel
- erhoehte Queue-Prioritaet und interne Ansage fuer Apotheken
- optionales rotes PJSIP-Telefon ausserhalb der Queue
- priorisierte Ringall-Sonderqueue als Fachstellen-Fallback
- internes Ansagen-IVR auf Nebenstelle `777`
- optionale interne Telefone ausserhalb der Queue
- deutsche Rufnummernnormalisierung mit konfigurierbaren Sperrlisten
- strukturierte WAV-Aufnahmen fuer Personen- und Vorgangsdaten
- fehlende Einzelfelder blockieren keine spaeteren Aufnahmen oder Transkriptionen
- `faster-whisper` mit getrennt konfigurierbaren Modellen fuer Namen,
  Medikamente und alle uebrigen Felder
- dateibasierter, atomarer Ordner-Spool ohne Datenbank
- OpenSSL-kompatible `AES-256-CBC`/RSA-Ausgabe als `*.json.enc`
- unverschlüsselte JSON-Ablage für den Betrieb direkt in der Praxis
- optionale WAV-Beilage im Vorgangsverzeichnis der Inbox
- Ansagen in WAV, SLN16, G.722, A-law und mu-law. Lokal stehen Kokoro-Thorsten (Standard), Piper und Qwen3-TTS zur Wahl, optional auch Google Cloud TTS.
- gezielte neue Qwen-Variante fuer einzelne Ansagen bei unerwuenschten Sprach-Artefakten
- telefonische Ansagenaufnahmen als normalisiertes 16-kHz-PCM
- Meldung jedes technisch erkannten Fehlers im konfigurierten Ausgabemodus
- gruppenschreibbare Telepraxis-Ausgabedateien mit Modus `0660`
- Asterisk spielt fertig erzeugte Audiodateien ab. Google Cloud TTS benötigt HTTPS nur zur Synthese.
- optionaler AI-Admission-Listener auf dem Haupt-Kienzlefon
- KI-Nebenstellen ab `8810`, die nur mit einer aktiven AI-Freimeldungs-Lease
  angerufen werden
- interne Ziele `8800` bis `8805` fuer Gesamteingang, klassischen IVR,
  priorisierte Warteschlangen und die reine Musikhörprobe
- aktivierte Begruessungs-, Sonder-, Notfall- und Bereitschaftsansagen liegen
  vor einer moeglichen AI-Uebergabe; die Admission-Pruefung bleibt am
  bisherigen Einstieg ins Hauptmenue
- Die KI-Taste (standardmäßig `0`) während dieser Eingangsansagen springt sofort zur AI-Zulassung
- Die KI-Taste im klassischen Hauptmenü versucht dieselbe AI-Zulassung lautlos
  erneut, ohne nach einer AI-Rueckkehr einen Kreisverkehr zu erzeugen
- sofortige Medienbridge nach Annahme der freigemeldeten AI-Nebenstelle, damit
  das vom KI-Backend erzeugte Greeting vollstaendig hoerbar ist
- jede Anrufer-DTMF-Taste waehrend des AI-Gespraechs beendet das AI-Leg und
  wird unveraendert an das klassische Kienzlefon-Hauptmenue uebergeben
- dauerhaftes, einmalig verbrauchbares AI-Handoff-Ergebnis mit festen lokalen
  Zielen `8801` bis `8804` und fail-closed-Pruefung der aktuellen Praxisregeln
- kurz gueltige Call-Policy fuer Oeffnungs-, Telefon-, Apotheken- und
  Fachstellenlogik sowie die vollstaendigen Wochenzeitprofile
- bestaetigte `super_priority`-Handoffs werden nach allen Claim-, Lease-,
  Persistenz- und Einmalverbrauchspruefungen nicht erneut durch die
  Fachstellenzeiten blockiert
- integriertes Administrations-Webinterface mit vier Zeitbloecken, einem
  alternativen Anrufsbaum und expliziten Ansagenmodi

## Neu in 2.6.6

Zeitfenster brauchen eine Anfangs- und eine Endzeit, etwa `08:00-12:00`.
Mehrere Fenster am selben Tag werden in zeitlicher Reihenfolge durch Kommas
getrennt. Ein leerer Tag bedeutet „geschlossen“. Der Installer fragt bei einer
ungültigen Eingabe erneut nach. Um beim Update nur fehlerhafte gespeicherte
Tage zu korrigieren, die bestehende Konfiguration übernehmen und **Zeitprofile
jetzt neu konfigurieren?** mit **Nein** beantworten.

## Neu in 2.6.3

Beim Update lassen sich die vier Zeitprofile einer bestehenden Anlage erneut
erfassen. Einzeln eingegebene Tageszeiten werden gespeichert. Ein leerer Tag
bedeutet „geschlossen“. Nach einem Abbruch mit `KeyError: 'CONFIG_FILE'` den
Installer mit dem korrigierten Paket erneut starten und die Zeiten erneut eingeben.

## Neu in 2.6.1

Bei verschlüsselter Ablage übernimmt der Installer den öffentlichen RSA-Schlüssel
des Praxisservers aus einem eingefügten PEM-Block oder einer Datei. Beim Einfügen
schließt die Zeile `-----END PUBLIC KEY-----` die Eingabe ab. Bei Updates
verwendet der Installer den bereits eingerichteten gültigen Schlüssel weiter.

## Neu in 2.6.0

Der Installer fragt nach den Direktnummern für Praxisqueue und ROT, dem optionalen
Whisper-Commander und der Übergabe an die App. Für lokale und verschlüsselte
Ablage lässt sich die WAV-Beilage getrennt wählen. Der CPU-Fallback bleibt verfügbar.
Das klassische IVR kann weitere Anliegen aufnehmen. Seine Menütasten sind im
Adminbereich konfigurierbar. Der geschützte Anlagendienst steuert die Rufgruppen
Normal und ROT und liefert den Live-Status. Die Tagesstatistik verwendet
Anrufereignisse. Details stehen in der [Anlagensteuerung](docs/ANLAGENSTEUERUNG.md)
im [Vertrag für Anliegen und Audio](docs/vorgang-v1/README.md) und im
[Prüfbericht für 2.6.0](docs/TESTS-2.6.0.md).

## Neu in 2.5.5

Unbeantwortete Anrufe werden beim Wechsel des Rufzyklus neu verteilt: Anfangs
koennen mehrere Anrufe gleichzeitig an verschiedenen Telefonen klingeln. Ab dem
zweiten Zyklus hat der erste wartende Anruf Vorrang; juengere Anrufe warten bis zu
seiner Annahme oder seinem Auflegen. Angenommene Gespraeche laufen weiter, waehrend
freie Telefone wieder weitere Anrufe erhalten. Die vorhandene Apothekenprioritaet
und die globale Prioritaet der roten Sonderqueue bleiben erhalten.

Die Positionsansage lautet bei Position 2 „Sie sind auf Position zwei in der
Warteschlange.“ Der Installer migriert bekannte alte Standardtexte, installiert
eindeutige Queue-Audiodateien und prueft deren Erzeugungsstand nach dem Reload.
Eigene Aufnahmen bleiben erhalten; die Diagnose kennzeichnet sie als Aufnahme.

Die Asterisk-Vorpruefung akzeptiert normale Dial-Hilfetexte mit „not registered“
und erfolgt vor der Ansagenerzeugung. Die Wartemusikfrage lautet jetzt
„Wartemusik von Johannes Plachetka installieren?“.

Technik, Diagnose und Live-Abnahme: [Rufzyklen und Queue-Ansagen](docs/WARTESCHLANGE.md).

## Neu in 2.5.4

Die AMI-Anbindung unterstuetzt jetzt die Vermittlungsfunktionen der separaten
T2med-Middleware: direkt weitergeben oder Rueckfrage, jeweils intern und extern,
mit nativem Abschluss und Rueckkehr zum Anrufer. Der Installer bereitet die
tatsaechlichen Mitarbeiterkanaele vor und richtet den privaten Zielkontext
`kienzlefon-transfer` ein. Freigegeben sind die in `[middleware].nebenstellen`
ausgewaehlten physischen Telefone; Fax, KI und Funktionsziele sind ausgeschlossen.
Bestehende AMI-Zugangsdaten, IP-Regeln und globale Transfercodes bleiben erhalten.

Externe Vermittlungen verwenden Rufnummernsperren, Provider, Praxis-Absendernummer
und Kapazitaetspruefung der normalen Ausgehroute. `0049…`, `+49…` und nationale
Schreibweisen werden fuer deutsche Ziele gleich behandelt; Auslandsziele bleiben
bei aktivierter Auslandssperre gesperrt. Freigegebene Auslandsnummern behalten
ihre Landesvorwahl auch nach mehreren Pruefschritten.

Die Queue sagt jetzt korrekt **„Sie sind auf Position zwei in der Warteschlange.“**
Position eins bleibt „Sie sind als Naechstes an der Reihe.“ Unveraenderte alte
Standardtexte werden beim Update ersetzt; eigene Texte und Aufnahmen bleiben erhalten.

Update ueber den normalen Hauptinstaller. Danach neue Gespraeche verwenden:
Bereits laufende Gespraeche erhalten die neuen Kanal-Hooks nicht nachtraeglich.
Einrichtung und vollstaendige Live-Testfolge: [Vermittlung](docs/VERMITTLUNG.md).

## Korrektur in 2.5.3

Click-to-Dial brach unter Asterisk 20 nach dem Abheben des Mitarbeitertelefons
ab: Die Endpunktabfrage hatte einen falschen Funktionsparameter. Sie verwendet
jetzt `CHANNEL(endpoint)`. Nur wenn der tatsaechliche Kanal zur angeforderten
und freigegebenen Nebenstelle passt, wird die bestehende Ausgehroute erreicht.
Leere oder abweichende Endpunkte werden weiterhin abgelehnt.

Beim Auflegen startet der Click-to-Dial-Kontext keine erneute AGI-Pruefung mehr.
Die Korrektur wird ueber den regulaeren Hauptinstaller angewendet; Zugangsdaten
und Middleware-Konfiguration muessen dafuer nicht geaendert werden. Anschliessend
live pruefen: Telefon klingelt, abheben, externes Ziel klingelt, Gespraech fuehren
und auflegen. Details siehe [AMI-Middleware](docs/MIDDLEWARE.md#click-to-dial).

## Neu in 2.5.2

Der AMI-Installer bietet fuer externe Middleware **Alle ueber das VPN erreichbaren
Clients zulassen** an. Die bisherige Einzel-IP bleibt beim Update vorausgewaehlt,
bis die neue Auswahl ausdruecklich aktiviert wird. In der Konfiguration entspricht
das beispielsweise:

```toml
[middleware]
aktiv = true
quell_ip = "*"
server_ip = "10.88.0.1"
port = 5038
```

Dies ist ein Ausschnitt: vorhandene Benutzer-, Funktions- und Nebenstellenangaben
beibehalten. Benutzername und Secret bleiben erforderlich. AMI und die verwaltete
Firewallfreigabe bleiben auf die konkrete Zieladresse begrenzt. Im Stern-Modus
werden bestehende Listener auf anderen Adressen und aktives Web-AMI abgelehnt.
Die Erreichbarkeit dieser Adresse muss durch das VPN/Netz abgesichert sein;
der Stern erkennt nicht selbst, auf welchem Netzwerkweg ein Client ankommt.
Details und Umstellung stehen in [AMI-Middleware](docs/MIDDLEWARE.md).

## Neu in 2.5.1

- Wartemelodie als Vorgabe bei neuer Einrichtung; vorhandene Entscheidungen
  bleiben erhalten. Klingelzeichen ist weiterhin im Installer und Webinterface waehlbar.
- AMI-Verbindungsdatei als TOML: `/etc/kienzlefon/middleware-connection.toml`.
  Der Installer uebernimmt einen vorhandenen JSON-Export samt Secret und sichert
  die Altdatei mit Modus 0600, bevor sie aus dem aktiven Pfad entfernt wird.
- KI-Assistent im Webinterface ein-/ausschaltbar, mit sichtbarem Status.
  Bei ausgeschalteter KI gehen neue Anrufe ueber den klassischen IVR, inklusive
  der bisherigen Zeit- und Ansagenregeln. Auch Taste 0 und direkte interne
  KI-Anwahl erhalten keine neue KI-Zulassung. Bereits laufende Gespraeche und
  ihre Rueckgaben werden weiter verarbeitet; Nebenstellen und Zugangsdaten bleiben
  erhalten. Der Schalter startet weder Asterisk noch den Admission-Listener neu.

Die technische KI-Anbindung wird weiterhin im Installer eingerichtet.
Der Betriebsschalter ist `[ki_integration].assistent_aktiv` in `kienzlefon.toml`;
`aktiv` beschreibt weiterhin die technische Einrichtung. Ohne eingerichtete
KI-Anbindung laesst sich der Assistent im Webinterface nicht einschalten.

## Neu in 2.5.0

- Optionale AMI-Schnittstelle fuer die separat entwickelte Middleware: Callmonitor,
  Namensaufloesung vor dem Klingeln und Click-to-Dial. Der Installer fragt jede
  eingerichtete Telefon-Nebenstelle einzeln ab; Fax, Provider und Funktionsziele
  stehen nicht zur Auswahl. KI-Nebenstellen sind standardmaessig abgewählt.
- Wartemelodie von **Johannes Plachetka**, optional im Installer eingerichtet,
  normalisiert als G.722, SLN16 und WAV16 sowie A-law/mu-law fuer schmalbandige
  Verbindungen. Wahl zwischen Melodie und Klingelzeichen auch im internen Webinterface.
- Warteschlangenansagen und deutsche Zahlenbausteine werden mit derselben
  ausgewaehlten TTS-Stimme wie die uebrigen Ansagen erzeugt. Eigene Aufnahmen,
  Hoerprobe und Rueckkehr zu TTS stehen ebenfalls zur Verfuegung.
- MIT-Lizenz fuer Projekt und bereitgestellte Wartemusik; siehe [LICENSE](LICENSE)
  und [Urheber-/Drittanbieterhinweise](THIRD_PARTY_NOTICES.md).

### Wartemusik vor der Umstellung anhoeren

Im Installer **Wartemusik einrichten: ja** waehlen, den Wartemodus zunaechst auf
**Klingelzeichen** auswaehlen (bei neuer Einrichtung ist Melodie vorausgewaehlt). Anschliessend von einem internen Telefon **8805**
waehlen. Diese Hoerprobe spielt nur die Melodie ab und ruft keine Telefone an.
Alternativ im internen Webinterface unter **Wartemusik** die Vorschau abspielen.
Erst danach bei Bedarf auf **Melodie** umstellen und speichern. Der Installer
uebernimmt diese Auswahl bei spaeteren Updates als Vorgabe.

Die breitbandigen Dateien liefern G.722-Qualitaet, wenn Telefon und Verbindung
G.722 aushandeln. Bei einer G.711-Verbindung wird die schmalbandige Variante
verwendet. Die Hoerprobe aendert den eingestellten Wartemodus nicht.
Details zu den neuen Ansagen und eigenen Aufnahmen: [Ansagen](docs/ANSAGEN.md).

### Interne Nebenstellen und Testziele

| Nummer | Funktion |
| --- | --- |
| **8800** | Gesamter Kienzlefon-Eingang einschliesslich Begruessung, Zeitregeln und gegebenenfalls KI |
| **8801** | Klassischer IVR-Einstieg |
| **8802** | Praxiswarteschlange mit normalen Telefonen |
| **8803** | Praxiswarteschlange mit Apothekenprioritaet |
| **8804** | Fachstellenweg: gegebenenfalls rotes Telefon, danach priorisierte Sonderqueue |
| **8805** | Reine Wartemusik-Hoerprobe, sobald die Musik installiert ist |
| **777** | Ansagenverwaltung: anhoeren, aufnehmen und aktivieren; Nummer konfigurierbar |
| **201 ff.** | Praxis-/Queue-Telefone; Start und Anzahl laut Konfiguration |
| **299** | Standardnummer des optionalen roten Telefons; konfigurierbar |
| **8810 ff.** | Aktivierte KI-Nebenstellen entsprechend der eingerichteten Anzahl |
| weitere konfigurierte Nummern | Zusaetzliche interne Telefone |

Die Ziele 8800–8805 sind Funktionsnummern ohne eigene SIP-Anmeldung.
8802–8804 koennen tatsaechlich Telefone klingeln lassen. Die vorhandenen
Faxnummern gehoeren zur Kienzlefax-Basis und werden hier nicht neu vergeben.

### Middleware einrichten

Der Hauptinstaller fragt die AMI-Aktivierung, Betrieb auf diesem oder einem
anderen Rechner, Quell-IP der Middleware, erreichbare Server-IP, Port und
Benutzer ab. Namensaufloesung und Click-to-Dial sind getrennt waehlbar.
Jedes konfigurierte Telefon wird bei Click-to-Dial einzeln zur Freigabe angeboten.
Die Grundeinstellungen stehen in `[middleware]` der Kienzlefon-TOML.

Das zufaellig erzeugte Secret bleibt bei Updates erhalten. Am Installerende
kann es direkt am Terminal angezeigt werden. Die Uebergabe an das separate
Middleware-Modul erfolgt ueber `/etc/kienzlefon/middleware-connection.toml`
(nur root, Modus 0600). Diese Datei enthaelt Zugangsdaten und gehoert auf den
Middleware-Server, nicht auf Arbeitsplatzrechner oder eine Freigabe.
Bestehende AMI-Nutzer und Listener werden erhalten; ein widerspruechlicher
Listener wird mit einer konkreten Meldung zur manuellen Abstimmung abgelehnt.

Details, Exportformat und Testfaelle: [Middleware-Anbindung](docs/MIDDLEWARE.md).

## Installation

### Universalinstaller

Auf dem Linux-Server in einem eigenen Installationsverzeichnis den Universalinstaller herunterladen und im Terminal starten. Im Menü die gewünschten Rollen für Fax, Fon, Praxis-App oder T2med wählen.

```bash
wget -O kienzlefon-installieren.sh https://kienzlefon.de/kienzlefon-installieren.sh &&
sudo bash ./kienzlefon-installieren.sh
```

Für Fon die Frage **Online nach veröffentlichten Modulversionen suchen?** mit **Ja** beantworten und Kienzlefon `v2.7` auswählen. Alternativ das [Fon-Paket 2.7](https://github.com/thomaskien/kienzlefon/releases/download/v2.7/kienzlefon-2.7.tar.gz) vor dem Start in `pakete/` neben die Bash-Datei legen. Weitere ausgewählte Module benötigen ihre eigenen Pakete. Mit `bash kienzlefon-installieren.sh --pakete-pruefen` lassen sich die lokalen Archive vor der Installation prüfen.

### Als zweite Komponente nach Kienzlefax

Das fertige Fon-Paket steht im [GitHub-Release 2.7](https://github.com/thomaskien/kienzlefon/releases/tag/v2.7). Wer das Paket aus einem eigenen Quellstand bauen möchte, führt im Repository folgenden Befehl aus. Das Zielverzeichnis muss existieren.

```bash
bash scripts/pack.sh --output /absoluter/pfad/kienzlefon-2.7.tar.gz
```

Auf dem Linux-Ziel das Paket in ein frisches Verzeichnis entpacken. Der
Kombi-Installer ruft dort als root eine der beiden Varianten auf.

```bash
tar -xzf /absoluter/pfad/kienzlefon-2.7.tar.gz
cd kienzlefon
bash kienzlefon-installer.sh --kombi
```

Fuer die Anbindung an die T2med-Middleware lautet der letzte Befehl

```bash
bash kienzlefon-installer.sh --kombi --mit-t2med
```

Der Kombi-Aufruf gilt als Startbestaetigung. Die fachlichen Einstellungen
bleiben interaktiv. Vor APT prueft Fon die Paketdateiliste, die Fax-Umgebung
`/etc/kienzlefax-installer.env`, die aktivierte Queue `[praxis]`, Telefoniedialplan,
PJSIP-Konfiguration und den Kontext `[kfx_external_capacity]`. Bei einem Fehler
nennt es die Voraussetzung und beendet den Komponentenschritt mit Fehlerstatus.

Anwendung und Webinstaller kommen aus dem entpackten Ordner. Bei Erstinstallation
und Update richtet der Webinstaller die Administration verbindlich ein. Sein
Fehlerstatus geht an den Kombi-Installer zurueck. Bei Wahl von Qwen prueft Fon
den mitgelieferten v1.5-Helfer vor der Ausfuehrung gegen die fest hinterlegte
SHA-256-Summe. Systempakete, Python-/TTS-Abhaengigkeiten und Sprachmodelle
nutzen weiterhin ihre regulaeren Bezugsquellen.

Mit `--mit-t2med` richtet Fon die Asterisk-Seite der Verbindung ein. Im
AMI-Dialog den lokalen oder den separaten Middleware-Rechner waehlen. Fuer
den separaten Rechner werden Quelle und erreichbare Zieladresse abgefragt.
Die Uebergabedatei liegt unter `/etc/kienzlefon/middleware-connection.toml`
(root, Modus `0600`). Bei Updates bleiben AMI-Benutzer und Secret erhalten.
Ohne das Flag behaelt ein Update die konfigurierte Anbindung bei. Die
Installation des T2med-Dienstes erfolgt in einem eigenen Schritt.

Die Pflichtdateien stehen in `scripts/package-files.txt`. Der Packer liest sie
direkt aus dem Arbeitsbaum und ergaenzt neue Python-Module unter `kienzlefon/`,
Webprogrammdateien und Assets, Shell- und Python-Helfer in `scripts/` und
`scripts/kokoro/` sowie Beispielvorlagen in `config/`. Die Dateiliste im
Archiv enthaelt die tatsaechlich gepackten Pfade. Neue benoetigte Dateien
ausserhalb dieser Auswahl in die Pflichtliste aufnehmen. Lokale Konfiguration,
Schluessel, virtuelle Umgebungen, Laufzeitdaten und die separate
Telepraxis-Demowebseite bleiben ausserhalb des Pakets.

### Eigenständige Kienzlefon-Installation

Für Version 2.7 auf dem Linux-Server in einem frischen Verzeichnis das Release-Paket laden, seine SHA-256-Prüfsumme vergleichen und den beiliegenden Installer starten.

```bash
curl -fL -o kienzlefon-2.7.tar.gz https://github.com/thomaskien/kienzlefon/releases/download/v2.7/kienzlefon-2.7.tar.gz &&
echo 'c622f4678dcf62afbde752ad18dd7cba9eebd033acd06c54287093fad8c9cb09  kienzlefon-2.7.tar.gz' | sha256sum -c - &&
tar -xzf kienzlefon-2.7.tar.gz &&
sudo bash kienzlefon/kienzlefon-installer.sh
```

Fehlt Kienzlefax, bietet der Installer zuerst dessen offizielle Installation
an. Die Kienzlefax-Telefoniequeue muss aktiviert sein. Der Installer fragt
Praxisname, Zeitprofile, Telepraxis-Kanal, Ausgabemodus, die Nutzung eines roten
Telefons und optionale Direktnummern für die Warteschlange und ROT ab.

Für den Betrieb direkt in der Praxis kann Kienzlefon unverschlüsselt in die
lokale Inbox schreiben. Für den Betrieb auf einem Root-Server im Rechenzentrum
wählt man die verschlüsselte Ablage mit dem öffentlichen Empfängerschlüssel.
Der Abholer und die Bearbeitung laufen in der Praxis.

Bei Installation, Update und Neukonfiguration fragt der Installer nach **Nur
JSON** oder **Audio beilegen** sowie nach der optionalen IP-Adresse des
Kienzledoku-Commanders. Bei einem Ausfall des Commanders übernimmt lokales
CPU-Whisper. Für Namen, Medikamente und andere Angaben lassen sich getrennte
Whisper-Modelle verwenden.

Bei aktivierter Kienzlefon-AI-Anbindung fragt der Installer die Anzahl der
anzulegenden KI-Nebenstellen und die konkrete Listener-Bindung ab. Der Listener
liegt auf dem Haupt-Kienzlefon und bindet wahlweise an Loopback, eine
WireGuard-IP oder eine LAN-IP. Die KI-Maschine meldet jeden Slot aktiv als
`free` oder `not_free`; Kienzlefon fragt die Kapazitaet nicht auf der
KI-Maschine ab. Ohne aktuelle, einmalig verbrauchbare Lease wird kein Anruf an
eine KI-Nebenstelle geleitet. Die Schnittstelle besitzt auf ausdrueckliche
Vorgabe keine Anwendungsauthentifizierung und darf nur in einem geschuetzten
Netz betrieben werden.

Ab 2.4.4 erzeugt `_ai_endpoint()` die KI-Endpunkte (bei drei Slots `8810` bis
`8812`) dauerhaft mit `disallow=all`, `allow=g722` sowie
`incoming_call_offer_pref=local_first` und `outgoing_call_offer_pref=local_first`.
Dies gilt bei Installation, Update und erneutem Aufruf von `kienzlefon-asterisk`.
Provider und normale Telefone behalten ihre G.711-Codecs `alaw`/`ulaw`.
Der Codec-Fix aendert keine Kokoro-/CUDA-Einstellungen oder vorhandenen
Sprechpausen; insbesondere bleiben konfigurierte 1000 ms erhalten.

Der verbindliche Laufzeitvertrag fuer Kapazitaet, Call-Policy und Handoff ist
in `SPEZIFIKATION-KIENZLEFON-AI-RUNTIME-SCHNITTSTELLE-v1.1.md` dokumentiert.
`large-v3-turbo` ist etwa dreimal so schnell und speichersparender;
`large-v3` kann bei Eigennamen genauer sein.

Bei einem Update kann die vorhandene Grundkonfiguration erhalten und separat
entschieden werden, ob die Zeitprofile neu konfiguriert werden sollen. Neu
eingegebene Zeiten werden nach dem Schreiben aus der TOML-Datei zurueckgelesen
und mit den Eingaben verglichen.
Fehlende Eintraege werden dabei aus der aktuellen Vorlage ergaenzt, vorhandene
TOML-Werte nicht ueberschrieben. Das gilt auch fuer `[ansagen_modus]` seit 2.4.0.
Die nachfolgende TTS-Auswahl bietet bei bisherigem
Piper den Wechsel zu Kokoro-Thorsten als Standard an; Auswahl 2 behaelt Piper.
Bei Wechsel von Piper zu Kokoro werden die vorhandenen automatischen Ansagen
auch ohne Vollerzeugung neu erzeugt und ersetzt; eigene Aufnahmen bleiben erhalten.
Eine bestehende Qwen-Auswahl bleibt vorausgewaehlt, sofern Qwen installiert ist.
Passwoerter unveraenderter Zusatztelefone bleiben erhalten.
Der Installer erklaert die priorisierte Sonderqueue und fragt, welche bereits
konfigurierten Zusatznebenstellen dort neben den normalen Queue-Telefonen
gleichzeitig klingeln sollen.

Die Installation laedt jedes konfigurierte Whisper-Modell genau einmal, die
Piper-Stimme als weiter waehlbare Alternative und bei Kokoro-Auswahl das
pruefsummengesicherte Thorsten-Modell in einer separaten CPU-Umgebung.
Für Qwen3-TTS verwendet der Hauptinstaller seit 2.6.2 auch beim normalen
Start den mitgelieferten Installer v1.5. Fehlt die Datei, fragt das Menü,
ob sie von GitHub geladen werden darf. Enter lehnt den Download ab und beendet
die Installation. Vor der Ausführung prüft Kienzlefon die fest hinterlegte
SHA-256-Summe. Bei einer Abweichung bricht die Installation ab.
Bei weniger als 16 GB warnt der Installer vor der
gleichzeitigen Verwendung beider Whisper-Modelle, erlaubt sie aber nach
ausdruecklicher Bestaetigung.
Je nach Server und Internetanbindung kann dieser Schritt laenger dauern.
Version 1.9.1 prueft das fuer breitbandige Telefonaufnahmen erforderliche
`wav16`-Format ohne einen falschnegativen Abbruch durch Bash-`pipefail`.
Version 1.9.2 ueberspringt die nur fuer Demo-Konfigurationen vorgesehene
Anonymisierungsabfrage bei Produktivkonfigurationen mit erfolgreichem Status.
Version 1.9.3 erzeugt fuer einen fehlerfreien Anruf ohne ein einziges nicht
leeres Whisper-Transkript keinen Telepraxis-Eintrag. Caller-ID, IVR-Kategorie
und leere WAV-Dateien gelten dabei nicht als Inhalt.

## Konfiguration

Fuer ein Fonial-IP-Endgeraet ueber Plusnet stehen eine
[PJSIP-Vorlage](config/pjsip-fonial.conf.example) und
[Hinweise zur Einbindung und zu `\;lr`](docs/FONIAL.md) bereit.

Die zentrale, von Menschen editierbare Konfiguration liegt unter:

```text
/etc/kienzlefon/kienzlefon.toml
```

Das rote Telefon und die Sonderqueue werden zentral gesteuert:

```toml
[ivr]
rotes_telefon_aktiv = true

[sonderqueue]
name = "kienzlefon-sonder"
gewicht = 100
zusaetzliche_nebenstellen = []
```

Die Anfangsbesetzung von ROT umfasst die normalen Queue-Nebenstellen, ausgewählte Zusatztelefone und ein aktiviertes rotes Telefon, jeweils mit Penalty `0`. Bei eingerichteter Rufgruppenverwaltung zählt anschließend die aktive Teilnahme in ROT. Ohne eigenes rotes Telefon führt der Fachstellenweg direkt in diese Gruppe. Mit rotem Telefon klingelt es zuerst allein, standardmäßig 20 Sekunden. Bei Nichtannahme klingeln die aktiven ROT-Mitglieder. [Rufgruppen verwalten](docs/ANLAGENSTEUERUNG.md#rufgruppen)

Extern eingehende deutsche Caller-IDs erscheinen an allen Telefonen als
`02331...`, auslaendische als `0048...`. Die urspruenglich uebertragene
Caller-ID bleibt fuer den Telepraxis-Datensatz unveraendert.

Die Modellzuordnung und die editierbaren Feld-Prompts stehen zentral unter
`[whisper]`:

```toml
modell_standard = "large-v3-turbo"
modell_namen = "large-v3"
modell_medikamente = "large-v3-turbo"
initial_prompt_vorname = "Es folgt ausschließlich der Vorname einer Person."
initial_prompt_nachname = "Es folgt ausschließlich der Familienname einer Person."
initial_prompt_medikamente = "Es folgt eine Medikamentenangabe mit Medikamentenname oder Wirkstoff, Wirkstärke und Packungsgröße."
```

Sind alle drei Modellwerte gleich, hält der Worker nur eine Modellinstanz. Bei unterschiedlichen Werten hält der Worker jede konfigurierte Modellvariante einmal im Speicher.

Nach einer Text-, Zeit- oder Stimmenaenderung werden die Ansagen aktualisiert:

```bash
sudo kienzlefon-ansagen
```

Alle Ansagen bewusst neu erzeugen:

```bash
sudo kienzlefon-ansagen --all
```

Während der Verarbeitung wird der aktuelle Schritt unmittelbar vor der jeweiligen
Ansage ausgegeben. Bei Qwen3-TTS erscheinen außerdem das vorübergehende Beenden und
der anschließende Wiederanlauf des Whisper-Workers, beispielsweise:

```text
[0/4] 4 Verarbeitungsschritt(e) erforderlich.
[0/4] Whisper-Worker wird für Qwen3-TTS vorbereitet.
[1/4] Automatische Ansage wird erzeugt: greeting_open
[2/4] Automatische Ansage wird erzeugt: phone_hours
```

Ab 2.4.1 ist **Kokoro-Thorsten** die Standardstimme fuer lokale Ansagen.

Ab 2.4.2 werden Zahlen und Uhrzeiten vor der Spracherzeugung deutsch ausgeschrieben:
`drücken Sie 6` wird `drücken Sie sechs`, `08:30 Uhr` wird `acht Uhr dreißig`
und `14 Uhr` wird `vierzehn Uhr`. Dies gilt fuer alle drei TTS-Engines, auch fuer
automatische Oeffnungs-/Telefonzeiten, Sonderansagen und Vorschauen. Das normale
Update erzeugt betroffene TTS-Audiodateien neu, ohne `--all`; eigene Aufnahmen
bleiben Audioquelle. Die bearbeitbaren Texte und Pausenmarker bleiben erhalten.

Der Hauptinstaller richtet bei Auswahl 1 die aus Kienzlefon-AI uebernommenen,
fixierten Kokoro-/Misaki-Versionen und das deutsche Thorsten-Modell ein.
Voraussetzung ist Linux x86_64. Ab 2.4.3 richtet der Installer bei fehlendem
Python 3.11/3.12 mit venv-Unterstuetzung automatisch eine separate,
pruefsummengepruefte Python-3.12-Laufzeit unter `/opt/kienzlefon/kokoro/python/`
ein, auch auf Debian 13 mit System-Python 3.13. System-Python und andere
Python-Umgebungen werden dabei nicht ersetzt.
Die Synthese laeuft auf CPU, ohne dauerhaft geladenen TTS-Dienst und nach dem
Modelldownload offline. Die bestehende Normalisierung und die Telefonieformate
bleiben erhalten; bei einem Fehler wird nicht automatisch auf Piper gewechselt.

```toml
[tts]
engine = "kokoro"
kokoro_generator = "/usr/local/bin/kienzlefon-kokoro-tts-generate"
kokoro_modellverzeichnis = "/var/lib/kienzlefon/kokoro-thorsten"
kokoro_speed = 1.0
```

`kokoro_speed` muss endlich und groesser als 0 sein; groessere Werte sprechen
schneller. Text, Engine, Geschwindigkeit und Generatorstand fliessen in die
Aenderungserkennung ein. Unveraenderte Ansagen werden nicht erneut synthetisiert.
Piper bleibt mit `engine = "piper"` wählbar. Im Webinterface stehen auch Qwen, Kokoro und Google zur Wahl, sobald die jeweilige Engine eingerichtet ist. [Google Cloud TTS einrichten](docs/GOOGLE_TTS.md)
Wenn Kokoro bei einer Installation nicht gewaehlt wurde, den Hauptinstaller
mit Auswahl 1 erneut ausfuehren, bevor im Webinterface darauf gewechselt wird.

Auch das separat installierte, nicht residente Qwen3-TTS bleibt verfuegbar.
Qwen wird vom Hauptinstaller auf Wunsch mit dem fest freigegebenen
Offline-Installer v1.5 eingerichtet:

```toml
engine = "qwen"
qwen_stimme = "ryan"
qwen_sprache = "German"
qwen_seed = 42
qwen_generator = "/usr/local/bin/kienzlefon-qwen3-tts-generate"
```

Zulaessige Qwen-Sprecher sind `ryan`, `vivian`, `serena`, `aiden`, `eric`,
`dylan`, `uncle_fu`, `ono_anna` und `sohee`. Die Auswahl gilt global und ist
im Installer sowie im Webinterface aenderbar. Der Ansagengenerator vergleicht
Text, Modell, Sprecher, Seed, Generatorstand und Normalisierung. Ohne Unterschied
wird Qwen nicht gestartet; `--all` bleibt die ausdrueckliche Wartungsfunktion.
Manuelle WAV-Aufnahmen bleiben von Modell- und Sprecherwechseln unberuehrt.

Die Piper-Sprechgeschwindigkeit wird unter `[tts]` mit `length_scale` gesteuert.
Der Standardwert `1.3` wird bei der Installation abgefragt; groessere Werte
sprechen langsamer. `sentence_silence = 0.8` legt die zusaetzliche Satzpause in
Sekunden fest. Eine exakt platzierte Pause steht direkt im Ansagetext:

```toml
ansage = "Guten Tag.{pause:800}Bitte waehlen Sie."
```

Die Zahl bezeichnet Millisekunden. Nach einer Text-, Praxisnamen- oder
TTS-Aenderung erzeugt `kienzlefon-ansagen` alle betroffenen Ansagen neu.

Die ausschliesslich intern erreichbare Nebenstelle `777` verwaltet Ansagen
ohne PIN. Dort koennen Bausteine nach stabiler Nummer aufgenommen, angehoert,
aktiviert oder auf die automatische TTS-Fassung zurueckgeschaltet werden. Ausserdem laesst sich der
Feiertags- und Sonderansagemodus mit oder ohne Sperrung der Telefonzeiten
schalten. Ohne Eingabe werden die jeweiligen Anweisungen nach fuenf Sekunden
unbegrenzt wiederholt. Die vollstaendige
Nummerierung steht in [Ansagen](docs/ANSAGEN.md).

Unter `[wahlregeln]` stehen Ortsvorwahl, Praxisrufnummer und die Schalter fuer
Sonderrufnummern. `110`, `112`, `116116` und `116117` bleiben immer erreichbar.
Intern unbekannte Nummern ab drei Ziffern werden fuer Deutschland normalisiert;
internationale Ziele sind standardmaessig gesperrt.

Telefonisch neu aufgenommene Ansagen starten nach einem Signalton und werden
als `wav16` mit 16 kHz gespeichert. Vor der Vorschau erfolgt eine zweistufige
Lautheitsnormalisierung. Dieselbe Masterung gilt auch fuer Kokoro-, Piper- und
Qwen-Ansagen. Die Standardwerte unter `[tts]` sind:

```toml
ziel_lautheit_lufs = -19.0
max_true_peak_db = -2.0
```

Damit bleiben manuelle und automatisch erzeugte Ansagen in vergleichbarer
Lautstaerke, waehrend Spitzenpegel begrenzt werden. Patientenaufnahmen bleiben
signaltonfrei und verwenden unveraendert ihren bisherigen Aufnahmeweg.

Eine menschlich eingesprochene WAV-Datei unter
`/var/lib/kienzlefon/ansagen-upload/<ansagenname>.wav` ersetzt fuer diesen
Ansagenamen die automatische TTS-Fassung. `kienzlefon-ansagen` prueft auch diese Dateien und erzeugt
daraus dieselben Telefonieformate. Beim Erzeugen wird deutlich darauf
hingewiesen, dass eine solche Datei Text und Praxisname ueberschreibt.

Konfiguration pruefen:

```bash
sudo kienzlefon-config
```

Worker und Warteschlangen pruefen:

```bash
sudo kienzlefon-status
systemctl status kienzlefon-worker
```

## Administrations-Webinterface

Das Webinterface gehoert ab Version 2.4.0 zur Kienzlefon-Hauptversion und fuehrt
keine eigene Produktversion mehr. Eine vorhandene Installation wird vom
Hauptinstaller automatisch mitaktualisiert. Bei einer eigenstaendigen
Erstinstallation bleibt die Aktivierung optional. Der technische
Installationshelfer laesst sich auch direkt starten.

```bash
sudo ./kienzlefon-webinterface-installer.sh
```

Für ein internes Praxis-LAN kann **1 · Eigener schlanker PHP-Systemdienst**
an die feste private IPv4-Adresse des Servers gebunden werden. Die Anmeldung
erfolgt standardmäßig mit Kennwort über HTTP auf Port 8088. Der Installer bietet nach ausdrücklicher Bestätigung auch kennwortlosen Zugriff im privaten Praxisnetz an. In dieser
Betriebsart darf der Dienst keinesfalls aus dem Internet erreichbar sein.

Der Installationshelfer aktiviert den Export des fluechtigen
Laufzeitstatus als Boot-Dienst. Dadurch werden nach dem Leeren von `/run` bei
einem Systemneustart insbesondere der konfigurierte Passwortmodus und die
WireGuard-Bindung vor dem Webserverstart wiederhergestellt.

Es bearbeitet Zeiten und Ansagen. Die Zeitseite zeigt Oeffnungszeiten,
Telefonzeiten, `care_service` fuer Apotheke, Pflegeheim oder Pflegedienst sowie
`professional_urgent` fuer Arztpraxis, Krankenhaus, Rettungsdienst oder Notarzt
weiterhin untereinander. Die vorhandenen technischen TOML-Felder
`apothekenzeiten` und `fachstellenzeiten` bleiben unveraendert.

Der Navigationspunkt „Anrufsbaum“ zeigt den konfigurierten Ablauf. Dort lassen sich Tasten belegen, Funktionen deaktivieren und die Reihenfolge im Hauptmenü ändern. Ansagen können dort
ausdruecklich aktiviert oder deaktiviert und weiterhin abgespielt werden.
Begruessungen und Notfallhinweis unterstuetzen `immer`, `offen`, `zu` und
`deaktiviert`. Das Abschalten zeigt keine Warnabfrage und aendert nur die
Wiedergabe, nicht das anschliessende Routing.

Ansagen koennen direkt im Browser
abgespielt und ueber eine freigegebene Nebenstelle neu aufgenommen werden.
Ein leerer erforderlicher Ansagentext wird vor der TOML-Uebernahme abgelehnt;
Deaktivieren erfolgt ueber den expliziten Ansagenmodus.
Benannte Sonderansagen behalten ihren TTS-Text, die erzeugte TTS-WAV, eine
optional eingesprochene WAV und die ausgewaehlte Audioquelle gemeinsam. Mehrere
Eintraege koennen gleichzeitig geplant werden. Beruecksichtigt werden der
Aktivstatus, ein optionaler Beginn, ein optionaler Ablauf und eine eindeutige
Prioritaet zwischen 0 und 1000. Bei jedem neuen Anruf wird nur die aktuell
gueltige Ansage mit der hoechsten Prioritaetszahl verwendet. Dadurch uebernimmt
nach einem Ablauf automatisch die naechste gueltige Stufe, ohne erneute
Ansagenerzeugung. Fuer jeden Eintrag werden Position und Telefonzeitensperre
getrennt gespeichert. Die Position ist anstelle, vor oder nach der normalen
Begruessungsansage. Wenn gleichzeitig die normalen Telefonzeiten gesperrt
werden, wird bei den Positionen davor und danach die Geschlossen-Begruessung
verwendet; der Bereitschaftsdienst-Hinweis folgt immer.

## Dateifluss

Jeder Anruf verwendet ein Verzeichnis nach dem Muster:

```text
20260711_114658_676879/
  call.json
  audio/
    vorname.wav
    nachname.wav
    geburtsdatum.wav
    grund.wav
```

Die Zustandsverzeichnisse liegen standardmaessig unter
`/var/spool/asterisk/kienzlefon/`:

```text
recording -> queue -> processing -> ready
                                  -> error
```

Der gesamte Vorgangsordner wird atomar zwischen den Zustaenden verschoben.
Die Telepraxis-Ausgabe liegt im abgefragten Kanalverzeichnis, beispielsweise
`/srv/telepraxis/dahl/inbox`. Die verschlüsselte JSON-Ausgabe verwendet
`.json.enc`, die lokale Praxisablage `.json`. Mit Audio-Beilage liegen die WAVs
in der lokalen Inbox unter `<vorgang_id>/audio/` oder werden als verschlüsseltes
`.kienzlepaket` vom App-Abholer in die Praxis übernommen. Nach gesicherter
Ausgabe bzw. bestätigter Ablage entfernt Kienzlefon die temporären WAVs aus
dem Spool. Anschließend verwaltet die App die Tonaufnahmen in der Inbox.
[Gemeinsamer Audiovertrag](docs/vorgang-v1/AUDIO.md)

## Mehrere Anliegen pro Anruf

Der klassische IVR fragt nach jedem Anliegen nach einem weiteren. Die
Folgeauswahl bietet die im Admin-Menü aktivierten Anliegenarten an. Name,
Geburtsdatum und Rückrufnummer werden gemeinsam erfasst. Auflegen oder eine
ausbleibende Auswahl schließt den Vorgang mit den vorhandenen Aufnahmen ab.
Ein einzelnes Anliegen behält das bisherige JSON-Format. Mehrere Anliegen
werden als gemeinsame Vorgangs-JSON mit stabilen Teilanliegen-IDs ausgegeben.

Kienzlefon kann fertige KI-Fälle der Runtime 2.9 aus einem geschützten
Ergebnisverzeichnis übernehmen. `ergebnisverzeichnis` unter `[ki_integration]`
ist der absolute Pfad zu den UUID-Fallordnern des KI-Postprozessors. Bei
getrennten Rechnern benötigt der Kienzlefon-Worker geschützten Lesezugriff auf
die bereitgestellten Fallordner mit `call.json`, `result.json` und optional
`caller.wav`. Einzelne Fälle lassen sich mit `/opt/kienzlefon/venv/bin/kienzlefon-ki-import` und dem
Pfad zum Fallordner übernehmen.

Der Import verwendet die eingestellte Praxisablage oder verschlüsselte
Abholung und die dort gewählte Audio-Beilage. Anliegen mehrerer Patienten
erzeugen getrennte Vorgänge. Eine Gesamtaufnahme, die mehrere Patienten
betrifft, wird dabei nicht beigelegt. [Gemeinsamer JSON-Vertrag](docs/vorgang-v1/ANLIEGEN.md)

## Rufgruppen und Live-Zähler

Der optionale Kienzlefon-Steuerungsdienst liefert **Normal**, **ROT** sowie
die aktuellen Zähler für Warteschleife, IVR und KI. Die Administration legt
Standardteilnahme, Freigaben und die Rufstufe fest. Der Anlagenzustand und
temporäre Änderungen werden über Asterisk bestätigt.
[Einrichtung und Abnahme](docs/ANLAGENSTEUERUNG.md)

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check kienzlefon tests
bash -n kienzlefon-installer.sh
```

### Abnahme des Kombi-Pakets am 18.11.2026

```bash
python -m pytest -q tests/test_installer.py tests/test_kombi_installer.py \
  tests/test_webadmin.py tests/test_middleware.py tests/test_middleware_sources.py
```

Auf macOS bestanden alle 160 Tests dieses Laufs. Fehlende Fax- und
Paketbestandteile fuehrten vor APT und vor jedem Download zum Abbruch.
Eine nur im Test-Arbeitsbaum markierte `webinterface/admin.php` kam nach
Packen, Entpacken und Aufruf des Webinstallers bytegleich am Installationsziel
an. Das galt auch beim Update mit gleicher Dateigroesse und gleichem Zeitstempel.
Die simulierten Webinstaller-Fehler 17 und 23 erreichten den Aufrufer mit
demselben Status. Lokale und separate AMI-Anbindungen behielten Benutzer und
Secret bei weiteren Laeufen mit und ohne `--mit-t2med`.

Der Packer lief mit der macOS-System-Bash 3.2. Aus dem entpackten Archiv liess
sich das Python-Wheel mit Python 3.11 ohne Netzwerkzugriff bauen. Alle 33
Python-Module stimmten in Arbeitsbaum, Archiv und Wheel byteweise ueberein.
Die Installertests verwenden temporaere Zielpfade und simulieren APT, Asterisk
und systemd. Der vollstaendige Lauf mit `python -m pytest -q` bestand mit
647 Tests und 34 Untertests, einschliesslich der lokalen Loopback-Testserver.

Weitere Einzelheiten stehen in [Architektur](docs/ARCHITEKTUR.md),
[IVR-Ablauf](docs/IVR.md), [Telepraxis-Format](docs/TELEPRAXIS.md) und
[SMS-Ausgangsqueue mit eigenständigem Worker](docs/SMS-QUEUE.md).

Maßgeblich für SMS-Bibliotheken, Konfiguration und Worker ist künftig das
[Repository der Praxis-App](https://github.com/thomaskien/kienzlefon-app) (lokal `ionos`). Die Demo wird nur gezielt abgeglichen;
sie ersetzt die reguläre App nicht. Siehe [SMS-Repository-Zuordnung](docs/SMS-REPOSITORIES.md).
