<?php
declare(strict_types=1);

define('KZF_RUNTIME', getenv('KZF_WEB_RUNTIME') ?: '/run/kienzlefon-webinterface');
define('KZF_STATE', KZF_RUNTIME . '/state.json');
define('KZF_PASSWORD_HASH', KZF_RUNTIME . '/password.hash');
define('KZF_INBOX', KZF_RUNTIME . '/inbox');
define('KZF_STATUS', KZF_RUNTIME . '/status');
define('KZF_AUDIO', KZF_RUNTIME . '/audio');

function json_response(array $value, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function read_json_file(string $path): ?array
{
    if (!is_file($path) || !is_readable($path)) {
        return null;
    }
    $contents = file_get_contents($path);
    if ($contents === false) {
        return null;
    }
    $value = json_decode($contents, true, 64, JSON_INVALID_UTF8_SUBSTITUTE);
    return is_array($value) ? $value : null;
}

function h(mixed $value): string
{
    return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function csrf_token(): string
{
    if (!isset($_SESSION['csrf']) || !is_string($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(32));
    }
    return $_SESSION['csrf'];
}

function require_csrf(): void
{
    $provided = $_SERVER['HTTP_X_CSRF_TOKEN'] ?? $_POST['csrf'] ?? '';
    if (!is_string($provided) || !hash_equals(csrf_token(), $provided)) {
        json_response(['ok' => false, 'error' => 'Ungültige Sicherheitsprüfung.'], 403);
    }
}

function active_job_exists(): bool
{
    $jobs = glob(KZF_INBOX . '/job-*.json');
    return is_array($jobs) && count($jobs) > 0;
}

function login_throttle(int $mode): array
{
    $fallback = [
        'attempts' => (int)($_SESSION['attempts'] ?? 0),
        'blocked_until' => (int)($_SESSION['blocked_until'] ?? 0),
        'updated_at' => time(),
    ];
    $directory = KZF_RUNTIME . '/sessions';
    if (!is_dir($directory) || !is_writable($directory)) {
        if ($mode > 0) {
            $fallback['attempts']++;
            if ($fallback['attempts'] >= 5) {
                $fallback['blocked_until'] = time() + min(300, 15 * ($fallback['attempts'] - 4));
            }
        } elseif ($mode < 0) {
            $fallback['attempts'] = 0;
            $fallback['blocked_until'] = 0;
        }
        $_SESSION['attempts'] = $fallback['attempts'];
        $_SESSION['blocked_until'] = $fallback['blocked_until'];
        return $fallback;
    }
    $address = (string)($_SERVER['REMOTE_ADDR'] ?? 'unbekannt');
    $path = $directory . '/login-' . hash('sha256', $address) . '.json';
    $handle = @fopen($path, 'c+');
    if ($handle === false || !flock($handle, LOCK_EX)) {
        if (is_resource($handle)) {
            fclose($handle);
        }
        return $fallback;
    }
    @chmod($path, 0600);
    try {
        rewind($handle);
        $stored = json_decode(stream_get_contents($handle) ?: '{}', true);
        $value = is_array($stored) ? $stored : [];
        $attempts = (int)($value['attempts'] ?? 0);
        $blockedUntil = (int)($value['blocked_until'] ?? 0);
        $updatedAt = (int)($value['updated_at'] ?? 0);
        if ($updatedAt < time() - 900) {
            $attempts = 0;
            $blockedUntil = 0;
        }
        if ($mode > 0) {
            $attempts++;
            if ($attempts >= 5) {
                $blockedUntil = time() + min(300, 15 * ($attempts - 4));
            }
        } elseif ($mode < 0) {
            $attempts = 0;
            $blockedUntil = 0;
        }
        $result = ['attempts' => $attempts, 'blocked_until' => $blockedUntil, 'updated_at' => time()];
        ftruncate($handle, 0);
        rewind($handle);
        fwrite($handle, json_encode($result, JSON_UNESCAPED_SLASHES) . "\n");
        fflush($handle);
        return $result;
    } finally {
        flock($handle, LOCK_UN);
        fclose($handle);
    }
}

function queue_job(array $payload): string
{
    if (!is_dir(KZF_INBOX) || !is_writable(KZF_INBOX)) {
        throw new RuntimeException('Der sichere Auftragsordner ist nicht verfügbar.');
    }
    if (active_job_exists()) {
        throw new RuntimeException('Ein anderer Vorgang läuft bereits.');
    }
    $allowed = [
        'save',
        'record',
        'activate_candidate',
        'save_override_preset',
        'record_override_preset',
        'delete_override_preset',
    ];
    if (!isset($payload['action']) || !in_array($payload['action'], $allowed, true)) {
        throw new RuntimeException('Diese Aktion ist nicht freigegeben.');
    }
    $jobId = bin2hex(random_bytes(16));
    $payload['id'] = $jobId;
    $temporary = KZF_INBOX . '/.' . $jobId . '.tmp';
    $target = KZF_INBOX . '/job-' . $jobId . '.json';
    $encoded = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($encoded === false || strlen($encoded) > 262144) {
        throw new RuntimeException('Der Auftrag ist zu groß oder ungültig.');
    }
    $handle = @fopen($temporary, 'x+b');
    if ($handle === false) {
        throw new RuntimeException('Der Auftrag konnte nicht sicher angelegt werden.');
    }
    try {
        if (fwrite($handle, $encoded . "\n") === false) {
            throw new RuntimeException('Der Auftrag konnte nicht geschrieben werden.');
        }
        fflush($handle);
        if (function_exists('fsync')) {
            fsync($handle);
        }
    } finally {
        fclose($handle);
    }
    chmod($temporary, 0640);
    if (!rename($temporary, $target)) {
        @unlink($temporary);
        throw new RuntimeException('Der Auftrag konnte nicht freigegeben werden.');
    }
    return $jobId;
}

$secureCookie = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off');
if (is_dir(KZF_RUNTIME . '/sessions')) {
    session_save_path(KZF_RUNTIME . '/sessions');
}
session_name('KZFADMIN');
session_set_cookie_params([
    'lifetime' => 0,
    'path' => '/',
    'secure' => $secureCookie,
    'httponly' => true,
    'samesite' => 'Strict',
]);
ini_set('session.use_strict_mode', '1');
ini_set('session.use_only_cookies', '1');
session_start();

$nonce = base64_encode(random_bytes(18));
header("Content-Security-Policy: default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'nonce-{$nonce}'; script-src 'nonce-{$nonce}'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'");
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
header('X-Frame-Options: DENY');
header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
header('Cache-Control: no-store');
if ($secureCookie) {
    header('Strict-Transport-Security: max-age=31536000');
}

$state = read_json_file(KZF_STATE);
$stateAvailable = is_array($state);
$authRequired = $stateAvailable ? (bool)($state['auth_required'] ?? true) : true;
$authReady = $stateAvailable && (bool)($state['auth_ready'] ?? false);
$currentPasswordHash = ($authRequired && is_readable(KZF_PASSWORD_HASH))
    ? trim((string)file_get_contents(KZF_PASSWORD_HASH))
    : '';
$currentAuthTag = $currentPasswordHash !== '' ? hash('sha256', $currentPasswordHash) : '';
$expectedAddress = $stateAvailable ? (string)($state['network']['listen'] ?? '') : '';
$serverMode = $stateAvailable ? (string)($state['network']['server'] ?? '') : '';
$localAddress = (string)($_SERVER['SERVER_ADDR'] ?? '');
if ($serverMode === 'standalone' && $localAddress === '') {
    // Der eingebaute PHP-Server setzt SERVER_ADDR nicht. Da der Installer ihn
    // an eine numerische Adresse bindet, enthaelt SERVER_NAME hier die feste
    // Listener-Adresse und nicht den vom Client gelieferten Host-Header.
    $localAddress = (string)($_SERVER['SERVER_NAME'] ?? '');
}
if (!$authRequired && ($expectedAddress === '' || !hash_equals($expectedAddress, $localAddress))) {
    http_response_code(403);
    exit('Passwortloser Zugriff ist ausschließlich über die konfigurierte WireGuard-Adresse erlaubt.');
}
$authenticated = !$authRequired || (
    !empty($_SESSION['authenticated'])
    && $currentAuthTag !== ''
    && isset($_SESSION['auth_tag'])
    && is_string($_SESSION['auth_tag'])
    && hash_equals($currentAuthTag, $_SESSION['auth_tag'])
);
$loginError = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['login'])) {
    $now = time();
    $throttle = login_throttle(0);
    $blockedUntil = (int)$throttle['blocked_until'];
    if ($blockedUntil > $now) {
        $loginError = 'Bitte warten Sie kurz, bevor Sie es erneut versuchen.';
    } elseif (!$authReady || !is_readable(KZF_PASSWORD_HASH)) {
        $loginError = 'Der Passwortschutz ist noch nicht vollständig eingerichtet.';
    } else {
        $password = isset($_POST['password']) && is_string($_POST['password']) ? $_POST['password'] : '';
        if ($currentPasswordHash !== '' && password_verify($password, $currentPasswordHash)) {
            session_regenerate_id(true);
            $_SESSION['authenticated'] = true;
            $_SESSION['auth_tag'] = $currentAuthTag;
            login_throttle(-1);
            header('Location: ' . strtok($_SERVER['REQUEST_URI'] ?? '/', '?'));
            exit;
        }
        login_throttle(1);
        usleep(250000);
        $loginError = 'Das Kennwort ist nicht korrekt.';
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['logout'])) {
    if (!hash_equals(csrf_token(), (string)($_POST['csrf'] ?? ''))) {
        http_response_code(403);
        exit('Ungültige Sicherheitsprüfung.');
    }
    $_SESSION = [];
    session_destroy();
    header('Location: ' . strtok($_SERVER['REQUEST_URI'] ?? '/', '?'));
    exit;
}

