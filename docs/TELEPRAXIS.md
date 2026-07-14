<!--
kienzlefon
Version: 1.8.3
Changelog:
- 1.8.3: Teiltranskription und leere Datenfelder ohne Fehlerdatensatz dokumentiert.
- 1.8.2: Dynamische Versionskennung auf Kienzlefon 1.8.2 aktualisiert.
- 1.8.1: Dateimodus und Gruppenzuordnung der Ausgabe dokumentiert.
- 1.8: Demo-Klartextausgabe und Behandlung leerer Abbrueche dokumentiert.
- 1.7.1: Dynamische Versionskennung auf Kienzlefon 1.7.1 aktualisiert.
- 1.7: Unveraenderte Telepraxis-ID trotz normalisierter Telefonanzeige dokumentiert.
- 1.6.2: Regulaeren AGI-Hangup ohne technische Fehlerausgabe dokumentiert.
- 1.6.1: Dynamische Versionskennung auf Kienzlefon 1.6.1 aktualisiert.
- 1.6: Dynamische Versionskennung auf Kienzlefon 1.6 aktualisiert.
- 1.5: Dynamische Versionskennung auf Kienzlefon 1.5 aktualisiert.
- 1.4: Dynamische Versionskennung auf Kienzlefon 1.4 aktualisiert.
- 1.3: Dynamische Versionskennung auf Kienzlefon 1.3 aktualisiert.
- 1.2: Dynamische Versionskennung auf Kienzlefon 1.2 aktualisiert.
- 1.1: Versionskennung und Transkriptbereinigung dokumentiert.
- 1.0: Direktes verschluesseltes Telepraxis-Dateiformat dokumentiert.
-->

# Telepraxis-Dateiformat

Version 1.8.3 verwendet keinen HTTP-POST. Im Produktivmodus erzeugt der Worker
direkt eine verschluesselte Datei im konfigurierten Kanalverzeichnis:

```text
/srv/telepraxis/dahl/inbox/20260711_114658_676879.json.enc
```

Der Klartext vor der Verschluesselung entspricht dem gespeicherten
Telepraxis-Transportdatensatz:

```json
{
  "received_at": "2026-07-11T11:46:58+02:00",
  "remote_ip": "",
  "user_agent": "kienzlefon/1.8.3",
  "typ": "termin",
  "payload": {
    "typ": "termin",
    "id": "+492331...",
    "telefon": "+492331...",
    "zusammenfassung": "keine Zusammenfassung vorhanden",
    "vorname": "Max",
    "nachname": "Muster",
    "geburtsdatum": "1. Januar 1970",
    "grund": "Termin am Montag"
  }
}
```

Von jedem Whisper-Transkript wird genau ein abschliessender Punkt entfernt.
Punkte innerhalb eines Textes und alle uebrigen Inhalte bleiben unveraendert.
Die `id` bleibt die urspruenglich uebertragene Caller-ID. Die rein fuer interne
Telefone vorgenommene Anzeigeformatierung veraendert diesen Wert nicht.

Schweigend uebersprungene Felder bleiben als leere Zeichenketten im normalen
Payload. Sie sind kein technischer Fehler. Alle weiteren Audiodateien desselben
Vorgangs werden trotzdem transkribiert und in ihre festgelegten Felder geschrieben.

Die aeussere Datei ist kompatibel zur Referenzfunktion `openssl_seal()`:

```json
{
  "v": 1,
  "created_at": "2026-07-11T11:46:58+02:00",
  "cipher": "AES-256-CBC",
  "sha256": "...",
  "ek": "...",
  "iv": "...",
  "ct": "..."
}
```

`ct` ist der AES-verschluesselte Klartext, `ek` der mit RSA PKCS#1 v1.5
verschluesselte AES-256-Schluessel. `sha256` prueft nach dem Entschluesseln den
exakten Klartext.

Bei einer ausdruecklich bestaetigten Demo-Installation steht in der TOML
`demo = true`. Dann wird kein Public Key benoetigt und exakt der oben gezeigte
Transportdatensatz atomar als `<vorgang_id>.json` abgelegt. Auch technische
Fehlerdatensaetze sind in diesem Modus unverschluesselt. Der Demo-Modus darf
auf keinen Fall fuer echte Patientendaten verwendet werden.

Jeder erkannte technische Fehler wird zusaetzlich als eigener Datensatz mit
`typ = kienzlefon_error` im konfigurierten Ausgabemodus ausgegeben. Ist das Zielverzeichnis
voruebergehend nicht beschreibbar, bleibt das Fehlerereignis lokal erhalten
und wird erneut ausgegeben, sobald die Dateiausgabe wieder funktioniert.

Legt eine anrufende Person nach einer vorhandenen Aufnahme auf und meldet
Asterisk deshalb AGI-Code `511`, ist dies ein regulaerer Abschlussweg. Die
Aufnahme wird verarbeitet; dafuer entsteht kein technischer Fehlerdatensatz.
Legt die Person auf, bevor irgendeine verwertbare Aufnahme entstanden ist,
wird der vollstaendig leere Vorgang verworfen. Ein vorhandener technischer
Fehler wird unabhaengig davon weiterhin gemeldet.

Fertige Produktiv- und Demodateien werden atomar mit Modus `0660` aktiviert.
Laeuft der Worker als Root, setzt er Eigentumer `root` und uebernimmt die
Gruppe des Ausgabeverzeichnisses. Dadurch bleibt eine geerbte ACL-Maske fuer
die Gruppe schreibbar. Interne Spooldateien sind davon nicht betroffen.
