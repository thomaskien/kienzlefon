# Spezifikation der Kienzlefon-AI-Runtime-Schnittstelle

**Version:** 1.0  
**Stand:** 15. August 2026  
**Implementierungsstand:** Haupt-Kienzlefon 2.3  
**Basis:** `SPEZIFIKATION-KIENZLEFON-AI-INTEGRATION-v1.4.md`

Diese Datei beschreibt den endgültigen, auf der Haupt-Kienzlefon-Seite
implementierten Vertrag. Sie ist die Vorgabe für die spätere Implementierung
auf der Kienzlefon-AI-Seite. Die AI-Seite ist nicht Bestandteil dieses
Umsetzungsschritts.

## 1. Verbindlicher Anrufablauf

Externe Anrufe und interne Anrufe auf `8800` durchlaufen zuerst den bisherigen
Eingangsblock:

1. Begrüßung beziehungsweise aktive Sonderansage,
2. Notfallansage,
3. bei aktueller klassischer Regel zusätzlich die Bereitschaftsdienstansage,
4. erst an der bisherigen Stelle des Hauptmenüs die AI-Admission-Prüfung.

Die drei vorhandenen Sonderansagepositionen bleiben unverändert:

- `statt_begruessung`,
- `vor_begruessung`,
- `nach_begruessung`.

Wird während dieses Eingangsblocks `0` gedrueckt, endet der Ansagenblock sofort
und die AI-Admission-Pruefung beginnt unmittelbar. Gibt es keine aktuelle
Freimeldung oder scheitert der AI-Wahlversuch vor Annahme, laeuft das klassische
Hauptmenue ohne eine ungueltige Null-Eingabe und ohne Wiederholung der bereits
abgespielten Eingangsansagen weiter. Bei `1` bis `9`, `*` oder `#` findet kein
AI-Versuch statt; das klassische Hauptmenue erhaelt genau dieses Zeichen als
bereits gedrueckte erste Eingabe.

Die interne Nummer `8801` bleibt der vollständige klassische Einstieg von
Beginn an. `8802`, `8803` und `8804` bleiben die direkten Praxis-, Apotheken-
und Fachdienstziele. KI-Slots beginnen unverändert bei `8810`.

Nach Annahme einer freigemeldeten KI-Nebenstelle startet der Haupt-Asterisk den
Medienbridge ohne vorgeschaltete eigene Assistentenansage. Das KI-Backend gibt
sein Greeting erst auf dem angenommenen AI-Leg aus und ist dadurch fuer den
Anrufer vollstaendig hoerbar. Bei einer Direktwahl auf `8810` ff. gilt derselbe
Dialpfad. Ohne Freimeldung entsteht kein AI-Leg; die Direktwahl erhaelt
unmittelbar `BUSY`.

Während des gebridgten AI-Gesprächs fängt der Haupt-Asterisk jede Anrufer-DTMF-
Taste `0` bis `9`, `*` oder `#` ab. Er beendet ausschließlich das AI-SIP-Leg
und übergibt das Zeichen unverändert an das klassische Hauptmenü. Die AI-Seite
darf diese Tasten weder fachlich auswerten noch eigene DTMF-Ziele ausführen.

## 2. Transport und Vertrauensgrenze

Der Admission-Listener läuft auf dem Haupt-Kienzlefon. Er bindet an genau eine
konfigurierte Loopback-, WireGuard- oder LAN-IP, niemals automatisch an
`0.0.0.0` oder `::`. Standardport ist TCP `8190`.

Der Transport ist UTF-8-JSONL:

- genau ein JSON-Objekt je Zeile,
- Abschluss jeder Nachricht mit `LF`,
- höchstens 65.536 Byte je Nachricht,
- Antworten in derselben Reihenfolge wie die Anfragen.

Es gibt auf ausdrückliche Vorgabe weder Anwendungsauthentifizierung noch TLS.
Die Schnittstelle darf nur in einem administrativ geschützten Netz betrieben
werden. `publisher_id`, `request_id` und `lease_id` sind technische
Zuordnungen, keine Authentifizierungsmerkmale.

Alle Netzwerkkommandos verwenden den äußeren Protokollwert:

```json
{"protocol":"kienzlefon-ai-admission-v1","command":"..."}
```

