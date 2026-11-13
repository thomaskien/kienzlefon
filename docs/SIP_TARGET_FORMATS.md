# SIP-Zielrufnummernformat je Provider-Endpunkt

Kienzlefon prueft und normalisiert ausgehende Rufnummern weiterhin vor dem Rufaufbau.
Wahlberechtigungen, Sperrlisten, Rufnummern-Audit und Absenderrufnummern bleiben unveraendert.
Erst nach erfolgreicher Freigabe setzt die Wahlpruefung `KZF_SIP_TARGET` fuer den finalen
`Dial(PJSIP/...)`-Aufruf.

In `/etc/kienzlefon/kienzlefon.toml` unter `[wahlregeln]`:

```toml
sip_zielformate = { "kfx-phone-in-endpoint" = "e164_plus" }
```

Die Zuordnung erfolgt ueber den Namen des konfigurierten Asterisk-PJSIP-Endpunkts.

- `digits` (Standard): bisheriges normalisiertes Format ohne `+`.
- `e164_plus`: deutsche Rufnummern `49...` werden zu `+49...` und erlaubte
  auslaendische Ziele `00...` zu `+...`.
- Die Ausnahmeziele `110`, `112`, `116116`, `116117` bleiben unveraendert.

Nicht aufgefuehrte Endpunkte behalten das bisherige Verhalten (`digits`).
Der Modus `e164_plus` sollte nur fuer Provider verwendet werden, die dieses
Format erwarten.

## Beobachtetes Fonial/Plusnet-Problem

Ein Fonial/Plusnet-SIP-Proxy beantwortete `sip:49176...@sip.plusnet.de`
mit `480 Temporarily Unavailable` / `Target not found`. Ein direkter
Test mit `sip:+49176...@sip.plusnet.de` war erfolgreich.

## Installation und Test

1. `kienzlefon.toml` und `/etc/asterisk` sichern.
2. In `[wahlregeln]` die gewuenschten Endpunkte unter `sip_zielformate` konfigurieren.
3. Aktualisierte Python-Version installieren; `kienzlefon-config` ausfuehren.
4. `kienzlefon-asterisk` neu generieren; bei individuell geaenderten Asterisk-Dateien
   den Diff vor dem produktiven Einspielen pruefen.
5. Dialplan neu laden und ausgehende Anrufe (normal und Click-to-Dial) testen.

Die Formatierung erfolgt im gemeinsamen Kontext `[kienzlefon-outbound]`
und gilt dadurch auch fuer externe Vermittlungen. Manuelle Aenderungen an
generierten Asterisk-Konfigurationsdateien sind nicht erforderlich.
