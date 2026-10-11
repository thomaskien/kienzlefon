# Kienzlefon-Webinterface in Kienzlefon 2.5.1

Das Webinterface gehoert zur Kienzlefon-Hauptversion und besitzt keine eigene
Produktversion mehr. Der Hauptinstaller aktualisiert eine vorhandene
Webinterface-Installation automatisch; bei einer Erstinstallation bleibt die
Aktivierung optional. Technisch besteht es weiterhin aus einer
einzelnen PHP-Datei und einem privilegierten, positivlistenbasierten Systemdienst. PHP kann die
geschützte Kienzlefon-TOML weder lesen noch direkt verändern.

## Installation

Auf dem Kienzlefon-Rechner im Quellverzeichnis als root ausführen:

```bash
sudo ./kienzlefon-webinterface-installer.sh
```

Der Installer bietet drei Betriebsarten an:

- eigener schlanker PHP-Systemdienst,
- Apache mit eigener Site-Konfiguration,
- Nginx mit eigener Site-Konfiguration.

Ist ein aktives WireGuard-Interface vorhanden, kann ausschließlich dessen feste IPv4-Adresse
verwendet und optional der passwortlose Betrieb gewählt werden. Ohne WireGuard ist ein Kennwort
zwingend; ein Zugriff außerhalb von `127.0.0.1` wird nur über Apache oder Nginx mit HTTPS
eingerichtet.

Das Klartextkennwort steht wie vereinbart in der geschützten Datei
`/etc/kienzlefon/kienzlefon.toml`:

```toml
[webinterface]
passwort = "hier-aendern"
```

Nach einer manuellen Änderung erzeugt der Aktualisierungsdienst automatisch den von PHP
verwendeten Hash. Das Klartextkennwort wird nicht in den für PHP lesbaren Status exportiert.

## Sicherheitsgrenze

Die PHP-Datei legt ausschließlich JSON-Aufträge in `/run/kienzlefon-webinterface/inbox` ab. Der
root-Dienst prüft eine feste Positivliste, validiert eine temporäre TOML mit
`kienzlefon-config`, ersetzt die Konfiguration atomar und startet danach immer
`kienzlefon-ansagen --config /etc/kienzlefon/kienzlefon.toml`. Shell-Befehle oder frei wählbare
Dateipfade werden nicht aus Webeingaben übernommen.

Text, aktive Audioquelle und die Aufnahmeaktion stehen für jede Ansage in einer gemeinsamen
Karte. Für eine Aufnahme wird die Nebenstelle einmal gewählt; danach ruft der jeweilige Knopf
direkt für genau diese Ansage an. Die Sonderansage besitzt dieselben Aufnahme- und
TTS-Umschaltmöglichkeiten auf ihrer eigenen Seite. Sperrt eine wirksame Sonderansage die normalen
Telefonzeiten, wird anschließend unabhängig von der Uhrzeit immer der Hinweis auf den ärztlichen
Bereitschaftsdienst abgespielt.

Die Zeitseite zeigt vier Bloecke untereinander: Oeffnungszeiten,
Telefonzeiten, `care_service` fuer Apotheke, Pflegeheim oder Pflegedienst und
`professional_urgent` fuer Arztpraxis, Krankenhaus, Rettungsdienst oder
Notarzt. Die technischen Abschnitte bleiben `[apothekenzeiten]` und
`[fachstellenzeiten]`; beim Prioritaetsweg wird auf das rote Telefon
hingewiesen.

„Anrufsbaum“ ist ein alternativer Zugang zu den vorhandenen Ansagen. Er zeigt
den festen Ablauf, die Tastenwege, den lautlosen AI-Versuch ueber Taste `0` und
den zeitabhaengigen Abschluss ohne Tasteneingabe. Ansagen koennen dort ohne
Warnabfrage aktiviert oder deaktiviert und unabhaengig vom Aktivstatus
abgespielt werden. Begruessungen und Notfallhinweis unterstuetzen die Modi
`immer`, `offen`, `zu` und `deaktiviert`.

