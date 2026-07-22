<?php
// telepraxis-receive.php – offene Demo-Version
// Version: 1.9
// Changelog:
// - 1.9: Telefonnummern und Caller-IDs vor der unverschluesselten Demoablage anonymisiert.
// IONOS: static PSK via Header X-TP-Token (kein Rate-Limit)
// Webformular: id == "web-formular" -> OTP (1 Tag, 1x) + Rate-Limit 20/10min
// Speichert jede Anfrage als einzelne UNVERSCHLÜSSELTE JSON-Datei nach ./inbox/
// Telefonnummern und Caller-IDs werden vor dem Speichern anonymisiert.

header('Content-Type: application/json; charset=utf-8');

// ======= Konfiguration =======
$INBOX_DIR = __DIR__ . '/inbox';

// IONOS-PSK (statisch) – in IONOS Tool Headers setzen: X-TP-Token: <dieser Wert>
$IONOS_PSK = 'CHANGE_ME_LONG_RANDOM_SECRET';

// OTP DB (für Webformular)
$OTP_DB = __DIR__ . '/state/otp.sqlite';

// Rate-Limit nur fürs Webformular
$WEB_RL_LIMIT = 20;
$WEB_RL_WINDOW_SEC = 10 * 60;

// ======= /Konfiguration =======

function scalar_str($v) {
    if (is_array($v) || is_object($v)) return '';
    return trim((string)$v);
}

function looks_like_phone_number($value) {
    if (is_array($value) || is_object($value) || is_bool($value) || $value === null) {
        return false;
    }

    $digits = preg_replace('/\D+/', '', (string)$value);
    return is_string($digits) && strlen($digits) >= 7;
}

function is_phone_field($key, $value = null) {
    $normalized = strtolower((string)$key);
    $normalized = preg_replace('/[^a-z0-9]/', '', $normalized);
    if (!is_string($normalized) || $normalized === '') return false;

    // IONOS verwendet id als Caller-ID; web-formular und andere Text-IDs bleiben erhalten.
    if ($normalized === 'id') return looks_like_phone_number($value);

    if (in_array($normalized, array('tel', 'telefon', 'telephone', 'phone', 'mobil', 'mobile', 'handy', 'fax', 'ani'), true)) {
        return true;
    }

    foreach (array('telefon', 'telephone', 'phone', 'rufnummer', 'caller', 'anrufer', 'callback', 'mobilnummer', 'handynummer', 'faxnummer') as $marker) {
        if (strpos($normalized, $marker) !== false) return true;
    }

    return false;
}

function collect_phone_values($value, &$phoneValues, $key = '', $phoneContext = false) {
    $phoneContext = $phoneContext || is_phone_field($key, $value);

    if (is_array($value)) {
        foreach ($value as $childKey => $childValue) {
            collect_phone_values($childValue, $phoneValues, $childKey, $phoneContext);
        }
        return;
    }

    if (!$phoneContext || is_object($value) || is_bool($value) || $value === null) return;

    $phoneValue = trim((string)$value);
    if ($phoneValue !== '') $phoneValues[] = $phoneValue;
}

function is_free_text_field($key) {
    $normalized = strtolower((string)$key);
    $normalized = preg_replace('/[^a-z0-9]/', '', $normalized);
    if (!is_string($normalized)) return false;

    return in_array($normalized, array(
        'zusammenfassung', 'summary', 'anliegen', 'grund', 'reason', 'message',
        'nachricht', 'text', 'comment', 'kommentar', 'description', 'beschreibung',
        'notes', 'notiz'
    ), true);
}

function anonymize_phone_patterns($text) {
    $anonymized = preg_replace_callback(
        '/(?<![\p{L}\p{N}])(?:\+|00)?\d(?:[ \t()\/.\-]*\d){6,}(?![\p{L}\p{N}])/u',
        function ($match) {
            $candidate = trim($match[0]);
            $compact = preg_replace('/[ \t()]+/', '', $candidate);

            // Datumsangaben sind keine Telefonnummern und bleiben lesbar.
            if (is_string($compact) && preg_match('/^(?:\d{1,2}[.\/-]\d{1,2}[.\/-](?:\d{2}|\d{4})|\d{4}-\d{2}-\d{2})$/', $compact)) {
                return $match[0];
            }

            return '#anonymisiert demo#';
        },
        (string)$text
    );

    return is_string($anonymized) ? $anonymized : (string)$text;
}

