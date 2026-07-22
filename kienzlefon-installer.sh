#!/usr/bin/env bash
# ==============================================================================
# kienzlefon-installer.sh
#
# Version: 1.9.1
# Changelog:
# - 1.9.1: Falschnegative Asterisk-wav16-Pruefung korrigiert und erfolgreichen Worker-Neustart wiederhergestellt.
# - 1.9: Optionale Rufnummernanonymisierung fuer neue und bestehende Demo-Konfigurationen ergaenzt.
# - 1.8.3: Verlustfreie Teiltranskription bei leeren Einzelfeldern installiert.
# - 1.8.2: Bereitschaftsdienst- und Ansagetextkorrekturen installiert.
# - 1.8.1: Gruppenschreibbare Telepraxis-Ausgabe und passende Worker-Gruppe ergaenzt.
# - 1.8: Gewarnten Demomodus ohne Public Key und unverschluesselte JSON-Ausgabe ergaenzt.
# - 1.7.1: Aktiviertes rotes Telefon in die priorisierte Sonderqueue aufgenommen.
# - 1.7: Optionales rotes Telefon, Sonderqueue und Caller-ID-Anzeige ergaenzt.
# - 1.6.2: Patchrelease mit korrigierter AGI-Hangup-Behandlung installiert.
# - 1.6.1: Falschnegative FFmpeg-loudnorm-Pruefung unter pipefail korrigiert.
# - 1.6: Getrennte Whisper-Modellwahl mit RAM-Hinweis und Mehrfachdownload ergaenzt.
# - 1.5: 16-kHz-Ansagen und Lautheitsnormalisierung in die Installation aufgenommen.
# - 1.4: PIN entfernt und Ansagen-IVR-Menues auf klare Wiederholung umgestellt.
# - 1.3: Konfigurationsmigration, Ansagen-IVR, Zusatztelefone und Wahlregeln ergaenzt.
# - 1.2: Zeitabfragen, Zeitkopien und TOML-Persistenzpruefung korrigiert.
# - 1.1: Versionsfreigabe und neue TTS-, IVR- und Notfallparameter ergaenzt.
# - 1.0: Erstinstallation mit Kienzlefax-Basis, Asterisk, Whisper und Piper.
# ==============================================================================

set -Eeuo pipefail

VERSION="1.9.1"
PROJECT_URL="https://github.com/thomaskien/kienzlefon"
ARCHIVE_URL="${PROJECT_URL}/archive/refs/heads/main.tar.gz"
KFX_INSTALLER_URL="https://raw.githubusercontent.com/thomaskien/kienzlefax-fuer-linux/main/kienzlefax-installer.sh"
KFX_ENV="/etc/kienzlefax-installer.env"
CONFIG_DIR="/etc/kienzlefon"
CONFIG_FILE="${CONFIG_DIR}/kienzlefon.toml"
PUBLIC_KEY_FILE="${CONFIG_DIR}/telepraxis-public.pem"
INSTALL_ROOT="/opt/kienzlefon"
SOURCE_TARGET="${INSTALL_ROOT}/src"
VENV="${INSTALL_ROOT}/venv"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPORTING_ERROR="n"

log(){ printf '[%s] %s\n' "$(date -Is)" "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
sep(){ printf '\n======================================================================\n== %s\n======================================================================\n' "$*"; }

report_installer_error(){
  local code="$1" message="$2"
  [[ "$REPORTING_ERROR" == "n" ]] || return 0
  REPORTING_ERROR="y"
  if [[ -x "${VENV}/bin/kienzlefon-fehler" && -r "$CONFIG_FILE" ]]; then
    "${VENV}/bin/kienzlefon-fehler" --config "$CONFIG_FILE" \
      --code "$code" --phase installation --message "$message" >/dev/null 2>&1 || true
  fi
  REPORTING_ERROR="n"
}

on_error(){
  local status=$? line="${BASH_LINENO[0]:-?}" command="${BASH_COMMAND:-unbekannt}"
  report_installer_error "INSTALLER_FAILED" "Zeile ${line}, Status ${status}: ${command}"
  printf 'ERROR: Installation abgebrochen in Zeile %s: %s\n' "$line" "$command" >&2
  exit "$status"
}
trap on_error ERR

require_root(){ [[ ${EUID:-0} -eq 0 ]] || die "Bitte als root ausfuehren."; }

ask_yes_no(){
  local __var="$1" prompt="$2" default="$3" value=""
  while true; do
    read -r -p "${prompt} [${default}]: " value
    value="${value:-$default}"
    case "$value" in
      y|Y|yes|YES|j|J|ja|JA) printf -v "$__var" 'y'; return 0 ;;
      n|N|no|NO|nein|NEIN) printf -v "$__var" 'n'; return 0 ;;
      *) printf 'Bitte j/n eingeben.\n' ;;
    esac
  done
}

ask_value(){
  local __var="$1" prompt="$2" default="${3-}" value=""
  read -r -p "${prompt}${default:+ [${default}]}: " value
  printf -v "$__var" '%s' "${value:-$default}"
}

whisper_model_from_choice(){
  case "$1" in
    1) printf 'large-v3-turbo' ;;
    2) printf 'large-v3' ;;
    *) return 1 ;;
  esac
}

whisper_choice_from_model(){
  case "$1" in
    large-v3-turbo) printf '1' ;;
    large-v3) printf '2' ;;
    *) return 1 ;;
  esac
}

collect_whisper_models(){
  local default_standard="1" default_names="2" default_medications="1"
  local choice_standard="" choice_names="" choice_medications="" confirmation=""
  local ram_mib="" ram_gib="unbekannt" unique_count=1

  if [[ -r "$CONFIG_FILE" ]]; then
    default_standard="$("${VENV}/bin/python" -c \
      'import sys,tomllib; v=tomllib.load(open(sys.argv[1],"rb"))["whisper"]["modell_standard"]; print(1 if v == "large-v3-turbo" else 2)' \
      "$CONFIG_FILE")"
    default_names="$("${VENV}/bin/python" -c \
      'import sys,tomllib; v=tomllib.load(open(sys.argv[1],"rb"))["whisper"]["modell_namen"]; print(1 if v == "large-v3-turbo" else 2)' \
      "$CONFIG_FILE")"
    default_medications="$("${VENV}/bin/python" -c \
      'import sys,tomllib; v=tomllib.load(open(sys.argv[1],"rb"))["whisper"]["modell_medikamente"]; print(1 if v == "large-v3-turbo" else 2)' \
      "$CONFIG_FILE")"
  fi

  if [[ -r /proc/meminfo ]]; then
    ram_mib="$(awk '/^MemTotal:/ { print int($2 / 1024); exit }' /proc/meminfo)"
    if [[ -n "$ram_mib" ]]; then
      ram_gib="$(awk -v mib="$ram_mib" 'BEGIN { printf "%.1f", mib / 1024 }')"
    fi
  fi

  printf '\nWhisper-Modellwahl (erkannter Arbeitsspeicher: %s GB):\n' "$ram_gib"
  printf '  1 = large-v3-turbo (etwa dreimal so schnell wie large-v3 und speichersparender)\n'
  printf '  2 = large-v3 (langsamer, bei Eigennamen moeglicherweise genauer)\n'
  printf 'Mit 16 GB Arbeitsspeicher koennen beide Modelle dauerhaft geladen werden.\n'
  printf 'Mit 8 GB ist die Verwendung beider Modelle moeglich, aber nicht empfohlen.\n\n'

  while true; do
    ask_value choice_names "Whisper-Modell fuer Vor- und Nachnamen (1 oder 2)" "$default_names"
    whisper_model_from_choice "$choice_names" >/dev/null \
      || { printf 'Bitte 1 oder 2 eingeben.\n'; continue; }
    ask_value choice_medications \
      "Whisper-Modell fuer Medikamente und Wirkstoffe (1 oder 2)" \
      "$default_medications"
    whisper_model_from_choice "$choice_medications" >/dev/null \
      || { printf 'Bitte 1 oder 2 eingeben.\n'; continue; }
    ask_value choice_standard \
      "Whisper-Modell fuer alle uebrigen Aufnahmen (1 oder 2)" \
      "$default_standard"
    whisper_model_from_choice "$choice_standard" >/dev/null \
      || { printf 'Bitte 1 oder 2 eingeben.\n'; continue; }

    KZF_MODEL_NAMES="$(whisper_model_from_choice "$choice_names")"
    KZF_MODEL_MEDICATIONS="$(whisper_model_from_choice "$choice_medications")"
    KZF_MODEL_STANDARD="$(whisper_model_from_choice "$choice_standard")"
    if [[ "$KZF_MODEL_NAMES" != "$KZF_MODEL_STANDARD" \
      || "$KZF_MODEL_MEDICATIONS" != "$KZF_MODEL_STANDARD" ]]; then
      unique_count=2
    else
      unique_count=1
    fi

    if (( unique_count > 1 )) && { [[ -z "$ram_mib" ]] || (( ram_mib < 15360 )); }; then
      printf '\nWARNUNG: Beide Whisper-Modelle werden dauerhaft im Arbeitsspeicher gehalten.\n'
      printf 'Auf einem System mit weniger als 16 GB ist diese Auswahl nicht empfohlen.\n'
      printf 'Sie ist zulaessig, kann aber zu Speicherdruck oder einem Abbruch des Workers fuehren.\n'
      ask_yes_no confirmation "Beide Modelle trotzdem verwenden?" "n"
      if [[ "$confirmation" != "y" ]]; then
        printf 'Bitte die drei Modellbereiche erneut auswaehlen.\n'
        continue
      fi
    fi
    break
  done
  export KZF_MODEL_STANDARD KZF_MODEL_NAMES KZF_MODEL_MEDICATIONS
}

