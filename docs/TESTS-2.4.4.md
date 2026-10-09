# Pruefung Kienzlefon 2.4.4

Geprueft am 10.10.2026 unter macOS mit Python 3.12. Der saubere
Veroeffentlichungskandidat enthaelt keine unabhaengigen lokalen SMS-Arbeiten.

- `python -m pytest -q`: **265 Tests bestanden**, einschliesslich der lokalen
  Loopback-Testserver. Die gezielte Asterisk-/Codec-Pruefung bestand mit
  **13 Tests**.
- Sechs neue Regressionstests pruefen Konfigurationen mit einem, zwei und drei
  KI-Slots sowie Neuinstallation, Update alter G.711-Dateien und Neuerzeugung
  bereits auf dem Server korrigierter G.722-Dateien.
- Fuer jeden KI-Endpunkt sind die Codec-Zeilen exakt `disallow=all`,
  `allow=g722`, `incoming_call_offer_pref=local_first` und
  `outgoing_call_offer_pref=local_first`.
- Rotes Telefon, zusaetzliche Telefone und direkte Provider-Registrierungen
  behalten `allow=g722,alaw,ulaw`. Bestehende Kienzlefax-Provider-/Telefondateien
  mit G.711 werden bytegleich erhalten.
- Die Tests verwenden den echten CLI-Einstieg `kienzlefon-asterisk`, der auch
  vom Hauptinstaller aufgerufen wird. Nach erneutem Aufruf ist die erzeugte
  PJSIP-Datei bytegleich. Die Konfigurationsmigration und Erzeugung erhalten
  die vorhandenen TTS-Einstellungen und eine konfigurierte Pause von 1000 ms.
- Shellsyntax beider Installer, PHP-Syntax, Ruff (E4/E7/E9/F, Python 3.11)
  fuer die geaenderten Python-Dateien und `git diff --check` erfolgreich.

Die funktionale Aenderung liegt ausschliesslich in `_ai_endpoint()`.
Kokoro-Runtime, CUDA-/Modellinstallation und Pausenverarbeitung wurden nicht
geaendert. Ein erfolgreicher Live-Testanruf mit hoerbarer Antwort von Karl
wurde vom Betreiber bereits bei der Uebergabe des Server-Fixes bestaetigt.
Lokal wurden die erzeugten Konfigurationen geprueft; ein weiterer Live-Anruf
oder ein Eingriff in den bereits korrigierten Server erfolgte nicht.
