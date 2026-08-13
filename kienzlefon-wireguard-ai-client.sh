#!/usr/bin/env bash
# Kienzlefon WireGuard KI-Client
# Version: 1.0
set -Eeuo pipefail
umask 077

WG_IF="wg0"

DEFAULT_CLIENT_IP="10.88.0.50"
DEFAULT_VPS_WG_IP="10.88.0.1"
DEFAULT_WG_PORT="51820"

die() {
    echo "FEHLER: $*" >&2
    exit 1
}

ask_yes_no() {
    local prompt="$1"
    local default="${2:-n}"
    local answer

    if [[ "$default" == "j" ]]; then
        read -r -p "$prompt [J/n]: " answer
        answer="${answer:-j}"
    else
        read -r -p "$prompt [j/N]: " answer
        answer="${answer:-n}"
    fi

    [[ "$answer" =~ ^[JjYy]$ ]]
}

ask_value() {
    local prompt="$1"
    local default="$2"
    local value
    read -r -p "$prompt [$default]: " value
    printf '%s' "${value:-$default}"
}

require_root() {
    [[ "$(id -u)" -eq 0 ]] || die "Bitte als root ausführen."
}

install_wireguard() {
    if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then
        echo "WireGuard ist bereits installiert."
        return
    fi

    if ask_yes_no "WireGuard jetzt installieren?" "j"; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y wireguard wireguard-tools
    else
        die "WireGuard wird benötigt."
    fi
}

main() {
    require_root

    echo "============================================================"
    echo " Kienzlefon WireGuard KI-Client"
    echo "============================================================"
    echo
    echo "Der Tunnel erhält KEINE Default-Route."
    echo "Über WireGuard wird nur die VPN-IP des VPS erreicht."
    echo

    install_wireguard

    local config="/etc/wireguard/${WG_IF}.conf"
    local backup=""

    if [[ -e "$config" ]]; then
        echo
        echo "Es existiert bereits: $config"
        if ask_yes_no "Bestehende Datei sichern und ersetzen?" "n"; then
            backup="${config}.backup-$(date +%Y%m%d-%H%M%S)"
            cp -a "$config" "$backup"
            echo "Sicherung: $backup"
            systemctl stop "wg-quick@${WG_IF}" 2>/dev/null || true
        else
            die "Abgebrochen."
        fi
    fi

    echo
    read -r -p "Öffentliche IPv4-Adresse oder DNS-Name des VPS: " VPS_ENDPOINT
    [[ -n "$VPS_ENDPOINT" ]] || die "VPS-Adresse fehlt."

    WG_PORT="$(ask_value "WireGuard-Port des VPS" "$DEFAULT_WG_PORT")"
    VPS_WG_IP="$(ask_value "WireGuard-IP des VPS" "$DEFAULT_VPS_WG_IP")"
    CLIENT_IP="$(ask_value "WireGuard-IP dieses KI-Systems" "$DEFAULT_CLIENT_IP")"

    echo
    read -r -p "PublicKey des VPS: " VPS_PUBLIC_KEY
    [[ -n "$VPS_PUBLIC_KEY" ]] || die "VPS-PublicKey fehlt."

    echo
    echo "PresharedKey:"
    echo "  1) Neuen Schlüssel hier erzeugen"
    echo "  2) Vorhandenen Schlüssel eingeben"
    read -r -p "Auswahl [1]: " PSK_MODE
    PSK_MODE="${PSK_MODE:-1}"

    case "$PSK_MODE" in
        1)
            PSK="$(wg genpsk)"
            ;;
        2)
            read -r -s -p "PresharedKey: " PSK
            echo
            [[ -n "$PSK" ]] || die "PresharedKey fehlt."
            ;;
        *)
            die "Ungültige Auswahl."
            ;;
    esac

    CLIENT_PRIVATE_KEY="$(wg genkey)"
    CLIENT_PUBLIC_KEY="$(printf '%s' "$CLIENT_PRIVATE_KEY" | wg pubkey)"

    mkdir -p /etc/wireguard
    chmod 700 /etc/wireguard

    cat > "$config" <<EOF
[Interface]
Address = ${CLIENT_IP}/32
PrivateKey = ${CLIENT_PRIVATE_KEY}

[Peer]
PublicKey = ${VPS_PUBLIC_KEY}
PresharedKey = ${PSK}
Endpoint = ${VPS_ENDPOINT}:${WG_PORT}
AllowedIPs = ${VPS_WG_IP}/32
PersistentKeepalive = 25
EOF

    chmod 600 "$config"

    echo
    echo "Konfiguration geschrieben:"
    echo "  $config"
    echo

    if ask_yes_no "WireGuard jetzt aktivieren und beim Booten starten?" "j"; then
        systemctl enable "wg-quick@${WG_IF}"
        systemctl restart "wg-quick@${WG_IF}"
    fi

    echo
    echo "============================================================"
    echo " PEER-BLOCK FÜR DEN VPS"
    echo "============================================================"
    echo
    cat <<EOF
[Peer]
# KI-System
PublicKey = ${CLIENT_PUBLIC_KEY}
PresharedKey = ${PSK}
AllowedIPs = ${CLIENT_IP}/32
EOF

    echo
    echo "============================================================"
    echo " KI-SYSTEM-KONFIGURATION"
    echo "============================================================"
    echo
    cat "$config"

    echo
    echo "============================================================"
    echo " TEST"
    echo "============================================================"
    echo
    echo "Nach Ergänzung des Peer-Blocks auf dem VPS:"
    echo "  ping -c 3 ${VPS_WG_IP}"
    echo
    echo "Status:"
    echo "  wg show"
    echo
    echo "Routing-Kontrolle:"
    echo "  ip route"
    echo
    echo "Es darf KEINE Default-Route über ${WG_IF} vorhanden sein."
}

main "$@"
