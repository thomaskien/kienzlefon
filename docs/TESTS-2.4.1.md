# Pruefung Kienzlefon 2.4.1

Lokale Pruefung unter macOS mit Python 3.12; Testabhaengigkeiten in einer
separaten temporaeren Umgebung. Kein Deployment und keine Aenderung laufender
Telefonie-/KI-Dienste.

- Sauberer Veroeffentlichungskandidat aus dem Git-Index, ohne unabhaengige
  lokale SMS-Arbeiten: `python -m pytest -q` — **210 Tests bestanden**.
  Loopback-Testserver waren fuer diesen Lauf erlaubt.
- Darunter 28 neue Kokoro-Tests fuer Default/Update, Konfigurationsvalidierung,
  Cache, lange Ansagen, Downloadpruefsummen sowie atomare Generator-/Audioausgabe.
- Der Piper-Update-Test startet mit bestehenden Piper-Masterdateien,
  Telefonieformaten und Manifest. Ein normaler Kokoro-Generierungslauf ohne
  `--all` ersetzt alle diese TTS-Dateien; ein zweiter Lauf ueberspringt sie.
- Die PHP-Rendertests pruefen die ausgewaehlte Engine fuer Kokoro, Piper und Qwen.
- `bash -n kienzlefon-installer.sh`, `bash -n kienzlefon-webinterface-installer.sh`
  und `php -l webinterface/admin.php` erfolgreich.
- Ruff (E4/E7/E9/F, Python 3.11) fuer geaenderte Python-Produktionsmodule und
  neue Kokoro-Tests sowie `git diff --check` erfolgreich.

Die Kokoro-Modellabhaengigkeiten, Inferenz und Downloads sind in den lokalen
Vertragstests simuliert. Die echte Linux-x86_64-Installation mit Python 3.11/3.12,
Modellinferenz, Laufzeit/RAM und Hoer-/Telefonqualitaet wurden hier nicht
abgenommen. Der Installer prueft beim spaeteren Einsatz seine Abhaengigkeiten,
Modellpruefsummen und eine echte lokale Testansage vor Aktivierung des Generators.
