"""Serviços de registro: perfil, metas, refeições, atividades e peso.

São as ÚNICAS funções que gravam dados do usuário. O assistente (IA ou regras) só
consegue alterar o banco chamando estas funções, sempre com dados validados por Pydantic.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, timedelta

from backend.database.connection import transaction
from backend.exercise.mets import activity_energy, choose_met
from backend.models.schemas import ActivityIn, GoalIn, MealIn, ProfileIn, WeightIn
from backend.nutrition.calculator import compute_item
from backend.services.audit import audit


class DuplicateError(Exception):
    """Registro idêntico já existe para a mesma data."""

    def __init__(self, message: str, existing_id: int):
        super().__init__(message)
        self.existing_id = existing_id


class NotFoundError(Exception):
    pass


def _fp(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


# ------------------------------------------------------------------ perfil e metas
def get_profile(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
    return dict(row) if row else None


def save_profile(conn: sqlite3.Connection, p: ProfileIn, origin: str = "ui") -> None:
    before = get_profile(conn)
    data = p.model_dump()
    with transaction(conn):
        if before:
            conn.execute(
                """UPDATE user_profile SET name=:name, sex=:sex, age=:age, height_cm=:height_cm,
                   initial_weight_kg=:initial_weight_kg, activity_level=:activity_level, goal=:goal,
                   energy_method=:energy_method, sedentary_factor=:sedentary_factor,
                   target_weight_kg=:target_weight_kg, weekly_rate_kg=:weekly_rate_kg,
                   updated_at=datetime('now','localtime') WHERE id=1""", data)
            audit(conn, "user_profile", 1, "update", before=before, after=data, origin=origin)
        else:
            conn.execute(
                """INSERT INTO user_profile (id, name, sex, age, height_cm, initial_weight_kg, activity_level,
                   goal, energy_method, sedentary_factor, target_weight_kg, weekly_rate_kg)
                   VALUES (1, :name, :sex, :age, :height_cm, :initial_weight_kg, :activity_level, :goal,
                   :energy_method, :sedentary_factor, :target_weight_kg, :weekly_rate_kg)""", data)
            audit(conn, "user_profile", 1, "create", after=data, origin=origin)


def save_goal(conn: sqlite3.Connection, g: GoalIn, origin: str = "ui") -> None:
    """Metas valem a partir de start_date; uma nova meta na mesma data substitui a anterior."""
    data = g.model_dump()
    data["start_date"] = g.start_date.isoformat()
    with transaction(conn):
        old = conn.execute("SELECT * FROM goals WHERE start_date=?", (data["start_date"],)).fetchone()
        conn.execute(
            """INSERT INTO goals (start_date, kcal, protein_g, carbs_g, fat_g, fiber_g)
               VALUES (:start_date, :kcal, :protein_g, :carbs_g, :fat_g, :fiber_g)
               ON CONFLICT(start_date) DO UPDATE SET kcal=excluded.kcal, protein_g=excluded.protein_g,
               carbs_g=excluded.carbs_g, fat_g=excluded.fat_g, fiber_g=excluded.fiber_g""", data)
        audit(conn, "goals", None, "update" if old else "create",
              before=dict(old) if old else None, after=data, origin=origin)


def goal_for(conn: sqlite3.Connection, day: date) -> dict | None:
    row = conn.execute("SELECT * FROM goals WHERE start_date <= ? ORDER BY start_date DESC LIMIT 1",
                       (day.isoformat(),)).fetchone()
    if row is None:  # metas criadas depois do dia: usa a mais antiga
        row = conn.execute("SELECT * FROM goals ORDER BY start_date LIMIT 1").fetchone()
    return dict(row) if row else None


def all_goals(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM goals ORDER BY start_date")]


# ------------------------------------------------------------------ peso
def weight_on_or_before(conn: sqlite3.Connection, day: date) -> float | None:
    row = conn.execute("SELECT weight_kg FROM weights WHERE date <= ? ORDER BY date DESC LIMIT 1",
                       (day.isoformat(),)).fetchone()
    return row["weight_kg"] if row else None


def body_weight_for(conn: sqlite3.Connection, day: date) -> float:
    w = weight_on_or_before(conn, day)
    if w is None:
        row = conn.execute("SELECT weight_kg FROM weights ORDER BY date LIMIT 1").fetchone()
        if row:
            return row["weight_kg"]
        prof = get_profile(conn)
        if not prof:
            raise NotFoundError("Perfil não configurado.")
        return prof["initial_weight_kg"]
    return w


def get_weight(conn: sqlite3.Connection, day: date) -> dict | None:
    row = conn.execute("SELECT * FROM weights WHERE date=?", (day.isoformat(),)).fetchone()
    return dict(row) if row else None


def save_weight(conn: sqlite3.Connection, w: WeightIn, replace: bool = False, origin: str = "ui") -> int:
    """Um peso por dia. Se já existir, exige replace=True (confirmação explícita)."""
    existing = get_weight(conn, w.date)
    with transaction(conn):
        if existing:
            if not replace:
                raise DuplicateError(
                    f"Já existe peso registrado em {w.date:%d/%m/%Y}: {existing['weight_kg']:.1f} kg.",
                    existing["id"])
            conn.execute("UPDATE weights SET weight_kg=?, notes=? WHERE id=?",
                         (w.weight_kg, w.notes, existing["id"]))
            audit(conn, "weights", existing["id"], "update", before=existing, after=w.model_dump(), origin=origin)
            return existing["id"]
        cur = conn.execute("INSERT INTO weights (date, weight_kg, notes) VALUES (?,?,?)",
                           (w.date.isoformat(), w.weight_kg, w.notes))
        audit(conn, "weights", cur.lastrowid, "create", after=w.model_dump(), origin=origin)
        return cur.lastrowid


def delete_weight(conn: sqlite3.Connection, weight_id: int, origin: str = "ui") -> None:
    with transaction(conn):
        row = conn.execute("SELECT * FROM weights WHERE id=?", (weight_id,)).fetchone()
        if not row:
            raise NotFoundError(f"Peso {weight_id} não encontrado.")
        conn.execute("DELETE FROM weights WHERE id=?", (weight_id,))
        audit(conn, "weights", weight_id, "delete", before=dict(row), origin=origin)


# ------------------------------------------------------------------ refeições
def save_meal(conn: sqlite3.Connection, meal: MealIn, allow_duplicate: bool = False, origin: str = "ui") -> int:
    computed = [compute_item(conn, it.food_id, it.quantity, it.unit, it.size, it.grams_override)
                for it in meal.items]
    fingerprint = _fp({"meal_type": meal.meal_type,
                       "items": sorted((c.food_id, round(c.grams, 1)) for c in computed)})
    with transaction(conn):
        if not allow_duplicate:
            dup = conn.execute("SELECT id FROM meals WHERE date=? AND fingerprint=?",
                               (meal.date.isoformat(), fingerprint)).fetchone()
            if dup:
                raise DuplicateError(
                    f"Uma refeição idêntica já foi registrada em {meal.date:%d/%m/%Y} (id {dup['id']}).", dup["id"])
        cur = conn.execute(
            "INSERT INTO meals (date, meal_type, time, notes, source_text, fingerprint) VALUES (?,?,?,?,?,?)",
            (meal.date.isoformat(), meal.meal_type, meal.time, meal.notes, meal.source_text, fingerprint))
        meal_id = cur.lastrowid
        for c in computed:
            n = c.nutrients
            conn.execute(
                """INSERT INTO meal_items (meal_id, food_id, food_name, quantity, unit, grams, kcal, protein_g,
                   carbs_g, fat_g, fiber_g, grams_basis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (meal_id, c.food_id, c.food_name, c.quantity, c.unit, c.grams, round(n.kcal, 2),
                 round(n.protein_g, 2), round(n.carbs_g, 2), round(n.fat_g, 2),
                 None if n.fiber_g is None else round(n.fiber_g, 2), c.basis))
        audit(conn, "meals", meal_id, "create", after=meal.model_dump(), origin=origin)
    return meal_id


