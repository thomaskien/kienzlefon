<!--
kienzlefon
Version: 2.5.5
Changelog:
- 2.4.1: Kokoro-Thorsten als Standard fuer lokale Ansagen ergaenzt.
- 2.4.0: Webinterface integriert, Anrufsbaum und Super-Priority-Notfallweg freigegeben.
- 2.3.2: AI-Medienbridge fuer ein hoerbares Backend-Greeting sofort gestartet.
- 2.3.1: Eingangs- und Menuephase ohne DTMF-Eingabe korrigiert.
- 2.3: Sicheren AI-Handoff, Call-Policy, Assistentenansage und DTMF-Rueckkehr integriert.
- 2.2: Push-basierten AI-Admission-Listener und freigemeldete KI-Nebenstellen integriert.
- 2.1.2: Passwortloser WireGuard-Zugriff bleibt nach einem Systemneustart erhalten.
- 2.1.1: Hauptinstaller bietet Webinterface-Installation oder -Aktualisierung immer an.
- 2.1: Gezielte Qwen-Varianten, Webinterface 1.1 und WireGuard-KI-Client ergaenzt.
- 2.0: Qwen3-TTS, globale Sprecherwahl, Webinterface 1.0 und differenzielle Ansagenerzeugung ergaenzt.
- 1.9.3: Telepraxis-Ausgabe fuer vollstaendig inhaltslose fehlerfreie Anrufe unterdrueckt.
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

## 2.5.5

- Installer-Nachkorrektur: Bei deaktivierter Middleware bleiben unverwaltete
  Ueberlaufrouten unveraendert; ein Middleware-Uebergabepunkt ist dann nicht
  erforderlich. Bereits gesetzte eigene Middleware-Hooks werden beim Abschalten
  weiterhin zurueckgenommen, mehrdeutige Hooks vor dem Schreiben abgewiesen.
- Parallele erste Rufversuche werden vor dem naechsten Zyklus des ersten wartenden
  Anrufers beendet; ab dann wartet der nachrangige Anrufer bis zur Annahme oder zum
  Auflegen des vorrangigen Anrufers. Laufende Gespraeche werden nicht beendet.
- Bestehende Apothekenprioritaet, Sonderqueue-Gewichtung und PJSIP-Belegtzustaende
  bleiben Teil der Verteilung; native Queue-Ansagen und Wartepositionen bleiben erhalten.
- Positionsansagen nutzen eigene eindeutig konfigurierte Audiodateien; bekannte
  fehlerhafte Standardformulierungen werden gemeinsam migriert. Installerdiagnose
  prueft Texte, Dateien und den erfolgreichen Queue-Reload.
- Asterisk-Vorpruefung erkennt echte CLI-Fehler statt Hilfetext-Schluesselwoertern
  und laeuft vor der Ansagenerzeugung.
- Installerfrage: „Wartemusik von Johannes Plachetka installieren?“.

## 2.5.4

- Vermittlungsuebergabe der T2med-Middleware vollstaendig im Installer und
  Dialplan umgesetzt: private Zielpruefung, BlindTransfer, native Rueckfrage,
  Abschluss und Abbruch mit vorhandenen Kanal-Featurecodes.
- Tatsaechliche freigegebene PJSIP-Mitarbeiterkanaele erhalten Bereitschaft
  und passende Transferrechte bei Queue-, Direkt-, internen und ausgehenden
  Anrufen einschliesslich Click-to-Dial; Local-Zwischenwege werden beruecksichtigt.
- Externe Ziele verwenden gemeinsame Wahlregeln, Mitarbeiter-Provider,
  Praxis-Absendernummer und Kapazitaetspruefung. Fortschrittsereignis erst
  unmittelbar vor dem echten Dial, Ablehnung separat; kein Fehler beim normalen
  Besetzt/Nichtmelden oder beim Auflegen nach erfolgreicher Vermittlung.
- Installer prueft Asterisk-Faehigkeiten, plant und validiert Konfigurationen
  vor dem Schreiben und kontrolliert nach Reload die geladenen Kontexte.
  Bestehende Featurecodes, native Rueckkehrregeln und AMI-Zugaenge bleiben erhalten.
- Inland in internationaler Schreibweise folgt denselben Sperren wie nationale
  Nummern; freigegebene Auslandsnummern werden nicht als Ortsnummer umgedeutet.

