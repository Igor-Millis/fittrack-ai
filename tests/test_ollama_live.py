"""Teste OPCIONAL com Ollama real. É pulado automaticamente se o Ollama não estiver rodando.
Modelo: variável OLLAMA_TEST_MODEL (padrão qwen2.5:3b)."""
from __future__ import annotations

import os

import pytest

from backend.ai.ollama_client import parse_with_llm, status

URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_TEST_MODEL", "qwen2.5:3b")
st = status(URL, timeout=2)
pytestmark = pytest.mark.skipif(not st.reachable or MODEL not in st.models,
                                reason=f"Ollama/modelo {MODEL} indisponível")


def test_llm_extracts_food_and_activity():
    p = parse_with_llm("Comi 150 g de arroz e 2 ovos e depois corri 5 km em 30 minutos", URL, MODEL, timeout=180)
    assert p is not None
    foods = {f.food.lower(): f for f in p.foods}
    assert any("arroz" in k for k in foods) and any("ovo" in k for k in foods)
    arroz = next(f for k, f in foods.items() if "arroz" in k)
    assert arroz.quantity in (150, None)  # nunca um número inventado
    run = [a for a in p.activities if a.activity_type == "corrida"]
    assert run and run[0].distance_km in (5, None) and run[0].duration_min in (30, None)


def test_llm_query_intent():
    p = parse_with_llm("Quanto consumi de proteína nesta semana?", URL, MODEL, timeout=180)
    assert p is not None and p.intent == "consulta"
