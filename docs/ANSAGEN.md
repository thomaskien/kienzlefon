<!--
kienzlefon
Version: 2.4.2
Changelog:
- 2.4.2: Zahlen und Uhrzeiten vor der Spracherzeugung deutsch ausschreiben.
- 2.4.1: Kokoro-Thorsten als Standard fuer lokale Ansagen ergaenzt.
- 2.4.0: Explizite Abspielmodi und sichere Behandlung leerer Texte dokumentiert.
- 1.5: Signaltonhinweis des telefonischen Aufnahmebausteins aktualisiert.
- 1.4: PIN-Bausteine entfernt und Administrationsnummern klar neu belegt.
- 1.3: Stabile Nummerierung aller generierten und administrativen Ansagen eingefuehrt.
-->

# Ansagen

Ab 2.4.1 erzeugt standardmaessig Kokoro-Thorsten die deutschen Ansagen lokal
auf CPU. Piper und Qwen bleiben im Installer und Webinterface waehlbar.
`[tts].kokoro_speed` steuert die Kokoro-Sprechgeschwindigkeit (Standard 1.0).
Manuelle Aufnahmen und Pausenmarker bleiben erhalten. Installation und
Konfigurationsbeispiele stehen in der [README](../README.md).

Seit 2.4.2 schreibt der gemeinsame Generator Zahlen und Uhrzeiten vor der
Spracherzeugung deutsch aus. Dies gilt fuer Kokoro, Piper und Qwen, auch fuer
Vorschauen und Sonderansagen. Beispiele:

- `Für unsere Öffnungszeiten drücken Sie 6.` → `Für unsere Öffnungszeiten drücken Sie sechs.`
- `08:30 Uhr` oder `08.30 Uhr` → `acht Uhr dreißig`
- `8 Uhr 05` oder `08:05` → `acht Uhr fünf`
- `14 Uhr` → `vierzehn Uhr`; `1 Uhr` → `ein Uhr`

Auch dynamische Oeffnungs- und Telefonzeiten durchlaufen diese Umwandlung.
Konfiguration und bearbeitbare Texte im Webinterface behalten ihre Eingabeform;
Pausenmarker wie `{pause:700}` bleiben Zeitsteuerung. Beim normalen Update
werden betroffene automatisch erzeugte Ansagen anhand des gesprochenen Texts
neu erzeugt; `--all` ist dafuer nicht erforderlich. Gespeicherte TTS-Fassungen
geplanter Sonderansagen werden ebenfalls aktualisiert. Manuelle Aufnahmen
werden weiterhin als Audioquelle verwendet.

Die Nummern sind verbindlich und werden in spaeteren Versionen nicht
verschoben. Neue Bausteine werden ausschliesslich am Ende angehaengt. Die
Texte stehen unter `[ansagen]` in `/etc/kienzlefon/kienzlefon.toml`; dynamische
Zeittexte werden aus den Zeitprofilen gebildet.

