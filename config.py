"""
Config loader - reads settings from .env file
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

SERVERS = json.loads(os.getenv("SERVERS", "[]"))

# AmneziaWG obfuscation params
AWG_PARAMS = {
    "Jc": int(os.getenv("AWG_JC", "5")),
    "Jmin": int(os.getenv("AWG_JMIN", "10")),
    "Jmax": int(os.getenv("AWG_JMAX", "50")),
    "S1": int(os.getenv("AWG_S1", "95")),
    "S2": int(os.getenv("AWG_S2", "42")),
    "S3": int(os.getenv("AWG_S3", "14")),
    "S4": int(os.getenv("AWG_S4", "3")),
    "H1": os.getenv("AWG_H1", "1801680827-1998653040"),
    "H2": os.getenv("AWG_H2", "2142741064-2144902292"),
    "H3": os.getenv("AWG_H3", "2146093884-2146220331"),
    "H4": os.getenv("AWG_H4", "2146616603-2147215006"),
    "I1": os.getenv("AWG_I1", "<r 2><b 0x858000010001000000000669636c6f756403636f6d0000010001c00c000100010000105a00044d583737>"),
}

# Hysteria2
HY2_OBFS = os.getenv("HY2_OBFS", "")
HY2_PORT = int(os.getenv("HY2_PORT", "31000"))
HY2_HOP = os.getenv("HY2_HOP", "20000-30000")

VPN_SUBNET = os.getenv("VPN_SUBNET", "10.8.0.0/24")
VPN_SERVER_IP = os.getenv("VPN_SERVER_IP", "10.8.0.1")
DEFAULT_KEY_LIMIT = int(os.getenv("DEFAULT_KEY_LIMIT", "3"))

# Database path
DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")