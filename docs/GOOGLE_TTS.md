# Ansagen mit Google Cloud Text-to-Speech (Chirp 3 HD)

Optionale Engine `google`: Die automatischen Ansagen werden einmalig ueber die
Google-Cloud-API erzeugt und danach wie jede andere TTS-Ausgabe gecacht. Die
Engine braucht keine GPU. Verbrauch entsteht nur beim (Neu-)Erzeugen von Ansagen.

## Einrichtung

1. In der Google Cloud Console die **Cloud Text-to-Speech API** aktivieren und
   einen API-Schluessel anlegen, der nur diese API aufrufen darf. Ein
   Budgetlimit/Alarm einrichten.
2. **Per Installer (empfohlen):** `kienzlefon-installer.sh` bietet bei der Auswahl des
   Erzeugungsmodells Punkt *4) Google Cloud TTS* an. Er fragt den Schluessel (Eingabe
   unsichtbar), Stimme und Tempo ab, installiert den Generator nach
   `/usr/local/bin/kienzlefon-google-tts-generate` und schreibt
   `/etc/kienzlefon/google-tts.conf` (Rechte 0600, root). Ein vorhandener Schluessel
   kann beibehalten werden.

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
| `VOICE` | `de-DE-Chirp3-HD-Sulafat` | Stimme (Chirp 3 HD) |
| `LANG` | `de-DE` | Sprachcode |
| `RATE` | `0.93` | Sprechtempo 0,25 bis 2,0 |
| `ENDPOINT` | `texttospeech.googleapis.com` | API-Host |

Ein Wechsel von `VOICE`, `LANG` oder `RATE` erzeugt alle automatischen Ansagen neu.
Ein neuer `API_KEY` loest keine Neuerzeugung aus. Manuelle Aufnahmen bleiben erhalten.

## Hinweise

- Der Text der Ansagen wird an Google uebertragen (keine Patientendaten; nur die
  konfigurierten Ansagetexte). Bei Datenschutzbedenken die lokalen Engines nutzen.
- Der Server braucht ausgehenden HTTPS-Zugriff auf `texttospeech.googleapis.com`.
- Der API-Schluessel steht nur in der Konfigurationsdatei, nicht in `kienzlefon.toml`.
