# API-Schlüssel für Google-Stimmen im Kienzlefon-Installer einrichten

Für die Stimme **Google Cloud TTS Chirp 3 HD** brauchst du einen API-Schlüssel aus einem Google-Cloud-Projekt mit aktiver Abrechnung. Du kannst den Schlüssel im Browser anlegen und ihn anschließend auf dem Kienzlefon-Server im Installer einfügen.

## In Google Cloud

1. Melde dich mit deinem Google-Konto an. Wähle oben ein vorhandenes Projekt oder klicke auf **Neues Projekt** und gib ihm einen Namen, etwa `Kienzlefon`. Wähle dieses Projekt auch bei den folgenden Schritten aus. [Google Cloud Console öffnen](https://console.cloud.google.com/)
2. Öffne im Menü **Abrechnung**. Verknüpfe das Projekt mit einem aktiven Rechnungskonto. Falls du noch keines hast, führt dich Google durch die Einrichtung. Die Abrechnung muss auch für die Nutzung des Freikontingents aktiv sein. [Einrichtung bei Google](https://docs.cloud.google.com/text-to-speech/docs/get-started?hl=de)
3. Öffne die **Cloud Text-to-Speech API** und klicke auf **Aktivieren**. Steht dort bereits **Verwalten**, ist die API für das ausgewählte Projekt aktiv. [Cloud Text-to-Speech API öffnen](https://console.cloud.google.com/apis/library/texttospeech.googleapis.com)
4. Gehe zu **APIs und Dienste → Anmeldedaten → Anmeldedaten erstellen → API-Schlüssel**. Gib dem Schlüssel einen Namen, etwa `Kienzlefon-Ansagen`. Lass die optionale Bindung an ein Dienstkonto ausgeschaltet. [Anmeldedaten öffnen](https://console.cloud.google.com/apis/credentials)
5. Wähle unter **API-Einschränkungen → Schlüssel einschränken** ausschließlich **Cloud Text-to-Speech API** aus. Hat der Server eine feste öffentliche Ausgangs-IP, kannst du diese zusätzlich unter **Anwendungseinschränkungen → IP-Adressen** eintragen. [Google-Anleitung zu Schlüsseleinschränkungen](https://docs.cloud.google.com/docs/authentication/api-keys?hl=de)
6. Klicke auf **Erstellen** und kopiere den angezeigten Schlüsselwert. Wenn Google den Schlüssel schon vor der Auswahl der Einschränkungen erstellt hat, öffne ihn unter **Anmeldedaten** über seinen Namen, hole Schritt 5 nach und klicke auf **Speichern**.

## Im Kienzlefon-Installer

1. Wähle bei **Erzeugungsmodell für automatische Ansagen** den Punkt **4) Google Cloud TTS Chirp 3 HD**. Fehlt Punkt 4, brauchst du eine Installer-Fassung mit Google-Unterstützung.
2. Füge bei **Google-API-Schluessel** nur den kopierten Schlüsselwert ein und drücke **Enter**. Das Terminal zeigt beim Einfügen weder Buchstaben noch Sternchen an.
3. Bestätige **Google-Stimme** und **Sprechtempo** jeweils mit **Enter**, wenn du die Vorschläge übernehmen möchtest. Bei einer Ersteinrichtung sind das `de-DE-Chirp3-HD-Sulafat` und `0.93`. Der Installer speichert den Schlüssel in `/etc/kienzlefon/google-tts.conf`. Bei einem späteren Lauf kannst du den vorhandenen Schlüssel beibehalten.

## Kosten für alle Ansagen

Mit der Beispielkonfiguration benötigt ein vollständiger Lauf für **107 Ansagen 6.400 Zeichen**. Der Entwicklungsstand für 2.6 enthält **109 Ansagen mit 6.689 Zeichen**. Beide Werte berücksichtigen den eingesetzten Praxisnamen aus der Vorlage, die Öffnungs- und Telefonzeiten sowie ausgeschriebene Zahlen. Eigene Texte und Sonderansagen verändern den Verbrauch.

Für Chirp 3 HD sind laut Google **1 Million Zeichen pro Monat kostenlos** (Stand 18. November 2026). Passt der Lauf ins verbleibende Freikontingent, kostet er **0 US-Dollar**. Ist das Kontingent bereits ausgeschöpft, kosten 1.000 Zeichen **0,03 US-Dollar**. Die beiden Beispielläufe kosten dann rund **0,19 bzw. 0,20 US-Dollar**. Kienzlefon speichert die erzeugten Audiodateien lokal. Beim Abspielen am Telefon fallen keine weiteren Google-TTS-Kosten an. [Google-Preise für Chirp 3 HD](https://cloud.google.com/text-to-speech/pricing?hl=de)
