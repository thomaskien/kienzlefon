<!--
kienzlefon
Version: 1.8.3
Changelog:
- 1.8.3: Fortsetzung aller Feldaufnahmen trotz schweigend uebersprungener Felder dokumentiert.
- 1.8.2: Bereitschaftsdienst vor erster und nach letzter Tagesoeffnung dokumentiert.
- 1.8: Verhalten bei Abbruch vor der ersten Aufnahme dokumentiert.
- 1.7.1: Weiteres Klingeln des roten Telefons in der Sonderqueue dokumentiert.
- 1.7: Optionales Rottelefon und priorisierte Sonderqueue dokumentiert.
- 1.5: Signalton und normalisierte 16-kHz-Ansagenaufnahme dokumentiert.
- 1.4: PIN entfernt und unbegrenzte Fuenf-Sekunden-Wiederholung dokumentiert.
- 1.3: Telefonzeit-Wochenende und internes Ansagen-IVR dokumentiert.
- 1.2: Zusammengefasste Oeffnungs- und Telefonzeitansagen dokumentiert.
- 1.1: Menueeinleitung, Aufnahmeabschluss und Notfallfallback dokumentiert.
- 1.0: Freigegebenen IVR-Ablauf dokumentiert.
-->

# IVR-Ablauf

## Hauptmenue

- Taste 1: bestehende Praxisqueue, nur waehrend der Telefonzeiten
- Taste 2: Rezeptbestellung
- Taste 3: Ueberweisung
- Taste 4: Termin
- Taste 5: Untermenue fuer Rueckrufbitte oder sonstiges Anliegen
- Taste 6: regulaere Praxisoeffnungszeiten der gesamten Woche
- Taste 8: Apotheke mit erhoehter Prioritaet in der Praxisqueue
- Taste 9: Fachstelle zum roten Telefon oder direkt zur priorisierten Sonderqueue

Nach Taste 5 waehlt Taste 1 die Rueckrufbitte und Taste 2 das sonstige
Anliegen. Das Hauptmenue wird zweimal angeboten. Taste 6 kehrt zum Hauptmenue
zurueck und verbraucht keinen dieser beiden Durchlaeufe.

Vor jedem Menue-Durchlauf fordert eine eigene Ansage zur Tastenauswahl auf.
Zwischen den einzelnen IVR-Ansagen liegt standardmaessig eine Pause von 700
Millisekunden. Auch waehrend dieser Pause werden Tastendruecke angenommen.

Ohne Auswahl wird waehrend der Telefonzeiten zur Queue verbunden. Ausserhalb
der Telefonzeiten folgt eine einzige zusammenhaengende Rueckrufaufnahme. Dabei
bleiben die strukturierten Personenfelder leer und das vollstaendige
Transkript wird in `grund` geschrieben.

## Aufnahmen

Vorname, Nachname und Geburtsdatum werden getrennt aufgenommen. Das
Geburtsdatum wird als Tag, Monat und Jahr abgefragt und ohne Interpretation als
Whisper-Text uebernommen. Eine Telefonnummer wird nur aufgenommen, wenn keine
Caller-ID uebermittelt wurde.

Rezeptmedikamente werden einzeln aufgenommen. Taste 1 fuegt ein weiteres
Medikament hinzu, Taste 2 beendet die Liste. Fehlende Auswahl oder Auflegen
sind ebenfalls normale Abschluesse. Die Transkripte werden mit Zeilenumbruechen
in `medikamente` verbunden.

Bei Ueberweisungen werden `fachrichtung` und `grund` getrennt aufgenommen.
Termin, Rueckruf und sonstiges Anliegen verwenden jeweils ihr festgelegtes
Inhaltsfeld.

Schweigen bei einem einzelnen Personenfeld gilt als fehlende Angabe. Die
folgenden Personenfelder und das eigentliche Vorgangsfeld werden trotzdem
aufgenommen. Der Worker verarbeitet alle vorhandenen Aufnahmen; leere
Einzeltranskripte erzeugen keinen technischen Fehler und blockieren keine
spaeteren Inhalte. Im fertigen JSON bleiben nicht genannte Felder leer.

Eine laengere Stille beendet standardmaessig die Aufnahme. Zusaetzlich beendet
jede DTMF-Taste die aktuelle Aufnahme. Die Taste wird verbraucht. Asterisk
behaelt mit der Record-Option `k` auch beim Auflegen alle bis dahin
geschriebenen Audiodaten. Die Aufnahme startet ohne Signalton unmittelbar nach
der jeweiligen Feldansage.