Technische Kennungen bestehen aus 1 bis 128 Zeichen aus
`A-Z`, `a-z`, `0-9`, Punkt, Unterstrich, Doppelpunkt oder Bindestrich. Eine
`lease_id` verwendet dieselbe Zeichenmenge, ist aber mindestens 16 Zeichen
lang. Kennungen enthalten keine Rufnummern oder Patientendaten.

## 3. Kapazitätspublisher und Admission

### 3.1 Anmeldung

Der AI-Rechner baut die dauerhafte Verbindung aktiv auf und sendet zuerst:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "publisher_hello",
  "publisher_id": "kienzlefon-ai-01",
  "slot_count": 3
}
```

Erfolg:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "publisher_hello_result",
  "accepted": true,
  "configured_slot_count": 3,
  "slot_ids": ["ai-slot-00", "ai-slot-01", "ai-slot-02"],
  "lease_ttl_ms": 5000,
  "publisher_timeout_ms": 7000
}
```

Bei abweichender Anzahl wird mit `accepted = false` und
`reason = "slot_count_mismatch"` geantwortet. Eine neue akzeptierte
Publisher-Verbindung ersetzt die bisherige und setzt zunächst alle Slots auf
`not_free`.

### 3.2 Vollständiger Kapazitätssnapshot

Nur der AI-Rechner entscheidet über seine Kapazität. Er sendet bei jeder
Änderung und zusätzlich periodisch alle konfigurierten Slots genau einmal:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "capacity_snapshot",
  "sequence": 42,
  "slots": [
    {
      "slot_id": "ai-slot-00",
      "state": "free",
      "lease_id": "793e9c5d-0000-0000-0000-000000000000",
      "ttl_ms": 5000
    },
    {
      "slot_id": "ai-slot-01",
      "state": "not_free",
      "reason": "in_call"
    },
    {
      "slot_id": "ai-slot-02",
      "state": "not_free",
      "reason": "no_capacity"
    }
  ]
}
```

Zulässige veröffentlichte `not_free`-Gründe sind ausschließlich:

```text
in_call
draining
no_capacity
not_ready
maintenance
service_unavailable
slot_disabled
```

Erfolg:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "capacity_snapshot_result",
  "accepted": true,
  "sequence": 42,
  "free_slots": 1
}
```

Eine identische Wiederholung derselben Sequenz ist mit `duplicate = true`
idempotent. Gleiche Sequenz mit anderem Inhalt liefert `sequence_conflict`,
eine kleinere Sequenz `stale_sequence`. Nachrichten eines nicht aktiven
Publishers liefern `publisher_not_active`.

Der AI-Rechner muss einen Slot selbstständig und sofort `not_free` melden,
sobald keine vollständige Kapazität mehr vorhanden ist. Zusätzlich sperren
Verbindungsabbruch, Publisher-Timeout und Lease-TTL-Ablauf neue Vergaben auf
dem Haupt-Kienzlefon fail-closed.

Jede `lease_id`, die ein Snapshot als `free` meldet, muss innerhalb dieses
Snapshots eindeutig genau einem Slot zugeordnet sein. Eine doppelt verwendete
`lease_id` macht den gesamten Snapshot ungültig.

### 3.3 Atomare lokale Vergabe

Der lokale Asterisk-Client fordert für den automatischen Weg irgendeinen Slot
an:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "claim_any",
  "request_id": "opaque-call-request-id"
}
```

Eine Direktwahl auf `8810` ff. verwendet den fest zugeordneten Slot:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "claim_specific",
  "request_id": "opaque-call-request-id",
  "slot_id": "ai-slot-01"
}
```

Erfolg:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "claim_result",
  "accepted": true,
  "request_id": "opaque-call-request-id",
  "publisher_id": "kienzlefon-ai-01",
  "slot_id": "ai-slot-01",
  "extension": "8811",
  "lease_id": "793e9c5d-0000-0000-0000-000000000000",
  "expires_in_ms": 4312
}
```

Ablehnungsgründe sind insbesondere `publisher_unavailable`, `no_capacity`,
`slot_not_free` und bei erschöpftem begrenztem Claim-Speicher
`claim_store_full`. Dieselbe `request_id` ist idempotent. Eine Lease wird
atomar höchstens einmal vergeben.

Scheitert der SIP-Wahlversuch vor Annahme, sendet der lokale Client:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "release",
  "request_id": "opaque-call-request-id",
  "lease_id": "793e9c5d-0000-0000-0000-000000000000"
}
```

