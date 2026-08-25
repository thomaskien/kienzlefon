#!/bin/bash
# install-kienzlefon-qwen3-tts-v1.5.sh
#
# Cross-platform standalone installer for the native Qwen3-TTS 0.6B
# CustomVoice service and one-shot announcement generator used by the
# Kienzlefon project.
#
# Supported targets:
#   - macOS on Apple Silicon (arm64): CPU + Metal build
#   - Ubuntu Linux on x86_64:        CPU + NVIDIA CUDA build
#   - Debian 12/13 on x86_64:        offline-only CPU + optional NVIDIA CUDA
#
# Runtime defaults:
#   macOS Apple Silicon: CPU / INT4 / 4 threads / batch size 1 / TCP 8182
#   Ubuntu + NVIDIA CUDA: CUDA / INT4 / batch size 1 / TCP 8182
#   Offline-only:        pause detected ASR units, then CUDA when usable,
#                        otherwise CPU / INT4 / no TCP port
#
# On Ubuntu, CUDA is the normal service backend whenever this CUDA-enabled
# installer is used. CPU remains available as a benchmark/fallback backend.
#
# Scope:
#   - installs/builds https://github.com/gabriele-mastrapasqua/qwen3-tts
#   - downloads ONLY Qwen3-TTS-12Hz-0.6B-CustomVoice
#   - keeps model data separate from source code
#   - installs a persistent HTTP service (launchd or systemd)
#   - tests German/Ryan WAV and streaming PCM endpoints
#   - installs healthcheck / benchmark / control commands
#   - benchmarks CPU INT4/INT8 plus Metal INT4/INT8 or CUDA INT4/INT8
#   - optionally installs a non-resident one-shot generator without a service
#
# Explicitly NOT in scope:
#   - Piper selection/fallback
#   - Whisper / llama.cpp changes
#   - Kienzlefon call routing
#   - automatic git updates or commit pinning
#   - Docker, Python or PyTorch TTS runtimes
#   - installing/upgrading NVIDIA drivers or the CUDA Toolkit
#
# Ubuntu CUDA policy:
#   The installer installs ordinary build dependencies (OpenBLAS, compiler, etc.)
#   through apt, but NEVER modifies NVIDIA drivers or CUDA. A working nvidia-smi
#   and nvcc are required on Ubuntu so the delivered binary really has CUDA
#   support. CUDA_HOME can be overridden with --cuda-home.
#
# The upstream HTTP server currently binds to all IPv4 interfaces. This installer
# intentionally does not patch that behaviour.

set -Eeuo pipefail
IFS=$'\n\t'
umask 022

SCRIPT_NAME="$(basename "$0")"
VERSION="1.5"

REPO_URL="https://github.com/gabriele-mastrapasqua/qwen3-tts.git"
BASE_DIR="/opt/kienzlefon/qwen3-tts"
SRC_DIR="${BASE_DIR}/src"
BIN_DIR="${BASE_DIR}/bin"
TOOLS_DIR="${BASE_DIR}/tools"
MODEL_BASE="/opt/kienzlefon/models"
MODEL_DIR="${MODEL_BASE}/qwen3-tts-0.6b-customvoice"
LOG_DIR="/var/log/kienzlefon/qwen3-tts"
ETC_DIR="/etc/kienzlefon"
STATE_DIR="/var/lib/kienzlefon/qwen3-tts"

BINARY="${BIN_DIR}/qwen_tts"
CPU_BINARY="${BIN_DIR}/qwen_tts-cpu"
CUDA_BINARY="${BIN_DIR}/qwen_tts-cuda"
TTFA_HELPER="${BIN_DIR}/kienzlefon-qwen3-tts-ttfa"
HEALTH_CMD="/usr/local/bin/kienzlefon-qwen3-tts-healthcheck"
BENCH_CMD="/usr/local/bin/kienzlefon-qwen3-tts-benchmark"
CTL_CMD="/usr/local/bin/kienzlefon-qwen3-tts-ctl"
GENERATE_CMD="/usr/local/bin/kienzlefon-qwen3-tts-generate"
ENV_FILE="${ETC_DIR}/qwen3-tts.env"
OFFLINE_ENV_FILE="${ETC_DIR}/qwen3-tts-offline.env"
GENERATE_LOCK="${STATE_DIR}/generate.lock"

LABEL="com.kienzlefon.qwen3-tts"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"
SYSTEMD_UNIT_NAME="kienzlefon-qwen3-tts.service"
SYSTEMD_UNIT="/etc/systemd/system/${SYSTEMD_UNIT_NAME}"

PORT=8182
THREADS=4
THREADS_EXPLICIT=0
BATCH_SIZE=1
RUN_BENCHMARK=1
MIN_RAM_GIB=8
MIN_GENERATE_AVAILABLE_KIB=$((5 * 1024 * 1024))
STOP_TIMEOUT_SECONDS=60
READINESS_TIMEOUT_SECONDS=300
CUDA_HOME_OVERRIDE=""
UNINSTALL=0
KEEP_MODEL=0
OFFLINE_ONLY=0

PLATFORM=""
ARCH=""
OS_VERSION=""
SERVICE_KIND=""
CUDA_HOME=""
CUDA_LIBDIR=""
CUDA_ARCH=""
CUDA_GPU_NAME=""
CUDA_AVAILABLE=0
DISTRO_ID=""
PAUSE_UNITS=()

MAINTENANCE_MARKER="/run/kienzlefon/asr-maintenance"
CLASSIC_WORKER_UNIT="kienzlefon-worker.service"
CLASSIC_STATUS_CMD="/opt/kienzlefon/venv/bin/kienzlefon-status"
CLASSIC_STATUS_PYTHON="/opt/kienzlefon/venv/bin/python"
CLASSIC_CONFIG="/etc/kienzlefon/kienzlefon.toml"
CLASSIC_HEARTBEAT="/run/kienzlefon/whisper-health.json"

STANDARD_MODE="CPU INT4"  # set to CUDA INT4 on Ubuntu after platform detection
MODEL_HF_ID="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
TEST_TEXT="Guten Tag. Dies ist ein reproduzierbarer Test der natürlichen Sprachausgabe für Kienzlefon."
TEST_SEED=42

ORIGINAL_ARGS=("$@")
CLEANUP_STAGE=""
CLEANUP_TMP=""

usage() {
  cat <<USAGE
Usage: sudo ./${SCRIPT_NAME} [options]

Supported platforms:
  macOS Apple Silicon arm64     -> CPU + Metal
  Ubuntu Linux x86_64          -> CPU + NVIDIA CUDA
  Debian 12/13 x86_64          -> offline-only CPU + optional NVIDIA CUDA

Debian offline-only uses 2 CPU threads unless --threads is supplied.

Options:
  --port N             HTTP port; service mode only (default: ${PORT})
  --threads N          CPU worker threads (default: ${THREADS})
  --batch-size N       Server request batch size; service mode only (default: ${BATCH_SIZE})
  --cuda-home PATH     Linux only: explicit CUDA Toolkit prefix
  --skip-benchmark     Service mode only: install + healthcheck without benchmark
  --offline-only       Install only the non-resident local WAV generator;
                       create no service, autostart, HTTP server, or listener
  --uninstall          Completely remove this Qwen3-TTS installation
  --keep-model         With --uninstall: keep the downloaded 0.6B model
  -h, --help           Show this help

Default service mode:
  macOS Apple Silicon : CPU / INT4 / ${THREADS} threads / batch size ${BATCH_SIZE}
  Ubuntu + NVIDIA CUDA: CUDA / INT4 / batch size ${BATCH_SIZE}

CPU remains available on Ubuntu for comparison/fallback. Ubuntu requires an
already working NVIDIA driver (nvidia-smi) and CUDA Toolkit (nvcc). This installer
does not install or change either one.

Offline-only mode:
  sudo ./${SCRIPT_NAME} --offline-only

The offline generator always includes a CPU-only binary. On Ubuntu it additionally
uses CUDA when a working NVIDIA driver, CUDA Toolkit, and CUDA self-test are
available. The same optional CUDA preference applies to Debian. A pure offline-only
installation never creates a Qwen service and never opens port ${PORT}. During each
generation it temporarily stops only detected, positively listed Kienzlefon ASR
units, then restores exactly the units that were active before. Source, build
dependencies, and model are installed normally and may require network access.

Installation validation performs one real one-shot generation. Low currently
available RAM does not block installation before ASR units are stopped; the hard
5 GiB MemAvailable check runs only immediately before Qwen generation.

Uninstall:
  sudo ./${SCRIPT_NAME} --uninstall
  sudo ./${SCRIPT_NAME} --uninstall --keep-model

Uninstall never removes NVIDIA drivers, CUDA, Xcode tools, compilers, apt packages,
or other shared system dependencies.
USAGE
}

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }

cleanup_transient() {
  set +e
  if [[ -n "${CLEANUP_STAGE:-}" && -d "${CLEANUP_STAGE}" ]]; then
    case "$CLEANUP_STAGE" in
      "${MODEL_BASE}"/.qwen3-tts-0.6b-customvoice.download.*) rm -rf -- "$CLEANUP_STAGE" ;;
    esac
  fi
  if [[ -n "${CLEANUP_TMP:-}" && -d "${CLEANUP_TMP}" ]]; then
    case "$CLEANUP_TMP" in /tmp/kienzlefon-qwen-*) rm -rf -- "$CLEANUP_TMP" ;; esac
  fi
  set -e
}

die() {
  local msg="$*"
  cleanup_transient
  printf '[ERROR] %s\n' "$msg" >&2
  exit 1
}

on_error() {
  local rc=$?
  local line=${1:-?}
  cleanup_transient
  set +e
  printf '\n[ERROR] Installation failed at line %s (exit %s).\n' "$line" "$rc" >&2
  if (( OFFLINE_ONLY == 1 )); then
    printf '[ERROR] Offline-only mode created no service log containing the TTS input text.\n' >&2
  else
    printf '[ERROR] Service logs are under: %s\n' "$LOG_DIR" >&2
  fi
  exit "$rc"
}
trap 'on_error $LINENO' ERR

is_uint() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      [[ $# -ge 2 ]] || die "--port requires a value"
      PORT="$2"; shift 2 ;;
    --threads)
      [[ $# -ge 2 ]] || die "--threads requires a value"
      THREADS="$2"; THREADS_EXPLICIT=1; shift 2 ;;
    --batch-size)
      [[ $# -ge 2 ]] || die "--batch-size requires a value"
      BATCH_SIZE="$2"; shift 2 ;;
    --cuda-home)
      [[ $# -ge 2 ]] || die "--cuda-home requires a value"
      CUDA_HOME_OVERRIDE="$2"; shift 2 ;;
    --skip-benchmark)
      RUN_BENCHMARK=0; shift ;;
    --offline-only)
      OFFLINE_ONLY=1; shift ;;
    --uninstall)
      UNINSTALL=1; shift ;;
    --keep-model)
      KEEP_MODEL=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      die "Unknown option: $1" ;;
  esac
done

if (( KEEP_MODEL == 1 && UNINSTALL == 0 )); then
  die "--keep-model is only valid together with --uninstall"
fi

if (( OFFLINE_ONLY == 1 && UNINSTALL == 1 )); then
  die "--offline-only cannot be combined with --uninstall"
fi

is_uint "$PORT" || die "Port must be an integer"
is_uint "$THREADS" || die "Threads must be an integer"
is_uint "$BATCH_SIZE" || die "Batch size must be an integer"
(( PORT >= 1 && PORT <= 65535 )) || die "Port must be between 1 and 65535"
(( THREADS >= 1 && THREADS <= 64 )) || die "Threads must be between 1 and 64"
(( BATCH_SIZE >= 1 && BATCH_SIZE <= 64 )) || die "Batch size must be between 1 and 64"

# Re-exec as root because installation uses system locations.
if [[ "${EUID}" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || die "This installer requires root privileges and sudo was not found."
  log "Root privileges are required; invoking sudo."
  exec sudo -- "$0" "${ORIGINAL_ARGS[@]}"
fi

remove_file_if_present() {
  local p="$1"
  if [[ -e "$p" || -L "$p" ]]; then
    rm -f -- "$p"
    log "Removed: $p"
  fi
}

remove_dir_if_present() {
  local p="$1"
  if [[ -d "$p" ]]; then
    rm -rf -- "$p"
    log "Removed: $p"
  fi
}

uninstall_service_only() {
  local kernel
  kernel="$(uname -s)"
  case "$kernel" in
    Darwin)
      if command -v launchctl >/dev/null 2>&1; then
        if launchctl print "system/${LABEL}" >/dev/null 2>&1; then
          log "Stopping launchd service ${LABEL}..."
          launchctl bootout "system/${LABEL}" >/dev/null 2>&1 || true
          local i
          for ((i=0; i<50; i++)); do
            launchctl print "system/${LABEL}" >/dev/null 2>&1 || break
            sleep 0.2
          done
        fi
      fi
      remove_file_if_present "$PLIST"
      ;;
    Linux)
      if command -v systemctl >/dev/null 2>&1; then
        log "Stopping/disabling systemd service ${SYSTEMD_UNIT_NAME} if present..."
        systemctl stop "$SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true
        systemctl disable "$SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true
      fi
      remove_file_if_present "$SYSTEMD_UNIT"
      if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload >/dev/null 2>&1 || true
        systemctl reset-failed "$SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true
      fi
      ;;
    *)
      warn "Unknown OS '$kernel'; removing files but no service manager action can be guaranteed."
      remove_file_if_present "$PLIST"
      remove_file_if_present "$SYSTEMD_UNIT"
      ;;
  esac
}