- Die Queue nennt jetzt die eigene Warteposition: "Sie sind auf Position zwei
  in der Warteschlange." Asterisk liefert die Position einschliesslich des
  eigenen Anrufs; "Vor Ihnen warten noch zwei Anrufe" war deshalb falsch.
  Position eins bleibt "Sie sind als Naechstes an der Reihe."
- Beim Update wird das unveraenderte bisherige TTS-Textpaar gemeinsam ersetzt.
  Eigene Texte und manuelle Aufnahmen bleiben erhalten.

## 2.5.3

- Click-to-Dial fragt den tatsaechlichen PJSIP-Endpunkt korrekt ueber
  `CHANNEL(endpoint)` ab. Die bisherige Abfrage `CHANNEL(pjsip,endpoint)` lieferte
  unter Asterisk 20 einen leeren Wert und fuehrte nach dem Abheben zu Hangup(21).
- Leere oder abweichende Endpunkte bleiben abgewiesen; die angeforderte
  Nebenstelle wird nicht als Ersatzwert fuer die Kanalidentitaet verwendet.
- Der Click-to-Dial-Kontext verwendet Rufnummern-Einstiege statt `_.` und
  behandelt `h` separat ohne AGI. Auflegen startet keine erneute Freigabepruefung.
- Regressionstests pruefen den vollstaendigen AGI-Dialog einschliesslich der
  konkreten Endpunktabfrage, Antwortverarbeitung, Freigabe und Ablehnungsfaelle.

## 2.5.2

- AMI kann mit `quell_ip = "*"` alle Clients zulassen, die die konfigurierte
  VPN-Zieladresse erreichen. Benutzername, Secret und AMI-Rechte bleiben erhalten.
- Der Installer bietet die Auswahl bei externer Middleware an und erhaelt die
  bisherige Einzel-IP oder Stern-Auswahl bei wiederholten Laeufen als Vorgabe.
- Im Stern-Modus muessen saemtliche AMI-TCP-/TLS-Listener exakt an `server_ip`
  gebunden und Web-AMI deaktiviert sein. Konflikte werden vor Aenderungen an
  AMI-Dateien abgelehnt; fremde Integrationen werden nicht umkonfiguriert.
- UFW-Freigaben bleiben auf Zieladresse und Port begrenzt. Wechsel der
  Quellfreigabe und Deaktivierung entfernen die bisher verwaltete Regel;
  bestehende eigene AMI-Sitzungen werden bei einer Aenderung getrennt.
- Der TOML-Verbindungs-Export kennzeichnet die Freigabe mit
  `allowed_source_ip = "*"`. Vorhandene Einzel-IP-Konfigurationen bleiben kompatibel.

## 2.5.1

- Wartemelodie ist bei neuer Einrichtung vorausgewaehlt. Installer,
  Konfigurationsvorlage und Webinterface verwenden dieselbe Vorgabe;
  Klingelzeichen und bereits gespeicherte Entscheidungen bleiben erhalten.
- AMI-Verbindungs-Export auf `middleware-connection.toml` umgestellt.
  JSON-Altdateien werden unter Erhalt von Secret und Firewallregel migriert
  und mit Modus 0600 gesichert. Leser und Dokumentation sind angepasst.
- KI-Assistent ueber die Webinterface-Uebersicht dauerhaft ein-/ausschaltbar.
  Der Betriebsschalter laesst technische Anbindung, SIP-Zugaenge und laufende
  Gespraeche bestehen. Neue KI-Zulassungen werden auch bei interner Direktwahl
  oder veraltetem Dialplan blockiert; bestehende Rueckgaben bleiben moeglich.
- Reine KI-Schalterauftraege erzeugen keine Ansagen neu und benoetigen nur
  einen Dialplan-Reload. Kombinierte Auftraege melden Erfolg erst nach Reload.

## 2.5.0

- Optionale AMI-Middleware mit geschuetztem Verbindungs-Export, stabilen Secrets,
  IP-ACL, erhaltener Fremdkonfiguration und separater Telefonfreigabe.
- Einmaliger eingehender Namenslookup mit maximal einer Sekunde Wartebudget
  und Click-to-Dial ueber die vorhandenen Wahlregeln und Providerwege.
- Optionale Wartemusik von Johannes Plachetka, native G.722-/16-kHz-Formate,
  interne Hoerprobe 8805 und Umschaltung Melodie/Klingelzeichen im Webinterface.
- Warteschlangenansagen samt deutschen Zahlenfragmenten aus der ausgewaehlten
  TTS-Stimme oder eigener Aufnahme; eigener Sprachordner ohne Systemdatei-Ersatz.
