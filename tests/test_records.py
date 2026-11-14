"""Registro, persistência, duplicação, auditoria, backup e migrations (integração com SQLite)."""
from __future__ import annotations

import sqlite3
import zipfile
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from backend.database import backup, migrations
from backend.database.connection import connect, init_db
from backend.models.schemas import ActivityIn, MealIn, MealItemIn, WeightIn
from backend.services import records
from tests.conftest import food_id

TODAY = date.today()


def _meal(conn, day=TODAY, grams=150):
    return MealIn(date=day, meal_type="almoco", items=[
        MealItemIn(food_id=food_id(conn, "Arroz, tipo 1, cozido"), quantity=grams, unit="g"),
        MealItemIn(food_id=food_id(conn, "Pão, trigo, francês"), quantity=1, unit="unidade")])


def test_meal_saved_with_snapshot(profile_conn):
    mid = records.save_meal(profile_conn, _meal(profile_conn))
    m = records.get_meal(profile_conn, mid)
    assert [i["kcal"] for i in m["items"]] == [192.0, 150.0]
    assert m["items"][1]["grams"] == 50


def test_duplicate_meal_blocked_unless_forced(profile_conn):
    records.save_meal(profile_conn, _meal(profile_conn))
    with pytest.raises(records.DuplicateError):
        records.save_meal(profile_conn, _meal(profile_conn))
    records.save_meal(profile_conn, _meal(profile_conn), allow_duplicate=True)
    records.save_meal(profile_conn, _meal(profile_conn, grams=151))  # quantidade diferente não é duplicata
    assert profile_conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 3


def test_update_and_delete_item(profile_conn):
    mid = records.save_meal(profile_conn, _meal(profile_conn))
    item = records.get_meal(profile_conn, mid)["items"][0]
    records.update_meal_item(profile_conn, item["id"], 200, "g")
    assert records.get_meal(profile_conn, mid)["items"][0]["kcal"] == pytest.approx(256)
    for it in records.get_meal(profile_conn, mid)["items"]:
        records.delete_meal_item(profile_conn, it["id"])
    assert records.get_meal(profile_conn, mid) is None  # refeição vazia é removida


def test_activity_uses_latest_weight_and_dedup(profile_conn):
    records.save_weight(profile_conn, WeightIn(date=TODAY - timedelta(days=1), weight_kg=75))
    aid = records.save_activity(profile_conn, ActivityIn(date=TODAY, activity_type="musculacao", duration_min=60))
    row = profile_conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    assert row["weight_kg_used"] == 75 and row["kcal_gross"] == pytest.approx(375) and row["kcal_net"] == pytest.approx(300)
    with pytest.raises(records.DuplicateError):
        records.save_activity(profile_conn, ActivityIn(date=TODAY, activity_type="musculacao", duration_min=60))


def test_invalid_inputs_rejected():
    with pytest.raises(ValidationError):
        ActivityIn(date=TODAY, activity_type="corrida", duration_min=10, distance_km=50)  # 300 km/h
    with pytest.raises(ValidationError):
        WeightIn(date=TODAY, weight_kg=900)
    with pytest.raises(ValidationError):
        ActivityIn(date=TODAY, activity_type="voar", duration_min=10)


def test_db_check_constraints(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO weights (date, weight_kg) VALUES ('2026-01-01', 5)")


def test_weight_one_per_day_requires_replace(profile_conn):
    records.save_weight(profile_conn, WeightIn(date=TODAY, weight_kg=80))
    with pytest.raises(records.DuplicateError):
        records.save_weight(profile_conn, WeightIn(date=TODAY, weight_kg=79.5))
    records.save_weight(profile_conn, WeightIn(date=TODAY, weight_kg=79.5), replace=True)
    assert records.get_weight(profile_conn, TODAY)["weight_kg"] == 79.5


def test_persistence_after_reopen(db_path, profile_conn):
    records.save_meal(profile_conn, _meal(profile_conn))
    records.save_weight(profile_conn, WeightIn(date=TODAY, weight_kg=80))
    profile_conn.close()
    c2 = init_db(db_path)
    assert c2.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 1
    assert c2.execute("SELECT COUNT(*) FROM weights").fetchone()[0] == 1
    assert records.get_profile(c2)["height_cm"] == 180
    c2.close()


def test_migrations_idempotent_and_foreign_keys(db_path, conn):
    assert migrations.current_version(conn) == len(migrations.MIGRATIONS)
    assert migrations.migrate(conn) == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO meal_items (meal_id, food_id, food_name, quantity, unit, grams, kcal) "
                     "VALUES (999, 1, 'x', 1, 'g', 1, 1)")


def test_audit_log(profile_conn):
    mid = records.save_meal(profile_conn, _meal(profile_conn))
    records.delete_meal(profile_conn, mid)
    actions = [r["action"] for r in profile_conn.execute("SELECT action FROM audit_log WHERE entity='meals' ORDER BY id")]
    assert actions == ["create", "delete"]


def test_goals_versioned_by_date(profile_conn):
    from backend.models.schemas import GoalIn
    records.save_goal(profile_conn, GoalIn(start_date=TODAY, kcal=2000, protein_g=160, carbs_g=180, fat_g=60))
    assert records.goal_for(profile_conn, TODAY)["kcal"] == 2000
    assert records.goal_for(profile_conn, TODAY - timedelta(days=1))["kcal"] == 2200


def test_backup_restore_and_export(db_path, profile_conn):
    records.save_weight(profile_conn, WeightIn(date=TODAY, weight_kg=80))
    b = backup.create_backup(profile_conn, "teste")
    assert b.exists() and b.parent == db_path.parent / "backups"
    records.save_weight(profile_conn, WeightIn(date=TODAY - timedelta(days=1), weight_kg=81))
    assert profile_conn.execute("SELECT COUNT(*) FROM weights").fetchone()[0] == 2
    safety = backup.restore_backup(profile_conn, b)
    assert profile_conn.execute("SELECT COUNT(*) FROM weights").fetchone()[0] == 1
    assert safety.exists()  # estado anterior preservado
    out, data = backup.export_csv_zip(profile_conn)
    names = zipfile.ZipFile(out).namelist()
    assert {"meals.csv", "weights.csv", "activities.csv", "user_profile.csv"} <= set(names)
    out.unlink()


def test_prune_keeps_safety_backups(db_path, profile_conn):
    for _ in range(4):
        backup.create_backup(profile_conn, "auto")
    backup.create_backup(profile_conn, "pre-restore")
    backup.prune_backups(2)
    names = [p.name for p in backup.list_backups()]
    assert len([n for n in names if n.endswith("auto.db")]) == 2
    assert any(n.endswith("pre-restore.db") for n in names)


def test_connect_creates_directory(tmp_path):
    c = connect(tmp_path / "nested" / "x.db")
    c.close()
    assert (tmp_path / "nested" / "x.db").exists()
