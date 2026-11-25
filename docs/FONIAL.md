# Fonial-/Plusnet-Vorlage fuer Kienzlefon

Die [PJSIP-Vorlage](../config/pjsip-fonial.conf.example) uebernimmt die am
17.11.2026 bereitgestellte Konfiguration fuer das Fonial-IP-Endgeraet
Kienzlefon, Nebenstelle 90. Sie verwendet `sip.plusnet.de` als Registrar und
`sbc.sip.plusnet.de` als ausgehenden Proxy. Zugangsdaten sind Platzhalter.

Bei einer Einrichtung mit dem modularen Kienzlefax-Installer 3.5.0 steht **Fonial / Plusnet** als Provider 7 für Fax- und Telefonieleitungen zur Wahl. Kienzlefon nutzt die konfigurierte Telefonieleitung. Die mit Kienzlefon gelieferte Beispielvorlage dient zum manuellen Abgleich bestehender Anlagen. [Modularer Kienzlefax-Installer](https://github.com/thomaskien/kienzlefax-fuer-linux/blob/main/installer-modular/kienzlefax-install-modular.sh)

## Einbindung

Die Vorlage setzt den vorhandenen UDP-Transport `transport-udp` und den
Kienzlefax-Eingangskontext `kfx-phone-in` voraus. Die Nebenstelle 90 ist die
Zuordnung in der Fonial-Anlage; die SIP-Zugangsdaten werden separat eingetragen.

| Platzhalter | Einzutragender Wert |
| --- | --- |
| `CHANGE_ME_FONIAL_CLIENT_USER` | Benutzerteil der Registrierungsadresse |
| `CHANGE_ME_FONIAL_AUTH_USERNAME` | SIP-Benutzername fuer die Anmeldung |
| `CHANGE_ME_FONIAL_AUTH_PASSWORD` | SIP-Passwort |
| `CHANGE_ME_FONIAL_FROM_USER` | Benutzerteil des ausgehenden From-Headers |

Die Benutzerwerte gemaess den Zugangsdaten des Fonial-Endgeraets setzen;
bei identischen Vorgaben denselben Wert an den betreffenden Stellen eintragen.
Sonderzeichen in Zugangsdaten entsprechend der Asterisk-Konfigurationssyntax
maskieren, insbesondere ein Semikolon als `\;`.

Die ausgefuellte Datei kann als `/etc/asterisk/pjsip-fonial.conf` mit
eingeschraenktem Lesezugriff abgelegt und in `pjsip.conf` eingebunden werden:

```ini
#include "pjsip-fonial.conf"
```

Vorher die bestehenden Provider-Definitionen in `pjsip-kfx-telefonie.conf`
abgleichen: Die Vorlage definiert bereits `kfx-phone-in-endpoint` und die
Fonial-Registrierung. Diese Definitionen muessen eindeutig sein, damit nicht
zwei Provider-Konfigurationen oder Registrierungen parallel aktiv werden.
Vom Installer verwaltete Dateien bei spaeteren Updates erneut abgleichen.
Die Beispielvorlage wird nicht automatisch durch den Installer aktiviert.

## Bedeutung von \;lr

`lr` steht fuer **loose routing**. Asterisk sendet die SIP-Anfrage ueber den
angegebenen Proxy; das eigentliche Ziel bleibt in der Request-URI erhalten.
Der Proxy ist der naechste Vermittlungsschritt und wird im Route-Header gefuehrt.
Die SIP-Grundlage beschreibt [RFC 3261, Abschnitt 12.2.1.1](https://www.rfc-editor.org/rfc/rfc3261.html#section-12.2.1.1).

In einer Asterisk-Konfigurationsdatei beginnt ein unmaskiertes `;` einen
Kommentar. Deshalb steht in der Datei genau ein Backslash vor dem Semikolon:

```ini
outbound_proxy=sip:sbc.sip.plusnet.de\;lr
```

Die resultierende SIP-URI lautet `sip:sbc.sip.plusnet.de;lr`. Backslashes am
Ende aller uebrigen Konfigurationszeilen gehoeren nicht in die Datei.
Die Proxy-Einstellung bleibt wie in der gelieferten Vorlage in Registrierung,
AOR und Endpunkt erhalten; siehe die
[Asterisk-Proxy-Dokumentation](https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/PJSIP-with-Proxies/).

## Format ausgehender Rufnummern

Mit der SIP-Zielformat-Erweiterung aus
[PR #1](https://github.com/thomaskien/kienzlefon/pull/1) kann fuer diesen Endpunkt
das Format mit fuehrendem Plus eingestellt werden. Im vorhandenen
`[wahlregeln]`-Abschnitt von `kienzlefon.toml` ergaenzen:

```toml
sip_zielformate = { "kfx-phone-in-endpoint" = "e164_plus" }
```

Damit wird beispielsweise `49176...` beim ausgehenden SIP-Ruf zu `+49176...`.
Die PJSIP-Vorlage selbst formatiert keine Rufnummern um. Aeltere 2.5.5-Staende
ohne diese Erweiterung unterstuetzen die Einstellung noch nicht.

Die Vorlage wurde auf konsistente Verweise und Maskierung geprueft. Eine
Registrierung oder ein Testanruf am echten Fonial-Anschluss wurde nicht ausgefuehrt.