uninstall_all() {
  log "Starting Kienzlefon Qwen3-TTS uninstall v${VERSION}"

  uninstall_service_only

  remove_file_if_present "$HEALTH_CMD"
  remove_file_if_present "$BENCH_CMD"
  remove_file_if_present "$CTL_CMD"
  remove_file_if_present "$GENERATE_CMD"
  remove_file_if_present "$ENV_FILE"
  remove_file_if_present "$OFFLINE_ENV_FILE"

  # Everything below BASE_DIR belongs solely to this installer.
  remove_dir_if_present "$BASE_DIR"
  remove_dir_if_present "$STATE_DIR"
  remove_dir_if_present "$LOG_DIR"

  # Remove interrupted/staged model downloads created by this installer.
  if [[ -d "$MODEL_BASE" ]]; then
    local p
    shopt -s nullglob
    for p in \
      "${MODEL_BASE}"/.qwen3-tts-0.6b-customvoice.download.* \
      "${MODEL_DIR}".incomplete.*; do
      [[ -e "$p" ]] || continue
      rm -rf -- "$p"
      log "Removed: $p"
    done
    shopt -u nullglob
  fi

  if (( KEEP_MODEL == 1 )); then
    if [[ -d "$MODEL_DIR" ]]; then
      log "Keeping model by request: $MODEL_DIR"
    else
      log "No model directory present to keep."
    fi
  else
    remove_dir_if_present "$MODEL_DIR"
  fi

  # Remove only empty parent directories; never touch unrelated Kienzlefon data.
  rmdir "$MODEL_BASE" >/dev/null 2>&1 || true
  rmdir "$ETC_DIR" >/dev/null 2>&1 || true
  rmdir "/var/lib/kienzlefon" >/dev/null 2>&1 || true
  rmdir "/var/log/kienzlefon" >/dev/null 2>&1 || true
  rmdir "/opt/kienzlefon" >/dev/null 2>&1 || true

  cat <<EOF_UNINSTALL

====================================================================
Kienzlefon Qwen3-TTS uninstall complete
====================================================================
Service            : removed/stopped
Helper commands    : removed
Source/binary      : removed
Configuration      : removed
State              : removed
Logs               : removed
Model              : $([[ "$KEEP_MODEL" -eq 1 ]] && echo "kept at ${MODEL_DIR}" || echo "removed")
System dependencies: untouched
NVIDIA/CUDA        : untouched
====================================================================
EOF_UNINSTALL
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

file_size() {
  if [[ "$PLATFORM" == "macos" ]]; then
    stat -f '%z' "$1"
  else
    stat -c '%s' "$1"
  fi
}

validate_wav() {
  local f="$1"
  [[ -f "$f" ]] || return 1
  local size
  size="$(file_size "$f")"
  (( size > 44 )) || return 1
  [[ "$(dd if="$f" bs=1 count=4 2>/dev/null)" == "RIFF" ]] || return 1
  [[ "$(dd if="$f" bs=1 skip=8 count=4 2>/dev/null)" == "WAVE" ]] || return 1
  return 0
}

model_is_complete() {
  local d="$1"
  local required=(
    "config.json"
    "generation_config.json"
    "tokenizer_config.json"
    "preprocessor_config.json"
    "model.safetensors"
    "vocab.json"
    "merges.txt"
    "speech_tokenizer/config.json"
    "speech_tokenizer/configuration.json"
    "speech_tokenizer/model.safetensors"
    "speech_tokenizer/preprocessor_config.json"
  )
  local f size
  for f in "${required[@]}"; do
    [[ -s "${d}/${f}" ]] || return 1
  done

  # Conservative size thresholds catch common interrupted downloads without
  # coupling the installer to exact model file sizes.
  size="$(file_size "${d}/model.safetensors")"
  (( size >= 100000000 )) || return 1
  size="$(file_size "${d}/speech_tokenizer/model.safetensors")"
  (( size >= 10000000 )) || return 1
  return 0
}

wait_for_health() {
  local url="$1"
  local attempts="${2:-180}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --max-time 2 "${url}/v1/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

detect_platform() {
  local kernel
  kernel="$(uname -s)"
  ARCH="$(uname -m)"

  case "$kernel" in
    Darwin)
      PLATFORM="macos"
      SERVICE_KIND="launchd"
      [[ "$ARCH" == "arm64" ]] || die "macOS support requires Apple Silicon arm64; detected ${ARCH}."
      OS_VERSION="$(sw_vers -productVersion 2>/dev/null || true)"
      ;;
    Linux)
      [[ -r /etc/os-release ]] || die "Linux detected, but /etc/os-release is missing."
      # shellcheck disable=SC1091
      . /etc/os-release
      DISTRO_ID="${ID:-unknown}"
      [[ "$ARCH" == "x86_64" ]] || die "Linux support currently requires x86_64; detected ${ARCH}."
      SERVICE_KIND="systemd"
      OS_VERSION="${VERSION_ID:-unknown}"
      case "$DISTRO_ID" in
        ubuntu)
          PLATFORM="ubuntu"
          STANDARD_MODE="CUDA INT4"
          ;;
        debian)
          case "$OS_VERSION" in
            12|13) ;;
            *) die "Debian support is limited to versions 12 and 13; detected ${OS_VERSION}." ;;
          esac
          (( OFFLINE_ONLY == 1 )) || die "Debian ${OS_VERSION} is supported only together with --offline-only."
          PLATFORM="debian"
          STANDARD_MODE="CPU INT4"
          (( THREADS_EXPLICIT == 1 )) || THREADS=2
          ;;
        *)
          die "Linux support is limited to Ubuntu and Debian 12/13; detected ID='${DISTRO_ID}'."
          ;;
      esac
      ;;
    *)
      die "Unsupported operating system: ${kernel}"
      ;;
  esac
}

check_ram() {
  local ram_bytes ram_gib available_kib=0
  if [[ "$PLATFORM" == "macos" ]]; then
    ram_bytes="$(sysctl -n hw.memsize)"
  else
    ram_bytes="$(awk '/^MemTotal:/ {printf "%.0f", $2 * 1024}' /proc/meminfo)"
  fi
  ram_gib=$(( ram_bytes / 1073741824 ))
  if [[ "$PLATFORM" != "macos" ]]; then
    available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
    is_uint "$available_kib" || available_kib=0
  fi

  if (( OFFLINE_ONLY == 1 )); then
    log "RAM detected: ${ram_gib} GiB total; current free memory does not block offline installation."
    if (( available_kib > 0 && available_kib < MIN_GENERATE_AVAILABLE_KIB )); then
      warn "Only $((available_kib / 1024)) MiB is currently available. ASR units will be stopped before the installation generation test; the 5 GiB check runs afterwards."
    fi
    return 0
  fi

  (( ram_gib >= MIN_RAM_GIB )) || die "At least ${MIN_RAM_GIB} GiB RAM is required; detected ${ram_gib} GiB."
  log "RAM detected: ${ram_gib} GiB"
}

install_linux_build_dependencies() {
  log "Installing/checking Linux build dependencies (NVIDIA/CUDA are intentionally untouched)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  local packages=(
    build-essential
    ca-certificates
    curl
    git
    libopenblas-dev
  )
  if (( OFFLINE_ONLY == 0 )); then
    packages+=(lsof)
  fi
  apt-get install -y --no-install-recommends "${packages[@]}"
}

probe_cuda_optional() {
  [[ "$PLATFORM" == "ubuntu" || "$PLATFORM" == "debian" ]] || return 1

  CUDA_AVAILABLE=0
  CUDA_HOME=""
  CUDA_LIBDIR=""
  CUDA_ARCH=""
  CUDA_GPU_NAME=""

  if ! command -v nvidia-smi >/dev/null 2>&1; then
    warn "No nvidia-smi found; offline generation will use the CPU backend."
    return 1
  fi
  if ! nvidia-smi >/dev/null 2>&1; then
    warn "nvidia-smi cannot communicate with the NVIDIA driver; offline generation will use CPU."
    return 1
  fi

  CUDA_GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -n "$CUDA_GPU_NAME" ]] || CUDA_GPU_NAME="NVIDIA GPU"

  local nvcc_path="" resolved=""
  if [[ -n "$CUDA_HOME_OVERRIDE" ]]; then
    CUDA_HOME="${CUDA_HOME_OVERRIDE%/}"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  elif command -v nvcc >/dev/null 2>&1; then
    nvcc_path="$(command -v nvcc)"
    if command -v readlink >/dev/null 2>&1; then
      resolved="$(readlink -f "$nvcc_path" 2>/dev/null || true)"
      [[ -n "$resolved" ]] && nvcc_path="$resolved"
    fi
    CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
  elif [[ -x /usr/local/cuda/bin/nvcc ]]; then
    CUDA_HOME="/usr/local/cuda"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  elif [[ -x /opt/cuda/bin/nvcc ]]; then
    CUDA_HOME="/opt/cuda"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  else
    warn "NVIDIA driver found, but no CUDA Toolkit compiler (nvcc); offline generation will use CPU."
    return 1
  fi

  if [[ ! -x "$nvcc_path" || ! -d "${CUDA_HOME}/include" ]]; then
    warn "CUDA Toolkit at '${CUDA_HOME}' is incomplete; offline generation will use CPU."
    CUDA_HOME=""
    return 1
  fi

  if [[ -d "${CUDA_HOME}/lib64" ]]; then
    CUDA_LIBDIR="${CUDA_HOME}/lib64"
  elif [[ -d "${CUDA_HOME}/lib" ]]; then
    CUDA_LIBDIR="${CUDA_HOME}/lib"
  else
    warn "CUDA library directory is missing below '${CUDA_HOME}'; offline generation will use CPU."
    CUDA_HOME=""
    return 1
  fi

  local cc
  cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]' || true)"
  if [[ ! "$cc" =~ ^[0-9]+\.[0-9]+$ ]]; then
    warn "Could not determine NVIDIA compute capability; offline generation will use CPU."
    CUDA_HOME=""
    CUDA_LIBDIR=""
    return 1
  fi

  CUDA_ARCH="sm_${cc/./}"
  CUDA_AVAILABLE=1
  log "Optional CUDA backend detected: ${CUDA_GPU_NAME} (compute capability ${cc}, build arch ${CUDA_ARCH})"
  log "CUDA Toolkit: ${CUDA_HOME}"
  "$nvcc_path" --version | tail -n 1 || true
  return 0
}

detect_cuda() {
  [[ "$PLATFORM" == "ubuntu" ]] || return 0

  require_cmd nvidia-smi
  nvidia-smi >/dev/null 2>&1 || die "nvidia-smi exists but cannot communicate with the NVIDIA driver. CUDA setup is not healthy."

  CUDA_GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -n "$CUDA_GPU_NAME" ]] || CUDA_GPU_NAME="NVIDIA GPU"

  local nvcc_path
  if [[ -n "$CUDA_HOME_OVERRIDE" ]]; then
    CUDA_HOME="${CUDA_HOME_OVERRIDE%/}"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  elif command -v nvcc >/dev/null 2>&1; then
    nvcc_path="$(command -v nvcc)"
    # Resolve symlinks where possible, then take <prefix>/bin/nvcc -> <prefix>.
    if command -v readlink >/dev/null 2>&1; then
      local resolved
      resolved="$(readlink -f "$nvcc_path" 2>/dev/null || true)"
      [[ -n "$resolved" ]] && nvcc_path="$resolved"
    fi
    CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
  elif [[ -x /usr/local/cuda/bin/nvcc ]]; then
    CUDA_HOME="/usr/local/cuda"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  elif [[ -x /opt/cuda/bin/nvcc ]]; then
    CUDA_HOME="/opt/cuda"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  else
    die "CUDA Toolkit compiler nvcc was not found. Install/configure CUDA first; this installer deliberately does not modify CUDA or NVIDIA drivers."
  fi

  [[ -x "$nvcc_path" ]] || die "nvcc is not executable at ${nvcc_path}"
  [[ -d "${CUDA_HOME}/include" ]] || die "CUDA include directory missing: ${CUDA_HOME}/include"

  if [[ -d "${CUDA_HOME}/lib64" ]]; then
    CUDA_LIBDIR="${CUDA_HOME}/lib64"
  elif [[ -d "${CUDA_HOME}/lib" ]]; then
    CUDA_LIBDIR="${CUDA_HOME}/lib"
  else
    die "CUDA library directory not found below ${CUDA_HOME}"
  fi

  # Build for the installed machine's first GPU rather than upstream's broad
  # multi-arch default. This both shortens compilation and avoids asking older
  # toolkits to understand unrelated future architectures (e.g. sm_120).
  local cc
  cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]' || true)"
  if [[ "$cc" =~ ^[0-9]+\.[0-9]+$ ]]; then
    CUDA_ARCH="sm_${cc/./}"
  else
    die "Could not determine NVIDIA compute capability with nvidia-smi; refusing to guess a CUDA architecture."
  fi

  log "NVIDIA GPU: ${CUDA_GPU_NAME} (compute capability ${cc}, build arch ${CUDA_ARCH})"
  log "CUDA Toolkit: ${CUDA_HOME}"
  "$nvcc_path" --version | tail -n 1 || true
  CUDA_AVAILABLE=1
}

