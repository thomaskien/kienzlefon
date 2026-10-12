# Warteschlangen und Rufzyklen ab 2.5.5

Bei drei Empfangstelefonen gilt fuer einen unbeantworteten Anruf: zuerst 201,
im zweiten Rufzyklus 201 und 202, danach 201, 202 und 203. Besetzte Telefone
werden ausgespart. Die vorhandenen Werte `timeout` und `retry` der Praxisqueue
bestimmen die Dauer; standardmaessig beginnt alle 20 Sekunden ein neuer Zyklus.

Kommen A und B kurz nacheinander an, kann A zunaechst auf 201 und B auf 202
klingeln. Vor As zweitem Zyklus endet Bs unbeantworteter Rufversuch. Dann
klingelt A auf beiden freien Telefonen; B wartet, bis A angenommen wurde oder
aufgelegt hat. Nach der Annahme darf B an freien Telefonen klingeln, waehrend
As Gespraech weiterlaeuft. Wird B schon im ersten Zyklus angenommen, bleibt
dieses Gespraech bestehen und A wird auf die uebrigen freien Telefone verteilt.

Die vorhandenen Prioritaeten gelten weiterhin:

- Apotheken haben `QUEUE_PRIO=10` in der Praxisqueue und stehen vor normalen
  Anrufern. Bei mehreren gleich priorisierten Anrufen gilt deren Reihenfolge.
- Die rote Sonderqueue hat Gewicht 100 und Vorrang bei der Vergabe gemeinsam
  genutzter Telefone. Sie greift auch beim Fallback eines nicht erreichbaren
  roten Telefons. Bereits angenommene Gespraeche werden nicht unterbrochen.
- Ein bereits klingelnder Rufversuch laeuft bis zu seiner Klingelgrenze oder
  Annahme. Prioritaet entscheidet ueber die folgenden Angebote an freie Telefone.

## Ansagen

Position 2 lautet „Sie sind auf Position zwei in der Warteschlange.“ Die Zahl
bezeichnet die eigene Position, nicht die Zahl der davor wartenden Anrufe.
Position 1 verwendet weiterhin die eigene Ansage fuer den naechsten Anruf.

Der Installer ersetzt bekannte alte Standardpaare wie „Vor Ihnen warten noch“
und „Anrufe“. Eigene Texte und eigene Aufnahmen bleiben erhalten. Die vier
Queue-Fragmente werden zusaetzlich unter `<ansagenverzeichnis>/queue/`
bereitgestellt und mit absoluten Pfaden in der Queue eingetragen. Damit
koennen alte gleichnamige Standarddateien die neue Ausgabe nicht verdecken.

Nach dem Reload zeigt die Installation fuer jedes Fragment den erzeugten Text
und den aktiven Dateipfad. Bei eigenen Aufnahmen zeigt sie stattdessen deren
Quelle; deren gesprochener Inhalt muss selbst kontrolliert werden. Ansagen
lassen sich weiterhin ueber das Webinterface oder das Ansagen-IVR bearbeiten.

## Technik und Diagnose

Die native Asterisk-Queue verwaltet weiterhin Reihenfolge, Prioritaeten,
Positionsansagen und Gespraechsvermittlung. Die Telefon-Mitglieder laufen ueber
`Local/201@kienzlefon-queue-member` usw.; ihr Zustand kommt weiterhin vom echten
`PJSIP/201`-Endpunkt. Der AGI-Helper begrenzt nur die Klingeldauer des inneren
`Dial()`. Er setzt keine maximale Gespraechsdauer und sendet keine AMI-Hangups.
Die Mitarbeiter-Transferhooks liegen am echten PJSIP-Kanal.

Der Installer verwaltet `ringall`, `autofill=yes`, `ringinuse=no`, aufsteigende
Mitglieder-Penalties und die Regel `kienzlefon-progressive`. Die urspruenglichen
Mitgliederzeilen bleiben als Kommentare erhalten. Bei unbekannten, fehlenden
oder doppelten Mitgliedern bricht die Planung vor dem Schreiben ab.
Das gilt auch fuer fremde gleichnamige Rufregeln oder doppelte Einbindungen.
Die Regeln stehen in `queuerules-kienzlefon.conf`; bei 19 Sekunden Klingeln
und 1 Sekunde Pause liegen die Grenzen bei 19 und 39 Sekunden. Asterisk wertet
sie im Kopfpfad erst nach Ueberschreiten der Grenze aus.

Auf dem Server sind folgende lesende Pruefungen hilfreich:

```sh
sudo /opt/kienzlefon/venv/bin/kienzlefon-queue-setup verify --config /etc/kienzlefon/kienzlefon.toml
sudo /opt/kienzlefon/venv/bin/kienzlefon-queue-setup audio --config /etc/kienzlefon/kienzlefon.toml
sudo asterisk -rx 'queue show praxis'
sudo asterisk -rx 'queue show kienzlefon-sonder'
sudo asterisk -rx 'queue show rules kienzlefon-progressive'
sudo asterisk -rx 'dialplan show kienzlefon-queue-member'
```

Am besten in einer anruffreien Phase aktualisieren: Bereits vor dem Update
wartende Kanaele haben noch keine Rufzyklus-Metadaten. Neue Angebote hinter
einem solchen Kanal werden bis zu dessen Ausscheiden zurueckgehalten.

## Live-Abnahme

1. A anrufen lassen, kurz danach B: anfangs zwei verschiedene Telefone.
2. Beide unbeantwortet lassen: im zweiten Zyklus A auf zwei, danach auf allen
   drei freien Telefonen; B wartet.
3. A annehmen: B klingelt wieder an freien Telefonen, As Gespraech bleibt stabil.
4. Wiederholen und diesmal B sofort annehmen; dieses Gespraech bleibt bestehen.
5. Apotheke und roten Fallback sowie Annahme und Vermittlung ueber die Middleware
   pruefen. Bei Position 2 die vollstaendige Positionsansage anhoeren.

Die reine Wartemusik-Hoerprobe bleibt unter **8805** erreichbar.
