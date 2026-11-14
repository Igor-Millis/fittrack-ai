"""Interpretação de mensagens (interpretador por regras) e aterramento da saída do LLM."""
from __future__ import annotations

from datetime import date

import pytest

from backend.ai.dates import parse_period, resolve_date_ref
from backend.ai.ollama_client import ground, parse_with_llm
from backend.ai.rule_parser import parse
from backend.models.schemas import LLMActivity, LLMFoodItem, LLMParse


def foods(msg):
    return [(f.food, f.quantity, f.unit, f.size) for f in parse(msg).foods]


def test_foods_with_grams():
    assert foods("Comi 150 g de arroz, 100 g de feijão e 180 g de peito de frango.") == [
        ("arroz", 150, "g", None), ("feijao", 100, "g", None), ("peito de frango", 180, "g", None)]


def test_word_numbers_units_and_size():
    assert foods("Comi dois pães franceses com 30 g de queijo.") == [("paes franceses", 2, "unidade", None), ("queijo", 30, "g", None)]
    p = parse("Meu café da manhã foi um abacate pequeno e um iogurte.")
    assert p.meal_type == "cafe_da_manha"
    assert [(f.food, f.quantity, f.size) for f in p.foods] == [("abacate", 1, "pequeno"), ("iogurte", 1, None)]


@pytest.mark.parametrize("msg,expected", [
    ("comi meio pão francês", [("pao frances", 0.5, "unidade", None)]),
    ("comi 1,5 colher de sopa de azeite", [("azeite", 1.5, "colher de sopa", None)]),
    ("comi arroz 150g", [("arroz", 150, "g", None)]),
    ("tomei 300 ml de café", [("cafe", 300, "ml", None)]),
    ("almocei arroz e feijão", [("arroz", None, None, None), ("feijao", None, None, None)]),  # sem quantidade -> perguntar
])
def test_food_variants(msg, expected):
    assert foods(msg) == expected


@pytest.mark.parametrize("msg,kind,dur,dist,inten", [
    ("Hoje fiz musculação por 1 hora e 20 minutos.", "musculacao", 80, None, None),
    ("Corri 5 km em 30 minutos.", "corrida", 30, 5, None),
    ("Pedalei por 25 minutos em intensidade moderada.", "ciclismo", 25, None, "moderada"),
    ("Hoje caminhei por 40 minutos.", "caminhada", 40, None, None),
    ("joguei futebol por 1h30", "esportes", 90, None, None),
    ("corri 10 km no ritmo 5:30/km", "corrida", 55, 10, None),
    ("nadei 40 min leve", "natacao", 40, None, "leve"),
    ("fiz bike ergométrica 30 minutos forte", "bicicleta_ergometrica", 30, None, "vigorosa"),
])
def test_activities(msg, kind, dur, dist, inten):
    p = parse(msg)
    assert p.intent == "registrar_atividades"
    a = p.activities[0]
    assert (a.activity_type, a.duration_min, a.distance_km, a.intensity) == (kind, dur, dist, inten)


def test_two_activities_in_one_message():
    p = parse("Fiz musculação por 1 hora e corri 3 km")
    assert [(a.activity_type, a.duration_min, a.distance_km) for a in p.activities] == [
        ("musculacao", 60, None), ("corrida", None, 3)]  # corrida sem duração -> será perguntada


def test_food_and_activity_together():
    p = parse("no almoço comi 200 g de arroz e depois caminhei 30 minutos")
    assert [f.food for f in p.foods] == ["arroz"] and p.activities[0].activity_type == "caminhada"


@pytest.mark.parametrize("msg,w", [("Hoje acordei com 71,2 kg.", 71.2), ("pesei 80.5 hoje", 80.5), ("meu peso hoje: 92 kg", 92.0)])
def test_weight(msg, w):
    p = parse(msg)
    assert p.intent == "registrar_peso" and p.weight_kg == w


def test_food_kg_is_not_body_weight():
    assert parse("comi 1 kg de melancia").intent == "registrar_alimentos"


@pytest.mark.parametrize("msg,query", [
    ("Estou em déficit hoje?", "status_hoje"),
    ("Quanto consumi de proteína nesta semana?", "proteina_periodo"),
    ("Quanto ainda posso comer hoje?", "restante_hoje"),
    ("Quantas calorias consumi ontem?", "consumo_dia"),
    ("Qual foi meu déficit acumulado nos últimos sete dias?", "saldo_periodo"),
    ("Estou perdendo peso no ritmo esperado?", "ritmo_peso"),
    ("Qual foi minha média de calorias nos últimos 30 dias?", "media_periodo"),
    ("Compare esta semana com a anterior.", "comparar_semanas"),
    ("Quais dias fiquei acima da minha meta?", "dias_acima_meta"),
    ("Estou comendo proteína suficiente?", "proteina_suficiente"),
])
def test_queries(msg, query):
    p = parse(msg)
    assert p.intent == "consulta" and p.query == query


@pytest.mark.parametrize("msg,intent", [("sim", "confirmar"), ("Confirmar", "confirmar"), ("cancelar", "cancelar"),
                                        ("não", "cancelar"), ("apagar o último registro", "desfazer"), ("ajuda", "ajuda"),
                                        ("bom dia", "desconhecido")])
def test_commands(msg, intent):
    assert parse(msg).intent == intent


def test_dates_and_periods():
    today = date(2026, 11, 14)  # sábado
    assert resolve_date_ref("ontem", today) == date(2026, 11, 13)
    assert resolve_date_ref("12/11", today) == date(2026, 11, 12)
    with pytest.raises(ValueError):
        resolve_date_ref("20/12", today)  # sem ano, futuro próximo -> recusado (não vira o ano passado em silêncio)
    assert resolve_date_ref("30/12", date(2027, 1, 5)) == date(2026, 12, 30)  # virada de ano
    assert resolve_date_ref("segunda", today) == date(2026, 11, 9)
    assert parse("ontem no jantar comi 2 ovos").date_ref == "ontem"
    p = parse_period("quanto consumi nesta semana", today)
    assert (p.start, p.end) == (date(2026, 11, 9), today)
    assert parse_period("ultimos 30 dias", today).days == 30
    assert parse_period("semana passada", today).start == date(2026, 11, 2)
    assert not parse_period("qual a media", today).explicit


# ------------------------------------------------------------------ LLM: aterramento
def test_ground_discards_invented_values():
    msg = "comi arroz e 2 ovos e corri 5 km"
    llm = LLMParse(intent="registrar_alimentos",
                   foods=[LLMFoodItem(food="arroz", quantity=150, unit="g"),     # 150 não está na mensagem
                          LLMFoodItem(food="ovos", quantity=2, unit="unidade"),
                          LLMFoodItem(food="banana", quantity=1, unit="unidade")],  # alimento inventado
                   activities=[LLMActivity(activity_type="corrida", duration_min=30, distance_km=5)],  # 30 inventado
                   weight_kg=80)
    g = ground(llm, msg)
    assert [(f.food, f.quantity) for f in g.foods] == [("arroz", None), ("ovos", 2)]
    assert g.activities[0].duration_min is None and g.activities[0].distance_km == 5
    assert g.weight_kg is None


def test_ground_accepts_unit_conversions():
    g = ground(LLMParse(intent="registrar_atividades",
                        activities=[LLMActivity(activity_type="musculacao", duration_min=80)]), "treinei 1 hora e 20 minutos")
    assert g.activities[0].duration_min == 80


def test_llm_unreachable_returns_none():
    assert parse_with_llm("comi arroz", "http://127.0.0.1:9", "x", timeout=1) is None
