# Ansagen mit Google Cloud Text-to-Speech (Chirp 3 HD)

Optionale Engine `google`: Die automatischen Ansagen werden einmalig ueber die
Google-Cloud-API erzeugt und danach wie jede andere TTS-Ausgabe gecacht. Die
Engine braucht keine GPU. Verbrauch entsteht nur beim (Neu-)Erzeugen von Ansagen.

## Einrichtung

1. In der Google Cloud Console die **Cloud Text-to-Speech API** aktivieren und
   einen API-Schluessel anlegen, der nur diese API aufrufen darf. Ein Cloud-Budget kann beim Erreichen festgelegter Kostenschwellen benachrichtigen. Die Abrechnung läuft weiter. [Google-Budgetbenachrichtigungen](https://docs.cloud.google.com/billing/docs/how-to/budgets?hl=de)
2. **Per Installer (empfohlen):** `kienzlefon-installer.sh` bietet bei der Auswahl des
   Erzeugungsmodells Punkt *4) Google Cloud TTS* an. Er fragt den Schluessel (Eingabe
   unsichtbar), Stimme und Tempo ab, installiert den Generator nach
   `/usr/local/bin/kienzlefon-google-tts-generate` und schreibt
   standardmäßig `/etc/kienzlefon/google-tts.conf` (Rechte 0600, root). Bei
   **Google-API-Schlüssel (schon gesetzt)** übernimmt Enter den gespeicherten
   Schlüssel. Mit **n** lässt er sich ersetzen. Bei einem eigenen Pfad unter
   `[tts].google_konfig` verwendet der Installer die dort angegebene Datei.

   **Manuell:**

   ```bash
   sudo install -m 0755 scripts/google-tts/kienzlefon-google-tts-generate /usr/local/bin/
   sudo install -m 0600 -o root -g root scripts/google-tts/google-tts.conf.example /etc/kienzlefon/google-tts.conf
   sudoedit /etc/kienzlefon/google-tts.conf     # API_KEY eintragen
   ```

3. Danach im Webinterface unter *Ansagen → Automatische Spracherzeugung → Erzeugungsmodell* **Google Cloud TTS · Chirp 3 HD**
   waehlen und speichern, oder in `kienzlefon.toml`:

   ```toml
   [tts]
   engine = "google"
   ```

Die Auswahl ist erst moeglich, wenn Generator und Konfigurationsdatei vorhanden sind.

## Konfiguration (`/etc/kienzlefon/google-tts.conf`)

| Schluessel | Standard | Bedeutung |
|---|---|---|
| `API_KEY` | – | Google-Cloud-API-Schluessel |
| `VOICE` | `de-DE-Chirp3-HD-Enceladus` | Stimme (Chirp 3 HD) |
| `LANG` | `de-DE` | Sprachcode |
| `RATE` | `0.93` | Sprechtempo 0,25 bis 2,0 |
| `ENDPOINT` | `texttospeech.googleapis.com` | API-Host |

Ändern sich Stimme, Sprache oder das wirksame Sprechtempo, erzeugt der nächste Google-Generierungslauf die automatischen Ansagen neu. Ein im Webinterface gespeichertes Tempo hat Vorrang vor `RATE`.
Ein neuer `API_KEY` loest keine Neuerzeugung aus. Manuelle Aufnahmen bleiben erhalten.

## Hinweise

- Bei der Synthese wird der Ansagetext an Google übertragen. Verwende für diese Texte allgemeine Praxisinformationen. Bei Datenschutzbedenken die lokalen Engines nutzen.
- Der Server braucht ausgehenden HTTPS-Zugriff auf `texttospeech.googleapis.com`.
- Der API-Schluessel steht nur in der Konfigurationsdatei, nicht in `kienzlefon.toml`.

## Sprechtempo im Webinterface

Unter **Ansagen → Google-Stimme testen** lässt sich das Tempo zwischen 0,25 und 2,0 ausprobieren. Die Hörprobe sendet einen festen Beispieltext mit der eingerichteten Google-Stimme und dem ausgewählten Tempo. „Tempo speichern“ hinterlegt das Tempo unter `[tts].google_sprechtempo` in der Kienzlefon-Konfiguration. Bis dahin gilt `RATE` aus der Google-Konfiguration. Beim nächsten Google-Installerdialog erscheint das gespeicherte Tempo als Vorschlag und wird anschließend wieder als `RATE` übernommen. Über „Ansagen speichern“ lassen sich die aktiven Telefonansagen anschließend aktualisieren.