update_existing_whisper_models(){
  "${VENV}/bin/kienzlefon-migration" \
    --config "$CONFIG_FILE" \
    --template "$SOURCE_TARGET/config/kienzlefon.toml.example" \
    --standard-model "$KZF_MODEL_STANDARD" \
    --name-model "$KZF_MODEL_NAMES" \
    --medication-model "$KZF_MODEL_MEDICATIONS"
}

configure_demo_anonymization(){
  local demo_mode="" current="" default="n" choice="" value="false"
  demo_mode="$(${VENV}/bin/python -c \
    'import sys,tomllib; print("y" if tomllib.load(open(sys.argv[1],"rb"))["telepraxis"].get("demo", False) else "n")' \
    "$CONFIG_FILE")"
  [[ "$demo_mode" == "y" ]] || return
  current="$(${VENV}/bin/python -c \
    'import sys,tomllib; print("y" if tomllib.load(open(sys.argv[1],"rb"))["telepraxis"].get("anrufernummern_anonymisieren", False) else "n")' \
    "$CONFIG_FILE")"
  [[ "$current" == "y" ]] && default="j"
  printf '\nDie optionale Anonymisierung ersetzt in ausgegebenen Demo-JSONs id und telefon durch #anonymisiert demo#.\n'
  printf 'Audiodateien und in Freitexten genannte Rufnummern werden dadurch nicht veraendert.\n'
  ask_yes_no choice "Anrufernummern in den Demo-JSON-Dateien anonymisieren?" "$default"
  [[ "$choice" == "y" ]] && value="true"
  "${VENV}/bin/kienzlefon-migration" \
    --config "$CONFIG_FILE" \
    --template "$SOURCE_TARGET/config/kienzlefon.toml.example" \
    --demo-anonymize "$value"
}

ask_secret(){
  local __var="$1" prompt="$2" value=""
  read -r -s -p "${prompt}: " value
  printf '\n'
  [[ -n "$value" ]] || die "${prompt} darf nicht leer sein."
  printf -v "$__var" '%s' "$value"
}

download(){
  local url="$1" target="$2"
  local temporary="${target}.tmp.$$"
  curl -fsSL "$url" -o "$temporary"
  [[ -s "$temporary" ]] || die "Download leer: ${url}"
  mv -f "$temporary" "$target"
}

ffmpeg_supports_filter(){
  local filter="$1" filters=""
  filters="$(ffmpeg -hide_banner -filters 2>/dev/null)" || return 1
  [[ "$filters" =~ [[:space:]]${filter}[[:space:]] ]]
}

asterisk_supports_format(){
  local format="$1" formats=""
  formats="$(asterisk -rx "core show file formats")" || return 1
  [[ "$formats" =~ (^|[[:space:]])${format}([[:space:]]|$) ]]
}

ensure_kienzlefax(){
  local install_kfx=""
  if [[ ! -r "$KFX_ENV" ]]; then
    ask_yes_no install_kfx "Kienzlefax-Grundinstallation fehlt. Jetzt installieren?" "j"
    [[ "$install_kfx" == "y" ]] || die "Kienzlefon setzt eine Kienzlefax-Telefoniebasis voraus."
    local installer
    installer="$(mktemp)"
    download "$KFX_INSTALLER_URL" "$installer"
    chmod +x "$installer"
    "$installer"
    rm -f "$installer"
  fi

  # shellcheck disable=SC1090
  source "$KFX_ENV"
  if [[ "${KFX_PHONE_QUEUE_ENABLED:-n}" != "y" ]]; then
    ask_yes_no install_kfx "Kienzlefax-Praxisqueue ist nicht aktiv. Kienzlefax erneut konfigurieren?" "j"
    [[ "$install_kfx" == "y" ]] || die "Die bestehende Queue 'praxis' ist erforderlich."
    local installer
    installer="$(mktemp)"
    download "$KFX_INSTALLER_URL" "$installer"
    chmod +x "$installer"
    "$installer"
    rm -f "$installer"
    # shellcheck disable=SC1090
    source "$KFX_ENV"
  fi

  [[ "${KFX_PHONE_QUEUE_ENABLED:-n}" == "y" ]] || die "Kienzlefax-Praxisqueue ist weiterhin deaktiviert."
  [[ -r /etc/asterisk/extensions-kfx-telefonie.conf ]] || die "Kienzlefax-Telefoniedialplan fehlt."
  [[ -r /etc/asterisk/pjsip-kfx-telefonie.conf ]] || die "Kienzlefax-PJSIP-Konfiguration fehlt."
  grep -q '^\[praxis\]' /etc/asterisk/queues-kfx.conf || die "Kienzlefax-Queue [praxis] fehlt."
  grep -q '^\[kfx_external_capacity\]' /etc/asterisk/extensions.conf \
    || grep -q '^\[kfx_external_capacity\]' /etc/asterisk/extensions-kfx-telefonie.conf \
    || die "Gemeinsamer Kienzlefax-Kapazitaetsguard fehlt; mindestens Stand 3.3.19 ist erforderlich."
}

prepare_source(){
  if [[ -f "${SCRIPT_DIR}/pyproject.toml" && -d "${SCRIPT_DIR}/kienzlefon" ]]; then
    SOURCE_DIR="$SCRIPT_DIR"
    return
  fi
  local archive extract
  archive="$(mktemp)"
  extract="$(mktemp -d)"
  download "$ARCHIVE_URL" "$archive"
  tar -xzf "$archive" -C "$extract"
  SOURCE_DIR="$(find "$extract" -mindepth 1 -maxdepth 1 -type d -name 'kienzlefon-*' | head -n1)"
  [[ -n "$SOURCE_DIR" && -f "${SOURCE_DIR}/pyproject.toml" ]] || die "Projektarchiv ist unvollstaendig."
}

install_packages(){
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 python3-venv python3-pip ffmpeg curl wget openssl rsync acl libgomp1
  ffmpeg_supports_filter loudnorm \
    || die "Das installierte FFmpeg unterstuetzt den erforderlichen loudnorm-Filter nicht."
  python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("ERROR: Python 3.11 oder neuer ist erforderlich.")
PY
}

copy_and_install_project(){
  install -d -m 0755 "$INSTALL_ROOT" "$SOURCE_TARGET"
  if [[ "$(readlink -f "$SOURCE_DIR")" != "$(readlink -f "$SOURCE_TARGET")" ]]; then
    rsync -a --delete --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' \
      "${SOURCE_DIR}/" "${SOURCE_TARGET}/"
  fi
  if [[ ! -x "${VENV}/bin/python" ]]; then
    python3 -m venv "$VENV"
  fi
  "${VENV}/bin/python" -m pip install --upgrade pip wheel
  "${VENV}/bin/python" -m pip install --upgrade "$SOURCE_TARGET"
  for command in kienzlefon-ansagen kienzlefon-config kienzlefon-status kienzlefon-asterisk kienzlefon-fehler kienzlefon-migration; do
    ln -sfn "${VENV}/bin/${command}" "/usr/local/sbin/${command}"
  done
}

#collect_schedule(){
#  local prefix="$1" label="$2" day variable value
#  for day in montag dienstag mittwoch donnerstag freitag samstag sonntag; do
#    variable="${prefix}_${day^^}"
#    ask_value value "${label} ${day} (z.B. 08:00-12:00,14:00-17:00; leer=geschlossen)" ""
#    printf -v "$variable" '%s' "$value"
#    export "$variable"
#  done
#}