check_platform_and_tools() {
  detect_platform
  log "Detected platform: ${PLATFORM} ${OS_VERSION} / ${ARCH}"

  if [[ "$PLATFORM" == "ubuntu" || "$PLATFORM" == "debian" ]]; then
    require_cmd apt-get
    install_linux_build_dependencies
  fi

  require_cmd awk
  require_cmd cat
  require_cmd cp
  require_cmd curl
  require_cmd dd
  require_cmd dirname
  require_cmd git
  require_cmd grep
  require_cmd head
  require_cmd install
  require_cmd make
  require_cmd mkdir
  require_cmd mktemp
  require_cmd mv
  require_cmd od
  require_cmd sed
  require_cmd stat
  require_cmd tr
  require_cmd wc

  if (( OFFLINE_ONLY == 0 )); then
    require_cmd lsof
    require_cmd ps
    require_cmd tail
    require_cmd tee
  fi

  if [[ "$PLATFORM" == "macos" ]]; then
    require_cmd clang
    require_cmd xcode-select
    require_cmd sysctl
    if (( OFFLINE_ONLY == 0 )); then
      require_cmd plutil
      require_cmd launchctl
    fi
    xcode-select -p >/dev/null 2>&1 || die "Xcode Command Line Tools are not active. Run: xcode-select --install"
    clang --version >/dev/null 2>&1 || die "clang is not usable"
  else
    require_cmd gcc
    require_cmd ldd
    require_cmd systemctl
    gcc --version >/dev/null 2>&1 || die "gcc is not usable"
    if (( OFFLINE_ONLY == 1 )); then
      probe_cuda_optional || true
    else
      detect_cuda
    fi
  fi

  make --version >/dev/null 2>&1 || die "make is not usable"
  check_ram
}

prepare_directories() {
  log "Preparing directories..."
  mkdir -p "$BASE_DIR" "$BIN_DIR" "$TOOLS_DIR" "$MODEL_BASE" "$LOG_DIR" "$ETC_DIR" "$STATE_DIR" /usr/local/bin
  chmod 0755 "$BASE_DIR" "$BIN_DIR" "$TOOLS_DIR" "$MODEL_BASE" "$LOG_DIR" "$ETC_DIR" "$STATE_DIR" /usr/local/bin
}

systemd_unit_exists() {
  local unit="$1" load_state
  [[ "$PLATFORM" != "macos" ]] || return 1
  load_state="$(systemctl show "$unit" -p LoadState --value 2>/dev/null || true)"
  [[ -n "$load_state" && "$load_state" != "not-found" ]]
}

