"""
Hysteria2 manager - keys, links and config rollout to servers

Ключи живут в общей таблице keys (protocol='hy2'), поэтому лимит,
список и отзыв работают теми же функциями, что и для AmneziaWG.
Для Hysteria в ней:
    public_key  - логин в userpass-карте сервера
    private_key - пароль
    client_ip   - не используется
"""
import sqlite3
import secrets
import string
import subprocess
import urllib.parse as up

from config import DB_PATH, SERVERS, HY2_OBFS, HY2_PORT, HY2_HOP
from whitelist import get_assigned_server, set_assigned_server, add_key

OBFS = HY2_OBFS
PORT = HY2_PORT
HOP = HY2_HOP
CONF = "/etc/hysteria/config.yaml"
SSH = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]


def _password(n: int = 24) -> str:
    """Только буквы и цифры: дефис и точку мобильные клиенты на Xray
    разбирают как диапазон портов и ломаются на такой ссылке."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _server(name: str) -> dict | None:
    for s in SERVERS:
        if s["name"] == name:
            return s
    return None


def domain(host: str) -> str:
    """sslip.io отдаёт домен прямо из IP - нужен для сертификата Let's Encrypt.

    Точечная форма, не дефисная: Xray-подобные парсеры в мобильных клиентах
    разбирают дефисы в host:port как диапазон портов и ломаются.
    """
    return host + ".sslip.io"


def pick_server(username: str) -> str:
    """Назначенный сервер, либо наименее загруженный (и запоминаем выбор)"""
    username = username.lower()
    assigned = get_assigned_server(username)
    if assigned and _server(assigned):
        return assigned
    conn = sqlite3.connect(DB_PATH)
    counts = dict(conn.execute(
        "SELECT assigned_server, COUNT(*) FROM whitelist "
        "WHERE assigned_server IS NOT NULL GROUP BY assigned_server"))
    conn.close()
    name = min((s["name"] for s in SERVERS), key=lambda n: counts.get(n, 0))
    set_assigned_server(username, name)
    return name


def create_key(username: str, key_name: str) -> tuple[str, str]:
    """Заводит новый ключ Hysteria. Возвращает (сервер, ссылка)."""
    username = username.lower()
    server = pick_server(username)
    # ни точки (viper в Hysteria делает из неё вложенность),
    # ни дефиса (мобильные парсеры путают его с диапазоном портов)
    login = f"{username}_{secrets.token_hex(3)}"
    password = _password()
    add_key(username, key_name, server, "", password, login, protocol="hy2")
    sync()
    return server, build_link(login, password, server)


def build_link(login: str, password: str, server_name: str, hop: bool = False) -> str:
    srv = _server(server_name)
    if not srv:
        raise ValueError(f"нет такого сервера: {server_name}")
    auth = f"{up.quote(login, safe='')}:{up.quote(password, safe='')}"
    query = up.urlencode({"obfs": "salamander", "obfs-password": OBFS})
    port = HOP if hop else str(PORT)
    return f"hysteria2://{auth}@{domain(srv['host'])}:{port}/?{query}"


def link_for_key(key: dict, hop: bool = False) -> str:
    """Ссылка по строке из таблицы keys"""
    return build_link(key["public_key"], key["private_key"], key["server_name"], hop)


def _render(users: list[tuple[str, str]], host: str) -> str:
    # Hysteria не стартует с пустым userpass, а без ключей сервер должен
    # остаться живым - кладём заглушку со случайным паролем
    body = "\n".join(f'    "{u}": "{p}"' for u, p in users) \
        or f'    "_none": "{secrets.token_urlsafe(24)}"' 
    return f"""listen: :{PORT}

acme:
  domains:
    - {domain(host)}
  dir: /etc/hysteria/acme

obfs:
  type: salamander
  salamander:
    password: {OBFS}

auth:
  type: userpass
  userpass:
{body}

masquerade:
  type: proxy
  proxy:
    url: https://www.bing.com/
    rewriteHost: true

quic:
  initStreamReceiveWindow: 8388608
  maxStreamReceiveWindow: 8388608
  initConnReceiveWindow: 20971520
  maxConnReceiveWindow: 20971520
"""


def _deploy(srv: dict, conf: str) -> bool:
    if srv.get("is_local"):
        open(CONF, "w").write(conf)
        return subprocess.run(["systemctl", "restart", "hysteria-server"],
                              capture_output=True).returncode == 0
    target = f"{srv.get('ssh_user', 'root')}@{srv['host']}"
    prep = subprocess.run(
        SSH + [target, f"mkdir -p /etc/hysteria/acme && chown -R hysteria:hysteria /etc/hysteria/acme "
                       f"&& chmod 700 /etc/hysteria/acme && cat > {CONF}"],
        input=conf.encode(), capture_output=True)
    restart = subprocess.run(SSH + [target, "systemctl restart hysteria-server"], capture_output=True)
    return prep.returncode == 0 and restart.returncode == 0


def sync() -> dict:
    """Раскатывает всех живых hy2-ключей на все серверы.

    Ключи удалённых из вайтлиста людей не попадают в конфиг - доступ отзывается.
    Блокирующая: в боте вызывать через asyncio.to_thread.
    """
    conn = sqlite3.connect(DB_PATH)
    users = list(conn.execute(
        "SELECT k.public_key, k.private_key FROM keys k "
        "JOIN whitelist w ON w.username = k.username "
        "WHERE k.protocol = 'hy2' ORDER BY k.public_key"))
    conn.close()
    results = {s["name"]: _deploy(s, _render(users, s["host"])) for s in SERVERS}
    return {"keys": len(users), "servers": results}
