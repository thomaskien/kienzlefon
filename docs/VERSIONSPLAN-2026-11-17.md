# Gemeinsames Aenderungspaket fuer die naechste Version

**Nachtrag vom 19.11.2026.** Den lokalen Kienzlefon-Stand mit den zugehörigen Prüfungen beschreibt der [Prüfbericht für 2.6.0](TESTS-2.6.0.md). Die folgenden Angaben dokumentieren den damaligen Plan.

**Telefonie-Vertragsstand 18.11.2026:** Die Schnittstellen für Live-/Tageszähler,
Rufgruppen und geschützten Zugriff sind im [gemeinsamen Vertrag v1](telefonie-v1/README.md)
festgelegt, mit Schema und identischen Beispielen in allen drei Projekten.
Frühere Formulierungen „technisch noch festzulegen“ gelten für diese
Telefonieschnittstellen nicht mehr. Umsetzung, Einrichtung und gemeinsame
Abnahme stehen aus. Andere Themen dieser Versionsplanung bleiben unverändert.

Stand 18.11.2026. Zusammenfassung der Benutzerentscheidungen und des
Dokumentabgleichs; die gemeinsame Implementierung hat noch nicht begonnen.
Arbeitsvorschlag fuer Kienzlefon: Version 2.6.0. Kienzlefax, Middleware und App
behalten ihre eigene Versionsfolge; die zusammenpassenden Staende gemeinsam
ausliefern und pruefen.

## Ausgangsstand

- Der Stand unmittelbar vor PR #1 ist als annotierter Tag `v2.5.5` auf GitHub
  gesichert: Commit `799378b7c90544117c5226e94070c960d3b5c04a`.
- Die geprueften Beitraege aus PR #1, #3 und #4 liegen bis `0e1f11c` vor.
  Der lokale Hauptbranch liegt noch auf dem Altstand. Bei der Umsetzung einen
  gezielt zusammengestellten Ausgangsstand verwenden und fremde lokale
  Aenderungen erhalten.
- Die bereits vorhandenen SMS-/Demo-Arbeiten sind ein separater Arbeitsstand;
  ihre Anwesenheit im Checkout macht sie nicht automatisch zum Teil dieses
  Funktionspakets.

## Vereinbarter Umfang

| Bereich | Vereinbartes Ergebnis |
| --- | --- |
| Beitraege und Korrekturen | SIP-Zielformate und Google Cloud TTS integrieren. Den TOML-Migrationsfehler, die veralteten Testerwartungen sowie Google-Netzwerkzugriff des Webdienstes, Konfigurationspfad, Erhalt des Endpunkts und korrekte URL-Pruefung beheben. |
| Provider | Anbieterprofile zentral in Kienzlefax pflegen. Fonial/Plusnet-Vorlage und voip2gsm-Issue #2 aufnehmen; Registrierung, Fax-/Telefon-Endpunkte, ausgehende Zielformate, eingehende Nummern mit/ohne `+` und hilfreiche Fehlerdiagnose abstimmen. |
| Direktnummern | Optionale direkte Praxisqueue ohne Zeitbeschraenkung und eigene Nummer fuer den Rufweg ROT. Mit rotem Telefon zuerst dessen Rufversuch, bei Misserfolg gemeinsames Klingeln; ohne rotes Telefon sofort die ROT-Gruppe. Einrichtung/Aenderung bei Installation, Update und Neukonfiguration immer anbieten; vorhandene Werte erhalten. |
| Whisper | Optionalen kienzledoku-Commander mit IP-Abfrage anbinden und bevorzugen. CPU-Whisper samt lokalen Modellen bleibt immer verfuegbar; bei Nichterreichbarkeit, Fehler oder Zeitueberschreitung automatisch lokal fortsetzen. |
| IVR und Administration | Jeden Haupt-/Untermenuepunkt einzeln aktivieren/deaktivieren und seine Taste konfigurieren. Routing, Ansagen und Anrufbaum verwenden dieselbe Konfiguration. Fachliche Funktionen und Statistikkategorien bleiben unabhaengig von den Ziffern. |
| Rufgruppen | Sichtbare Gruppen Normal und ROT, unabhaengig von der IVR-Tastenziffer. Das letzte konfigurierte Mitglied bleibt erhalten. Das ROT-Haekchen steuert das gemeinsame Klingeln: ohne rotes Telefon sofort, mit rotem Telefon nach dessen erfolglosem ersten Rufversuch. Bedienaenderungen aus App/Middleware gelten bis zum Anlagenneustart, administrative Grundeinstellungen bleiben dauerhaft. |
| Rechte und Fernbedienung | Zentrale Freigabe im Adminmenue sowie separate Aktivierungs-/Deaktivierungsrechte pro Nebenstelle und Gruppe. Status auch bei gesperrter Aenderung lesbar. Middleware und App verwenden denselben geschuetzten Kienzlefon-Dienst; Rechte werden dort unmittelbar vor Ausfuehrung geprueft. |
| App und Middleware | Gruppenstatus und erlaubte Schalter in der bestehenden Nebenstellenuebersicht. Bestaetigten, ausstehenden, veralteten und fehlgeschlagenen Zustand unterscheiden. Kein unabhaengiger verbindlicher Routingbestand in Middleware oder App. |
| Anrufstatistik | Jeden externen Telefoneingang einmal zaehlen, auch anonym und vor Annahme abgebrochen. Gewaehlte/erreichte Wege je Anruf getrennt erfassen. Direkte Eingaenge und Fallbacks einbeziehen; interne, ausgehende und Faxanrufe ausschliessen. Die Middleware speichert die Statistik, die App zeigt sie samt Vollstaendigkeit an. |
| Audioaufbewahrung | Installer fragt bei Installation, Update und Neukonfiguration nach Audio-Beilage oder JSON-only. WAVs liegen dauerhaft nur im Begleitverzeichnis in der Inbox. Die App entscheidet ueber Aufbewahrung und Loeschung. Bei verschluesselter Abholung gelten Paket, Fehler-JSON und Ablagequittung gemaess Abholerspezifikation. |