collect_schedule() {
  local prefix="$1"
  local label="$2"
  local day day_key variable
  local value=""

  for day in montag dienstag mittwoch donnerstag freitag samstag sonntag; do
    case "$day" in
      montag) day_key="MONTAG" ;;
      dienstag) day_key="DIENSTAG" ;;
      mittwoch) day_key="MITTWOCH" ;;
      donnerstag) day_key="DONNERSTAG" ;;
      freitag) day_key="FREITAG" ;;
      samstag) day_key="SAMSTAG" ;;
      sonntag) day_key="SONNTAG" ;;
    esac
    variable="${prefix}_${day_key}"
    value=""

    ask_value value \
      "${label} ${day} (ohne Klammern; z.B. 08:00-12:00,14:00-17:00; leer=geschlossen)" \
      ""

    printf -v "$variable" '%s' "$value"
    export "$variable"
  done
}


set_schedule_value() {
  local prefix="$1" day_key="$2" value="$3" variable
  variable="${prefix}_${day_key}"
  printf -v "$variable" '%s' "$value"
  export "$variable"
}


collect_opening_schedule() {
  local same_morning="" morning="" afternoon="" combined="" weekend=""
  local day day_key day_label

  ask_yes_no same_morning \
    "Sind die Vormittagsoeffnungszeiten montags bis freitags gleich?" "j"
  if [[ "$same_morning" != "y" ]]; then
    collect_schedule KZF_OPEN "Praxisoeffnungszeiten"
    return
  fi

  ask_value morning \
    "Gemeinsame Vormittagsoeffnungszeit Montag bis Freitag (z.B. 08:00-12:00)" ""
  [[ -n "$morning" ]] || die "Die gemeinsame Vormittagsoeffnungszeit darf nicht leer sein."

  for day in montag dienstag mittwoch donnerstag freitag; do
    case "$day" in
      montag) day_key="MONTAG"; day_label="Montag" ;;
      dienstag) day_key="DIENSTAG"; day_label="Dienstag" ;;
      mittwoch) day_key="MITTWOCH"; day_label="Mittwoch" ;;
      donnerstag) day_key="DONNERSTAG"; day_label="Donnerstag" ;;
      freitag) day_key="FREITAG"; day_label="Freitag" ;;
    esac
    ask_value afternoon \
      "Praxisoeffnungszeit ${day_label} nachmittags (leer=geschlossen)" ""
    combined="$morning"
    if [[ -n "$afternoon" ]]; then
      combined="${combined},${afternoon}"
    fi
    set_schedule_value KZF_OPEN "$day_key" "$combined"
  done

  ask_value weekend "Praxisoeffnungszeiten Samstag (leer=geschlossen)" ""
  set_schedule_value KZF_OPEN "SAMSTAG" "$weekend"
  ask_value weekend "Praxisoeffnungszeiten Sonntag (leer=geschlossen)" ""
  set_schedule_value KZF_OPEN "SONNTAG" "$weekend"
}


collect_phone_schedule() {
  local same_weekdays="" weekdays="" weekend="" day_key
  ask_yes_no same_weekdays "Sind die Telefonzeiten montags bis freitags gleich?" "j"
  if [[ "$same_weekdays" != "y" ]]; then
    collect_schedule KZF_PHONE "Telefonzeiten"
    return
  fi

  ask_value weekdays \
    "Gemeinsame Telefonzeiten Montag bis Freitag (z.B. 08:00-12:00)" ""
  for day_key in MONTAG DIENSTAG MITTWOCH DONNERSTAG FREITAG; do
    set_schedule_value KZF_PHONE "$day_key" "$weekdays"
  done
  ask_value weekend "Telefonzeiten Samstag (leer=geschlossen)" ""
  set_schedule_value KZF_PHONE "SAMSTAG" "$weekend"
  ask_value weekend "Telefonzeiten Sonntag (leer=geschlossen)" ""
  set_schedule_value KZF_PHONE "SONNTAG" "$weekend"
}


copy_schedule() {
  local source_prefix="$1" target_prefix="$2" day_key source_variable
  for day_key in MONTAG DIENSTAG MITTWOCH DONNERSTAG FREITAG SAMSTAG SONNTAG; do
    source_variable="${source_prefix}_${day_key}"
    set_schedule_value "$target_prefix" "$day_key" "${!source_variable}"
  done
}


collect_time_configuration() {
  local same_hours=""
  collect_opening_schedule
  collect_phone_schedule
  ask_yes_no same_hours \
    "Apothekenzugang zu denselben Zeiten wie die Praxisoeffnungszeiten anbieten?" "j"
  if [[ "$same_hours" == "y" ]]; then
    copy_schedule KZF_OPEN KZF_PHARMACY
  else
    collect_schedule KZF_PHARMACY "Apothekenzugang"
  fi
  ask_yes_no same_hours \
    "Fachstellenzugang zu denselben Zeiten wie die Praxisoeffnungszeiten anbieten?" "j"
  if [[ "$same_hours" == "y" ]]; then
    copy_schedule KZF_OPEN KZF_SPECIALIST
  else
    collect_schedule KZF_SPECIALIST "Fachstellenzugang"
  fi
}


update_existing_times() {
  "${VENV}/bin/python" - <<'PY'
# kienzlefon installer time updater
# Version: 1.8
# Changelog:
# - 1.8: Zeitaktualisierung unveraendert in den 1.8-Installer uebernommen.
# - 1.7.1: Zeitaktualisierung unveraendert in den 1.7.1-Installer uebernommen.
# - 1.7: Zeitaktualisierung unveraendert in den 1.7-Installer uebernommen.
# - 1.6.2: Zeitaktualisierung unveraendert in den 1.6.2-Installer uebernommen.
# - 1.6.1: Zeitaktualisierung unveraendert in den 1.6.1-Installer uebernommen.
# - 1.6: Zeitaktualisierung unveraendert in den 1.6-Installer uebernommen.
# - 1.5: Zeitaktualisierung unveraendert in den 1.5-Installer uebernommen.
# - 1.4: Zeitaktualisierung unveraendert in den 1.4-Installer uebernommen.
# - 1.3: Zeitaktualisierung unveraendert in den 1.3-Installer uebernommen.
# - 1.2: Ausschliesslich vorhandene TOML-Zeitprofile atomar aktualisieren.
import json
import os
import re
import tomllib
from pathlib import Path

target = Path(os.environ["CONFIG_FILE"])
text = target.read_text(encoding="utf-8")

def toml(value):
    return json.dumps(value, ensure_ascii=False)

def set_value(section, key, value):
    global text
    lines = text.splitlines()
    in_section = False
    for index, line in enumerate(lines):
        if line == f"[{section}]":
            in_section = True
            continue
        if in_section and line.startswith("["):
            break
        if in_section and re.match(rf"^{re.escape(key)}\s*=", line):
            lines[index] = f"{key} = {toml(value)}"
            text = "\n".join(lines) + "\n"
            return
    raise SystemExit(f"ERROR: TOML-Feld nicht gefunden: [{section}].{key}")

def schedule(prefix):
    result = {}
    for day in ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"):
        raw = os.environ.get(f"{prefix}_{day.upper()}", "").replace(" ", "")
        result[day] = [value for value in raw.split(",") if value]
    return result

expected_schedules = {
    "oeffnungszeiten": schedule("KZF_OPEN"),
    "telefonzeiten": schedule("KZF_PHONE"),
    "apothekenzeiten": schedule("KZF_PHARMACY"),
    "fachstellenzeiten": schedule("KZF_SPECIALIST"),
}
for section, values in expected_schedules.items():
    for key, value in values.items():
        set_value(section, key, value)

temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
temporary.write_text(text, encoding="utf-8")
os.chmod(temporary, 0o640)
os.replace(temporary, target)

with target.open("rb") as handle:
    stored = tomllib.load(handle)
for section, expected in expected_schedules.items():
    actual = {day: stored[section][day] for day in expected}
    if actual != expected:
        raise SystemExit(
            f"ERROR: Zeitprofil [{section}] wurde nicht korrekt in {target} gespeichert"
        )
PY
}


