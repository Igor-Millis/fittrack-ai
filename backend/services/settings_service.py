"""Configurações persistidas na tabela `settings`."""
from __future__ import annotations

import sqlite3

from backend import config


def get(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else config.DEFAULT_SETTINGS[key]


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    data = dict(config.DEFAULT_SETTINGS)
    data.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    return data


def set_many(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    unknown = set(values) - set(config.DEFAULT_SETTINGS)
    if unknown:
        raise KeyError(f"Configurações desconhecidas: {unknown}")
    conn.execute("BEGIN")
    try:
        for k, v in values.items():
            conn.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (k, str(v)))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_bool(conn: sqlite3.Connection, key: str) -> bool:
    return get(conn, key).lower() in ("1", "true", "sim", "yes", "on")


def get_float(conn: sqlite3.Connection, key: str) -> float:
    return float(get(conn, key))
