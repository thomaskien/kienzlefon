# Anlagensteuerung für Kienzlefon

Die geschützte HTTP-Schnittstelle folgt dem [Telefonievertrag v1](telefonie-v1/README.md).
Bei Installation, Update und Neukonfiguration fragt Kienzlefon nach der lokalen Rufgruppenverwaltung. Mit „Ja“ richtet der Installer den Steuerungsdienst auf Loopback, eine eigene lokale Identität und den AMI-Zugang ein. Für eine bestehende aktive Anbindung bleiben Listener, Identitäten und Freigaben erhalten. Der Installer prüft AMI, die Praxisqueue und die Erfassungsfunktionen vor der Umstellung.

Im Admin-Menü zeigt **Rufgruppen** die zuletzt durch Asterisk bestätigte Teilnahme. „Jetzt anmelden“ und „Jetzt abmelden“ ändern die laufende Teilnahme unabhängig von der Freigabe für externe Anwendungen. Bei einem veralteten Stand bittet die Oberfläche um erneutes Laden. „Teilnahme als Standard“ legt den Startzustand nach einem Asterisk-Neustart fest.

## Einstellungen auf der Anlage

- In `[control_api]` bestimmen `bind` und `port` die Adresse des Dienstes. Die lokale Einrichtung verwendet `127.0.0.1:8767` und erlaubt mit `allowed_networks = ["127.0.0.1/32"]` Zugriffe vom selben Rechner. Für eine getrennte Middleware müssen die erreichbare private Bind-Adresse und ihr erlaubtes Quellnetz zur Installation passen.
- Die stabile `pbx_id` muss der Middleware-Anbindung und, sofern separat
  konfiguriert, `[anrufstatistik].pbx_id` entsprechen.
- `sudo /opt/kienzlefon/venv/bin/kienzlefon-control-setup register --id <installation> --token-file <privater-pfad>`
  registriert einen neuen Zugang für die authentifizierten Arbeitsplätze einer Middleware-Installation.
  Eine oder mehrere Optionen `--client <platz>` beschränken den Zugang auf diese IDs.
  Bei der Schlüsselrotation einer vorhandenen Identität bleiben deren Arbeitsplatzrechte ohne `--client` erhalten.
  Der Token wird in der angegebenen neuen privaten Datei abgelegt. Die Anlage
  speichert in `credentials_file` die Identität, die Arbeitsplatzfreigaben und
  den SHA-256-Hash des Tokens. Für den App-Proxy gilt ein separater Schlüssel
  gemäß [HTTP-Vertrag](telefonie-v1/HTTP.md).
- Der Installer übernimmt bekannte AMI-Listener-Einstellungen und richtet
  ein getrenntes lokales Anlagenkonto ein. Das externe API-Secret berechtigt
  ausschließlich zur Übersicht und zu den Rufgruppenaufträgen.

## Rufgruppen

Bei der ersten Aktivierung speichert Kienzlefon die bisherigen Queue-Mitglieder
als Ausgangswerte. Danach hat jede Gruppe eigene Standards. Im Admin-Menü
**Rufgruppen** sind Standardteilnahme, Eignung und externe Rechte zum Hinzufügen
und Entfernen pro Nebenstelle getrennt einstellbar. In Normal kann zusätzlich
die vorhandene Rufstufe geändert werden.

„Änderungen aus App und Middleware erlauben“ schaltet externe Aufträge ein. Vorgabe für neue und bestehende Anlagen ist „Alle Arbeitsplätze (Standard)“. „Nur ausgewählte Arbeitsplätze“ begrenzt Aufträge auf die eingetragenen Platz-IDs. Eine leere Auswahl sperrt jeden Platz. Für jeden Dienstzugang gelten zusätzlich seine bisherigen Einschränkungen. Der Admin sieht die gekoppelten Schaltzugänge unter der Auswahl. Der globale Schalter bleibt bei Erstinstallation aus.

Unter jeder Nebenstelle lässt sich der Gerätename dauerhaft ändern. Die optionalen Einträge in `[nebenstellennamen]` der Anlagen-TOML verwenden die Nummer als Schlüssel. Der Anlagenstatus liefert den Namen in `extensions[].label`. Ohne Eintrag verwendet Kienzlefon den bisherigen Rollennamen.

Beim Speichern übernimmt Asterisk denselben Namen in die Anruferkennung der verwalteten Nebenstelle und bestätigt den geladenen Wert. Der Fon-Installer gleicht bei Installation und Update auch die vorhandenen Namen ab. Die Rufverteilung ordnet Mitglieder über ihre Schnittstelle zu. „Telefon 201“ kann deshalb weiterhin als Mitgliedsbezeichnung in der Warteschlange erscheinen.

Ein Update der Richtlinie allein ändert die vorübergehenden Mitgliedschaften
der übrigen Telefone nicht. Ändert die Administration die Standardteilnahme
eines Telefons, gilt der neue Wert für dieses Telefon unmittelbar nach dem
Anlagenabgleich. Eine Gruppe muss sowohl ein Standardmitglied als auch ein
effektives Mitglied behalten. Das rote Telefon erhält seinen separaten ersten
Rufversuch, wenn es dafür eingerichtet ist. Anschließend klingeln die aktiven
ROT-Mitglieder gemeinsam. Ohne rotes Telefon beginnt der Gruppenruf sofort.

