# Übergabe: Kienzlefon – Qwen3-TTS-Offlinemodus integrieren

- **Stand:** 13. August 2026
- **Qwen-Ausgangspunkt:** `install-kienzlefon-qwen3-tts-v1.5.sh`
- **Zielprojekt:** klassisches Kienzlefon
- **Kienzlefon-Schnittstellenstand:** `2.1.2`
- **Webinterface-Installer:** `1.1.2`
- **Qwen3-TTS-Installer und Generator-Schnittstelle:** `v1.5` (unverändert)
- **Status:** Im klassischen Kienzlefon und seinem Webinterface integriert.

## Ziel

Das klassische Kienzlefon soll statische Ansagen mit dem lokal installierten
Qwen3-TTS-0.6B-CustomVoice-Modell erzeugen können. Qwen wird nur für einen
Auftrag gestartet und anschließend vollständig beendet. Es gibt keinen
residenten Qwen-Prozess, keinen Qwen-HTTP-Dienst und keinen neuen Port.

Auf den Debian-Zielsystemen belegt der residente CPU-Whisper-Worker einen großen
Teil des Arbeitsspeichers. Der Qwen-Generator übernimmt deshalb selbst den
kontrollierten Ablauf:

```text
Wartungsmarker setzen
→ laufende Aufnahme/Verarbeitung ausschließen
→ vorher aktive ASR-Units stoppen
→ mindestens 5 GiB MemAvailable prüfen
→ Qwen über CUDA oder CPU ausführen
→ WAV prüfen
→ vorher aktive ASR-Units wieder starten
→ neuen Whisper-Heartbeat verifizieren
→ WAV atomar aktivieren
→ Wartungsmarker entfernen
```

## Bereitgestellte Schnittstelle

Der Installer erzeugt:

```text
/usr/local/bin/kienzlefon-qwen3-tts-generate
```

Beispiel:

```bash
sudo /usr/local/bin/kienzlefon-qwen3-tts-generate \
  --text "Unsere Praxis ist heute geschlossen." \
  --output /var/lib/kienzlefon/ansagen-master/beispiel.wav
```

Parameter:

- erforderlich: `--text`, `--output`
- optional: `--speaker`, `--language`, `--seed`, `--force`
- Standard: Sprecher `ryan`, Sprache `German`, Seed `42`
- Ausgabe: WAV, PCM S16LE, 24.000 Hz, mono
- vorhandene Zieldateien werden ohne `--force` nicht ersetzt

Der Generator bevorzugt eine installierte und zur Laufzeit funktionsfähige
CUDA-Binary. Schlägt CUDA fehl, wird genau einmal mit der unabhängigen
CPU-Binary wiederholt.

## Bereits im Generator implementierte Sicherungen

- feste, bei der Installation ermittelte Positivliste pausierbarer Units
- klassisches Kienzlefon: `kienzlefon-worker.service`
- Kienzlefon AI: Stop-Reihenfolge Gateway vor Backend; Start in Gegenrichtung
- nur zuvor aktive Units werden wieder gestartet
- `systemctl stop`, kein `SIGSTOP` und kein direktes Töten der Python-PID
- Stop-Timeout 60 Sekunden
- Readiness-Timeout 300 Sekunden
- Prüfung von `systemctl is-active` und `MainPID`
- beim klassischen Worker zusätzlich neuer Heartbeat mit passender neuer PID
- Abbruch bei `recording > 0` oder `processing > 0`
- `queue` darf liegen bleiben
- globaler Generierungs-Lock
- Wartungsmarker `/run/kienzlefon/asr-maintenance`
- mindestens 5 GiB `MemAvailable` erst nach dem Worker-Stopp
- temporäre Qwen-Logs werden nach dem Auftrag gelöscht
- Eingabetexte werden nicht in normale Logs geschrieben
- temporäre WAV auf demselben Dateisystem
- Prüfung auf PCM S16LE, 24 kHz, mono
- Wiederherstellung der ASR auch bei Qwen-Fehler oder Signal
- Aktivierung der WAV erst nach erfolgreicher ASR-Wiederherstellung
- bei Wiederanlauffehler bleibt der Wartungsmarker bestehen

## Bestehender privilegierter Auftragsweg

Der vorhandene Weg soll beibehalten werden:

