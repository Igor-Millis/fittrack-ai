"""Histórico do chat (persistido localmente para sobreviver ao fechamento do app)."""
from __future__ import annotations

import sqlite3


def add(conn: sqlite3.Connection, role: str, content: str) -> None:
    conn.execute("INSERT INTO chat_messages (role, content) VALUES (?, ?)", (role, content[:8000]))


def recent(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    rows = conn.execute("SELECT * FROM (SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?) ORDER BY id", (limit,))
    return [dict(r) for r in rows]


def clear(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM chat_messages")
