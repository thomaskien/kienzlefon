# AMI-Middleware ab Kienzlefon 2.5.2

Die Middleware wird separat entwickelt. Kienzlefon stellt den AMI-Zugang,
Lookup-Ereignisse und den validierenden Click-to-Dial-Einstieg bereit. Die
vollstaendige fachliche Uebergabe steht in
[AMI-Callmonitor-Uebergabe](../KIENZLEFON_INSTALLER_UEBERGABE_AMI_Callmonitor.md).

## Installation und Update

Im Hauptinstaller die Middleware einschalten und die beiden Funktionen
Namensaufloesung/Click-to-Dial getrennt waehlen. Bei einer neuen Einrichtung
sind menschliche Telefon-Nebenstellen fuer Click-to-Dial vorausgewaehlt,
KI-Telefone nicht. Jede Nummer wird einzeln abgefragt; vorhandene Entscheidungen
bleiben bei Updates die Vorgabe. Faxnummern, Provider und Funktionsnummern sind
keine auswaehlbaren Telefone.

Lokal verwendet die Einrichtung 127.0.0.1. Bei einem separaten Rechner wird
zwischen einer exakten Quell-IP und **Alle ueber das VPN erreichbaren Clients
zulassen** gewaehlt. Danach wird eine auf der Telefonanlage vorhandene Ziel-IP
abgefragt. IPv4 und IPv6 werden unterstuetzt; bei einer einzelnen Quell-IP
muessen beide Seiten dieselbe Adressfamilie verwenden. TCP ist der Standard;
bereits eingerichtetes AMI-TLS kann verwendet werden. Zertifikate und vorhandene
Listener werden nicht ersetzt.
Bei TCP muss der Uebertragungsweg vertrauenswuerdig sein, etwa ein Praxisnetz
oder WireGuard. AMI-Zugangsdaten bleiben ausschliesslich auf dem Middleware-Server.

Die eigene Datei `/etc/asterisk/manager_kienzlefon_middleware.conf` erlaubt
die ausgewaehlten Quellen. Rechte: `read=system,call,agent,user,dialplan` und
`write=call,originate,reporting`. Fremde Benutzer und Listener-Konfigurationen
werden nicht ersetzt. Listener-Konflikte oder globale Ereignissperren werden vor
Aenderungen abgelehnt. Ein aktives UFW erhaelt eine eigene markierte Regel;
andere Firewalls muessen entsprechend konfiguriert sein. Eine deaktivierte
Firewall wird nicht automatisch aktiviert.

Nach Aenderungen erfolgt `manager reload`, ohne Asterisk-Neustart. Bei
Secret-Wechsel, Benutzer-/Quell-IP-Aenderung oder Deaktivierung werden die
zugehoerigen alten Sitzungen getrennt. Falls in der Asterisk-CLI gekuerzte
Benutzernamen nicht eindeutig sind, fordert die Einrichtung zur manuellen
Trennung auf, statt fremde Sitzungen zu beenden.

## Alle Clients an der VPN-Adresse zulassen

Ab 2.5.2 bedeutet `quell_ip = "*"`: keine Einschraenkung auf eine einzelne
Quelladresse. Die Freigabe gilt fuer die Adressfamilie der konkreten `server_ip`.
Fuer eine bereits eingerichtete Anlage mit VPN-Adresse 10.88.0.1 im vorhandenen
`[middleware]`-Abschnitt nur diese Angabe aendern:

```toml
quell_ip = "*"
server_ip = "10.88.0.1"
```

Nach dem Software-Update die geaenderte Konfiguration anwenden:

```bash
sudo /opt/kienzlefon/venv/bin/kienzlefon-middleware install
```

Alternativ die neue Auswahl im Hauptinstaller verwenden. Bestehende Einzel-IP-
Angaben werden nicht automatisch erweitert; der Installer uebernimmt die letzte
Auswahl als Vorgabe. Zur Einschraenkung wieder eine konkrete Quell-IP eintragen
und anwenden. Benutzername und Secret bleiben bei beiden Wechseln erhalten.

Im Stern-Modus muessen der TCP-Listener und ein eventuell aktiver TLS-Listener
exakt an `server_ip` gebunden sein. Wildcard-Bindungen wie `0.0.0.0`/`::`, andere
Listener-Adressen und aktiviertes Web-AMI (`webenabled=yes`) werden abgelehnt,
bevor AMI-Dateien veraendert werden: dieselbe Benutzerfreigabe gilt sonst auch
fuer diese weiteren Zugangswege. Fremde Listener werden nicht automatisch
umgestellt. Bei Einzel-IP-Freigaben bleibt das bisherige Verhalten erhalten.