function anonymize_phone_data($value, $phoneValues, $key = '', $phoneContext = false) {
    $phoneContext = $phoneContext || is_phone_field($key, $value);

    if (is_array($value)) {
        $result = array();
        foreach ($value as $childKey => $childValue) {
            $result[$childKey] = anonymize_phone_data($childValue, $phoneValues, $childKey, $phoneContext);
        }
        return $result;
    }

    if ($phoneContext) {
        if ($value === null || trim((string)$value) === '') return $value;
        return '#anonymisiert demo#';
    }

    if (!is_string($value)) return $value;

    $anonymized = $value;
    foreach ($phoneValues as $phoneValue) {
        $anonymized = str_replace($phoneValue, '#anonymisiert demo#', $anonymized);
    }

    if (is_free_text_field($key)) {
        $anonymized = anonymize_phone_patterns($anonymized);
    }

    return $anonymized;
}

function json_out($code, $arr) {
    http_response_code($code);
    echo json_encode($arr, JSON_UNESCAPED_UNICODE);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    // Wenn du CORS brauchst, hier erlauben (optional)
    // header('Access-Control-Allow-Origin: https://DEINE-ORIGIN');
    // header('Access-Control-Allow-Headers: Content-Type, X-TP-Token');
    // header('Access-Control-Allow-Methods: POST, OPTIONS');
    http_response_code(204);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    json_out(405, array('ok' => false, 'error' => 'Nur POST erlaubt'));
}

$raw = file_get_contents('php://input');
$data = json_decode($raw, true);
if (!is_array($data)) {
    json_out(400, array('ok' => false, 'error' => 'Ungültiges JSON'));
}

// Mindestens ein Feld befüllt?
$hasAny = false;
foreach ($data as $v) {
    if (is_array($v) || is_object($v)) {
        if (!empty($v)) {
            $hasAny = true;
            break;
        }
    } else if (is_bool($v) || is_int($v) || is_float($v)) {
        $hasAny = true;
        break;
    } else if (trim((string)$v) !== '') {
        $hasAny = true;
        break;
    }
}
if (!$hasAny) {
    json_out(400, array('ok' => false, 'error' => 'Mindestens ein Feld muss befüllt sein'));
}

$typ = scalar_str($data['typ'] ?? '');
if ($typ === '') $typ = 'unknown';

$id = scalar_str($data['id'] ?? '');
$ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';

// --- Auth Entscheidung ---
$hdrToken = scalar_str($_SERVER['HTTP_X_TP_TOKEN'] ?? '');

// 1) IONOS-Pfad: Header-Token korrekt => OK (kein Rate-Limit)
$isIonosAuthorized = ($hdrToken !== '' && hash_equals($IONOS_PSK, $hdrToken));

// 2) Webformular-Pfad: id == "web-formular" => OTP + Rate-Limit nötig
$isWeb = ($id === 'web-formular');

if (!$isIonosAuthorized && !$isWeb) {
    json_out(403, array(
        'ok' => false,
        'error' => 'forbidden',
        'message' => 'Nicht autorisiert (fehlender/ungültiger PSK oder kein Webformular-Request).'
    ));
}

