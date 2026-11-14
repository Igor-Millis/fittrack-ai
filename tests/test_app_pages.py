"""Testes da interface com o AppTest do Streamlit (renderiza as páginas sem navegador)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from backend.models.schemas import ActivityIn, MealIn, MealItemIn, WeightIn
from backend.services import records
from tests.conftest import ROOT, food_id

PAGES = ["dashboard", "chat", "alimentacao", "exercicios", "peso", "relatorios", "configuracoes"]


@pytest.fixture()
def seeded(profile_conn):
    arroz = food_id(profile_conn, "Arroz, tipo 1, cozido")
    for i in range(5):
        d = date.today() - timedelta(days=i)
        records.save_meal(profile_conn, MealIn(date=d, meal_type="almoco", items=[MealItemIn(food_id=arroz, quantity=300, unit="g")]))
        records.save_activity(profile_conn, ActivityIn(date=d, activity_type="corrida", duration_min=30, distance_km=5))
        records.save_weight(profile_conn, WeightIn(date=d, weight_kg=80 - i * 0.1))
    return profile_conn


def run_page(name: str) -> AppTest:
    """Executa pelo ponto de entrada real (main.py + st.navigation) e troca para a página."""
    at = AppTest.from_file(str(ROOT / "app" / "main.py"), default_timeout=90)
    at.run()
    assert not at.exception, at.exception
    at.switch_page(f"pages/{name}.py").run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_without_errors(seeded, page):
    at = run_page(page)
    assert not at.exception, at.exception


def test_first_run_shows_setup_wizard(conn):
    at = run_page("configuracoes")
    assert not at.exception
    assert any("Bem-vindo" in m.value for m in at.markdown)


def test_dashboard_shows_db_values(seeded):
    at = run_page("dashboard")
    html = " ".join(m.value for m in at.markdown)
    assert "384" in html  # 300 g de arroz × 128 kcal/100 g = 384 kcal hoje


def test_chat_registers_through_ui(seeded):
    at = run_page("chat")
    at.chat_input[0].set_value("comi 100 g de feijão").run()
    assert not at.exception
    confirm = next(b for b in at.button if b.label == "Confirmar registro")
    confirm.click().run()
    assert not at.exception
    n = seeded.execute("SELECT COUNT(*) FROM meal_items WHERE food_name='Feijão, carioca, cozido'").fetchone()[0]
    assert n == 1