- Interne Funktionsnummern dokumentiert, MIT-Lizenz und Musik-Urheberhinweis ergaenzt.

## 2.4.1

- Installerkorrektur: System- und Kokoro-Paketinstallationen warten bis zu
  300 Sekunden auf eine belegte dpkg-Sperre, statt bei einem parallelen
  `apt-get` sofort abzubrechen. Ein verbleibender Paketfehler bricht weiterhin ab.
- Kokoro-Thorsten als Standard fuer lokale, vorberechnete Ansagen; Piper und
  Qwen bleiben im Installer und Webinterface waehlbar.
- Eigenstaendige CPU-Umgebung mit den fixierten Kokoro-/Misaki-Staenden und
  dem Thorsten-Modell aus Kienzlefon-AI 2.6. Drei Modelldateien werden per
  SHA-256 geprueft; der Generator wird erst nach erfolgreicher Testansage aktiviert.
- Neuinstallation und Piper-Update bieten Kokoro als Vorauswahl an.
  Reine TOML-Migration ergaenzt fehlende Felder und behaelt explizite Engines.
- Engine, Modellrevision, Geschwindigkeit und Generatorstand werden im
  Ansagencache beruecksichtigt; manuelle Aufnahmen bleiben erhalten.
- Lange Texte werden vor der Synthese geteilt, ohne sie am Phonemlimit
  still abzuschneiden. Synthese nutzt ausschliesslich lokale Dateien.
- Hauptprogramm und Webinterface tragen gemeinsam Version 2.4.1.

## 2.4.0

- ein gueltiges, claim- und lease-gebundenes `super_priority`-Ergebnis wird nach
  persistentem Einmalverbrauch nicht erneut anhand der Fachstellenzeiten
  verworfen; `specialist_transfer_allowed` bleibt unveraendert Teil der AI-Policy
- `practice_queue` und `pharmacy_queue` bleiben zeitabhaengig, ein fehlender
  Policy-Provider bleibt fuer alle nichtklassischen Ziele fail-closed
- Taste `0` versucht Kienzlefon AI auch aus dem klassischen Hauptmenue lautlos;
  fehlende Kapazitaet fuehrt zurueck ins Menue, eine AI-Rekursion bleibt gesperrt
- `[ansagen_modus]` steuert Ansagen explizit mit `immer`, `offen`, `zu` oder
  `deaktiviert`; bestehende Konfigurationen erhalten nur fehlende Standardwerte
- deaktivierte Ansagen werden uebersprungen, waehrend die anschliessende
  Durchstellung oder Aufnahme unveraendert ausgefuehrt wird
- leere erforderliche Ansagentexte werden vor dem Austausch der TOML-Datei
  abgelehnt und lassen das Webinterface nicht mehr in einer laufenden Erzeugung
  haengen
- die Zeitseite zeigt Oeffnungszeiten, Telefonzeiten, `care_service` mit den
  genannten Versorgungsdiensten und `professional_urgent` mit den genannten
  Fachdiensten samt Hinweis auf das rote Telefon untereinander
- der neue Navigationspunkt „Anrufsbaum“ bietet Aktivierung, Deaktivierung und
  Audiovorschau als alternativen Zugriff auf die vorhandenen Ansagen
- das Webinterface gehoert zur Hauptversion, wird bei vorhandenen Installationen
  automatisch aktualisiert und zeigt Kienzlefon-Version, `kienzlefon.de` sowie
  „von Dr. Thomas Kienzle“ an
- Spezifikation v1.1 dokumentiert die unveraenderten Policy-Felder und die neue
  Behandlung bereits bestaetigter `super_priority`-Handoffs

## 2.3.2

- die Medienbridge zum angenommenen KI-Slot startet ohne eine vorgeschaltete
  Asterisk-`A()`-Ansage
- das vom KI-Backend unmittelbar erzeugte Greeting erreicht dadurch den Anrufer
  vollstaendig statt waehrend der noch getrennten Kanaele verloren zu gehen
- externe Anrufe und die Direktwahl ab `8810` verwenden denselben korrigierten
  Dialpfad
- die nicht mehr verwendete Hauptserver-Ansage `ai_assistant_intro` wurde aus
  Konfigurationsvorlage, Migration, Ansagenkatalog und Webinterface entfernt
