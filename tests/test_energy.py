"""TMB, gasto diário, METs e prevenção de dupla contagem."""
from __future__ import annotations

import pytest

from backend.energy.metabolism import bmr_mifflin, daily_expenditure, suggest_goals
from backend.exercise.mets import activity_energy, choose_met, interpolate, RUNNING_SPEED_MET


def test_mifflin_st_jeor():
    assert bmr_mifflin("M", 80, 180, 30) == pytest.approx(10 * 80 + 6.25 * 180 - 5 * 30 + 5)   # 1780
    assert bmr_mifflin("F", 60, 165, 25) == pytest.approx(10 * 60 + 6.25 * 165 - 5 * 25 - 161)  # 1345.25
    with pytest.raises(ValueError):
        bmr_mifflin("X", 60, 165, 25)


def test_net_vs_gross_activity_energy():
    e = activity_energy(met=8.0, weight_kg=80, duration_min=60)
    assert e.kcal_gross == pytest.approx(640)
    assert e.kcal_net == pytest.approx(560)  # desconta 1 MET de repouso
    assert e.kcal_gross - e.kcal_net == pytest.approx(80)  # = repouso no período


def test_sedentary_plus_exercise_has_no_double_count():
    kw = dict(sex="M", weight_kg=80, height_cm=180, age=30, activity_level="moderado", sedentary_factor=1.2)
    rest = daily_expenditure(method="sedentario_mais_exercicio", exercise_net_kcal=0, **kw)
    train = daily_expenditure(method="sedentario_mais_exercicio", exercise_net_kcal=560, exercise_gross_kcal=640, **kw)
    assert rest.total == pytest.approx(1780 * 1.2)
    assert train.total - rest.total == pytest.approx(560)  # soma só o líquido, não o bruto


def test_activity_factor_method_ignores_logged_exercise():
    kw = dict(sex="M", weight_kg=80, height_cm=180, age=30, activity_level="moderado", sedentary_factor=1.2)
    a = daily_expenditure(method="fator_atividade", exercise_net_kcal=0, **kw)
    b = daily_expenditure(method="fator_atividade", exercise_net_kcal=600, **kw)
    assert a.total == b.total == pytest.approx(1780 * 1.55)


def test_met_interpolation_by_speed():
    assert interpolate(RUNNING_SPEED_MET, 9.7) == pytest.approx(9.8)
    m = choose_met("corrida", duration_min=30, distance_km=5)  # 10 km/h
    assert 9.8 < m.met < 10.5 and "10.0 km/h" in m.source
    assert choose_met("caminhada", duration_min=60, distance_km=4.8).met == pytest.approx(3.5)


def test_met_defaults_and_specific():
    assert choose_met("musculacao").met == 5.0 and "assumida moderada" in choose_met("musculacao").source
    assert choose_met("musculacao", "vigorosa").met == 6.0
    assert choose_met("esportes", specific="futebol").met == 7.0


def test_suggested_goals_are_coherent():
    g = suggest_goals(sex="M", weight_kg=80, height_cm=180, age=30, activity_level="moderado", goal="emagrecimento")
    assert g["kcal"] == pytest.approx(round(1780 * 1.55 * 0.8 / 10) * 10)
    assert g["protein_g"] == 128
    assert abs(g["protein_g"] * 4 + g["carbs_g"] * 4 + g["fat_g"] * 9 - g["kcal"]) < 15
