# Übergabe: AMI und Dialplan für die kienzlefon-Middleware

Stand: 11.10.2026 · Schnittstellenvertrag v1

**Auftrag an das kienzlefon-Projekt:** Den Asterisk-Installer um einen eigenen AMI-Zugang, einen begrenzten Lookup-Hook für eingehende Anrufe und einen Einstiegskontext für Click-to-Dial erweitern. Die Middleware, die GDT-Freigabe und die Arbeitsplatzinstaller werden separat umgesetzt. Dieses Dokument ist eine Umsetzungsspezifikation; die Referenzblöcke wurden noch nicht auf der Telefonanlage ausgeführt.

## 1. Feststehende Entscheidungen

- Die Middleware läuft zentral unter Ubuntu, Debian oder Raspbian/Raspberry Pi OS. Sie muss sowohl auf dem Asterisk-Rechner als auch auf einem getrennten Linuxserver betreibbar sein. Im konkreten Fall ist ein getrennter Rechner vorgesehen. Adressen dürfen nicht fest im Code stehen.
- Ausschließlich die Middleware greift auf AMI und APS zu. Browser und Arbeitsplatzhelfer erhalten keine AMI- oder APS-Zugangsdaten.
- Die APS-Telefonnummernsuche ist bereits bestätigt: `POST /aps/rest/praxis/patient/suche/find`, Basic Auth, JSON `{"suchmaske":"<Rufnummer>","ignoreSichtbarkeit":false}`. Antwort: Patientenliste einschließlich Name, Geburtsdatum, formatierter Adresse, Patientennummer und vollständiger interner Referenz. Dies ist die bestehende APS-REST-Schnittstelle, nicht die FHIR-Demo. Ein neuer Telefonnummernindex ist keine Voraussetzung dieses Auftrags.
- Mehrdeutige Treffer bleiben getrennt, auch bei gleichem Namen. Die allgemeine APS-Suche berücksichtigt ebenfalls Patientennummern. Die Middleware verantwortet die Entscheidung, ob ein Ergebnis eindeutig zugeordnet werden kann; der Dialplan erhält nur das fertige Ergebnis. Niemals pauschal den ersten Treffer wählen.
- Der Aktenaufruf über GDT-Satztyp `6301`, Importdatei `AUFRUFi.gdt`, Absender `AUFRUF`, Empfänger `T2MED_PX` wurde bereits erfolgreich getestet. Der Auftrag enthält die Patientennummer und GDT-Steuerfelder, keine Namen, Adressen oder Geburtsdaten.
- Der Middleware-Installer erstellt die SMB-Freigabe **`kienzlefon-GDT` mit Gastzugriff ohne Anmeldung** für das abgeschottete Praxisnetz. Er muss bestehende SMB-Dienste und Freigaben erhalten.
- Pro Arbeitsplatz wird ein eigenes GDT-Ziel verwendet, beispielsweise `\\middleware\kienzlefon-GDT\empfang-1\AUFRUFi.gdt`. T2med wird am jeweiligen Arbeitsplatz auf dieses Ziel eingestellt. Der Netzwerkimport ist bei der Abnahme zu testen.
- Click-to-Dial ist über einen lokalen Arbeitsplatzhelfer unter **Windows, macOS und Linux registrierbar**, primär als `tel:`-Handler, optional zusätzlich `callto:`. Der Arbeitsplatzinstaller hinterlegt Middleware-Adresse, feste Client-ID und zugewiesene Nebenstelle. Die Nebenstelle wird nicht bei jedem Anruf neu abgefragt. Ein Browser kann die Rechneridentität nicht verlässlich selbst ermitteln; die Webansicht verwendet dieselbe explizite Arbeitsplatzzuordnung.

## 2. Zuständigkeiten und Konfiguration