Die Antwort heißt `release_result`. Eine erfolgreiche Freigabe setzt
`accepted = true`; sonst wird `claim_not_found` geliefert. `release` macht den
Slot nicht wieder frei. Nur ein neuer Snapshot der KI-Maschine mit einer neuen
Lease kann ihn erneut freimelden.

Der technische Statusbefehl lautet:

```json
{"protocol":"kienzlefon-ai-admission-v1","command":"status"}
```

`status_result` enthält `enabled`, `publisher_connected`, `publisher_id`,
`configured_slots` und aggregierte `states`, aber keine Gesprächsdaten.

## 4. Aktuelle Call-Policy für die AI-Seite

Die Policy darf nur über die aktuell akzeptierte Publisher-Verbindung und nur
für einen zuvor akzeptierten Claim desselben Publishers abgefragt werden. Die
Anfrage besitzt exakt diese vier Felder:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "get_call_policy",
  "request_id": "opaque-call-request-id",
  "lease_id": "793e9c5d-0000-0000-0000-000000000000"
}
```

Erfolg:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "get_call_policy_result",
  "accepted": true,
  "request_id": "opaque-call-request-id",
  "lease_id": "793e9c5d-0000-0000-0000-000000000000",
  "policy": {
    "protocol": "kienzlefon-ai-call-policy-v1",
    "evaluated_at": "2026-08-14T09:30:00+02:00",
    "valid_for_ms": 1000,
    "timezone": "Europe/Berlin",
    "practice_open": true,
    "phone_open": true,
    "greeting_open": true,
    "urgent_help_active": false,
    "override_active": false,
    "override_blocks_phone_hours": false,
    "practice_queue_allowed": true,
    "pharmacy_transfer_allowed": true,
    "specialist_transfer_allowed": false,
    "opening_hours": [
      {"weekday": 1, "windows": [{"start": "08:00", "end": "12:00"}]},
      {"weekday": 2, "windows": []},
      {"weekday": 3, "windows": []},
      {"weekday": 4, "windows": []},
      {"weekday": 5, "windows": []},
      {"weekday": 6, "windows": []},
      {"weekday": 7, "windows": []}
    ],
    "phone_hours": [
      {"weekday": 1, "windows": [{"start": "08:00", "end": "10:00"}]},
      {"weekday": 2, "windows": []},
      {"weekday": 3, "windows": []},
      {"weekday": 4, "windows": []},
      {"weekday": 5, "windows": []},
      {"weekday": 6, "windows": []},
      {"weekday": 7, "windows": []}
    ],
    "spoken_information": {
      "opening_hours": "Unsere regulären Öffnungszeiten sind: ...",
      "phone_hours": "Unsere Telefonzeiten sind: ..."
    },
    "dtmf": {
      "mode": "classic_handoff",
      "digits": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "#"]
    }
  }
}
```

`weekday` verwendet ISO-Wochentage `1 = Montag` bis `7 = Sonntag`; jedes
Zeitfenster ist halboffen (`start` einschließlich, `end` ausschließlich).
`spoken_information` enthält dieselben aus der aktuellen Konfiguration
erzeugten Öffnungs- und Telefonzeittexte wie Kienzlefon Klassik.

Die Policy wird bei jeder Abfrage aus der aktuellen Konfigurationsdatei und der
aktuellen Uhrzeit neu erzeugt. Sie ist nur für `valid_for_ms = 1000` gültig und
darf danach nicht zwischengespeichert weiterverwendet werden.

Ablehnungsgründe sind `invalid_query`, `publisher_not_active`,
`claim_not_found`, `publisher_mismatch`, `lease_mismatch` und
`policy_unavailable`.

Die `dtmf`-Angabe ist verbindlich: Die AI-Seite verarbeitet keine klassische
Zahlentaste. Der Haupt-Asterisk übernimmt den Wechsel und reicht die Taste an
Kienzlefon Klassik weiter.

## 5. Terminales Call-Result und Handoff

### 5.1 Zulässiger Inhalt

