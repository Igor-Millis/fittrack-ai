"""Importação de bases nutricionais para a tabela `foods`.

* TACO 4ª ed. (NEPA/UNICAMP, 2011) — incluída em data/nutrition/taco_4ed.csv, extraída do
  PDF oficial por scripts/extract_taco_pdf.py. Reprodução permitida citando a fonte.
* Qualquer outra base (ex.: TBCA/USP, rótulos) pode ser importada por `import_generic_csv`
  desde que o usuário tenha direito de uso dos dados. A TBCA não é redistribuída aqui
  porque seus termos de uso não autorizam redistribuição em massa.
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from backend import config
from backend.database.connection import transaction
from backend.textutil import normalize

TACO_SOURCE = "TACO 4ª ed. (NEPA/UNICAMP, 2011)"


def _f(v: str | None) -> float | None:
    if v is None:
        return None
    v = str(v).strip().replace(",", ".")
    return float(v) if v not in ("", "nan", "None") else None


def import_taco(conn: sqlite3.Connection, csv_path: Path = config.TACO_CSV) -> int:
    n = 0
    with open(csv_path, encoding="utf-8") as fh, transaction(conn):
        for r in csv.DictReader(fh):
            kcal = _f(r["energia_kcal"])
            if kcal is None:
                continue  # TACO marca como não analisado: não inventamos valores
            umidade = _f(r.get("umidade_pct"))
            density = None
            # infusões (café/chá) têm >97% de água: densidade ~1 g/mL é uma aproximação segura
            if "infusao" in normalize(r["nome"]) and umidade is not None and umidade >= 97:
                density = 1.0
            conn.execute(
                """INSERT OR IGNORE INTO foods (name, norm_name, category, kcal, protein_g, carbs_g,
                   fat_g, fiber_g, density_g_ml, source, source_ref, is_custom)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,0)""",
                (r["nome"], normalize(r["nome"]), r["categoria"], kcal, _f(r["proteina_g"]),
                 _f(r["carboidrato_g"]), _f(r["lipidios_g"]), _f(r["fibra_g"]), density,
                 TACO_SOURCE, str(r["taco_id"])),
            )
            n += 1
    return n


def _taco_food_id(conn: sqlite3.Connection, taco_id: str) -> int | None:
    row = conn.execute("SELECT id FROM foods WHERE source=? AND source_ref=?",
                       (TACO_SOURCE, str(taco_id))).fetchone()
    return row["id"] if row else None


def import_aliases(conn: sqlite3.Connection, csv_path: Path = config.ALIASES_CSV) -> int:
    n = 0
    with open(csv_path, encoding="utf-8") as fh, transaction(conn):
        for r in csv.DictReader(fh, delimiter=";"):
            fid = _taco_food_id(conn, r["taco_id"])
            if fid is None:
                continue
            conn.execute("INSERT OR IGNORE INTO food_aliases (alias, food_id, priority) VALUES (?,?,?)",
                         (normalize(r["alias"]), fid, int(r["priority"])))
            n += 1
    return n


def import_portions(conn: sqlite3.Connection, csv_path: Path = config.PORTIONS_CSV) -> int:
    n = 0
    with open(csv_path, encoding="utf-8") as fh, transaction(conn):
        for r in csv.DictReader(fh, delimiter=";"):
            fid = _taco_food_id(conn, r["taco_id"])
            if fid is None:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO food_portions (food_id, unit, size, grams, source) VALUES (?,?,?,?,?)",
                (fid, r["unit"], r["size"], float(r["grams"]), r["source"]),
            )
            n += 1
    return n


def seed_if_empty(conn: sqlite3.Connection) -> bool:
    if conn.execute("SELECT COUNT(*) FROM foods").fetchone()[0] > 0:
        return False
    import_taco(conn)
    import_aliases(conn)
    import_portions(conn)
    return True


GENERIC_COLUMNS = ["nome", "energia_kcal", "proteina_g", "carboidrato_g", "lipidios_g"]


def import_generic_csv(conn: sqlite3.Connection, csv_path: Path, source_name: str,
                       delimiter: str = ",") -> tuple[int, list[str]]:
    """Importa CSV com colunas: nome, categoria?, energia_kcal, proteina_g, carboidrato_g,
    lipidios_g, fibra_g?, densidade_g_ml?, codigo?  (valores por 100 g).
    Retorna (inseridos, erros). Linhas inválidas são ignoradas e reportadas."""
    errors: list[str] = []
    n = 0
    with open(csv_path, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        missing = [c for c in GENERIC_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"Colunas obrigatórias ausentes: {missing}")
        rows = list(reader)
    with transaction(conn):
        for i, r in enumerate(rows, start=2):
            try:
                kcal = _f(r["energia_kcal"])
                if kcal is None or not r["nome"].strip():
                    raise ValueError("nome/energia ausentes")
                ref = (r.get("codigo") or "").strip() or normalize(r["nome"])
                cur = conn.execute(
                    """INSERT OR IGNORE INTO foods (name, norm_name, category, kcal, protein_g, carbs_g,
                       fat_g, fiber_g, density_g_ml, source, source_ref, is_custom)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,0)""",
                    (r["nome"].strip(), normalize(r["nome"]), (r.get("categoria") or None), kcal,
                     _f(r["proteina_g"]), _f(r["carboidrato_g"]), _f(r["lipidios_g"]),
                     _f(r.get("fibra_g")), _f(r.get("densidade_g_ml")), source_name, ref),
                )
                n += cur.rowcount
            except (ValueError, sqlite3.IntegrityError) as e:
                errors.append(f"linha {i}: {e}")
    return n, errors