Bei aktivem UFW lautet die eigene Regel beispielsweise
`allow proto tcp from any to 10.88.0.1 port 5038 comment kienzlefon-middleware`.
Sie oeffnet nicht pauschal Port 5038 auf allen Server-Adressen. Die alte eigene
Regel wird beim Wechsel entfernt; andere Regeln bleiben bestehen. Bei inaktivem
oder fehlendem UFW bleibt die Regelzuordnung fuer einen spaeteren Lauf erhalten.

Die Bindadresse ist keine Pruefung des eingehenden VPN-Interfaces. Zugelassen
sind alle Clients, die diese Zieladresse ueber das vorhandene Routing und die
Firewall erreichen koennen. Fuer den vorgesehenen VPN-Betrieb muss diese
Erreichbarkeit durch die Netzkonfiguration auf die gewuenschten Clients begrenzt
sein. AMI-Benutzername und Secret bleiben unabhaengig davon erforderlich.

## Geschuetzte Uebergabedatei

`/etc/kienzlefon/middleware-connection.toml` und `middleware-secret` besitzen
Modus 0600. Das Secret wird bei normalen Updates wiederverwendet. Beispiel mit
Platzhalter, kein nutzbares Secret:

```toml
schema_version = 1
enabled = true
allowed_source_ip = "192.168.10.9"

[ami]
host = "192.168.10.2"
port = 5038
transport = "tcp"
username = "kienzlefon-middleware"
secret = "<zufaelliges-Secret>"
events = "on"

[lookup]
enabled = true
budget_ms = 1000

[click_to_dial]
enabled = true
context = "kienzlefon-click-to-dial"
extensions = ["201", "299"]
ring_timeout_ms = 20000
```

Ein optionales `ufw_rule`-Feld dient ausschliesslich der Verwaltung der eigenen
Firewallregel und wird von der Middleware ignoriert. Ebenso muessen zukuenftige
unbekannte optionale Felder ignoriert werden. Bei `enabled=false` keine Verbindung
herstellen. Die komplette TOML-Datei darf nicht protokolliert werden.

Ab 2.5.2 kann `allowed_source_ip` den Wert `"*"` enthalten. Er beschreibt die
Quellfreigabe, nicht das Verbindungsziel: Die Middleware verbindet sich weiterhin
mit `ami.host` und `ami.port`. `schema_version = 1` und die uebrigen Felder bleiben
unveraendert. Ein eigener Leser darf `allowed_source_ip` daher nicht mehr
zwingend als einzelne IP-Adresse parsen.

Beim Update von 2.5.0 liest der Installer den alten `middleware-connection.json`-
Export ein, erhaelt Secret und eigene Firewallregel und schreibt die TOML-Datei
atomar mit Modus 0600. Anschliessend wird die alte JSON-Datei als
`middleware-connection.json.bak.<Zeitstempel>` ebenfalls mit Modus 0600 gesichert
und aus dem bisherigen aktiven Pfad entfernt. Eine bereits vorhandene TOML-Datei
hat Vorrang. Die Middleware muss ab 2.5.1 TOML lesen (zum Beispiel mit Pythons
`tomllib`); Feldnamen und `schema_version = 1` bleiben unveraendert. AMI-Nachrichten
und die separate Middleware-API aendern dadurch ihr Format nicht.

Secret direkt am Terminal anzeigen oder bewusst erneuern:

```bash
sudo /opt/kienzlefon/venv/bin/kienzlefon-middleware show-secret
sudo /opt/kienzlefon/venv/bin/kienzlefon-middleware rotate-secret
```

Die Anzeige schreibt unmittelbar nach `/dev/tty`, nicht in die normale
Installer-Ausgabe. Nach einer Rotation die geschuetzte Uebergabedatei erneut an
die Middleware uebernehmen. Kein Secret in der Hauptkonfiguration
`kienzlefon.toml`, im Webinterface, auf SMB-Freigaben oder im Browsercode ablegen.

## Lookup-Vertrag

Externe Haupt-, Direkt- und Ueberlaufeingaenge normalisieren die Rufnummer und
rufen einmal pro Kanal `kienzlefon-lookup` auf. Interne Testziele und Telefonate
starten keinen Lookup. Es wird kein zusaetzliches Answer ausgefuehrt.