Die Google-Netzwerkanbindung ist vom Benutzer bereits erlaubt. Die zuvor
besprochene Stoerung betrifft die Dienstkonfiguration; ein Problem mit dem
Google-Konto wurde nicht nachgewiesen. Einen gewaehlten Google-Endpunkt beim
Update erhalten, keine neue regionale Vorgabe daraus ableiten.

Die Rufgruppen-Steuerung muss von der App ueber die Middleware bis zur
Telefonanlage gemeinsam funktionieren. Die Anrufstatistik ist ebenfalls ein
gemeinsamer Bestandteil; ihre laufenden Middleware-Arbeiten gezielt einbeziehen.
Die App erhaelt die besprochenen zusaetzlichen Bubbles in der bestehenden
Zaehlerleiste und die Gruppen-Schalter in der ausklappbaren Nebenstellenliste.

## Bestaetigte Benutzerentscheidungen, praezisiert am 18.11.2026

Die vier fachlichen Rueckfragen sind beantwortet:

1. **Ablageart und Audio separat abfragen:** Lokale Ablage in der Praxis
   oder verschluesselte Ablage zur Abholung. Bei verschluesselter Ablage
   den lokalen Abholer in der Praxis einrichten. In beiden Faellen
   ausdruecklich Audio-Beilage oder nur JSON abfragen. Beim Update
   die bisherigen Entscheidungen als Vorgaben verwenden.
2. **Aufbewahrung in der App:** WAVs im zugeordneten Inbox-Begleitverzeichnis
   ablegen. Eine moegliche Loeschfrist legt die App fest. Bei nur JSON WAVs
   nach erfolgreicher Erkennung und sicherer Ausgabe bereinigen.
3. **Letztes konfiguriertes Rufgruppenmitglied:** Darf nicht deaktiviert oder
   entfernt werden. Pruefung und Aenderung auf der Anlage zusammen absichern,
   auch bei parallelen Auftraegen. Besetzte/offline Telefone bleiben Mitglieder.
4. **Rufgruppe ROT:** Die sichtbare Bezeichnung lautet ROT, nicht IVR9.
   Das Haekchen steuert die Teilnahme am gemeinsamen Klingeln. Ohne
   aktiviertes rotes Telefon beginnt dieses sofort; mit rotem Telefon erst
   nach dessen erfolglosem separatem Rufversuch. Der erste Rottelefon-
   Versuch bleibt vom Gruppenhaekchen unabhaengig.