detect_pause_units() {
  PAUSE_UNITS=()
  [[ "$PLATFORM" != "macos" ]] || return 0

  # Fixed positive list. Stop order is front-to-back; restart order is reversed
  # so gateways stop before their backend and backends start before gateways.
  local unit
  for unit in \
    "$CLASSIC_WORKER_UNIT" \
    "kienzlefon-ai-asr.service" \
    "kienzlefon-ai-asr-backend.service"; do
    if systemd_unit_exists "$unit"; then
      PAUSE_UNITS+=("$unit")
    fi
  done

  if (( ${#PAUSE_UNITS[@]} == 0 )); then
    warn "No positively listed Kienzlefon ASR unit detected; generation cannot release ASR memory automatically on this host."
  else
    log "ASR units configured for temporary generation pause: $(pause_units_csv)"
  fi
}

pause_units_csv() {
  local result="" unit
  if (( ${#PAUSE_UNITS[@]} > 0 )); then
    for unit in "${PAUSE_UNITS[@]}"; do
      [[ -z "$result" ]] || result+=","
      result+="$unit"
    done
  fi
  printf '%s\n' "$result"
}

install_source() {
  if [[ -d "${SRC_DIR}/.git" ]]; then
    log "Existing source checkout found; leaving its revision unchanged."
    local origin
    origin="$(git -C "$SRC_DIR" remote get-url origin 2>/dev/null || true)"
    if [[ -n "$origin" && "$origin" != "$REPO_URL" && "$origin" != "https://github.com/gabriele-mastrapasqua/qwen3-tts" ]]; then
      warn "Existing checkout origin is '${origin}', expected '${REPO_URL}'. Continuing without changing it."
    fi
  elif [[ -e "$SRC_DIR" ]]; then
    die "${SRC_DIR} exists but is not a git checkout. Refusing to overwrite it."
  else
    log "Cloning qwen3-tts (current upstream main; no commit pinning in this version)..."
    git clone --recursive "$REPO_URL" "$SRC_DIR"
  fi

  # Initialize missing submodules, but do not update the main checkout revision.
  git -C "$SRC_DIR" submodule update --init --recursive
  [[ -f "${SRC_DIR}/Makefile" ]] || die "Source checkout is missing Makefile"
  [[ -x "${SRC_DIR}/download_model.sh" ]] || chmod +x "${SRC_DIR}/download_model.sh"
}

build_binary() {
  if [[ "$PLATFORM" == "macos" ]]; then
    log "Building Metal-capable native binary (CPU remains runtime default on macOS)..."
    (
      cd "$SRC_DIR"
      make metal CC=clang
    )
  else
    log "Building CUDA-capable native binary for ${CUDA_ARCH} (CUDA will be runtime default on Ubuntu)..."
    (
      cd "$SRC_DIR"
      make cuda CUDA_HOME="$CUDA_HOME" NVCC_ARCH="-arch=${CUDA_ARCH}"
    )
  fi

  [[ -x "${SRC_DIR}/qwen_tts" ]] || die "Build completed without producing ${SRC_DIR}/qwen_tts"
  install -m 0755 "${SRC_DIR}/qwen_tts" "$BINARY"

  if [[ "$PLATFORM" == "ubuntu" ]]; then
    # A CUDA build links CUDA shared libraries even when the CPU backend is used.
    # Verify the installed binary can resolve every dependency. The env file and
    # systemd unit also carry CUDA_LIBDIR for non-standard toolkit prefixes.
    if ! LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" ldd "$BINARY" | grep -q 'not found'; then
      :
    else
      LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" ldd "$BINARY" >&2 || true
      die "The CUDA-capable qwen_tts binary has unresolved shared libraries."
    fi
  fi

  run_binary --caps >/dev/null 2>&1 || warn "qwen_tts --caps returned non-zero; continuing to functional tests."
  run_binary --self-test >/dev/null 2>&1 || die "qwen_tts --self-test failed"
}

cpu_binary_is_usable() {
  [[ -x "$CPU_BINARY" ]] || return 1
  "$CPU_BINARY" --self-test >/dev/null 2>&1 || return 1
  if [[ "$PLATFORM" != "macos" ]] && ldd "$CPU_BINARY" 2>/dev/null | grep -Eq 'libcuda|libcudart|libcublas'; then
    return 1
  fi
  return 0
}

build_offline_cpu_binary() {
  if cpu_binary_is_usable; then
    log "Existing independent CPU binary passed self-test; no rebuild needed."
    return 0
  fi

  local build_root build_src
  build_root="$(mktemp -d /tmp/kienzlefon-qwen-cpu-build.XXXXXX)"
  build_src="${build_root}/src"
  CLEANUP_TMP="$build_root"

  log "Building independent CPU-only BLAS binary in a temporary build tree..."
  cp -R "$SRC_DIR" "$build_src"

  if [[ "$PLATFORM" == "macos" ]]; then
    (
      cd "$build_src"
      make clean >/dev/null 2>&1 || true
      make blas CC=clang
    )
  elif grep -qw avx2 /proc/cpuinfo && grep -qw fma /proc/cpuinfo; then
    log "CPU supports AVX2 and FMA; using the normal x86 BLAS build."
    (
      cd "$build_src"
      make clean >/dev/null 2>&1 || true
      make blas
    )
  else
    warn "CPU lacks AVX2/FMA; building the slower scalar fallback."
    (
      cd "$build_src"
      make clean >/dev/null 2>&1 || true
      make blas SIMD=scalar
    )
  fi

  [[ -x "${build_src}/qwen_tts" ]] || die "CPU build completed without producing qwen_tts"
  install -m 0755 "${build_src}/qwen_tts" "$CPU_BINARY"

  if [[ "$PLATFORM" != "macos" ]]; then
    if ldd "$CPU_BINARY" | grep -q 'not found'; then
      ldd "$CPU_BINARY" >&2 || true
      die "The CPU-only qwen_tts binary has unresolved shared libraries."
    fi
    if ldd "$CPU_BINARY" | grep -Eq 'libcuda|libcudart|libcublas'; then
      die "The supposed CPU-only qwen_tts binary unexpectedly depends on CUDA libraries."
    fi
  fi

  "$CPU_BINARY" --caps >/dev/null 2>&1 || warn "CPU qwen_tts --caps returned non-zero; continuing to self-test."
  "$CPU_BINARY" --self-test >/dev/null 2>&1 || die "CPU-only qwen_tts --self-test failed"

  rm -rf -- "$build_root"
  CLEANUP_TMP=""
}

cuda_binary_is_usable() {
  [[ "$PLATFORM" != "macos" && "$CUDA_AVAILABLE" -eq 1 && -x "$CUDA_BINARY" ]] || return 1
  if LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
      ldd "$CUDA_BINARY" 2>/dev/null | grep -q 'not found'; then
    return 1
  fi
  LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
    "$CUDA_BINARY" --self-test >/dev/null 2>&1 || return 1
  return 0
}

build_offline_cuda_binary() {
  [[ "$PLATFORM" != "macos" && "$CUDA_AVAILABLE" -eq 1 ]] || return 0

  if cuda_binary_is_usable; then
    log "Existing independent CUDA binary passed dependency/basic self-test; runtime GPU test follows after ASR stop."
    return 0
  fi

  local build_root build_src
  build_root="$(mktemp -d /tmp/kienzlefon-qwen-cuda-build.XXXXXX)"
  build_src="${build_root}/src"
  CLEANUP_TMP="$build_root"

  log "Building independent CUDA binary for ${CUDA_ARCH} in a temporary build tree..."
  cp -R "$SRC_DIR" "$build_src"
  if ! (
    cd "$build_src"
    make clean >/dev/null 2>&1 || true
    make cuda CUDA_HOME="$CUDA_HOME" NVCC_ARCH="-arch=${CUDA_ARCH}"
  ); then
    warn "CUDA build failed; keeping the required CPU generator as fallback."
    rm -rf -- "$build_root"
    rm -f -- "$CUDA_BINARY"
    CLEANUP_TMP=""
    CUDA_AVAILABLE=0
    return 0
  fi

  if [[ ! -x "${build_src}/qwen_tts" ]]; then
    warn "CUDA build produced no executable; keeping the CPU generator as fallback."
    rm -rf -- "$build_root"
    rm -f -- "$CUDA_BINARY"
    CLEANUP_TMP=""
    CUDA_AVAILABLE=0
    return 0
  fi

  install -m 0755 "${build_src}/qwen_tts" "$CUDA_BINARY"
  rm -rf -- "$build_root"
  CLEANUP_TMP=""

  if ! cuda_binary_is_usable; then
    warn "CUDA binary failed dependency or basic self-test; offline generation will use CPU."
    rm -f -- "$CUDA_BINARY"
    CUDA_AVAILABLE=0
    return 0
  fi

  log "Independent CUDA binary passed dependency/basic self-test; runtime GPU test follows after ASR stop."
}

run_binary() {
  if [[ "$PLATFORM" == "ubuntu" ]]; then
    LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" "$BINARY" "$@"
  else
    "$BINARY" "$@"
  fi
}

download_model() {
  if model_is_complete "$MODEL_DIR"; then
    log "Complete 0.6B CustomVoice model already present; no download needed."
    return
  fi

  if [[ -e "$MODEL_DIR" ]]; then
    warn "Model directory exists but is incomplete. It will not be trusted or modified in place."
    mv "$MODEL_DIR" "${MODEL_DIR}.incomplete.$(date '+%Y%m%d-%H%M%S')"
  fi

  local stage="${MODEL_BASE}/.qwen3-tts-0.6b-customvoice.download.$$"
  rm -rf -- "$stage"
  mkdir -p "$stage"
  CLEANUP_STAGE="$stage"

  log "Downloading ${MODEL_HF_ID} into staging directory..."
  (
    cd "$SRC_DIR"
    ./download_model.sh --model small --dir "$stage"
  )

  model_is_complete "$stage" || die "Downloaded model failed completeness validation"
  mv "$stage" "$MODEL_DIR"
  CLEANUP_STAGE=""
  touch "${MODEL_DIR}/.kienzlefon-complete"
  log "Model download complete."
}

write_env_file() {
  cat > "$ENV_FILE" <<EOF_ENV
# Generated by ${SCRIPT_NAME}
KIENZLEFON_QWEN_PLATFORM=${PLATFORM}
KIENZLEFON_QWEN_PORT=${PORT}
KIENZLEFON_QWEN_THREADS=${THREADS}
KIENZLEFON_QWEN_BATCH_SIZE=${BATCH_SIZE}
KIENZLEFON_QWEN_DEFAULT_BACKEND=$([[ "$PLATFORM" == "ubuntu" ]] && echo cuda || echo cpu)
KIENZLEFON_QWEN_DEFAULT_QUANTIZATION=int4
KIENZLEFON_QWEN_MODEL=${MODEL_DIR}
CUDA_HOME=${CUDA_HOME}
CUDA_LIBDIR=${CUDA_LIBDIR}
CUDA_ARCH=${CUDA_ARCH}
EOF_ENV
  chmod 0644 "$ENV_FILE"
}

write_offline_env_file() {
  cat > "$OFFLINE_ENV_FILE" <<EOF_OFFLINE_ENV
# Generated by ${SCRIPT_NAME}
KIENZLEFON_QWEN_INSTALL_MODE=offline-one-shot
KIENZLEFON_QWEN_PLATFORM=${PLATFORM}
KIENZLEFON_QWEN_THREADS=${THREADS}
KIENZLEFON_QWEN_MODEL=${MODEL_DIR}
KIENZLEFON_QWEN_CPU_BINARY=${CPU_BINARY}
KIENZLEFON_QWEN_CUDA_BINARY=${CUDA_BINARY}
KIENZLEFON_QWEN_CUDA_AVAILABLE=${CUDA_AVAILABLE}
KIENZLEFON_QWEN_BACKEND_PREFERENCE=$([[ "$CUDA_AVAILABLE" -eq 1 ]] && echo cuda || echo cpu)
KIENZLEFON_QWEN_DEFAULT_QUANTIZATION=int4
KIENZLEFON_QWEN_OUTPUT_FORMAT=wav-pcm-s16le-24000hz-mono
KIENZLEFON_QWEN_PAUSE_UNITS=$(pause_units_csv)
KIENZLEFON_QWEN_MAINTENANCE_MARKER=${MAINTENANCE_MARKER}
KIENZLEFON_QWEN_MIN_AVAILABLE_KIB=${MIN_GENERATE_AVAILABLE_KIB}
KIENZLEFON_QWEN_STOP_TIMEOUT_SECONDS=${STOP_TIMEOUT_SECONDS}
KIENZLEFON_QWEN_READINESS_TIMEOUT_SECONDS=${READINESS_TIMEOUT_SECONDS}
CUDA_HOME=${CUDA_HOME}
CUDA_LIBDIR=${CUDA_LIBDIR}
CUDA_ARCH=${CUDA_ARCH}
EOF_OFFLINE_ENV
  chmod 0644 "$OFFLINE_ENV_FILE"
}

install_generate_command() {
  local pause_units_literal="" unit
  if (( ${#PAUSE_UNITS[@]} > 0 )); then
    for unit in "${PAUSE_UNITS[@]}"; do
      [[ "$unit" =~ ^[A-Za-z0-9_.@:-]+\.service$ ]] || die "Unsafe ASR unit name refused: ${unit}"
      printf -v pause_units_literal '%s  %q\n' "$pause_units_literal" "$unit"
    done
  fi

  cat > "$GENERATE_CMD" <<EOF_GENERATE
#!/bin/bash
# Non-resident Kienzlefon Qwen3-TTS announcement generator.
set -Eeuo pipefail
IFS=\$'\\n\\t'
umask 022

PLATFORM="${PLATFORM}"
CPU_BIN="${CPU_BINARY}"
CUDA_BIN="${CUDA_BINARY}"
CUDA_ENABLED="${CUDA_AVAILABLE}"
CUDA_LIBDIR="${CUDA_LIBDIR}"
MODEL="${MODEL_DIR}"
THREADS="${THREADS}"
LOCK_FILE="${GENERATE_LOCK}"
MIN_AVAILABLE_KIB="${MIN_GENERATE_AVAILABLE_KIB}"
STOP_TIMEOUT="${STOP_TIMEOUT_SECONDS}"
READINESS_TIMEOUT="${READINESS_TIMEOUT_SECONDS}"
MAINTENANCE_MARKER="${MAINTENANCE_MARKER}"
CLASSIC_WORKER_UNIT="${CLASSIC_WORKER_UNIT}"
CLASSIC_STATUS_CMD="${CLASSIC_STATUS_CMD}"
CLASSIC_STATUS_PYTHON="${CLASSIC_STATUS_PYTHON}"
CLASSIC_CONFIG="${CLASSIC_CONFIG}"
CLASSIC_HEARTBEAT="${CLASSIC_HEARTBEAT}"
PAUSE_UNITS=(
${pause_units_literal})

TEXT=""
OUTPUT=""
SPEAKER="ryan"
LANGUAGE="German"
SEED="${TEST_SEED}"
FORCE=0
TMP_OUTPUT=""
TMP_DIR=""
CUDA_LOG=""
CPU_LOG=""
LOCK_DIR=""
LOCK_CANDIDATE=""
MARKER_CREATED=0
MARKER_TMP=""
KEEP_MARKER=0
RESTORE_REQUIRED=0
RESTORE_COMPLETE=0
OLD_HEARTBEAT_PID=""
OLD_HEARTBEAT_UPDATED=""
ACTIVE_BEFORE=()
TARGET_UID=""
TARGET_GID=""

usage() {
  cat <<'USAGE'
Usage:
  kienzlefon-qwen3-tts-generate --text TEXT --output FILE.wav [options]

Required:
  --text TEXT           Text to synthesize
  --output FILE.wav     Destination WAV (PCM S16LE, 24000 Hz, mono)

Optional:
  --speaker NAME        CustomVoice speaker (default: ryan)
  --language LANGUAGE   Language (default: German)
  --seed N              Non-negative deterministic seed (default: 42)
  --force               Atomically replace an existing destination file
  -h, --help            Show this help

The command prefers a validated CUDA backend when installed and usable, then
automatically retries once with the independent CPU binary. Before model loading,
it temporarily stops only positively listed Kienzlefon ASR units that were active.
It restores and verifies them before activating the finished WAV. It starts no
HTTP server, opens no TCP port, and exits after writing the WAV file.
USAGE
}

die() {
  printf '[ERROR] %s\\n' "\$*" >&2
  exit 1
}

unit_is_active() {
  systemctl is-active --quiet "\$1" 2>/dev/null
}

classic_worker_was_active() {
  local i
  for i in "\${!PAUSE_UNITS[@]}"; do
    if [[ "\${PAUSE_UNITS[\$i]}" == "\$CLASSIC_WORKER_UNIT" && "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]]; then
      return 0
    fi
  done
  return 1
}

create_maintenance_marker() {
  (( \${#PAUSE_UNITS[@]} > 0 )) || return 0
  mkdir -p "\$(dirname "\$MAINTENANCE_MARKER")"
  if [[ -e "\$MAINTENANCE_MARKER" ]]; then
    die "ASR maintenance marker already exists; refusing concurrent generation: \$MAINTENANCE_MARKER"
  fi
  MARKER_TMP="\$(mktemp "\${MAINTENANCE_MARKER}.tmp.XXXXXX")"
  printf 'qwen3-tts-generation pid=%s started=%s\\n' "\$\$" "\$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >"\$MARKER_TMP"
  chmod 0644 "\$MARKER_TMP"
  mv -f -- "\$MARKER_TMP" "\$MAINTENANCE_MARKER"
  MARKER_TMP=""
  MARKER_CREATED=1
}

remove_owned_maintenance_marker() {
  if [[ "\$MARKER_CREATED" -eq 1 && "\$KEEP_MARKER" -eq 0 ]]; then
    rm -f -- "\$MAINTENANCE_MARKER"
    MARKER_CREATED=0
  fi
}

read_old_heartbeat_identity() {
  [[ -x "\$CLASSIC_STATUS_PYTHON" && -r "\$CLASSIC_HEARTBEAT" ]] || return 0
  local identity old_ifs
  identity="\$("\$CLASSIC_STATUS_PYTHON" -c '
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        value = json.load(handle)
    print("{}|{}".format(value.get("pid", -1), value.get("updated_at", "?")))
except Exception:
    print("-1|?")
' "\$CLASSIC_HEARTBEAT" 2>/dev/null || printf '%s' '-1|?')"
  old_ifs="\$IFS"
  IFS='|' read -r OLD_HEARTBEAT_PID OLD_HEARTBEAT_UPDATED <<<"\$identity"
  IFS="\$old_ifs"
}

check_classic_worker_idle() {
  classic_worker_was_active || return 0
  [[ -x "\$CLASSIC_STATUS_CMD" ]] || die "Classic status command is missing: \$CLASSIC_STATUS_CMD"
  [[ -x "\$CLASSIC_STATUS_PYTHON" ]] || die "Classic status Python is missing: \$CLASSIC_STATUS_PYTHON"
  [[ -r "\$CLASSIC_CONFIG" ]] || die "Classic Kienzlefon config is missing: \$CLASSIC_CONFIG"

  local status_json counts recording processing queue old_ifs
  if ! status_json="\$("\$CLASSIC_STATUS_CMD" --config "\$CLASSIC_CONFIG" 2>/dev/null)"; then
    die "Classic Whisper worker is not ready before generation; refusing to stop it"
  fi
  counts="\$("\$CLASSIC_STATUS_PYTHON" -c '
import json, sys
value = json.load(sys.stdin)
calls = value.get("calls", {})
print("{}:{}:{}".format(
    int(calls.get("recording", 0)),
    int(calls.get("processing", 0)),
    int(calls.get("queue", 0)),
))
' <<<"\$status_json")" || die "Could not parse classic Kienzlefon status JSON"
  old_ifs="\$IFS"
  IFS=':' read -r recording processing queue <<<"\$counts"
  IFS="\$old_ifs"
  [[ "\$recording" -eq 0 ]] || die "Kienzlefon currently has \$recording active recording(s); generation was not started"
  [[ "\$processing" -eq 0 ]] || die "Kienzlefon currently processes \$processing ASR job(s); generation was not started"
  printf '[INFO] Classic Kienzlefon is idle; queued jobs left in place: %s\\n' "\$queue"
  read_old_heartbeat_identity
}

record_active_units() {
  local i unit active_count=0
  ACTIVE_BEFORE=()
  for i in "\${!PAUSE_UNITS[@]}"; do
    unit="\${PAUSE_UNITS[\$i]}"
    if unit_is_active "\$unit"; then
      ACTIVE_BEFORE[\$i]=1
      active_count=\$((active_count + 1))
    else
      ACTIVE_BEFORE[\$i]=0
    fi
  done
  printf '[INFO] Active ASR units to restore later: %s\\n' "\$active_count"
}

wait_units_stopped() {
  local waited i unit pid all_stopped
  for ((waited=0; waited<STOP_TIMEOUT; waited++)); do
    all_stopped=1
    for i in "\${!PAUSE_UNITS[@]}"; do
      [[ "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]] || continue
      unit="\${PAUSE_UNITS[\$i]}"
      pid="\$(systemctl show "\$unit" -p MainPID --value 2>/dev/null || printf '0')"
      if unit_is_active "\$unit" || [[ "\${pid:-0}" != "0" ]]; then
        all_stopped=0
        break
      fi
    done
    (( all_stopped == 1 )) && return 0
    sleep 1
  done
  return 1
}

stop_active_units() {
  local i unit
  RESTORE_REQUIRED=1
  for i in "\${!PAUSE_UNITS[@]}"; do
    [[ "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]] || continue
    unit="\${PAUSE_UNITS[\$i]}"
    printf '[INFO] Stopping ASR unit: %s\\n' "\$unit"
    systemctl --no-block stop "\$unit" || return 1
  done
  wait_units_stopped
}

check_available_memory() {
  [[ "\$PLATFORM" != "macos" ]] || return 0
  local available_kib
  available_kib="\$(awk '/^MemAvailable:/ {print \$2}' /proc/meminfo)"
  case "\$available_kib" in ''|*[!0-9]*) die "Could not read MemAvailable from /proc/meminfo" ;; esac
  printf '[INFO] Memory available after ASR stop: %s MiB\\n' "\$((available_kib / 1024))"
  (( available_kib >= MIN_AVAILABLE_KIB )) \
    || die "Only \$((available_kib / 1024)) MiB available after ASR stop; at least \$((MIN_AVAILABLE_KIB / 1024)) MiB required"
}

current_heartbeat_identity() {
  "\$CLASSIC_STATUS_PYTHON" -c '
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if value.get("ready") is not True:
        raise ValueError("not ready")
    print("{}|{}".format(int(value.get("pid", -1)), value.get("updated_at", "?")))
except Exception:
    raise SystemExit(1)
' "\$CLASSIC_HEARTBEAT" 2>/dev/null
}

wait_classic_readiness() {
  classic_worker_was_active || return 0
  local waited main_pid identity heartbeat_pid heartbeat_updated old_ifs
  for ((waited=0; waited<READINESS_TIMEOUT; waited++)); do
    if unit_is_active "\$CLASSIC_WORKER_UNIT" \
        && "\$CLASSIC_STATUS_CMD" --config "\$CLASSIC_CONFIG" >/dev/null 2>&1; then
      main_pid="\$(systemctl show "\$CLASSIC_WORKER_UNIT" -p MainPID --value 2>/dev/null || printf '0')"
      identity="\$(current_heartbeat_identity 2>/dev/null || true)"
      old_ifs="\$IFS"
      IFS='|' read -r heartbeat_pid heartbeat_updated <<<"\$identity"
      IFS="\$old_ifs"
      if [[ -n "\$identity" && "\$main_pid" != "0" && "\$heartbeat_pid" == "\$main_pid" \
          && "\$heartbeat_updated" != "\$OLD_HEARTBEAT_UPDATED" ]]; then
        printf '[INFO] Classic Whisper worker is ready with new heartbeat PID %s.\\n' "\$main_pid"
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}

restore_paused_units() {
  if (( RESTORE_REQUIRED == 0 )); then
    RESTORE_COMPLETE=1
    return 0
  fi

  local i unit waited all_active=0
  for ((i=\${#PAUSE_UNITS[@]}-1; i>=0; i--)); do
    [[ "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]] || continue
    unit="\${PAUSE_UNITS[\$i]}"
    printf '[INFO] Starting previously active ASR unit: %s\\n' "\$unit"
    systemctl --no-block start "\$unit" || return 1
  done

  for ((waited=0; waited<READINESS_TIMEOUT; waited++)); do
    all_active=1
    for i in "\${!PAUSE_UNITS[@]}"; do
      [[ "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]] || continue
      unit_is_active "\${PAUSE_UNITS[\$i]}" || { all_active=0; break; }
    done
    (( all_active == 1 )) && break
    sleep 1
  done
  (( all_active == 1 )) || return 1
  wait_classic_readiness || return 1
  RESTORE_COMPLETE=1
  return 0
}

prepare_generation_resources() {
  (( \${#PAUSE_UNITS[@]} == 0 )) || [[ "\${EUID}" -eq 0 ]] \
    || die "Root privileges are required to pause configured ASR units"
  if (( \${#PAUSE_UNITS[@]} > 0 )); then
    command -v systemctl >/dev/null 2>&1 || die "systemctl is required for configured ASR units"
    record_active_units
    create_maintenance_marker
    check_classic_worker_idle
    if ! stop_active_units; then
      die "Configured ASR units did not stop cleanly within \${STOP_TIMEOUT} seconds"
    fi
  fi
  check_available_memory
}

cleanup() {
  local rc=\$?
  set +e
  if [[ "\$RESTORE_REQUIRED" -eq 1 && "\$RESTORE_COMPLETE" -eq 0 ]]; then
    printf '[WARN] Restoring ASR units after interrupted or failed generation.\\n' >&2
    if ! restore_paused_units; then
      KEEP_MARKER=1
      printf '[CRITICAL] ASR units could not be restored; maintenance marker remains at %s\\n' "\$MAINTENANCE_MARKER" >&2
    fi
  fi
  if [[ "\$KEEP_MARKER" -eq 0 ]]; then remove_owned_maintenance_marker; fi
  [[ -n "\$MARKER_TMP" ]] && rm -f -- "\$MARKER_TMP"
  [[ -n "\$TMP_OUTPUT" ]] && rm -f -- "\$TMP_OUTPUT"
  [[ -n "\$CUDA_LOG" ]] && rm -f -- "\$CUDA_LOG"
  [[ -n "\$CPU_LOG" ]] && rm -f -- "\$CPU_LOG"
  [[ -n "\$TMP_DIR" ]] && rmdir "\$TMP_DIR" >/dev/null 2>&1
  [[ -n "\$LOCK_DIR" ]] && rmdir "\$LOCK_DIR" >/dev/null 2>&1
  return "\$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while [[ \$# -gt 0 ]]; do
  case "\$1" in
    --text)
      [[ \$# -ge 2 ]] || die "--text requires a value"
      TEXT="\$2"; shift 2 ;;
    --output)
      [[ \$# -ge 2 ]] || die "--output requires a value"
      OUTPUT="\$2"; shift 2 ;;
    --speaker)
      [[ \$# -ge 2 ]] || die "--speaker requires a value"
      SPEAKER="\$2"; shift 2 ;;
    --language)
      [[ \$# -ge 2 ]] || die "--language requires a value"
      LANGUAGE="\$2"; shift 2 ;;
    --seed)
      [[ \$# -ge 2 ]] || die "--seed requires a value"
      SEED="\$2"; shift 2 ;;
    --force)
      FORCE=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      die "Unknown option: \$1" ;;
  esac
done

[[ -n "\$TEXT" ]] || die "--text is required and must not be empty"
[[ -n "\$OUTPUT" ]] || die "--output is required"
[[ -n "\$SPEAKER" ]] || die "--speaker must not be empty"
[[ -n "\$LANGUAGE" ]] || die "--language must not be empty"
case "\$SEED" in ''|*[!0-9]*) die "--seed must be a non-negative integer" ;; esac
case "\$OUTPUT" in *.wav|*.WAV) ;; *) die "--output must end in .wav" ;; esac

[[ -x "\$CPU_BIN" ]] || die "CPU generator binary is missing: \$CPU_BIN"
[[ -d "\$MODEL" ]] || die "Qwen3-TTS model directory is missing: \$MODEL"

OUTPUT_DIR="\$(dirname "\$OUTPUT")"
[[ -d "\$OUTPUT_DIR" ]] || die "Output directory does not exist: \$OUTPUT_DIR"
[[ -w "\$OUTPUT_DIR" ]] || die "Output directory is not writable: \$OUTPUT_DIR"
if [[ -e "\$OUTPUT" && "\$FORCE" -eq 0 ]]; then
  die "Output already exists; use --force to replace it: \$OUTPUT"
fi
if [[ "\${EUID}" -eq 0 ]]; then
  owner_source="\$OUTPUT_DIR"
  [[ -e "\$OUTPUT" ]] && owner_source="\$OUTPUT"
  if [[ "\$PLATFORM" == "macos" ]]; then
    TARGET_UID="\$(stat -f '%u' "\$owner_source")"
    TARGET_GID="\$(stat -f '%g' "\$owner_source")"
  else
    TARGET_UID="\$(stat -c '%u' "\$owner_source")"
    TARGET_GID="\$(stat -c '%g' "\$owner_source")"
  fi
fi

# Serialize generation so multiple model instances cannot exhaust RAM/VRAM.
if command -v flock >/dev/null 2>&1; then
  exec 9>>"\$LOCK_FILE"
  flock -n 9 || die "Another Qwen3-TTS generation is already running"
else
  LOCK_CANDIDATE="/tmp/kienzlefon-qwen3-tts-generate.lock.d"
  if mkdir "\$LOCK_CANDIDATE" 2>/dev/null; then
    LOCK_DIR="\$LOCK_CANDIDATE"
  else
    die "Another Qwen3-TTS generation is already running"
  fi
fi

# The temporary directory is inside the destination directory: the final rename
# is atomic and the native output path still has a real .wav suffix.
TMP_DIR="\$(mktemp -d "\${OUTPUT_DIR}/.kienzlefon-qwen3-tts.XXXXXX")"
TMP_OUTPUT="\${TMP_DIR}/output.wav"
CUDA_LOG="\${TMP_DIR}/cuda.log"
CPU_LOG="\${TMP_DIR}/cpu.log"

prepare_generation_resources

byte_at() {
  od -An -tu1 -j "\$2" -N1 "\$1" | tr -d '[:space:]'
}

u16le_at() {
  local b0 b1
  b0="\$(byte_at "\$1" "\$2")"
  b1="\$(byte_at "\$1" "\$((\$2 + 1))")"
  printf '%s\\n' "\$((b0 + (b1 << 8)))"
}

u32le_at() {
  local b0 b1 b2 b3
  b0="\$(byte_at "\$1" "\$2")"
  b1="\$(byte_at "\$1" "\$((\$2 + 1))")"
  b2="\$(byte_at "\$1" "\$((\$2 + 2))")"
  b3="\$(byte_at "\$1" "\$((\$2 + 3))")"
  printf '%s\\n' "\$((b0 + (b1 << 8) + (b2 << 16) + (b3 << 24)))"
}

validate_qwen_wav() {
  local f="\$1" size
  [[ -s "\$f" ]] || return 1
  size="\$(wc -c < "\$f")"
  (( size > 44 )) || return 1
  [[ "\$(dd if="\$f" bs=1 count=4 2>/dev/null)" == "RIFF" ]] || return 1
  [[ "\$(dd if="\$f" bs=1 skip=8 count=4 2>/dev/null)" == "WAVE" ]] || return 1
  [[ "\$(u16le_at "\$f" 20)" -eq 1 ]] || return 1
  [[ "\$(u16le_at "\$f" 22)" -eq 1 ]] || return 1
  [[ "\$(u32le_at "\$f" 24)" -eq 24000 ]] || return 1
  [[ "\$(u16le_at "\$f" 34)" -eq 16 ]] || return 1
}

run_cpu() {
  rm -f -- "\$TMP_OUTPUT"
  "\$CPU_BIN" -d "\$MODEL" --int4 -j "\$THREADS" \
    -s "\$SPEAKER" -l "\$LANGUAGE" --seed "\$SEED" \
    --text "\$TEXT" -o "\$TMP_OUTPUT" >"\$CPU_LOG" 2>&1
}

run_cuda() {
  rm -f -- "\$TMP_OUTPUT"
  QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1 \
    LD_LIBRARY_PATH="\${CUDA_LIBDIR}\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}}" \
    "\$CUDA_BIN" -d "\$MODEL" --int4 -j "\$THREADS" --backend cuda \
    -s "\$SPEAKER" -l "\$LANGUAGE" --seed "\$SEED" \
    --text "\$TEXT" -o "\$TMP_OUTPUT" >"\$CUDA_LOG" 2>&1
}

BACKEND="cpu"
CUDA_OK=0
if [[ "\$PLATFORM" != "macos" && "\$CUDA_ENABLED" -eq 1 && -x "\$CUDA_BIN" ]] \
    && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  if LD_LIBRARY_PATH="\${CUDA_LIBDIR}\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}}" \
      "\$CUDA_BIN" --gpu-selftest --backend cuda >"\$CUDA_LOG" 2>&1; then
    if run_cuda && validate_qwen_wav "\$TMP_OUTPUT"; then
      CUDA_OK=1
      BACKEND="cuda"
    else
      printf '[WARN] CUDA generation failed; retrying once with CPU.\\n' >&2
    fi
  else
    printf '[WARN] CUDA self-test failed; using CPU.\\n' >&2
  fi
fi

if [[ "\$CUDA_OK" -eq 0 ]]; then
  if ! run_cpu; then
    die "Qwen3-TTS CPU generation failed (input text was not logged)"
  fi
  validate_qwen_wav "\$TMP_OUTPUT" || die "Generator produced no valid PCM S16LE/24000 Hz/mono WAV"
fi

if ! restore_paused_units; then
  KEEP_MARKER=1
  die "Previously active ASR units failed to return to their verified ready state; generated audio was not activated"
fi

if [[ -e "\$OUTPUT" && "\$FORCE" -eq 0 ]]; then
  die "Output appeared during generation; refusing to overwrite it without --force"
fi
chmod 0644 "\$TMP_OUTPUT"
if [[ "\${EUID}" -eq 0 && -n "\$TARGET_UID" && -n "\$TARGET_GID" ]]; then
  chown "\${TARGET_UID}:\${TARGET_GID}" "\$TMP_OUTPUT"
fi
mv -f -- "\$TMP_OUTPUT" "\$OUTPUT"
TMP_OUTPUT=""
printf 'Generated WAV: %s (backend=%s, PCM S16LE, 24000 Hz, mono)\\n' "\$OUTPUT" "\$BACKEND"
EOF_GENERATE

  chmod 0755 "$GENERATE_CMD"
  touch "$GENERATE_LOCK"
  chmod 0666 "$GENERATE_LOCK"
}

offline_smoke_tests() {
  local tmp
  tmp="$(mktemp -d /tmp/kienzlefon-qwen-offline-test.XXXXXX)"
  CLEANUP_TMP="$tmp"

  log "Running full offline generation test, including configured ASR stop and verified restoration..."
  "$GENERATE_CMD" \
    --text "Dies ist ein technischer Installationstest." \
    --output "${tmp}/installation-test.wav"
  validate_wav "${tmp}/installation-test.wav" || die "Full offline generation test produced an invalid WAV"

  rm -rf -- "$tmp"
  CLEANUP_TMP=""
}

install_ttfa_helper() {
  local src="${TOOLS_DIR}/kienzlefon_qwen_ttfa.c"
  cat > "$src" <<'C_EOF'
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static double now_sec(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static int send_all(int fd, const char *buf, size_t len) {
    while (len > 0) {
        ssize_t n = send(fd, buf, len, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        buf += (size_t)n;
        len -= (size_t)n;
    }
    return 0;
}

static char *find_bytes(char *buf, size_t len, const char *needle, size_t nlen) {
    if (nlen == 0 || len < nlen) return NULL;
    for (size_t i = 0; i + nlen <= len; i++) {
        if (memcmp(buf + i, needle, nlen) == 0) return buf + i;
    }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "usage: %s <ipv4> <port> <path> <json-body>\n", argv[0]);
        return 2;
    }

    signal(SIGPIPE, SIG_IGN);

    const char *host = argv[1];
    int port = atoi(argv[2]);
    const char *path = argv[3];
    const char *body = argv[4];
    if (port < 1 || port > 65535) {
        fprintf(stderr, "invalid port\n");
        return 2;
    }

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 2; }

    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = htons((unsigned short)port);
    if (inet_pton(AF_INET, host, &sa.sin_addr) != 1) {
        fprintf(stderr, "host must be an IPv4 address\n");
        close(fd);
        return 2;
    }

    if (connect(fd, (struct sockaddr *)&sa, sizeof(sa)) != 0) {
        perror("connect");
        close(fd);
        return 2;
    }

    size_t body_len = strlen(body);
    size_t req_cap = body_len + strlen(path) + 512;
    char *req = malloc(req_cap);
    if (!req) { close(fd); return 2; }
    int req_len = snprintf(req, req_cap,
        "POST %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n\r\n%s",
        path, host, port, body_len, body);
    if (req_len < 0 || (size_t)req_len >= req_cap) {
        fprintf(stderr, "request too large\n");
        free(req); close(fd); return 2;
    }

    double t0 = now_sec();
    if (send_all(fd, req, (size_t)req_len) != 0) {
        perror("send");
        free(req); close(fd); return 2;
    }
    free(req);

    size_t cap = 131072, used = 0;
    char *prefix = malloc(cap);
    if (!prefix) { close(fd); return 2; }

    int first_audio_seen = 0;
    double ttfa = -1.0;
    size_t total_received = 0;
    char recvbuf[32768];

    for (;;) {
        ssize_t n = recv(fd, recvbuf, sizeof(recvbuf), 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            perror("recv");
            free(prefix); close(fd); return 2;
        }
        if (n == 0) break;
        total_received += (size_t)n;

        if (!first_audio_seen) {
            if (used + (size_t)n > cap) {
                size_t newcap = cap * 2;
                while (newcap < used + (size_t)n) newcap *= 2;
                if (newcap > 1048576) {
                    fprintf(stderr, "response prefix too large\n");
                    free(prefix); close(fd); return 2;
                }
                char *tmp = realloc(prefix, newcap);
                if (!tmp) { free(prefix); close(fd); return 2; }
                prefix = tmp; cap = newcap;
            }
            memcpy(prefix + used, recvbuf, (size_t)n);
            used += (size_t)n;

            char *hend = find_bytes(prefix, used, "\r\n\r\n", 4);
            if (hend) {
                size_t header_len = (size_t)(hend - prefix) + 4;
                if (used >= 12 && memcmp(prefix, "HTTP/1.1 200", 12) != 0) {
                    fprintf(stderr, "HTTP request did not return 200\n");
                    free(prefix); close(fd); return 2;
                }
                char *chunk_end = find_bytes(prefix + header_len, used - header_len, "\r\n", 2);
                if (chunk_end) {
                    size_t chunk_line_end = (size_t)(chunk_end - prefix) + 2;
                    if (used > chunk_line_end) {
                        first_audio_seen = 1;
                        ttfa = now_sec() - t0;
                    }
                }
            }
        }
    }

    free(prefix);
    close(fd);

    if (!first_audio_seen || ttfa < 0.0 || total_received == 0) {
        fprintf(stderr, "no streaming PCM observed\n");
        return 2;
    }

    printf("%.6f\n", ttfa);
    return 0;
}
C_EOF

  if [[ "$PLATFORM" == "macos" ]]; then
    clang -O2 -Wall -Wextra -Werror "$src" -o "$TTFA_HELPER"
  else
    gcc -O2 -Wall -Wextra -Werror "$src" -o "$TTFA_HELPER"
  fi
  chmod 0755 "$TTFA_HELPER"
}

service_loaded_or_enabled() {
  if [[ "$SERVICE_KIND" == "launchd" ]]; then
    launchctl print "system/${LABEL}" >/dev/null 2>&1
  else
    systemctl is-enabled --quiet "$SYSTEMD_UNIT_NAME" 2>/dev/null || systemctl is-active --quiet "$SYSTEMD_UNIT_NAME" 2>/dev/null
  fi
}

service_active() {
  if [[ "$SERVICE_KIND" == "launchd" ]]; then
    launchctl print "system/${LABEL}" >/dev/null 2>&1
  else
    systemctl is-active --quiet "$SYSTEMD_UNIT_NAME"
  fi
}

service_stop() {
  if [[ "$SERVICE_KIND" == "launchd" ]]; then
    if launchctl print "system/${LABEL}" >/dev/null 2>&1; then
      launchctl bootout "system/${LABEL}" >/dev/null 2>&1 || true
      local i
      for ((i=0; i<50; i++)); do
        launchctl print "system/${LABEL}" >/dev/null 2>&1 || break
        sleep 0.2
      done
    fi
  else
    systemctl stop "$SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true
  fi
}

service_start() {
  if [[ "$SERVICE_KIND" == "launchd" ]]; then
    launchctl enable "system/${LABEL}" >/dev/null 2>&1 || true
    if launchctl print "system/${LABEL}" >/dev/null 2>&1; then
      launchctl kickstart -k "system/${LABEL}"
    else
      launchctl bootstrap system "$PLIST"
    fi
  else
    systemctl daemon-reload
    systemctl enable "$SYSTEMD_UNIT_NAME" >/dev/null
    systemctl restart "$SYSTEMD_UNIT_NAME"
  fi
}

install_control_command() {
  cat > "$CTL_CMD" <<EOF_CTL
#!/bin/bash
set -Eeuo pipefail
PLATFORM="${PLATFORM}"
LABEL="${LABEL}"
PLIST="${PLIST}"
UNIT="${SYSTEMD_UNIT_NAME}"
LOG_DIR="${LOG_DIR}"

need_root() {
  if [[ "\${EUID}" -ne 0 ]]; then
    exec sudo -- "\$0" "\$@"
  fi
}

if [[ "\$PLATFORM" == "macos" ]]; then
  loaded() { launchctl print "system/\${LABEL}" >/dev/null 2>&1; }
  case "\${1:-status}" in
    start)
      need_root "\$@"
      launchctl enable "system/\${LABEL}" >/dev/null 2>&1 || true
      if loaded; then launchctl kickstart -k "system/\${LABEL}"; else launchctl bootstrap system "\$PLIST"; fi
      ;;
    stop)
      need_root "\$@"
      if loaded; then launchctl bootout "system/\${LABEL}"; fi
      ;;
    restart)
      need_root "\$@"
      if loaded; then launchctl bootout "system/\${LABEL}" >/dev/null 2>&1 || true; fi
      launchctl enable "system/\${LABEL}" >/dev/null 2>&1 || true
      launchctl bootstrap system "\$PLIST"
      ;;
    status)
      if loaded; then launchctl print "system/\${LABEL}"; else echo "\${LABEL}: not loaded"; exit 3; fi
      ;;
    logs)
      exec tail -n 100 -F "\${LOG_DIR}/server.stdout.log" "\${LOG_DIR}/server.stderr.log"
      ;;
    *) echo "Usage: \$0 {start|stop|restart|status|logs}" >&2; exit 2 ;;
  esac
else
  case "\${1:-status}" in
    start)   need_root "\$@"; systemctl start "\$UNIT" ;;
    stop)    need_root "\$@"; systemctl stop "\$UNIT" ;;
    restart) need_root "\$@"; systemctl restart "\$UNIT" ;;
    status)  systemctl status --no-pager "\$UNIT" ;;
    logs)    exec journalctl -u "\$UNIT" -n 100 -f ;;
    *) echo "Usage: \$0 {start|stop|restart|status|logs}" >&2; exit 2 ;;
  esac
fi
EOF_CTL
  chmod 0755 "$CTL_CMD"
}

install_health_command() {
  cat > "$HEALTH_CMD" <<EOF_HEALTH
#!/bin/bash
set -Eeuo pipefail
PLATFORM="${PLATFORM}"
PORT="${PORT}"
URL="http://127.0.0.1:\${PORT}"
LABEL="${LABEL}"
UNIT="${SYSTEMD_UNIT_NAME}"
TMP="\$(mktemp -d /tmp/kienzlefon-qwen-health.XXXXXX)"
trap 'rm -rf "\$TMP"' EXIT

fail() { echo "[FAIL] \$*" >&2; exit 1; }
ok()   { echo "[ OK ] \$*"; }
file_size() {
  if [[ "\$PLATFORM" == "macos" ]]; then stat -f '%z' "\$1"; else stat -c '%s' "\$1"; fi
}
validate_wav() {
  local f="\$1" size
  [[ -f "\$f" ]] || return 1
  size="\$(file_size "\$f")"
  (( size > 44 )) || return 1
  [[ "\$(dd if="\$f" bs=1 count=4 2>/dev/null)" == "RIFF" ]] || return 1
  [[ "\$(dd if="\$f" bs=1 skip=8 count=4 2>/dev/null)" == "WAVE" ]] || return 1
}

if [[ "\$PLATFORM" == "macos" ]]; then
  launchctl print "system/\${LABEL}" >/dev/null 2>&1 || fail "launchd service is not loaded"
  ok "launchd service loaded"
else
  systemctl is-active --quiet "\$UNIT" || fail "systemd service is not active"
  ok "systemd service active"
fi

curl -fsS --max-time 10 "\${URL}/v1/health" >"\${TMP}/health.json" || fail "/v1/health"
ok "/v1/health"

BODY='{"text":"Guten Tag. Wie kann ich Ihnen helfen?","speaker":"ryan","language":"German","seed":42}'
curl -fsS --max-time 180 -H 'Content-Type: application/json' -d "\$BODY" \
  "\${URL}/v1/tts" -o "\${TMP}/test.wav" || fail "/v1/tts request"
validate_wav "\${TMP}/test.wav" || fail "/v1/tts returned invalid WAV"
ok "German Ryan WAV synthesis"

OPENAI='{"input":"Guten Tag. Wie kann ich Ihnen helfen?","voice":"ryan","language":"German","seed":42}'
curl -fsS --max-time 180 -H 'Content-Type: application/json' -d "\$OPENAI" \
  "\${URL}/v1/audio/speech" -o "\${TMP}/openai.wav" || fail "/v1/audio/speech request"
validate_wav "\${TMP}/openai.wav" || fail "/v1/audio/speech returned invalid WAV"
ok "OpenAI-compatible WAV endpoint"

curl -fsSN --max-time 180 -D "\${TMP}/stream.headers" -H 'Content-Type: application/json' -d "\$BODY" \
  "\${URL}/v1/tts/stream" -o "\${TMP}/stream.pcm" || fail "/v1/tts/stream request"
[[ -s "\${TMP}/stream.pcm" ]] || fail "stream contained no PCM"
bytes="\$(file_size "\${TMP}/stream.pcm")"
(( bytes % 2 == 0 )) || fail "stream byte count is not valid s16le"
grep -qi '^Content-Type: audio/pcm' "\${TMP}/stream.headers" || fail "stream Content-Type is not audio/pcm"
grep -qi '^X-Sample-Rate: 24000' "\${TMP}/stream.headers" || fail "stream sample rate is not 24000"
grep -qi '^X-Sample-Format: s16le' "\${TMP}/stream.headers" || fail "stream format is not s16le"
grep -qi '^X-Channels: 1' "\${TMP}/stream.headers" || fail "stream is not mono"
ok "streaming PCM: s16le / 24000 Hz / mono (\${bytes} bytes)"

echo "Qwen3-TTS healthcheck passed."
EOF_HEALTH
  chmod 0755 "$HEALTH_CMD"
}

install_benchmark_command() {
  local gpu_backend gpu_label cuda_env cuda_batch_env plausibility
  if [[ "$PLATFORM" == "macos" ]]; then
    gpu_backend="metal"
    gpu_label="Metal"
    cuda_env=""
    cuda_batch_env=""
    plausibility="Upstream M4 reference only: CPU INT4 ~RTF 0.32; Metal INT4 ~RTF 0.28."
  else
    gpu_backend="cuda"
    gpu_label="CUDA"
    cuda_env="QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1"
    if (( BATCH_SIZE > 1 )); then cuda_batch_env="QWEN_CUDA_BATCH=1"; else cuda_batch_env=""; fi
    plausibility="CUDA results vary strongly by GPU; upstream reports 0.6B ~RTF 0.39 on A100 as one reference point."
  fi

  cat > "$BENCH_CMD" <<EOF_BENCH
#!/bin/bash
# Reproducible Kienzlefon Qwen3-TTS benchmark for ${PLATFORM}.
set -Eeuo pipefail
IFS=\$'\\n\\t'

PLATFORM="${PLATFORM}"
LABEL="${LABEL}"
PLIST="${PLIST}"
UNIT="${SYSTEMD_UNIT_NAME}"
BIN="${BINARY}"
TTFA="${TTFA_HELPER}"
MODEL="${MODEL_DIR}"
PORT="${PORT}"
THREADS="${THREADS}"
BATCH="${BATCH_SIZE}"
CUDA_LIBDIR="${CUDA_LIBDIR}"
GPU_BACKEND="${gpu_backend}"
GPU_LABEL="${gpu_label}"
LOG_DIR="${LOG_DIR}"
TEST_TEXT='${TEST_TEXT}'
SEED='${TEST_SEED}'
URL="http://127.0.0.1:\${PORT}"

if [[ "\${EUID}" -ne 0 ]]; then exec sudo -- "\$0" "\$@"; fi

if [[ "\$PLATFORM" == "ubuntu" && -n "\$CUDA_LIBDIR" ]]; then
  export LD_LIBRARY_PATH="\${CUDA_LIBDIR}\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}}"
fi

TMP="\$(mktemp -d /tmp/kienzlefon-qwen-bench.XXXXXX)"
RESULTS="\${TMP}/results.tsv"
: >"\$RESULTS"

service_was_active=0
server_pid=""
sampler_pid=""

service_is_active() {
  if [[ "\$PLATFORM" == "macos" ]]; then
    launchctl print "system/\${LABEL}" >/dev/null 2>&1
  else
    systemctl is-active --quiet "\$UNIT"
  fi
}
service_stop() {
  if [[ "\$PLATFORM" == "macos" ]]; then
    launchctl bootout "system/\${LABEL}" >/dev/null 2>&1 || true
  else
    systemctl stop "\$UNIT" >/dev/null 2>&1 || true
  fi
}
service_restore() {
  if [[ "\$PLATFORM" == "macos" ]]; then
    launchctl enable "system/\${LABEL}" >/dev/null 2>&1 || true
    if launchctl print "system/\${LABEL}" >/dev/null 2>&1; then
      launchctl kickstart -k "system/\${LABEL}" >/dev/null 2>&1 || true
    else
      launchctl bootstrap system "\$PLIST" >/dev/null 2>&1 || true
    fi
  else
    systemctl start "\$UNIT" >/dev/null 2>&1 || true
  fi
}

if service_is_active; then service_was_active=1; fi

cleanup() {
  set +e
  if [[ -n "\$server_pid" ]]; then
    kill "\$server_pid" >/dev/null 2>&1 || true
    wait "\$server_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "\$sampler_pid" ]]; then
    wait "\$sampler_pid" >/dev/null 2>&1 || { kill "\$sampler_pid" >/dev/null 2>&1 || true; }
  fi
  if (( service_was_active == 1 )); then service_restore; fi
  rm -rf "\$TMP"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_health() {
  local i
  for ((i=1; i<=180; i++)); do
    curl -fsS --max-time 2 "\${URL}/v1/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

file_size() {
  if [[ "\$PLATFORM" == "macos" ]]; then stat -f '%z' "\$1"; else stat -c '%s' "\$1"; fi
}
validate_wav() {
  local f="\$1" size
  [[ -f "\$f" ]] || return 1
  size="\$(file_size "\$f")"
  (( size > 44 )) || return 1
  [[ "\$(dd if="\$f" bs=1 count=4 2>/dev/null)" == "RIFF" ]] || return 1
  [[ "\$(dd if="\$f" bs=1 skip=8 count=4 2>/dev/null)" == "WAVE" ]] || return 1
}

stop_temp_server() {
  if [[ -n "\$server_pid" ]]; then
    kill "\$server_pid" >/dev/null 2>&1 || true
    wait "\$server_pid" >/dev/null 2>&1 || true
    server_pid=""
  fi
  if [[ -n "\$sampler_pid" ]]; then
    wait "\$sampler_pid" >/dev/null 2>&1 || true
    sampler_pid=""
  fi
}

start_sampler() {
  local pid="\$1" out="\$2"
  (
    max=0
    while kill -0 "\$pid" >/dev/null 2>&1; do
      rss="\$(ps -o rss= -p "\$pid" 2>/dev/null | tr -d ' ')"
      case "\$rss" in ''|*[!0-9]*) ;; *) (( rss > max )) && max="\$rss" ;; esac
      sleep 0.1
    done
    echo "\$max" >"\$out"
  ) &
  sampler_pid=\$!
}

run_mode() {
  local name="\$1" backend="\$2" quant="\$3"
  local wav="\${TMP}/\${name}.wav"
  local slog="\${TMP}/\${name}.server.log"
  local rssfile="\${TMP}/\${name}.rss"
  local body gen_time bytes data_bytes audio_s rtf realtime ttfa_s rss_kb rss_mib

  echo
  echo "=== \${name} ==="

  if [[ "\$backend" == "metal" ]]; then
    QWEN_METAL_FUSED_TALKER=1 "\$BIN" -d "\$MODEL" "--\${quant}" -j "\$THREADS" \
      --backend metal --serve "\$PORT" --batch-size "\$BATCH" >"\$slog" 2>&1 &
  elif [[ "\$backend" == "cuda" ]]; then
    if (( BATCH > 1 )); then
      QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1 QWEN_CUDA_BATCH=1 \
        "\$BIN" -d "\$MODEL" "--\${quant}" -j "\$THREADS" --backend cuda \
        --serve "\$PORT" --batch-size "\$BATCH" >"\$slog" 2>&1 &
    else
      QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1 \
        "\$BIN" -d "\$MODEL" "--\${quant}" -j "\$THREADS" --backend cuda \
        --serve "\$PORT" --batch-size "\$BATCH" >"\$slog" 2>&1 &
    fi
  else
    "\$BIN" -d "\$MODEL" "--\${quant}" -j "\$THREADS" \
      --serve "\$PORT" --batch-size "\$BATCH" >"\$slog" 2>&1 &
  fi
  server_pid=\$!
  start_sampler "\$server_pid" "\$rssfile"

  if ! wait_health; then
    echo "Server failed to become healthy. Log:" >&2
    tail -n 80 "\$slog" >&2 || true
    return 1
  fi

  body="{\"text\":\"\${TEST_TEXT}\",\"speaker\":\"ryan\",\"language\":\"German\",\"seed\":\${SEED}}"

  # Non-measured warm-up: compare steady-state resident-server performance.
  curl -fsS --max-time 240 -H 'Content-Type: application/json' -d "\$body" \
    "\${URL}/v1/tts" -o /dev/null

  gen_time="\$(curl -fsS --max-time 240 -H 'Content-Type: application/json' -d "\$body" \
    -o "\$wav" -w '%{time_total}' "\${URL}/v1/tts")"
  validate_wav "\$wav" || { echo "Invalid WAV from \${name}" >&2; return 1; }

  bytes="\$(file_size "\$wav")"
  data_bytes=\$(( bytes - 44 ))
  audio_s="\$(awk -v b="\$data_bytes" 'BEGIN { printf "%.6f", b / 48000.0 }')"
  rtf="\$(awk -v g="\$gen_time" -v a="\$audio_s" 'BEGIN { if (a>0) printf "%.4f", g/a; else print "nan" }')"
  realtime="\$(awk -v r="\$rtf" 'BEGIN { if (r>0) printf "%.3f", 1/r; else print "nan" }')"

  ttfa_s="\$("\$TTFA" 127.0.0.1 "\$PORT" /v1/tts/stream "\$body")"

  stop_temp_server
  rss_kb="\$(cat "\$rssfile" 2>/dev/null || echo 0)"
  case "\$rss_kb" in ''|*[!0-9]*) rss_kb=0 ;; esac
  rss_mib="\$(awk -v k="\$rss_kb" 'BEGIN { printf "%.1f", k/1024.0 }')"

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "\$name" "\$audio_s" "\$gen_time" "\$rtf" "\$realtime" "\$ttfa_s" "\$rss_mib" >>"\$RESULTS"

  echo "Audio:      \${audio_s} s"
  echo "Generation: \${gen_time} s"
  echo "RTF:        \${rtf}"
  echo "x realtime: \${realtime}x"
  echo "TTFA:       \${ttfa_s} s"
  echo "Peak RSS:   \${rss_mib} MiB (process RSS; GPU VRAM is not included)"
}

if (( service_was_active == 1 )); then
  service_stop
  for ((i=0; i<50; i++)); do
    service_is_active || break
    sleep 0.2
  done
fi

if lsof -nP -iTCP:"\$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port \${PORT} is still in use; refusing benchmark." >&2
  lsof -nP -iTCP:"\$PORT" -sTCP:LISTEN >&2 || true
  exit 1
fi

run_mode "cpu-int4" cpu int4
run_mode "cpu-int8" cpu int8
run_mode "${gpu_backend}-int4" "${gpu_backend}" int4
run_mode "${gpu_backend}-int8" "${gpu_backend}" int8

echo
echo "Qwen3-TTS 0.6B benchmark summary"
echo "Text: \${TEST_TEXT}"
echo "Speaker: ryan | Language: German | Seed: \${SEED} | Threads: \${THREADS} | Batch: \${BATCH}"
printf '%-12s %10s %10s %8s %10s %10s %12s\n' "Mode" "Audio(s)" "Gen(s)" "RTF" "xRealtime" "TTFA(s)" "PeakRSS(MiB)"
awk -F '\\t' '{ printf "%-12s %10s %10s %8s %10s %10s %12s\\n", \$1,\$2,\$3,\$4,\$5,\$6,\$7 }' "\$RESULTS"

echo
echo "${plausibility}"
echo "Reference values are informational only and never decide installation success."
EOF_BENCH
  chmod 0755 "$BENCH_CMD"
}

write_service_definition() {
  if [[ "$PLATFORM" == "macos" ]]; then
    log "Installing launchd service (${LABEL})..."
    local tmp
    tmp="$(mktemp /tmp/${LABEL}.plist.XXXXXX)"
    cat > "$tmp" <<EOF_PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${BINARY}</string>
    <string>-d</string>
    <string>${MODEL_DIR}</string>
    <string>--int4</string>
    <string>-j</string>
    <string>${THREADS}</string>
    <string>--serve</string>
    <string>${PORT}</string>
    <string>--batch-size</string>
    <string>${BATCH_SIZE}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${BASE_DIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>${LOG_DIR}/server.stdout.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/server.stderr.log</string>
</dict>
</plist>
EOF_PLIST
    plutil -lint "$tmp" >/dev/null
    service_stop
    install -o root -g wheel -m 0644 "$tmp" "$PLIST"
    rm -f "$tmp"
  else
    log "Installing systemd service (${SYSTEMD_UNIT_NAME}) with CUDA INT4 as default backend..."
    service_stop
    local cuda_batch_env=""
    if (( BATCH_SIZE > 1 )); then
      cuda_batch_env="Environment=QWEN_CUDA_BATCH=1"
    fi
    cat > "$SYSTEMD_UNIT" <<EOF_SYSTEMD
[Unit]
Description=Kienzlefon Qwen3-TTS 0.6B CUDA service
After=local-fs.target network.target

[Service]
Type=simple
WorkingDirectory=${BASE_DIR}
Environment=LD_LIBRARY_PATH=${CUDA_LIBDIR}
Environment=QWEN_CUDA_FUSED_TALKER=1
Environment=QWEN_CUDA_CONVDEC=1
${cuda_batch_env}
ExecStart=${BINARY} -d ${MODEL_DIR} --int4 -j ${THREADS} --backend cuda --serve ${PORT} --batch-size ${BATCH_SIZE}
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/server.stdout.log
StandardError=append:${LOG_DIR}/server.stderr.log

[Install]
WantedBy=multi-user.target
EOF_SYSTEMD
    chmod 0644 "$SYSTEMD_UNIT"
    systemctl daemon-reload
  fi
}

port_must_be_free() {
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "TCP port ${PORT} is already in use:"
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
    die "Port ${PORT} must be free after stopping the Qwen3-TTS service."
  fi
}

backend_smoke_tests() {
  log "Smoke-testing CPU INT4 backend..."
  local tmp
  tmp="$(mktemp -d /tmp/kienzlefon-qwen-backend.XXXXXX)"
  CLEANUP_TMP="$tmp"

  if ! run_binary -d "$MODEL_DIR" --int4 -j "$THREADS" \
    -s ryan -l German --seed "$TEST_SEED" \
    --text "Guten Tag. Dies ist ein kurzer CPU-Test." -o "${tmp}/cpu.wav" >/dev/null 2>"${tmp}/cpu.log"; then
    cat "${tmp}/cpu.log" >&2 || true
    die "CPU INT4 smoke test failed"
  fi
  validate_wav "${tmp}/cpu.wav" || { cat "${tmp}/cpu.log" >&2; die "CPU INT4 smoke test produced invalid WAV"; }

  if [[ "$PLATFORM" == "macos" ]]; then
    log "Smoke-testing Metal backend..."
    run_binary --gpu-selftest --backend metal >/dev/null 2>"${tmp}/metal-selftest.log" || {
      cat "${tmp}/metal-selftest.log" >&2 || true; die "Metal GPU self-test failed";
    }
    if ! QWEN_METAL_FUSED_TALKER=1 "$BINARY" -d "$MODEL_DIR" --int4 -j "$THREADS" --backend metal \
      -s ryan -l German --seed "$TEST_SEED" \
      --text "Guten Tag. Dies ist ein kurzer Metal-Test." -o "${tmp}/metal.wav" >/dev/null 2>"${tmp}/metal.log"; then
      cat "${tmp}/metal.log" >&2 || true
      die "Metal INT4 smoke test failed"
    fi
    validate_wav "${tmp}/metal.wav" || { cat "${tmp}/metal.log" >&2; die "Metal INT4 smoke test produced invalid WAV"; }
  else
    log "Smoke-testing CUDA backend..."
    LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
      "$BINARY" --gpu-selftest --backend cuda >/dev/null 2>"${tmp}/cuda-selftest.log" || {
        cat "${tmp}/cuda-selftest.log" >&2 || true; die "CUDA GPU self-test failed";
      }
    if ! QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1 \
      LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
      "$BINARY" -d "$MODEL_DIR" --int4 -j "$THREADS" --backend cuda \
      -s ryan -l German --seed "$TEST_SEED" \
      --text "Guten Tag. Dies ist ein kurzer CUDA-Test." -o "${tmp}/cuda.wav" >/dev/null 2>"${tmp}/cuda.log"; then
      cat "${tmp}/cuda.log" >&2 || true
      die "CUDA INT4 smoke test failed"
    fi
    validate_wav "${tmp}/cuda.wav" || { cat "${tmp}/cuda.log" >&2; die "CUDA INT4 smoke test produced invalid WAV"; }
  fi

  rm -rf "$tmp"
  CLEANUP_TMP=""
}

start_and_healthcheck_service() {
  port_must_be_free
  service_start
  wait_for_health "http://127.0.0.1:${PORT}" 180 || {
    tail -n 120 "${LOG_DIR}/server.stderr.log" >&2 || true
    if [[ "$PLATFORM" == "ubuntu" ]]; then journalctl -u "$SYSTEMD_UNIT_NAME" -n 120 --no-pager >&2 || true; fi
    die "Qwen3-TTS service did not become healthy on port ${PORT}"
  }

  log "Running API healthcheck..."
  "$HEALTH_CMD"

  if [[ "$PLATFORM" == "macos" ]]; then
    log "Verifying launchd unload/reload cycle..."
  else
    log "Verifying systemd stop/start cycle and boot enablement..."
  fi

  service_stop
  port_must_be_free
  service_start
  wait_for_health "http://127.0.0.1:${PORT}" 180 || die "Service failed after service-manager reload"
  "$HEALTH_CMD" >/dev/null

  if [[ "$PLATFORM" == "ubuntu" ]]; then
    systemctl is-enabled --quiet "$SYSTEMD_UNIT_NAME" || die "systemd unit is not enabled for boot"
  fi
  log "Service-manager restart check passed."
}

run_benchmark() {
  local report latest
  report="${LOG_DIR}/benchmark-$(date '+%Y%m%d-%H%M%S').txt"
  latest="${LOG_DIR}/benchmark-latest.txt"

  if [[ "$PLATFORM" == "macos" ]]; then
    log "Running reproducible CPU/Metal INT4/INT8 benchmark..."
  else
    log "Running reproducible CPU/CUDA INT4/INT8 benchmark..."
  fi
  "$BENCH_CMD" | tee "$report"
  cp "$report" "$latest"
  chmod 0644 "$report" "$latest"
}

write_offline_install_metadata() {
  local commit preferred_backend
  commit="$(git -C "$SRC_DIR" rev-parse HEAD)"
  preferred_backend="$([[ "$CUDA_AVAILABLE" -eq 1 ]] && echo cuda || echo cpu)"
  cat > "${STATE_DIR}/offline-install-info.txt" <<EOF_OFFLINE_INFO
installer_version=${VERSION}
installed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
install_mode=offline-one-shot
platform=${PLATFORM}
os_version=${OS_VERSION}
architecture=${ARCH}
repo=${REPO_URL}
git_commit=${commit}
model=${MODEL_HF_ID}
source_dir=${SRC_DIR}
cpu_binary=${CPU_BINARY}
cuda_binary=${CUDA_BINARY}
cuda_available=${CUDA_AVAILABLE}
generator=${GENERATE_CMD}
model_dir=${MODEL_DIR}
threads=${THREADS}
preferred_backend=${preferred_backend}
fallback_backend=cpu
default_quantization=int4
speaker=ryan
language=German
seed=${TEST_SEED}
output_format=wav-pcm-s16le
output_rate=24000
output_channels=1
qwen_service_action=none
pause_units=$(pause_units_csv)
maintenance_marker=${MAINTENANCE_MARKER}
min_available_kib=${MIN_GENERATE_AVAILABLE_KIB}
stop_timeout_seconds=${STOP_TIMEOUT_SECONDS}
readiness_timeout_seconds=${READINESS_TIMEOUT_SECONDS}
installation_generation_test=passed
listener_action=none
cuda_home=${CUDA_HOME}
cuda_libdir=${CUDA_LIBDIR}
cuda_arch=${CUDA_ARCH}
cuda_gpu=${CUDA_GPU_NAME}
EOF_OFFLINE_INFO
  chmod 0644 "${STATE_DIR}/offline-install-info.txt"
}

print_offline_summary() {
  local commit preferred_backend existing_service
  commit="$(git -C "$SRC_DIR" rev-parse HEAD)"
  preferred_backend="$([[ "$CUDA_AVAILABLE" -eq 1 ]] && echo cuda || echo cpu)"
  existing_service="none detected"
  if [[ -e "$PLIST" || -e "$SYSTEMD_UNIT" ]]; then
    existing_service="present and deliberately unchanged"
  fi

  cat <<EOF_OFFLINE_SUMMARY

====================================================================
Kienzlefon Qwen3-TTS 0.6B offline installation complete
====================================================================

Platform          : ${PLATFORM} ${OS_VERSION} / ${ARCH}
Installation path : ${BASE_DIR}
Source path       : ${SRC_DIR}
CPU binary        : ${CPU_BINARY}
CUDA binary       : $([[ "$CUDA_AVAILABLE" -eq 1 ]] && echo "$CUDA_BINARY" || echo "not installed/usable")
Model             : ${MODEL_HF_ID}
Model path        : ${MODEL_DIR}
Git commit        : ${commit}  (recorded only; not pinned/auto-updated)
Generator         : ${GENERATE_CMD}
Preferred backend : ${preferred_backend}
Fallback backend  : CPU INT4
Default voice     : ryan
Default language  : German
Default seed      : ${TEST_SEED}
Output format     : WAV, PCM S16LE, 24000 Hz, mono
Qwen service      : none
Paused ASR units  : $([[ ${#PAUSE_UNITS[@]} -gt 0 ]] && pause_units_csv || echo "none detected")
RAM preflight     : 5 GiB MemAvailable after ASR stop (Linux)
Stop timeout      : ${STOP_TIMEOUT_SECONDS} seconds
Readiness timeout : ${READINESS_TIMEOUT_SECONDS} seconds
Install E2E test  : passed (ASR stop/generate/restore path)
Port/listener     : none created by offline-only mode
Existing Qwen svc.: ${existing_service}
Resident RAM/VRAM : none after each generator process exits

Example:
  sudo ${GENERATE_CMD} \
    --text "Unsere Praxis ist heute geschlossen." \
    --output /tmp/ansage.wav

Replace an existing WAV atomically:
  sudo ${GENERATE_CMD} \
    --text "Unsere Praxis ist heute geschlossen." \
    --output /tmp/ansage.wav \
    --force

Uninstall  : sudo ${SCRIPT_NAME} --uninstall
Keep model : sudo ${SCRIPT_NAME} --uninstall --keep-model

Note: --offline-only starts no Qwen HTTP server and opens no port. A pre-existing
Qwen service remains unchanged. During each generation, only the listed ASR units
that were active are stopped temporarily and verified before the WAV is activated.
====================================================================
EOF_OFFLINE_SUMMARY
}

write_install_metadata() {
  local commit gpu_backend
  commit="$(git -C "$SRC_DIR" rev-parse HEAD)"
  if [[ "$PLATFORM" == "macos" ]]; then gpu_backend="metal"; else gpu_backend="cuda"; fi
  cat > "${STATE_DIR}/install-info.txt" <<EOF_INFO
installer_version=${VERSION}
installed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
platform=${PLATFORM}
os_version=${OS_VERSION}
architecture=${ARCH}
repo=${REPO_URL}
git_commit=${commit}
model=${MODEL_HF_ID}
source_dir=${SRC_DIR}
binary=${BINARY}
model_dir=${MODEL_DIR}
port=${PORT}
threads=${THREADS}
batch_size=${BATCH_SIZE}
default_backend=$([[ "$PLATFORM" == "ubuntu" ]] && echo cuda || echo cpu)
default_quantization=int4
optional_gpu_backend=${gpu_backend}
speaker=ryan
language=German
stream_format=s16le
stream_rate=24000
stream_channels=1
cuda_home=${CUDA_HOME}
cuda_libdir=${CUDA_LIBDIR}
cuda_arch=${CUDA_ARCH}
cuda_gpu=${CUDA_GPU_NAME}
EOF_INFO
  chmod 0644 "${STATE_DIR}/install-info.txt"
}

print_summary() {
  local commit gpu_modes service_desc service_file
  commit="$(git -C "$SRC_DIR" rev-parse HEAD)"
  if [[ "$PLATFORM" == "macos" ]]; then
    gpu_modes="Metal INT4 / Metal INT8"
    service_desc="launchd: ${LABEL}"
    service_file="$PLIST"
  else
    gpu_modes="CUDA INT4 / CUDA INT8"
    service_desc="systemd: ${SYSTEMD_UNIT_NAME}"
    service_file="$SYSTEMD_UNIT"
  fi

  cat <<EOF_SUMMARY

====================================================================
Kienzlefon Qwen3-TTS 0.6B installation complete
====================================================================

Platform          : ${PLATFORM} ${OS_VERSION} / ${ARCH}
Installation path : ${BASE_DIR}
Source path       : ${SRC_DIR}
Binary            : ${BINARY}
Model             : ${MODEL_HF_ID}
Model path        : ${MODEL_DIR}
Git commit        : ${commit}  (recorded only; not pinned/auto-updated)
Server port       : ${PORT} (upstream binds all IPv4 interfaces)
Local server URL  : http://127.0.0.1:${PORT}
Service           : ${service_desc}
Service file      : ${service_file}
Default mode      : ${STANDARD_MODE}, ${THREADS} threads, batch size ${BATCH_SIZE}
Available modes   : CPU INT4 / CPU INT8 / ${gpu_modes}
Default API voice : ryan
Kienzlefon lang.  : German (send explicitly per request)
Streaming format  : raw PCM s16le, 24000 Hz, mono
EOF_SUMMARY

  if [[ "$PLATFORM" == "ubuntu" ]]; then
    cat <<EOF_CUDA
CUDA GPU          : ${CUDA_GPU_NAME}
CUDA Toolkit      : ${CUDA_HOME}
CUDA build arch   : ${CUDA_ARCH}
Note              : CUDA is the default service backend; CPU remains available for benchmark/fallback.
EOF_CUDA
  else
    echo "Note              : Metal is available but NOT used by the default service."
  fi

  cat <<EOF_REQUESTS

Primary streaming request:
  curl -sN http://127.0.0.1:${PORT}/v1/tts/stream \\
    -H 'Content-Type: application/json' \\
    -d '{"text":"Guten Tag. Wie kann ich Ihnen helfen?","speaker":"ryan","language":"German"}' \\
    -o output.pcm

Full WAV request:
  curl -s http://127.0.0.1:${PORT}/v1/tts \\
    -H 'Content-Type: application/json' \\
    -d '{"text":"Guten Tag. Wie kann ich Ihnen helfen?","speaker":"ryan","language":"German"}' \\
    -o output.wav

OpenAI-compatible WAV request:
  curl -s http://127.0.0.1:${PORT}/v1/audio/speech \\
    -H 'Content-Type: application/json' \\
    -d '{"input":"Guten Tag. Wie kann ich Ihnen helfen?","voice":"ryan","language":"German"}' \\
    -o output-openai.wav

Healthcheck : ${HEALTH_CMD}
Benchmark   : sudo ${BENCH_CMD}
Status      : ${CTL_CMD} status
Start       : sudo ${CTL_CMD} start
Stop        : sudo ${CTL_CMD} stop
Restart     : sudo ${CTL_CMD} restart
Logs        : ${CTL_CMD} logs
Uninstall   : sudo ${SCRIPT_NAME} --uninstall
Keep model  : sudo ${SCRIPT_NAME} --uninstall --keep-model

Benchmark report:
  ${LOG_DIR}/benchmark-latest.txt
====================================================================
EOF_REQUESTS

  if [[ -f "${LOG_DIR}/benchmark-latest.txt" ]]; then
    echo
    echo "Latest benchmark:"
    cat "${LOG_DIR}/benchmark-latest.txt"
  fi
}

main() {
  if (( UNINSTALL == 1 )); then
    uninstall_all
    return 0
  fi

  log "Starting Kienzlefon Qwen3-TTS cross-platform installer v${VERSION}"
  check_platform_and_tools
  prepare_directories
  install_source

  if (( OFFLINE_ONLY == 1 )); then
    log "Offline-only mode selected: no service definition, autostart, HTTP server, or listener will be created."
    detect_pause_units
    build_offline_cpu_binary
    build_offline_cuda_binary
    download_model
    write_offline_env_file
    install_generate_command
    offline_smoke_tests
    write_offline_install_metadata
    print_offline_summary
    return 0
  fi

  build_binary
  download_model
  write_env_file
  install_ttfa_helper
  install_control_command
  install_health_command
  install_benchmark_command
  write_service_definition
  backend_smoke_tests
  start_and_healthcheck_service

  if (( RUN_BENCHMARK == 1 )); then
    run_benchmark
    wait_for_health "http://127.0.0.1:${PORT}" 180 || die "Service was not healthy after benchmark restoration"
  else
    warn "Benchmark skipped by request. Run later with: sudo ${BENCH_CMD}"
  fi

  write_install_metadata
  print_summary
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
