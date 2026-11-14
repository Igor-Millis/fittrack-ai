"""Backup, restauração e exportação CSV."""
from __future__ import annotations

import csv
import io
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from backend import config

EXPORT_TABLES = [
    "user_profile", "goals", "meals", "meal_items", "activities", "weights",
    "foods", "food_portions", "food_aliases", "audit_log", "settings",
]


def _data_subdir(name: str, default: Path) -> Path:
    # backups/exportações ficam ao lado do banco em uso (mantém bancos de teste/demo isolados)
    db = config.db_path()
    d = default if db.parent.resolve() == config.DATA_DIR.resolve() else db.parent / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _backup_dir() -> Path:
    return _data_subdir("backups", config.BACKUP_DIR)


def create_backup(conn: sqlite3.Connection, reason: str = "manual", keep: int | None = None) -> Path:
    """Cópia consistente via API de backup do SQLite (segura com o banco aberto)."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = _backup_dir() / f"fittrack_{stamp}_{reason}.db"
    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    if keep:
        prune_backups(keep)
    return target


def list_backups() -> list[Path]:
    return sorted(_backup_dir().glob("fittrack_*.db"), reverse=True)


def prune_backups(keep: int) -> None:
    """Mantém os `keep` backups mais recentes (backups pre-restore/pre-migration nunca são apagados)."""
    regular = [p for p in list_backups() if not p.stem.endswith(("pre-restore", "pre-migration"))]
    for old in regular[keep:]:
        old.unlink(missing_ok=True)


def last_backup_time() -> datetime | None:
    b = list_backups()
    return datetime.fromtimestamp(b[0].stat().st_mtime) if b else None


def restore_backup(conn: sqlite3.Connection, backup_file: Path) -> Path:
    """Restaura um backup no banco em uso. Antes, salva o estado atual (pre-restore)."""
    backup_file = Path(backup_file)
    if not backup_file.exists():
        raise FileNotFoundError(backup_file)
    # valida o arquivo antes de tocar no banco atual
    src = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)
    try:
        ok = src.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise ValueError(f"Backup corrompido: {ok}")
        safety = create_backup(conn, reason="pre-restore")
        src.backup(conn)
    finally:
        src.close()
    return safety


def export_csv_zip(conn: sqlite3.Connection) -> tuple[Path, bytes]:
    """Exporta todas as tabelas para CSV (UTF-8 com BOM, abre bem no Excel) num .zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in EXPORT_TABLES:
            cur = conn.execute(f"SELECT * FROM {table}")  # nomes vêm da lista fixa acima
            cols = [c[0] for c in cur.description]
            s = io.StringIO()
            w = csv.writer(s, delimiter=";")
            w.writerow(cols)
            w.writerows(cur.fetchall())
            zf.writestr(f"{table}.csv", chr(0xFEFF) + s.getvalue())  # BOM: Excel reconhece UTF-8
    data = buf.getvalue()
    out = _data_subdir("exports", config.EXPORT_DIR) / f"fittrack_export_{datetime.now():%Y%m%d_%H%M%S}.zip"
    out.write_bytes(data)
    return out, data

