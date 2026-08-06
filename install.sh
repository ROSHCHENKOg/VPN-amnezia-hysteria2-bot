#!/bin/bash
# AmneziaWG server installer
# Usage: bash install.sh
# Installs awg, generates server keys, creates awg0 interface, starts service

set -e

INTERFACE="awg0"
WG_DIR="/etc/amnezia/amneziawg"
WG_CONFIG="$WG_DIR/${INTERFACE}.conf"
PORT=51820
SUBNET="10.8.0.0/24"
SERVER_IP="10.8.0.1/24"

# AmneziaWG obfuscation params (must match across all servers)
JC=5
JMIN=10
JMAX=50
S1=95
S2=42
S3=14
S4=3
H1="1801680827-1998653040"
H2="2142741064-2144902292"
H3="2146093884-2146220331"
H4="2146616603-2147215006"

echo "=== AmneziaWG Installer ==="
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash install.sh"
    exit 1
fi

# Detect network interface (ens3, eth0, etc.)
NET_IFACE=$(ip route get 8.8.8.8 2>/dev/null | grep -oP 'dev \K\S+' || echo "eth0")
echo "Network interface: $NET_IFACE"

# Install packages
echo ""
echo "Installing packages..."
apt-get update -qq
apt-get install -y -qq wireguard-tools qrencode > /dev/null 2>&1

# Install AmneziaWG
if ! command -v awg &> /dev/null; then
    echo "Installing AmneziaWG..."
    apt-get install -y -qq software-properties-common python3-launchpadlib gnupg2 linux-headers-$(uname -r) > /dev/null 2>&1
    add-apt-repository -y ppa:amnezia/ppa > /dev/null 2>&1
    apt-get update -qq
    apt-get install -y -qq amneziawg > /dev/null 2>&1
fi

if ! command -v awg &> /dev/null; then
    echo "ERROR: awg not found. Install amneziawg manually: apt install amneziawg"
    exit 1
fi

echo "awg version: $(awg --version 2>&1 | head -1)"

# Generate server keypair
echo ""
echo "Generating server keys..."
SERVER_PRIVKEY=$(awg genkey)
SERVER_PUBKEY=$(echo "$SERVER_PRIVKEY" | awg pubkey)

# Create config directory
mkdir -p "$WG_DIR"

# Write server config
echo ""
echo "Writing config to $WG_CONFIG..."
cat > "$WG_CONFIG" << EOF
[Interface]
PrivateKey = $SERVER_PRIVKEY
Address = $SERVER_IP
ListenPort = $PORT
Jc = $JC
Jmin = $JMIN
Jmax = $JMAX
S1 = $S1
S2 = $S2
S3 = $S3
S4 = $S4
H1 = $H1
H2 = $H2
H3 = $H3
H4 = $H4
EOF
chmod 600 "$WG_CONFIG"

# Enable IP forwarding
echo ""
echo "Enabling IP forwarding..."
sysctl -w net.ipv4.ip_forward=1 > /dev/null
if ! grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf; then
    echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
fi

# NAT rules (persist with iptables-persistent)
echo ""
echo "Setting up NAT..."
apt-get install -y -qq iptables iptables-persistent > /dev/null 2>&1 || true
iptables -t nat -A POSTROUTING -s $SUBNET -o $NET_IFACE -j MASQUERADE
iptables -A FORWARD -i $INTERFACE -j ACCEPT
iptables -A FORWARD -o $INTERFACE -j ACCEPT
netfilter-persistent save > /dev/null 2>&1 || true

# Bring up interface
echo ""
echo "Starting interface..."
awg-quick down $INTERFACE 2>/dev/null || true
awg-quick up $INTERFACE

# Verify
echo ""
echo "=== Verification ==="
awg show $INTERFACE
echo ""
echo "Server public key: $SERVER_PUBKEY"
echo "Config: $WG_CONFIG"
echo "Network interface: $NET_IFACE"
echo ""
echo "=== DONE ==="
echo ""
echo "IMPORTANT: Save this server public key — you'll need it for .env:"
echo "  SERVER_PUB_KEY=$SERVER_PUBKEY"
echo ""
echo "Next: add this server to .env on the bot server and restart the bot."