collect_sip_line(){
  local prefix="$1" label="$2" enabled did user password domain proxy expiration outbound
  ask_yes_no enabled "Separate externe Rufnummer fuer ${label} einrichten?" "n"
  if [[ "$enabled" == "y" ]]; then
    ask_value did "Externe Rufnummer/DID fuer ${label}" ""
    [[ "$did" =~ ^[0-9]+$ ]] || die "DID fuer ${label} ist ungueltig."
    ask_value user "SIP-Benutzer fuer ${label}" "$did"
    ask_secret password "SIP-Passwort fuer ${label}"
    ask_value domain "SIP-Domain fuer ${label}" "${KFX_PHONE_IN_SIP_DOMAIN:-}"
    [[ -n "$domain" ]] || die "SIP-Domain fuer ${label} fehlt."
    ask_value proxy "Outbound-Proxy fuer ${label} (leer=keiner)" "${KFX_PHONE_IN_SIP_OUTBOUND_PROXY:-}"
    ask_value expiration "Registration-Expiration fuer ${label}" "300"
    ask_yes_no outbound "Diese Rufnummer ausgehend verwenden? Empfehlung: Praxis-Hauptnummer" "n"
  else
    did=""; user=""; password=""; domain=""; proxy=""; expiration="300"; outbound="n"
  fi
  printf -v "${prefix}_AKTIV" '%s' "$enabled"
  printf -v "${prefix}_DID" '%s' "$did"
  printf -v "${prefix}_USER" '%s' "$user"
  printf -v "${prefix}_PASSWORD" '%s' "$password"
  printf -v "${prefix}_DOMAIN" '%s' "$domain"
  printf -v "${prefix}_PROXY" '%s' "$proxy"
  printf -v "${prefix}_EXPIRATION" '%s' "$expiration"
  printf -v "${prefix}_OUTBOUND" '%s' "$outbound"
  export "${prefix}_AKTIV" "${prefix}_DID" "${prefix}_USER" "${prefix}_PASSWORD"
  export "${prefix}_DOMAIN" "${prefix}_PROXY" "${prefix}_EXPIRATION" "${prefix}_OUTBOUND"
}

configure_additional_extensions(){
  local configure="" count="0" red
  red="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["ivr"]["rote_nebenstelle"])' "$CONFIG_FILE")"
  ask_yes_no configure "Zusaetzliche interne Nebenstellen ausserhalb der Queue konfigurieren?" "n"
  [[ "$configure" == "y" ]] || return 0
  ask_value count "Anzahl zusaetzlicher Nebenstellen direkt nach ${red}" "0"
  [[ "$count" =~ ^[0-9]+$ ]] || die "Die Anzahl zusaetzlicher Nebenstellen ist ungueltig."
  export CONFIG_FILE KZF_EXTRA_COUNT="$count"
  "${VENV}/bin/python" - <<'PY'
# kienzlefon installer extension updater
# Version: 1.8
# Changelog:
# - 1.8: Zusatznebenstellen unveraendert in den 1.8-Installer uebernommen.
# - 1.7.1: Zusatznebenstellen unveraendert in den 1.7.1-Installer uebernommen.
# - 1.7: Zusatznebenstellen fuer die Auswahl der Sonderqueue bereitgestellt.
# - 1.6.2: Zusatznebenstellen unveraendert in den 1.6.2-Installer uebernommen.
# - 1.6.1: Zusatznebenstellen unveraendert in den 1.6.1-Installer uebernommen.
# - 1.6: Zusatznebenstellen unveraendert in den 1.6-Installer uebernommen.
# - 1.5: Zusatznebenstellen unveraendert in den 1.5-Installer uebernommen.
# - 1.4: Zusatznebenstellen unveraendert in den 1.4-Installer uebernommen.
# - 1.3: Zusatznebenstellen atomar aktualisiert und vorhandene Passwoerter bewahrt.
import json
import os
import re
import secrets
import tomllib
from pathlib import Path

target = Path(os.environ["CONFIG_FILE"])
with target.open("rb") as handle:
    raw = tomllib.load(handle)
red = int(raw["ivr"]["rote_nebenstelle"])
count = int(os.environ["KZF_EXTRA_COUNT"])
extensions = [str(red + offset) for offset in range(1, count + 1)]
if "777" in extensions:
    raise SystemExit("ERROR: Zusatznebenstellen duerfen die feste Ansagen-Nebenstelle 777 nicht belegen")
old = dict(zip(
    raw["zusaetzliche_nebenstellen"].get("nebenstellen", []),
    raw["zusaetzliche_nebenstellen"].get("passwoerter", []),
))
passwords = [old.get(extension) or secrets.token_urlsafe(24) for extension in extensions]
text = target.read_text(encoding="utf-8")

def replace(key, value):
    global text
    lines = text.splitlines()
    in_section = False
    for index, line in enumerate(lines):
        if line == "[zusaetzliche_nebenstellen]":
            in_section = True
            continue
        if in_section and line.startswith("["):
            break
        if in_section and re.match(rf"^{re.escape(key)}\s*=", line):
            lines[index] = f"{key} = {json.dumps(value)}"
            text = "\n".join(lines) + "\n"
            return
    raise SystemExit(f"ERROR: TOML-Feld fehlt: {key}")

replace("nebenstellen", extensions)
replace("passwoerter", passwords)
temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
temporary.write_text(text, encoding="utf-8")
os.chmod(temporary, 0o640)
os.replace(temporary, target)
PY
}

configure_special_queue(){
  local preset_red="${1-}" red_enabled="" default_red="j"
  local known="" current="" selected="" use_additional="" default_additional="n"

  printf '\nDie priorisierte Sonderqueue klingelt alle normalen Queue-Telefone,\n'
  printf 'bei Nutzung auch das rote Telefon und die hier gewaehlten zusaetzlichen\n'
  printf 'Nebenstellen gleichzeitig. Sie wird\n'
  printf 'verwendet, wenn kein rotes Telefon vorhanden ist oder das rote Telefon\n'
  printf 'besetzt, nicht erreichbar oder nicht angenommen ist.\n'
  if [[ -n "$preset_red" ]]; then
    red_enabled="$preset_red"
  else
    default_red="$(${VENV}/bin/python -c \
      'import sys,tomllib; print("j" if tomllib.load(open(sys.argv[1],"rb"))["ivr"].get("rotes_telefon_aktiv", True) else "n")' \
      "$CONFIG_FILE")"
    ask_yes_no red_enabled \
      "Wird ein rotes Telefon verwendet? Wenn nein, fuehrt Taste 9 direkt zur priorisierten Sonderqueue." \
      "$default_red"
  fi

  known="$(${VENV}/bin/python -c \
    'import sys,tomllib; print(",".join(tomllib.load(open(sys.argv[1],"rb"))["zusaetzliche_nebenstellen"]["nebenstellen"]))' \
    "$CONFIG_FILE")"
  current="$(${VENV}/bin/python -c \
    'import sys,tomllib; d=tomllib.load(open(sys.argv[1],"rb")); known=set(d["zusaetzliche_nebenstellen"]["nebenstellen"]); print(",".join(v for v in d["sonderqueue"].get("zusaetzliche_nebenstellen", []) if v in known))' \
    "$CONFIG_FILE")"
  if [[ -n "$known" ]]; then
    printf 'Verfuegbare zusaetzliche Nebenstellen: %s\n' "$known"
    [[ -z "$current" ]] || default_additional="j"
    ask_yes_no use_additional \
      "Sollen zusaetzliche Nebenstellen in der Sonderqueue mitklingeln?" \
      "$default_additional"
    if [[ "$use_additional" == "y" ]]; then
      ask_value selected \
        "Welche zusaetzlichen Nebenstellen sollen mitklingeln (kommagetrennt)" \
        "${current:-$known}"
    fi
  else
    printf 'Es sind keine zusaetzlichen Nebenstellen konfiguriert.\n'
  fi

  export CONFIG_FILE KZF_RED_ENABLED="$red_enabled" KZF_SPECIAL_MEMBERS="$selected"
  "${VENV}/bin/python" - <<'PY'
# kienzlefon installer special queue updater
# Version: 1.8
# Changelog:
# - 1.8: Sonderqueue-Auswahl unveraendert in den 1.8-Installer uebernommen.
# - 1.7.1: Sonderqueue-Auswahl unveraendert in den 1.7.1-Installer uebernommen.
# - 1.7: Rotes Telefon und zusaetzliche Sonderqueue-Mitglieder atomar aktualisiert.
import json
import os
import re
import tomllib
from pathlib import Path

target = Path(os.environ["CONFIG_FILE"])
with target.open("rb") as handle:
    raw = tomllib.load(handle)
known = [str(value) for value in raw["zusaetzliche_nebenstellen"]["nebenstellen"]]
selected = [
    value.strip()
    for value in os.environ.get("KZF_SPECIAL_MEMBERS", "").split(",")
    if value.strip()
]
if len(selected) != len(set(selected)):
    raise SystemExit("ERROR: Nebenstellen der Sonderqueue duerfen nicht doppelt vorkommen")
unknown = [value for value in selected if value not in known]
if unknown:
    raise SystemExit(
        "ERROR: Unbekannte zusaetzliche Nebenstellen fuer die Sonderqueue: "
        + ", ".join(unknown)
    )
text = target.read_text(encoding="utf-8")

def replace(section, key, value):
    global text
    rendered = "true" if value is True else "false" if value is False else json.dumps(value)
    lines = text.splitlines()
    in_section = False
    for index, line in enumerate(lines):
        if line == f"[{section}]":
            in_section = True
            continue
        if in_section and line.startswith("["):
            break
        if in_section and re.match(rf"^{re.escape(key)}\s*=", line):
            lines[index] = f"{key} = {rendered}"
            text = "\n".join(lines) + "\n"
            return
    raise SystemExit(f"ERROR: TOML-Feld fehlt: [{section}].{key}")

replace("ivr", "rotes_telefon_aktiv", os.environ["KZF_RED_ENABLED"] == "y")
replace("sonderqueue", "zusaetzliche_nebenstellen", selected)
temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
temporary.write_text(text, encoding="utf-8")
os.chmod(temporary, 0o640)
os.replace(temporary, target)
PY
}