if (isset($_GET['api'])) {
    if (!$authenticated) {
        json_response(['ok' => false, 'error' => 'Anmeldung erforderlich.'], 401);
    }
    if ($_GET['api'] === 'audio') {
        if ($_SERVER['REQUEST_METHOD'] !== 'GET' || !$stateAvailable) {
            http_response_code(404);
            exit;
        }
        $kind = isset($_GET['kind']) && is_string($_GET['kind']) ? $_GET['kind'] : '';
        $name = isset($_GET['name']) && is_string($_GET['name']) ? $_GET['name'] : '';
        $filename = '';
        if (in_array($kind, ['active', 'candidate'], true) && preg_match('/^[a-z][a-z0-9_]{0,63}$/', $name)) {
            foreach (($state['sources'] ?? []) as $source) {
                if (($source['name'] ?? '') !== $name) {
                    continue;
                }
                $flag = $kind === 'active' ? 'active_preview' : 'candidate_preview';
                if (!empty($source[$flag])) {
                    $filename = $kind . '-' . $name . '.wav';
                }
                break;
            }
        } elseif (in_array($kind, ['preset_tts', 'preset_manual'], true) && preg_match('/^[a-f0-9]{32}$/', $name)) {
            foreach (($state['override_presets'] ?? []) as $preset) {
                if (($preset['id'] ?? '') !== $name) {
                    continue;
                }
                $flag = $kind === 'preset_tts' ? 'tts_preview' : 'manual_preview';
                if (!empty($preset[$flag])) {
                    $prefix = $kind === 'preset_tts' ? 'preset-tts-' : 'preset-manual-';
                    $filename = $prefix . $name . '.wav';
                }
                break;
            }
        }
        $path = $filename !== '' ? KZF_AUDIO . '/' . $filename : '';
        if ($path === '' || !is_file($path) || is_link($path) || !is_readable($path)) {
            http_response_code(404);
            exit;
        }
        $size = filesize($path);
        session_write_close();
        header('Content-Type: audio/wav');
        header('Content-Disposition: inline');
        header('Cache-Control: private, no-store');
        if (is_int($size)) {
            header('Content-Length: ' . $size);
        }
        readfile($path);
        exit;
    }
    if ($_GET['api'] === 'state') {
        if (!$stateAvailable) {
            json_response(['ok' => false, 'error' => 'Statusdatei ist nicht verfügbar.'], 503);
        }
        json_response(['ok' => true, 'state' => $state]);
    }
    if ($_GET['api'] === 'status') {
        $jobId = isset($_GET['job']) && is_string($_GET['job']) ? $_GET['job'] : '';
        if (!preg_match('/^[a-f0-9]{32}$/', $jobId)) {
            json_response(['ok' => false, 'error' => 'Ungültige Auftragsnummer.'], 400);
        }
        $status = read_json_file(KZF_STATUS . '/' . $jobId . '.json');
        json_response(['ok' => true, 'status' => $status]);
    }
    if ($_GET['api'] === 'job' && $_SERVER['REQUEST_METHOD'] === 'POST') {
        require_csrf();
        $body = file_get_contents('php://input');
        if ($body === false || strlen($body) > 262144) {
            json_response(['ok' => false, 'error' => 'Ungültiger Auftrag.'], 400);
        }
        $payload = json_decode($body, true, 32, JSON_INVALID_UTF8_SUBSTITUTE);
        if (!is_array($payload)) {
            json_response(['ok' => false, 'error' => 'Ungültiges JSON.'], 400);
        }
        try {
            $jobId = queue_job($payload);
            json_response(['ok' => true, 'job_id' => $jobId], 202);
        } catch (Throwable $error) {
            json_response(['ok' => false, 'error' => $error->getMessage()], 409);
        }
    }
    json_response(['ok' => false, 'error' => 'Unbekannte Schnittstelle.'], 404);
}

