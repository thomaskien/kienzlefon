<!--
kienzlefon
Version: 2.5.3

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
feldweise als WAV auf, transkribiert lokal mit Whisper und legt jeden Vorgang
im Produktivmodus als verschluesselte Telepraxis-Datei ab.

Demo-Server: https://kienzlefon.de

Version: **2.5.3**

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
- ausdruecklich zu bestaetigender Demomodus mit unverschluesselter `*.json`-Ausgabe
- optionale Anonymisierung von `id` und `telefon` in Demo-JSONs
- lokale Kokoro-Thorsten-Ansagen (Standard), alternativ Piper oder Qwen3-TTS,
  in WAV, SLN16, G.722, A-law und mu-law
- gezielte neue Qwen-Variante fuer einzelne Ansagen bei unerwuenschten Sprach-Artefakten
- telefonische Ansagenaufnahmen als normalisiertes 16-kHz-PCM
- Meldung jedes technisch erkannten Fehlers im konfigurierten Ausgabemodus
- gruppenschreibbare Telepraxis-Ausgabedateien mit Modus `0660`
- keine TTS-HTTP-Schnittstelle und kein dauerhaft geladener TTS-Dienst
- optionaler AI-Admission-Listener auf dem Haupt-Kienzlefon
- KI-Nebenstellen ab `8810`, die nur mit einer aktiven AI-Freimeldungs-Lease
  angerufen werden
- interne Ziele `8800` bis `8805` fuer Gesamteingang, klassischen IVR,
  priorisierte Warteschlangen und die reine Musikhörprobe
- aktivierte Begruessungs-, Sonder-, Notfall- und Bereitschaftsansagen liegen
  vor einer moeglichen AI-Uebergabe; die Admission-Pruefung bleibt am
  bisherigen Einstieg ins Hauptmenue
- Taste `0` waehrend dieser Eingangsansagen springt sofort zur AI-Zulassung
- Taste `0` im klassischen Hauptmenue versucht dieselbe AI-Zulassung lautlos
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

Auf einem unterstuetzten Kienzlefax-Linux-System oder einem frischen Server:

```bash
curl -fsSLO https://raw.githubusercontent.com/thomaskien/kienzlefon/main/kienzlefon-installer.sh
chmod +x kienzlefon-installer.sh
sudo ./kienzlefon-installer.sh
```

Fehlt Kienzlefax, bietet der Installer zuerst dessen offizielle Installation
an. Die Kienzlefax-Telefoniequeue muss aktiviert sein. Der Installer fragt
Praxisname, Zeitprofile, Telepraxis-Kanal, Ausgabemodus, die Nutzung eines roten
Telefons und optionale direkte externe Rufnummern interaktiv ab. Im normalen
Produktivmodus wird zusaetzlich der Public Key abgefragt. Der Demo-Modus legt
alle Daten unverschluesselt ab und darf auf keinen Fall mit echten
Patientendaten verwendet werden. Optional ersetzt Version 1.9 in den
ausgegebenen Demo-JSONs die Felder `id` und `telefon` durch `#anonymisiert demo#`.
Audiodateien und in Freitexten genannte Rufnummern werden dadurch nicht
veraendert. Seit Version 1.6 werden die
Whisper-Modelle fuer Namen, Medikamente und alle uebrigen Aufnahmen getrennt ab.

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
Qwen3-TTS wird nur nach ausdruecklicher Auswahl
mit dem geprueften Offline-Installer v1.5 eingerichtet. Bei weniger als 16 GB warnt der Installer vor der
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

Die bestehende Kienzlefax-Queue `praxis` wird dabei nicht veraendert. Die
Sonderqueue enthaelt automatisch alle normalen Queue-Nebenstellen mit Penalty
`0`; ausgewaehlte Zusatztelefone und ein aktiviertes rotes Telefon werden
ebenfalls mit Penalty `0` aufgenommen. Ohne rotes Telefon fuehrt Taste 9 direkt
dorthin. Mit rotem Telefon klingelt dieses zuerst exklusiv fuer die konfigurierte
Dauer von standardmaessig 20 Sekunden. Danach folgt die Sonderqueue, in der das
rote Telefon gemeinsam mit allen anderen Mitgliedern erneut beruecksichtigt wird.

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

Sind alle drei Modellwerte gleich, hält der Worker nur eine Modellinstanz. Bei
unterschiedlichen Werten bleiben beide benötigten Modelle dauerhaft geladen.

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
Piper bleibt mit `engine = "piper"` waehlbar. Das Webinterface bietet alle drei
Engines an und prueft vor dem Wechsel, ob Kokoro bzw. Qwen eingerichtet ist.
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
Hauptinstaller automatisch mitaktualisiert; bei einer Erstinstallation bleibt
die Aktivierung optional. Der technische Installationshelfer kann weiterhin
direkt ausgefuehrt werden:

```bash
sudo ./kienzlefon-webinterface-installer.sh
```

Der Installationshelfer aktiviert den Export des fluechtigen
Laufzeitstatus als Boot-Dienst. Dadurch werden nach dem Leeren von `/run` bei
einem Systemneustart insbesondere der konfigurierte Passwortmodus und die
WireGuard-Bindung vor dem Webserverstart wiederhergestellt.

Es bearbeitet Zeiten und Ansagen. Die Zeitseite zeigt Oeffnungszeiten,
Telefonzeiten, `care_service` fuer Apotheke, Pflegeheim oder Pflegedienst sowie
`professional_urgent` fuer Arztpraxis, Krankenhaus, Rettungsdienst oder Notarzt
weiterhin untereinander. Die vorhandenen technischen TOML-Felder
`apothekenzeiten` und `fachstellenzeiten` bleiben unveraendert.

Der zusaetzliche Navigationspunkt „Anrufsbaum“ zeigt den festen Ablauf als
alternativen Zugang zu den vorhandenen Ansagen. Ansagen koennen dort
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
`/srv/telepraxis/dahl/inbox`. Produktivdateien enden auf `.json.enc`,
unverschluesselte Demodateien auf `.json`.
Beide Varianten erhalten Modus `0660`. Bei Root-Ausfuehrung entspricht ihre
Gruppe der Gruppe des Ausgabeverzeichnisses; interne Spooldateien bleiben
restriktiver geschuetzt.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check kienzlefon tests
bash -n kienzlefon-installer.sh
```

Weitere Einzelheiten stehen in [Architektur](docs/ARCHITEKTUR.md),
[IVR-Ablauf](docs/IVR.md) und [Telepraxis-Format](docs/TELEPRAXIS.md).