Das Call-Result-Objekt besitzt exakt sechs Felder:

```json
{
  "protocol": "kienzlefon-ai-call-result-v1",
  "request_id": "opaque-call-request-id",
  "lease_id": "793e9c5d-0000-0000-0000-000000000000",
  "outcome": "handoff_requested",
  "handoff_target": "practice_queue",
  "commit_status": "not_committed"
}
```

Zulässig sind ausschließlich diese logischen Ziele:

| `handoff_target` | feste lokale Zuordnung |
|---|---:|
| `classic` | `8801` |
| `practice_queue` | `8802` |
| `pharmacy_queue` | `8803` |
| `super_priority` | `8804` |

`8800`, `8810` ff., freie Rufnummern, SIP-URIs, Kontexte, Prioritäten,
Asterisk-Kommandos und zusätzliche Felder sind unzulässig. Ebenso unzulässig
sind ein anderes `outcome` oder ein anderer `commit_status`.

### 5.2 Veröffentlichung

Vor dem eigenen SIP-`BYE` veröffentlicht die AI-Seite das Ergebnis über ihre
weiterhin aktive Publisher-Verbindung. Die äußere Nachricht besitzt exakt die
drei gezeigten Felder:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "publish_call_result",
  "result": {
    "protocol": "kienzlefon-ai-call-result-v1",
    "request_id": "opaque-call-request-id",
    "lease_id": "793e9c5d-0000-0000-0000-000000000000",
    "outcome": "handoff_requested",
    "handoff_target": "practice_queue",
    "commit_status": "not_committed"
  }
}
```

Erste erfolgreiche Speicherung:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "publish_call_result_result",
  "accepted": true,
  "request_id": "opaque-call-request-id",
  "duplicate": false
}
```

Eine byteunabhängig inhaltlich identische Wiederholung wird mit
`duplicate = true` akzeptiert. Ein abweichendes zweites Ergebnis derselben
`request_id` wird als `result_conflict` abgelehnt.

Weitere Ablehnungsgründe sind `invalid_call_result`, `publisher_not_active`,
`claim_not_found`, `publisher_mismatch`, `lease_mismatch`, `result_expired`,
`result_store_full` und `result_persistence_failed`.

Eine positive Bestätigung darf erst ausgewertet werden, nachdem die AI-Seite
das vollständige Antwortobjekt empfangen hat. Erst danach beendet sie
ausschließlich ihr eigenes SIP-Leg.

### 5.3 Dauerhafte Ablage

Der Listener speichert Call-Results unter:

```text
/var/lib/kienzlefon/ai-call-results
```

Verzeichnisrechte sind `0700`, Dateirechte `0600`. Der Dateiname ist ein
SHA-256-Wert der technischen `request_id`. Geschrieben wird über eine neue
temporäre Datei, Datei-`fsync`, atomisches `replace` und Verzeichnis-`fsync`.
Erst danach folgt die positive Netzwerkantwort.

Die Result-TTL beträgt 30 Sekunden. Der Speicher ist auf 1.024 aktuelle
Ergebnisse begrenzt. Gespeichert werden ausschließlich Publisher-ID,
technische Zeit- und Verbrauchsmetadaten sowie die sechs Call-Result-Felder.
Rufnummern, Patientendaten, Transkripte und Gesprächsinhalte sind verboten.

### 5.4 Lokaler Verbrauch durch das Admission-AGI