- Taste `0` waehrend der Eingangsansagen beendet den Ansagenblock sofort und
  startet unmittelbar die AI-Zulassung; ohne freien Slot folgt das klassische
  Hauptmenue ohne eine ungueltige Null-Eingabe

## 2.3.1

- die Eingangsphase behandelt einen normalen Ablauf ohne Tastendruck wieder als
  erfolgreich und erreicht danach die AI-Admission
- der klassische Menuepfad startet auch ohne bereits gedrueckte Anfangstaste
  fehlerfrei
- Regressionstests decken beide DTMF-leeren Pfade ab

## 2.3

- Begruessung, alle drei Positionen der Sonderansage, Notfallansage und bei Bedarf
  Bereitschaftsdienstansage laufen unveraendert vor der AI-Zulassung
- die AI-Zulassung erfolgt genau an der bisherigen Stelle des klassischen Hauptmenues
- ein Tastendruck waehrend der Eingangsansagen bleibt vollstaendig im klassischen
  Kienzlefon; die bereits gedrueckte Taste wird als erste Menueeingabe verwendet
- die neue Ansage `ai_assistant_intro` wird erst nach Annahme einer freigemeldeten
  AI-Nebenstelle und vor dem Medienbridge abgespielt
- jede Anrufer-DTMF-Taste `0` bis `9`, `*` oder `#` im AI-Gespraech beendet das
  AI-Leg und wird unveraendert an das klassische Hauptmenue uebergeben
- der aktive AI-Publisher kann eine aktuelle, claim-gebundene Call-Policy mit Praxis-,
  Telefon-, Apotheken- und Fachstellenstatus sowie Wochenzeitprofilen abrufen
- Handoff-Ergebnisse werden vor positiver Bestaetigung atomar mit Modus `0600`
  gespeichert, kurz befristet und lokal genau einmal verbraucht
- nur `classic`, `practice_queue`, `pharmacy_queue` und `super_priority` werden fest
  auf `8801` bis `8804` abgebildet; dynamische Ziele und Handoffs nach Commit sind gesperrt
- ein fehlgeschlagenes bestaetigtes Queue-Ziel `8802` bis `8804` faellt hoechstens
  einmal auf `8801` zurueck; `8801` startet weder Rekursion noch erneute AI-Zulassung
- der Installer richtet den geschuetzten Result-Speicher und die DTMF-Features ein
- die vollstaendige JSONL-Laufzeitschnittstelle ist in
  `SPEZIFIKATION-KIENZLEFON-AI-RUNTIME-SCHNITTSTELLE-v1.0.md` festgehalten

## 2.2

- der Hauptinstaller fragt, ob Kienzlefon AI angebunden werden soll
- bei aktiver Anbindung wird die Anzahl der anzulegenden KI-Nebenstellen abgefragt
- die Nebenstellen beginnen bei `8810` und erhalten getrennte zufaellige SIP-Passwoerter
- der Admission-Listener laeuft auf dem Haupt-Kienzlefon und bindet ausschliesslich an eine konkrete Loopback-, WireGuard- oder LAN-IP
- der KI-Rechner baut die Verbindung aktiv auf und meldet alle Slots als `free` oder `not_free`
- nur eine aktuelle, einmalig atomar verbrauchte Freimeldungs-Lease erlaubt einen KI-Wahlversuch
- `not_free`, Lease-TTL, Publisher-Timeout und Verbindungsabbruch sperren neue KI-Anrufe fail-closed
- die internen Ziele `8800` bis `8804` und die direkten KI-Ziele ab `8810` werden im Asterisk-Dialplan erzeugt
- PJSIP-Header uebergeben Protokoll-, Request-, Lease- und Slot-ID an das spaetere AI-SIP-Gateway
- der Listener verwendet auf ausdrueckliche Vorgabe weder Anwendungsauthentifizierung noch TLS
- Spezifikation 1.4 beschreibt die verbindlichen JSONL-Kommandos

## 2.1.2

- `/run/kienzlefon-webinterface/state.json` wird nach jedem Systemstart neu aus der geschuetzten Konfiguration exportiert
- der Exportdienst ist nun selbst fuer `multi-user.target` aktiviert und laeuft nach `systemd-tmpfiles-setup.service`
- der Export wird vor dem schlanken PHP-Systemdienst sowie vor Apache und Nginx eingeordnet
- ein manueller Start des PHP-Systemdienstes zieht den Exportdienst ebenfalls als Abhaengigkeit heran
- damit faellt das Webinterface nach einem Reboot nicht mehr wegen fehlenden Laufzeitstatus auf Kennwortschutz zurueck
- Kienzlefon traegt die Patchversion 2.1.2, der separate Webinterface-Installer die Patchversion 1.1.2
- der Qwen3-TTS-Installer und seine Generator-Schnittstelle bleiben unveraendert auf v1.5

