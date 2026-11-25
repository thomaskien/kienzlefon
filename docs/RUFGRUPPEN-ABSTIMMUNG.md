# Rufgruppen: Abstimmung zwischen Kienzlefon, Middleware und App

> **Abgelöst am 18.11.2026:** Der [gemeinsame Telefonievertrag v1](telefonie-v1/README.md)
> legt Endpunkte, Zugriff, JSON-Typen, Live-Zähler, Rufgruppenaufträge und
> Neustartverhalten jetzt vollständig fest. Das lokale Paket enthält dieselben
> Schemata und Testbeispiele wie die anderen Projekte. Kienzlefon 2.7 implementiert den Steuerungsdienst. Einrichtung, Rechte und Abnahme auf der konkreten Anlage beschreibt die [Anlagensteuerung](ANLAGENSTEUERUNG.md).
>
> Der folgende Text bleibt als **historischer Abstimmungsstand** erhalten.
> Bei Abweichungen gilt ausschließlich der neue Vertrag, insbesondere
> Normal/ROT, der geschützte App-PHP-Proxy und die befristeten Änderungsaufträge.

Stand 18.11.2026: Abstimmungsvorlage fuer das gemeinsame Aenderungspaket.
Der Benutzer verlangt ausdruecklich die Abstimmung aller drei Komponenten.
Die fachlichen Rueckfragen sind beantwortet. Dieses Dokument beschreibt die
festgelegten Anforderungen und die noch auszuarbeitenden technischen Details;
es ist noch kein vollstaendiger API-Vertrag und keine Implementierung.
Die fachlichen Vorgaben stehen in der
[Architekturplanung](ARCHITEKTUR.md#geplant-nebenstellen-flexibel-rufgruppen-zuordnen).

## Abgleich mit dem App-Entwurf

Der vom Benutzer benannte
[App-Entwurf zur Nebenstellensteuerung](https://github.com/thomaskien/kienzlefon-app/blob/main/docs/ABSTIMMUNG-NEBENSTELLENSTEUERUNG-2026-11-17.md)
ist gelesen und in diese Abstimmung einbezogen. Sein Ablauf ueber App,
Middleware und denselben geschuetzten Kienzlefon-Dienst fuer Administration
und Maschinenzugriff passt zur Planung. Die aktuelle
[Middleware-Rueckmeldung](https://github.com/thomaskien/kienzlefon-t2med/blob/main/docs/NEBENSTELLENSTEUERUNG-ABSTIMMUNG.md)
unterscheidet dauerhafte administrative Grundeinstellungen/Freigaben von
voruebergehenden Bedienaenderungen. Diese Praezisierung ersetzt die fruehere
Annahme, jede App-Aenderung dauerhaft in die Grundkonfiguration zu schreiben.
Middleware und App pflegen keine unabhaengige verbindliche Routingkonfiguration.

Im App-Entwurf wurden zwei vorhandene Benutzervorgaben ergaenzt:

- Der globale Freigabeschalter kommt zu den Rechten pro Nebenstelle und
  Rufgruppe hinzu. Aktivierung und Deaktivierung sind getrennt freizugeben.
  Das einzelne `editable` wurde im Beispiel durch wirksame Rechte je Gruppe
  und Schaltrichtung samt Sperrgrund ersetzt. Revision und Pruefung erfassen
  auch diese Einzelrechte, einschliesslich einer Aenderung vor Ausfuehrung
  eines bereits angenommenen Auftrags.
- Die sichtbaren Gruppen heissen Normal und ROT, nicht IVR9. Die fachliche
  Gruppe bleibt beim Umbelegen des IVR bestehen. Die stabilen
  Kennungen lauten gemaess Middleware-Abgleich `normal` und `specialist`;
  `ivr9` aus frueheren Beispielen wird ersetzt. ROT bleibt die Gruppen-
  beschriftung; eine aktuelle IVR-Taste ist hoechstens eine zusaetzliche Angabe.

Der App-Entwurf konkretisiert ausserdem die gezielten Schreibauftraege,
Wiederholungserkennung, Revisionskonflikte, Auftragsstatus und den Unterschied
zwischen angenommen und tatsaechlich auf der Anlage angewendet.
Diese Vorschlaege bei der Vertragsfestlegung verwenden; die genannten API-
Endpunkte sind noch nicht implementiert oder abschliessend vereinbart.
Eine reine Rufgruppenaenderung erhaelt einen begrenzten Verarbeitungspfad,
der keine Ansagenerzeugung und keinen vollstaendigen Asterisk-Neustart ausloest.

Fachlich bestaetigt: Der letzte konfigurierte Teilnehmer darf nicht entfernt
werden. Die Fachstellengruppe enthaelt nur ihre ausdruecklich aktivierten
Mitglieder und erbt keine Mitglieder aus der normalen Gruppe. Das ROT-
Haekchen steuert die Gruppenteilnahme beim gemeinsamen Klingeln: Ohne
aktiviertes rotes Telefon beginnt dieses sofort. Mit rotem Telefon folgt es
auf dessen erfolglosen ersten Rufversuch; dieser bleibt separat konfiguriert.
Damit ist auch der bestaetigte Ablauf der roten Direktnummer abgebildet.

Bedienaenderungen aus App und Middleware gelten bis zum Anlagenneustart;
danach gelten wieder die administrativen Grundeinstellungen. Browser- und
Middleware-Neustarts setzen die Anlage nicht zurueck. Revisionen und
Auftraege sind an die Anlagenlaufzeit zu binden, sodass alte Auftraege nach
einem Anlagenneustart keine temporaeren Einstellungen wiederherstellen.

Technisch auszuarbeiten bleiben der maschinelle Transport, die administrativ
einstellbare Rufstufe neuer Normal-Mitglieder sowie die konkreten
Status-/Auftragsantworten und die Neustarterkennung.
Die Checkbox-Zeile wird in die vorhandene ausklappbare Nebenstellenuebersicht
der App integriert. Die Anrufstatistik bleibt ein eigener, dazu kompatibler
Teil des gemeinsamen Aenderungspakets.

## Beteiligte Komponenten

| Komponente | Lokales Projekt | Aufgabe im Feature |
| --- | --- | --- |
| Kienzlefon / Telefonanlage | `kienzlefon` | Mitgliedschaften und Freigaben pro Nebenstelle/Rufgruppe verwalten, serverseitig pruefen und wirksam anwenden; Administration im Adminmenue. |
| T2med-Middleware | `T2med-asterisk` / `kienzlefon-t2med` | Status und erlaubte Aktionen von der Telefonanlage lesen, berechtigte Aenderungsauftraege vermitteln und den tatsaechlichen Ausgang an die App liefern. |
| Kienzlefon-App | `ionos`, `telepraxis-app.php` | Rufgruppen und Status der Nebenstellen anzeigen; administrativ freigegebene Schalter ohne Adminzugang und ohne Beschraenkung auf die eigene Nebenstelle bedienen; Sperren/Fehler verstaendlich anzeigen. |

Die vorhandene App-Anbindung verwendet Middleware-Links fuer Wahl und
Aktenaufruf sowie eine bereits konfigurierte Client-ID. Eine fertige
Rufgruppen-Schnittstelle oder gemeinsame Schaltlogik ist damit noch nicht
gegeben. Die Middleware- und App-Quellen wurden fuer diese Einordnung gelesen.

## Technischer Vertrag und festgelegte Randbedingungen

1. **Arbeitsplatz und Nebenstelle:** Bestehende Middleware-Client-ID zur
   Einordnung des Auftrags verwenden; die Freigabe entscheidet fuer die
   betroffene Nebenstelle und Gruppe, nicht nur fuer das eigene Telefon.
   Fehlende/ungueltige Client-Zuordnung behandeln; ein freier Platzname
   erteilt selbst keine Schreibberechtigung. Beide Bedienoberflaechen
   verwenden dieselben fachlichen Freigaben.
2. **Statusvertrag:** Stabile Gruppen- und Nebenstellenkennungen, Bezeichnungen,
   aktive Mitgliedschaft, getrennte Rechte zum Aktivieren/Deaktivieren,
   Sperrgrund, Aktualitaet und Versions-/Revisionsangabe. Mitgliedschaft und
   technische Erreichbarkeit/Besetztstatus des Telefons getrennt behandeln.
3. **Schreibvertrag:** Gewuenschten Zustand explizit setzen, statt blind
   umzuschalten. Berechtigungen fuer jeden Auftrag aktuell auf der Telefonanlage
   pruefen. Annahme eines Auftrags und wirksame Aenderung unterscheiden;
   Wiederholungen, parallele Bedienung und Konflikte eindeutig behandeln.
   Die Pruefung des letzten konfigurierten Mitglieds erfolgt atomar mit der
   Aenderung; die wirksamen Rechte liefern dafuer einen Sperrgrund.
4. **Transport und Zugriff:** Konkrete Endpunkte/Ereignisse fuer beide Grenzen
   Telefonanlage–Middleware und Middleware–App, einschliesslich Zugriffsschutz
   und Browser-Origin-Regeln. Bestehende Linkaufrufe ersetzen keine freigegebene
   Lese-/Schreib-API. AMI-Zugangsdaten bleiben auf der Serverseite.
5. **Aktualisierung und Fehler:** Polling oder Ereigniszustellung vereinbaren;
   offline, veraltet, nicht unterstuetzt, gesperrt und fehlgeschlagen eindeutig
   darstellen. Keine Erfolgsmeldung ohne bestaetigten Zustand. Nach unklarem
   Ausgang erst abgleichen, bevor eine weitere Aenderung angeboten wird.
6. **Gruppenregeln und Darstellung:** Normal und ROT ohne automatische
   Vererbung und mit unabhaengigen Rechten
   abbilden. Adminmenue, Middleware, App und Anrufbaum zeigen dieselben
   wirksamen Mitgliedschaften. Ohne rotes Telefon klingelt ROT sofort;
   mit rotem Telefon nach dessen erfolglosem separatem ersten Rufversuch.
   Dieser erste Versuch bleibt vom Gruppenhaekchen unabhaengig. Eine Pausierfunktion darf
   weder eine gesperrte Deaktivierung noch den Schutz des letzten Mitglieds
   umgehen.
7. **Kompatibilitaet und Update:** Gemeinsame Schnittstellenversion und
   Faehigkeitsabfrage, Verhalten mit aelteren Gegenstellen, Reihenfolge der
   Updates sowie Erhalt von Grundmitgliedschaften, Freigaben und App-Verbindung.
   Anlagenneustart und erneute Verbindung einer Bedienoberflaeche unterscheiden;
   alte Auftraege niemals in einer neuen Anlagenlaufzeit erneut ausfuehren.

## Gemeinsame Abnahme

- Sprechzimmertelefon ueber die App zur normalen Telefoniegruppe hinzufuegen,
  den wirksamen Status in allen drei Komponenten sehen und einen Anruf annehmen.
- Gruppenmitgliedschaft wieder deaktivieren, ohne ein bereits angenommenes
  Gespraech abzubrechen; danach keine weiteren Rufangebote aus dieser Gruppe.
- Fuer dieselbe Nebenstelle normale Gruppe schaltbar und Rottelefon-Gruppe
  gegen Deaktivierung gesperrt pruefen, anschliessend die umgekehrte Freigabe.
- Gesperrte Aenderung auch bei direktem Schnittstellenaufruf ablehnen;
  Status bleibt fuer den berechtigten Client lesbar.
- Admin aendert Freigabe bei geoeffneter App, gleichzeitige Bedienung zweier
  Clients, Arbeitsplatzwechsel, Doppelklick und wiederholten Auftrag pruefen.
- Unterbrechung zwischen App, Middleware und Telefonanlage, Wiederverbindung,
  Neustart/Update sowie aeltere Gegenstellen ohne Rufgruppenfunktion pruefen.
- Gleichzeitig die beiden letzten Mitglieder abschalten: Hoechstens ein
  Auftrag darf wirken, ein Mitglied bleibt konfiguriert. Besetzte oder
  nicht erreichbare Telefone zaehlen weiterhin als Gruppenmitglieder.
- Rotes Telefon aus dem gemeinsamen Klingeln nehmen: Erster separat
  konfigurierter Rufversuch bleibt erhalten. Normale Mitglieder werden nicht
  ungefragt in die Fachstellengruppe aufgenommen.
- Ohne aktiviertes rotes Telefon klingeln die aktiven ROT-Mitglieder direkt.
  Bei erfolgreicher Annahme am roten Telefon gibt es kein nachfolgendes
  Gruppenklingeln. Beide Oberflaechen beschriften die Gruppe mit ROT.
- Nach Anlagenneustart gelten Grundmitgliedschaften, nach Browser-/Middleware-
  Neustart der unveraenderte aktuelle Anlagenzustand. Auftragswiederholung aus
  einer alten Anlagenlaufzeit darf keine temporaere Zuordnung wiederherstellen.

Vor der Implementierung den gemeinsamen Vertrag in dieser Abstimmung
konkretisieren und die Tests auf beiden Schnittstellen daran ausrichten.
Erst nach der gemeinsamen Abnahme ist das Feature vollstaendig integriert.