Die aktuelle [Middleware-Abstimmung](https://github.com/thomaskien/kienzlefon-t2med/blob/main/docs/NEBENSTELLENSTEUERUNG-ABSTIMMUNG.md)
enthaelt weitere Benutzerpraezisierungen: Beide Gruppen sind aus App und
Middleware-Telefonmenue bedienbar, ohne Beschraenkung auf die eigene
Arbeitsplatz-Nebenstelle, aber immer innerhalb der administrativen Freigaben.
Gruppenmitglieder werden nicht automatisch zwischen den Gruppen vererbt.
Bedienaenderungen gelten voruebergehend; nach Anlagenneustart gelten wieder
die dauerhaften administrativen Grundeinstellungen. Browser- oder Middleware-
Neustarts setzen die Anlage nicht zurueck. Alte Auftraege duerfen in einer
neuen Anlagenlaufzeit keine temporaeren Einstellungen wiederherstellen.

## Technische Festlegung vor gemeinsamer Implementierung

Hierfuer sind keine erneuten fachlichen Grundsatzfragen vorgesehen; die
Entwuerfe anhand der Benutzerantworten zu einem gemeinsamen Vertrag ausarbeiten:

- Stabile Gruppenkennungen `normal` und `specialist` statt
  einer Kopplung an Taste 9; sichtbare Bezeichnungen Normal und ROT.
- Einheitliche Status-, Rechte-, Revisions- und Auftragsdaten. Explizites
  Setzen eines Zielzustands, Wiederholungserkennung bis zum schreibenden
  Dienst, Konflikterkennung und nachvollziehbarer Auftragsstatus. Erfolg erst
  nach bestaetigter wirksamer Anwendung auf der Anlage. Administrative
  Grundeinstellungen bleiben dauerhaft; temporaere Bedienaenderungen werden
  nicht durch alte Auftraege nach einem Anlagenneustart wiederhergestellt.
- Eng begrenzten Maschinenzugang zum vorhandenen Kienzlefon-Dienst festlegen,
  sowohl fuer denselben Rechner als auch fuer getrennte Systeme. Verbindung
  App–Middleware mit den vorhandenen Origin-/Host-/Netzwerkregeln abstimmen;
  ein eingegebener Arbeitsplatzname ist keine Schreibberechtigung.
- Administrative Grundmitgliedschaften, Einzelrechte, globale Freigabe und
  Queue-Reihenfolge bei Migration und Updates erhalten. Neue Gruppenmitglieder
  mit administrativ festgelegter Rufstufe integrieren; bestehende Penalties
  und Prioritaeten nicht still umordnen. Neustarterkennung und Revisionen
  verhindern die Wiederanwendung ueberholter temporaerer Bedienauftraege.
- Manuell gesprochene Menueansagen bei geaenderter Tastenbelegung behandeln;
  eine Kombination mit falschen Tastenhinweisen nicht unbemerkt aktivieren.
  Leere Menues und ausbleibende Eingaben brauchen definierte Fallbacks.
- Commander-Zeitlimits, Wiederanlauf und feldabhaengige Erkennung konkret
  pruefen. Eine geplante GPU-Pause ist nicht automatisch ein Dienstausfall;
  dennoch muss das Warten begrenzt sein.
- Bei Erkennungs-/Ausgabefehlern die Wiederholungsmoeglichkeit erhalten.
  Der [Audiovertrag v1](vorgang-v1/AUDIO.md)
  beschreibt Paket, Ablagequittung, Fehler-JSON und Spool-Bereinigung.
  Den [Vertrag fuer Mehrfach-Anliegen v1](vorgang-v1/ANLIEGEN.md)
  gemeinsam anhand der Beispieldateien pruefen. Vorhandene Spool-Aufnahmen
  beim Update nicht pauschal rueckwirkend loeschen.
- Fuer den Statistikvertrag die konkretisierte Middleware-Spezifikation
  `T2med-asterisk/docs/ANRUFSTATISTIK.md` verwenden. Die aeltere App-Uebergabe
  daran angleichen, einschliesslich Wegeaufschluesselung und Anzeige
  unvollstaendiger Werte. Unterschiedliche Beispiele `>=N`/`ca. N` beschreiben
  keinen unterschiedlichen Zaehler; die Oberflaechenkonvention vereinheitlichen.

## Abnahme und Auslieferung

Die Anforderungen sind gesammelt; eine erfolgreiche Release-Abnahme steht
noch aus. Sie umfasst Bestandsmigration und wiederholte Installerlaeufe,
Provider-/Direktrouting, IVR/Ansagen, Rufgruppen samt Rechtepruefung aus beiden
Oberflaechen, Erhalt laufender Gespraeche, Commander-Ausfall mit CPU-Fallback,
Audiolebenszyklus mit verpflichtenden Installerfragen, App-Loeschregeln und
Quittungen vor der Spool-Bereinigung, Audio nach **Fertig**, WAV-Loeschung beim Verschieben in
den **Papierkorb**,
ROT mit und ohne rotes Telefon, Statistik-Doppelzaehlschutz
und Verhalten bei Verbindungs-
oder Speicherfehlern. Vorhandene Tests und die dokumentierten Review-Befunde
gezielt einbeziehen. Echte Asterisk-/Provider-/Commander-Funktion anschliessend
auf dem dafuer vorgesehenen Testsystem pruefen.

## Detailquellen

- [Architektur und vorgemerkte Features](ARCHITEKTUR.md)
- [Gemeinsame Rufgruppen-Abstimmung](RUFGRUPPEN-ABSTIMMUNG.md)
- [App-Entwurf zur Nebenstellensteuerung](https://github.com/thomaskien/kienzlefon-app/blob/main/docs/ABSTIMMUNG-NEBENSTELLENSTEUERUNG-2026-11-17.md)
- [Middleware-Anrufstatistik](https://github.com/thomaskien/kienzlefon-t2med/blob/main/docs/ANRUFSTATISTIK.md)
- [Review PR #1](REVIEW-COMMITS-2026-11-17.md)
- [Review PR #3 und #4](REVIEW-COMMITS-2026-11-17-NACHTRAG.md)