Der Dienst bestätigt Änderungen über den nativen Queue-Bestand. Ein
Steuerungsdienst-Neustart verwendet dieselbe Asterisk-Epoch und erhält die
laufenden Rufgruppen. Beim Asterisk-Neustart gelten wieder die administrativen
Standards. Unterbrechungen mit unbestätigter Wirkung bleiben im Auftragsjournal
offen, bis die Anlage den Ausgang belegt. Die Auftrags-ID wird nicht erneut
ausgeführt. Ungültige oder veraltete Live-Stände liefern unbekannte Zähler.

## Anbindung von Middleware und Praxis-App

**Kienzlefon ab 2.6.11.** Der zusätzliche authentifizierte Endpunkt `GET /control/v1/routing/workplaces` liefert den wirksamen Umfang des aufrufenden Dienstzugangs. Ein eingerichteter Praxis-Schaltzugang kann folgende Antwort erhalten.

```json
{"schema_version":1,"pbx_id":"praxis-test","remote_enabled":true,"mode":"all","client_ids":[]}
```

`mode=all` erlaubt die vom angebundenen Dienst authentifizierten Arbeitsplätze dieser Praxis. Bei `mode=selected` gilt ausschließlich die Schnittmenge aus Anlagen-Auswahl und Dienstfreigabe in `client_ids`. Ein Lesezugang erhält immer `selected` mit leerer Liste. Für jede Änderung müssen zusätzlich `remote_enabled`, der frische Anlagenzustand, die Freigabe der Nebenstelle für die angeforderte Richtung und der Schutz des letzten Mitglieds erfüllt sein.

**Kopplung bei Neuinstallation und Update.** Der Fon-Helfer `python -m kienzlefon.t2med_counters describe` meldet `routing_pairing_version: 1`. Der Middleware-Installer kann neben dem bisherigen `control.sha256` einen separaten `routing.sha256` (64 Hexzeichen, private Datei mit Modus 0600 im Installer-Arbeitsverzeichnis) an `plan` übergeben. Das zugehörige zufällige 64-stellige Hex-Token speichert die Middleware privat. Fon registriert den Hash mit `apply` und unterstützt `rollback`. Ein bereits vorhandener externer Schaltzugang wird über seinen bisherigen Schlüssel samt Einschränkungen weiterverwendet. Ohne Rufgruppenschlüssel richtet die Kopplung wie bisher nur den Lesezugang ein. Intern behält eine Liste in den Anlagen-Credentials ihre bisherige Bedeutung. Nur das neue lokale Dateiformat 2 kann für einen eigens delegierten Schaltzugang `allowed_clients: null` ausdrücken.

**Folgearbeit T2med-Middleware.** Bei der Einrichtung und Reparatur den beschriebenen Schaltzugang koppeln. Mit dessen Token den Arbeitsplatzumfang, Schaltaufträge und deren Ergebnisse abrufen. In `src/HttpApi.php` und `src/TelephonyControl.php` den authentifizierten Praxis-App-Zugang und dessen Platzkennung auswerten. Im Modus „alle“ muss ein neuer App-Arbeitsplatz auch ohne separaten Eintrag im Click-to-Dial-Telefonverzeichnis schalten können. Ausdrücklich konfigurierte Zugriffsbeschränkungen bleiben wirksam. Bei älteren Gegenstellen nur bereits belegte Freigaben verwenden.

**Folgearbeit Kienzlefon-App.** In `telepraxis-telephony.php` den angemeldeten Arbeitsplatz serverseitig der Praxis zuordnen und den wirksamen Umfang beim Bootstrap, beim Absenden und beim Ergebnisabruf berücksichtigen. Meldet der gekoppelte Schaltzugang beim Update von App und Middleware `mode=all` bei aktiver Freigabe, ist bei bisher unbefüllten Standardlisten keine Nachpflege je Arbeitsplatz nötig. Eine ausdrücklich gewählte Beschränkung, auch „nur ausgewählte“ mit leerer Liste, bleibt verbindlich. In `telepraxis-telephony.js` den Haken nur aktivieren, wenn der aktuelle Arbeitsplatz im wirksamen Umfang liegt und der frische Status die jeweilige Aktion erlaubt. Die Anzeige verwendet bereits `extensions[].label`. Bei Nummer 201, beiden Richtungsrechten für Normal und gesperrtem ROT kann jeder authentifizierte Platz eines unbeschränkten Praxiszugangs Normal schalten, solange die Gruppe besetzt bleibt.

## Abnahme

Der gemeinsame [Abnahmeplan](telefonie-v1/ACCEPTANCE.md) umfasst unter anderem
Rufstufen, ROT mit und ohne rotes Telefon, laufende Gespräche, konkurrierende
Aufträge, Asterisk-Neustart und Rückkehr nach Verbindungsausfall. Die lokalen
Tests nutzen synthetische AMI-Daten und die echte HTTP-Schnittstelle des
Kienzlefon-Dienstes auf Loopback.

Der Anlagenabgleich nutzt die dokumentierten Asterisk-Aktionen für
[Queue-Mitgliedschaft](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/AMI_Actions/QueueAdd/),
[aktive Kanäle](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/AMI_Actions/CoreShowChannels/)
und [Brücken](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/AMI_Actions/BridgeInfo/).
