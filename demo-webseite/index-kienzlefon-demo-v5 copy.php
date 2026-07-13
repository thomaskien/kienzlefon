<?php
// index.php – offene Demo mit Kontaktformular, Links und eingebetteter Telepraxis-App
// erzeugt einen OTP (1 Tag gültig, 1x verwendbar) und sendet an ./telepraxis-receive.php

$OTP_DB = __DIR__ . '/state/otp.sqlite';

function ensure_db($path) {
    if (!is_dir(dirname($path))) @mkdir(dirname($path), 0770, true);
    $pdo = new PDO('sqlite:' . $path);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('CREATE TABLE IF NOT EXISTS otps (
        token_hash TEXT PRIMARY KEY,
        expires_at INTEGER NOT NULL,
        used_at INTEGER
    )');
    return $pdo;
}

$pdo = ensure_db($OTP_DB);

// OTP erzeugen
$otp = bin2hex(random_bytes(16));
$hash = hash('sha256', $otp);
$expires = time() + 24 * 60 * 60;

$stmt = $pdo->prepare('INSERT OR REPLACE INTO otps(token_hash, expires_at, used_at) VALUES(:h, :e, NULL)');
$stmt->execute(array(':h' => $hash, ':e' => $expires));

header('Content-Type: text/html; charset=utf-8');
?>
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <meta name="description" content="KIENZLEfon – telefonische Anliegen strukturiert erfassen und an die Praxis übergeben." />
  <title>KIENZLEfon – Telefonassistenz für Arztpraxen</title>
  <style>
    :root {
      --ink: #08111f;
      --ink-soft: #384354;
      --red: #c40d1e;
      --red-dark: #990916;
      --green: #0aa65b;
      --line: #dfe4ea;
      --surface: #ffffff;
      --surface-soft: #f4f6f8;
      --shadow: 0 18px 50px rgba(8, 17, 31, 0.10);
      --radius: 20px;
    }

    * { box-sizing: border-box; }

    html { scroll-behavior: smooth; }

    body {
      margin: 0;
      color: var(--ink);
      background: var(--surface-soft);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }

    a { color: inherit; }

    .site-header {
      position: relative;
      z-index: 5;
      background: rgba(255,255,255,.96);
      border-bottom: 1px solid var(--line);
    }

    .header-inner {
      width: min(1220px, calc(100% - 40px));
      height: 92px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      overflow: hidden;
    }

    .brand {
      display: block;
      width: min(240px, 21vw);
      height: 76px;
      flex: 0 1 auto;
      overflow: hidden;
      text-decoration: none;
      min-width: 0;
    }

    .brand img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center 50%;
    }

    .top-nav {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 8px 20px;
      font-size: .95rem;
      font-weight: 750;
    }

    .top-nav a {
      text-decoration: none;
      color: var(--ink-soft);
    }

    .top-nav a:hover,
    .top-nav a:focus-visible { color: var(--red); }

    .hero {
      background: #fff;
      border-bottom: 1px solid var(--line);
    }

    .hero-inner {
      width: min(1220px, calc(100% - 40px));
      margin: 0 auto;
      padding: 20px 0 22px;
      display: grid;
      grid-template-columns: minmax(0, 1.08fr) minmax(410px, .92fr);
      gap: 30px;
      align-items: start;
    }

    .eyebrow {
      margin: 0 0 7px;
      color: var(--red);
      font-size: .82rem;
      font-weight: 900;
      letter-spacing: .16em;
      text-transform: uppercase;
    }

    h1 {
      max-width: 780px;
      margin: 0;
      font-size: clamp(2rem, 4vw, 3.55rem);
      line-height: .98;
      letter-spacing: -.055em;
    }

    .lead {
      max-width: 720px;
      margin: 12px 0 0;
      color: var(--ink-soft);
      font-size: clamp(.98rem, 1.45vw, 1.12rem);
    }

    .feature-list {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 18px;
      margin: 17px 0 0;
      padding: 0;
      list-style: none;
    }

    .feature-list li {
      position: relative;
      padding-left: 29px;
      font-size: .94rem;
      font-weight: 720;
      line-height: 1.28;
    }

    .feature-list li::before {
      content: "✓";
      position: absolute;
      left: 0;
      top: -.04em;
      display: grid;
      place-items: center;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      color: #fff;
      background: var(--green);
      font-size: .88rem;
      font-weight: 950;
    }

    .hero-actions {
      display: block;
      margin-top: 18px;
    }

    .hero-actions .button-primary {
      width: 100%;
    }

    .button,
    button {
      border: 0;
      border-radius: 12px;
      font: inherit;
      font-weight: 850;
      cursor: pointer;
      transition: transform .15s ease, background .15s ease, box-shadow .15s ease;
    }

    .button {
      display: inline-flex;
      min-height: 44px;
      align-items: center;
      justify-content: center;
      padding: 10px 15px;
      text-decoration: none;
    }

    .button-primary {
      color: #fff;
      background: var(--red);
      box-shadow: 0 10px 28px rgba(196, 13, 30, .20);
    }

    .button-primary:hover,
    .button-primary:focus-visible {
      background: var(--red-dark);
      transform: translateY(-1px);
    }

    .button-secondary {
      color: var(--ink);
      background: #fff;
      border: 1px solid var(--line);
    }

    .button-secondary:hover,
    .button-secondary:focus-visible {
      border-color: #b7c0ca;
      transform: translateY(-1px);
    }

    .tech-line {
      margin-top: 11px;
      color: #697586;
      font-size: .92rem;
      font-weight: 750;
      letter-spacing: .02em;
    }

    .form-card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .form-card-header {
      padding: 14px 20px 11px;
      border-bottom: 1px solid var(--line);
    }

    .form-card-header h2 {
      margin: 0;
      font-size: 1.28rem;
      letter-spacing: -.025em;
    }

    .form-card-header p {
      margin: 3px 0 0;
      color: var(--ink-soft);
      font-size: .84rem;
    }

    .form-body { padding: 3px 20px 15px; }

    label {
      display: block;
      margin: 8px 0 3px;
      color: #202b39;
      font-size: .82rem;
      font-weight: 780;
    }

    input,
    select,
    textarea {
      width: 100%;
      min-height: 37px;
      padding: 7px 10px;
      color: var(--ink);
      background: #fff;
      border: 1px solid #cdd4dc;
      border-radius: 9px;
      font: inherit;
      font-size: .91rem;
      outline: none;
      transition: border-color .15s ease, box-shadow .15s ease;
    }

    textarea {
      min-height: 52px;
      resize: vertical;
    }

    input:focus,
    select:focus,
    textarea:focus {
      border-color: var(--red);
      box-shadow: 0 0 0 3px rgba(196, 13, 30, .10);
    }

    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .hidden { display: none; }

    #sendBtn {
      width: 100%;
      min-height: 43px;
      margin-top: 12px;
      padding: 9px 16px;
      color: #fff;
      background: var(--red);
    }

    #sendBtn:hover,
    #sendBtn:focus-visible { background: var(--red-dark); }

    #sendBtn:disabled {
      cursor: wait;
      opacity: .65;
    }

    .note {
      margin-top: 4px;
      color: #6f7987;
      font-size: .83rem;
    }

    .status-panel {
      margin-top: 9px;
      border-top: 1px solid var(--line);
      padding-top: 8px;
    }

    .status-panel summary {
      cursor: pointer;
      color: var(--ink-soft);
      font-size: .88rem;
      font-weight: 780;
    }

    pre {
      max-height: 280px;
      margin: 10px 0 0;
      padding: 13px;
      overflow: auto;
      color: #283342;
      background: #f3f5f7;
      border: 1px solid var(--line);
      border-radius: 9px;
      font-size: .78rem;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .telepraxis-section {
      background: #fff;
      border-bottom: 1px solid var(--line);
    }

    .telepraxis-heading {
      width: min(1220px, calc(100% - 40px));
      margin: 0 auto;
      padding: 4px 0 3px;
      display: grid;
      grid-template-columns: minmax(0, 1.08fr) minmax(410px, .92fr);
      gap: 30px;
      background: #fff;
      border-bottom: 1px solid var(--line);
    }

    .telepraxis-heading-copy {
      grid-column: 1;
      min-width: 0;
    }

    .telepraxis-heading h2 {
      margin: 0;
      font-size: clamp(1.4rem, 2.2vw, 1.9rem);
      letter-spacing: -.035em;
    }

    .telepraxis-heading p {
      margin: 2px 0 0;
      color: var(--ink-soft);
    }

    .telepraxis-frame {
      display: block;
      width: 100%;
      height: 900px;
      border: 0;
      background: #fff;
    }

    .site-footer {
      background: var(--ink);
      color: #dce2e9;
    }

    .footer-inner {
      width: min(1220px, calc(100% - 40px));
      margin: 0 auto;
      padding: 24px 0;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px 24px;
      font-size: .91rem;
    }

    .footer-inner a {
      color: #fff;
      font-weight: 760;
      text-decoration: none;
    }

    .footer-inner a:hover,
    .footer-inner a:focus-visible { color: #ffb3ba; }

    .modalBackdrop {
      position: fixed;
      inset: 0;
      z-index: 30;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 20px;
      background: rgba(8, 17, 31, .62);
      backdrop-filter: blur(4px);
    }

    .modal {
      width: min(520px, 100%);
      padding: 26px;
      background: #fff;
      border-radius: 16px;
      box-shadow: var(--shadow);
    }

    .modal h2 { margin: 0 0 10px; }

    .modal .btnrow {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
    }

    .modal button {
      margin-top: 14px;
      padding: 11px 15px;
      color: #fff;
      background: var(--red);
    }

    @media (max-width: 960px) {
      .header-inner {
        height: auto;
        min-height: 92px;
        align-items: flex-start;
        flex-direction: column;
        padding: 8px 0 10px;
        overflow: visible;
      }

      .brand {
        width: min(240px, 76vw);
        height: 68px;
      }

      .top-nav { justify-content: flex-start; }

      .hero-inner {
        grid-template-columns: 1fr;
        gap: 24px;
        padding-top: 18px;
      }

      .form-card { max-width: 720px; }

      .telepraxis-heading {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 620px) {
      .header-inner,
      .hero-inner,
      .telepraxis-heading,
      .footer-inner {
        width: min(100% - 24px, 1220px);
      }

      .top-nav { gap: 8px 14px; font-size: .87rem; }
      .hero-inner { padding: 16px 0 20px; }
      .row { grid-template-columns: 1fr; gap: 0; }
      .feature-list { grid-template-columns: 1fr; }
      .form-card-header, .form-body { padding-left: 18px; padding-right: 18px; }
      .button { width: 100%; }
      .telepraxis-frame { height: 1100px; }
    }
  </style>
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="#top" aria-label="KIENZLEfon Startseite">
        <img src="./kienzlefon.png" alt="KIENZLEfon" />
      </a>

      <nav class="top-nav" aria-label="Demo-Links">
        <a href="./inbox/">Gespeicherte JSON-Dateien</a>
        <a href="https://github.com/thomaskien/kienzlefon" target="_blank" rel="noopener noreferrer">GitHub</a>
        <a href="https://www.kienzlefax.de/impressum/" target="_blank" rel="noopener noreferrer">Impressum</a>
      </nav>
    </div>
  </header>

  <main id="top">
    <section class="hero">
      <div class="hero-inner">
        <div class="hero-copy">
          <p class="eyebrow">Open Source · Asterisk · Whisper</p>
          <h1>Telefonische Anliegen klar erfassen.</h1>
          <p class="lead">
            KIENZLEfon nimmt Patientenanliegen strukturiert auf, transkribiert die Angaben
            und übergibt sie übersichtlich an die Praxis.
          </p>

          <ul class="feature-list">
            <li>Rezepte, Überweisungen, Termine und Rückrufbitten vorsortiert</li>
            <li>Vorname, Nachname und Geburtsdatum getrennt erfasst</li>
            <li>Direkte Übergabe an die Telepraxis-Oberfläche</li>
            <li>Self-hosted und transparent als Open-Source-Lösung</li>
          </ul>

          <div class="hero-actions">
            <a class="button button-primary" href="tel:+4923319108956">Testanruf: 02331 9108956</a>
          </div>

          <div class="tech-line">Für Arztpraxen entwickelt. Klarer Ablauf. Nachvollziehbare Übergabe.</div>
        </div>

        <section class="form-card" aria-labelledby="kontakt-title">
          <div class="form-card-header">
            <h2 id="kontakt-title">Kontaktformular</h2>
            <p>Alternativ zum Testanruf kann hier direkt eine Demo-Anfrage gesendet werden.</p>
          </div>

          <div class="form-body">
            <form id="f">
              <input type="hidden" id="otp" name="otp" value="<?php echo htmlspecialchars($otp, ENT_QUOTES, 'UTF-8'); ?>" />

              <label for="typ">Anliegen</label>
              <select id="typ" name="typ" required>
                <option value="rezeptbestellung">Rezept</option>
                <option value="ueb_req">Überweisung</option>
                <option value="termin">Termin</option>
                <option value="rueckruf_tel_grund">Rückrufbitte</option>
                <option value="sonstiges">Sonstiges</option>
              </select>

              <div class="row">
                <div>
                  <label for="vorname">Vorname</label>
                  <input id="vorname" name="vorname" autocomplete="given-name" />
                </div>
                <div>
                  <label for="nachname">Nachname</label>
                  <input id="nachname" name="nachname" autocomplete="family-name" />
                </div>
              </div>

              <div class="row">
                <div>
                  <label for="geburtsdatum">Geburtsdatum</label>
                  <input id="geburtsdatum" name="geburtsdatum" placeholder="TT.MM.JJJJ" />
                </div>
                <div>
                  <label for="telefon">Telefonnummer (notwendig)</label>
                  <input id="telefon" name="telefon" required autocomplete="tel" />
                </div>
              </div>

              <div id="block_rezept" class="hidden">
                <label for="medikamente">Medikamente</label>
                <textarea id="medikamente" name="medikamente" rows="2" placeholder="z. B. Ramipril 5 mg; Metformin 1000 mg"></textarea>
              </div>

              <div id="block_ueb" class="hidden">
                <label for="fachrichtung">Fachrichtung</label>
                <input id="fachrichtung" name="fachrichtung" placeholder="z. B. Augenheilkunde" />
                <label for="grund_ueb">Grund</label>
                <input id="grund_ueb" name="grund_ueb" placeholder="z. B. Katarakt" />
              </div>

              <div id="block_rueckruf" class="hidden">
                <label for="grund_rr">Grund</label>
                <input id="grund_rr" name="grund_rr" placeholder="z. B. Befundfrage" />
              </div>

              <div id="block_termin" class="hidden">
                <label for="termin_text">Terminwunsch</label>
                <textarea id="termin_text" name="termin_text" rows="2" placeholder="z. B. nächste Woche vormittags, wegen ..."></textarea>
                <div class="note">Wird beim Absenden in <code>grund</code> übertragen.</div>
              </div>

              <div id="block_sonstiges" class="hidden">
                <label for="anliegen">Anliegen</label>
                <textarea id="anliegen" name="anliegen" rows="2" placeholder="Worum geht es?"></textarea>
              </div>

              <button type="submit" id="sendBtn">Anfrage senden</button>
            </form>

            <details class="status-panel">
              <summary>Technischen Übertragungsstatus anzeigen</summary>
              <pre id="out">(noch nichts gesendet)</pre>
            </details>
          </div>
        </section>
      </div>
    </section>

    <section class="telepraxis-section" aria-labelledby="telepraxis-title">
      <div class="telepraxis-heading">
        <div class="telepraxis-heading-copy">
          <h2 id="telepraxis-title">Demo der Benutzeroberfläche</h2>
          <p>Die eingegangenen Anfragen erscheinen nach dem Absenden in der eingebetteten Oberfläche.</p>
        </div>
      </div>

      <iframe
        class="telepraxis-frame"
        src="./telepraxis-app-demo.php"
        title="Telepraxis-App"
        loading="eager"
      ></iframe>
    </section>
  </main>

  <footer class="site-footer">
    <div class="footer-inner">
      <span>© Dr. Thomas Kienzle · KIENZLEfon · Open Source</span>
      <a href="https://www.kienzlefax.de/impressum/" target="_blank" rel="noopener noreferrer">Impressum</a>
    </div>
  </footer>

  <div class="modalBackdrop" id="modalBg">
    <div class="modal">
      <h2>Die Anfrage wurde erfolgreich gespeichert</h2>
      <div class="btnrow">
        <button id="closeBtn" type="button">Fenster schließen</button>
      </div>
      <div class="note">Hinweis: Manche Browser schließen Tabs nur, wenn das Fenster per Script geöffnet wurde.</div>
    </div>
  </div>

  <script>
    const endpoint = "./telepraxis-receive.php";

    const out = document.getElementById("out");
    const sendBtn = document.getElementById("sendBtn");
    const modalBg = document.getElementById("modalBg");
    const closeBtn = document.getElementById("closeBtn");

    function show(msg) { out.textContent = msg; }

    const blocks = {
      rezeptbestellung: document.getElementById("block_rezept"),
      ueb_req: document.getElementById("block_ueb"),
      rueckruf_tel_grund: document.getElementById("block_rueckruf"),
      termin: document.getElementById("block_termin"),
      sonstiges: document.getElementById("block_sonstiges"),
    };

    function el(id) { return document.getElementById(id); }

    function showFor(typ) {
      Object.values(blocks).forEach(b => b.classList.add("hidden"));
      if (blocks[typ]) blocks[typ].classList.remove("hidden");

      el("medikamente").required = (typ === "rezeptbestellung");
      el("fachrichtung").required = (typ === "ueb_req");
      el("grund_ueb").required = (typ === "ueb_req");
      el("grund_rr").required = (typ === "rueckruf_tel_grund");
      el("termin_text").required = (typ === "termin");
      el("anliegen").required = (typ === "sonstiges");
    }

    const typSel = el("typ");
    typSel.addEventListener("change", () => showFor(typSel.value));
    showFor(typSel.value);

    function buildSummary(p) {
      const who = [p.vorname, p.nachname].filter(Boolean).join(" ").trim();
      const dob = p.geburtsdatum ? `Geburtsdatum ${p.geburtsdatum}` : "";
      const tel = p.telefon ? `Rückrufnummer ${p.telefon}` : "";
      const base = [who, dob, tel].filter(Boolean).join(", ");

      let topic = "";
      if (p.typ === "rezeptbestellung") topic = `Rezeptwunsch: ${p.medikamente || ""}`.trim();
      if (p.typ === "ueb_req") topic = `Überweisung: ${p.fachrichtung || ""}${p.grund ? " ("+p.grund+")" : ""}`.trim();
      if (p.typ === "rueckruf_tel_grund") topic = `Rückrufbitte: ${p.grund || ""}`.trim();
      if (p.typ === "termin") topic = `Terminwunsch: ${p.grund || ""}`.trim();
      if (p.typ === "sonstiges") {
        if (p.anliegen) topic = `Anliegen: ${p.anliegen}`.trim();
        if (p.grund) topic = `Anliegen: ${p.grund}`.trim();
      }

      const s1 = base ? `${base}.` : "";
      const s2 = topic ? `${topic}.` : "";
      const s3 = "Bitte bearbeiten.";
      return [s1, s2, s3].filter(Boolean).join(" ").trim();
    }

    closeBtn.addEventListener("click", () => {
      try { window.close(); } catch(e) {}
      modalBg.style.display = "none";
    });

    el("f").addEventListener("submit", async (e) => {
      e.preventDefault();

      if (!e.target.reportValidity()) {
        show("Bitte Pflichtfelder ausfüllen (Browser-Validierung hat blockiert).");
        return;
      }

      sendBtn.disabled = true;

      const uiTyp = typSel.value;
      const telefon = el("telefon").value.trim();
      const otp = el("otp").value.trim();

      const payload = {
        typ: uiTyp,
        id: "web-formular",
        telefon,
        otp,
        vorname: el("vorname").value.trim(),
        nachname: el("nachname").value.trim(),
        geburtsdatum: el("geburtsdatum").value.trim()
      };

      if (uiTyp === "rezeptbestellung") payload.medikamente = el("medikamente").value.trim();
      if (uiTyp === "ueb_req") { payload.fachrichtung = el("fachrichtung").value.trim(); payload.grund = el("grund_ueb").value.trim(); }
      if (uiTyp === "rueckruf_tel_grund") payload.grund = el("grund_rr").value.trim();
      if (uiTyp === "termin") payload.grund = el("termin_text").value.trim();
      if (uiTyp === "sonstiges") payload.anliegen = el("anliegen").value.trim();

      payload.zusammenfassung = buildSummary(payload);

      show("Sende...\n\n" + JSON.stringify(payload, null, 2));

      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        const txt = await res.text();

        if (res.ok) {
          modalBg.style.display = "flex";
          show(`HTTP ${res.status}\n\n${txt}`);
        } else if (res.status === 429) {
          show("Senden NICHT Erfolgreich: Empfang begrenzt auf maximal 20 Nachrichten in 10 Minuten, bitte warten und dann nochmal absenden.\n\n" + txt);
        } else {
          show(`Senden NICHT Erfolgreich (HTTP ${res.status}):\n\n${txt}`);
        }
      } catch (err) {
        show("Senden NICHT Erfolgreich: Netzwerkfehler.\n" + (err && err.message ? err.message : String(err)));
      } finally {
        sendBtn.disabled = false;
      }
    });
  </script>
</body>
</html>
