#!/usr/bin/env bash
# Separater Installer fuer das Kienzlefon-Webinterface.
# Version: 1.1.1
# Changelog:
# - 1.1.1: Bestaetigte Aufrufe aus dem Kienzlefon-Hauptinstaller werden unterstuetzt.
# - 1.1: Gezielte neue Qwen-Varianten je Ansage und Sonderansage ergaenzt.
# - 1.0: Globale TTS-Modell- und Sprecherwahl sowie sichere Qwen3-TTS-Ausfuehrung.
# - 0.4.1: Eigene Position und Telefonzeitensperre je Planung; klarer Aktivstatus.
# - 0.4.0: Mehrere geplante Sonderansagen mit Start, Ablauf und Prioritaet.
# - 0.3.0: Abspielbare Ansagen und benannte Sonderansagen mit TTS/WAV-Bibliothek.
# - 0.2.1: Auswahlansage nach der Wiedergabe in die Vergangenheitsform gesetzt.
# - 0.2.0: Ansagentext, Audioquelle und Direktaufnahme je Ansage zusammengefuehrt.
# - 0.1.4: WireGuard-Adresspruefung fuer den eingebauten PHP-Server korrigiert.
# - 0.1.3: Erwartetes Ueberspringen von TLS mit erfolgreichem Status beendet.
# - 0.1.2: Konfigurationspfade ohne fehlerverdeckende Prozesssubstitution eingelesen.
# - 0.1.1: Lautlosen Abbruch bei der Asterisk-Benutzerermittlung behoben.
# - 0.1.0: Erste separate Fassung fuer PHP-Systemdienst, Apache und Nginx.

set -Eeuo pipefail
umask 027

installer_error() {
  local status="$1" line="$2"
  printf 'FEHLER: Webinterface-Installation in Zeile %s abgebrochen (Status %s).\n' \
    "$line" "$status" >&2
}
trap 'installer_error "$?" "$LINENO"' ERR

VERSION="1.1.1"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG_FILE="/etc/kienzlefon/kienzlefon.toml"
WEB_CONFIG="/etc/kienzlefon/webinterface.json"
VENV="/opt/kienzlefon/venv"
WEB_ROOT="/usr/share/kienzlefon-webinterface"
RUNTIME_DIR="/run/kienzlefon-webinterface"
WEB_GROUP="kienzlefon-web"
WEB_USER="www-data"
DEFAULTS_FILE="${WEB_ROOT}/kienzlefon-defaults.toml"
PHP_FILE="${WEB_ROOT}/admin.php"
TLS_CERT="/etc/kienzlefon/webinterface.crt"
TLS_KEY="/etc/kienzlefon/webinterface.key"
ASTERISK_RESTART_REQUIRED="false"

die() {
  printf 'FEHLER: %s\n' "$*" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || die "Erforderliches Programm fehlt: $1"
}

ask_yes_no() {
  local variable="$1" prompt="$2" default="${3:-n}" answer
  while true; do
    if [[ "$default" == "y" ]]; then
      read -r -p "${prompt} [J/n] " answer
      answer="${answer:-j}"
    else
      read -r -p "${prompt} [j/N] " answer
      answer="${answer:-n}"
    fi
    case "${answer,,}" in
      j|ja|y|yes) printf -v "$variable" 'y'; return ;;
      n|nein|no) printf -v "$variable" 'n'; return ;;
    esac
  done
}

choose_server() {
  local answer
  printf '\nBetriebsart:\n'
  printf '  1) Eigener schlanker PHP-Systemdienst\n'
  printf '  2) Apache-Konfiguration\n'
  printf '  3) Nginx-Konfiguration\n'
  while true; do
    read -r -p 'Auswahl [1]: ' answer
    case "${answer:-1}" in
      1) SERVER_MODE="standalone"; return ;;
      2) SERVER_MODE="apache"; return ;;
      3) SERVER_MODE="nginx"; return ;;
    esac
  done
}

