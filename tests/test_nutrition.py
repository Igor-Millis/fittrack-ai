"""Unidades, cálculo nutricional, base TACO e busca de alimentos."""
from __future__ import annotations

import csv

import pytest

from backend import config
from backend.nutrition import foods as food_repo
from backend.nutrition.calculator import compute_item, nutrients_for, total
from backend.nutrition.units import ConversionError, Portion, canonical_unit, to_grams
from tests.conftest import food_id


# ------------------------------------------------------------------ unidades
@pytest.mark.parametrize("raw,expected", [
    ("gramas", "g"), ("g", "g"), ("Quilos", "kg"), ("ml", "ml"), ("litros", "l"), ("colheres de sopa", "colher de sopa"),
    ("colher de chá", "colher de cha"), ("fatias", "fatia"), ("porções", "porcao"), ("unidades", "unidade"), ("xyz", None),
])
def test_canonical_unit(raw, expected):
    assert canonical_unit(raw) == expected


def test_mass_conversion():
    assert to_grams(150, "g").grams == 150
    assert to_grams(0.25, "kg").grams == 250
    assert to_grams(500, "mg").grams == pytest.approx(0.5)


def test_volume_requires_density():
    with pytest.raises(ConversionError):
        to_grams(200, "ml", density_g_ml=None)
    assert to_grams(200, "ml", density_g_ml=1.03).grams == pytest.approx(206)
    assert to_grams(0.5, "l", density_g_ml=1.0).grams == pytest.approx(500)


def test_household_portions_and_sizes():
    portions = [Portion("unidade", "pequeno", 40, "x"), Portion("unidade", "medio", 55, "x"), Portion("unidade", "grande", 70, "x")]
    assert to_grams(2, "unidade", portions=portions).grams == 110          # sem tamanho -> médio
    assert to_grams(1, "unidade", portions=portions, size="grande").grams == 70
    with pytest.raises(ConversionError):
        to_grams(1, "fatia", portions=portions)                             # medida inexistente -> pergunta
    with pytest.raises(ConversionError):
        to_grams(1, "unidade", portions=[Portion("unidade", "medio", 50, "x")], size="grande")


def test_spoon_uses_density_only_without_portion():
    assert to_grams(2, "colher de sopa", density_g_ml=1.0).grams == 30
    with pytest.raises(ConversionError):
        to_grams(2, "colher de sopa")


def test_invalid_quantity():
    with pytest.raises(ConversionError):
        to_grams(0, "g")


# ------------------------------------------------------------------ cálculo
def test_nutrients_scale_linearly():
    food = {"kcal": 128, "protein_g": 2.5, "carbs_g": 28.1, "fat_g": 0.2, "fiber_g": 1.6}
    n = nutrients_for(food, 150)
    assert n.kcal == pytest.approx(192)
    assert n.protein_g == pytest.approx(3.75)
    assert n.carbs_g == pytest.approx(42.15)
    assert n.fat_g == pytest.approx(0.3)
    assert n.fiber_g == pytest.approx(2.4)


def test_missing_macro_is_zero_but_missing_fiber_unknown():
    n = nutrients_for({"kcal": 884, "protein_g": None, "carbs_g": None, "fat_g": 100, "fiber_g": None}, 10)
    assert n.kcal == pytest.approx(88.4) and n.protein_g == 0 and n.fat_g == pytest.approx(10)
    assert n.fiber_g is None


def test_compute_item_and_total_from_taco(conn):
    arroz = compute_item(conn, food_id(conn, "Arroz, tipo 1, cozido"), 150, "g")
    feijao = compute_item(conn, food_id(conn, "Feijão, carioca, cozido"), 100, "g")
    frango = compute_item(conn, food_id(conn, "Frango, peito, sem pele, grelhado"), 180, "g")
    t = total([arroz, feijao, frango])
    assert arroz.nutrients.kcal == pytest.approx(192)       # 128 kcal/100 g (TACO)
    assert feijao.nutrients.kcal == pytest.approx(76)
    assert frango.nutrients.kcal == pytest.approx(286.2)    # 159 × 1,8
    assert t.kcal == pytest.approx(554.2)
    assert t.protein_g == pytest.approx(3.75 + 4.8 + 57.6)


