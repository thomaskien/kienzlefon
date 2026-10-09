# Kokoro-Thorsten fuer Kienzlefon 2.4.1

Der Hauptinstaller ruft `install.py --config /etc/kienzlefon/kienzlefon.toml`
auf, wenn Kokoro ausgewaehlt ist. Ziel: Linux x86_64, Python 3.11 oder 3.12
mit passendem venv-Paket, `git`, `espeak-ng`, `libsndfile1` und `libgomp1`.
Piper bleibt in der Hauptumgebung installiert. Keine Dienste oder CUDA-Pakete
aus Kienzlefon-AI werden veraendert.

Modellmanifest und CPU-Lockdatei stammen unveraendert aus
`kienzlefon-ai/installer/kokoro-v2.6/`. Die eigenstaendige Ansagenruntime
`kienzlefon/kokoro.py` verwendet dessen lokale Modellinitialisierung,
Thorsten-Tensor und Phonemkorrektur `ʏ` → `y`. Zusaetzlich normalisiert sie
deutsche Texte vor der Aufteilung und teilt lange Texte unterhalb des
510-Phonemlimits. Ein einzelnes zu langes Wort wird mit Fehler abgewiesen.

Fixierte Quellen:

- [Thorsten-Voice/Kokoro](https://huggingface.co/Thorsten-Voice/Kokoro/tree/734e593d320a3d876bede7020f773dfd481a0cc7),
  Revision `734e593d320a3d876bede7020f773dfd481a0cc7` (Epoch 5).
- [Kokoro-Fork](https://github.com/semidark/kokoro/tree/b96fef95e6a746495f92443fac7c688f90fc57fc),
  Commit `b96fef95e6a746495f92443fac7c688f90fc57fc`.
- [Misaki-Fork](https://github.com/semidark/misaki/tree/6d252a2e02f3b030f22f56686f1a73786c16ffc8),
  Commit `6d252a2e02f3b030f22f56686f1a73786c16ffc8`.

Die drei benoetigten Modelldateien werden bei Download und Synthese gegen
SHA-256 geprueft. Beschaedigte vorhandene Dateien werden nicht ueberschrieben.
Gewichte und Bibliotheken werden erst bei Installation geladen, nicht im
Repository mitgeliefert; deren jeweilige Lizenzen gelten weiterhin.

Die Python-Umgebung liegt unter `/opt/kienzlefon/kokoro/2.4.1-<Inhaltshash>/`.
Nach `pip check`, Modelldownload und erfolgreicher Testansage wird der
konfigurierte Generator atomar veroeffentlicht. Bei einem Fehler davor bleibt
ein vorhandener Generator erhalten. Eine teilweise vorbereitete Umgebung kann
beim naechsten Lauf vervollstaendigt werden. Alte Umgebungen bleiben erhalten.

Die Laufzeit liefert 24-kHz-Mono-WAV mit 16-Bit-PCM. Anschliessend wendet
Kienzlefon dieselbe Lautheitsnormalisierung und Formatkonvertierung wie bei
Piper an. Hugging Face und Transformers sind zur Laufzeit im Offline-Modus.
Synthesetexte und Phoneme werden nicht durch die neue Runtime protokolliert.

Lokale Tests: `python -m pytest -q tests/test_kokoro.py` deckt Defaults,
Migration, Enginewahl, Cache, lange Texte, Downloadpruefsummen und atomare
Veroeffentlichung ab. Audio-/CPU-Vertraege werden dabei mit simulierten
Modellabhaengigkeiten getestet. Eine echte Linux-Installation, Modellinferenz
und Hoer-/Telefonabnahme sind separat auf dem Zielsystem durchzufuehren.