Leere erforderliche Ansagentexte werden bereits vor dem atomaren Austausch der
TOML-Datei abgelehnt. Das ausdrueckliche Deaktivieren erfolgt stattdessen ueber
`[ansagen_modus]`.

Unter „Ansagen“ sind außerdem das globale TTS-Erzeugungsmodell und bei Qwen3-TTS einer der neun
freigegebenen Sprecher auswählbar. Ein Wechsel erzeugt alle automatischen TTS-Fassungen neu;
manuelle Aufnahmen werden weder überschrieben noch gelöscht. Ohne Text-, Modell- oder
Sprecheränderung beendet sich die Ansagenaktualisierung ohne Qwen-Start.

Bei einer aktiven Qwen-TTS-Quelle erzeugt „Noch einmal neu generieren“ nur für
die gewählte Ansage eine neue Variante. Das gilt auch für die einzelne
Sonderansage und gespeicherte TTS-Sonderansagen. Andere Ansagen werden nicht
angestoßen; bei einem technischen Fehler bleibt die vorhandene Datei aktiv.

Während einer laufenden Erzeugung aktualisiert die Statusanzeige fortlaufend die
Schrittnummer und den Namen der gerade verarbeiteten Ansage. Auch das Vorbereiten
und der Wiederanlauf des Whisper-Workers werden angezeigt; ein langer Qwen-Aufruf
bleibt dadurch nicht mehr als unbestimmter Hintergrundvorgang stehen.

Bei einem direkten Aufruf verlangt der technische Installationshelfer weiterhin seine eigene Bestätigung.
Nach einer bereits bestätigten Auswahl im Hauptinstaller entfällt ausschließlich diese doppelte
Startfrage; Betriebsart, Netzwerkbindung und Zugriffsschutz werden weiterhin interaktiv festgelegt.

Der von PHP benoetigte Laufzeitstatus liegt absichtlich unter `/run` und wird
bei einem Neustart geloescht. Der Installationshelfer fuehrt
`kienzlefon-webinterface-refresh.service` deshalb bei jedem Boot nach dem
Anlegen der Laufzeitverzeichnisse und vor dem Webserver ausgefuehrt. Der
passwortlose WireGuard-Modus bleibt dadurch auch nach einem Reboot wirksam.

Unter **Ansagen → Automatische Spracherzeugung** ist Kokoro · Thorsten der
Standard. Piper und Qwen bleiben auswählbar; Kokoro und Qwen setzen ihre lokale
Installation voraus. Die Auswahl erzeugt betroffene TTS-Ansagen neu und erhält
manuelle Aufnahmen. Kokoro wird mit dem Hauptinstaller eingerichtet.

## KI-Assistent ab 2.5.1

In der **Uebersicht** zeigt die Karte **KI-Assistent** den Zustand Ein, Aus oder
Nicht eingerichtet. Bei eingerichteter KI-Anbindung den Schalter setzen und
**KI-Assistent speichern** waehlen. Die Auswahl steht dauerhaft als
`[ki_integration].assistent_aktiv` in der TOML-Datei. Die technische Aktivierung,
Nebenstellen und Passwoerter bleiben unveraendert.

Ausgeschaltet werden neue Anrufe nach den bisherigen Regeln im klassischen
IVR verarbeitet. Laufende Gespraeche werden nicht abgebrochen. Fuer die reine
Umschaltung werden keine Ansagen erzeugt und weder Asterisk noch der
Admission-Listener neu gestartet. Ohne eingerichtete Anbindung zeigt die Karte
einen Hinweis auf die Einrichtung im Hauptinstaller.

Wartemusik ist bei neuer Einrichtung als Melodie vorausgewaehlt; eine bereits
gespeicherte Auswahl wird durch ein Update nicht ueberschrieben.