migrate_version_1_8(){
  local area="" number=""
  if ! "${VENV}/bin/python" -c 'import sys,tomllib; d=tomllib.load(open(sys.argv[1],"rb")); raise SystemExit(0 if "wahlregeln" in d else 1)' "$CONFIG_FILE"; then
    ask_value area "Ortsvorwahl der Praxis mit fuehrender Null" ""
    [[ "$area" =~ ^0[1-9][0-9]+$ ]] || die "Die Ortsvorwahl ist ungueltig."
    ask_value number "Lokale Praxisrufnummer ohne Vorwahl" ""
    [[ "$number" =~ ^[0-9]+$ ]] || die "Die Praxisrufnummer ist ungueltig."
  fi
  local arguments=(--config "$CONFIG_FILE" --template "$SOURCE_TARGET/config/kienzlefon.toml.example")
  [[ -z "$area" ]] || arguments+=(--area-code "$area")
  [[ -z "$number" ]] || arguments+=(--practice-number "$number")
  "${VENV}/bin/kienzlefon-migration" "${arguments[@]}"
}

collect_configuration(){
  local reuse="" reconfigure_times="" key_source="" suggested_red demo_confirm=""
  if [[ -r "$CONFIG_FILE" ]]; then
    migrate_version_1_8
    ask_yes_no reuse "Vorhandene Kienzlefon-Konfiguration unveraendert wiederverwenden?" "j"
    if [[ "$reuse" == "y" ]]; then
      collect_whisper_models
      update_existing_whisper_models
      ask_yes_no reconfigure_times "Zeitprofile jetzt neu konfigurieren?" "n"
      if [[ "$reconfigure_times" == "y" ]]; then
        collect_time_configuration
        update_existing_times
      fi
      configure_additional_extensions
      configure_special_queue
      configure_demo_anonymization
      return
    fi
  fi

  ask_value KZF_PRACTICE_NAME "Praxisname fuer die Ansagen" "Praxisname"
  ask_value KZF_CHANNEL "Telepraxis-Kanal/SSH-Benutzer" "dahl"
  ask_value KZF_OUTPUT_DIR "Telepraxis-Ausgabeverzeichnis" "/srv/telepraxis/${KZF_CHANNEL}/inbox"
  ask_yes_no KZF_DEMO_MODE \
    "Demo-Modus mit unverschluesselter JSON-Ausgabe verwenden?" "n"
  if [[ "$KZF_DEMO_MODE" == "y" ]]; then
    printf '\nACHTUNG: Im Demo-Modus werden alle regulaeren und Fehler-JSONs unverschluesselt abgelegt.\n'
    printf 'Diesen Modus AUF KEINEN FALL fuer echte Patientendaten verwenden.\n\n'
    ask_yes_no demo_confirm \
      "Demo-Modus trotz unverschluesselter Ausgabe wirklich aktivieren?" "n"
    [[ "$demo_confirm" == "y" ]] || die "Demo-Modus wurde nicht bestaetigt."
    printf 'Die Anonymisierung ersetzt id und telefon in ausgegebenen JSON-Dateien durch #anonymisiert demo#.\n'
    printf 'Audiodateien und in Freitexten genannte Rufnummern bleiben unveraendert.\n'
    ask_yes_no KZF_DEMO_ANONYMIZE \
      "Anrufernummern in den Demo-JSON-Dateien anonymisieren?" "j"
  else
    KZF_DEMO_ANONYMIZE="n"
  fi
  ask_value KZF_TTS_VOICE "Piper-Stimme" "de_DE-thorsten-high"
  ask_value KZF_TTS_LENGTH_SCALE "Piper length_scale (groesser=langsamer)" "1.3"
  [[ "$KZF_TTS_LENGTH_SCALE" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] \
    || die "Piper length_scale muss eine positive Dezimalzahl sein."
  [[ ! "$KZF_TTS_LENGTH_SCALE" =~ ^0*([.]0*)?$ ]] \
    || die "Piper length_scale muss groesser als 0 sein."
  ask_value KZF_TTS_SENTENCE_SILENCE "Piper sentence_silence in Sekunden" "0.8"
  [[ "$KZF_TTS_SENTENCE_SILENCE" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] \
    || die "Piper sentence_silence muss eine nichtnegative Dezimalzahl sein."
  ask_value KZF_ANNOUNCEMENT_PAUSE_MS "Pause zwischen IVR-Ansagen in Millisekunden" "700"
  [[ "$KZF_ANNOUNCEMENT_PAUSE_MS" =~ ^[0-9]+$ ]] \
    || die "Die IVR-Ansagepause muss eine nichtnegative ganze Zahl sein."
  (( KZF_ANNOUNCEMENT_PAUSE_MS <= 10000 )) \
    || die "Die IVR-Ansagepause darf hoechstens 10000 Millisekunden betragen."
  ask_value KZF_CPU_THREADS "Whisper CPU-Threads (0=automatisch)" "0"
  collect_whisper_models
  ask_value KZF_AREA_CODE "Ortsvorwahl der Praxis mit fuehrender Null" ""
  [[ "$KZF_AREA_CODE" =~ ^0[1-9][0-9]+$ ]] || die "Die Ortsvorwahl ist ungueltig."
  ask_value KZF_PRACTICE_NUMBER "Lokale Praxisrufnummer ohne Vorwahl" ""
  [[ "$KZF_PRACTICE_NUMBER" =~ ^[0-9]+$ ]] || die "Die Praxisrufnummer ist ungueltig."

  suggested_red=$((${KFX_PHONE_FIRST_EXTENSION:-201} + ${KFX_PHONE_COUNT:-1}))
  ask_yes_no KZF_RED_ENABLED \
    "Wird ein rotes Telefon verwendet? Wenn nein, fuehrt Taste 9 direkt zur priorisierten Sonderqueue." \
    "j"
  KZF_RED_EXTENSION="$suggested_red"
  KZF_RED_RING_SECONDS="20"
  if [[ "$KZF_RED_ENABLED" == "y" ]]; then
    ask_value KZF_RED_EXTENSION "Nebenstelle fuer das rote Telefon" "$suggested_red"
    [[ "$KZF_RED_EXTENSION" =~ ^[1-9][0-9]+$ ]] || die "Rote Nebenstelle ist ungueltig."
    ask_value KZF_RED_RING_SECONDS "Klingeldauer des roten Telefons in Sekunden" "20"
    [[ "$KZF_RED_RING_SECONDS" =~ ^[1-9][0-9]*$ ]] \
      || die "Die Klingeldauer des roten Telefons muss mindestens 1 Sekunde betragen."
  fi
  ask_value KZF_RED_PRIORITY "Prioritaet der Sonderqueue" "100"
  [[ "$KZF_RED_PRIORITY" =~ ^[1-9][0-9]*$ ]] \
    || die "Die Prioritaet der Sonderqueue muss positiv sein."
  (( KZF_RED_PRIORITY > 10 )) \
    || die "Die Prioritaet der Sonderqueue muss groesser als 10 sein."
  KZF_RED_PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"

  if [[ "$KZF_DEMO_MODE" != "y" ]]; then
    if [[ -r "$PUBLIC_KEY_FILE" ]]; then
      ask_yes_no reuse "Vorhandenen Telepraxis-Public-Key wiederverwenden?" "j"
    else
      reuse="n"
    fi
    if [[ "$reuse" != "y" ]]; then
      ask_value key_source "Pfad zur Telepraxis-Public-Key-PEM-Datei" ""
      [[ -r "$key_source" ]] || die "Public-Key-Datei ist nicht lesbar: ${key_source}"
      openssl pkey -pubin -in "$key_source" -noout >/dev/null
      install -d -m 0755 "$CONFIG_DIR"
      install -m 0644 "$key_source" "$PUBLIC_KEY_FILE"
    fi
  fi

  collect_time_configuration

  collect_sip_line KZF_QUEUE_LINE "die direkte Praxisqueue"
  if [[ "$KZF_RED_ENABLED" == "y" ]]; then
    collect_sip_line KZF_RED_LINE "das rote Telefon"
  else
    KZF_RED_LINE_AKTIV="n"; KZF_RED_LINE_DID=""; KZF_RED_LINE_USER=""
    KZF_RED_LINE_PASSWORD=""; KZF_RED_LINE_DOMAIN=""; KZF_RED_LINE_PROXY=""
    KZF_RED_LINE_EXPIRATION="300"; KZF_RED_LINE_OUTBOUND="n"
    export KZF_RED_LINE_AKTIV KZF_RED_LINE_DID KZF_RED_LINE_USER KZF_RED_LINE_PASSWORD
    export KZF_RED_LINE_DOMAIN KZF_RED_LINE_PROXY KZF_RED_LINE_EXPIRATION KZF_RED_LINE_OUTBOUND
  fi

  if [[ "${KFX_PHONE_SEPARATE_OUTBOUND:-n}" == "y" ]]; then
    KZF_MAIN_ENDPOINT="kfx-phone-out-endpoint"
    KZF_MAIN_NUMBER="${KFX_PHONE_OUT_SIP_NUMBER:-}"
  else
    KZF_MAIN_ENDPOINT="kfx-phone-in-endpoint"
    KZF_MAIN_NUMBER="${KFX_PHONE_IN_SIP_NUMBER:-}"
  fi
  [[ -n "$KZF_MAIN_NUMBER" ]] || die "Kienzlefax-Hauptausgangsnummer fehlt."
  KZF_OUT_COUNTS="${KFX_PHONE_OUT_COUNTS_PROVIDER_LIMIT:-y}"
  KZF_FIRST_EXTENSION="${KFX_PHONE_FIRST_EXTENSION:-201}"
  KZF_EXTENSION_COUNT="${KFX_PHONE_COUNT:-1}"

  export KZF_PRACTICE_NAME KZF_CHANNEL KZF_OUTPUT_DIR KZF_TTS_VOICE KZF_TTS_LENGTH_SCALE
  export KZF_TTS_SENTENCE_SILENCE KZF_ANNOUNCEMENT_PAUSE_MS KZF_CPU_THREADS
  export KZF_MODEL_STANDARD KZF_MODEL_NAMES KZF_MODEL_MEDICATIONS
  export KZF_RED_ENABLED KZF_RED_EXTENSION KZF_RED_RING_SECONDS KZF_RED_PRIORITY KZF_RED_PASSWORD
  export KZF_MAIN_ENDPOINT KZF_MAIN_NUMBER KZF_OUT_COUNTS
  export KZF_FIRST_EXTENSION KZF_EXTENSION_COUNT CONFIG_FILE PUBLIC_KEY_FILE SOURCE_TARGET
  export KZF_AREA_CODE KZF_PRACTICE_NUMBER KZF_DEMO_MODE KZF_DEMO_ANONYMIZE

  install -d -m 0755 "$CONFIG_DIR"
  "${VENV}/bin/python" - <<'PY'
# kienzlefon installer config writer
# Version: 1.9.1
# Changelog:
# - 1.9.1: Konfigurationsschreiber unveraendert fuer Kienzlefon 1.9.1 uebernommen.
# - 1.9: Optionale Demo-Anonymisierung sicher in die TOML-Konfiguration geschrieben.
# - 1.8: Demo-Ausgabemodus und optional leeren Public-Key-Pfad sicher geschrieben.
# - 1.7.1: Konfigurationsschreiber fuer Kienzlefon 1.7.1 aktualisiert.
# - 1.7: Nutzung des roten Telefons sicher in TOML geschrieben.
# - 1.6.2: Konfigurationsschreiber unveraendert fuer Patchrelease uebernommen.
# - 1.6.1: Konfigurationsschreiber unveraendert fuer Patchrelease uebernommen.
# - 1.6: Drei Whisper-Modellzuordnungen sicher in TOML geschrieben.
# - 1.5: Neue Audioziele aus der 1.5-Vorlage uebernommen.
# - 1.4: PIN-Felder aus der geschriebenen TOML-Konfiguration entfernt.
# - 1.3: Ansagen-IVR- und Wahlregelwerte sicher in TOML geschrieben.
# - 1.2: Geschriebene Zeitprofile werden aus TOML zurueckgelesen und verglichen.
# - 1.1: Neue TTS-, IVR- und Notfallparameter sicher in TOML geschrieben.
# - 1.0: Erstfassung der sicheren TOML-Erzeugung.
import json
import os
import re
import tomllib
from pathlib import Path

template = Path(os.environ["SOURCE_TARGET"]) / "config/kienzlefon.toml.example"
target = Path(os.environ["CONFIG_FILE"])
text = template.read_text(encoding="utf-8")

def toml(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False)

def set_value(section, key, value):
    global text
    lines = text.splitlines()
    in_section = False
    for index, line in enumerate(lines):
        if line == f"[{section}]":
            in_section = True
            continue
        if in_section and line.startswith("["):
            break
        if in_section and re.match(rf"^{re.escape(key)}\s*=", line):
            lines[index] = f"{key} = {toml(value)}"
            text = "\n".join(lines) + "\n"
            return
    raise SystemExit(f"ERROR: TOML-Feld nicht gefunden: [{section}].{key}")

def schedule(prefix):
    result = {}
    for day in ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"):
        raw = os.environ.get(f"{prefix}_{day.upper()}", "").replace(" ", "")
        result[day] = [value for value in raw.split(",") if value]
    return result

set_value("praxis", "name", os.environ["KZF_PRACTICE_NAME"])
set_value("ivr", "rotes_telefon_aktiv", os.environ["KZF_RED_ENABLED"] == "y")
set_value("ivr", "rote_nebenstelle", os.environ["KZF_RED_EXTENSION"])
set_value("ivr", "ansage_pause_ms", int(os.environ["KZF_ANNOUNCEMENT_PAUSE_MS"]))
set_value(
    "ivr",
    "rotes_telefon_klingeldauer_sekunden",
    int(os.environ["KZF_RED_RING_SECONDS"]),
)
set_value("ivr", "rotes_telefon_queue_prioritaet", int(os.environ["KZF_RED_PRIORITY"]))
set_value("sonderqueue", "gewicht", int(os.environ["KZF_RED_PRIORITY"]))
set_value("whisper", "cpu_threads", int(os.environ["KZF_CPU_THREADS"]))
set_value("whisper", "modell_standard", os.environ["KZF_MODEL_STANDARD"])
set_value("whisper", "modell_namen", os.environ["KZF_MODEL_NAMES"])
set_value("whisper", "modell_medikamente", os.environ["KZF_MODEL_MEDICATIONS"])
set_value("telepraxis", "kanal", os.environ["KZF_CHANNEL"])
set_value("telepraxis", "ausgabeverzeichnis", os.environ["KZF_OUTPUT_DIR"])
demo_mode = os.environ["KZF_DEMO_MODE"] == "y"
set_value("telepraxis", "demo", demo_mode)
set_value(
    "telepraxis",
    "anrufernummern_anonymisieren",
    demo_mode and os.environ["KZF_DEMO_ANONYMIZE"] == "y",
)
set_value("telepraxis", "public_key", "" if demo_mode else os.environ["PUBLIC_KEY_FILE"])
set_value("tts", "stimme", os.environ["KZF_TTS_VOICE"])
set_value("tts", "length_scale", float(os.environ["KZF_TTS_LENGTH_SCALE"]))
set_value("tts", "sentence_silence", float(os.environ["KZF_TTS_SENTENCE_SILENCE"]))
set_value("asterisk", "rotes_telefon_passwort", os.environ["KZF_RED_PASSWORD"])
set_value("asterisk", "hauptausgang_endpoint", os.environ["KZF_MAIN_ENDPOINT"])
set_value("asterisk", "hauptausgang_nummer", os.environ["KZF_MAIN_NUMBER"])
set_value("asterisk", "ausgehend_zaehlt_kanalgrenze", os.environ["KZF_OUT_COUNTS"] == "y")
set_value("asterisk", "erste_queue_nebenstelle", int(os.environ["KZF_FIRST_EXTENSION"]))
set_value("asterisk", "queue_nebenstellen_anzahl", int(os.environ["KZF_EXTENSION_COUNT"]))
set_value("wahlregeln", "ortsvorwahl", os.environ.get("KZF_AREA_CODE", "02331"))
set_value("wahlregeln", "praxisrufnummer", os.environ.get("KZF_PRACTICE_NUMBER", "123456"))

for section, prefix in (
    ("oeffnungszeiten", "KZF_OPEN"),
    ("telefonzeiten", "KZF_PHONE"),
    ("apothekenzeiten", "KZF_PHARMACY"),
    ("fachstellenzeiten", "KZF_SPECIALIST"),
):
    for key, value in schedule(prefix).items():
        set_value(section, key, value)

for section, prefix in (
    ("sip_direkte_queue", "KZF_QUEUE_LINE"),
    ("sip_rotes_telefon", "KZF_RED_LINE"),
):
    set_value(section, "aktiv", os.environ[f"{prefix}_AKTIV"] == "y")
    set_value(section, "rufnummer", os.environ[f"{prefix}_DID"])
    set_value(section, "benutzer", os.environ[f"{prefix}_USER"])
    set_value(section, "passwort", os.environ[f"{prefix}_PASSWORD"])
    set_value(section, "domain", os.environ[f"{prefix}_DOMAIN"])
    set_value(section, "outbound_proxy", os.environ[f"{prefix}_PROXY"])
    set_value(section, "expiration", int(os.environ[f"{prefix}_EXPIRATION"]))
    set_value(section, "ausgehend_verwenden", os.environ[f"{prefix}_OUTBOUND"] == "y")

temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
temporary.write_text(text, encoding="utf-8")
os.chmod(temporary, 0o640)
os.replace(temporary, target)

with target.open("rb") as handle:
    stored = tomllib.load(handle)
for section, prefix in (
    ("oeffnungszeiten", "KZF_OPEN"),
    ("telefonzeiten", "KZF_PHONE"),
    ("apothekenzeiten", "KZF_PHARMACY"),
    ("fachstellenzeiten", "KZF_SPECIALIST"),
):
    expected = schedule(prefix)
    actual = {day: stored[section][day] for day in expected}
    if actual != expected:
        raise SystemExit(
            f"ERROR: Zeitprofil [{section}] wurde nicht korrekt in {target} gespeichert"
        )
PY
#  chown root:asterisk "$CONFIG_FILE"
  chown root:root "$CONFIG_FILE"
  chmod 0640 "$CONFIG_FILE"
  configure_additional_extensions
  configure_special_queue "$KZF_RED_ENABLED"
}

#prepare_directories(){
#  local output channel spool models voices uploads masters prompts
#  output="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["telepraxis"]["ausgabeverzeichnis"])' "$CONFIG_FILE")"
#  channel="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["telepraxis"]["kanal"])' "$CONFIG_FILE")"
#  spool="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["pfade"]["spool"])' "$CONFIG_FILE")"
#  models="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["whisper"]["modellverzeichnis"])' "$CONFIG_FILE")"
#  voices="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["tts"]["stimmenverzeichnis"])' "$CONFIG_FILE")"
#  uploads="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["tts"]["uploadverzeichnis"])' "$CONFIG_FILE")"
#  masters="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["pfade"]["ansagen_master"])' "$CONFIG_FILE")"
#  prompts="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["pfade"]["ansagen"])' "$CONFIG_FILE")"
#  install -d -o asterisk -g asterisk -m 2770 "$spool"
#  for state in recording queue processing ready error; do
#   install -d -o asterisk -g asterisk -m 2770 "${spool}/${state}"
#  done
#  install -d -o asterisk -g asterisk -m 0750 /var/lib/kienzlefon "$models" "$voices"
#  install -d -o root -g asterisk -m 2770 "$uploads"
#  install -d -o asterisk -g asterisk -m 0755 "$masters" "$prompts"
#  if [[ ! -d "$output" ]]; then
#    install -d -o asterisk -g asterisk -m 2770 "$output"
#  fi
#  setfacl -m u:asterisk:rwx "$output"
#  setfacl -m d:u:asterisk:rwx "$output"
#  if getent passwd "$channel" >/dev/null; then
#    setfacl -m "u:${channel}:rwx" "$output"
#    setfacl -m "d:u:${channel}:rwx" "$output"
#  fi
#  runuser -u asterisk -- test -w "$output" || die "Benutzer asterisk kann nicht nach ${output} schreiben."
#}



prepare_directories() {
  local output channel spool models voices uploads masters prompts
  local asterisk_user asterisk_group
  local state

  # Tatsächlichen Asterisk-Benutzer anhand des laufenden Prozesses ermitteln.
  # Auf deinem System ergibt das root:root.
  asterisk_user="$(
    ps -eo user=,comm= |
      awk '$2 == "asterisk" { print $1; exit }'
  )"
  asterisk_user="${asterisk_user:-root}"

  if ! getent passwd "$asterisk_user" >/dev/null 2>&1; then
    die "Ermittelter Asterisk-Benutzer '${asterisk_user}' existiert nicht."
  fi

  asterisk_group="$(id -gn "$asterisk_user")"

  output="$(
    "${VENV}/bin/python" -c \
      'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["telepraxis"]["ausgabeverzeichnis"])' \
      "$CONFIG_FILE"
  )"

  channel="$(
    "${VENV}/bin/python" -c \
      'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["telepraxis"]["kanal"])' \
      "$CONFIG_FILE"
  )"

  spool="$(
    "${VENV}/bin/python" -c \
      'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["pfade"]["spool"])' \
      "$CONFIG_FILE"
  )"

  models="$(
    "${VENV}/bin/python" -c \
      'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["whisper"]["modellverzeichnis"])' \
      "$CONFIG_FILE"
  )"

  voices="$(
    "${VENV}/bin/python" -c \
      'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["tts"]["stimmenverzeichnis"])' \
      "$CONFIG_FILE"
  )"

  uploads="$(
    "${VENV}/bin/python" -c \
      'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["tts"]["uploadverzeichnis"])' \
      "$CONFIG_FILE"
  )"

  masters="$(
    "${VENV}/bin/python" -c \
      'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["pfade"]["ansagen_master"])' \
      "$CONFIG_FILE"
  )"

  prompts="$(
    "${VENV}/bin/python" -c \
      'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["pfade"]["ansagen"])' \
      "$CONFIG_FILE"
  )"

  install -d \
    -o "$asterisk_user" \
    -g "$asterisk_group" \
    -m 2770 \
    "$spool"

  for state in recording queue processing ready error; do
    install -d \
      -o "$asterisk_user" \
      -g "$asterisk_group" \
      -m 2770 \
      "${spool}/${state}"
  done

  install -d \
    -o "$asterisk_user" \
    -g "$asterisk_group" \
    -m 0750 \
    /var/lib/kienzlefon \
    "$models" \
    "$voices"

  install -d \
    -o root \
    -g "$asterisk_group" \
    -m 2770 \
    "$uploads" \
    "$uploads/kandidaten" \
    "$uploads/inaktiv"

  install -d \
    -o "$asterisk_user" \
    -g "$asterisk_group" \
    -m 0755 \
    "$masters" \
    "$prompts"

  if [[ ! -d "$output" ]]; then
    install -d \
      -o "$asterisk_user" \
      -g "$asterisk_group" \
      -m 2770 \
      "$output"
  fi

  # Der Asterisk-Benutzer ist Eigentümer. Eine zusätzliche ACL für root
  # wäre auf deinem System redundant, schadet aber auch nicht. Daher nur
  # hinzufügen, wenn Asterisk nicht ohnehin als root läuft.
  if [[ "$asterisk_user" != "root" ]]; then
    setfacl -m "u:${asterisk_user}:rwx" "$output"
    setfacl -m "d:u:${asterisk_user}:rwx" "$output"
  fi

  if getent passwd "$channel" >/dev/null 2>&1; then
    setfacl -m "u:${channel}:rwx" "$output"
    setfacl -m "d:u:${channel}:rwx" "$output"
  else
    printf 'WARNUNG: Konfigurierter Kanal-Benutzer %q existiert nicht.\n' \
      "$channel" >&2
  fi

  runuser -u "$asterisk_user" -- test -w "$output" ||
    die "Benutzer ${asterisk_user} kann nicht nach ${output} schreiben."
}




