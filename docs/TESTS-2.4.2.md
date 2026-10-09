# Pruefung Kienzlefon 2.4.2

Geprueft am 09.10.2026 unter macOS mit Python 3.12. Der vollstaendige
Veroeffentlichungskandidat wurde aus dem bisherigen Git-Stand und den
Releaseaenderungen aufgebaut; unabhaengige lokale SMS-Arbeiten sind nicht
enthalten.

- `python -m pytest -q`: **246 Tests bestanden**. Lokale Loopback-Testserver
  waren fuer diesen Lauf erlaubt.
- 32 neue Tests pruefen ausgeschriebene deutsche Zahlen und Uhrzeiten,
  einschliesslich `08:05`, `8 Uhr 05`, `08.30 Uhr`, `1 Uhr` und `24:00 Uhr`.
- Alle drei TTS-Engines erhalten den ausgeschriebenen Text. Numerische
  Engine-Parameter, Dateipfade und Pausendauern bleiben unveraendert.
- Oeffnungs-/Telefonzeiten und Vorschauen nutzen dieselbe Umwandlung.
- Ein Update mit einem alten Manifest ersetzt betroffene TTS-Ausgaben ohne
  `--all` und behaelt manuelle Aufnahmen sowie unveraenderte Texte bei.
  Ein zweiter Lauf erzeugt diese Ansagen nicht erneut.
- Gespeicherte geplante TTS-Sonderansagen werden im selben Lauf zusammen mit
  ihren aktiven Audioausgaben aktualisiert. Der Test verwendet den echten
  Ansagenkatalog und prueft die anschliessende Wiederverwendung.
- Shellsyntax beider Installer, PHP-Syntax der Administration, Ruff
  (E4/E7/E9/F, Python 3.11) fuer die geaenderten Python-Dateien und
  `git diff --check` sind erfolgreich.

Die neuen Synthesetests pruefen Textuebergabe und Updateverhalten mit
simulierter Spracherzeugung. Eine echte Modellinferenz oder telefonische
Hoerpruefung wurde lokal nicht durchgefuehrt. Kokoro-Modell, CPU-Lockdatei
und eigenstaendige Runtime bleiben auf dem bereits veroeffentlichten Stand.
