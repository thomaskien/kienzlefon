# Spezifikation der Kienzlefon-AI-Runtime-Schnittstelle

**Version:** 1.1
**Stand:** 25. August 2026
**Implementierungsstand:** Haupt-Kienzlefon 2.4.0
**Basis:** `SPEZIFIKATION-KIENZLEFON-AI-RUNTIME-SCHNITTSTELLE-v1.0.md`

Diese Fassung übernimmt den Vertrag aus Version 1.0 unverändert, soweit die
folgenden Präzisierungen nichts Abweichendes bestimmen. Sie ersetzt Version
1.0 für neue Installationen und Aktualisierungen. Die technischen Protokoll-
und Zielkennungen bleiben unverändert.

## 1. Rollen und bestehende Kienzlefon-Policy

Die AI verwendet für ihre semantische Einordnung insbesondere diese Rollen:

- `care_service`: Apotheke, Pflegeheim oder Pflegedienst,
- `professional_urgent`: Arzt oder Arztpraxis, Krankenhaus, Rettungsdienst
  oder Notarzt.

Diese Rollen ersetzen keine vorhandenen Kienzlefon-Policy-Felder. Die an die
AI gelieferte Call-Policy behält insbesondere:

- `pharmacy_transfer_allowed` für den bestehenden Apotheken- und
  Versorgungsweg `pharmacy_queue` / `8803`,
- `specialist_transfer_allowed` für den bestehenden Fachstellen- und
  Prioritätsweg `super_priority` / `8804`.

`specialist_transfer_allowed` bleibt erforderlich und steuert, ob die AI die
Rolle `professional_urgent` auf `8804` routen darf. Das Feld wird weder
umbenannt noch durch ein Rollenfeld ersetzt.

Ein von der AI festgestellter Patienten- oder Laiennotfall mit
`urgency = emergency` bleibt davon getrennt. Die AI darf dafür unabhängig von
den Fachstellenzeiten ein Handoff auf `super_priority` anfordern.

## 2. Verbindlicher Anruf- und DTMF-Ablauf

Kienzlefon schaltet vor dem klassischen Hauptmenü weiterhin nur dann zur AI,
wenn eine aktuelle Freimeldung sowie ein gültiger Claim und eine gültige Lease
vorliegen. Es gibt auf der Kienzlefon-Seite keine zusätzliche gesprochene
AI-Ansage.

Taste `0` kann die AI-Admission auch aus dem klassischen Hauptmenü erneut
anfordern. Ist keine AI-Kapazität verfügbar, wird ohne zusätzliche Ansage in
das klassische Hauptmenü zurückgekehrt. Nach einer bereits erfolgten
AI-Übergabe wird kein weiterer AI-Kreisverkehr zugelassen.

Die internen Zielkennungen bleiben unverändert:

| Ziel | lokale Zuordnung |
|---|---:|
| `classic` | `8801` |
| `practice_queue` | `8802` |
| `pharmacy_queue` | `8803` |
| `super_priority` | `8804` |

## 3. Verbrauch eines bestätigten Handoffs

Vor jedem Verbrauch gelten unverändert sämtliche Prüfungen aus Version 1.0:

- aktive Publisher-Zuordnung,
- gültige `request_id`, Claim- und Lease-Bindung,
- exakter Result-Hash und erlaubter Result-Inhalt,
- persistente Ablage vor positiver Bestätigung,
- Result-TTL und `result_expired`,
- dauerhaft gespeicherter, höchstens einmaliger Verbrauch.

Die Zielprüfung lautet in Version 1.1:

- `classic` ist immer zulässig,
- `practice_queue` bleibt von der bestehenden Praxis- und Telefonregel
  abhängig,
- `pharmacy_queue` bleibt von `pharmacy_transfer_allowed` beziehungsweise der
  bestehenden Apothekenzeit abhängig,
- ein bereits bestätigtes `super_priority`-Handoff wird von Kienzlefon nicht
  erneut anhand von `specialist_is_available()` oder den Fachstellenzeiten
  verworfen.

Damit versucht Kienzlefon nach einem gültigen, claim- und lease-gebundenen
Ergebnis den technischen Weg `super_priority` / `8804`. Dies erweitert weder
die AI-Policy für `professional_urgent` noch die Menge zulässiger Ziele.

Fehlt der Policy-Provider, bleiben nichtklassische Ziele fail-closed. Ein
gültiger Provider ist daher auch für `super_priority` erforderlich. Fehler bei
Claim, Lease, Persistenz, Ergebnisinhalt oder Verbrauch werden durch diese
Änderung nicht geöffnet.

## 4. Fallback und Datenschutz

Das feste lokale Mapping und der einmalige Queue-Fallback auf `8801` bleiben
unverändert. Es wird kein empfangener Zielwert dynamisch als Asterisk-Kommando,
SIP-Ziel oder Rufnummer verwendet.

Call-Results, Tests, Spezifikation und Übergabedateien enthalten keine
Gesprächsinhalte, Patientendaten, Transkripte oder produktiven Telefonie-Logs.
