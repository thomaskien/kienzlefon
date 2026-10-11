# Releasepruefung 2.5.0

Stand: 11.10.2026. Lokale Releasepruefung vor dem GitHub-Upload.

- **312 Tests bestanden** (25,33 Sekunden), gesamte Kienzlefon-Testsuite.
  Die lokal separat vorhandenen, noch nicht veroeffentlichten SMS-Tests und
  SMS-Arbeiten gehoeren nicht zu diesem Release und wurden ausgeschlossen.
- Bash-Syntax beider Installer und PHP-Syntax des Webinterfaces geprueft.
- Neue Middleware-, Musik- und Zahlenmodule mit Ruff (F/I) geprueft.
- Python-Wheel `kienzlefon-2.5.0-py3-none-any.whl` erfolgreich gebaut;
  Version, neue Module und enthaltene MIT-Lizenzmetadaten kontrolliert.
- Originalmusik real mit FFmpeg verarbeitet; WAV16, SLN16, G.722, A-law und
  mu-law vollstaendig und fehlerfrei dekodiert. WAV16: mono, 16 Bit, 16 kHz,
  etwa 41,14 Sekunden. Kein falsch benanntes 16-kHz-`.wav` im MOH-Verzeichnis.
- Wiederholte Asterisk-Konfiguration, Wechsel Musik/Klingelzeichen, Schutz
  fremder Konfiguration, stabile Ansagennummern und manuelle Zahlenaktivierung
  durch Tests abgedeckt.
- AMI-Tests fuer Dateirechte, Secrets, Wiederholung, Deaktivierung, Rotation,
  bestehende Listener/TLS/Benutzer, IPv6, Firewallregelverwaltung, Telefonabfrage,
  externe Hooks und Click-to-Dial-Validierung bestanden.

## Noch auf der Telefonanlage pruefen

Es wurde kein Live-Deployment und kein produktiver Anruf ausgefuehrt. Die
Asterisk-Dialplanpruefungen kontrollieren hier die generierte Konfiguration;
Zeitverhalten und echte AMI-/SIP-Ereignisse benoetigen den Anlagentest.

1. Installer ausfuehren, Wartemusik einrichten und zunaechst Klingelzeichen
   belassen. Von intern 8805 anrufen, Browser-Hoerprobe pruefen.
2. Melodie im Webinterface speichern, Praxis- und Sonderqueue anrufen;
   zurueck auf Klingelzeichen schalten. Laufende Gespraeche beobachten.
3. Neue Queue-Ansagen, einschliesslich Positionszahlen, anhoeren. Einen Baustein
   selbst aufnehmen, aktivieren und wieder auf TTS stellen.
4. Middleware anhand der geschuetzten Exportdatei verbinden. Die konkreten
   Lookup-, Grenzzeit-, Click-to-Dial- und Widerrufstests stehen in
   [MIDDLEWARE.md](MIDDLEWARE.md#pruefung-auf-der-telefonanlage).
5. Installer ein zweites Mal ausfuehren: Vorgaben, Secret und vorhandene
   fremde AMI-Zugaenge muessen erhalten bleiben.
