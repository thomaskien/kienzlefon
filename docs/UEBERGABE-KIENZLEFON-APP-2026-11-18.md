# Übergabe für die nächste kienzlefon app Version

Stand 18.11.2026. Diese Spezifikation übergibt die vereinbarten Änderungen aus Sicht der App an das Kienzlefon-Projekt. Sie ergänzt den [Kienzlefon-Versionsplan](VERSIONSPLAN-2026-11-17.md) um die Anforderungen an Vorgangsdaten, Audio-Beilagen und die gemeinsame Telefonie. Für die Telefonie gilt Vertragsfassung **1.0.2** mit `schema_version: 1`. Die Vorgangsdaten und das Audio-Paket v1 sind anhand des gemeinsamen synthetischen Testpakets technisch für die Implementierung freigegeben.

## Bestätigter App-Ausgangsstand

Grundlage ist `ionos/telepraxis-app.php` in Commit `2f11f0d6c99abeea6403936f76bba8d0c6d60801`. Darin bleiben Bearbeiten in der Neu-Tabelle, der optionale WAV-Abspieler und das automatische Schließen des Patiententabs nach erfolgreicher Aktenübergabe erhalten. Der bisherige App-Release `v3.6` bleibt auf `e1f6a51` vor den drei Pull Requests. Die nächste App-Versionsnummer und Veröffentlichung sind offen.