install_systemd_unit(){
  local output spool output_gid output_group group_record
  output="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["telepraxis"]["ausgabeverzeichnis"])' "$CONFIG_FILE")"
  spool="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["pfade"]["spool"])' "$CONFIG_FILE")"
  output_gid="$(stat -c '%g' -- "$output")"
  group_record="$(getent group "$output_gid")" \
    || die "Gruppe ${output_gid} des Telepraxis-Ausgabeverzeichnisses ist nicht aufloesbar."
  output_group="${group_record%%:*}"
  cat >/etc/systemd/system/kienzlefon-worker.service <<EOF
# kienzlefon-worker.service
# Version: 1.9.1
# Changelog:
# - 1.9.1: Diensteinheit fuer den nach korrigierter Formatpruefung gestarteten Worker aktualisiert.
# - 1.9: Diensteinheit unveraendert fuer Kienzlefon 1.9 uebernommen.
# - 1.8.3: Diensteinheit fuer Kienzlefon 1.8.3 uebernommen.
# - 1.8.2: Diensteinheit fuer Kienzlefon 1.8.2 uebernommen.
# - 1.8.1: Primaergruppe aus dem Ausgabeverzeichnis und UMask 0007 gesetzt.
# - 1.8: Diensteinheit fuer Kienzlefon 1.8 aktualisiert.
# - 1.7.1: Diensteinheit fuer Kienzlefon 1.7.1 aktualisiert.
# - 1.7: Diensteinheit fuer Kienzlefon 1.7 aktualisiert.
# - 1.6.2: Diensteinheit fuer Kienzlefon 1.6.2 aktualisiert.
# - 1.6.1: Diensteinheit fuer Kienzlefon 1.6.1 aktualisiert.
# - 1.6: Diensteinheit fuer den Mehrmodell-Worker aktualisiert.
# - 1.5: Diensteinheit fuer Kienzlefon 1.5 aktualisiert.
# - 1.4: Diensteinheit fuer Kienzlefon 1.4 aktualisiert.
# - 1.3: Diensteinheit fuer Kienzlefon 1.3 aktualisiert.
# - 1.2: Diensteinheit fuer Kienzlefon 1.2 aktualisiert.
# - 1.1: Worker-Diensteinheit fuer Kienzlefon 1.1 aktualisiert.
# - 1.0: Dauerhafter CPU-Worker mit automatischem Wiederanlauf.

[Unit]
Description=Kienzlefon Whisper Worker
After=network-online.target asterisk.service
Wants=network-online.target
Requires=asterisk.service

[Service]
Type=simple
User=root
Group=${output_group}
UMask=0007
Environment=KIENZLEFON_CONFIG=${CONFIG_FILE}
ExecStart=${VENV}/bin/kienzlefon-worker --config ${CONFIG_FILE}
Restart=always
RestartSec=3
Nice=10
CPUWeight=20
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=${spool} /run/kienzlefon ${output}
RuntimeDirectory=kienzlefon
RuntimeDirectoryMode=0750

[Install]
WantedBy=multi-user.target
EOF
  chmod 0644 /etc/systemd/system/kienzlefon-worker.service
  systemctl daemon-reload
  systemctl enable kienzlefon-worker.service
}