```text
Browser/PHP als www-data
→ validierter JSON-Auftrag unter /run/kienzlefon-webinterface/inbox
→ kienzlefon-webinterface-worker.service als root
→ fest positiv gelistete Qwen-Aktion
→ kienzlefon-qwen3-tts-generate
```

Kein `sudo` aus PHP, keine Shellbefehle aus HTTP-Parametern und keine vom Browser
übergebenen Dienst- oder Dateipfade.

## Im klassischen Kienzlefon umgesetzte Anbindung

### 1. Wartungsmarker im IVR beachten

Vor Beginn einer neuen strukturierten Aufnahme muss das IVR zusätzlich prüfen:

```text
/run/kienzlefon/asr-maintenance
```

Ist der Marker vorhanden, wird der Anrufer wie bei einem nicht bereiten
Whisper-Worker zur vorgesehenen Praxisqueue umgeleitet. Asterisk selbst und
normale Praxisgespräche bleiben unberührt.

Die vorhandene Healthcheck-Prüfung bleibt zusätzlich bestehen. Der Marker darf
nicht bewirken, dass `kienzlefon-status` den tatsächlich noch bereiten Worker
vor dessen Stop fälschlich als defekt meldet; der Generator benötigt die
Statuszählung nach dem Setzen des Markers.

### 2. Wartungsmarker im Worker beachten

Der klassische Worker darf bei gesetztem Marker keinen neuen Queue-Auftrag
beanspruchen. Einen bereits verarbeiteten Auftrag beendet er kontrolliert.

Dadurch kann der Generator nach dem Setzen des Markers zuverlässig prüfen:

```text
recording == 0
processing == 0
```

Vorhandene `queue`-Aufträge bleiben liegen und werden nach dem Neustart weiter
verarbeitet. Recovery-, Verschlüsselungs- und Fehlerlogik bleiben unverändert.

### 3. Positiv gelistete Webinterface-Aktion ergänzen

Im Root-Webinterface-Worker ist eine feste Aktion für Qwen-Ansagen zu ergänzen.
Der HTTP-Auftrag darf nur fachliche Daten enthalten, insbesondere:

- fest erlaubte Ansagenkennung
- validierten TTS-Text
- optional eine fest definierte Sprecher-/Sprachauswahl

Nicht aus dem Auftrag übernommen werden dürfen:

- Shellkommando oder zusätzliche CLI-Argumente
- systemd-Unit
- Ausgabe- oder Konfigurationspfad
- Modell- oder Binary-Pfad
- Umgebungsvariablen

### 4. Zielpfade ausschließlich aus der TOML ableiten

Vorgesehene Pfade:

```text
/var/lib/kienzlefon/ansagen-master/<ansagenname>.wav
/var/lib/kienzlefon/ansagen-master/sonderansagen/<id>/tts.wav
```

Telefonieformate bleiben Aufgabe der bestehenden Kienzlefon-Audioschicht:

```text
/var/lib/asterisk/sounds/kienzlefon/<ansagenname>.sln16
/var/lib/asterisk/sounds/kienzlefon/<ansagenname>.g722
/var/lib/asterisk/sounds/kienzlefon/<ansagenname>.alaw
/var/lib/asterisk/sounds/kienzlefon/<ansagenname>.ulaw
```

24-kHz-Qwen-Audio darf niemals nur als 16 oder 8 kHz deklariert werden. Die
bestehende Normalisierung muss echtes Resampling durchführen.

### 5. Eigentümer, Rechte und atomare Aktivierung

- temporäre Dateien zunächst `0600`
- fertige Master- und Telefoniedateien `0644`
- Verzeichnisse `0755`, soweit die bestehende Kienzlefon-Konfiguration nichts
  Strengeres vorsieht
- vorhandene UID/GID beim Ersetzen erhalten
- bei neuen Dateien UID/GID des Zielverzeichnisses übernehmen
- Master und abgeleitete Telefonieformate zunächst vollständig im Staging
  erstellen und prüfen
- bestehende aktive Ansagen erst danach atomar ersetzen

Der Qwen-Generator selbst aktiviert seine einzelne Ziel-WAV bereits atomar und
stellt vorher die ASR wieder her. Die Aktivierung einer zusammengehörigen Gruppe
aus Master-WAV und Asterisk-Formaten bleibt Verantwortung der bestehenden
Kienzlefon-Audioschicht.

