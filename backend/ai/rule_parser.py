"""Interpretador determinístico (sem IA) de mensagens em português.

Produz exatamente o mesmo contrato (`LLMParse`) que o LLM, de modo que o resto do sistema
não depende de qual interpretador foi usado. Funciona offline e é o fallback quando o
Ollama está desligado/indisponível.
"""
from __future__ import annotations

import re

from backend.ai.dates import extract_date_ref
from backend.exercise.mets import SPECIFIC_MET
from backend.models.schemas import LLMActivity, LLMFoodItem, LLMParse
from backend.nutrition.units import canonical_unit
from backend.textutil import light_norm

WORD_NUMBERS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
    "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "quinze": 15, "vinte": 20, "trinta": 30,
    "quarenta": 40, "cinquenta": 50, "meia": 0.5, "meio": 0.5,
}
NUM = r"(?:\d+(?:[.,]\d+)?|\d+/\d+|" + "|".join(sorted(WORD_NUMBERS, key=len, reverse=True)) + r")"

UNIT_WORDS = [
    "colheres de sopa", "colher de sopa", "colheres de cha", "colher de cha", "colher sopa", "colher cha",
    "quilogramas", "quilograma", "quilos", "quilo", "kilos", "kilo", "kgs", "kg", "miligramas", "mg",
    "gramas", "grama", "grs", "gr", "g", "mililitros", "mililitro", "ml", "litros", "litro", "lt", "l",
    "unidades", "unidade", "unid", "und", "un", "fatias", "fatia", "porcoes", "porcao", "colheres", "colher",
    "conchas", "concha", "xicaras", "xicara", "copos", "copo", "potinho", "potes", "pote", "quadradinho",
    "quadrados", "quadrado", "pedacos", "pedaco", "latas", "lata", "escumadeiras", "escumadeira",
]
UNIT_RE = "|".join(re.escape(u) for u in UNIT_WORDS)
SIZE_WORDS = {"pequeno": "pequeno", "pequena": "pequeno", "medio": "medio", "media": "medio",
              "grande": "grande"}

MEAL_PATTERNS = [
    (r"cafe da manha|desjejum", "cafe_da_manha"),
    (r"lanche da manha", "lanche_manha"),
    (r"lanche da tarde|cafe da tarde", "lanche_tarde"),
    (r"\balmoco\b|\balmocei\b", "almoco"),
    (r"\bjantar\b|\bjantei\b|\bjanta\b", "jantar"),
    (r"\bceia\b", "ceia"),
    (r"\blanche\b|\blanchei\b", "lanche_tarde"),
]

FOOD_LEADS = re.compile(
    r"^(?:(?:e|entao|hoje|ontem|agora|tambem|eu|comi|bebi|tomei|almocei|jantei|lanchei|ingeri|consumi|"
    r"meu|minha|no|na|de|o|a|foi|foram|teve|tive|so|apenas)\b\s*|[:\-]\s*)*", re.I)

ACTIVITY_KEYWORDS: list[tuple[str, str]] = [
    (r"musculacao|academia|treino de forca|treinei (?:perna|peito|costas|braco|ombro|bracos|pernas)|malhei|"
     r"musculacao|levantamento de peso", "musculacao"),
    (r"bicicleta ergometrica|ergometrica|bike ergometrica|spinning|bike indoor|bicicleta estacionaria", "bicicleta_ergometrica"),
    (r"\bcorri\b|\bcorrida\b|\bcorrer\b|\bcorrendo\b|\bjogging\b|\btrote\b", "corrida"),
    (r"\bcaminhei\b|\bcaminhada\b|\bcaminhar\b|\bandei\b|\btrilha\b", "caminhada"),
    (r"\bpedalei\b|\bpedal\b|\bciclismo\b|\bbike\b|\bbicicleta\b|\bpedalada\b", "ciclismo"),
    (r"\bnadei\b|\bnatacao\b|\bnadar\b|\bpiscina\b", "natacao"),
    (r"\b(" + "|".join(k for k, (t, _) in SPECIFIC_MET.items() if t == "esportes") + r")\b", "esportes"),
    (r"\b(" + "|".join(k for k, (t, _) in SPECIFIC_MET.items() if t == "outra") + r")\b", "outra"),
]

INTENSITY_WORDS = [
    (r"\b(leve|levinho|tranquil[oa]|devagar|suave)\b", "leve"),
    (r"\b(moderad[oa]|medi[oa]|normal)\b", "moderada"),
    (r"\b(intens[oa]|forte|pesad[oa]|vigoros[oa]|puxad[oa]|rapid[oa]|tiro|tiros)\b", "vigorosa"),
]