install_models_and_prompts(){
  local voice voices
  voice="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["tts"]["stimme"])' "$CONFIG_FILE")"
  voices="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["tts"]["stimmenverzeichnis"])' "$CONFIG_FILE")"
#  runuser -u asterisk -- "${VENV}/bin/python" -m piper.download_voices \
#    --data-dir "$voices" "$voice"
#  runuser -u asterisk -- "${VENV}/bin/kienzlefon-modell-laden" --config "$CONFIG_FILE"
#  runuser -u asterisk -- "${VENV}/bin/kienzlefon-ansagen" --config "$CONFIG_FILE" --all
  runuser -u root -- "${VENV}/bin/python" -m piper.download_voices \
    --data-dir "$voices" "$voice"
  runuser -u root -- "${VENV}/bin/kienzlefon-modell-laden" --config "$CONFIG_FILE"
  runuser -u root -- "${VENV}/bin/kienzlefon-ansagen" --config "$CONFIG_FILE" --all
}

configure_asterisk(){
  local red_enabled red_extension special_queue
  "${VENV}/bin/kienzlefon-asterisk" --config "$CONFIG_FILE"
  asterisk -rx "pjsip reload"
  asterisk -rx "dialplan reload"
  asterisk -rx "module reload app_queue.so" || true
  asterisk_supports_format wav16 \
    || die "Asterisk stellt das erforderliche Aufnahmeformat wav16 nicht bereit."
  red_enabled="$(${VENV}/bin/python -c 'import sys,tomllib; print("y" if tomllib.load(open(sys.argv[1],"rb"))["ivr"]["rotes_telefon_aktiv"] else "n")' "$CONFIG_FILE")"
  red_extension="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["ivr"]["rote_nebenstelle"])' "$CONFIG_FILE")"
  special_queue="$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["sonderqueue"]["name"])' "$CONFIG_FILE")"
  if [[ "$red_enabled" == "y" ]]; then
    asterisk -rx "pjsip show endpoint ${red_extension}"
  fi
  asterisk -rx "queue show praxis"
  asterisk -rx "queue show ${special_queue}"
}