| Komponente | Verantwortlich für |
| --- | --- |
| kienzlefon-Installer | AMI-Benutzer/Erreichbarkeit, Lookup-Gosub vor `Dial()`/`Queue()`, Click-to-Dial-Kontext, Anschluss an vorhandene Ausgehregeln |
| Middleware-Installer | Linux-Dienst, AMI-/APS-Verbindung, API/Webansicht, GDT-Schreiber, zusätzliche SMB-Gastfreigabe |
| Arbeitsplatzinstaller | URI-Handler, lokale Client-ID/Nebenstellenzuordnung, Verbindung zur Middleware, gegebenenfalls Einbinden des GDT-Shares |
| Arbeitsplatz/T2med | Kalenderanbindung auf das eigene GDT-Ziel konfigurieren |

Der kienzlefon-Installer benötigt als Parameter:

| Parameter | Vorgabe |
| --- | --- |
| Integrationsfunktion | Aktivierbar/deaktivierbar; deaktiviert bleibt die bisherige Telefonie erhalten |
| Asterisk-Adresse / AMI-Port | Installationsabhängig, Standardport TCP `5038` |
| Middleware-Quelladresse | Exakte IP aus Sicht des Asterisk-Servers, bei gleichem Host `127.0.0.1` |
| AMI-Benutzer | Standard `kienzlefon-middleware`, eindeutiger eigener Benutzer |
| AMI-Secret | Zufällig bei Erstinstallation erzeugen, bei Wiederholung erhalten |
| Transport | Lokaler TCP-Zugriff oder TCP im freigegebenen abgeschotteten LAN; vorhandenes AMI-TLS muss weiter unterstützt werden |
| Lookup-Frist | Höchstens `1000 ms`, durch Asterisk durchgesetzt |
| Click-to-Dial-Kontext | Fest vereinbart: `kienzlefon-click-to-dial` |
| Nebenstellen | Freigegebene PJSIP-Nebenstellen; zunächst `201`, `202`, `203`, `204`, `8810`, `8811`, `8812` |
| Ausgehroute | Anschluss an den tatsächlichen kienzlefon-Ausgehkontext; dessen Namen aus dem Projekt übernehmen |
| Lokaler Klingel-Timeout | Vorgabe `20000 ms`, konfigurierbar; betrifft die Mitarbeiter-Nebenstelle |

AMI-Passwort und Verbindungseinstellungen werden dem Middleware-Installer als geschützte Konfiguration übergeben. Keine Secrets in normalen Installationsprotokollen oder in der SMB-Freigabe. Ein Arbeitsplatz-SSH-Tunnel gehört nicht zur neuen Architektur.

## 3. AMI-Konfiguration

### 3.1 Eigener Benutzer

Eigene verwaltete Datei, beispielsweise `/etc/asterisk/manager_kienzlefon_middleware.conf`, einmalig aus `manager.conf` einbinden. Das folgende Beispiel enthält Platzhalter und darf nicht unverändert installiert werden:

```ini
[kienzlefon-middleware]
secret = <ERZEUGTES_SECRET>
deny = 0.0.0.0/0.0.0.0
permit = <MIDDLEWARE_QUELL_IPV4>/255.255.255.255
read = system,call,agent,user,dialplan
write = call,originate,reporting
```

