"""
AmneziaWG manager - creates/removes peers on servers via SSH or locally
"""
import subprocess
import paramiko
from config import SERVERS, AWG_PARAMS, VPN_SERVER_IP


def _run_local(cmd: str) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Local command failed: {result.stderr}")
    return result.stdout.strip()


def _run_ssh(server: dict, cmd: str) -> str:
    if server.get("is_local"):
        return _run_local(cmd)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=server["host"],
        port=server.get("ssh_port", 22),
        username=server.get("ssh_user", "root"),
        key_filename=server.get("ssh_key"),
        timeout=10
    )
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    client.close()
    if err and not out:
        raise Exception(f"SSH error: {err}")
    return out


def _get_server_public_key(server: dict) -> str:
    cmd = f"cat {server['wg_config']} | grep PrivateKey | awk '{{print $3}}'"
    privkey = _run_ssh(server, cmd)
    # Derive public key from private
    pub = _run_ssh(server, f"echo '{privkey}' | awg pubkey")
    return pub.strip()


def _get_used_ips(server: dict) -> list[str]:
    cmd = f"awg show {server['wg_interface']} allowed-ips"
    try:
        out = _run_ssh(server, cmd)
        ips = []
        for line in out.splitlines():
            line = line.strip()
            if not line or "(none)" in line:
                continue
            for part in line.split():
                if part.startswith("10.") and "/" in part:
                    ip = part.split("/")[0]
                    ips.append(ip)
        return ips
    except:
        return []


def _get_next_ip(server: dict) -> str:
    used = _get_used_ips(server)
    # Start from 10.8.0.2
    base = VPN_SERVER_IP.rsplit(".", 1)[0]
    for i in range(2, 255):
        ip = f"{base}.{i}"
        if ip not in used:
            return ip
    raise Exception("No available IPs in subnet")


def create_peer(server: dict) -> dict:
    """
    Generate a new keypair, add peer to server, return client config info.
    Returns: {private_key, public_key, client_ip, server_public_key}
    """
    # Generate keypair on server
    privkey = _run_ssh(server, "awg genkey")
    pubkey = _run_ssh(server, f"echo '{privkey}' | awg pubkey")

    # Get next available IP
    client_ip = _get_next_ip(server)
    server_pubkey = _get_server_public_key(server)

    # Add peer to server
    interface = server["wg_interface"]
    cmd = f"awg set {interface} peer {pubkey} allowed-ips {client_ip}/32"
    _run_ssh(server, cmd)

    return {
        "private_key": privkey.strip(),
        "public_key": pubkey.strip(),
        "client_ip": client_ip,
        "server_public_key": server_pubkey.strip(),
        "server_host": server["host"],
        "server_name": server["name"]
    }


def remove_peer(server: dict, public_key: str) -> bool:
    """Remove a peer from the server"""
    interface = server["wg_interface"]
    cmd = f"awg set {interface} peer {public_key} remove"
    try:
        _run_ssh(server, cmd)
        return True
    except Exception as e:
        print(f"Error removing peer: {e}")
        return False


def get_server_info(server: dict) -> dict:
    """Get server stats: peer count, etc"""
    interface = server["wg_interface"]
    try:
        out = _run_ssh(server, f"awg show {interface}")
        peer_count = out.count("peer: ")
        return {
            "name": server["name"],
            "host": server["host"],
            "peer_count": peer_count,
            "max_users": server.get("max_users", 15),
            "available": max_users - peer_count if (max_users := server.get("max_users", 15)) > peer_count else 0
        }
    except Exception as e:
        return {
            "name": server["name"],
            "host": server["host"],
            "peer_count": -1,
            "max_users": server.get("max_users", 15),
            "available": 0,
            "error": str(e)
        }


def get_least_loaded_server(exclude_full: bool = True) -> dict | None:
    """Find the server with the fewest peers. Skip full servers if exclude_full=True."""
    best = None
    best_count = float("inf")
    for server in SERVERS:
        info = get_server_info(server)
        if info["peer_count"] < 0:
            continue
        if exclude_full and info["peer_count"] >= info["max_users"]:
            continue
        if info["peer_count"] < best_count:
            best = server
            best_count = info["peer_count"]
    return best


def get_server_for_user(username: str) -> dict | None:
    """Get the server a user is assigned to, or find the least loaded one for a new user."""
    from whitelist import get_assigned_server, set_assigned_server
    assigned = get_assigned_server(username)
    if assigned:
        server = next((s for s in SERVERS if s["name"] == assigned), None)
        if server:
            return server
    # New user — find least loaded server
    server = get_least_loaded_server(exclude_full=True)
    if server:
        set_assigned_server(username, server["name"])
    return server


def generate_wireguard_config(peer_info: dict) -> str:
    """Generate a standard WireGuard/AmneziaWG .conf file"""
    lines = [
        "[Interface]",
        f"PrivateKey = {peer_info['private_key']}",
        f"Address = {peer_info['client_ip']}/24",
        "",
        "[Peer]",
        f"PublicKey = {peer_info['server_public_key']}",
        f"Endpoint = {peer_info['server_host']}:51820",
        "AllowedIPs = 0.0.0.0/0",
    ]
    # Add AmneziaWG obfuscation params
    for key, val in AWG_PARAMS.items():
        lines.append(f"{key} = {val}")
    return "\n".join(lines) + "\n"


def generate_vpn_uri(peer_info: dict, server_pubkey: str = None,
                     server_host: str = None, server_port: int = 51820,
                     dns1: str = "1.1.1.1", dns2: str = "8.8.8.8",
                     description: str = "VPN") -> str:
    """Generate AmneziaVPN vpn:// URI for direct import into the app"""
    from vpn_uri import generate_vpn_uri as _gen
    return _gen(peer_info, server_pubkey or peer_info.get("server_public_key", ""),
                server_host or peer_info.get("server_host", ""),
                server_port, dns1, dns2, description)