"""Rotinas de manutenção: backup automático e logging sem dados pessoais."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from backend import config
from backend.database import backup
from backend.services import settings_service


def auto_backup(conn: sqlite3.Connection) -> str | None:
    """Faz backup na abertura do app se o último tiver mais de `auto_backup_days` dias."""
    days = settings_service.get_float(conn, "auto_backup_days")
    if days <= 0:
        return None
    if conn.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0] == 0:
        return None  # nada do usuário para proteger ainda
    last = backup.last_backup_time()
    if last and datetime.now() - last < timedelta(days=days):
        return None
    keep = int(settings_service.get_float(conn, "backup_keep"))
    return str(backup.create_backup(conn, reason="auto", keep=keep))


def setup_logging() -> None:
    """Log técnico em data/logs. Nunca registramos texto de mensagens, alimentos ou pesos."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    h = RotatingFileHandler(config.LOG_DIR / "fittrack.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.INFO)