$csrf = csrf_token();
$days = [
    'montag' => 'Montag',
    'dienstag' => 'Dienstag',
    'mittwoch' => 'Mittwoch',
    'donnerstag' => 'Donnerstag',
    'freitag' => 'Freitag',
    'samstag' => 'Samstag',
    'sonntag' => 'Sonntag',
];
$scheduleLabels = [
    'oeffnungszeiten' => 'Öffnungszeiten',
    'telefonzeiten' => 'Telefonzeiten',
    'fachstellenzeiten' => 'Fachdienstzeiten',
];
$groupLabels = [
    'hauptansagen' => 'Hauptansagen',
    'zeiten_und_menue' => 'Zeiten und Menüführung',
    'datenerfassung' => 'Datenerfassung',
    'abschluss_und_fehler' => 'Abschluss und Fehlerfälle',
    'interne_verwaltung' => 'Interne Verwaltung',
    'weitere_ansagen' => 'Weitere Ansagen',
];
$positionLabels = [
    'statt_begruessung' => 'Anstelle der Begrüßungsansage',
    'vor_begruessung' => 'Vor der Begrüßungsansage',
    'nach_begruessung' => 'Nach der Begrüßungsansage',
];
$qwenVoiceLabels = [
    'ryan' => 'Ryan',
    'vivian' => 'Vivian',
    'serena' => 'Serena',
    'aiden' => 'Aiden',
    'eric' => 'Eric',
    'dylan' => 'Dylan',
    'uncle_fu' => 'Uncle Fu',
    'ono_anna' => 'Ono Anna',
    'sohee' => 'Sohee',
];
$practiceTimezone = new DateTimeZone('Europe/Berlin');
if ($stateAvailable) {
    try {
        $practiceTimezone = new DateTimeZone((string)($state['timezone'] ?? 'Europe/Berlin'));
    } catch (Throwable) {
        $practiceTimezone = new DateTimeZone('Europe/Berlin');
    }
}
$practiceNow = new DateTimeImmutable('now', $practiceTimezone);
$parseLocalDate = static function (mixed $value) use ($practiceTimezone): ?DateTimeImmutable {
    if (!is_string($value) || trim($value) === '') {
        return null;
    }
    try {
        return new DateTimeImmutable($value, $practiceTimezone);
    } catch (Throwable) {
        return null;
    }
};
$presetRuntimeStatus = [];
$effectivePresetId = '';
$effectivePriority = -1;
foreach (($state['override_presets'] ?? []) as $preset) {
    $identifier = (string)($preset['id'] ?? '');
    $validFrom = $parseLocalDate($preset['valid_from'] ?? '');
    $expiresAt = $parseLocalDate($preset['expires_at'] ?? '');
    $past = $expiresAt !== null && $practiceNow >= $expiresAt;
    $future = $validFrom !== null && $practiceNow < $validFrom;
    $validNow = !empty($preset['active']) && !$past && !$future;
    $priority = (int)($preset['priority'] ?? 0);
    if ($validNow && ($effectivePresetId === '' || $priority > $effectivePriority)) {
        $effectivePresetId = $identifier;
        $effectivePriority = $priority;
    }
    $presetRuntimeStatus[$identifier] = ['past' => $past, 'future' => $future];
}
$legacyExpiresAt = $parseLocalDate($state['override']['expires_at'] ?? '');
$legacyPast = $legacyExpiresAt !== null && $practiceNow >= $legacyExpiresAt;
$legacyValid = !empty($state['override']['active']) && !$legacyPast;
$legacyEffective = $effectivePresetId === '' && $legacyValid;
$currentOverrideName = '';
if ($effectivePresetId !== '') {
    foreach (($state['override_presets'] ?? []) as $preset) {
        if (($preset['id'] ?? '') === $effectivePresetId) {
            $currentOverrideName = (string)($preset['name'] ?? 'Sonderansage');
            break;
        }
    }
} elseif ($legacyEffective) {
    $currentOverrideName = 'Bisherige Sonderansage';
}
?>
<!doctype html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,nofollow">
    <title>Kienzlefon Administration</title>
    <style nonce="<?= h($nonce) ?>">
        :root { color-scheme: light; --ink:#17212b; --muted:#647180; --line:#dce2e7; --paper:#fff; --soft:#f4f6f7; --nav:#12263a; --accent:#007b72; --accent-dark:#005e57; --warn:#a24a00; --danger:#a32626; --ok:#26734d; --radius:14px; }
        * { box-sizing:border-box; }
        body { margin:0; background:var(--soft); color:var(--ink); font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
        button,input,textarea,select { font:inherit; }
        button { cursor:pointer; }
        .shell { min-height:100vh; display:grid; grid-template-columns:245px minmax(0,1fr); }
        aside { background:var(--nav); color:#fff; padding:26px 18px; position:sticky; top:0; height:100vh; }
        .brand { display:flex; gap:12px; align-items:center; margin:0 8px 30px; }
        .brand-mark { width:38px; height:38px; border-radius:11px; display:grid; place-items:center; background:#e6fbf7; color:var(--accent-dark); font-weight:800; }
        .brand strong { display:block; font-size:17px; }
        .brand span { color:#aebcca; font-size:12px; }
        nav { display:grid; gap:7px; }
        nav button { border:0; border-radius:10px; padding:11px 12px; background:transparent; color:#dbe5ec; text-align:left; }
        nav button:hover,nav button.active { background:#203b52; color:#fff; }
        .aside-foot { position:absolute; left:18px; right:18px; bottom:22px; color:#aebcca; font-size:12px; }
        main { padding:34px clamp(20px,4vw,58px) 60px; max-width:1500px; width:100%; }
        .topline { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; margin-bottom:28px; }
        h1 { margin:0; font-size:clamp(25px,3vw,34px); letter-spacing:-.03em; }
        h2 { margin:0 0 15px; font-size:20px; }
        h3 { margin:0 0 9px; font-size:16px; }
        p { margin:0 0 12px; }
        .muted { color:var(--muted); }
        .page { display:none; }
        .page.active { display:block; }
        .grid { display:grid; gap:18px; }
        .grid.two { grid-template-columns:repeat(2,minmax(0,1fr)); }
        .card { background:var(--paper); border:1px solid var(--line); border-radius:var(--radius); padding:20px; box-shadow:0 4px 20px rgba(18,38,58,.04); }
        .status { display:flex; gap:12px; align-items:center; }
        .status-dot { width:11px; height:11px; border-radius:50%; background:var(--ok); box-shadow:0 0 0 5px #e3f3ea; flex:0 0 auto; }
        .status-dot.busy { background:var(--warn); box-shadow:0 0 0 5px #fff0df; }
        .status-dot.error { background:var(--danger); box-shadow:0 0 0 5px #fde7e7; }
        .metric { font-size:28px; font-weight:750; letter-spacing:-.03em; }
        .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:space-between; margin:0 0 16px; }
        .button { border:1px solid transparent; border-radius:9px; padding:9px 14px; background:var(--accent); color:#fff; font-weight:650; }
        .button:hover { background:var(--accent-dark); }
        .button.secondary { background:#fff; color:var(--ink); border-color:var(--line); }
        .button.danger { background:#fff; color:var(--danger); border-color:#eccaca; }
        .button.small { padding:6px 9px; font-size:13px; }
        .field { display:grid; gap:7px; margin-bottom:16px; }
        label { font-weight:650; }
        input[type=text],input[type=password],input[type=number],input[type=datetime-local],textarea,select { width:100%; border:1px solid #cbd4db; border-radius:9px; padding:10px 11px; background:#fff; color:var(--ink); }
        textarea { resize:vertical; min-height:96px; }
        input:focus,textarea:focus,select:focus,button:focus-visible { outline:3px solid rgba(0,123,114,.22); outline-offset:1px; border-color:var(--accent); }
        .field-row { display:grid; grid-template-columns:120px minmax(0,1fr) auto; gap:12px; align-items:center; padding:9px 0; border-bottom:1px solid #edf0f2; }
        .field-row:last-child { border-bottom:0; }
        .hint { color:var(--muted); font-size:13px; }
        details { border:1px solid var(--line); border-radius:12px; background:#fff; margin:12px 0; }
        details summary { padding:15px 18px; font-weight:700; cursor:pointer; }
        details .details-body { padding:0 18px 18px; }
        .recording-bar { display:grid; grid-template-columns:minmax(220px,1fr) minmax(180px,260px); gap:18px; align-items:end; margin-bottom:18px; }
        .announcement-card { border-top:1px solid #edf0f2; padding:20px 0; }
        .announcement-card:first-of-type { border-top:0; }
        .announcement-head { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:13px; }
        .announcement-head h4 { margin:0 0 4px; font-size:16px; }
        .announcement-status { display:flex; flex-wrap:wrap; gap:7px; justify-content:flex-end; }
        .announcement-fields { display:grid; gap:12px; }
        .tts-preview { background:#f7f9fa; border:1px solid var(--line); border-radius:9px; padding:11px 12px; color:#43515e; }
        .announcement-controls { display:flex; flex-wrap:wrap; gap:9px; align-items:end; margin-top:14px; }
        .announcement-controls .source-control { min-width:190px; flex:1 1 190px; }
        .announcement-controls .button { margin-bottom:1px; }
        .audio-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:10px; margin-top:14px; }
        .audio-item { display:grid; gap:6px; min-width:0; }
        .audio-item audio { width:100%; height:38px; }
        .preset-grid { display:grid; gap:14px; margin-top:16px; }
        .preset-card { border:1px solid var(--line); border-left-width:5px; border-radius:11px; padding:16px; }
        .preset-card.status-active { border-left-color:var(--ok); background:#fbfffc; }
        .preset-card.status-inactive,.preset-card.status-past { border-left-color:#87939e; background:#f7f8f9; }
        .preset-head { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; }
        .preset-head h4 { margin:0 0 3px; }
        .preset-text { white-space:pre-wrap; background:#f7f9fa; border-radius:8px; padding:9px 11px; margin-top:11px; }
        .planning-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 16px; margin-top:16px; }
        .badge { display:inline-flex; align-items:center; border-radius:999px; padding:3px 8px; font-size:12px; font-weight:650; background:#e6f4f2; color:var(--accent-dark); }
        .badge.muted-badge { background:#edf0f2; color:#596672; }
        .badge.status-active { background:#dff2e7; color:#1f6845; }
        .badge.status-inactive,.badge.status-past { background:#e5e9ec; color:#4c5964; }
        .checkbox { display:flex; gap:9px; align-items:center; font-weight:500; }
        .checkbox input { width:18px; height:18px; accent-color:var(--accent); }
        .flash { position:fixed; right:22px; bottom:22px; width:min(420px,calc(100vw - 44px)); padding:15px 17px; background:var(--nav); color:#fff; border-radius:12px; box-shadow:0 16px 50px rgba(0,0,0,.25); display:none; z-index:20; }
        .flash.show { display:block; }
        .flash.error { background:#741d1d; }
        .login { min-height:100vh; display:grid; place-items:center; padding:20px; }
        .login-card { width:min(430px,100%); background:#fff; border:1px solid var(--line); border-radius:18px; padding:28px; box-shadow:0 18px 60px rgba(18,38,58,.13); }
        .login-card .brand { color:var(--ink); margin:0 0 24px; }
        .error-box { background:#fff0f0; color:#781f1f; border:1px solid #eccaca; border-radius:9px; padding:10px 12px; margin-bottom:15px; }
        .empty { padding:28px; text-align:center; color:var(--muted); }
        .mt18 { margin-top:18px; }
        .mb18 { margin-bottom:18px; }
        @media (max-width:900px) { .shell{grid-template-columns:1fr}.grid.two,.recording-bar,.planning-grid{grid-template-columns:1fr}aside{position:static;height:auto;padding:14px}.brand{margin:0 4px 12px}nav{grid-template-columns:repeat(4,1fr)}nav button{text-align:center;padding:9px 5px;font-size:13px}.aside-foot{display:none}main{padding:24px 16px 50px}.field-row{grid-template-columns:1fr}.topline{display:block}.topline form{margin-top:12px}.announcement-head,.preset-head{display:block}.announcement-status{justify-content:flex-start;margin-top:8px} }
    </style>
</head>
<body>
<?php if (!$authenticated): ?>
<div class="login">
    <form class="login-card" method="post" autocomplete="on">
        <div class="brand"><div class="brand-mark">K</div><div><strong>Kienzlefon</strong><span>Administration</span></div></div>
        <h1>Anmelden</h1>
        <p class="muted">Geben Sie das in der Kienzlefon-Konfiguration hinterlegte Administratorkennwort ein.</p>
        <?php if (!$stateAvailable): ?><div class="error-box">Die Verwaltungsdienste sind noch nicht verfügbar.</div><?php endif; ?>
        <?php if ($loginError !== ''): ?><div class="error-box"><?= h($loginError) ?></div><?php endif; ?>
        <div class="field"><label for="password">Kennwort</label><input id="password" type="password" name="password" required autofocus autocomplete="current-password"></div>
        <button class="button" type="submit" name="login" value="1">Anmelden</button>
    </form>
</div>
<?php elseif (!$stateAvailable): ?>
<div class="login"><div class="login-card"><h1>Nicht verfügbar</h1><p>Der sichere Verwaltungsstatus konnte nicht gelesen werden. Bitte prüfen Sie den Webinterface-Dienst.</p></div></div>
<?php else: ?>
<div class="shell">
    <aside>
        <div class="brand"><div class="brand-mark">K</div><div><strong>Kienzlefon</strong><span><?= h($state['practice'] ?? 'Administration') ?></span></div></div>
        <nav aria-label="Hauptnavigation">
            <button type="button" data-page="overview" class="active">Übersicht</button>
            <button type="button" data-page="times">Zeiten</button>
            <button type="button" data-page="prompts">Ansagen</button>
            <button type="button" data-page="override">Sonderansage</button>
        </nav>
        <div class="aside-foot">Konfiguration nur für Zeiten und Ansagen</div>
    </aside>
    <main>
        <div class="topline">
            <div><h1>Kienzlefon Administration</h1><p class="muted">Änderungen gelten ab dem nächsten neu eingehenden Anruf.</p></div>
            <?php if ($authRequired): ?><form method="post"><input type="hidden" name="csrf" value="<?= h($csrf) ?>"><button class="button secondary" type="submit" name="logout" value="1">Abmelden</button></form><?php endif; ?>
        </div>

        <section id="page-overview" class="page active" aria-labelledby="overview-title">
            <h2 id="overview-title">Übersicht</h2>
            <div class="grid two">
                <div class="card"><div class="status"><span class="status-dot"></span><div><strong>Ansagen bereit</strong><div class="muted">Automatische Erzeugung: <?= ($state['tts']['engine'] ?? 'piper') === 'qwen' ? 'Qwen3-TTS · ' . h($qwenVoiceLabels[$state['tts']['qwen_voice'] ?? ''] ?? ($state['tts']['qwen_voice'] ?? '')) : 'Piper' ?></div></div></div></div>
                <div class="card"><div class="muted">Erreichbarkeit</div><div class="metric"><?= h(($state['network']['listen'] ?? '') . ':' . ($state['network']['port'] ?? '')) ?></div><span class="badge"><?= !empty($state['auth_required']) ? 'Kennwortschutz' : 'WireGuard, passwortlos' ?></span></div>
                <div class="card"><div class="muted">Konfigurierbare Ansagetexte</div><div class="metric"><?= count($state['prompts'] ?? []) ?></div></div>
                <div class="card"><div class="muted">Aufnahmefähige Nebenstellen</div><div class="metric"><?= count($state['extensions'] ?? []) ?></div></div>
            </div>
            <div class="card mt18"><h3>Temporäre Sonderansage</h3><p><?= $currentOverrideName !== '' ? 'Derzeit wird „' . h($currentOverrideName) . '“ verwendet.' : 'Derzeit ist keine Sonderansage gültig.' ?></p><button class="button secondary" type="button" data-go="override">Sonderansagen öffnen</button></div>
        </section>

        <section id="page-times" class="page" aria-labelledby="times-title">
            <div class="toolbar"><div><h2 id="times-title">Zeiten</h2><p class="muted">Mehrere Zeiträume durch Komma trennen, zum Beispiel 08:00-12:00, 14:00-17:00.</p></div><button class="button" type="button" id="save-times">Zeiten speichern</button></div>
            <?php foreach ($scheduleLabels as $section => $label): ?>
            <div class="card mb18"><h3><?= h($label) ?></h3>
                <?php foreach ($days as $day => $dayLabel): $ranges = $state['schedules'][$section][$day] ?? []; $defaults = $state['schedule_defaults'][$section][$day] ?? []; ?>
                <div class="field-row"><label for="<?= h($section . '-' . $day) ?>"><?= h($dayLabel) ?></label><input type="text" id="<?= h($section . '-' . $day) ?>" data-schedule="<?= h($section) ?>" data-day="<?= h($day) ?>" data-default="<?= h(implode(', ', $defaults)) ?>" value="<?= h(implode(', ', $ranges)) ?>" placeholder="geschlossen"><button class="button secondary small reset-input" type="button">Auf Standard</button></div>
                <?php endforeach; ?>
            </div>
            <?php endforeach; ?>
        </section>

        <section id="page-prompts" class="page" aria-labelledby="prompts-title">
            <div class="toolbar"><div><h2 id="prompts-title">Ansagen</h2><p class="muted">Texte und aktive Audioquelle werden gemeinsam gespeichert.</p></div><button class="button" type="button" id="save-prompts">Ansagen speichern</button></div>
            <div class="card mb18">
                <h3>Automatische Spracherzeugung</h3>
                <p class="muted">Erzeugungsmodell und Sprecher gelten global für sämtliche automatisch erzeugten TTS-Ansagen.</p>
                <div class="planning-grid">
                    <div class="field">
                        <label for="tts-engine">Erzeugungsmodell</label>
                        <select id="tts-engine" data-default="<?= h($state['tts']['defaults']['engine'] ?? 'piper') ?>">
                            <option value="piper" <?= ($state['tts']['engine'] ?? 'piper') === 'piper' ? 'selected' : '' ?>>Piper</option>
                            <option value="qwen" <?= ($state['tts']['engine'] ?? '') === 'qwen' ? 'selected' : '' ?> <?= empty($state['tts']['qwen_available']) && ($state['tts']['engine'] ?? '') !== 'qwen' ? 'disabled' : '' ?>>Qwen3-TTS 0.6B CustomVoice<?= empty($state['tts']['qwen_available']) ? ' – nicht verfügbar' : '' ?></option>
                        </select>
                        <button class="button secondary small reset-select" type="button">Auf Standard</button>
                    </div>
                    <div class="field">
                        <label for="qwen-voice">Qwen-Sprecher</label>
                        <select id="qwen-voice" data-default="<?= h($state['tts']['defaults']['qwen_voice'] ?? 'ryan') ?>">
                            <?php foreach (($state['tts']['qwen_voices'] ?? array_keys($qwenVoiceLabels)) as $voice): ?><option value="<?= h($voice) ?>" <?= ($state['tts']['qwen_voice'] ?? 'ryan') === $voice ? 'selected' : '' ?>><?= h($qwenVoiceLabels[$voice] ?? $voice) ?> (<?= h($voice) ?>)</option><?php endforeach; ?>
                        </select>
                        <button class="button secondary small reset-select" type="button">Auf Standard</button>
                    </div>
                </div>
                <p class="hint">Ein Wechsel von Modell oder Sprecher erzeugt beim Speichern alle TTS-Ansagen neu. Manuelle Aufnahmen bleiben erhalten und werden nicht gelöscht.</p>
                <?php if (empty($state['tts']['qwen_available'])): ?><div class="error-box">Qwen3-TTS kann erst gewählt werden, nachdem der geprüfte Offline-Installer vollständig eingerichtet wurde.</div><?php endif; ?>
            </div>
            <div class="card recording-bar">
                <div><h3>Aufnahmen über eine Nebenstelle</h3><p class="hint">Die hier gewählte Nebenstelle gilt für den Aufnahmeknopf direkt bei jeder Ansage.</p></div>
                <div class="field"><label for="record-extension">Aufnahme-Nebenstelle</label><select id="record-extension" <?= empty($state['extensions']) ? 'disabled' : '' ?>><?php foreach (($state['extensions'] ?? []) as $extension): ?><option value="<?= h($extension) ?>"><?= h($extension) ?></option><?php endforeach; ?></select></div>
            </div>
            <?php foreach ($groupLabels as $group => $groupLabel):
                $items = array_values(array_filter(
                    $state['sources'] ?? [],
                    fn($item) => ($item['name'] ?? '') !== 'override' && ($item['group'] ?? '') === $group
                ));
                if (!$items) continue;
                $primaryGroup = $group === 'hauptansagen';
            ?>
            <?php if ($primaryGroup): ?><div class="card mb18"><h3>Häufig verwendete Hauptansagen</h3><?php else: ?><details><summary><?= h($groupLabel) ?> · <?= count($items) ?></summary><div class="details-body"><?php endif; ?>
                <?php foreach ($items as $source): $fields = $source['fields'] ?? []; ?>
                <article class="announcement-card" data-announcement="<?= h($source['name']) ?>">
                    <div class="announcement-head">
                        <div><h4><?= h($source['label']) ?></h4><div class="hint"><?= !empty($source['candidate_available']) ? 'Neue Aufnahme wartet auf Aktivierung' : (!empty($source['manual_available']) ? 'Manuelle Aufnahme vorhanden' : 'Noch keine manuelle Aufnahme') ?></div></div>
                        <div class="announcement-status"><span class="badge"><?= ($source['source'] ?? '') === 'manuell' ? 'Manuell aktiv' : 'TTS aktiv' ?></span><?php if (!empty($source['candidate_available'])): ?><span class="badge muted-badge">Kandidat vorhanden</span><?php endif; ?></div>
                    </div>
                    <div class="announcement-fields">
                        <?php if (count($fields) > 1): ?><div><label>Aktuell erzeugter TTS-Sprechtext</label><div class="tts-preview"><?= h($source['tts_text'] ?? '') ?></div></div><?php endif; ?>
                        <?php foreach ($fields as $field): ?><div class="field"><div class="prompt-head"><label for="prompt-<?= h($field['name']) ?>"><?= count($fields) === 1 ? 'TTS-Text' : h($field['label']) ?></label><button class="button secondary small reset-prompt" type="button">Auf Standard</button></div><textarea id="prompt-<?= h($field['name']) ?>" data-prompt="<?= h($field['name']) ?>" data-default="<?= h($field['default']) ?>"><?= h($field['value']) ?></textarea></div><?php endforeach; ?>
                    </div>
                    <?php if (!empty($source['active_preview']) || !empty($source['candidate_preview'])): ?><div class="audio-grid">
                        <?php if (!empty($source['active_preview'])): ?><div class="audio-item"><label>Derzeit verwendete Ansage anhören</label><audio controls preload="none" src="?api=audio&amp;kind=active&amp;name=<?= h($source['name']) ?>"></audio></div><?php endif; ?>
                        <?php if (!empty($source['candidate_preview'])): ?><div class="audio-item"><label>Neue Aufnahme anhören</label><audio controls preload="none" src="?api=audio&amp;kind=candidate&amp;name=<?= h($source['name']) ?>"></audio></div><?php endif; ?>
                    </div><?php endif; ?>
                    <div class="announcement-controls">
                        <div class="source-control"><label for="source-<?= h($source['name']) ?>">Aktive Audioquelle</label><select id="source-<?= h($source['name']) ?>" data-source="<?= h($source['name']) ?>"><option value="tts" <?= ($source['source'] ?? '') === 'tts' ? 'selected' : '' ?>>Automatisch (TTS)</option><option value="manuell" <?= ($source['source'] ?? '') === 'manuell' ? 'selected' : '' ?> <?= empty($source['manual_available']) ? 'disabled' : '' ?>>Manuelle Aufnahme</option></select></div>
                        <button class="button secondary use-tts" data-prompt="<?= h($source['name']) ?>" type="button">Auf TTS umschalten</button>
                        <button class="button record-announcement" data-prompt="<?= h($source['name']) ?>" data-extension-select="record-extension" type="button" <?= empty($state['extensions']) ? 'disabled' : '' ?>>Genau diese Ansage aufnehmen</button>
                        <?php if (!empty($source['candidate_available'])): ?><button class="button activate-candidate" data-prompt="<?= h($source['name']) ?>" type="button">Neue Aufnahme aktivieren</button><?php endif; ?>
                    </div>
                </article>
                <?php endforeach; ?>
            <?php if ($primaryGroup): ?></div><?php else: ?></div></details><?php endif; ?>
            <?php endforeach; ?>
        </section>

        <section id="page-override" class="page" aria-labelledby="override-title">
            <div class="toolbar"><div><h2 id="override-title">Sonderansagen planen</h2><p class="muted">Von allen aktiven und gerade gültigen Ansagen wird ausschließlich die mit der höchsten Priorität abgespielt.</p></div></div>
            <?php
                $legacyActive = !empty($state['override']['active']) && !$legacyPast;
                $legacyStatusClass = $legacyPast ? 'status-past' : ($legacyActive ? 'status-active' : 'status-inactive');
                $legacyStatusText = $legacyPast ? 'Vergangenheit' : ($legacyActive ? ($legacyEffective ? 'Aktiv – wird aktuell angesagt' : 'Aktiv') : 'Inaktiv');
            ?>
            <div class="card">
                <div class="toolbar"><div><h3>Bisherige einzelne Sonderansage</h3><p class="hint">Dieser Bereich bleibt als kompatibler Fallback erhalten. Für mehrstufige Planung verwenden Sie die gespeicherten Sonderansagen darunter.</p></div><div class="announcement-status"><span class="badge <?= h($legacyStatusClass) ?>"><?= h($legacyStatusText) ?></span><button class="button" type="button" id="save-override">Einzelansage speichern</button></div></div>
                <div class="field"><label class="checkbox"><input id="override-active" type="checkbox" data-default="<?= !empty($state['override']['defaults']['active']) ? '1' : '0' ?>" <?= !empty($state['override']['active']) ? 'checked' : '' ?>>Sonderansage aktiv</label><button class="button secondary small reset-check" type="button">Auf Standard</button></div>
                <div class="field"><label for="override-text">TTS-Text der Sonderansage</label><textarea id="override-text" data-default="<?= h($state['override']['defaults']['announcement'] ?? '') ?>"><?= h($state['override']['announcement'] ?? '') ?></textarea><button class="button secondary small reset-textarea" type="button">Auf Standard</button></div>
                <div class="field"><label for="override-expiry">Optionales Ablaufdatum mit Uhrzeit</label><input id="override-expiry" type="datetime-local" data-default="<?= h($state['override']['defaults']['expires_at'] ?? '') ?>" value="<?= h($state['override']['expires_at'] ?? '') ?>"><button class="button secondary small reset-input" type="button">Auf Standard</button></div>
                <div class="field"><label for="override-position">Position im Anrufablauf</label><select id="override-position" data-default="<?= h($state['override']['defaults']['position'] ?? 'statt_begruessung') ?>"><option value="statt_begruessung" <?= ($state['override']['position'] ?? '') === 'statt_begruessung' ? 'selected' : '' ?>>Anstelle der Begrüßungsansage</option><option value="vor_begruessung" <?= ($state['override']['position'] ?? '') === 'vor_begruessung' ? 'selected' : '' ?>>Vor der Begrüßungsansage</option><option value="nach_begruessung" <?= ($state['override']['position'] ?? '') === 'nach_begruessung' ? 'selected' : '' ?>>Nach der Begrüßungsansage</option></select><button class="button secondary small reset-select" type="button">Auf Standard</button></div>
                <div class="field"><label class="checkbox"><input id="override-block" type="checkbox" data-default="<?= !empty($state['override']['defaults']['block_phone_hours']) ? '1' : '0' ?>" <?= !empty($state['override']['block_phone_hours']) ? 'checked' : '' ?>>Normale Telefonzeiten sperren</label><button class="button secondary small reset-check" type="button">Auf Standard</button></div>
                <?php if (!empty($state['override']['active_preview']) || !empty($state['override']['candidate_preview'])): ?><div class="audio-grid">
                    <?php if (!empty($state['override']['active_preview'])): ?><div class="audio-item"><label>Derzeit verwendete Sonderansage anhören</label><audio controls preload="none" src="?api=audio&amp;kind=active&amp;name=override"></audio></div><?php endif; ?>
                    <?php if (!empty($state['override']['candidate_preview'])): ?><div class="audio-item"><label>Neue Sonderansage anhören</label><audio controls preload="none" src="?api=audio&amp;kind=candidate&amp;name=override"></audio></div><?php endif; ?>
                </div><?php endif; ?>
                <div class="announcement-controls">
                    <div class="source-control"><label for="override-source">Aktive Audioquelle</label><select id="override-source"><option value="tts" <?= ($state['override']['source'] ?? '') === 'tts' ? 'selected' : '' ?>>Automatisch (TTS)</option><option value="manuell" <?= ($state['override']['source'] ?? '') === 'manuell' ? 'selected' : '' ?> <?= empty($state['override']['manual_available']) ? 'disabled' : '' ?>>Manuelle Aufnahme</option></select></div>
                    <div class="source-control"><label for="override-record-extension">Aufnahme-Nebenstelle</label><select id="override-record-extension" <?= empty($state['extensions']) ? 'disabled' : '' ?>><?php foreach (($state['extensions'] ?? []) as $extension): ?><option value="<?= h($extension) ?>"><?= h($extension) ?></option><?php endforeach; ?></select></div>
                    <button class="button secondary" id="use-override-tts" type="button">Auf TTS umschalten</button>
                    <button class="button record-announcement" data-prompt="override" data-extension-select="override-record-extension" type="button" <?= empty($state['extensions']) ? 'disabled' : '' ?>>Genau diese Sonderansage aufnehmen</button>
                    <?php if (!empty($state['override']['candidate_available'])): ?><button class="button activate-candidate" data-prompt="override" type="button">Neue Sonderansage aktivieren</button><?php endif; ?>
                </div>
            </div>
            <div class="card mt18">
                <h3>Geplante und gespeicherte Sonderansagen</h3>
                <p class="muted">TTS, manuelle WAV, aktive Quelle und Zeitplanung bleiben pro Eintrag erhalten. Aktive Einträge benötigen unterschiedliche Prioritäten von 0 bis 1000.</p>
                <div class="field"><label for="override-preset-name">Name, zum Beispiel Weihnachten oder Quartalsanfang</label><input id="override-preset-name" type="text" maxlength="100" autocomplete="off"></div>
                <div class="planning-grid">
                    <div class="field"><label class="checkbox"><input id="override-preset-active" type="checkbox">Für neue Anrufe berücksichtigen</label></div>
                    <div class="field"><label for="override-preset-priority">Priorität</label><input id="override-preset-priority" type="number" min="0" max="1000" step="1" value="100"><span class="hint">Eine höhere Zahl hat Vorrang.</span></div>
                    <div class="field"><label for="override-preset-valid-from">Gültig ab, optional</label><input id="override-preset-valid-from" type="datetime-local"></div>
                    <div class="field"><label for="override-preset-expiry">Gültig bis, optional</label><input id="override-preset-expiry" type="datetime-local"></div>
                    <div class="field"><label for="override-preset-position">Position im Anrufablauf</label><select id="override-preset-position"><option value="statt_begruessung">Anstelle der Begrüßungsansage</option><option value="vor_begruessung">Vor der Begrüßungsansage</option><option value="nach_begruessung">Nach der Begrüßungsansage</option></select></div>
                    <div class="field"><label class="checkbox"><input id="override-preset-block" type="checkbox">Normale Telefonzeiten sperren</label><span class="hint">Bei einer Begrüßungsansage wird dann die Geschlossen-Ansage verwendet; der ärztliche Bereitschaftsdienst bleibt aktiv.</span></div>
                    <div class="field"><label for="override-preset-source">Zu verwendende Audioquelle</label><select id="override-preset-source"><option value="tts">Automatisch (TTS)</option><option value="manuell" <?= empty($state['override']['manual_available']) && empty($state['override']['candidate_available']) ? 'disabled' : '' ?>>Manuelle Aufnahme</option></select><span class="hint">Bei einem neuen Eintrag wird die vorhandene aktuelle Aufnahme beziehungsweise der neue Aufnahme-Kandidat mitgespeichert.</span></div>
                </div>
                <div class="announcement-controls">
                    <button class="button secondary" type="button" id="save-override-preset">Planung speichern</button>
                    <button class="button" type="button" id="record-new-override-preset" <?= empty($state['extensions']) ? 'disabled' : '' ?>>Neue Sonderansage aufnehmen</button>
                    <button class="button secondary" type="button" id="clear-override-preset">Neue Eingabe beginnen</button>
                </div>
                <?php if (empty($state['override_presets'])): ?><div class="empty">Noch keine Sonderansage gespeichert.</div><?php else: ?><div class="preset-grid">
                    <?php foreach (($state['override_presets'] ?? []) as $preset):
                        $runtimeStatus = $presetRuntimeStatus[(string)($preset['id'] ?? '')] ?? ['past' => false, 'future' => false];
                        $isPast = $runtimeStatus['past'];
                        $isFuture = $runtimeStatus['future'];
                        $isEffective = ($preset['id'] ?? '') === $effectivePresetId;
                        $isActive = !empty($preset['active']) && !$isPast;
                        $statusClass = $isPast ? 'status-past' : ($isActive ? 'status-active' : 'status-inactive');
                        $statusText = $isPast ? 'Vergangenheit' : ($isActive ? ($isEffective ? 'Aktiv – wird aktuell angesagt' : ($isFuture ? 'Aktiv – beginnt künftig' : 'Aktiv')) : 'Inaktiv');
                    ?>
                    <article class="preset-card <?= h($statusClass) ?>">
                        <div class="preset-head"><div><h4><?= h($preset['name']) ?></h4><div class="hint">Priorität <?= h($preset['priority']) ?> · <?= h($positionLabels[$preset['position'] ?? ''] ?? 'Unbekannte Position') ?> · <?= !empty($preset['block_phone_hours']) ? 'Telefonzeiten gesperrt' : 'Telefonzeiten bleiben gültig' ?></div><div class="hint">Gültig ab: <?= h($preset['valid_from'] ?: 'sofort') ?> · bis: <?= h($preset['expires_at'] ?: 'unbegrenzt') ?></div></div><div class="announcement-status"><span class="badge <?= h($statusClass) ?>"><?= h($statusText) ?></span><span class="badge"><?= ($preset['source'] ?? 'tts') === 'manuell' ? 'WAV gewählt' : 'TTS gewählt' ?></span></div></div>
                        <div class="preset-text"><?= h($preset['announcement']) ?></div>
                        <div class="audio-grid">
                            <?php if (!empty($preset['tts_preview'])): ?><div class="audio-item"><label>TTS anhören</label><audio controls preload="none" src="?api=audio&amp;kind=preset_tts&amp;name=<?= h($preset['id']) ?>"></audio></div><?php endif; ?>
                            <?php if (!empty($preset['manual_preview'])): ?><div class="audio-item"><label>Aufnahme anhören</label><audio controls preload="none" src="?api=audio&amp;kind=preset_manual&amp;name=<?= h($preset['id']) ?>"></audio></div><?php endif; ?>
                        </div>
                        <div class="announcement-controls">
                            <button class="button secondary load-preset" data-preset-id="<?= h($preset['id']) ?>" data-preset-source="tts" type="button">Mit TTS bearbeiten</button>
                            <?php if (!empty($preset['manual_available'])): ?><button class="button secondary load-preset" data-preset-id="<?= h($preset['id']) ?>" data-preset-source="manuell" type="button">Mit WAV bearbeiten</button><?php endif; ?>
                            <button class="button secondary rerecord-preset" data-preset-id="<?= h($preset['id']) ?>" type="button" <?= empty($state['extensions']) ? 'disabled' : '' ?>>Neu aufnehmen</button>
                            <button class="button danger delete-preset" data-preset-id="<?= h($preset['id']) ?>" type="button">Löschen</button>
                        </div>
                    </article>
                    <?php endforeach; ?>
                </div><?php endif; ?>
            </div>
        </section>
    </main>
</div>
<div id="flash" class="flash" role="status" aria-live="polite"><strong id="flash-title"></strong><div id="flash-detail"></div></div>
<script nonce="<?= h($nonce) ?>">
const csrf = <?= json_encode($csrf, JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) ?>;
const configHash = <?= json_encode($state['config_hash'] ?? '', JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) ?>;
const overridePresets = <?= json_encode($state['override_presets'] ?? [], JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) ?>;
const initialTtsEngine = <?= json_encode($state['tts']['engine'] ?? 'piper', JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) ?>;
const initialQwenVoice = <?= json_encode($state['tts']['qwen_voice'] ?? 'ryan', JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) ?>;
const terminalCodes = new Set(['ansagen_aktuell','ansagenerzeugung_fehlgeschlagen','aufnahme_gespeichert','aufnahme_verworfen','nebenstelle_nicht_erreichbar','vorlage_gespeichert','vorlage_geloescht','auftrag_abgelehnt']);
let selectedManualPreset = '';
let editingPresetId = '';
const flash = document.getElementById('flash');
function showFlash(title, detail = '', error = false) { document.getElementById('flash-title').textContent = title; document.getElementById('flash-detail').textContent = detail; flash.classList.toggle('error', error); flash.classList.add('show'); }
function page(name) { document.querySelectorAll('.page').forEach(el => el.classList.toggle('active', el.id === 'page-' + name)); document.querySelectorAll('nav button').forEach(el => el.classList.toggle('active', el.dataset.page === name)); location.hash = name; }
document.querySelectorAll('nav button').forEach(button => button.addEventListener('click', () => page(button.dataset.page)));
document.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => page(button.dataset.go)));
if (location.hash) page(location.hash.slice(1));
document.querySelectorAll('.reset-input').forEach(button => button.addEventListener('click', () => { const input = button.parentElement.querySelector('input'); input.value = input.dataset.default || ''; }));
document.querySelectorAll('.reset-prompt').forEach(button => button.addEventListener('click', () => { const input = button.closest('.field').querySelector('textarea'); input.value = input.dataset.default || ''; }));
document.querySelectorAll('.reset-check').forEach(button => button.addEventListener('click', () => { const input = button.parentElement.querySelector('input'); input.checked = input.dataset.default === '1'; }));
document.querySelectorAll('.reset-textarea').forEach(button => button.addEventListener('click', () => { const input = button.parentElement.querySelector('textarea'); input.value = input.dataset.default || ''; }));
document.querySelectorAll('.reset-select').forEach(button => button.addEventListener('click', () => { const input = button.parentElement.querySelector('select'); input.value = input.dataset.default || ''; }));
function splitRanges(value) { return value.split(',').map(item => item.trim()).filter(Boolean); }
async function queue(payload) { const response = await fetch('?api=job', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(payload)}); const value = await response.json(); if (!response.ok || !value.ok) throw new Error(value.error || 'Auftrag konnte nicht gestartet werden.'); showFlash('Auftrag angenommen', 'Der sichere Dienst verarbeitet die Änderung.'); await poll(value.job_id, payload.action); }
async function poll(job, action) { for (;;) { await new Promise(resolve => setTimeout(resolve, 900)); const response = await fetch('?api=status&job=' + encodeURIComponent(job), {cache:'no-store'}); const value = await response.json(); if (!value.status) continue; const status = value.status; showFlash(status.label || status.code, status.detail || '', ['ansagenerzeugung_fehlgeschlagen','aufnahme_verworfen','nebenstelle_nicht_erreichbar','auftrag_abgelehnt'].includes(status.code)); if (action === 'record_override_preset' && ['ansagen_aktuell','aufnahme_gespeichert'].includes(status.code)) continue; if (terminalCodes.has(status.code)) { if (['ansagen_aktuell','aufnahme_gespeichert','vorlage_gespeichert','vorlage_geloescht'].includes(status.code)) setTimeout(() => location.reload(), 700); return; } } }
async function safely(task) { try { await task(); } catch (error) { showFlash('Vorgang nicht möglich', error instanceof Error ? error.message : String(error), true); } }
function promptValues() { const prompts = {}; document.querySelectorAll('textarea[data-prompt]').forEach(input => prompts[input.dataset.prompt] = input.value); return prompts; }
function sourceValues() { const sources = {}; document.querySelectorAll('[data-source]').forEach(input => sources[input.dataset.source] = input.value); return sources; }
function ttsValues() { return {engine:document.getElementById('tts-engine').value, qwen_voice:document.getElementById('qwen-voice').value}; }
async function savePrompts() { const tts = ttsValues(); const activeTtsChanged = tts.engine !== initialTtsEngine || (tts.engine === 'qwen' && tts.qwen_voice !== initialQwenVoice); if (activeTtsChanged && !confirm('Modell oder Sprecher wurden geändert. Alle automatischen TTS-Ansagen werden neu erzeugt; manuelle Aufnahmen bleiben erhalten. Fortfahren?')) return; await queue({action:'save', config_hash:configHash, prompts:promptValues(), sources:sourceValues(), tts}); }
function overridePresetValues() { const priority = Number(document.getElementById('override-preset-priority').value); if (!Number.isInteger(priority)) throw new Error('Bitte geben Sie eine ganzzahlige Priorität ein.'); return {preset_id:editingPresetId, name:document.getElementById('override-preset-name').value, announcement:document.getElementById('override-text').value, active:document.getElementById('override-preset-active').checked, priority, valid_from:document.getElementById('override-preset-valid-from').value, expires_at:document.getElementById('override-preset-expiry').value, block_phone_hours:document.getElementById('override-preset-block').checked, position:document.getElementById('override-preset-position').value, source:document.getElementById('override-preset-source').value}; }
async function saveOverride() { const source = document.getElementById('override-source').value; const override = {active:document.getElementById('override-active').checked, announcement:document.getElementById('override-text').value, expires_at:document.getElementById('override-expiry').value, block_phone_hours:document.getElementById('override-block').checked, position:document.getElementById('override-position').value}; if (source === 'manuell' && selectedManualPreset) override.manual_preset_id = selectedManualPreset; await queue({action:'save', config_hash:configHash, override, sources:{override:source}}); }
function findPreset(id) { return overridePresets.find(item => item.id === id); }
function loadPreset(id, source) { const preset = findPreset(id); if (!preset) throw new Error('Die gespeicherte Sonderansage wurde nicht gefunden.'); document.getElementById('override-preset-name').value = preset.name; document.getElementById('override-text').value = preset.announcement; document.getElementById('override-preset-block').checked = Boolean(preset.block_phone_hours); document.getElementById('override-preset-position').value = preset.position || 'statt_begruessung'; document.getElementById('override-preset-active').checked = Boolean(preset.active); document.getElementById('override-preset-priority').value = String(preset.priority ?? 100); document.getElementById('override-preset-valid-from').value = preset.valid_from || ''; document.getElementById('override-preset-expiry').value = preset.expires_at || ''; const presetSource = document.getElementById('override-preset-source'); if (source === 'manuell') presetSource.querySelector('option[value="manuell"]').disabled = false; presetSource.value = source; const sourceSelect = document.getElementById('override-source'); if (source === 'manuell') { const manualOption = sourceSelect.querySelector('option[value="manuell"]'); manualOption.disabled = false; sourceSelect.value = 'manuell'; selectedManualPreset = id; } else { sourceSelect.value = 'tts'; selectedManualPreset = ''; } editingPresetId = id; window.scrollTo({top:document.getElementById('page-override').offsetTop, behavior:'smooth'}); showFlash('Planung geladen', source === 'manuell' ? 'Die WAV-Fassung ist für diesen Eintrag ausgewählt.' : 'Die TTS-Fassung ist für diesen Eintrag ausgewählt.'); }
async function saveOverridePreset() { await queue({action:'save_override_preset', ...overridePresetValues()}); }
async function recordOverridePreset(values = overridePresetValues()) { const extension = document.getElementById('override-record-extension').value; await queue({action:'record_override_preset', ...values, extension}); }
document.getElementById('save-times').addEventListener('click', () => safely(async () => { const schedules = {}; document.querySelectorAll('[data-schedule]').forEach(input => { schedules[input.dataset.schedule] ??= {}; schedules[input.dataset.schedule][input.dataset.day] = splitRanges(input.value); }); await queue({action:'save', config_hash:configHash, schedules}); }));
document.getElementById('save-prompts').addEventListener('click', () => safely(savePrompts));
document.getElementById('save-override').addEventListener('click', () => safely(saveOverride));
document.getElementById('save-override-preset').addEventListener('click', () => safely(saveOverridePreset));
document.getElementById('record-new-override-preset').addEventListener('click', () => safely(recordOverridePreset));
document.getElementById('clear-override-preset').addEventListener('click', () => { editingPresetId = ''; selectedManualPreset = ''; document.getElementById('override-preset-name').value = ''; document.getElementById('override-preset-active').checked = false; document.getElementById('override-preset-priority').value = '100'; document.getElementById('override-preset-valid-from').value = ''; document.getElementById('override-preset-expiry').value = ''; document.getElementById('override-preset-position').value = 'statt_begruessung'; document.getElementById('override-preset-block').checked = false; document.getElementById('override-preset-source').value = 'tts'; showFlash('Neue Eingabe', 'Geben Sie einen neuen Namen ein. Der aktuelle TTS-Text bleibt als Ausgangspunkt erhalten.'); });
document.querySelectorAll('.use-tts').forEach(button => button.addEventListener('click', () => safely(async () => { const card = button.closest('.announcement-card'); card.querySelector('[data-source]').value = 'tts'; await savePrompts(); })));
document.getElementById('use-override-tts').addEventListener('click', () => safely(async () => { document.getElementById('override-source').value = 'tts'; selectedManualPreset = ''; await saveOverride(); }));
document.getElementById('override-source').addEventListener('change', event => { if (event.target.value !== 'manuell') selectedManualPreset = ''; });
document.querySelectorAll('.record-announcement').forEach(button => button.addEventListener('click', () => safely(async () => { const extension = document.getElementById(button.dataset.extensionSelect).value; await queue({action:'record', prompt:button.dataset.prompt, extension}); })));
document.querySelectorAll('.activate-candidate').forEach(button => button.addEventListener('click', () => safely(async () => { await queue({action:'activate_candidate', config_hash:configHash, prompt:button.dataset.prompt}); })));
document.querySelectorAll('.load-preset').forEach(button => button.addEventListener('click', () => safely(async () => loadPreset(button.dataset.presetId, button.dataset.presetSource))));
document.querySelectorAll('.rerecord-preset').forEach(button => button.addEventListener('click', () => safely(async () => { const preset = findPreset(button.dataset.presetId); if (!preset) throw new Error('Die gespeicherte Sonderansage wurde nicht gefunden.'); await recordOverridePreset({preset_id:preset.id, name:preset.name, announcement:preset.announcement, active:Boolean(preset.active), priority:Number(preset.priority), valid_from:preset.valid_from || '', expires_at:preset.expires_at || '', block_phone_hours:Boolean(preset.block_phone_hours), position:preset.position || 'statt_begruessung', source:'manuell'}); })));
document.querySelectorAll('.delete-preset').forEach(button => button.addEventListener('click', () => safely(async () => { const preset = findPreset(button.dataset.presetId); if (!preset) throw new Error('Die gespeicherte Sonderansage wurde nicht gefunden.'); if (!confirm('Gespeicherte Sonderansage „' + preset.name + '“ löschen?')) return; await queue({action:'delete_override_preset', preset_id:preset.id}); })));
</script>
<?php endif; ?>
</body>
</html>