def get_meal(conn: sqlite3.Connection, meal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM meals WHERE id=?", (meal_id,)).fetchone()
    if not row:
        return None
    meal = dict(row)
    meal["items"] = [dict(r) for r in conn.execute("SELECT * FROM meal_items WHERE meal_id=? ORDER BY id", (meal_id,))]
    return meal


def list_meals(conn: sqlite3.Connection, start: date, end: date) -> list[dict]:
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM meals WHERE date BETWEEN ? AND ? ORDER BY date, COALESCE(time,''), id",
        (start.isoformat(), end.isoformat()))]
    return [get_meal(conn, i) for i in ids]


def delete_meal(conn: sqlite3.Connection, meal_id: int, origin: str = "ui") -> None:
    with transaction(conn):
        meal = get_meal(conn, meal_id)
        if not meal:
            raise NotFoundError(f"Refeição {meal_id} não encontrada.")
        conn.execute("DELETE FROM meals WHERE id=?", (meal_id,))
        audit(conn, "meals", meal_id, "delete", before=meal, origin=origin)


def update_meal_item(conn: sqlite3.Connection, item_id: int, quantity: float, unit: str,
                     grams_override: float | None = None, origin: str = "ui") -> None:
    """Corrige a quantidade de um item e recalcula seus nutrientes."""
    with transaction(conn):
        row = conn.execute("SELECT * FROM meal_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise NotFoundError(f"Item {item_id} não encontrado.")
        c = compute_item(conn, row["food_id"], quantity, unit, None, grams_override)
        n = c.nutrients
        conn.execute(
            """UPDATE meal_items SET quantity=?, unit=?, grams=?, kcal=?, protein_g=?, carbs_g=?, fat_g=?,
               fiber_g=?, grams_basis=? WHERE id=?""",
            (quantity, unit, c.grams, round(n.kcal, 2), round(n.protein_g, 2), round(n.carbs_g, 2),
             round(n.fat_g, 2), None if n.fiber_g is None else round(n.fiber_g, 2), c.basis, item_id))
        audit(conn, "meal_items", item_id, "update", before=dict(row),
              after={"quantity": quantity, "unit": unit, "grams": c.grams}, origin=origin)


def delete_meal_item(conn: sqlite3.Connection, item_id: int, origin: str = "ui") -> None:
    with transaction(conn):
        row = conn.execute("SELECT * FROM meal_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise NotFoundError(f"Item {item_id} não encontrado.")
        conn.execute("DELETE FROM meal_items WHERE id=?", (item_id,))
        left = conn.execute("SELECT COUNT(*) FROM meal_items WHERE meal_id=?", (row["meal_id"],)).fetchone()[0]
        if left == 0:
            conn.execute("DELETE FROM meals WHERE id=?", (row["meal_id"],))
        audit(conn, "meal_items", item_id, "delete", before=dict(row), origin=origin)


# ------------------------------------------------------------------ atividades
def preview_activity(conn: sqlite3.Connection, a: ActivityIn, specific: str | None = None) -> dict:
    weight = body_weight_for(conn, a.date)
    choice = choose_met(a.activity_type, a.intensity, a.duration_min, a.distance_km, specific)
    met = a.met_override or choice.met
    source = "MET informado pelo usuário" if a.met_override else choice.source
    e = activity_energy(met, weight, a.duration_min)
    return {"met": met, "met_source": source, "weight_kg_used": weight,
            "kcal_gross": e.kcal_gross, "kcal_net": e.kcal_net}


def save_activity(conn: sqlite3.Connection, a: ActivityIn, allow_duplicate: bool = False,
                  specific: str | None = None, origin: str = "ui") -> int:
    calc = preview_activity(conn, a, specific)
    fingerprint = _fp({"t": a.activity_type, "d": round(a.duration_min, 1),
                       "km": round(a.distance_km, 2) if a.distance_km else None, "desc": a.description})
    with transaction(conn):
        if not allow_duplicate:
            dup = conn.execute("SELECT id FROM activities WHERE date=? AND fingerprint=?",
                               (a.date.isoformat(), fingerprint)).fetchone()
            if dup:
                raise DuplicateError(
                    f"Atividade idêntica já registrada em {a.date:%d/%m/%Y} (id {dup['id']}).", dup["id"])
        cur = conn.execute(
            """INSERT INTO activities (date, activity_type, description, duration_min, distance_km, intensity,
               met, met_source, weight_kg_used, kcal_gross, kcal_net, notes, source_text, fingerprint)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (a.date.isoformat(), a.activity_type, a.description, a.duration_min, a.distance_km, a.intensity,
             calc["met"], calc["met_source"], calc["weight_kg_used"], calc["kcal_gross"], calc["kcal_net"],
             a.notes, a.source_text, fingerprint))
        audit(conn, "activities", cur.lastrowid, "create", after={**a.model_dump(), **calc}, origin=origin)
        return cur.lastrowid


def list_activities(conn: sqlite3.Connection, start: date, end: date) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM activities WHERE date BETWEEN ? AND ? ORDER BY date, id", (start.isoformat(), end.isoformat()))]


def delete_activity(conn: sqlite3.Connection, activity_id: int, origin: str = "ui") -> None:
    with transaction(conn):
        row = conn.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
        if not row:
            raise NotFoundError(f"Atividade {activity_id} não encontrada.")
        conn.execute("DELETE FROM activities WHERE id=?", (activity_id,))
        audit(conn, "activities", activity_id, "delete", before=dict(row), origin=origin)


def last_record(conn: sqlite3.Connection) -> tuple[str, int, str] | None:
    """Último registro criado (para 'desfazer'), como (tipo, id, criado_em)."""
    rows = []
    for table, kind in (("meals", "refeicao"), ("activities", "atividade"), ("weights", "peso")):
        r = conn.execute(f"SELECT id, created_at FROM {table} ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()
        if r:
            rows.append((kind, r["id"], r["created_at"]))
    return max(rows, key=lambda x: (x[2], x[1])) if rows else None


def days_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
