<!--
kienzlefon
Version: 1.5
Changelog:
- 1.5: Signaltonhinweis des telefonischen Aufnahmebausteins aktualisiert.
- 1.4: PIN-Bausteine entfernt und Administrationsnummern klar neu belegt.
- 1.3: Stabile Nummerierung aller generierten und administrativen Ansagen eingefuehrt.
-->

# Ansagen

Die Nummern sind verbindlich und werden in spaeteren Versionen nicht
verschoben. Neue Bausteine werden ausschliesslich am Ende angehaengt. Die
Texte stehen unter `[ansagen]` in `/etc/kienzlefon/kienzlefon.toml`; dynamische
Zeittexte werden aus den Zeitprofilen gebildet.

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