`call` wird für `Setvar`, `originate` für `Originate` benötigt. `reporting` deckt die Bestandsabfragen ab. Die Leseklassen erlauben Kanal-, Warteschlangen-, eigene Lookup- und Dialplanereignisse. `dialplan` ist für `Newexten`/`VarSet` relevant. Keine pauschalen `all`-Rechte, keine zusätzlichen Schreibrechte `command`, `config`, `system` oder `agent` vergeben. AMI-Rechte sind Kategorien, keine Einzelaktions-Whitelist: Die Middleware begrenzt ihre Aktionen zusätzlich selbst. [AMI-Aktionsregistrierung](https://github.com/asterisk/asterisk/blob/20/main/manager.c), [AMI-Konfigurationsvorlage](https://github.com/asterisk/asterisk/blob/20/configs/samples/manager.conf.sample)

Zulässige Aktionen der Middleware:

- Verbindung: `Login`, `Logoff`, `Ping`, bei Bedarf `Events`.
- Abgleich: `CoreShowChannels`, `QueueStatus`, optional `Getvar` für eigene Korrelationsvariablen.
- Lookup: `Setvar` ausschließlich für die unten definierten Ergebnisvariablen auf einem expliziten Kanal.
- Wählen: `Originate` ausschließlich an freigegebene Nebenstellen und den festen Click-to-Dial-Kontext.

Beim Login **`Events: on`** verwenden. Der bisherige lokale Prototyp mit `Events: off` und nur `write = reporting` erfüllt die neuen Anforderungen nicht.

### 3.2 Listener, Netzwerk und bestehende AMI-Nutzer

- AMI muss aktiviert sein. Bei Neuinstallation ohne vorhandene Nutzer nur an Loopback beziehungsweise die benötigte Praxisnetz-Schnittstelle binden.
- Auf getrennten Rechnern muss die gewählte Bindadresse vom Middleware-Server erreichbar sein. Die Benutzer-ACL erlaubt nur dessen tatsächliche Quelladresse. IPv6 bei Verwendung entsprechend explizit konfigurieren.
- Vorhandene Bindadressen, Ports, TLS-Einstellungen, Web-AMI und Benutzer prüfen und erhalten. Der Listener ist eine globale Einstellung; ihn nicht blind auf Loopback oder eine andere Einzeladresse umstellen und dadurch bestehende AMI-Clients aussperren.
- Eventuelle Firewallregeln gezielt für Middleware-Quelle und AMI-Port ergänzen; bestehende Regeln nicht ersetzen.
- Bestehende Filter oder deaktivierte Ereignisse dürfen die unten benötigten Ereignisse nicht unterdrücken. Für den neuen Benutzer zunächst keine zusätzliche Ereignisfilterung konfigurieren.
- Änderungen sichern, wiederholbar und ohne doppelte Includes ausführen. Secret bei normalen Updates nicht neu erzeugen. Änderungen gezielt neu laden; kein pauschaler Asterisk-Neustart während laufender Gespräche.

### 3.3 Benötigte Ereignisse

Mindestens verarbeiten beziehungsweise unverändert an den Benutzer ausliefern:

- Kanäle/Rufabschnitte: `Newchannel`, `Newstate`, `NewCallerid`, `NewConnectedLine`, `Newexten`, `VarSet`, `DialBegin`, `DialEnd`, `Hangup`.
- Brücken: `BridgeCreate`, `BridgeEnter`, `BridgeLeave`, `BridgeDestroy`; Transfer-/Local-Optimierungsereignisse der eingesetzten Version ebenfalls nicht wegfiltern.
- Warteschlangen: `QueueCallerJoin`, `QueueCallerLeave`, `QueueCallerAbandon`, `AgentCalled`, `AgentConnect`, `AgentComplete`, `QueueMemberStatus`, `QueueMemberPause`, `QueueMemberAdded`, `QueueMemberRemoved`.
- Integration: `UserEvent` mit den unten definierten Namen, `OriginateResponse`, `FullyBooted`.
- Abfrageantworten: `CoreShowChannel`, `CoreShowChannelsComplete`, `QueueParams`, `QueueMember`, `QueueEntry`, `QueueStatusComplete` und jeweilige AMI-Responses.

Die Middleware hält nach Verbindungsaufbau zunächst `stale=true`, gleicht `CoreShowChannels` und `QueueStatus` ab und berücksichtigt parallel eintreffende Ereignisse. Späte Snapshot-Einträge dürfen inzwischen beendete Kanäle nicht wiederbeleben. `Uniqueid`, `Linkedid`, Rufabschnitte und Brückenzugehörigkeit gemeinsam auswerten; gleiche `Linkedid` allein bedeutet bei Rückfragen/Transfers keine einzige aktive Gesprächsbrücke. Die Warteschlange referenziert den logischen Anruf und erzeugt keinen zweiten Anruf.

## 4. Vertrag für eingehende Namensauflösung

### 4.1 Einbaupunkt im kienzlefon-Dialplan

Ein eigener `Gosub(kienzlefon-lookup,s,1)` läuft **einmal pro externem Eingangskanal**, nachdem die endgültige Anrufernummer feststeht und bevor der erste Ruf zu einem Endgerät durch `Dial()` oder `Queue()` ausgelöst wird. Nicht zusätzlich auf jedem Local-/PJSIP-Zielkanal ausführen. Warteschlangenüberläufe dürfen keine weitere Sekunde hinzufügen.

Vorhandene Rufverteilung, Öffnungszeiten, Warteschlangen, Ansagen und Providerkonfiguration bleiben erhalten. Keine zusätzliche `Answer()`-Anweisung allein für den Lookup. Bei deaktiviertem Hook, fehlender/unterdrückter Rufnummer oder internen Gesprächen sofort mit dem bisherigen Ablauf fortfahren.

### 4.2 Anfrage: Dialplan → Middleware

Vor dem Ereignis initialisiert der Dialplan alle Ergebnisvariablen. Eine eindeutige `RequestId` gilt nur für diesen Lookup; bei genau einem Lookup pro Kanal kann sie aus `UNIQUEID` abgeleitet werden. Der Dialplan hält zusätzlich eine lokale absolute Deadline und einen abgeschlossenen/gestarteten Zustand.

```text
LOOKUP_NAME       = leer
LOOKUP_STATUS     = pending
LOOKUP_RESULT_ID  = leer
LOOKUP_DONE       = 0
```

Über `UserEvent()` wird folgendes eigene Ereignis ausgelöst:

```text
Event: UserEvent
UserEvent: KienzlefonLookupRequest
SchemaVersion: 1
RequestId: <eindeutige Lookup-ID>
SourceChannel: <vollständiger Eingangskanal>
SourceUniqueid: <UNIQUEID>
SourceLinkedid: <CHANNEL(linkedid)>
Number: <Anrufernummer>
BudgetMs: 1000
```

`Source*` sind explizite Nutzdatenfelder; dadurch entstehen keine doppelten AMI-Standardheader. Die Middleware ordnet die Anfrage diesem Kanal zu. Fehlende Kanalzuordnung darf niemals zu einem globalen `Setvar` führen. Die Deadline des Dialplans bleibt verbindlich, unabhängig vom Empfangszeitpunkt im Middleware-Prozess. [Dialplan-UserEvent](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/Dialplan_Applications/UserEvent/)

### 4.3 Ergebnis: Middleware → Dialplan

Die Middleware schreibt mit einzelnen AMI-`Setvar`-Aktionen auf **`SourceChannel`**, jeweils mit eigener `ActionID`. Für jeden Schritt muss eine erfolgreiche Response vorliegen, bevor der nächste Schritt erfolgt:

1. `LOOKUP_RESULT_ID = <RequestId>`
2. `LOOKUP_NAME = <Anzeigename oder leer>`
3. `LOOKUP_STATUS = resolved | not_found | ambiguous | error`
4. **Zuletzt** `LOOKUP_DONE = 1`

Damit kann auch ein früh feststehendes negatives Ergebnis die Wartephase sofort beenden. `LOOKUP_DONE=1` bedeutet „Ergebnis vollständig“, nicht „Name gefunden“. Nach diesem Abschluss darf die Middleware das Ergebnis desselben Auftrags nicht mehr ändern. Keine konkurrierenden Antwortschreiber für denselben Auftrag.

`resolved` setzt eine eindeutige Auswahl durch die Middleware und einen nichtleeren Namen voraus. Bei mehreren Patienten bleibt der Name leer, auch bei identischen Namen. Nummernnormalisierung, APS-Abfrage, Cache und Trefferbeurteilung sind Middleware-Aufgaben. Der Anzeigename muss ein einzeiliger UTF-8-Wert ohne CR/LF/NUL sein; Anwendungsgrenze 80 Zeichen. Er wird als Text behandelt, nicht als Dialplan-Ausdruck oder Befehl.

Die Middleware setzt **niemals `CALLERID(name)` oder `CALLERID(num)`**. Aufgelegte Kanäle, überholte Request-IDs und bereits geschlossene Lookup-Aufträge werden verworfen. Ein AMI-Fehler vor dem letzten Schritt lässt `LOOKUP_DONE` unverändert. Asterisk entscheidet dann spätestens an seiner eigenen Frist über die Weiterleitung. [AMI Setvar](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/AMI_Actions/Setvar/)

### 4.4 Höchstens eine Sekunde warten und einmal entscheiden

Die Lookup-Frist beträgt insgesamt 1000 ms ab Auslösung der Anfrage. Kein synchroner HTTP-/APS-Aufruf, Shellkommando oder Netzwerk-AGI im Dialplan. Die Middleware darf fehlen, abstürzen oder langsam antworten, ohne die Telefonie über diese Frist hinaus aufzuhalten.

Als Asterisk-Baustein ist `WaitForCondition()` vorgesehen. Beispiel für das dynamische Warten auf das Abschlussflag:

```asterisk
; Syntaxreferenz: Der echte Hook verwendet die noch verbleibende Frist.
same => n,WaitForCondition(#,#["#{LOOKUP_DONE}"="1"],1,0.01)
```

Den Ausdruck nicht vorab mit normalen `${...}`-Ersetzungen auf einen konstanten Wert reduzieren. Ein bereits fertiges Ergebnis beendet das Warten beim nächsten Prüfschritt. Der Installer prüft `app_waitforcond.so`; fehlt das Modul, muss er dies erkennen und den Hook ohne Telefonieblockade deaktiviert lassen, bis die Voraussetzung erfüllt ist. [WaitForCondition](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/Dialplan_Applications/WaitForCondition/)

**Deadline-Grenzfall:** Der Asterisk-20-Quellstand prüft die Bedingung vor der Timeoutprüfung. Deshalb nicht allein `WAITFORCONDITIONSTATUS=TRUE` als Fristnachweis verwenden. Der Hook berechnet die verbleibende Zeit und prüft die Deadline nochmals vor der Namensübernahme. Eine bereits abgelaufene Frist darf nicht als Timeout `0` an `WaitForCondition` übergeben werden, weil damit unbegrenzt gewartet würde. Der nominelle Timer und die Abnahme berücksichtigen die zeitliche Auflösung des Betriebssystems; fachlich wird nach Ablauf kein Name mehr angenommen. [Implementierung von WaitForCondition](https://github.com/asterisk/asterisk/blob/20/apps/app_waitforcond.c)

Nach Ende der Wartephase friert der Dialplan die Entscheidung in eigenen `KF_PHONE_*`-Variablen (Protokollkonvention; AMI besitzt keine Schreibsperre pro Variable) ein:

- Noch innerhalb der Frist, vollständig, passende Result-ID, Status `resolved`, Name vorhanden: `CALLERID(name)` übernehmen, Status `resolved`, `Applied=1`.
- Vollständiges negatives Ergebnis: `not_found`, `ambiguous` oder `error`, `Applied=0`.
- Frist überschritten: `timeout`, `Applied=0`.
- Falsche Result-ID, ungültiger Zustand oder Fehler der Warteanwendung: `error`, `Applied=0`; normal weiterleiten.
- In allen Fällen bleibt `CALLERID(num)` erhalten. Anschließend folgt der vorhandene Dial-/Queue-Ablauf. Keine späteren Namensupdates für diesen Anruf.

Ein Abschlussereignis meldet die **tatsächlich getroffene** Entscheidung:

```text
Event: UserEvent
UserEvent: KienzlefonLookupFinished
SchemaVersion: 1
RequestId: <Lookup-ID>
SourceUniqueid: <UNIQUEID>
Status: resolved | not_found | ambiguous | error | timeout
Applied: 0 | 1
```

Das Ereignis enthält keinen Patientennamen. Die Middleware unterscheidet das eingefrorene Ergebnis für die Telefonanzeige von ihrer Patientensuche für die Webansicht; dort dürfen später noch Kandidaten erscheinen. Ein Auflegen während des Hooks beendet den Kanal normal; dafür ist kein nachträgliches Abschlussereignis erforderlich.

## 5. Vertrag für Click-to-Dial

### 5.1 Arbeitsplatz → Middleware

Der registrierte URI-Handler übergibt eine normalisierte Zielrufnummer und die bei Installation zugeordnete Nebenstelle an `POST /api/v1/calls`. Die Arbeitsplatzkennung muss mit dieser Zuordnung übereinstimmen. Wiederholung desselben Auftrags erzeugt keinen zweiten Anruf. URI-Parameter dürfen weder einen Dialplan-Kontext noch freie AMI-Felder bestimmen.

```json
{
  "client_id": "empfang-1",
  "extension": "201",
  "number": "023311234567",
  "request_id": "<UUID>"
}
```

Die API bestätigt zunächst nur die Annahme des Auftrags und liefert eine Vorgangs-ID. AMI- und APS-Zugangsdaten bleiben auf dem Middleware-Server. Die Gastfreigabe benötigt keine Anmeldung; daraus folgt keine Ablage von Steuerungszugangsdaten im Share.

### 5.2 Middleware → Asterisk

Beispiel für einen ausgehenden Auftrag; Werte kommen aus validierter Konfiguration:

```text
Action: Originate
ActionID: kf-c2d-<UUID>
Channel: PJSIP/201
ChannelId: kf-<UUID>
Context: kienzlefon-click-to-dial
Exten: 023311234567
Priority: 1
Timeout: 20000
Async: true
EarlyMedia: false
CallerID: Rueckruf <023311234567>
Variable: __KF_C2D_ID=<UUID>
Variable: __KF_C2D_CLIENT=empfang-1
Variable: __KF_C2D_EXTENSION=201
```

`CallerID` in diesem Beispiel bezeichnet die Anzeige am zuerst gerufenen Mitarbeitertelefon. Sie ist **nicht** die ausgehende Praxis-Absenderrufnummer. Der Ausgehkontext muss diese vor dem Provider-Dial ausdrücklich korrekt setzen. `ChannelId` erleichtert die Zuordnung bereits vor Annahme der Nebenstelle; die vererbte Auftrags-ID verbindet nachfolgende Rufabschnitte. Alle IDs müssen pro Auftrag eindeutig sein. [AMI Originate](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/AMI_Actions/Originate/)

### 5.3 Neuer Dialplan-Einstieg

Der kienzlefon-Installer erstellt **`[kienzlefon-click-to-dial]`**. Dieser Kontext:

1. Wird erst nach Annahme des ersten Rufabschnitts an der Mitarbeiter-Nebenstelle ausgeführt.
2. Prüft Auftrags-ID, freigegebene Nebenstelle und Zielnummer. Definiert sind Ziffern sowie optional ein führendes `+`; Umwandlung in die vom vorhandenen Ausgehkontext erwartete Schreibweise erfolgt zentral. Keine beliebigen SIP-URIs, Kontexte, Anwendungen oder Dial-Strings übernehmen.
3. Setzt die bisherigen, für diese Nebenstelle geltenden Wählberechtigungen und Routinginformationen. Eine vom Rückrufdisplay geänderte `CALLERID(num)` darf nicht als Nachweis der internen Nebenstelle dienen; dafür wird `KF_C2D_EXTENSION` verwendet und geprüft.
4. Meldet `UserEvent: KienzlefonClickToDialProgress` mit `SchemaVersion: 1`, `RequestId: <KF_C2D_ID>`, `Phase: dialing_target`, `SourceUniqueid: <UNIQUEID>`.
5. Übergibt an die **vorhandene kienzlefon-Ausgehlogik**. Diese entscheidet Provider, Amts-/Landesvorwahlen, Sperren und Praxis-Absenderrufnummer. Keine zweite unabhängige Provider-Dial-Anweisung hinzufügen.
6. Sorgt dafür, dass Ziel-Besetzt, Nichtannahme, Abbruch oder Fehler den Mitarbeiterkanal sauber beenden. Kein hängenbleibender Rufabschnitt.

Der echte Name des bestehenden Ausgehkontexts ist bei der Implementierung aus dem kienzlefon-Projekt zu ermitteln. Ein erfundener Kontextname darf nicht als fertige Integration ausgeliefert werden. Der neue Kontext wird nicht pauschal in öffentlich erreichbare Eingangskontexte eingebunden.

**Fortschritt:** `requested → ringing_extension → dialing_target → ringing_target → connected → ended`, daneben `failed`/`cancelled`/`unknown` nach tatsächlich beobachtetem Verlauf. Nicht jede Zwischenstufe muss auftreten. `Response: Success`, `OriginateResponse: Success` und das eigene `dialing_target`-Ereignis bedeuten noch kein verbundenes Patientengespräch. Erst Annahme des zweiten Rufabschnitts und passende Brückenzugehörigkeit begründen `connected`. Nach Verbindungsverlust unbekannten Fortschritt kennzeichnen; nicht automatisch erneut wählen.

## 6. SMB und Plattformen: verbindliche Abgrenzung

Diese Arbeiten gehören zum Middleware-/Arbeitsplatzinstaller, nicht in den Asterisk-Dialplan:

- Ubuntu, Debian und Raspbian/Raspberry Pi OS berücksichtigen; unterstützte Versionen und Architekturen im Installer prüfen und dokumentieren. Keine ausschließliche Bindung an eine x86-Binärdatei.
- SMB-Share heißt exakt `kienzlefon-GDT`. Gastzugriff ohne Benutzeranmeldung ist festgelegt. Clients müssen Dateien lesen und die für T2meds tatsächliche Abholung notwendigen Lösch-/Umbenennungsoperationen ausführen können.
- Pro Client eigenes Verzeichnis; gleichzeitige Aufrufe verschiedener Clients dürfen sich nicht überschreiben. Vorhandene, nicht abgeholte GDT-Aufträge nicht still ersetzen. Nicht abgeholte Aufträge müssen sichtbar als ausstehend/fehlgeschlagen behandelt werden, damit nach einem späteren T2med-Start keine unbeachteten Altaufträge entstehen.
- Vorhandene Samba-Konfiguration, Includes, Serverrolle, Benutzer, Shares, ACLs, Bindadressen und Ports inventarisieren. Eigene Konfiguration additiv integrieren, vorher sichern und mit `testparm` prüfen. Wiederholung und Deinstallation entfernen beziehungsweise ändern nur eigene Bestandteile.
- `guest ok`/`guest only` sind sharebezogen; `map to guest` ist dagegen global. Deshalb nicht blind globale Gastzuordnung, Serverrolle, Signierungsregeln oder andere bestehende SMB-Einstellungen ändern. Bei inkompatibler vorhandener Konfiguration einen klaren Konflikt ausgeben und eine getrennte SMB-Instanz mit eigener Netzwerkadresse als Installationsvariante vorsehen. Den vorhandenen Dienst weder stoppen noch ersetzen. [Samba-Konfigurationsreferenz](https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html)
- Bei der Client-Abnahme echten Gastzugriff auf den Zielsystemen testen. Verbindungsprobleme eindeutig melden, nicht durch eine unbemerkte Umkonfiguration anderer Freigaben kaschieren.

## 7. Abnahmekriterien für das kienzlefon-Projekt

1. **Neuinstallation und Update:** zweimalige Ausführung erzeugt keine doppelten Includes, Benutzer oder Hooks. Vorhandene AMI-Nutzer funktionieren weiter; Secret bleibt erhalten.
2. **Zwei Topologien:** Middleware auf demselben Host und auf einem getrennten Host anmelden. Die richtige ACL-Quelle ist zulässig, andere Quellen sind abgewiesen.
3. **Rechte:** `CoreShowChannels`, `QueueStatus`, Lookup-`Setvar` auf einem Testkanal und `Originate` funktionieren ohne `write=all` oder CLI-Rechte. Benötigte Events werden empfangen.
4. **Frühes Ergebnis:** künstliches eindeutiges Ergebnis nach ca. 100 ms lässt das Telefon früh mit Namen klingeln; keine feste volle Sekunde Wartezeit.
5. **Negatives Ergebnis:** kein Treffer, mehrere Treffer und APS-Fehler lassen den Anruf ohne APS-Namen normal weiterlaufen. Frühe vollständige Negativergebnisse beenden die Wartephase ebenfalls früh.
6. **Ausfall:** Middleware gestoppt, AMI unterbrochen und APS langsam testen. Es gibt keine zusätzliche Wartephase über das 1000-ms-Budget hinaus, abgesehen von unvermeidlicher Timer-/Schedulerauflösung. Keine unbegrenzte Warteanweisung.
7. **Grenze und Verspätung:** Antwort unmittelbar vor, an und nach der Deadline testen. Nach Ablauf kein Name auf dem bereits weiterlaufenden Anruf; späte Variablen verändern die Telefonanzeige nicht.
8. **Isolation:** mehrere parallele Eingangskanäle, identische Telefonnummern und Auflegen während des Lookups führen zu keiner Vermischung. Pro Eingangskanal nur ein Lookup, auch bei Queue-Überlauf.
9. **Rückruf:** Mitarbeiter nimmt nicht ab → Ziel wird nicht angerufen. Mitarbeiter nimmt ab → vorhandene Ausgehroute wählt das Ziel mit der korrekten Praxis-Absenderrufnummer. Ziel-Besetzt/Nichtannahme/Auflegen räumen beide Rufabschnitte auf.
10. **Zustände:** Originate-Annahme wird nicht als Patientengespräch angezeigt. Zwei Rufabschnitte und Queue-Eintrag werden korrekt einem logischen Vorgang zugeordnet. Rückfragen und Transfers separat prüfen.
11. **Wiederverbindung:** bei aktiven und wartenden Anrufen Middleware neu verbinden; bis zum Abgleich `stale`, anschließend keine doppelten oder wiederbelebten Anrufe. Keine automatische Wiederholung eines unklaren Wählauftrags.
12. **Bestandsbetrieb:** vorhandene direkte Anrufe, Queues, Überläufe, Öffnungszeiten und Ausgehregeln funktionieren mit aktivierter und deaktivierter Integration unverändert weiter.

Zur Diagnose dürfen CLI-Abfragen genutzt werden, ohne diese CLI-Rechte dem AMI-Benutzer zu geben:

```bash
sudo asterisk -rx 'core show version'
sudo asterisk -rx 'core show application WaitForCondition'
sudo asterisk -rx 'core show application UserEvent'
sudo asterisk -rx 'manager show settings'
sudo asterisk -rx 'manager show user kienzlefon-middleware'
sudo asterisk -rx 'dialplan show kienzlefon-lookup'
sudo asterisk -rx 'dialplan show kienzlefon-click-to-dial'
```

## 8. Erwartetes Ergebnis der Übergabe

Das kienzlefon-Projekt liefert die Installer-Anpassungen, die beiden Dialplan-Kontexte, die Integration in die vorhandenen Ein-/Ausgehpfade, Konfigurationsparameter, dokumentierte Defaults und die Ergebnisse der obigen Tests. Die Rückmeldung nennt insbesondere den tatsächlich angebundenen Ausgehkontext sowie AMI-Adresse, Port und Benutzer. Das Secret wird separat geschützt übergeben.

Die alten lokalen Prototyp-Anweisungen in `docs/ASTERISK.md` sind für diese Zielarchitektur abgelöst. Aus dieser Spezifikation allein folgt noch keine Änderung am laufenden Server.
