<!--
kienzlefon
Version: 2.7
Changelog:
- 1.9.3: Keine Telepraxis-Datei fuer vollstaendig inhaltslose fehlerfreie Anrufe dokumentiert.
- 1.9.2: Fehlerfreies Ueberspringen der Demo-Anonymisierung bei Produktivupdates dokumentiert.
- 1.9.1: Wirksamwerden der Demo-Anonymisierung nach erfolgreichem Worker-Neustart dokumentiert.
- 1.9: Optionale Rufnummernanonymisierung in Demoausgaben dokumentiert.
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

Kienzlefon 2.7 schreibt in die konfigurierte Inbox, zum Beispiel `/srv/telepraxis/dahl/inbox`. Der Installer fragt die Ablageart und die Audio-Beilage getrennt ab.

| Ablageart | Nur JSON | Mit verwertbaren WAV-Aufnahmen |
| --- | --- | --- |
| Lokal in der Praxis | `<vorgang_id>.json` | JSON sowie WAVs unter `<vorgang_id>/audio/` |
| Verschlüsselt zur Abholung | `<vorgang_id>.json.enc` | `<vorgang_id>.kienzlepaket` mit JSON und WAVs |

Für die verschlüsselte Ablage braucht der Fon-Server den öffentlichen RSA-Schlüssel der Praxis. Bei einem Audiopaket wartet er mit der Quellbereinigung auf die passende Ablagequittung des Abholers. Die Verträge beschreiben auch fehlende Aufnahmen, die Ersatz-JSON und die Zuordnung mehrerer Anliegen. [Audioübergabe](vorgang-v1/AUDIO.md) · [Mehrere Anliegen](vorgang-v1/ANLIEGEN.md)

Beispiel einer verschlüsselten Ausgabe ohne Audio

```text
/srv/telepraxis/dahl/inbox/20260711_114658_676879.json.enc
```

Auszug aus dem Transportdatensatz eines einzelnen Terminanliegens vor der Verschlüsselung

```json
{
  "received_at": "2026-07-11T11:46:58+02:00",
  "remote_ip": "",
  "user_agent": "kienzlefon/2.7",
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

Ergibt keine einzige vorhandene Aufnahme ein nicht leeres Whisper-Transkript
und enthaelt der Vorgang keinen technischen Fehler, erzeugt der Worker keine
Telepraxis-Datei. Caller-ID, IVR-Kategorie, die Standardzusammenfassung und
technisch vorhandene stille WAV-Dateien gelten nicht als fachlicher Inhalt.
Der Vorgang wird intern als verarbeitet abgeschlossen. Sobald mindestens ein
Transkript vorhanden ist, wird das normale JSON mit den uebrigen leeren Feldern
ausgegeben. Technische Fehler werden weiterhin immer gemeldet.

Die äußere Datei einer `.json.enc`-Ausgabe ist kompatibel zur Referenzfunktion `openssl_seal()`. Sie hat folgende Felder

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

Für die lokale Praxisablage verwendet der Installer aus Kompatibilitätsgründen den TOML-Schalter `[telepraxis].demo = true`. In dieser Betriebsart schreibt der Worker auch Fehlerdatensätze unverschlüsselt. Sie ist für eine geschützte lokale Inbox vorgesehen. Auf dem öffentlich zugänglichen Demoserver ausschließlich Beispieldaten verwenden.

Bei lokaler Ablage ersetzt `anrufernummern_anonymisieren = true` bekannte Nummern in den Payload-Feldern `id` und `telefon` durch `#anonymisiert demo#`. Interne Spooldaten, Aufnahmen und frei gesprochene Texte können weiterhin Rufnummern und andere personenbezogene Angaben enthalten. Der neu gestartete Worker übernimmt die Einstellung.

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

Bei „Verzeichnisse und Rechte“ schreibt der Installer eine private temporäre
Datei in die konfigurierte Inbox, synchronisiert und entfernt sie. Die Prüfung
läuft als `root` mit der Gruppe der Inbox, wie der Kienzlefon-Worker. Läuft
Asterisk unter einem anderen Benutzer, wird auch dessen Schreibzugriff geprüft.
Bei einem Fehler nennt der Installer den Pfad und die Ursache des Dateisystems.
