"""
vpn:// URI generator for AmneziaVPN client compatibility
Format: vpn://base64url(4-byte-size-header + zlib-compress(json))

Key differences from working AmneziaVPN config:
- container name: "amnezia-awg2" (not "amnezia-awg")
- last_config: compact JSON (no indent), with clientId and psk_key
- port in last_config: integer (not string)
- DNS in native config: "$PRIMARY_DNS, $SECONDARY_DNS" (not literal IPs)
- native config includes I1-I5 fields
- PresharedKey is optional but present in working configs
"""
import json
import struct
import base64
import zlib

from config import AWG_PARAMS

I1_DEFAULT = "<r 2><b 0x858000010001000000000669636c6f756403636f6d0000010001c00c000100010000105a00044d583737>"


def qcompress(data: bytes, level: int = 8) -> bytes:
    return struct.pack(">I", len(data)) + zlib.compress(data, level)


def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_vpn_uri(peer_info: dict, server_pubkey: str, server_host: str,
                     server_port: int = 51820, dns1: str = "1.1.1.1",
                     dns2: str = "8.8.8.8", description: str = "VPN") -> str:
    client_ip = peer_info["client_ip"]
    client_priv = peer_info["private_key"]
    client_pub = peer_info["public_key"]

    H1 = str(AWG_PARAMS["H1"])
    H2 = str(AWG_PARAMS["H2"])
    H3 = str(AWG_PARAMS["H3"])
    H4 = str(AWG_PARAMS["H4"])
    S3 = str(AWG_PARAMS.get("S3", 14))
    S4 = str(AWG_PARAMS.get("S4", 3))
    I1 = AWG_PARAMS.get("I1", I1_DEFAULT)

    # Build native .conf (matches AmneziaVPN format)
    conf_lines = [
        "[Interface]",
        f"Address = {client_ip}/32",
        "DNS = $PRIMARY_DNS, $SECONDARY_DNS",
        f"PrivateKey = {client_priv}",
        f"Jc = {AWG_PARAMS['Jc']}",
        f"Jmin = {AWG_PARAMS['Jmin']}",
        f"Jmax = {AWG_PARAMS['Jmax']}",
        f"S1 = {AWG_PARAMS['S1']}",
        f"S2 = {AWG_PARAMS['S2']}",
        f"S3 = {S3}",
        f"S4 = {S4}",
        f"H1 = {H1}",
        f"H2 = {H2}",
        f"H3 = {H3}",
        f"H4 = {H4}",
        f"I1 = {I1}",
        "I2 = ",
        "I3 = ",
        "I4 = ",
        "I5 = ",
        "",
        "[Peer]",
        f"PublicKey = {server_pubkey}",
        f"AllowedIPs = 0.0.0.0/0, ::/0",
        f"Endpoint = {server_host}:{server_port}",
        "PersistentKeepalive = 25",
    ]
    native_conf = "\n".join(conf_lines)

    # Build last_config (compact JSON, no indent — matches AmneziaVPN format)
    last_config = {
        "H1": H1,
        "H2": H2,
        "H3": H3,
        "H4": H4,
        "I1": I1,
        "Jc": str(AWG_PARAMS["Jc"]),
        "Jmax": str(AWG_PARAMS["Jmax"]),
        "Jmin": str(AWG_PARAMS["Jmin"]),
        "S1": str(AWG_PARAMS["S1"]),
        "S2": str(AWG_PARAMS["S2"]),
        "S3": S3,
        "S4": S4,
        "allowed_ips": ["0.0.0.0/0", "::/0"],
        "clientId": client_pub,
        "client_ip": client_ip,
        "client_priv_key": client_priv,
        "client_pub_key": client_pub,
        "config": native_conf,
        "hostName": server_host,
        "mtu": "1280",
        "persistent_keep_alive": "25",
        "port": server_port,
        "server_pub_key": server_pubkey,
    }

    # Build outer server config (container name = "amnezia-awg2" to match working config)
    server_config = {
        "containers": [
            {
                "awg": {
                    "H1": H1,
                    "H2": H2,
                    "H3": H3,
                    "H4": H4,
                    "I1": I1,
                    "I2": "",
                    "I3": "",
                    "I4": "",
                    "I5": "",
                    "Jc": str(AWG_PARAMS["Jc"]),
                    "Jmax": str(AWG_PARAMS["Jmax"]),
                    "Jmin": str(AWG_PARAMS["Jmin"]),
                    "S1": str(AWG_PARAMS["S1"]),
                    "S2": str(AWG_PARAMS["S2"]),
                    "S3": S3,
                    "S4": S4,
                    "last_config": json.dumps(last_config, separators=(",", ":")),
                    "port": str(server_port),
                    "protocol_version": "2",
                    "subnet_address": "10.8.0.0",
                    "transport_proto": "udp",
                },
                "container": "amnezia-awg2",
            }
        ],
        "defaultContainer": "amnezia-awg2",
        "description": description,
        "dns1": dns1,
        "dns2": dns2,
        "hostName": server_host,
        "nameOverriddenByUser": "true",
    }

    json_bytes = json.dumps(server_config, indent=4).encode("utf-8")
    compressed = qcompress(json_bytes, 8)
    b64 = base64url_encode(compressed)
    return f"vpn://{b64}"