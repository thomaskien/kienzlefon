# Kienzlefon-Webinterface in Kienzlefon 2.7

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

Im Praxis-LAN kann der PHP-Systemdienst direkt an die feste private IPv4-Adresse
des Servers gebunden werden, beispielsweise `10.0.83.85`. Der vorgeschlagene
Port ist `8088`. Der Dienst verwendet unverschlüsseltes HTTP. Vorgabe ist ein Administratorkennwort. Auf Wunsch kann der Installer den Zugriff im privaten Praxisnetz ohne Kennwort einrichten. Dieser Betrieb ist nur innerhalb der Praxis zulässig.
Der Dienst darf keinesfalls aus dem Internet erreichbar sein. Keine Portfreigabe
oder öffentliche Proxy-Weiterleitung für das Webinterface einrichten.

Auf dem Server selbst ist der Zugriff über die Loopback-Adresse möglich. Bei
Apache und Nginx richtet der Installer für den Netzwerkzugriff ohne WireGuard
HTTPS ein. Auf einem aktiven WireGuard-Interface lässt sich der Dienst auf dessen
feste IPv4-Adresse beschränken und optional passwortlos betreiben.

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
`kienzlefon-config`, ersetzt die Konfiguration atomar und startet nach Änderungen an Ansagen oder Zeitprofilen die Ansagenerzeugung. Das reine Umschalten des KI-Assistenten, eine Google-Hörprobe und vorübergehende Rufgruppenwechsel haben eigene Abläufe. Shell-Befehle oder frei wählbare
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
den konfigurierten Ablauf, die Tastenwege, den lautlosen KI-Versuch (standardmäßig Taste `0`) und
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
Anlegen der Laufzeitverzeichnisse und vor dem Webserver aus. Der
passwortlose WireGuard-Modus bleibt dadurch auch nach einem Reboot wirksam.

Unter **Ansagen → Automatische Spracherzeugung** ist Kokoro · Thorsten der
Standard. Weitere Optionen sind Piper, Qwen3-TTS und Google Cloud TTS. Google benötigt den eingerichteten Generator und seine Konfigurationsdatei. [Google Cloud TTS einrichten](../docs/GOOGLE_TTS.md)

Die Auswahl erzeugt betroffene TTS-Ansagen neu und erhält
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

## Bedienung

In **Übersicht** ändert „Praxisname speichern“ den Namen für Texte mit dem Platzhalter `{praxisname}`. Eigene Aufnahmen behalten ihren gesprochenen Inhalt.

In **Anrufsbaum → Klassisches Hauptmenü** lassen sich die Ansagen ziehen oder mit den Pfeilen verschieben. Öffnungs-, Telefon- und Zugangszeiten bestimmen weiterhin, welche Ansagen ein Anrufer hört. Die zweite Sortierliste bestimmt die Reihenfolge der gesprochenen Tasten innerhalb der beiden Menütexte. Dafür wird TTS benötigt. Mit „Anrufsbaum speichern“ wird die Reihenfolge übernommen.

Unter **Ansagen → Google-Stimme testen** erzeugt „Beispielansage erzeugen“ eine einzelne Hörprobe mit dem eingetragenen Tempo. „Tempo speichern“ übernimmt den Wert für die künftige Erzeugung. „Ansagen speichern“ aktualisiert anschließend die Telefonansagen mit dem ausgewählten Erzeugungsmodell.

Unter **Rufgruppen** zeigt jede Nebenstelle die zuletzt bestätigte Teilnahme für Normal und ROT. „Jetzt anmelden“ und „Jetzt abmelden“ wirken bis zur nächsten Änderung oder zum Asterisk-Neustart. „Teilnahme als Standard“ legt den Startzustand fest. Zulassung, Rufstufe und externe Freigaben werden über „Rufgruppen speichern“ übernommen. Bei einem eigenen roten Telefon gilt die Teilnahme an ROT für das gemeinsame Klingeln nach dem ersten Rufversuch.

Zum Umbenennen die Nebenstelle aufklappen, den **Gerätenamen** ändern und **Rufgruppen speichern** wählen. Speichern übernimmt den Namen auch in die Asterisk-Anruferkennung. Der Name erscheint im Anlagenstatus, aus dem die Praxis-App ihre Rufgruppenanzeige bezieht.

Unter **Änderungen aus App und Middleware erlauben** gilt **Alle Arbeitsplätze (Standard)** für den authentifizierten Praxiszugang. **Nur ausgewählte Arbeitsplätze** akzeptiert die angegebenen Platz-IDs. Eine leere Auswahl sperrt alle. Der Dialog zeigt zusätzlich an, ob ein Schaltzugang eingerichtet ist und welche Beschränkungen er hat.