### 6. Serialisierung und Auftragsstatus

Der vorhandene `audio.lock` und die Serialisierung des Webinterface-Workers sind
weiterzuverwenden. Es darf nur eine Qwen-Instanz gleichzeitig laufen.

Die aktuelle Generator-Schnittstelle erzeugt genau eine WAV pro Prozess. Eine
spätere Batch-Schnittstelle, bei der das Modell nur einmal für mehrere Ansagen
geladen wird, wäre eine eigenständige Optimierung und ist nicht durch einen
temporären HTTP-Port zu simulieren.

Der Adminbereich benötigt klare Zustände:

- wartet
- Generierung läuft
- ASR wird wiederhergestellt
- erfolgreich
- fehlgeschlagen
- kritisch: ASR nicht wieder bereit

## Fehlerverhalten

- aktive Aufnahme oder Verarbeitung: Auftrag abbrechen, alte Ansage behalten
- Worker stoppt nicht innerhalb von 60 Sekunden: Qwen nicht starten
- weniger als 5 GiB verfügbar nach dem Stop: Qwen nicht starten, Worker
  wiederherstellen
- Qwen-/WAV-Fehler: Staging löschen, alte Ansage behalten, Worker
  wiederherstellen
- Worker wird nicht binnen 300 Sekunden bereit: neue Ansage nicht aktivieren,
  Wartungsmarker stehen lassen, kritischen Fehler anzeigen
- war der Worker vor Beginn inaktiv, darf er anschließend nicht gestartet werden

## Installationshinweis

`--offline-only` bedeutet keinen netzlosen Installer. Abhängigkeiten, Quellcode,
Binary und Modell werden vollständig installiert beziehungsweise erzeugt. Nur der
spätere Qwen-Betrieb ist nicht resident und portlos.

Der v1.5-Installer führt am Ende einmal einen echten Generierungstest über genau
den späteren Stop-/Generate-/Restart-Pfad aus. Vor dem ASR-Stopp blockiert geringer
freier RAM die Installation nicht. Erst nach dem Stop werden 5 GiB
`MemAvailable` verlangt.

IVR und Worker beachten den Wartungsmarker. Der Installationstest bleibt ein
Wartungsvorgang und sollte ohne aktive Kienzlefon-Aufnahme ausgeführt werden.

## Abnahmetests für die klassische Integration

1. Auftrag als `www-data` kann ausschließlich über die vorhandene Inbox erzeugt
   werden; kein direktes Root-/sudo-Kommando aus PHP.
2. Unbekannte Aktion, Ansagenkennung, Pfad, Unit oder Zusatzargument wird
   abgewiesen.
3. Wartungsmarker leitet neue strukturierte Anrufe zur Praxisqueue um.
4. Worker beansprucht bei Wartungsmarker keinen neuen Queue-Auftrag.
5. `recording > 0` und `processing > 0` verhindern den Qwen-Start.
6. `queue > 0` bleibt erhalten und wird nach dem Neustart verarbeitet.
7. Nur zuvor aktive Units werden gestoppt und wieder gestartet.
8. Qwen verwendet CUDA, wenn der Laufzeittest gelingt; sonst CPU.
9. Zu wenig RAM nach dem Stop verhindert Qwen und stellt die ASR wieder her.
10. Qwen-Fehler verändert keine bestehende Ansage.
11. Worker-Neustartfehler aktiviert keine neue Ansage und lässt den Marker
    bestehen.
12. Erfolgreicher Neustart verlangt aktiven Dienst, passende MainPID und neuen
    Heartbeat.
13. Ausgabedateien besitzen korrekte UID/GID und Modus `0644`.
14. WAV-Master ist PCM S16LE, 24 kHz, mono; Asterisk-Formate wurden tatsächlich
    resampelt.
15. Keine Eingabetexte, Transkripte oder Patientendaten erscheinen in normalen
    Logs oder Statusdateien.

## Nicht Teil dieser Übergabe

- Änderungen am Qwen-/Piper-Routing für Live-TTS
- ein persistenter Qwen-Dienst
- ein neuer TCP-Port
- Änderungen an Asterisk-Aufnahme oder normalen Praxisgesprächen
- Änderungen an Whisper-Modellen oder Transkriptionslogik
- automatische Swap-Einrichtung
- eine Batch-Erweiterung des nativen Qwen-CLI