QUESTION_HINTS = re.compile(
    r"\?|^(quanto|quantas|quantos|qual|quais|como|estou|to |tô |sera|compare|comparar|compara|mostre|mostra|"
    r"me (de|da|mostre)|resumo|relatorio|media|bati|atingi|cumpri)|\b(quanto|quantas|quantos|qual|quais)\b")


def to_number(tok: str) -> float | None:
    tok = tok.strip()
    if tok in WORD_NUMBERS:
        return float(WORD_NUMBERS[tok])
    if re.fullmatch(r"\d+/\d+", tok):
        a, b = tok.split("/")
        return float(a) / float(b) if float(b) else None
    try:
        return float(tok.replace(",", "."))
    except ValueError:
        return None


# ------------------------------------------------------------------ intenções simples
def _simple_intent(t: str) -> str | None:
    if re.fullmatch(r"(sim|s|ok|okay|confirm[ao]r?|confirmo|pode (registrar|salvar|confirmar)|registra(r)?|salva(r)?|"
                    r"isso|correto|certo|perfeito|beleza|manda ver)[.! ]*", t):
        return "confirmar"
    if re.fullmatch(r"(nao|n|cancela(r)?|descarta(r)?|esquece|deixa pra la|errado)[.! ]*", t):
        return "cancelar"
    if re.search(r"\b(desfazer|desfaca|apag(ar|ue|a) (o |a )?ultim|exclu(ir|a) (o |a )?ultim|remov(er|a) (o |a )?ultim)", t):
        return "desfazer"
    if re.fullmatch(r"(ajuda|help|menu|comandos|o que (voce|vc) (faz|sabe fazer)\??|como (funciona|usar)\??)[.!? ]*", t):
        return "ajuda"
    return None


# ------------------------------------------------------------------ peso
WEIGHT_RE = re.compile(
    r"(?:(?:pes(?:o|ei|ando)|balanca|acordei com|estou com|to com|amanheci com|marquei|marcou)\D{0,25}?"
    r"(\d{2,3}(?:[.,]\d{1,2})?)\s*(?:kg|quilos?|kilos?)?)"
    r"|(?:(\d{2,3}(?:[.,]\d{1,2})?)\s*(?:kg|quilos?|kilos?)\s*(?:na balanca|de peso|hoje cedo|em jejum))")


def parse_weight(t: str) -> float | None:
    m = WEIGHT_RE.search(t)
    if not m:
        return None
    if re.search(r"\b(kg|quilos?|kilos?) de \w", t) and not re.search(r"pes|balanca|acordei", t):
        return None  # "1 kg de arroz" não é peso corporal
    v = float((m.group(1) or m.group(2)).replace(",", "."))
    return v if 25 <= v <= 350 else None


# ------------------------------------------------------------------ atividades
def parse_duration_min(t: str) -> float | None:
    t = t.replace("meia hora", "30 minutos").replace("uma hora", "1 hora")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*h(?:oras?|rs?)?\s*(?:e\s*)?(\d{1,2})\s*(?:min(?:utos?)?|m)?\b", t)
    if m and not re.match(r"\s*km", t[m.end():]):
        return float(m[1].replace(",", ".")) * 60 + float(m[2])
    m = re.search(r"(\d{1,2}):(\d{2})\s*(?:h|hs|horas?)\b", t)
    if m:
        return int(m[1]) * 60 + int(m[2])
    total = 0.0
    found = False
    m = re.search(r"(\d+(?:[.,]\d+)?|" + "|".join(WORD_NUMBERS) + r")\s*(?:horas?|hrs?|h)\b", t)
    if m:
        total += to_number(m[1]) * 60
        found = True
    m2 = re.search(r"(\d+(?:[.,]\d+)?|" + "|".join(WORD_NUMBERS) + r")\s*(?:minutos?|mins?|min|m)\b(?!\s*/)", t)
    if m2 and not re.match(r"\s*(?:etros|ts?)\b", t[m2.end() - 1:]):
        total += to_number(m2[1])
        found = True
    return total if found and total > 0 else None


def parse_distance_km(t: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:km|quilometros?|kms|k)\b", t)
    if m:
        return float(m[1].replace(",", "."))
    m = re.search(r"(\d{3,5})\s*(?:metros|m)\b", t)
    if m:
        return float(m[1]) / 1000
    return None


def parse_pace_min_per_km(t: str) -> float | None:
    m = re.search(r"(?:ritmo|pace)\D{0,10}(\d{1,2})[:'´](\d{2})", t) or re.search(r"(\d{1,2})[:'](\d{2})\s*(?:/|por)\s*km", t)
    if m:
        return int(m[1]) + int(m[2]) / 60
    return None


def parse_intensity(t: str) -> str | None:
    for pat, val in INTENSITY_WORDS:
        if re.search(pat, t):
            return val
    return None


def parse_activities(t: str) -> list[LLMActivity]:
    hits: list[tuple[int, int, str, str]] = []
    for pat, kind in ACTIVITY_KEYWORDS:
        for m in re.finditer(pat, t):
            hits.append((m.start(), m.end(), kind, m.group(0)))
    if not hits:
        return []
    hits.sort(key=lambda h: (h[0], -h[1]))  # mesma posição: vence o termo mais longo
    # remove sobreposições (ex.: 'bike' dentro de 'bike ergometrica')
    dedup: list[tuple[int, int, str, str]] = []
    for h in hits:
        if dedup and h[0] < dedup[-1][1]:
            continue
        if dedup and dedup[-1][2] == h[2] and not re.search(r"\b(e|depois|tambem|mais)\b", t[dedup[-1][1]:h[0]]):
            continue  # mesma atividade mencionada duas vezes na mesma oração
        dedup.append(h)
    acts = []
    for i, (s, e, kind, word) in enumerate(dedup):
        seg_start = 0 if i == 0 else s
        seg_end = dedup[i + 1][0] if i + 1 < len(dedup) else len(t)
        seg = t[seg_start:seg_end]
        dur = parse_duration_min(seg)
        dist = parse_distance_km(seg) if kind in ("corrida", "caminhada", "ciclismo", "natacao") else None
        pace = parse_pace_min_per_km(seg)
        if dur is None and dist and pace:
            dur = round(dist * pace, 1)
        specific = word if word in SPECIFIC_MET else None
        if kind == "natacao" and dist and dist > 10:  # "nadei 1500 m" foi lido como km? (proteção)
            dist = None
        acts.append(LLMActivity(activity_type=kind, duration_min=dur, distance_km=dist,
                                intensity=parse_intensity(seg), description=specific))
    return acts


# ------------------------------------------------------------------ alimentos
ITEM_RE = re.compile(
    rf"^(?:(?P<qty>{NUM})\s*(?P<unit>{UNIT_RE})?\b\.?\s*(?:(?P<size1>pequen[oa]s?|medi[oa]s?|grandes?)\s+)?(?:de |do |da |dos |das )?)?"
    rf"(?P<food>.+?)"
    rf"(?:\s+(?P<size2>pequen[oa]s?|medi[oa]s?|grandes?))?"
    rf"(?:\s*\(?(?P<qty2>\d+(?:[.,]\d+)?)\s*(?P<unit2>{UNIT_RE})\)?)?$")


def _size(word: str | None) -> str | None:
    if not word:
        return None
    return SIZE_WORDS.get(re.sub(r"s$", "", word))


def parse_food_segment(seg: str) -> LLMFoodItem | None:
    seg = seg.strip(" .;:!-")
    seg = re.sub(r"^(?:e|mais|tambem|com|um pouco de|uns|umas|algumas|alguns)\s+", "", seg)
    if not seg:
        return None
    # "150g" -> "150 g"
    seg = re.sub(rf"(\d)({UNIT_RE})\b", r"\1 \2", seg)
    m = ITEM_RE.match(seg)
    if not m:
        return None
    food = m["food"].strip(" .,")
    food = re.sub(r"^(?:de|do|da|dos|das)\s+", "", food)
    if not food or re.fullmatch(r"[\d\s.,]+", food):
        return None
    qty_tok, unit_tok = m["qty"], m["unit"]
    if not qty_tok and m["qty2"]:
        qty_tok, unit_tok = m["qty2"], m["unit2"]
    qty = to_number(qty_tok) if qty_tok else None
    unit = canonical_unit(unit_tok) if unit_tok else None
    if qty is not None and unit is None:
        unit = "unidade"  # "dois pães", "2 ovos", "uma banana"
    size = _size(m["size1"] or m["size2"])
    return LLMFoodItem(food=food, quantity=qty, unit=unit, size=size)


def split_food_text(t: str) -> list[str]:
    t = re.sub(r"\b(\d+),(\d+)\b", r"\1.\2", t)  # protege decimais antes de separar por vírgula
    parts = re.split(r",|;|\+|\n|\s+e\s+|\s+com\s+|\s+mais\s+|\s+depois\s+", t)
    return [p.strip() for p in parts if p and p.strip()]


def strip_meal_words(t: str) -> tuple[str | None, str]:
    meal = None
    for pat, mt in MEAL_PATTERNS:
        if re.search(pat, t):
            meal = mt
            t = re.sub(r"(?:no |na |pro |para o |de |meu |minha |o |a )*(?:" + pat + r")(?: foi| foram| teve)?", " ", t, count=1)
            break
    return meal, re.sub(r"\s+", " ", t).strip()


FOOD_VERBS = re.compile(r"\b(comi|bebi|tomei|almocei|jantei|lanchei|ingeri|consumi|cafe da manha|almoco|jantar|lanche|ceia|refeicao)\b")


def parse_foods(t: str) -> list[LLMFoodItem]:
    t = FOOD_LEADS.sub("", t)
    items = []
    for seg in split_food_text(t):
        seg = FOOD_LEADS.sub("", seg)
        it = parse_food_segment(seg)
        if it:
            items.append(it)
    return items


# ------------------------------------------------------------------ consultas
def parse_query(t: str) -> tuple[str, int | None] | None:
    rules = [
        (r"proteina.*(suficiente|bastante|pouca|meta)|(suficiente|bati|atingi).*proteina", "proteina_suficiente"),
        (r"(quanto|o que).*(ainda )?(posso|consigo) comer|quanto (falta|resta|sobra)|restante|ainda posso", "restante_hoje"),
        (r"compar", "comparar_semanas"),
        (r"quais dias|que dias|em quais|dias (acima|que passei|em que passei)|passei da meta|acima da meta", "dias_acima_meta"),
        (r"ritmo|perdendo peso|ganhando peso|emagrecendo|tendencia|evolucao do peso|estou engordando", "ritmo_peso"),
        (r"peso atual|quanto (estou )?pesando|meu peso|ultimo peso", "peso_atual"),
        (r"proteina", "proteina_periodo"),
        (r"\bmedia\b", "media_periodo"),
        (r"relatorio|resumo|balanco geral|como (foi|estou|esta)( a| na| minha)? (semana|mes)", "relatorio"),
        (r"(deficit|superavit|saldo).*(acumulad|seman|ultim|mes|dias)|(acumulad).*(deficit|saldo)", "saldo_periodo"),
        (r"(atividades|treinos|exercicios|treinei|quanto (eu )?(corri|caminhei|pedalei))", "atividades_periodo"),
        (r"(deficit|superavit|saldo|como estou|como to)", "status_hoje"),
        (r"(quantas|quanto).*(caloria|kcal|comi|consumi)|calorias (de )?(ontem|hoje)", "consumo_dia"),
    ]
    for pat, kind in rules:
        if re.search(pat, t):
            m = re.search(r"ultim[oa]s? (\d+) dias", t)
            return kind, int(m[1]) if m else None
    return None


# ------------------------------------------------------------------ ponto de entrada
def parse(message: str) -> LLMParse:
    raw = message.strip()
    t = light_norm(raw)
    simple = _simple_intent(t)
    if simple:
        return LLMParse(intent=simple)

    is_question = bool(QUESTION_HINTS.search(t))
    if is_question:
        q = parse_query(t)
        if q:
            date_ref, _ = extract_date_ref(t)
            return LLMParse(intent="consulta", query=q[0], period_days=q[1], date_ref=date_ref)

    date_ref, rest = extract_date_ref(t)

    w = parse_weight(rest)
    if w is not None and not FOOD_VERBS.search(rest):
        return LLMParse(intent="registrar_peso", weight_kg=w, date_ref=date_ref)

    acts = parse_activities(rest)
    food_part = rest
    if acts:
        # remove as orações de atividade antes de procurar alimentos
        clauses = re.split(r"[.;]|\s+e depois\s+|\s+depois\s+", rest)
        food_part = " , ".join(c for c in clauses if FOOD_VERBS.search(c))
    meal, food_text = strip_meal_words(food_part)
    foods: list[LLMFoodItem] = []
    if food_text and (FOOD_VERBS.search(food_part) or (not acts and re.search(NUM, food_text))):
        foods = parse_foods(food_text)

    if foods and acts:
        return LLMParse(intent="registrar_alimentos", foods=foods, activities=acts, meal_type=meal, date_ref=date_ref)
    if acts:
        return LLMParse(intent="registrar_atividades", activities=acts, date_ref=date_ref)
    if foods:
        return LLMParse(intent="registrar_alimentos", foods=foods, meal_type=meal, date_ref=date_ref)
    if is_question:
        return LLMParse(intent="consulta", query="status_hoje", date_ref=date_ref)
    return LLMParse(intent="desconhecido")
