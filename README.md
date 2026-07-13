<!--
kienzlefon
Version: 1.8.2
Changelog:
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

`kienzlefon` ist ein konfigurationsgesteuertes Asterisk-Telefonsystem fuer
Arztpraxen. Es setzt auf der Telefoniebasis von Kienzlefax auf, nimmt Angaben
feldweise als WAV auf, transkribiert lokal mit Whisper und legt jeden Vorgang
im Produktivmodus als verschluesselte Telepraxis-Datei ab.

Version: **1.8.2**

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
- `faster-whisper` mit getrennt konfigurierbaren Modellen fuer Namen,
  Medikamente und alle uebrigen Felder
- dateibasierter, atomarer Ordner-Spool ohne Datenbank
- OpenSSL-kompatible `AES-256-CBC`/RSA-Ausgabe als `*.json.enc`
- ausdruecklich zu bestaetigender Demomodus mit unverschluesselter `*.json`-Ausgabe
- lokale Piper-TTS-Ansagen in WAV, SLN16, G.722, A-law und mu-law
- telefonische Ansagenaufnahmen als normalisiertes 16-kHz-PCM
- Meldung jedes technisch erkannten Fehlers im konfigurierten Ausgabemodus
- gruppenschreibbare Telepraxis-Ausgabedateien mit Modus `0660`
- keine HTTP-Uebertragung und kein LLM in Version 1.8.2

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
Patientendaten verwendet werden. Seit Version 1.6 werden die
Whisper-Modelle fuer Namen, Medikamente und alle uebrigen Aufnahmen getrennt ab.
`large-v3-turbo` ist etwa dreimal so schnell und speichersparender;
`large-v3` kann bei Eigennamen genauer sein.

Bei einem Update kann die vorhandene Grundkonfiguration erhalten und separat
entschieden werden, ob die Zeitprofile neu konfiguriert werden sollen. Neu
eingegebene Zeiten werden nach dem Schreiben aus der TOML-Datei zurueckgelesen
und mit den Eingaben verglichen.
Fehlende 1.7-Eintraege werden dabei ergaenzt, vorhandene TOML-Werte nicht
ueberschrieben. Passwoerter unveraenderter Zusatztelefone bleiben erhalten.
Der Installer erklaert die priorisierte Sonderqueue und fragt, welche bereits
konfigurierten Zusatznebenstellen dort neben den normalen Queue-Telefonen
gleichzeitig klingeln sollen.

Die Installation laedt jedes konfigurierte Whisper-Modell genau einmal und die
konfigurierte Piper-Stimme. Bei weniger als 16 GB warnt der Installer vor der
gleichzeitigen Verwendung beider Whisper-Modelle, erlaubt sie aber nach
ausdruecklicher Bestaetigung.
Je nach Server und Internetanbindung kann dieser Schritt laenger dauern.

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
aktiviert oder auf Piper zurueckgeschaltet werden. Ausserdem laesst sich der
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
Lautheitsnormalisierung. Dieselbe Masterung gilt auch fuer Piper-Ansagen. Die
Standardwerte unter `[tts]` sind:

```toml
ziel_lautheit_lufs = -19.0
max_true_peak_db = -2.0
```

Damit bleiben manuelle und automatisch erzeugte Ansagen in vergleichbarer
Lautstaerke, waehrend Spitzenpegel begrenzt werden. Patientenaufnahmen bleiben
signaltonfrei und verwenden unveraendert ihren bisherigen Aufnahmeweg.

Eine menschlich eingesprochene WAV-Datei unter
`/var/lib/kienzlefon/ansagen-upload/<ansagenname>.wav` ersetzt fuer diesen
Ansagenamen Piper. `kienzlefon-ansagen` prueft auch diese Dateien und erzeugt
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
