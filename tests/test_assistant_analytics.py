"""Integração: assistente (rascunho -> confirmação -> banco), consultas históricas e analytics."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from backend.ai.assistant import Assistant, merge_parses
from backend.analytics.daily import daily_summary, period_stats, weight_series, weight_trend
from backend.models.schemas import ActivityIn, LLMActivity, LLMFoodItem, LLMParse, MealIn, MealItemIn, WeightIn
from backend.services import records
from tests.conftest import food_id

TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 13, 0)


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture()
def bot(profile_conn):
    return Assistant(profile_conn, today=TODAY, now=NOW)


def test_requires_profile(conn):
    assert "perfil" in Assistant(conn, today=TODAY).handle("comi 100 g de arroz").text


def test_food_draft_then_confirm(bot, profile_conn):
    r = bot.handle("Comi 150 g de arroz, 100 g de feijão e 180 g de peito de frango.")
    assert r.draft and r.draft.ready and count(profile_conn, "meals") == 0  # nada salvo antes de confirmar
    assert "554 kcal" in r.text and r.draft.meal_type == "almoco"  # 13h -> almoço
    c = bot.handle("sim", r.draft)
    assert c.saved and c.draft is None and count(profile_conn, "meal_items") == 3
    total = profile_conn.execute("SELECT SUM(kcal) FROM meal_items").fetchone()[0]
    assert total == pytest.approx(554.2)


def test_cancel_saves_nothing(bot, profile_conn):
    r = bot.handle("Corri 5 km em 30 minutos")
    c = bot.handle("cancelar", r.draft)
    assert c.draft is None and count(profile_conn, "activities") == 0


def test_missing_quantity_is_asked(bot, profile_conn):
    r = bot.handle("almocei arroz e feijão")
    assert not r.draft.ready and "quantidade" in r.text.lower()
    assert "Ainda falta" in bot.handle("sim", r.draft).text and count(profile_conn, "meals") == 0
    for f in r.draft.foods:  # usuário corrige no cartão
        f.quantity, f.unit = 100, "g"
    assert bot.handle("sim", r.draft).saved


def test_ambiguous_requires_choice(bot):
    r = bot.handle("tomei 200 ml de leite")
    f = r.draft.foods[0]
    assert f.food_id is None and len(f.candidates) > 1 and "várias correspondências" in f.issue


def test_unknown_food_not_invented(bot):
    r = bot.handle("comi 30 g de whey protein")
    assert not r.draft.ready and "não encontrado" in r.draft.foods[0].issue


def test_unknown_household_measure_asks(bot):
    r = bot.handle("comi 1 tomate")
    assert "Não sei quantos gramas" in r.draft.foods[0].issue


def test_activities_and_running_without_duration(bot, profile_conn):
    r = bot.handle("Fiz musculação por 1 hora e corri 3 km")
    assert not r.draft.ready and "duração" in r.draft.activities[1].issue
    r.draft.activities[1].duration_min = 18
    c = bot.handle("sim", r.draft)
    assert c.saved and count(profile_conn, "activities") == 2


def test_weight_flow_and_replace(bot, profile_conn):
    bot.handle("sim", bot.handle("Hoje acordei com 79,4 kg").draft)
    r = bot.handle("pesei 79,1 hoje")
    assert r.draft.weight_exists == 79.4 and "substituirá" in r.text
    bot.handle("sim", r.draft)
    assert records.get_weight(profile_conn, TODAY)["weight_kg"] == 79.1 and count(profile_conn, "weights") == 1


def test_duplicate_detected_in_chat(bot):
    bot.handle("sim", bot.handle("comi 100 g de arroz").draft)
    r2 = bot.handle("sim", bot.handle("comi 100 g de arroz").draft)
    assert "idêntica" in r2.text and not r2.saved
    assert bot.confirm(r2.draft, allow_duplicate=True).saved


def test_undo_requires_confirmation(bot, profile_conn):
    bot.handle("sim", bot.handle("comi 100 g de arroz").draft)
    r = bot.handle("apagar o último registro")
    assert count(profile_conn, "meals") == 1 and r.draft.pending_delete
    bot.handle("sim", r.draft)
    assert count(profile_conn, "meals") == 0


def test_future_date_rejected(profile_conn):
    bot = Assistant(profile_conn, today=TODAY - timedelta(days=5), now=NOW)
    assert "futura" in bot.handle("no dia 12/11 comi 100 g de arroz").text


def test_past_date(bot):
    r = bot.handle("ontem no jantar comi 2 ovos")
    assert r.draft.day == TODAY - timedelta(days=1) and r.draft.meal_type == "jantar"


def test_merge_llm_with_rules():
    llm = LLMParse(intent="registrar_atividades", activities=[LLMActivity(activity_type="corrida", distance_km=10)],
                   foods=[LLMFoodItem(food="arroz")])
    rules = LLMParse(intent="registrar_atividades", activities=[LLMActivity(activity_type="corrida", duration_min=55, distance_km=10)],
                     foods=[LLMFoodItem(food="arroz", quantity=150, unit="g")])
    m = merge_parses(llm, rules)
    assert m.activities[0].duration_min == 55 and m.foods[0].quantity == 150


# ------------------------------------------------------------------ analytics e consultas
@pytest.fixture()
def history(profile_conn):
    """16 dias (i=0..15, i=15 é hoje): 2000 kcal/dia exceto i=4 e i=9 (sem registro), musculação 60 min em i par,
    peso caindo 0,1 kg/dia."""
    c = profile_conn
    arroz = food_id(c, "Arroz, tipo 1, cozido")  # 128 kcal/100 g
    for i in range(16):
        d = TODAY - timedelta(days=15 - i)
        if i not in (4, 9):
            records.save_meal(c, MealIn(date=d, meal_type="almoco", items=[MealItemIn(food_id=arroz, quantity=1562.5, unit="g")]))
        if i % 2 == 0:
            records.save_activity(c, ActivityIn(date=d, activity_type="musculacao", duration_min=60, intensity="moderada"))
        records.save_weight(c, WeightIn(date=d, weight_kg=round(81.3 - 0.1 * i, 2)))
    return c


def test_daily_summary_balance(history):
    df = daily_summary(history, TODAY - timedelta(days=15), TODAY)
    assert len(df) == 16 and df["has_food"].sum() == 14
    assert np.isnan(df.loc[4, "balance"]) and df.loc[4, "status"] == "sem_registro"  # sem consumo != déficit
    for idx, trained in ((14, True), (15, False)):
        row = df.iloc[idx]
        w = row["weight_used"]
        assert w == pytest.approx(81.3 - 0.1 * idx)
        bmr = 10 * w + 6.25 * 180 - 5 * 30 + 5
        expected_ex = (5.0 - 1) * w if trained else 0  # musculação moderada (MET 5) 60 min: líquido = 4 × kg
        assert row["kcal_in"] == pytest.approx(2000)
        assert row["tdee"] == pytest.approx(bmr * 1.2 + expected_ex, abs=0.6)
        assert row["balance"] == pytest.approx(row["tdee"] - 2000)


def test_moving_average(history):
    ws = weight_series(history, TODAY - timedelta(days=13), TODAY)  # começa em i=2
    last7 = [81.3 - 0.1 * i for i in range(9, 16)]
    assert ws["ma7"].iloc[-1] == pytest.approx(sum(last7) / 7)
    assert ws["ma7"].iloc[0] == pytest.approx((81.3 + 81.2 + 81.1) / 3)  # janela usa pesagens anteriores


def test_period_stats(history):
    s = period_stats(history, TODAY - timedelta(days=6), TODAY)
    assert s.days == 7 and s.days_logged == 6  # i=9..15; i=9 sem registro
    assert s.avg_kcal_in == pytest.approx(2000)
    assert s.days_deficit + s.days_surplus + s.days_maintenance == 6
    assert s.activities == 3 and s.exercise_minutes == 180  # i=10, 12, 14
    assert s.weight_change == pytest.approx(-0.6, abs=0.01)


def test_weight_trend(history):
    wt = weight_trend(history, TODAY, days=16)
    assert wt.slope_kg_week == pytest.approx(-0.7, abs=0.01)
    assert wt.sufficient and wt.observed_tdee == pytest.approx(2000 + 0.1 * 7700, abs=1)


@pytest.mark.parametrize("question,expected", [
    ("Quantas calorias consumi ontem?", "2.000 kcal"),
    ("Estou em déficit hoje?", "consumo de 2.000 kcal"),
    ("Quanto consumi de proteína nesta semana?", "total de"),
    ("Qual foi meu déficit acumulado nos últimos sete dias?", "Saldo acumulado"),
    ("Qual foi minha média de calorias nos últimos 30 dias?", "consumo **2.000 kcal/dia**"),
    ("Compare esta semana com a anterior.", "| Consumo médio (kcal) |"),
    ("Quais dias fiquei acima da minha meta?", "não passou da meta"),
    ("Estou perdendo peso no ritmo esperado?", "Tendência observada"),
    ("Estou comendo proteína suficiente?", "g/kg"),
    ("Quanto ainda posso comer hoje?", "ainda restam **200 kcal**"),
    ("relatório da semana", "Relatório"),
])
def test_history_queries_use_db(history, question, expected):
    r = Assistant(history, today=TODAY, now=NOW).handle(question)
    assert expected in r.text and r.draft is None


def test_protein_week_value(history):
    # proteína do arroz: 2,5 g/100 g × 1562,5 g = 39,06 g/dia; "esta semana" (seg 09/11 a sáb 14/11) tem 6 dias com registro
    r = Assistant(history, today=TODAY, now=NOW).handle("Quanto consumi de proteína nesta semana?")
    assert "total de **234 g**" in r.text