## 2.1.1

- der Kienzlefon-Hauptinstaller fragt bei jedem Lauf, ob das separate Webinterface installiert oder aktualisiert werden soll
- bei einer erkannten Webinterface-Installation lautet die Vorgabe `Ja`, bei einer Erstinstallation `Nein`
- nach Zustimmung wird genau der Webinterface-Installer aus demselben installierten Quellstand gestartet
- die bereits im Hauptinstaller gegebene Zustimmung wird uebernommen; es gibt keine doppelte Startabfrage
- Ablehnen ueberspringt ausschliesslich das Webinterface und beendet die Kienzlefon-Installation erfolgreich
- ein fehlender oder fehlerhafter Webinterface-Installer fuehrt zu einer eindeutigen Fehlermeldung
- Kienzlefon traegt die Patchversion 2.1.1, der separate Webinterface-Installer die Patchversion 1.1.1

## 2.1

- einzelne Qwen-TTS-Ansagen koennen im Webinterface gezielt als neue Variante erzeugt werden
- jeder erneute Versuch verwendet einen dauerhaft im Manifest gespeicherten Variantenwert und damit einen anderen Seed
- regulaere Ansagen, die einzelne Sonderansage und gespeicherte TTS-Sonderansagen werden unterstuetzt
- nur die ausgewaehlte Ansage wird verarbeitet; andere Ansagen und manuelle Aufnahmen bleiben unveraendert
- eine technisch fehlgeschlagene Variante ersetzt keine vorhandene Audiodatei
- `kienzlefon-ansagen --prompt NAME --new-variant` stellt dieselbe Funktion auf der Kommandozeile bereit
- `--all` verwendet bei Qwen nun ebenfalls neue Varianten statt derselben deterministischen Dateien
- das separate Webinterface traegt fuer diese Bedienfunktion die Version 1.1
- der neue WireGuard-KI-Client richtet einen auf die VPS-VPN-Adresse begrenzten Tunnel ohne Default-Route ein

## 2.0

- automatische Ansagen koennen global wahlweise mit Piper oder dem lokalen, nicht residenten Qwen3-TTS erzeugt werden
- der Hauptinstaller kann den fest freigegebenen Qwen3-TTS-Offline-Installer v1.5 laden und anhand seiner SHA-256-Pruefsumme verifizieren
- Erzeugungsmodell und Qwen-Sprecher werden bei der Installation abgefragt und zentral in `[tts]` gespeichert
- das separate Webinterface 1.0 kann Erzeugungsmodell und globalen Sprecher ebenfalls aendern
- unveraenderte Texte, Zeitprofile, Stimmen, Modelle und Audioquellen werden anhand eines Manifests erkannt und nicht erneut erzeugt
- bei einer Ueberinstallation ist eine ausdrueckliche Vollerzeugung aller automatischen Ansagen weiterhin moeglich
- fuer eine Qwen-Sammelerzeugung wird ein zuvor aktiver Whisper-Worker nur einmal gestoppt und nach Abschluss oder Fehler einmal wieder gestartet
- Wartungsmarker und gemeinsame Dateisperren verhindern neue Aufnahme- und ASR-Auftraege waehrend des Umschaltens
- manuelle Aufnahmen werden bei Modell- oder Sprecherwechsel weder geloescht noch ueberschrieben
- Terminal und Webinterface zeigen waehrend der Erzeugung Schrittzahl, aktuelle Ansage sowie Qwen-/Whisper-Umschaltphasen live an

## 1.9.3

- nach Abschluss aller Whisper-Auftraege wird geprueft, ob mindestens ein nicht leeres Transkript vorliegt
- Caller-ID, IVR-Kategorie, Standardzusammenfassung und technisch vorhandene stille WAV-Dateien gelten nicht als Inhalt
- vollstaendig inhaltslose fehlerfreie Vorgaenge werden intern als `ready` abgeschlossen, ohne eine Telepraxis-Datei zu erzeugen
- jedes vorhandene Teiltranskript fuehrt weiterhin zur normalen Ausgabe mit leeren uebrigen Feldern
- technische Fehlerausgaben und bestehende Fehlerwege bleiben unveraendert

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
