from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def db_path(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "test.db"
    monkeypatch.setenv("FITTRACK_DB", str(p))
    return p


@pytest.fixture()
def conn(db_path):
    from backend.database.connection import init_db

    c = init_db(db_path)
    yield c
    c.close()


@pytest.fixture()
def profile_conn(conn):
    """Banco com perfil (homem, 30 anos, 180 cm, 80 kg) e meta vigente."""
    from backend.models.schemas import GoalIn, ProfileIn
    from backend.services import records

    records.save_profile(conn, ProfileIn(sex="M", age=30, height_cm=180, initial_weight_kg=80,
                                         activity_level="moderado", goal="emagrecimento"))
    records.save_goal(conn, GoalIn(start_date=date(2000, 1, 1), kcal=2200, protein_g=150, carbs_g=220, fat_g=70))
    return conn


def food_id(conn, name: str) -> int:
    return conn.execute("SELECT id FROM foods WHERE name=?", (name,)).fetchone()[0]