Wird aufgelegt, bevor eine verwertbare Aufnahme entstanden ist, wird kein
leerer Vorgang ausgegeben. Bereits vorhandene Aufnahmen bleiben erhalten.
Technische Fehler werden auch ohne Aufnahme weiterhin gemeldet.

Nach einer vollstaendigen Aufnahme wird „Vielen Dank und bis bald!“ abgespielt.
Anschliessend endet das Gespraech; es erfolgt keine Weiterleitung in die Queue.
Bei Rezepten wird vorher die konfigurierte Rezeptinformation gesprochen.

Ist das rote Telefon aktiviert, klingelt es standardmaessig 20 Sekunden. Wird
der Anruf nicht angenommen, ist besetzt oder das Endgeraet nicht erreichbar,
faellt der Anruf mit `QUEUE_PRIO=100` in die priorisierte Sonderqueue. Ist das
rote Telefon zu diesem Zeitpunkt verfuegbar, klingelt es dort gemeinsam mit allen
normalen Queue-Telefonen und den im Installer ausgewaehlten Zusatznebenstellen
erneut. Ist kein rotes Telefon aktiviert, beginnt diese Sonderqueue unmittelbar
und enthaelt kein Rottelefon-Mitglied. Die normale Queue `praxis` bleibt
unveraendert.

## Zeitlogik

Praxisoeffnungszeiten steuern die Begruessung mit `geoeffnet` oder
`geschlossen`. Telefonzeiten steuern ausschliesslich Taste 1. Vor der ersten
und nach der letzten Praxisoeffnungszeit des Tages sowie an vollstaendig
geschlossenen Tagen wird auf 116117 hingewiesen. Zwischen zwei Oeffnungsbloecken
bleibt der Hinweis aus. Die Nummern werden als `eins eins zwei` beziehungsweise
`eins eins sechs, eins eins sieben` gesprochen.

Ein aktiver Feiertags-Override ersetzt die normale Begruessung. Optional sperrt
er zugleich Taste 1 und die Ansage der regulaeren Telefonzeiten. Taste 6 nennt
weiterhin die regulaeren Wochenoeffnungszeiten.

Identische Vormittagsoeffnungszeiten von Montag bis Freitag werden als „jeden
Werktag vormittags“ zusammengefasst. Nur vorhandene Nachmittagszeiten werden
tageweise angesagt. Sind Samstag und Sonntag leer, lautet der gemeinsame
Hinweis „An Wochenenden ist die Praxis geschlossen.“ Identische Telefonzeiten
von Montag bis Freitag werden als „werktäglich“ zusammengefasst.
Sind auch dort Samstag und Sonntag leer, lautet die gemeinsame Ansage:
„Am Wochenende sind wir telefonisch nicht erreichbar.“

## Internes Ansagen-IVR

Nebenstelle `777` ist ausschliesslich intern erreichbar und besitzt keine
PIN-Abfrage. Nach Auswahl einer stabilen Ansagenummer kann die aktive Fassung
angehoert, eine neue Fassung ohne Signalton aufgenommen, als Kandidat
kontrolliert und aktiviert werden. Die Rueckschaltung auf die generierte
Piper-Fassung ist jederzeit moeglich. Die Feiertags- und Sonderansage kann
aktiviert, deaktiviert und wahlweise mit einer Sperrung der Telefonzeiten
verbunden werden.

Hauptmenue, Ansagenummernauswahl, Aktionsmenue und Sonderansagenmenue warten
jeweils fuenf Sekunden auf eine Eingabe. Ohne Eingabe wird die vollstaendige
Anweisung unbegrenzt wiederholt. Eine Zeitueberschreitung trennt das Gespraech
nicht. Taste `0`, Auflegen oder ein technischer Verbindungsabbruch beenden den
jeweiligen Ablauf.

Bei einer neuen Ansagenaufnahme ertönt unmittelbar vor Aufnahmebeginn ein
Signalton. Die Aufnahme wird als `wav16` mit 16 kHz erfasst und vor dem ersten
Anhören auf die konfigurierte Sprachlautheit normalisiert. Die Vorschau
entspricht damit bereits der aufbereiteten Fassung. Diese Regel gilt nur für
die interne Ansagenverwaltung; Patientenaufnahmen starten weiterhin ohne
Signalton.