`KienzlefonLookupRequest` liefert SchemaVersion, RequestId, SourceChannel,
SourceUniqueid, SourceLinkedid, Number und BudgetMs. Die Middleware schreibt
auf SourceChannel nacheinander `LOOKUP_RESULT_ID`, `LOOKUP_NAME`,
`LOOKUP_STATUS` und zuletzt `LOOKUP_DONE=1`; jede Setvar-Response muss erfolgreich
sein. Statuswerte sind resolved, not_found, ambiguous oder error. Namen vorab
auf hoechstens 80 sichtbare Zeichen begrenzen, Steuerzeichen entfernen und
keine unbereinigten Fremddaten als AMI-Header verwenden.

Der Dialplan wartet mit WaitForCondition innerhalb eines absoluten Budgets von
1000 ms, kontrolliert die Deadline erneut und aendert ausschliesslich den Namen.
Die Rufnummer bleibt unveraendert. Bei Timeout, falscher RequestId, Fehler oder
leerer Antwort laeuft der bisherige Rufweg weiter. `KienzlefonLookupFinished`
enthaelt Status und Applied, keinen Patientennamen. Spaete Ergebnisvariablen
werden auf dem bereits weitergeleiteten Ruf nicht erneut ausgewertet.

Fehlen WaitForCondition oder UserEvent, deaktiviert der Installer nur den
Lookup-Pfad und exportiert `lookup.enabled=false`. Die uebrige AMI-Anbindung
bleibt verfuegbar. Nach einem Asterisk-Update den Installer erneut ausfuehren.

AMI-Rechte wirken auf Aktionskategorien, nicht auf einzelne Variablen oder
Kontexte. Auch `KF_PHONE_*` ist nur eine Protokollkonvention, keine Schreibsperre.
Der Middleware-Server ist daher eine vertrauenswuerdige Steuerungskomponente;
Arbeitsplaetze erhalten ausschliesslich dessen eingeschraenkte API.

## Click-to-Dial

Die Middleware originiert zuerst `PJSIP/<freigegebene Nebenstelle>`, dann
Context `kienzlefon-click-to-dial`, Exten Zielrufnummer, Priority 1, Async true
und EarlyMedia false. `__KF_C2D_ID` ist eine UUID, `__KF_C2D_CLIENT` die validierte
Arbeitsplatzkennung, `__KF_C2D_EXTENSION` die freigegebene Telefonnummer.
Ein vollstaendiges Originate-Beispiel steht in der Uebergabe.

Nach Abheben kontrolliert Kienzlefon diese Werte sowie den tatsaechlichen
PJSIP-Endpunkt. Externe Zielrufnummern enthalten nur Ziffern und optional ein
fuehrendes Plus. Die bestehenden Sperren gelten weiter. Der passende Haupt-
oder Direktprovider und die Praxis-Absenderrufnummer werden gesetzt, dann
uebernimmt `kienzlefon-outbound`. Eine eigene zweite Provider-Diallogik gibt es
nicht. `KienzlefonClickToDialProgress` mit Phase dialing_target bestaetigt den
Beginn des Zielrufes; verbunden ist ein Gespraech erst nach beobachteter
Zielannahme und passender Bruecke. Bei Verbindungsabbruch nicht automatisch
noch einmal waehlen.

## Pruefung auf der Telefonanlage

1. Bestehende AMI-Clients verbunden lassen, Installer durchlaufen lassen,
   Verbindung mit dem neuen Export pruefen und Ereignisse empfangen.
2. Aus externem Netz anrufen: Treffer, kein Treffer, mehrdeutiger Treffer,
   nicht erreichbare Middleware sowie Antworten vor/an/nach der Deadline testen.
   Rufnummer und Routing muessen erhalten bleiben.
3. Jeden eingerichteten externen Eingang testen; interne Testnummern duerfen
   keinen Lookup ausloesen. Ohne Middleware maximal das eine Lookup-Budget abwarten.
4. Click-to-Dial: freigegebenes Telefon, gesperrtes Telefon, falsche Endpunktangabe,
   ungueltige UUID, gesperrtes Ziel, Besetzt, Nichtannahme und Abbruch pruefen.
5. Secret erneuern und danach deaktivieren: alte Anmeldung/Sitzung darf nicht
   weiter verwendbar sein, fremde AMI-Clients muessen weiter funktionieren.

Die lokalen automatisierten Tests pruefen Konfiguration, Rechte, Dateimodi,
Updateverhalten, Dialplan-Erzeugung und Validierung. Echte AMI-Ereignisse,
Asterisk-Zeitverhalten und SIP-Gespraeche erfordern diesen Anlagentest.