Die Oberfläche übernimmt die besprochenen Ergänzungen im vorhandenen Design. Farben, Typografie, Karten, Tabellen, Spalten und die bestehende Kopfzeile bleiben erhalten. [App-Versionsplanung](https://github.com/thomaskien/kienzlefon-app/blob/main/docs/PLANUNG-NAECHSTE-APP-VERSION-2026-11-17.md)

## Mehrere Anliegen und ein Bearbeiter je Vorgang

- Eine JSON enthält ein oder mehrere Anliegen desselben Patienten. Die App zeigt einen gemeinsamen Patientenkasten mit passenden Typmarkern, etwa **Rezept** und **Überweisung**, und den gegliederten Originalinhalten. Zeilenumbrüche und bestehende Formatierung bleiben erhalten. Mehrere Aufträge desselben Typs bleiben einzeln unterscheidbar.
- Jedes Teilanliegen lässt sich einzeln abhaken. Die App speichert die Erledigung mit Teilanliegen-ID, Benutzer und Zeitpunkt. Der gesamte Vorgang bleibt bis zum ausdrücklichen Klick auf **Fertig** in Bearbeitung. Bei einem Vorgang mit mehreren Anliegen erfolgt der Abschluss nach Erledigung aller Teilanliegen. Altdaten mit einem Anliegen bleiben im bisherigen Ablauf nutzbar.
- Ein Patientenkasten in Bearbeitung hat genau einen aktuellen Bearbeiter. Bei Übernahme verschwindet er aus der Bearbeitungsansicht des bisherigen Benutzers und erscheint links beim neuen. Häkchen und deren Urheber bleiben erhalten. Die App prüft die aktuelle Zuordnung und speichert Übernahme sowie Statusänderungen unter der bestehenden Vorgangssperre. Schreibversuche aus einer veralteten Ansicht des bisherigen Bearbeiters weist sie ab. **Benutzer** bezeichnet den Bearbeiter. **Platz** bezeichnet den Arbeitsplatz.
- Kienzlefon und andere Erzeuger liefern die ursprünglichen Inhalte und stabilen Kennungen. Den aktuellen Bearbeiter, Häkchen und Abschluss speichert ausschließlich die App im lokalen `app`-Bereich außerhalb von `payload`. Wiederholte Lieferungen dürfen bestehende Bearbeitungsstände nicht überschreiben.

### JSON-Format v1 für Mehrfach-Anliegen

Die vorhandene Transporthülle bleibt bestehen. Im Nutzinhalt bleiben Patienten- und Rückrufdaten auf Vorgangsebene. `payload.anliegen` bleibt Freitext. Ergänzt wird `payload.anliegen_liste` mit `anliegen_id`, `typ` und den bekannten Inhaltsfeldern je Eintrag. Die ID wird bei der Anlage des Teilanliegens vergeben und bleibt bei Wiederholung, Sortierung und Korrektur gleich. Die bestehende `id` für die Anruferkennung bleibt davon getrennt. Beispiel für den Inhalt von `payload` mit fiktiven Angaben.

```json
{
  "typ": "mehrere_anliegen",
  "anliegen_schema_version": 1,
  "id": "unbekannt",
  "telefon": "unbekannt",
  "vorname": "Test",
  "nachname": "Beispiel",
  "zusammenfassung": "Rezept und Überweisung",
  "anliegen_liste": [
    {"anliegen_id": "a-001", "typ": "rezeptbestellung", "medikamente": "Testmedikament A"},
    {"anliegen_id": "a-002", "typ": "ueb_req", "fachrichtung": "Testfachrichtung", "grund": "Testanlass"}
  ]
}
```

Unbekannte Typen und Zusatzfelder bleiben erhalten. Eine fehlerhafte oder leere Liste darf vorhandene Texte nicht ausblenden. Fehlende oder doppelte Teilanliegen-IDs müssen erkennbar sein und dürfen zu keinem falsch zugeordneten Häkchen führen.

Der [Vertrag für Vorgangsdaten v1](vorgang-v1/ANLIEGEN.md) definiert Feldtypen, ID-Regeln und vollständige gemeinsame Beispiele. Die Ausgabe setzt eine kompatible App voraus. Die Erfassungswege werden bei ihrer jeweiligen Anbindung festgelegt.

## Verschlüsseltes Übergabeformat für Vorgangs-JSONs

Für reine JSON-Lieferungen gilt das bestehende Format `*.json.enc` v1. PHP-Empfänger und direkter Kienzlefon-Export schreiben diese Hülle.

| Feld | Inhalt |
| --- | --- |
| `v` | Ganzzahl `1`. |
| `created_at` | Zeitstempel mit UTC-Offset. |
| `cipher` | `AES-256-CBC`. |
| `sha256` | SHA-256 der exakten UTF-8-Klartextbytes, 64-stellig in Hex. |
| `ek` | Base64 der RSA-Verschlüsselung des 32-Byte-AES-Schlüssels mit dem Public Key des Empfängers und PKCS#1 v1.5. |
| `iv` | Base64 des 16-Byte-IVs. |
| `ct` | Base64 des AES-CBC-Chiffretexts der JSON mit PKCS#7-Padding. |

Der Klartext enthält `received_at`, `remote_ip`, `user_agent`, `typ` und `payload`. Kienzlefon erzeugt dieses Objekt beim direkten Export. Beim POST an das Empfangsmodul wird nur der Nutzinhalt gesendet. Das Empfangsmodul legt ihn unter `payload` ab. Teilanliegen und neue Audio-Metadaten gehören in `payload`. `anliegen_schema_version` und `v` sind getrennte Versionsangaben.

Der private RSA-Schlüssel bleibt am Ziel. Der separate SSH-Schlüssel dient dem Abruf. Der Abholer entschlüsselt am Ziel, prüft SHA-256 und JSON, legt die Datei atomar in der Inbox ab und bereinigt erst nach erfolgreicher Ablage gemäß Konfiguration. Referenz für das Format und die Abholerlogik ist die [Übergabe des Empfangsmoduls](https://github.com/thomaskien/kienzlefon-app/blob/main/docs/uebergabe-empfangsmodul.md).

## Audio-Beilagen und Löschung

Der Installer bietet **Lokale Ablage in der Praxis (unverschlüsselt)** an,
wenn Kienzlefon direkt in der Praxis betrieben wird. Kienzlefon legt die
Vorgänge in der Inbox ab. Bei **Verschlüsselter Ablage zur Abholung**,
etwa bei Kienzlefon auf einem Root-Server im Rechenzentrum, muss ein
lokaler Abholer in der Praxis eingerichtet werden. Die Bearbeitung findet
in der Praxis statt.

Bei Installation, Update und Neukonfiguration fragt der Installer
zusätzlich nach **Audio beilegen** oder **Nur JSON**. Beim Update werden
die bisherigen Entscheidungen als Vorgabe übernommen. Bei **Nur JSON**
räumt Kienzlefon die WAVs nach erfolgreicher Erkennung und gesicherter
JSON-Ausgabe auf. Beigefügte WAVs liegen dauerhaft ausschließlich in
`inbox/<vorgang_id>/audio/`. Die App entscheidet ab der Ablage über
Aufbewahrung, eine mögliche Löschfrist und Löschung.

Die aktive Liste liest die Vorgangs-JSONs direkt aus der konfigurierten
Inbox. Nach **Fertig** stehen vorhandene WAVs weiter zur Wiedergabe bereit.
Beim Verschieben in den **Papierkorb** löscht die App sämtliche WAVs des
Vorgangs. Sie verschiebt die JSON nach `inbox/papierkorb/`. Der Ordner wird
bei geöffneter Ansicht mit Admin-Sitzung eingelesen und hat keine
automatische Leerung. Wiederherstellen verschiebt die JSON zurück in die
Inbox. Schlägt die Audiolöschung fehl, zeigt die App den Fehler und erlaubt
einen erneuten Versuch.

Der [Vertrag für den Abholer](vorgang-v1/AUDIO.md)
beschreibt `*.kienzlepaket`, die Quittung und die Fehler-JSON als
`*.json.enc` v1. Die Quellbereinigung setzt eine bestätigte Ablage des
vollständigen Pakets oder der Ersatz-JSON voraus. Der Abholer macht die
JSON erst sichtbar, wenn das zugehörige Begleitverzeichnis bereitliegt.
Wiederholungen erhalten die Bearbeitungsstände. Bereits gelöschte WAVs
bleiben gelöscht.

Die App löst WAV-Pfade anhand der geprüften Vorgangszuordnung auf und
liefert die Segmente im bestehenden Zugriffsschutz aus. Die
Abspielposition bleibt beim Polling erhalten.
[Originalaufnahmen in der App](https://github.com/thomaskien/kienzlefon-app/blob/main/docs/RECORDINGS.md)

## Gemeinsame Telefonie nach Vertrag 1.0.2

| Projekt | Umsetzung |
| --- | --- |
| **Kienzlefon und Administration** | Dauerhafte Grundeinstellungen und globale Freigabe pflegen. Ein- und Ausschalten je Nebenstelle und Rufgruppe getrennt erlauben. Der geschützte Steuerungsdienst prüft Rechte, Anlagenlaufzeit, Revision und letztes Gruppenmitglied unmittelbar bei der Ausführung. Er liefert wirksame Zuordnungen, vollständige Live-Zustände und die vereinbarten Eingangs- und Wegeereignisse für den Tageszähler. |
| **kienzlefon-t2med** | Bestätigte Zustände und Auftragsstatus vermitteln, Tagesstatistik speichern und das eigene Telefonmenü anbinden. Für die App die datensparsame Übersicht `GET /api/v1/telephony/overview` bereitstellen. Unabhängig gültige Zähler bei Teilausfällen erhalten. |
| **kienzlefon app** | App-eigenen PHP-Proxy mit serverseitiger Verbindung zur Middleware einbauen. Telefonie und T2med-Patientenanbindung getrennt im Interface aktivierbar machen. Der Aktenaufruf bleibt am Patientenkasten. Status anzeigen und freigegebene Aufträge über den Proxy senden. Die Telefonanlage bleibt die maßgebliche Quelle. |

- Die sichtbaren Gruppen heißen **Normal** und **ROT**. Die technischen Gruppen-IDs sind `normal` und `specialist`. Eine geänderte IVR-Taste lässt die Gruppenkennung und den Namen ROT bestehen. Das ROT-Häkchen steuert das gemeinsame Klingeln. Bei aktiviertem rotem Telefon erfolgt dessen separater Einzelruf zuerst. Andernfalls beginnt der Gruppenruf sofort. ROT übernimmt keine Mitglieder aus Normal.
- Das letzte eingetragene Mitglied darf nicht entfernt werden. Besetzt und offline ändern keine Mitgliedschaft. Nach einem Anlagenneustart gelten die administrativen Grundeinstellungen. Browser- und Middleware-Neustarts ändern die Anlage nicht. Alte Aufträge dürfen in der neuen Anlagenlaufzeit keine Änderungen erneut anwenden. Laufende Gespräche bleiben verbunden.
- Bei gesperrter Änderung bleibt eine bekannte Zuordnung sichtbar. Bei unbekannter Mitgliedschaft oder nicht verfügbarer Gruppe sind beide Schaltrichtungen gesperrt. Die administrativen Freigaben gelten für die Zielnebenstelle. Benutzer- und Platzfelder erteilen keine Schaltrechte. Ein Auftrag wird erst nach Bestätigung der Anlage und neuem Zustandsabruf als wirksam angezeigt. Nach einem unklaren Ausgang dieselbe Auftrags-ID abfragen.
- Oberhalb des grauen App-Arbeitsbereichs die bestehende Zählerleiste um **Warteschleife**, **IVR**, **AI** und **Anrufe heute** ergänzen. Der separate große Statusblock entfällt. Nebenstellen stehen nebeneinander im ausklappbaren Bereich. Der Name steht oben, die Nummer rechts neben dem Status, gefolgt von den Häkchen **Normal** und **ROT**.
- Warteschleife, IVR und AI zeigen aktuell aktive Anrufe. **Anrufe heute** zählt ursprüngliche externe Eingänge nach Europe/Berlin genau einmal, auch anonym oder vor Annahme abgebrochen. Vermittlungen und Wegewechsel erzeugen keinen weiteren Eingang. Interne, ausgehende und Faxanrufe sind ausgeschlossen. Die App nutzt die gelieferten Werte, einschließlich Wege-Tooltip, `≈` bei lückenhafter Tageserfassung und `—` bei fehlenden Daten.

Endpunkte, Zustände, Fehlerantworten und Prüfdaten stehen im [Telefonievertrag 1.0.2](telefonie-v1/README.md). Für das Kienzlefon-Projekt sind insbesondere [Rufgruppen](telefonie-v1/ROUTING.md) und [Live- und Zählerereignisse](telefonie-v1/COUNTERS.md) maßgeblich. Die Middleware hat die Tagesstatistik lokal umgesetzt. Die reale Ereignisquelle auf der Anlage, der geschützte Steuerungsdienst und die App-Anbindung benötigen die gemeinsame Umsetzung und Abnahme.

## Technische Formatfreigabe vom 18.11.2026

Der gemeinsame Test verwendet die Kienzlefon-Beispiele, den vorhandenen Kienzlefon-Encoder, die bestehende Bash-Entschlüsselung und die PHP-Liste der App. Ein unabhängiger Leser hat das verschlüsselte JWE/ZIP mit drei Teilanliegen entschlüsselt und die WAV bytegleich dem Teilanliegen `a-002` zugeordnet. Alt- und Ersatz-JSON wurden bytegleich gelesen. Fehler in GCM-Tag, WAV-Bestand und IDs wurden erkannt. Die Beispielquittung ist an Dateiname und SHA-256 der verschlüsselten Lieferung gebunden.

[Gemeinsames synthetisches Testpaket und Prüfanleitung](https://github.com/thomaskien/kienzlefon-app/blob/main/docs/vorgang-paket-v1-test/README.md) · [Technische Freigabe im Empfangsmodul](https://github.com/thomaskien/kienzlefon-app/blob/main/docs/uebergabe-empfangsmodul.md#technische-freigabe-des-testpakets)

Die Freigabe gilt für die Schnittstelle als Grundlage der Implementierung. Nach der Umsetzung folgt die Laufzeitabnahme von Erzeuger, SSH-Abholer und App einschließlich Quittung, Wiederanlauf und Spool-Bereinigung.

## Übergabe zur Umsetzung und Abnahme

1. **Vorgangsdaten und Audio nach dem freigegebenen Format umsetzen.** Kienzlefon und App verwenden dieselben Verträge und Beispieldateien. Mehrfach-Anliegen und Audio-Beilage sind unabhängig nutzbar. Ein Vorgang darf mehrere Anliegen ohne WAVs oder ein Anliegen mit WAVs enthalten.
2. **Telefonie in der vereinbarten Reihenfolge anschließen.** Anlage und Ereignisse, Middleware, App und eigenes Middleware-Menü. Für Oberflächen und Schnittstellen die gemeinsamen Beispiele und [Abnahmekriterien](telefonie-v1/ACCEPTANCE.md) verwenden. Ausfall, Neustart, ablaufende Daten, Rechteentzug, parallele Bedienung und Schutz des letzten Mitglieds Ende zu Ende mit synthetischen Anrufen prüfen.
3. **Vorgangsablauf gemeinsam testen.** Alte Ein-Anliegen-Datei, zwei Anliegen in einem Kasten, zwei gleichartige Anliegen mit getrennten IDs, manueller Abschluss, Bearbeiterwechsel bei geöffneter alter Ansicht sowie unveränderte Druck- und Textkopie. Für Audio die Entscheidungen der App und die Quittung vor der Spool-Bereinigung prüfen. Ein Teilhäkchen und **Fertig** lassen vorhandene WAVs bestehen. Beim Verschieben eines offenen oder abgeschlossenen Vorgangs in den **Papierkorb** verschwinden alle WAVs am Ablageort und die JSON bleibt erhalten. Unvollständige Übertragung, fehlgeschlagene Löschung, wiederholte Lieferung und Wiederherstellung ohne Audio prüfen.
4. **App-Release absichern.** Bestehende Benutzer-/T2med-/Player-Einstellungen beim Update erhalten. Die korrigierten Browser- und SMS-Rendering-Tests in die Release-Abnahme einbeziehen. Bestehende Karten-/Tabellenfunktionen, SMS, Aktenaufruf und Polling einschließlich Kommentarfokus und laufender Audiowiedergabe prüfen.