Nach der Rückkehr aus `Dial(...,g)` fragt das lokale AGI mit exakt diesen
Feldern ab:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "consume_call_result",
  "request_id": "opaque-call-request-id",
  "lease_id": "793e9c5d-0000-0000-0000-000000000000"
}
```

Es wartet höchstens zwei Sekunden, damit Ergebnisablage, SIP-`BYE` und
Dialplan-Rücklauf deterministisch zusammengeführt werden.

Ein zulässiges, noch nicht verbrauchtes Ergebnis liefert:

```json
{
  "protocol": "kienzlefon-ai-admission-v1",
  "command": "consume_call_result_result",
  "accepted": true,
  "execute": true,
  "request_id": "opaque-call-request-id",
  "result": {
    "protocol": "kienzlefon-ai-call-result-v1",
    "request_id": "opaque-call-request-id",
    "lease_id": "793e9c5d-0000-0000-0000-000000000000",
    "outcome": "handoff_requested",
    "handoff_target": "practice_queue",
    "commit_status": "not_committed"
  }
}
```

Vor `execute = true` wird der einmalige Verbrauch ebenfalls dauerhaft
gespeichert. Parallele oder wiederholte Abfragen können deshalb höchstens
einmal `execute = true` erhalten. Weitere Antworten enthalten
`accepted = true`, `execute = false` und `reason = "already_consumed"`.

Vor dem Verbrauch wird die aktuelle klassische Ziellogik erneut geprüft:

- `classic` ist immer zulässig,
- `practice_queue` nur bei aktuell erlaubter Praxisqueue,
- `pharmacy_queue` nur innerhalb der konfigurierten Apothekenlogik,
- `super_priority` nur innerhalb der konfigurierten Fachdienstlogik.

Ist ein Ziel aktuell nicht zulässig oder kann die Konfiguration nicht sicher
ausgewertet werden, wird das Ergebnis einmalig ohne Ausführung verbraucht. Die
Antwort enthält `execute = false` und `reason = "target_not_available"`.
Nichtklassische Ziele verhalten sich bei fehlender Policy fail-closed.

Weitere Ablehnungsgründe sind `invalid_query`, `lease_mismatch`,
`result_not_found`, `result_expired` und `result_persistence_failed`.

### 5.5 Lokale Zielauflösung und Fallback

Der Dialplan vergleicht den logischen Zielnamen einzeln und springt danach auf
einen fest geschriebenen lokalen Zweig. Kein empfangener Wert wird zu einem
dynamischen `Goto`, SIP-Ziel oder Kommando zusammengesetzt.

Nach einem Handoff ist im selben Anruf jede weitere AI-Zulassung gesperrt.
Scheitert ein bestätigtes Ziel `8802`, `8803` oder `8804` mit einem definierten
Queue-Ausfallstatus, darf genau einmal auf `8801` zurückgefallen werden. Ein
Fehler auf `8801` erzeugt keine Rekursion.

Fehlt nach einem beantworteten AI-Gespräch ein eindeutiges, dauerhaftes und
noch nicht verbrauchtes `not_committed`-Ergebnis, endet der Weg fail-closed.
Es beginnt dann kein zweiter klassischer Auftrag.

## 6. SIP- und DTMF-Vertrag

Asterisk übermittelt der festen KI-Nebenstelle vor dem Wahlversuch:

```text
X-Kienzlefon-Protocol: kienzlefon-ai-admission-v1
X-Kienzlefon-Request-ID: <request_id>
X-Kienzlefon-Lease-ID: <lease_id>
X-Kienzlefon-Slot-ID: <slot_id>
```

Die AI-Endstelle muss die Lease vor `200 OK` auf ihrer lokalen Control-
Schnittstelle beanspruchen. Der Haupt-Asterisk bleibt mit `direct_media = no`
im Medienpfad und verwendet `Dial(...,g)`. SIP `REFER`, SIP `302`, AMI, ARI,
`ChannelRedirect` oder Asterisk-CLI durch die AI-Seite sind ausgeschlossen.

Die DTMF-Features werden ausschließlich auf dem ursprünglichen Anruferkanal
aktiviert und nicht auf den AI-Kanal vererbt. Bei einer Taste speichert
Asterisk das Zeichen, beendet den aktuellen Bridge-Peer und setzt nach Rückkehr
aus `Dial` das klassische Menü mit diesem Zeichen fort.

## 7. Noch erforderliche reale Abnahme

Die automatisierten Tests prüfen Protokollvalidierung, Persistenz,
Idempotenz, Race-Verhalten, Positivlisten, Dialplanerzeugung und klassische
DTMF-Übergabe statisch beziehungsweise simuliert.

Nicht als durchgeführt gelten damit:

- reale SIP-Annahme und reales SIP-`BYE`,
- tatsächlicher RTP-Abbau,
- DTMF-Erkennung des eingesetzten Providers und Telefons,
- echte Queue-Erreichbarkeit,
- Asterisk-/Telefon-Hardware-End-to-End.

Diese Punkte sind auf dem Haupt-Asterisk mit kontrolliertem Testaudio und
synthetischen Call-Results getrennt abzunehmen.