def test_bread_unit_uses_registered_portion(conn):
    item = compute_item(conn, food_id(conn, "Pão, trigo, francês"), 2, "unidade")
    assert item.grams == 100 and item.nutrients.kcal == pytest.approx(300)
    assert "50 g" in item.basis


# ------------------------------------------------------------------ base TACO
def test_taco_csv_complete_and_consistent():
    rows = list(csv.DictReader(open(config.TACO_CSV, encoding="utf-8")))
    assert len(rows) == 597
    assert [int(r["taco_id"]) for r in rows] == list(range(1, 598))
    by = {r["nome"]: r for r in rows}
    assert float(by["Arroz, tipo 1, cozido"]["energia_kcal"]) == 128
    assert float(by["Banana, prata, crua"]["energia_kcal"]) == 98
    assert float(by["Frango, peito, sem pele, grelhado"]["proteina_g"]) == 32.0
    # coerência de Atwater (4/4/9) para alimentos sem álcool: tolerância ampla
    bad = []
    for r in rows:
        if not r["energia_kcal"] or r["categoria"].startswith("Bebidas"):
            continue
        e = 4 * float(r["proteina_g"] or 0) + 4 * float(r["carboidrato_g"] or 0) + 9 * float(r["lipidios_g"] or 0)
        if abs(float(r["energia_kcal"]) - e) > 0.25 * float(r["energia_kcal"]) + 15:
            bad.append(r["nome"])
    assert bad == ["Fermento em pó, químico"]  # único caso conhecido na própria TACO


def test_import_skips_not_analyzed_foods(conn):
    n = conn.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
    assert n == 591  # 597 − 6 sem energia analisada (marcados '*' na TACO)
    assert conn.execute("SELECT COUNT(*) FROM foods WHERE name='Leite, de vaca, integral'").fetchone()[0] == 0


# ------------------------------------------------------------------ busca
@pytest.mark.parametrize("query,expected", [
    ("arroz", "Arroz, tipo 1, cozido"), ("feijão", "Feijão, carioca, cozido"),
    ("peito de frango", "Frango, peito, sem pele, grelhado"), ("pães franceses", "Pão, trigo, francês"),
    ("ovos", "Ovo, de galinha, inteiro, cozido/10minutos"), ("batata doce", "Batata, doce, cozida"),
    ("alfase", "Alface, lisa, crua"),  # erro de digitação corrigido
])
def test_match_food(conn, query, expected):
    names = [c.name for c in food_repo.match_food(conn, query).candidates]
    assert expected in names[:4]
    if query in ("arroz", "feijão", "peito de frango"):
        assert names[0] == expected


def test_ambiguous_and_not_found(conn):
    assert food_repo.match_food(conn, "leite").ambiguous
    assert not food_repo.match_food(conn, "whey protein").found


def test_custom_food_is_searchable(conn):
    from backend.models.schemas import CustomFoodIn, PortionIn
    fid = food_repo.add_custom_food(conn, CustomFoodIn(name="Whey protein X", kcal=400, protein_g=80, carbs_g=8, fat_g=6,
                                                       portions=[PortionIn(unit="porcao", grams=30)]))
    m = food_repo.match_food(conn, "whey protein x")
    assert m.best.food_id == fid and not m.ambiguous
    assert compute_item(conn, fid, 1, "porcao").nutrients.kcal == pytest.approx(120)


def test_custom_food_validation():
    from pydantic import ValidationError

    from backend.models.schemas import CustomFoodIn
    with pytest.raises(ValidationError):
        CustomFoodIn(name="Impossível", kcal=500, protein_g=60, carbs_g=50, fat_g=10)  # 120 g de macros em 100 g