// --- Webformular Schutz: Rate-Limit + OTP ---
if ($isWeb) {
    // Rate limit pro IP
    $rlFile = '/tmp/telepraxis_rl_' . preg_replace('/[^0-9a-fA-F:\.]/', '_', $ip) . '.json';
    $now = time();
    $events = array();

    if (is_readable($rlFile)) {
        $rlRaw = @file_get_contents($rlFile);
        $rlDec = @json_decode($rlRaw, true);
        if (is_array($rlDec) && isset($rlDec['events']) && is_array($rlDec['events'])) {
            $events = $rlDec['events'];
        }
    }

    $cutoff = $now - $WEB_RL_WINDOW_SEC;
    $kept = array();
    foreach ($events as $ts) {
        if (is_int($ts) && $ts >= $cutoff) $kept[] = $ts;
    }
    $events = $kept;

    if (count($events) >= $WEB_RL_LIMIT) {
        json_out(429, array(
            'ok' => false,
            'error' => 'rate_limited',
            'message' => 'Empfang begrenzt auf maximal 20 Nachrichten in 10 Minuten, bitte warten und dann nochmal absenden.'
        ));
    }

    // OTP prüfen
    $otp = scalar_str($data['otp'] ?? '');
    if ($otp === '') {
        json_out(403, array('ok' => false, 'error' => 'otp_missing', 'message' => 'OTP fehlt.'));
    }

    if (!is_dir(dirname($OTP_DB))) {
        @mkdir(dirname($OTP_DB), 0770, true);
    }

    try {
        $pdo = new PDO('sqlite:' . $OTP_DB);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

        $pdo->exec('CREATE TABLE IF NOT EXISTS otps (
            token_hash TEXT PRIMARY KEY,
            expires_at INTEGER NOT NULL,
            used_at INTEGER
        )');

        $hash = hash('sha256', $otp);
        $stmt = $pdo->prepare('SELECT expires_at, used_at FROM otps WHERE token_hash = :h');
        $stmt->execute(array(':h' => $hash));
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        if (!$row) {
            json_out(403, array('ok' => false, 'error' => 'otp_invalid', 'message' => 'OTP ungültig.'));
        }
        if (!empty($row['used_at'])) {
            json_out(403, array('ok' => false, 'error' => 'otp_used', 'message' => 'OTP wurde bereits verwendet.'));
        }
        if ((int)$row['expires_at'] < time()) {
            json_out(403, array('ok' => false, 'error' => 'otp_expired', 'message' => 'OTP ist abgelaufen.'));
        }

        // OTP als benutzt markieren (atomar)
        $upd = $pdo->prepare('UPDATE otps SET used_at = :u WHERE token_hash = :h AND used_at IS NULL');
        $upd->execute(array(':u' => time(), ':h' => $hash));
        if ($upd->rowCount() !== 1) {
            json_out(403, array('ok' => false, 'error' => 'otp_race', 'message' => 'OTP konnte nicht markiert werden (Race).'));
        }

    } catch (Exception $e) {
        json_out(500, array('ok' => false, 'error' => 'otp_db_error', 'message' => $e->getMessage()));
    }

    // erst nach erfolgreicher OTP-Prüfung zählen
    $events[] = $now;
    @file_put_contents($rlFile, json_encode(array('events' => $events)), LOCK_EX);
}

// Telefonnummern erst nach der Authentifizierung und OTP-Prüfung anonymisieren,
// dann ausschließlich die bereinigten Nutzdaten in die öffentliche Inbox schreiben.
$phoneValues = array();
collect_phone_values($data, $phoneValues);
$phoneValues = array_values(array_unique($phoneValues));
usort($phoneValues, function ($a, $b) {
    return strlen($b) - strlen($a);
});
$data = anonymize_phone_data($data, $phoneValues);

// --- Inbox schreiben ---
if (!is_dir($INBOX_DIR)) {
    if (!@mkdir($INBOX_DIR, 0755, true)) {
        json_out(500, array('ok' => false, 'error' => 'Konnte Inbox nicht anlegen', 'path' => $INBOX_DIR));
    }
}

$rand = function_exists('random_int') ? random_int(100000, 999999) : mt_rand(100000, 999999);
$fname = date('Ymd_His') . '_' . $rand . '.json';
$file  = rtrim($INBOX_DIR, '/') . '/' . $fname;

$record = array(
    'received_at' => date('c'),
    'remote_ip'   => $ip,
    'user_agent'  => $_SERVER['HTTP_USER_AGENT'] ?? '',
    'typ'         => $typ,
    'payload'     => $data
);

$out = json_encode($record, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
if ($out === false) {
    json_out(500, array('ok' => false, 'error' => 'JSON-Encoding fehlgeschlagen'));
}

// Erst vollständig in eine temporäre Datei schreiben und danach atomar umbenennen.
$tmp = $file . '.tmp';
if (@file_put_contents($tmp, $out . "\n", LOCK_EX) === false || !@rename($tmp, $file)) {
    @unlink($tmp);
    json_out(500, array('ok' => false, 'error' => 'Konnte Datei nicht schreiben', 'file' => $file));
}

// Die Demo-Dateien sollen absichtlich direkt über den Webserver lesbar sein.
@chmod($file, 0644);

json_out(200, array('ok' => true, 'file' => $fname, 'typ' => $typ));
