# Kienzlefon-Webinterface 1.0

Diese Fassung wird bewusst getrennt vom Hauptinstaller installiert. Sie besteht aus einer
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

Unter „Ansagen“ sind außerdem das globale TTS-Erzeugungsmodell und bei Qwen3-TTS einer der neun
freigegebenen Sprecher auswählbar. Ein Wechsel erzeugt alle automatischen TTS-Fassungen neu;
manuelle Aufnahmen werden weder überschrieben noch gelöscht. Ohne Text-, Modell- oder
Sprecheränderung beendet sich die Ansagenaktualisierung ohne Qwen-Start.

Die Installation verändert den bisherigen Hauptinstaller nicht. Eine Übernahme dorthin ist erst
nach dem Praxistest vorgesehen.
