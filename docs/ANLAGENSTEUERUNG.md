# Anlagensteuerung für Kienzlefon

Die geschützte HTTP-Schnittstelle folgt dem [Telefonievertrag v1](telefonie-v1/README.md).
Der Anlagen-Installer richtet den Dienst ein, wenn er unter `[control_api]`
aktiviert ist. Die Freigabe für vorübergehende Änderungen beginnt gesperrt.
Für die erste Aktivierung auf einer bestehenden Installation zunächst die
Anlagenkonfiguration und eine Middleware-Identität vorbereiten. Der Installer
prüft AMI, die Praxisqueue und die Erfassungsfunktionen vor dem Wechsel.

## Einstellungen auf der Anlage

- `bind` und `port` legen die konkrete private VPN-Adresse und den Port fest.
  `allowed_networks` enthält die erlaubten Quellnetze der Middleware. Der
  Standardport ist 8767. Die Betriebsverbindung nutzt das Praxisnetz oder VPN.
- Die stabile `pbx_id` muss der Middleware-Anbindung und, sofern separat
  konfiguriert, `[anrufstatistik].pbx_id` entsprechen.
- `kienzlefon-control-setup register --id <installation> --client <platz> --token-file <privater-pfad>`
  registriert eine Middleware-Identität. `--client` ist wiederholbar.
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
