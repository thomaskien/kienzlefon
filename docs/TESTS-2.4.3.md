# Pruefung Kienzlefon 2.4.3

Geprueft am 09.10.2026 unter macOS mit Python 3.12. Der saubere
Veroeffentlichungskandidat enthaelt keine unabhaengigen lokalen SMS-Arbeiten.

- `python -m pytest -q`: **259 Tests bestanden**, einschliesslich der lokalen
  Loopback-Testserver. Die gezielte Kokoro-/Installer-Pruefung bestand mit
  **68 Tests**.
- 13 neue Tests pruefen die automatische Python-Bereitstellung: Auswahl eines
  geeigneten vorhandenen Interpreters, Fallback bei ausschliesslichem
  System-Python 3.13, Versionspruefung mit echten SSL-/venv-/ensurepip-Imports,
  atomare Bereitstellung, Wiederverwendung und Zugriffsrechte bei `umask 0077`.
- Falsche Downloadpruefsumme, unterbrochener Download und fehlgeschlagener
  Laufzeittest hinterlassen keine aktive Teilinstallation; Wiederholung ist
  getestet. Pfadtraversierung und Symlinks aus dem Archiv heraus werden
  abgewiesen.
- Das echte Linux-x86_64-Archiv fuer CPython 3.12.15 (Build 20261009) wurde
  heruntergeladen: **34.304.557 Bytes**, SHA-256
  `ffa8f85f1b56e88b687f08d743d817015524b86a9365fd921243132b80f1a36d`.
  Python-Binaerdatei, venv und ensurepip sind enthalten. Version, URL und
  Pruefsumme sind in `scripts/kokoro/python_manifest.json` fixiert.
- Shellsyntax beider Installer, PHP-Syntax, Ruff (E4/E7/E9/F, Python 3.11)
  fuer die geaenderten Python-Dateien und `git diff --check` erfolgreich.

Eine vollstaendige Linux-Installation oder Kokoro-Inferenz wurde lokal nicht
ausgefuehrt. Das Linux-Archiv laesst sich auf dem hier verwendeten, Gross- und
Kleinschreibung nicht unterscheidenden macOS-Dateisystem nicht vollstaendig
entpacken: Terminfo-Namen wie `N/NCR260VT300WPP` und `n/ncr260vt300wpp` kollidieren.
Die Entpack-/Fehlerpfade wurden daher mit isolierten Testarchiven geprueft.
Auf dem Linux-Ziel prueft der Installer den bereitgestellten Interpreter vor
Uebernahme und anschliessend die echten Kokoro-Abhaengigkeiten, Modelle und
eine Testansage vor Aktivierung des Generators.
