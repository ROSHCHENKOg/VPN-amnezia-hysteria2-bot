"""
Whitelist manager - stores allowed Telegram usernames and their key limits
"""
import sqlite3
import json
from config import DB_PATH, DEFAULT_KEY_LIMIT


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            username TEXT PRIMARY KEY,
            key_limit INTEGER DEFAULT 3,
            assigned_server TEXT,
            added_by TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            key_name TEXT NOT NULL,
            server_name TEXT NOT NULL,
            client_ip TEXT NOT NULL,
            private_key TEXT NOT NULL,
            public_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES whitelist(username)
        )
    """)
    # Migration: add key_name column if it doesn't exist
    try:
        c.execute("ALTER TABLE keys ADD COLUMN key_name TEXT DEFAULT 'unnamed'")
    except:
        pass
    # Migration: add assigned_server column if it doesn't exist
    try:
        c.execute("ALTER TABLE whitelist ADD COLUMN assigned_server TEXT")
    except:
        pass
    # Migration: protocol per key - 'awg' or 'hy2'
    try:
        c.execute("ALTER TABLE keys ADD COLUMN protocol TEXT DEFAULT 'awg'")
    except:
        pass
    conn.commit()
    conn.close()


def add_to_whitelist(username: str, key_limit: int = None, added_by: str = "admin") -> bool:
    if key_limit is None:
        key_limit = DEFAULT_KEY_LIMIT
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT OR REPLACE INTO whitelist (username, key_limit, added_by) VALUES (?, ?, ?)",
            (username.lower(), key_limit, added_by)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding to whitelist: {e}")
        return False
    finally:
        conn.close()


def remove_from_whitelist(username: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM whitelist WHERE username = ?", (username.lower(),))
    conn.commit()
    deleted = c.rowcount > 0
    conn.close()
    return deleted


def is_in_whitelist(username: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM whitelist WHERE username = ?", (username.lower(),))
    row = c.fetchone()
    conn.close()
    if row:
        return {"username": row["username"], "key_limit": row["key_limit"], "assigned_server": row["assigned_server"]}
    return None


def get_assigned_server(username: str) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT assigned_server FROM whitelist WHERE username = ?", (username.lower(),))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_assigned_server(username: str, server_name: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE whitelist SET assigned_server = ? WHERE username = ?",
              (server_name, username.lower()))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def get_whitelist() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM whitelist ORDER BY username")
    rows = c.fetchall()
    conn.close()
    return [{"username": r["username"], "key_limit": r["key_limit"], "assigned_server": r["assigned_server"]} for r in rows]


def count_user_keys(username: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM keys WHERE username = ?", (username.lower(),))
    count = c.fetchone()[0]
    conn.close()
    return count


def add_key(username: str, key_name: str, server_name: str, client_ip: str,
             private_key: str, public_key: str, protocol: str = "awg") -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO keys (username, key_name, server_name, client_ip, private_key, public_key, protocol) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username.lower(), key_name, server_name, client_ip, private_key, public_key, protocol)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding key: {e}")
        return False
    finally:
        conn.close()


def remove_key(username: str, client_ip: str = None, key_id: int = None,
               key_name: str = None) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if key_id:
        c.execute("SELECT * FROM keys WHERE id = ?", (key_id,))
    elif key_name:
        c.execute("SELECT * FROM keys WHERE username = ? AND key_name = ?",
                  (username.lower(), key_name))
    else:
        c.execute("SELECT * FROM keys WHERE username = ? AND client_ip = ?",
                  (username.lower(), client_ip))
    row = c.fetchone()
    if row:
        c.execute("DELETE FROM keys WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()
        return {
            "id": row["id"],
            "username": row["username"],
            "key_name": row["key_name"],
            "server_name": row["server_name"],
            "client_ip": row["client_ip"],
            "public_key": row["public_key"],
            "private_key": row["private_key"],
            "protocol": row["protocol"] or "awg"
        }
    conn.close()
    return None


def get_user_keys(username: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE username = ? ORDER BY created_at DESC", (username.lower(),))
    rows = c.fetchall()
    conn.close()
    return [{
        "id": r["id"],
        "key_name": r["key_name"],
        "server_name": r["server_name"],
        "client_ip": r["client_ip"],
        "public_key": r["public_key"],
        "private_key": r["private_key"],
        "protocol": r["protocol"] or "awg",
        "created_at": r["created_at"]
    } for r in rows]


def update_key_limit(username: str, key_limit: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE whitelist SET key_limit = ? WHERE username = ?",
              (key_limit, username.lower()))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated