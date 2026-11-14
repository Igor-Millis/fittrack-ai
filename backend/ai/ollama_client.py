"""Integração OPCIONAL com Ollama (LLM local).

O LLM é usado apenas para INTERPRETAR a mensagem e devolver JSON no contrato `LLMParse`.
Ele nunca calcula calorias, nunca acessa o banco e nunca gera SQL. A saída é validada pelo
Pydantic e depois "aterrada" no texto original (ver `ground`): quantidades, durações e pesos
que não aparecem na mensagem do usuário são descartados — o sistema então pergunta.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import requests
from pydantic import ValidationError

from backend.ai.rule_parser import WORD_NUMBERS
from backend.models.schemas import LLMParse
from backend.textutil import light_norm, tokens

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é o interpretador de mensagens do FitTrack, um diário de alimentação e exercícios em português do Brasil.
Sua ÚNICA tarefa é converter a mensagem do usuário em JSON seguindo o esquema fornecido. Regras:
- NÃO calcule calorias nem nutrientes. NÃO invente quantidades, durações, distâncias ou pesos: use null quando o usuário não informou.
- intent: registrar_alimentos (o que comeu/bebeu), registrar_atividades (exercícios), registrar_peso (peso corporal),
  consulta (perguntas sobre o histórico), confirmar (sim/ok), cancelar (não), desfazer (apagar último registro), ajuda, desconhecido.
- foods: um item por alimento. "food" = nome do alimento como o usuário escreveu (sem quantidade). quantity = número; unit em
  [g, kg, mg, ml, l, unidade, fatia, porcao, colher de sopa, colher de cha, concha, xicara, copo, pote, quadrado, pedaco, lata].
  "dois pães" => quantity 2, unit "unidade". size: pequeno|medio|grande se dito.
- activities: activity_type em [musculacao, corrida, caminhada, bicicleta_ergometrica, ciclismo, natacao, esportes, outra];
  duration_min em minutos (1h20 = 80); distance_km; intensity leve|moderada|vigorosa se dita; description = esporte específico (ex.: futebol).
- Mensagem pode ter alimentos E atividades: preencha os dois. date_ref: hoje|ontem|anteontem|YYYY-MM-DD se mencionado.
- meal_type: cafe_da_manha|lanche_manha|almoco|lanche_tarde|jantar|ceia|outro se mencionado.
- Para consulta, query em [status_hoje, restante_hoje, consumo_dia, proteina_periodo, saldo_periodo, ritmo_peso, media_periodo,
  comparar_semanas, dias_acima_meta, proteina_suficiente, relatorio, peso_atual, atividades_periodo] e period_days se houver (ex.: 30).
Responda somente o JSON."""


@dataclass
class OllamaStatus:
    reachable: bool
    models: list[str]
    error: str | None = None


def status(url: str, timeout: float = 3) -> OllamaStatus:
    try:
        r = requests.get(f"{url.rstrip('/')}/api/tags", timeout=timeout)
        r.raise_for_status()
        return OllamaStatus(True, [m["name"] for m in r.json().get("models", [])])
    except Exception as e:  # noqa: BLE001 - qualquer falha = indisponível
        return OllamaStatus(False, [], str(e)[:200])


def parse_with_llm(message: str, url: str, model: str, timeout: float) -> LLMParse | None:
    """Retorna LLMParse validado, ou None se o LLM falhar/estiver fora/retornar JSON inválido."""
    payload = {
        "model": model,
        "stream": False,
        "format": LLMParse.model_json_schema(),
        "options": {"temperature": 0},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message}],
    }
    try:
        r = requests.post(f"{url.rstrip('/')}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        parsed = LLMParse.model_validate(json.loads(content))
    except (requests.RequestException, KeyError, json.JSONDecodeError, ValidationError) as e:
        log.warning("LLM indisponível ou resposta inválida (%s); usando interpretador de regras.", type(e).__name__)
        return None
    return ground(parsed, message)


# ------------------------------------------------------------------ aterramento
def _numbers_in(text: str) -> set[float]:
    t = light_norm(text)
    nums: list[float] = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", t)]
    nums += [float(WORD_NUMBERS[w]) for w in re.findall(r"[a-z]+", t) if w in WORD_NUMBERS]
    allowed = set(nums)
    allowed |= {n * 60 for n in nums}                     # horas -> minutos
    allowed |= {n * 1000 for n in nums} | {n / 1000 for n in nums}  # km <-> m
    allowed |= {a * 60 + b for a, b in zip(nums, nums[1:])}  # "1 hora e 20"
    if "meia hora" in t:
        allowed.add(30.0)
    if re.search(r"\b(meio|meia)\b", t):
        allowed.add(0.5)
    if re.search(r"\b(um|uma)\b", t):
        allowed.add(1.0)
    return allowed


def _grounded(v: float | None, allowed: set[float]) -> bool:
    return v is None or any(abs(v - a) < 0.051 for a in allowed)


def ground(p: LLMParse, message: str) -> LLMParse:
    allowed = _numbers_in(message)
    msg_tokens = set(tokens(message))
    foods = []
    for f in p.foods:
        if not (set(tokens(f.food)) & msg_tokens):
            continue  # alimento que não aparece na mensagem: descartado
        if not _grounded(f.quantity, allowed):
            f = f.model_copy(update={"quantity": None})
        foods.append(f)
    acts = []
    for a in p.activities:
        upd = {}
        if not _grounded(a.duration_min, allowed):
            upd["duration_min"] = None
        if not _grounded(a.distance_km, allowed):
            upd["distance_km"] = None
        acts.append(a.model_copy(update=upd) if upd else a)
    weight = p.weight_kg if _grounded(p.weight_kg, allowed) else None
    return p.model_copy(update={"foods": foods, "activities": acts, "weight_kg": weight})
