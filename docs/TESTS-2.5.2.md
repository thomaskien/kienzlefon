# Releasepruefung 2.5.2

Stand: 12.10.2026. Lokale Releasepruefung vor dem GitHub-Upload.

- **364 Tests bestanden** (27,08 Sekunden), gesamte Kienzlefon-Release-Suite.
  Die separat vorhandenen, noch nicht veroeffentlichten SMS-Arbeiten und ihre
  fuenf Testdateien gehoeren nicht zu diesem Release und wurden ausgeschlossen.
- **67 gezielte Middleware-Tests bestanden**, davon 30 neue Regressionstests.
  Der separate Sol-Worker hat Tests und unabhaengiges Review geliefert; der Lead
  hat den gefundenen Broadcast-Validierungsfehler korrigiert, den Diff geprueft
  und die Tests selbst erneut ausgefuehrt.
- Parsing von Stern/Einzel-IP/IPv6, Ablehnung von Wildcard-/Multicast-/Broadcast-
  Zieladressen, stabile Secrets, Dateirechte und TOML-Export geprueft.
- IPv4-/IPv6-ACLs, Wiederholung und Rueckwechsel auf eine Einzel-IP geprueft.
  Vorhandene AMI-Benutzer bleiben erhalten. Wildcard-/Fremdbindungen bei TCP/TLS
  sowie Web-AMI werden vor Aenderung von AMI-Dateien abgelehnt.
- Installer-Auswahl, Vorgaben bei Wiederholung, Rueckwechsel zu Einzel-IP/lokal
  und lokale Zieladresspruefung getestet. Keine Route-Abfrage mit `*`.
- UFW-Regelwechsel in beide Richtungen, Deaktivierung und Beibehaltung der
  Regelzuordnung bei fehlendem/inaktivem UFW getestet. Freigaben enthalten immer
  die konkrete Zieladresse und den Port.
- Installationsablauf mit ersetzten Asterisk-/UFW-/Socket-Aufrufen getestet:
  Aenderungen der Quellfreigabe trennen die eigene AMI-Sitzung, keine fremde
  Sitzung. Kein SIP-Befehl und kein Asterisk-Neustart.
- Bash-Syntax beider Installer, PHP-Syntax des Webinterfaces, Ruff (F/I) fuer
  geaenderte Middleware-Module und neue Tests sowie `git diff --check` bestanden.
- Python-Wheel `kienzlefon-2.5.2-py3-none-any.whl` erfolgreich gebaut;
  Version, MIT-Lizenzmetadaten und neue AMI-Laufzeitfunktionen kontrolliert.

Reproduzierbarer Suite-Aufruf:

```sh
python -m pytest -q \
  --ignore=tests/test_telepraxis_sms.py \
  --ignore=tests/test_telepraxis_sms_auto_reply.py \
  --ignore=tests/test_telepraxis_sms_cleanup.py \
  --ignore=tests/test_telepraxis_sms_queue.py \
  --ignore=tests/test_telepraxis_sms_web_queue.py
```

## Noch auf der Telefonanlage pruefen

Es wurde kein Live-Deployment und keine Verbindung zur produktiven AMI-
Schnittstelle ausgefuehrt. Die lokalen Tests ersetzen echte Netzwerk- und
Firewallaufrufe; sie belegen nicht das Routing der konkreten VPN-Installation.

1. Hauptinstaller aktualisieren und bei externer Middleware **Alle ueber das VPN
   erreichbaren Clients zulassen** waehlen. Konkrete lokale VPN-Zieladresse
   beibehalten, zum Beispiel 10.88.0.1. Benutzername und Secret bleiben erhalten.
2. Von zwei berechtigten VPN-Clients mit den vorhandenen Zugangsdaten verbinden.
   Lookup und Click-to-Dial pruefen. Ohne gueltiges Secret muss die Anmeldung
   weiterhin fehlschlagen.
3. Listener und eigene UFW-Regel kontrollieren: konkrete Zieladresse und AMI-Port,
   kein pauschales Lauschen/Freigeben auf allen Server-Adressen. Zusaetzliche
   Netzregeln und das tatsaechliche VPN-Routing separat pruefen.
4. Wieder auf eine einzelne Quell-IP einschraenken und anwenden. Die eigene
   breite UFW-Regel und alte eigene AMI-Sitzungen muessen entfernt werden;
   der zweite Client darf keine neue Sitzung aufbauen.
5. Installer erneut ausfuehren: Quellfreigabe, Zieladresse und Secret muessen
   erhalten bleiben. Details siehe [MIDDLEWARE.md](MIDDLEWARE.md).
