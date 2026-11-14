"""Balanço energético diário e indicadores por período — tudo calculado a partir do banco.

Convenções:
* saldo = gasto estimado − consumo.  Positivo = déficit; negativo = superávit.
* Dias SEM nenhum alimento registrado não têm saldo (NaN): contar consumo 0 criaria
  déficits fictícios. Eles aparecem como "sem registro" e ficam fora das médias de consumo.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from backend.energy.metabolism import daily_expenditure
from backend.services import records, settings_service


class ProfileMissing(Exception):
    pass


def _weights_df(conn: sqlite3.Connection, end: date) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT date, weight_kg FROM weights WHERE date <= ? ORDER BY date", conn,
                           params=(end.isoformat(),))
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df


def weight_series(conn: sqlite3.Connection, start: date, end: date) -> pd.DataFrame:
    """Pesos do período com média móvel de 7 dias (janela de calendário, pesagens disponíveis)."""
    w = _weights_df(conn, end)
    if w.empty:
        return pd.DataFrame(columns=["date", "weight_kg", "ma7"])
    w = w.set_index("date")
    w["ma7"] = w["weight_kg"].rolling("7D", min_periods=1).mean()
    w = w.reset_index()
    return w[w["date"] >= pd.Timestamp(start)].reset_index(drop=True)


def daily_summary(conn: sqlite3.Connection, start: date, end: date) -> pd.DataFrame:
    prof = records.get_profile(conn)
    if not prof:
        raise ProfileMissing("Configure seu perfil primeiro.")
    band = settings_service.get_float(conn, "maintenance_band_kcal")
    days = pd.DataFrame({"date": pd.date_range(start, end, freq="D").astype("datetime64[ns]")})

    food = pd.read_sql_query(
        """SELECT m.date, SUM(i.kcal) kcal_in, SUM(i.protein_g) protein_g, SUM(i.carbs_g) carbs_g,
                  SUM(i.fat_g) fat_g, SUM(i.fiber_g) fiber_g, COUNT(DISTINCT m.id) n_meals
           FROM meals m JOIN meal_items i ON i.meal_id = m.id
           WHERE m.date BETWEEN ? AND ? GROUP BY m.date""", conn, params=(start.isoformat(), end.isoformat()))
    act = pd.read_sql_query(
        """SELECT date, SUM(kcal_net) exercise_net, SUM(kcal_gross) exercise_gross, COUNT(*) n_activities,
                  SUM(duration_min) exercise_min
           FROM activities WHERE date BETWEEN ? AND ? GROUP BY date""", conn,
        params=(start.isoformat(), end.isoformat()))
    for df in (food, act):
        df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    out = days.merge(food, on="date", how="left").merge(act, on="date", how="left")
    out["has_food"] = out["n_meals"].fillna(0) > 0
    for c in ("exercise_net", "exercise_gross", "n_activities", "exercise_min", "n_meals"):
        out[c] = out[c].fillna(0)

    # peso usado em cada dia: último peso até a data (ou primeiro registrado / peso do perfil)
    w = _weights_df(conn, end)
    fallback = w["weight_kg"].iloc[0] if not w.empty else prof["initial_weight_kg"]
    if not w.empty:
        out = pd.merge_asof(out.sort_values("date"), w.rename(columns={"weight_kg": "weight_used"}),
                            on="date", direction="backward")
        out["weight_used"] = out["weight_used"].fillna(fallback)
    else:
        out["weight_used"] = fallback
    ws = weight_series(conn, start, end)
    out = out.merge(ws.rename(columns={"weight_kg": "weight"}), on="date", how="left")

    rows = []
    for r in out.itertuples():
        e = daily_expenditure(sex=prof["sex"], weight_kg=r.weight_used, height_cm=prof["height_cm"],
                              age=prof["age"], method=prof["energy_method"],
                              activity_level=prof["activity_level"], sedentary_factor=prof["sedentary_factor"],
                              exercise_net_kcal=r.exercise_net, exercise_gross_kcal=r.exercise_gross)
        g = records.goal_for(conn, r.date.date())
        rows.append({"bmr": e.bmr, "baseline": e.baseline, "exercise_counted": e.exercise_net, "tdee": e.total,
                     "goal_kcal": g["kcal"] if g else np.nan, "goal_protein": g["protein_g"] if g else np.nan,
                     "goal_carbs": g["carbs_g"] if g else np.nan, "goal_fat": g["fat_g"] if g else np.nan})
    out = pd.concat([out.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    out["balance"] = np.where(out["has_food"], out["tdee"] - out["kcal_in"].fillna(0), np.nan)
    out["status"] = np.select(
        [~out["has_food"], out["balance"] > band, out["balance"] < -band],
        ["sem_registro", "deficit", "superavit"], default="manutencao")
    out["above_goal"] = out["has_food"] & (out["kcal_in"] > out["goal_kcal"])
    return out


@dataclass
class PeriodStats:
    start: date
    end: date
    days: int
    days_logged: int
    avg_kcal_in: float | None
    avg_tdee: float | None
    avg_balance: float | None
    total_balance: float | None
    avg_protein: float | None
    avg_carbs: float | None
    avg_fat: float | None
    avg_fiber: float | None
    total_protein: float
    days_deficit: int
    days_surplus: int
    days_maintenance: int
    days_above_goal: int
    days_protein_goal_met: int
    goal_kcal_avg: float | None
    goal_protein_avg: float | None
    activities: int
    exercise_minutes: float
    exercise_net_total: float
    weight_start: float | None
    weight_end: float | None
    weight_change: float | None


def _nz(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def period_stats(conn: sqlite3.Connection, start: date, end: date, df: pd.DataFrame | None = None) -> PeriodStats:
    df = daily_summary(conn, start, end) if df is None else df
    logged = df[df["has_food"]]
    ws = weight_series(conn, start, end)
    w_start = w_end = None
    if not ws.empty:
        w_start, w_end = float(ws["ma7"].iloc[0]), float(ws["ma7"].iloc[-1])
    return PeriodStats(
        start=start, end=end, days=len(df), days_logged=len(logged),
        avg_kcal_in=_nz(logged["kcal_in"].mean()) if len(logged) else None,
        avg_tdee=_nz(df["tdee"].mean()),
        avg_balance=_nz(logged["balance"].mean()) if len(logged) else None,
        total_balance=_nz(logged["balance"].sum()) if len(logged) else None,
        avg_protein=_nz(logged["protein_g"].mean()) if len(logged) else None,
        avg_carbs=_nz(logged["carbs_g"].mean()) if len(logged) else None,
        avg_fat=_nz(logged["fat_g"].mean()) if len(logged) else None,
        avg_fiber=_nz(logged["fiber_g"].mean()) if len(logged) else None,
        total_protein=float(logged["protein_g"].sum()),
        days_deficit=int((df["status"] == "deficit").sum()),
        days_surplus=int((df["status"] == "superavit").sum()),
        days_maintenance=int((df["status"] == "manutencao").sum()),
        days_above_goal=int(df["above_goal"].sum()),
        days_protein_goal_met=int((logged["protein_g"] >= logged["goal_protein"]).sum()),
        goal_kcal_avg=_nz(df["goal_kcal"].mean()),
        goal_protein_avg=_nz(df["goal_protein"].mean()),
        activities=int(df["n_activities"].sum()),
        exercise_minutes=float(df["exercise_min"].sum()),
        exercise_net_total=float(df["exercise_net"].sum()),
        weight_start=w_start, weight_end=w_end,
        weight_change=None if w_start is None else round(w_end - w_start, 2),
    )


@dataclass
class WeightTrend:
    n_weighins: int
    span_days: int
    slope_kg_week: float | None          # tendência observada (regressão linear)
    expected_kg_week: float | None       # pelo saldo calculado (≈ kcal_per_kg)
    observed_tdee: float | None          # GET implícito pela tendência real
    estimated_tdee: float | None
    sufficient: bool
    message: str


def weight_trend(conn: sqlite3.Connection, end: date, days: int = 28) -> WeightTrend:
    """Compara a tendência real do peso com a esperada pelo saldo energético calculado."""
    start = end - timedelta(days=days - 1)
    ws = weight_series(conn, start, end)
    kcal_per_kg = settings_service.get_float(conn, "kcal_per_kg")
    df = daily_summary(conn, start, end)
    logged = df[df["has_food"]]
    n = len(ws)
    span = int((ws["date"].iloc[-1] - ws["date"].iloc[0]).days) if n else 0
    slope = expected = observed_tdee = None
    if n >= 2 and span >= 1:
        x = (ws["date"] - ws["date"].iloc[0]).dt.days.to_numpy(dtype=float)
        slope = float(np.polyfit(x, ws["weight_kg"].to_numpy(dtype=float), 1)[0]) * 7
    if len(logged):
        expected = -float(logged["balance"].mean()) * 7 / kcal_per_kg
    sufficient = n >= 8 and span >= 14 and len(logged) >= 10
    est_tdee = _nz(df["tdee"].mean())
    if sufficient and slope is not None:
        observed_tdee = float(logged["kcal_in"].mean()) - (slope / 7) * kcal_per_kg
        diff = observed_tdee - est_tdee
        if abs(diff) < 150:
            msg = "A tendência do peso é coerente com o gasto estimado."
        elif diff > 0:
            msg = (f"O peso está caindo mais (ou subindo menos) do que o previsto: seu gasto real parece "
                   f"~{diff:.0f} kcal/dia MAIOR que o estimado (ou parte do consumo não foi registrada a mais).")
        else:
            msg = (f"O peso está caindo menos do que o previsto: seu gasto real parece ~{-diff:.0f} kcal/dia "
                   f"MENOR que o estimado, ou parte do consumo pode não estar sendo registrada.")
    else:
        msg = ("Dados insuficientes para validar o gasto estimado: são necessárias ≥ 8 pesagens em ≥ 14 dias "
               "e ≥ 10 dias com alimentação registrada no período.")
    return WeightTrend(n, span, None if slope is None else round(slope, 3),
                       None if expected is None else round(expected, 3),
                       None if observed_tdee is None else round(observed_tdee), est_tdee and round(est_tdee),
                       sufficient, msg)