Bei der Queue-Positionsansage spricht Asterisk die **eigene Position** aus,
nicht die Anzahl der Anrufe davor. Die Bausteine 61 und 62 umschliessen diese
Zahl: "Sie sind auf Position" + "zwei" + "in der Warteschlange." Fuer Position
eins wird nur Baustein 60 ("Sie sind als Naechstes an der Reihe.") verwendet.
Siehe [Asterisk 20, app_queue](https://github.com/asterisk/asterisk/blob/20/apps/app_queue.c).
Die bisherigen Standardtexte "Vor Ihnen warten noch" / "Anrufe." werden bei
der Migration gemeinsam korrigiert und beim naechsten normalen Generatorlauf
neu erzeugt. Ist einer der Texte angepasst oder eine manuelle Aufnahme aktiv,
bleibt das Paar erhalten und muss bei Bedarf im Webinterface gemeinsam
angepasst beziehungsweise neu eingesprochen werden.

Die Wiedergabe wird getrennt vom Text unter `[ansagen_modus]` gesteuert.
Zulaessige Werte sind `immer`, `offen`, `zu` und `deaktiviert`. Fehlende Werte
bleiben aus Kompatibilitaetsgruenden `immer`; fuer `greeting_open`,
`greeting_closed` und `emergency` liefert die Vorlage die passenden
Standardmodi. Deaktivierte Ansagen bleiben fuer Vorschau und spaetere
Aktivierung erzeugbar. Ein leerer erforderlicher Text ist kein
Deaktivierungsweg und wird abgelehnt; nur der zusaetzliche Textbaustein
`phone_hours` darf leer bleiben.

1. `appointment`: Terminwunsch
2. `birth_date`: Geburtsdatum
3. `callback_number`: Rueckrufnummer bei fehlender Caller-ID
4. `callback_reason`: Grund der Rueckrufbitte
5. `completed`: Vielen Dank und bis bald
6. `emergency`: Notrufhinweis 112
7. `first_medication`: erstes Medikament
8. `first_name`: Vorname
9. `greeting_closed`: Begruessung Praxis geschlossen
10. `greeting_open`: Begruessung Praxis geoeffnet
11. `invalid`: ungueltige Eingabe
12. `last_name`: Nachname
13. `medication_choice`: weiteres Medikament oder Abschluss
14. `menu_closed`: Hauptmenue ausserhalb der Telefonzeiten
15. `menu_intro`: Einleitung zur Tastenauswahl
16. `menu_open`: Hauptmenue innerhalb der Telefonzeiten
17. `next_medication`: naechstes Medikament
18. `no_selection_closed`: freie Rueckrufaufnahme ausserhalb der Telefonzeiten
19. `no_selection_open`: Weiterleitung ohne Auswahl waehrend der Telefonzeiten
20. `opening_hours`: dynamische Oeffnungszeiten der Woche
21. `opening_hours_choice`: Auswahl 6 fuer Oeffnungszeiten
22. `other`: sonstiges Anliegen
23. `override`: Feiertags- und Sonderansage
24. `personal_data_fallback`: gemeinsame Aufnahme bei gescheiterten Personendaten
25. `pharmacy_access`: Auswahl 8 fuer Apotheken
26. `pharmacy_agent`: interne Apothekenansage
27. `phone_hours`: dynamische Telefonzeiten
28. `prescription_information`: Hinweis nach Rezeptaufnahme
29. `recording_hint`: allgemeiner Aufnahmehinweis
30. `referral_reason`: Grund der Ueberweisung
31. `specialist_access`: Auswahl 9 fuer Fachstellen
32. `specialist_agent`: interne Fachstellenansage
33. `specialty`: Fachrichtung der Ueberweisung
34. `submenu_five`: Rueckruf oder sonstiges Anliegen
35. `urgent_help`: Bereitschaftsdienst 116117
36. `whisper_failure`: Stoerungsweiterleitung zur Praxis
37. `blocked_destination`: gesperrtes Anrufziel
38. `admin_main`: Hauptmenue des Ansagen-IVR
39. `admin_prompt_select`: Auswahl der Ansagenummer
40. `admin_current_prompt`: Hinweis vor der aktuell verwendeten Ansage
41. `admin_prompt_actions`: Aktionen fuer den Ansagebaustein
42. `admin_record`: Hinweis auf Signalton und Start der telefonischen Aufnahme
43. `admin_record_ready`: Aufnahme als noch nicht aktiver Kandidat gespeichert
44. `admin_no_recording`: keine neue Aufnahme vorhanden
45. `admin_activated`: manuelle Ansage aktiviert
46. `admin_generated`: automatisch erzeugte Ansage aktiviert
47. `admin_special_menu`: Menue der Feiertags- und Sonderansage
48. `admin_special_keep`: Sonderansage aktiv, Telefonzeiten gueltig
49. `admin_special_block`: Sonderansage aktiv, Telefonzeiten gesperrt
50. `admin_special_disabled`: Feiertags- und Sonderansage deaktiviert
51. `admin_invalid`: ungueltige Eingabe im Ansagen-IVR
52. `admin_special_status_disabled`: Status Sonderansage deaktiviert
53. `admin_special_status_keep`: Status Sonderansage aktiv, Telefonzeiten gueltig
54. `admin_special_status_block`: Status Sonderansage aktiv, Telefonzeiten gesperrt
55. `webadmin_record`: Aufforderung zur Aufnahme ueber ein Telefon
56. `webadmin_record_actions`: Auswahl nach der Webinterface-Telefonaufnahme
57. `webadmin_record_saved`: Aufnahme als Kandidat gespeichert
58. `webadmin_record_discarded`: Aufnahme verworfen
59. `queue_thankyou`: Dank fuer die Geduld
60. `queue_youarenext`: Hinweis auf die naechste Warteposition
61. `queue_thereare`: Einleitung zur eigenen Warteposition ("Sie sind auf Position")
62. `queue_callswaiting`: Abschluss nach der Warteposition ("in der Warteschlange.")
63.–82. `queue_digit_0` bis `queue_digit_19`: eigenstaendige Zahlen Null bis Neunzehn
83.–91. `queue_digit_1_and` bis `queue_digit_9_and`: Einer mit angehaengtem „und“
92. `queue_digit_20`: Zwanzig
93. `queue_digit_30`: Dreissig
94. `queue_digit_40`: Vierzig
95. `queue_digit_50`: Fuenfzig
96. `queue_digit_60`: Sechzig
97. `queue_digit_70`: Siebzig
98. `queue_digit_80`: Achtzig
99. `queue_digit_90`: Neunzig
100. `queue_digit_one_neuter`: Ein (`digits/1N`)
101. `queue_digit_one_feminine`: Eine (`digits/1F`)
102. `queue_digit_hundred`: Hundert
103. `queue_digit_thousand`: Tausend
104. `queue_digit_million`: Million
105. `queue_digit_millions`: Millionen
106. `queue_digit_milliard`: Milliarde
107. `queue_digit_milliards`: Milliarden

Die vier Queue-Bausteine ersetzen gezielt die von der vorhandenen
Kienzlefax-Praxisqueue wirklich verwendeten schmalbandigen Standarddateien.
Sie werden wie alle anderen Ansagen als G.722, SLN16, A-Law und u-Law erzeugt
und koennen per TTS, Telefonaufnahme 777 oder Webinterface verwaltet werden.
Dasselbe gilt fuer die angehaengten Zahlenfragmente 63 bis 107. Der Generator
kopiert deren vier Asterisk-Formate zusaetzlich unter den von
`ast_say_number_full_de` verlangten Dateinamen nach
`/var/lib/asterisk/sounds/de_kienzlefon/digits/`. Neugenerierung und manuelle
Aktivierung aktualisieren diese Kopien atomar mit; System-Sprachpakete unter
`de/digits` bleiben unveraendert.

Beim Eintritt in jede von Kienzlefon verwendete Queue wird die Kanalsprache
auf `de_kienzlefon` gesetzt. Asterisks Sprachwahl verwendet wegen des
Praefixes `de` weiterhin die deutsche Zahlensyntax und kann fuer nicht
ueberschriebene Dateien auf die allgemeineren Sprach-/Sounds-Pfade
zurueckfallen. Dadurch bleiben die Ansagen unter `kienzlefon/` erreichbar.
Abgedeckt sind alle von der deutschen Zahlenfunktion fuer nichtnegative
32-Bit-Positionszahlen zusammengesetzten Fragmente, beispielsweise 21, Werte
ueber 100 sowie Million und Milliarde. Negative Zahlen sind fuer
Queue-Positionen nicht vorgesehen; `digits/minus` wird daher nicht ersetzt.
Eine Wartezeit wird in der aktuellen Kienzlefax-Queue nicht ausgegeben
(`announce-holdtime=no`); deshalb werden keine unbenutzten
Minuten-/Sekundenpfade pauschal ersetzt. Die Queue- und Zahlenansagen werden
unabhaengig davon immer installiert, ob Wartemusik aktiviert ist.

Die optionale Wartemusik ist davon getrennt. `[wartemusik].installiert`
beschreibt die vorhandenen Medien, `[wartemusik].modus` waehlt
`klingelzeichen` oder `musik`. Bei installierten Medien spielt 8805 die
Melodie nur intern zur Hoerprobe ab. Die eigene Asterisk-Klasse
`kienzlefon-wartemusik` veraendert weder globale Defaults noch fremde Klassen.
Die 16-kHz-Browser-/Asterisk-WAV liegt im Musikordner korrekt als
`wartemusik.wav16`; eine als 8-kHz-WAV missverstaendliche `wartemusik.wav`
wird dort nicht installiert. Die Weboberflaeche liefert davon weiterhin eine
geschuetzte Kopie mit WAV-MIME-Typ aus.
