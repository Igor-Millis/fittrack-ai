"""Histórico de alterações (audit_log). Chamar dentro da mesma transação da alteração."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any


def _default(o: Any):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def audit(conn: sqlite3.Connection, entity: str, entity_id: int | None, action: str,
          before: Any = None, after: Any = None, origin: str = "ui") -> None:
    conn.execute(
        "INSERT INTO audit_log (entity, entity_id, action, before_json, after_json, origin) VALUES (?,?,?,?,?,?)",
        (entity, entity_id, action,
         json.dumps(before, default=_default, ensure_ascii=False) if before is not None else None,
         json.dumps(after, default=_default, ensure_ascii=False) if after is not None else None,
         origin),
    )


def recent(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]