choose_wireguard() {
  local use_wireguard="n" selected interface_list address answer
  WG_INTERFACE=""
  PASSWORDLESS="false"
  if command -v wg >/dev/null 2>&1 && command -v ip >/dev/null 2>&1; then
    interface_list="$(wg show interfaces 2>/dev/null || true)"
  else
    interface_list=""
  fi
  if [[ -n "$interface_list" ]]; then
    ask_yes_no use_wireguard "Webinterface ausschliesslich ueber WireGuard bereitstellen?" y
  fi
  if [[ "$use_wireguard" == "y" ]]; then
    read -r -a interfaces <<<"$interface_list"
    if ((${#interfaces[@]} == 1)); then
      selected="${interfaces[0]}"
    else
      printf 'Verfuegbare WireGuard-Interfaces:\n'
      local index=1 item
      for item in "${interfaces[@]}"; do
        printf '  %d) %s\n' "$index" "$item"
        ((index += 1))
      done
      while true; do
        read -r -p 'Nummer des Interfaces: ' answer
        [[ "$answer" =~ ^[0-9]+$ ]] || continue
        ((answer >= 1 && answer <= ${#interfaces[@]})) || continue
        selected="${interfaces[answer-1]}"
        break
      done
    fi
    address="$(ip -o -4 address show dev "$selected" scope global | awk 'NR==1{sub(/\/.*/,"",$4); print $4}')"
    [[ -n "$address" ]] || die "WireGuard-Interface ${selected} besitzt keine aktive IPv4-Adresse."
    WG_INTERFACE="$selected"
    LISTEN_IP="$address"
    TLS_ENABLED="false"
    ask_yes_no use_passwordless "Auf diesem WireGuard-Interface passwortlosen Betrieb erlauben?" n
    [[ "$use_passwordless" == "y" ]] && PASSWORDLESS="true"
    return 0
  fi

  local suggested
  suggested="$(hostname -I 2>/dev/null | awk '{print $1}')"
  suggested="${suggested:-127.0.0.1}"
  read -r -p "Feste IPv4-Adresse fuer das Webinterface [${suggested}]: " LISTEN_IP
  LISTEN_IP="${LISTEN_IP:-$suggested}"
  [[ "$LISTEN_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "Nur eine feste IPv4-Adresse ist zulaessig."
  [[ "$LISTEN_IP" != "0.0.0.0" ]] || die "Das Webinterface darf nicht auf allen Interfaces lauschen."
  PASSWORDLESS="false"
  if [[ "$LISTEN_IP" == "127.0.0.1" ]]; then
    TLS_ENABLED="false"
  else
    [[ "$SERVER_MODE" != "standalone" ]] || die "Ohne WireGuard ist der PHP-Systemdienst nur auf 127.0.0.1 zulaessig. Bitte Apache oder Nginx fuer HTTPS waehlen."
    TLS_ENABLED="true"
  fi
}

read_paths() {
  local path_output
  if ! path_output="$("${VENV}/bin/python" - "$CONFIG_FILE" <<'PY'
import sys
from kienzlefon.config import load_config

config = load_config(sys.argv[1])
print(config.paths.prompts)
print(config.paths.prompt_masters)
print(config.tts.upload_directory)
PY
  )"; then
    die "Pfade konnten nicht aus der Kienzlefon-Konfiguration gelesen werden."
  fi
  readarray -t KZF_PATHS <<<"$path_output"
  ((${#KZF_PATHS[@]} == 3)) || die "Die Kienzlefon-Konfiguration lieferte nicht genau drei Verwaltungsverzeichnisse."
  [[ -n "${KZF_PATHS[0]}" && -n "${KZF_PATHS[1]}" && -n "${KZF_PATHS[2]}" ]] \
    || die "Mindestens ein erforderliches Verwaltungsverzeichnis ist leer."
  PROMPTS_DIR="${KZF_PATHS[0]}"
  MASTERS_DIR="${KZF_PATHS[1]}"
  UPLOADS_DIR="${KZF_PATHS[2]}"
  return 0
}

configure_password() {
  local current password first second
  current="$("${VENV}/bin/python" - "$CONFIG_FILE" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    raw = tomllib.load(handle)
print(raw.get("webinterface", {}).get("passwort", ""), end="")
PY
  )"
  password="$current"
  if [[ "$PASSWORDLESS" == "false" ]]; then
    if [[ -n "$current" ]]; then
      ask_yes_no keep_password "Vorhandenes Webinterface-Kennwort beibehalten?" y
    else
      keep_password="n"
    fi
    if [[ "$keep_password" != "y" ]]; then
      while true; do
        read -r -s -p 'Neues Administratorkennwort: ' first; printf '\n'
        read -r -s -p 'Kennwort wiederholen: ' second; printf '\n'
        [[ "$first" == "$second" ]] || { printf 'Kennwoerter stimmen nicht ueberein.\n'; continue; }
        ((${#first} >= 12)) || { printf 'Das Kennwort muss mindestens 12 Zeichen lang sein.\n'; continue; }
        password="$first"
        break
      done
    fi
    [[ -n "$password" ]] || die "Im Passwortmodus ist ein Kennwort erforderlich."
  fi
  KZF_WEB_PASSWORD="$password" "${VENV}/bin/python" - "$CONFIG_FILE" <<'PY'
import json, os, re, sys, tomllib
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
password = os.environ.get("KZF_WEB_PASSWORD", "")
literal = json.dumps(password, ensure_ascii=False)
match = re.search(r"^\[webinterface\]\s*$", text, re.M)
if match is None:
    updated = text.rstrip() + f"\n\n[webinterface]\npasswort = {literal}\n"
else:
    next_section = re.search(r"^\[[^]]+\]\s*$", text[match.end():], re.M)
    end = match.end() + (next_section.start() if next_section else len(text) - match.end())
    body = text[match.end():end]
    replaced, count = re.subn(r"^(passwort\s*=\s*).*$", rf"\g<1>{literal}", body, count=1, flags=re.M)
    if count == 0:
        replaced = body.rstrip() + f"\npasswort = {literal}\n"
    updated = text[:match.end()] + replaced + text[end:]
tomllib.loads(updated)
temporary = path.with_name(f".{path.name}.webinstaller.{os.getpid()}")
try:
    temporary.write_text(updated, encoding="utf-8")
    os.chmod(temporary, path.stat().st_mode & 0o777)
    os.chown(temporary, path.stat().st_uid, path.stat().st_gid)
    os.replace(temporary, path)
finally:
    temporary.unlink(missing_ok=True)
PY
  unset KZF_WEB_PASSWORD first second password current
}

write_web_config() {
  LISTEN_IP="$LISTEN_IP" PORT="$PORT" SERVER_MODE="$SERVER_MODE" PASSWORDLESS="$PASSWORDLESS" TLS_ENABLED="$TLS_ENABLED" WG_INTERFACE="$WG_INTERFACE" \
    "${VENV}/bin/python" - "$WEB_CONFIG" <<'PY'
import json, os, pathlib, tempfile
target = pathlib.Path(__import__('sys').argv[1])
value = {
    "version": 1,
    "server": os.environ["SERVER_MODE"],
    "listen": os.environ["LISTEN_IP"],
    "port": int(os.environ["PORT"]),
    "passwordless": os.environ["PASSWORDLESS"] == "true",
    "tls": os.environ["TLS_ENABLED"] == "true",
    "wireguard_interface": os.environ["WG_INTERFACE"],
}
target.parent.mkdir(parents=True, exist_ok=True)
fd, name = tempfile.mkstemp(prefix=".webinterface.", dir=target.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(name, 0o644)
    os.replace(name, target)
finally:
    pathlib.Path(name).unlink(missing_ok=True)
PY
}

install_runtime_layout() {
  local asterisk_process web_group_gid live_groups
  getent group "$WEB_GROUP" >/dev/null 2>&1 || groupadd --system "$WEB_GROUP"
  if ! getent passwd "$WEB_USER" >/dev/null 2>&1; then
    if [[ "$SERVER_MODE" == "standalone" ]]; then
      useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin "$WEB_USER"
    else
      die "Webserver-Benutzer ${WEB_USER} fehlt."
    fi
  fi
  # Nicht vorzeitig aus awk aussteigen: Mit pipefail koennte ps sonst wegen
  # SIGPIPE den gesamten Installer ohne hilfreiche Ausgabe abbrechen.
  asterisk_process="$(ps -eo user=,pid=,comm= | awk '$3 == "asterisk" && found == "" {found=$1 " " $2} END {print found}')"
  if [[ -n "$asterisk_process" ]]; then
    read -r ASTERISK_USER ASTERISK_PID <<<"$asterisk_process"
  else
    ASTERISK_USER="asterisk"
    ASTERISK_PID=""
  fi
  if getent passwd "$ASTERISK_USER" >/dev/null 2>&1 && [[ "$ASTERISK_USER" != "root" ]]; then
    if ! id -nG "$ASTERISK_USER" | tr ' ' '\n' | grep -Fxq "$WEB_GROUP"; then
      usermod -a -G "$WEB_GROUP" "$ASTERISK_USER"
      ASTERISK_RESTART_REQUIRED="true"
    fi
    if [[ -n "$ASTERISK_PID" && -r "/proc/${ASTERISK_PID}/status" ]]; then
      web_group_gid="$(getent group "$WEB_GROUP" | awk -F: '{print $3}')"
      live_groups="$(awk '$1 == "Groups:" {$1=""; sub(/^ /, ""); print}' "/proc/${ASTERISK_PID}/status")"
      if [[ " ${live_groups} " != *" ${web_group_gid} "* ]]; then
        ASTERISK_RESTART_REQUIRED="true"
      fi
    fi
  fi
  usermod -a -G "$WEB_GROUP" "$WEB_USER"

  install -d -o root -g "$WEB_GROUP" -m 0750 "$RUNTIME_DIR"
  install -d -o "$WEB_USER" -g "$WEB_GROUP" -m 0700 "$RUNTIME_DIR/inbox" "$RUNTIME_DIR/sessions"
  install -d -o root -g "$WEB_GROUP" -m 0770 "$RUNTIME_DIR/status"
  install -d -o root -g "$WEB_GROUP" -m 0750 "$RUNTIME_DIR/audio"
  install -d -o root -g root -m 0755 "$WEB_ROOT"
  install -o root -g root -m 0644 "$SOURCE_DIR/webinterface/admin.php" "$PHP_FILE"
  install -o root -g root -m 0444 "$SOURCE_DIR/config/kienzlefon.toml.example" "$DEFAULTS_FILE"

  cat >/usr/lib/tmpfiles.d/kienzlefon-webinterface.conf <<EOF
d ${RUNTIME_DIR} 0750 root ${WEB_GROUP} -
d ${RUNTIME_DIR}/inbox 0700 ${WEB_USER} ${WEB_GROUP} -
d ${RUNTIME_DIR}/sessions 0700 ${WEB_USER} ${WEB_GROUP} -
d ${RUNTIME_DIR}/status 0770 root ${WEB_GROUP} -
d ${RUNTIME_DIR}/audio 0750 root ${WEB_GROUP} -
EOF
}

install_python_commands() {
  [[ -x "${VENV}/bin/pip" ]] || die "Kienzlefon-Virtualenv fehlt: ${VENV}"
  "${VENV}/bin/pip" install --no-deps "$SOURCE_DIR"
  for command in kienzlefon-webadmin-worker kienzlefon-webadmin-export kienzlefon-webaufnahme; do
    [[ -x "${VENV}/bin/${command}" ]] || die "Installiertes Kommando fehlt: ${command}"
  done
}

install_worker_units() {
  cat >/etc/systemd/system/kienzlefon-webinterface-worker.service <<EOF
[Unit]
Description=Kienzlefon Webinterface Auftrag
After=asterisk.service
Requires=asterisk.service

[Service]
Type=oneshot
User=root
Group=${WEB_GROUP}
UMask=0027
ExecStart=${VENV}/bin/kienzlefon-webadmin-worker --config ${CONFIG_FILE} --defaults ${DEFAULTS_FILE} --web-config ${WEB_CONFIG} --runtime ${RUNTIME_DIR}
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=false
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX
ReadWritePaths=/etc/kienzlefon /run/kienzlefon -/var/lib/kienzlefon/qwen3-tts ${RUNTIME_DIR} ${PROMPTS_DIR} ${MASTERS_DIR} ${UPLOADS_DIR}
TimeoutStartSec=4h
EOF

  cat >/etc/systemd/system/kienzlefon-webinterface-worker.path <<EOF
[Unit]
Description=Kienzlefon Webinterface Auftragsueberwachung

[Path]
DirectoryNotEmpty=${RUNTIME_DIR}/inbox
Unit=kienzlefon-webinterface-worker.service

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/systemd/system/kienzlefon-webinterface-refresh.service <<EOF
[Unit]
Description=Kienzlefon Webinterface Ansicht und Kennwort-Hash aktualisieren

[Service]
Type=oneshot
User=root
Group=${WEB_GROUP}
UMask=0027
ExecStart=${VENV}/bin/kienzlefon-webadmin-export --config ${CONFIG_FILE} --defaults ${DEFAULTS_FILE} --web-config ${WEB_CONFIG} --runtime ${RUNTIME_DIR}
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=${RUNTIME_DIR}
EOF

  cat >/etc/systemd/system/kienzlefon-webinterface-refresh.path <<EOF
[Unit]
Description=Kienzlefon TOML-Aenderungen fuer das Webinterface beobachten

[Path]
PathChanged=${CONFIG_FILE}
Unit=kienzlefon-webinterface-refresh.service

[Install]
WantedBy=multi-user.target
EOF
}

generate_certificate() {
  [[ "$TLS_ENABLED" == "true" ]] || return 0
  need_command openssl
  if [[ ! -s "$TLS_KEY" || ! -s "$TLS_CERT" ]]; then
    openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 \
      -keyout "$TLS_KEY" -out "$TLS_CERT" \
      -subj "/CN=${LISTEN_IP}" -addext "subjectAltName=IP:${LISTEN_IP}"
  fi
  chown root:root "$TLS_KEY" "$TLS_CERT"
  chmod 0600 "$TLS_KEY"
  chmod 0644 "$TLS_CERT"
}

find_fpm_socket() {
  local socket version
  socket="$(find /run/php -maxdepth 1 -type s -name 'php*-fpm.sock' 2>/dev/null | sort -V | tail -n 1 || true)"
  if [[ -z "$socket" ]]; then
    version="$(find /etc/php -mindepth 2 -maxdepth 2 -type d -name fpm 2>/dev/null | awk -F/ '{print $4}' | sort -V | tail -n 1 || true)"
    [[ -n "$version" ]] || die "PHP-FPM fehlt. Bitte fuer Apache oder Nginx installieren."
    systemctl enable --now "php${version}-fpm.service"
    socket="/run/php/php${version}-fpm.sock"
    FPM_SERVICE="php${version}-fpm.service"
  else
    version="$(basename "$socket" | sed -E 's/^php([0-9.]+)-fpm\.sock$/\1/')"
    FPM_SERVICE="php${version}-fpm.service"
  fi
  FPM_SOCKET="$socket"
}

install_standalone() {
  [[ "$TLS_ENABLED" == "false" ]] || die "Der eingebaute PHP-Dienst bietet kein TLS."
  cat >/etc/systemd/system/kienzlefon-webinterface.service <<EOF
[Unit]
Description=Kienzlefon Webinterface
After=network-online.target kienzlefon-webinterface-refresh.service
Wants=network-online.target

[Service]
Type=simple
User=${WEB_USER}
Group=${WEB_GROUP}
UMask=0077
ExecStart=/usr/bin/php -d expose_php=0 -d display_errors=0 -S ${LISTEN_IP}:${PORT} -t ${WEB_ROOT} ${PHP_FILE}
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
ReadWritePaths=${RUNTIME_DIR}/inbox ${RUNTIME_DIR}/sessions

[Install]
WantedBy=multi-user.target
EOF
  systemctl disable --now kienzlefon-webinterface-apache.service 2>/dev/null || true
  systemctl enable --now kienzlefon-webinterface.service
}

install_apache() {
  need_command apache2ctl
  find_fpm_socket
  local ssl_lines=""
  if [[ "$TLS_ENABLED" == "true" ]]; then
    a2enmod ssl >/dev/null
    ssl_lines="SSLEngine on
SSLCertificateFile ${TLS_CERT}
SSLCertificateKeyFile ${TLS_KEY}"
  fi
  a2enmod proxy_fcgi setenvif >/dev/null
  cat >/etc/apache2/sites-available/kienzlefon-webinterface.conf <<EOF
Listen ${LISTEN_IP}:${PORT}
<VirtualHost ${LISTEN_IP}:${PORT}>
    ServerName ${LISTEN_IP}
    DocumentRoot ${WEB_ROOT}
    DirectoryIndex admin.php
    ${ssl_lines}
    <Directory ${WEB_ROOT}>
        Require all granted
        AllowOverride None
        Options -Indexes
    </Directory>
    <FilesMatch "\\.php$">
        SetHandler "proxy:unix:${FPM_SOCKET}|fcgi://localhost/"
    </FilesMatch>
    <LocationMatch "^/(?!admin\\.php$|$)">
        Require all denied
    </LocationMatch>
</VirtualHost>
EOF
  a2ensite kienzlefon-webinterface >/dev/null
  apache2ctl configtest
  systemctl disable --now kienzlefon-webinterface.service 2>/dev/null || true
  systemctl restart "$FPM_SERVICE"
  systemctl restart apache2
}

install_nginx() {
  need_command nginx
  find_fpm_socket
  local ssl_lines=""
  if [[ "$TLS_ENABLED" == "true" ]]; then
    ssl_lines="ssl_certificate ${TLS_CERT};
    ssl_certificate_key ${TLS_KEY};
    ssl_protocols TLSv1.2 TLSv1.3;"
  fi
  local listen_options=""
  [[ "$TLS_ENABLED" == "true" ]] && listen_options=" ssl"
  cat >/etc/nginx/sites-available/kienzlefon-webinterface <<EOF
server {
    listen ${LISTEN_IP}:${PORT}${listen_options};
    server_name ${LISTEN_IP};
    root ${WEB_ROOT};
    index admin.php;
    ${ssl_lines}

    location = / {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME ${PHP_FILE};
        fastcgi_pass unix:${FPM_SOCKET};
    }
    location = /admin.php {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME ${PHP_FILE};
        fastcgi_pass unix:${FPM_SOCKET};
    }
    location / { return 404; }
}
EOF
  ln -sfn /etc/nginx/sites-available/kienzlefon-webinterface /etc/nginx/sites-enabled/kienzlefon-webinterface
  nginx -t
  systemctl disable --now kienzlefon-webinterface.service 2>/dev/null || true
  systemctl restart "$FPM_SERVICE"
  systemctl restart nginx
}

main() {
  local confirmed="n"
  while (( $# > 0 )); do
    case "$1" in
      --from-main-installer) confirmed="y" ;;
      -h|--help)
        printf 'Aufruf: %s [--from-main-installer]\n' "${0##*/}"
        return 0
        ;;
      *) die "Unbekannte Option: $1" ;;
    esac
    shift
  done

  printf 'Kienzlefon-Webinterface-Installer %s\n' "$VERSION"
  [[ ${EUID} -eq 0 ]] || die "Dieser Installer muss als root ausgefuehrt werden."
  [[ -f "$CONFIG_FILE" ]] || die "Kienzlefon-Konfiguration fehlt: ${CONFIG_FILE}"
  [[ -f "$SOURCE_DIR/webinterface/admin.php" ]] || die "PHP-Datei fehlt im Quellverzeichnis."
  need_command systemctl
  need_command install
  need_command php
  need_command awk
  need_command find
  need_command getent
  [[ -x "${VENV}/bin/python" ]] || die "Kienzlefon-Virtualenv fehlt."
  if [[ "$confirmed" != "y" ]]; then
    ask_yes_no confirmed "Separate Webinterface-Installation jetzt starten?" n
  fi
  [[ "$confirmed" == "y" ]] || { printf 'Installation nicht gestartet.\n'; exit 0; }

  choose_server
  if [[ "$SERVER_MODE" == "standalone" ]] && ! getent passwd "$WEB_USER" >/dev/null 2>&1; then
    WEB_USER="kienzlefon-webui"
  fi
  choose_wireguard
  if [[ "$TLS_ENABLED" == "true" ]]; then
    PORT=8443
  else
    PORT=8088
  fi
  read -r -p "Port [${PORT}]: " selected_port
  PORT="${selected_port:-$PORT}"
  [[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1024 && PORT <= 65535)) || die "Ungueltiger Port."

  install_python_commands
  "${VENV}/bin/kienzlefon-migration" --config "$CONFIG_FILE" --template "$SOURCE_DIR/config/kienzlefon.toml.example"
  configure_password
  "${VENV}/bin/kienzlefon-config" --config "$CONFIG_FILE"
  printf 'Ansagen werden auf den aktuellen Konfigurationsstand gebracht.\n'
  "${VENV}/bin/kienzlefon-ansagen" --config "$CONFIG_FILE"
  read_paths
  printf 'Webinterface-Dateien und Laufzeitrechte werden eingerichtet.\n'
  write_web_config
  install_runtime_layout
  printf 'Systemd-Einheiten werden eingerichtet.\n'
  install_worker_units
  generate_certificate

  printf 'Webinterface-Dienste werden aktiviert.\n'
  systemctl daemon-reload
  if [[ "$ASTERISK_RESTART_REQUIRED" == "true" ]]; then
    printf 'Asterisk wird einmal neu gestartet, damit die neue Dateifreigabe wirksam ist.\n'
    systemctl restart asterisk
  fi
  systemctl enable --now kienzlefon-webinterface-worker.path kienzlefon-webinterface-refresh.path
  systemctl start kienzlefon-webinterface-refresh.service
  case "$SERVER_MODE" in
    standalone) install_standalone ;;
    apache) install_apache ;;
    nginx) install_nginx ;;
  esac

  local scheme="http"
  [[ "$TLS_ENABLED" == "true" ]] && scheme="https"
  printf '\nWebinterface installiert: %s://%s:%s/\n' "$scheme" "$LISTEN_IP" "$PORT"
  if [[ "$PASSWORDLESS" == "true" ]]; then
    printf 'Zugriff: passwortlos, ausschliesslich ueber WireGuard %s\n' "$WG_INTERFACE"
  else
    printf 'Zugriff: Administratorkennwort aus [webinterface].passwort\n'
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