start_and_verify(){
  systemctl restart kienzlefon-worker.service
  local waited
  for (( waited=0; waited<300; waited+=5 )); do
    if "${VENV}/bin/kienzlefon-status" --config "$CONFIG_FILE" >/dev/null 2>&1; then
      log "Whisper-Worker ist bereit."
      return
    fi
    sleep 5
  done
  systemctl status kienzlefon-worker.service --no-pager -l || true
  die "Whisper-Worker ist nach 300 Sekunden nicht bereit."
}

main(){
  local install_now="" demo_mode=""
  printf 'Kienzlefon Installer\nVersion: %s\n\n' "$VERSION"
  ask_yes_no install_now "Kienzlefon jetzt installieren?" "n"
  if [[ "$install_now" != "y" ]]; then
    trap - ERR
    printf 'Installation nicht gestartet.\n'
    return 0
  fi
  require_root
  sep "Systempakete installieren"
  install_packages
  sep "Kienzlefax-Grundlage pruefen"
  ensure_kienzlefax
  sep "Kienzlefon-Quellstand vorbereiten"
  prepare_source
  copy_and_install_project
  sep "Konfiguration erfassen"
  collect_configuration
  "${VENV}/bin/kienzlefon-config" --config "$CONFIG_FILE"
  demo_mode="$(${VENV}/bin/python -c 'import sys,tomllib; print("y" if tomllib.load(open(sys.argv[1],"rb"))["telepraxis"].get("demo", False) else "n")' "$CONFIG_FILE")"
  if [[ "$demo_mode" == "y" ]]; then
    printf 'ACHTUNG: Demo-Modus aktiv; Telepraxis-Dateien werden unverschluesselt abgelegt.\n'
    printf 'Auf KEINEN FALL echte Patientendaten verwenden.\n'
  else
    openssl pkey -pubin -in "$PUBLIC_KEY_FILE" -noout >/dev/null
  fi
  sep "Verzeichnisse und Rechte"
  prepare_directories
  sep "Modelle und Ansagen"
  install_models_and_prompts
  sep "Asterisk integrieren"
  configure_asterisk
  sep "Whisper-Worker installieren"
  install_systemd_unit
  start_and_verify
  trap - ERR
  sep "Kienzlefon 1.9.1 ist installiert"
  printf 'Konfiguration: %s\n' "$CONFIG_FILE"
  printf 'Ansagen neu erzeugen: sudo kienzlefon-ansagen\n'
  printf 'Status: sudo kienzlefon-status\n'
  "${VENV}/bin/python" - "$CONFIG_FILE" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    values = tomllib.load(handle)
if values["ivr"]["rotes_telefon_aktiv"]:
    print(f'Rote Nebenstelle: {values["ivr"]["rote_nebenstelle"]}')
    print(f'Passwort rote Nebenstelle: {values["asterisk"]["rotes_telefon_passwort"]}')
else:
    print("Rotes Telefon: nicht verwendet; Taste 9 fuehrt direkt zur Sonderqueue")
print(f'Sonderqueue: {values["sonderqueue"]["name"]}')
PY
  printf 'Internes Ansagen-IVR: 777\n'
  "${VENV}/bin/python" - "$CONFIG_FILE" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    values = tomllib.load(handle)["zusaetzliche_nebenstellen"]
for extension, password in zip(values["nebenstellen"], values["passwoerter"], strict=True):
    print(f"Zusaetzliche Nebenstelle {extension}: Passwort {password}")
PY
  printf 'Interner SIP-Registrar: %s:%s\n' "${KFX_PHONE_BIND_IP:-unbekannt}" "${KFX_PHONE_INTERNAL_PORT:-5060}"
  printf 'Telepraxis-Ausgabe: %s\n' "$(${VENV}/bin/python -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["telepraxis"]["ausgabeverzeichnis"])' "$CONFIG_FILE")"
  if [[ "$demo_mode" == "y" ]]; then
    printf 'Telepraxis-Modus: DEMO, unverschluesselte JSON-Ausgabe; keine echten Patientendaten verwenden!\n'
    "${VENV}/bin/python" - "$CONFIG_FILE" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    anonymous = tomllib.load(handle)["telepraxis"].get("anrufernummern_anonymisieren", False)
print("Demo-Anrufernummern: #anonymisiert demo#" if anonymous else "Demo-Anrufernummern: unveraendert")
PY
  else
    printf 'Telepraxis-Modus: Produktiv, verschluesselte JSON-Ausgabe\n'
  fi
}

main "$@"
