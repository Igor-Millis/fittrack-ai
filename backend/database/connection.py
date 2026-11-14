"""Conexão SQLite, transações e inicialização do banco."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend import config
from backend.database import migrations

log = logging.getLogger(__name__)


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None -> controlamos as transações explicitamente
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Bloco atômico: tudo ou nada."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(path: Path | None = None, seed: bool = True) -> sqlite3.Connection:
    """Abre o banco, faz backup se houver migrations a aplicar num banco existente,
    aplica migrations e carrega a base nutricional na primeira execução."""
    path = Path(path or config.db_path())
    existed = path.exists() and path.stat().st_size > 0
    conn = connect(path)
    if existed and migrations.pending(conn):
        from backend.database.backup import create_backup

        create_backup(conn, reason="pre-migration")
    applied = migrations.migrate(conn)
    if applied:
        log.info("Migrations aplicadas: %s", applied)
    if seed:
        from backend.nutrition.importer import seed_if_empty

        seed_if_empty(conn)
    return conn
