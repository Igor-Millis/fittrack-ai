"""Orquestrador do assistente conversacional.

Fluxo: mensagem -> interpretação (LLM opcional ou regras) -> JSON validado (LLMParse)
-> busca na base nutricional / METs -> motor de cálculo -> RASCUNHO exibido ao usuário
-> confirmação explícita -> serviços de registro (records) -> resposta com o que foi salvo.

Nada é gravado sem confirmação. Consultas são respondidas por `queries` (dados do banco).
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from backend.ai import ollama_client, queries, rule_parser
from backend.ai.queries import fmt
from backend.ai.dates import resolve_date_ref
from backend.models.schemas import (ACTIVITY_LABELS, MEAL_LABELS, ActivityIn, LLMParse, MealIn, MealItemIn,
                                    WeightIn)
from backend.nutrition.calculator import compute_item
from backend.nutrition.foods import match_food
from backend.nutrition.units import ConversionError
from backend.services import records, settings_service
from backend.textutil import tokens

HELP = """Posso registrar e consultar seus dados. Exemplos:

**Alimentação** — "Comi 150 g de arroz, 100 g de feijão e 180 g de peito de frango"; "No café da manhã comi dois pães franceses com 30 g de queijo"
**Exercícios** — "Fiz musculação por 1h20"; "Corri 5 km em 30 minutos"; "Pedalei 25 min moderado"
**Peso** — "Hoje acordei com 71,2 kg"
**Perguntas** — "Estou em déficit hoje?", "Quanto ainda posso comer?", "Quanto consumi de proteína nesta semana?",
"Qual meu déficit acumulado nos últimos 7 dias?", "Compare esta semana com a anterior", "Quais dias fiquei acima da meta?",
"Estou perdendo peso no ritmo esperado?", "Relatório do mês"
**Comandos** — "sim" confirma o rascunho, "cancelar" descarta, "apagar o último registro" remove o último lançamento (com confirmação).

Antes de salvar eu sempre mostro um rascunho com os valores calculados para você conferir."""


@dataclass
class DraftFood:
    raw_name: str
    quantity: float | None
    unit: str | None
    size: str | None = None
    food_id: int | None = None
    food_name: str | None = None
    candidates: list[tuple[int, str]] = field(default_factory=list)
    ambiguous: bool = False
    grams_override: float | None = None
    grams: float | None = None
    basis: str | None = None
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    issue: str | None = None  # o que falta para poder salvar


@dataclass
class DraftActivity:
    activity_type: str
    duration_min: float | None
    distance_km: float | None = None
    intensity: str | None = None
    specific: str | None = None
    met: float | None = None
    met_source: str | None = None
    kcal_gross: float | None = None
    kcal_net: float | None = None
    issue: str | None = None


@dataclass
class Draft:
    day: date
    source_text: str
    meal_type: str = "outro"
    foods: list[DraftFood] = field(default_factory=list)
    activities: list[DraftActivity] = field(default_factory=list)
    weight_kg: float | None = None
    weight_exists: float | None = None
    interpreter: str = "regras"
    pending_delete: tuple[str, int] | None = None

    @property
    def ready(self) -> bool:
        return all(f.issue is None for f in self.foods) and all(a.issue is None for a in self.activities)

    @property
    def empty(self) -> bool:
        return not self.foods and not self.activities and self.weight_kg is None and not self.pending_delete


@dataclass
class Reply:
    text: str
    draft: Draft | None = None
    saved: bool = False


def guess_meal_type(now: datetime) -> str:
    h = now.hour + now.minute / 60
    if h < 10.5:
        return "cafe_da_manha"
    if h < 15:
        return "almoco"
    if h < 18.5:
        return "lanche_tarde"
    if h < 22.5:
        return "jantar"
    return "ceia"


class Assistant:
    def __init__(self, conn: sqlite3.Connection, today: date | None = None, now: datetime | None = None):
        self.conn = conn
        self.today = today or date.today()
        self.now = now or datetime.now()

    # ---------------------------------------------------------------- interpretação
    def interpret(self, message: str) -> tuple[LLMParse, str]:
        rules = rule_parser.parse(message)
        if not settings_service.get_bool(self.conn, "ai_enabled"):
            return rules, "regras"
        if rules.intent in ("confirmar", "cancelar", "ajuda", "desfazer"):
            return rules, "regras"  # comandos simples não precisam de LLM
        llm = ollama_client.parse_with_llm(
            message, settings_service.get(self.conn, "ollama_url"), settings_service.get(self.conn, "ollama_model"),
            settings_service.get_float(self.conn, "ollama_timeout"))
        if llm is None or llm.intent == "desconhecido":
            return rules, "regras (IA indisponível)" if llm is None else "regras"
        return merge_parses(llm, rules), "IA local (Ollama) + validação"

    # ---------------------------------------------------------------- entrada principal
    def handle(self, message: str, pending: Draft | None = None) -> Reply:
        if not message or not message.strip():
            return Reply("Mensagem vazia.", pending)
        if len(message) > 2000:
            return Reply("Mensagem muito longa (máx. 2000 caracteres). Divida em partes.", pending)
        if records.get_profile(self.conn) is None:
            return Reply("Antes de começar, configure seu perfil na página **Configurações**.", None)

        parsed, interpreter = self.interpret(message)

        if parsed.intent == "confirmar":
            if pending is None or pending.empty:
                return Reply("Não há nada pendente para confirmar.")
            return self.confirm(pending)
        if parsed.intent == "cancelar":
            return Reply("Rascunho descartado. Nada foi registrado." if pending else "Nada pendente para cancelar.", None)
        if parsed.intent == "ajuda":
            return Reply(HELP, pending)
        if parsed.intent == "desfazer":
            last = records.last_record(self.conn)
            if not last:
                return Reply("Não há registros para apagar.", pending)
            kind, rid, created = last
            d = Draft(day=self.today, source_text=message, pending_delete=(kind, rid))
            return Reply(f"O último registro é **{kind} #{rid}** (criado em {created}). {describe_record(self.conn, kind, rid)}\n\n"
                         f"Confirma a exclusão? Responda **sim** ou **cancelar**.", d)
        if parsed.intent == "consulta":
            try:
                txt = queries.answer(self.conn, parsed.query or "status_hoje", message, self.today,
                                     parsed.period_days, parsed.date_ref)
            except ValueError as e:
                txt = f"Não consegui interpretar a data/período: {e}"
            return Reply(txt, pending)
        if parsed.intent in ("registrar_alimentos", "registrar_atividades", "registrar_peso"):
            try:
                day = resolve_date_ref(parsed.date_ref, self.today)
            except ValueError as e:
                return Reply(str(e), pending)
            if day > self.today:
                return Reply("Não é possível registrar em datas futuras.", pending)
            draft = self.build_draft(parsed, message, day, interpreter)
            if draft.empty:
                return Reply("Não identifiquei alimentos, atividades ou peso na mensagem. Digite **ajuda** para exemplos.", pending)
            return Reply(render_draft(draft), draft)
        return Reply("Não entendi. Você pode registrar refeições, treinos e peso, ou fazer perguntas. "
                     "Digite **ajuda** para ver exemplos.", pending)

    # ---------------------------------------------------------------- rascunho
    def build_draft(self, p: LLMParse, message: str, day: date, interpreter: str) -> Draft:
        meal = p.meal_type or (guess_meal_type(self.now) if day == self.today else "outro")
        d = Draft(day=day, source_text=message, meal_type=meal, interpreter=interpreter)
        for f in p.foods:
            m = match_food(self.conn, f.food)
            df = DraftFood(raw_name=f.food, quantity=f.quantity, unit=f.unit, size=f.size,
                           candidates=[(c.food_id, c.name) for c in m.candidates], ambiguous=m.ambiguous)
            # escolha automática só quando a correspondência é confiável (apelido ou nome claro);
            # em ambiguidade real o usuário escolhe entre as opções apresentadas
            if m.best and (m.best.via_alias or not m.ambiguous):
                df.food_id, df.food_name = m.best.food_id, m.best.name
            d.foods.append(df)
        for a in p.activities:
            d.activities.append(DraftActivity(a.activity_type, a.duration_min, a.distance_km, a.intensity, a.description))
        if p.weight_kg is not None:
            d.weight_kg = p.weight_kg
        self.recompute(d)
        return d

    def recompute(self, d: Draft) -> Draft:
        """Recalcula nutrientes/gasto após qualquer edição do rascunho."""
        for f in d.foods:
            f.issue = None
            f.grams = f.basis = f.kcal = f.protein_g = f.carbs_g = f.fat_g = f.fiber_g = None
            if f.food_id is None and f.candidates:
                opts = "; ".join(name for _, name in f.candidates[:4])
                f.issue = f"'{f.raw_name}' tem várias correspondências — escolha uma no cartão: {opts}."
                continue
            if f.food_id is None:
                f.issue = (f"'{f.raw_name}' não encontrado na base. Cadastre-o na página Alimentação "
                           f"(valores do rótulo) ou escolha outro nome.")
                continue
            if f.quantity is None and f.grams_override is None:
                f.issue = f"Qual a quantidade de '{f.food_name}'? (ex.: 120 g, 1 unidade, 2 colheres de sopa)"
                continue
            try:
                c = compute_item(self.conn, f.food_id, f.quantity or 1, f.unit or "g", f.size, f.grams_override)
            except ConversionError as e:
                f.issue = str(e)
                continue
            n = c.nutrients.rounded()
            f.food_name, f.grams, f.basis = c.food_name, c.grams, c.basis
            f.kcal, f.protein_g, f.carbs_g, f.fat_g, f.fiber_g = n.kcal, n.protein_g, n.carbs_g, n.fat_g, n.fiber_g
        for a in d.activities:
            a.issue = None
            a.met = a.kcal_gross = a.kcal_net = None
            if a.duration_min is None:
                what = "distância e duração/ritmo" if a.distance_km is None else "duração (ou ritmo)"
                a.issue = f"Informe a {what} de {ACTIVITY_LABELS[a.activity_type].lower()} para estimar o gasto."
                continue
            try:
                ai = ActivityIn(date=d.day, activity_type=a.activity_type, duration_min=a.duration_min,
                                distance_km=a.distance_km, intensity=a.intensity, description=a.specific)
                pv = records.preview_activity(self.conn, ai, a.specific)
            except ValueError as e:
                a.issue = str(e)
                continue
            a.met, a.met_source, a.kcal_gross, a.kcal_net = pv["met"], pv["met_source"], pv["kcal_gross"], pv["kcal_net"]
        if d.weight_kg is not None:
            existing = records.get_weight(self.conn, d.day)
            d.weight_exists = existing["weight_kg"] if existing else None
        return d

    # ---------------------------------------------------------------- confirmação
    def confirm(self, d: Draft, allow_duplicate: bool = False) -> Reply:
        if d.pending_delete:
            kind, rid = d.pending_delete
            try:
                {"refeicao": records.delete_meal, "atividade": records.delete_activity,
                 "peso": records.delete_weight}[kind](self.conn, rid, origin="chat")
            except records.NotFoundError as e:
                return Reply(str(e), None)
            return Reply(f"Registro **{kind} #{rid}** excluído (ação registrada no histórico de alterações).", None, True)
        self.recompute(d)
        if not d.ready:
            issues = [f.issue for f in d.foods if f.issue] + [a.issue for a in d.activities if a.issue]
            return Reply("Ainda falta informação antes de salvar:\n- " + "\n- ".join(issues), d)
        saved: list[str] = []
        try:
            if d.foods:
                meal = MealIn(date=d.day, meal_type=d.meal_type, source_text=d.source_text,
                              time=self.now.strftime("%H:%M") if d.day == self.today else None,
                              items=[MealItemIn(food_id=f.food_id, quantity=f.quantity or 1, unit=f.unit or "g",
                                                size=f.size, grams_override=f.grams_override) for f in d.foods])
                mid = records.save_meal(self.conn, meal, allow_duplicate=allow_duplicate, origin="chat")
                tot = sum(f.kcal or 0 for f in d.foods)
                saved.append(f"refeição #{mid} ({MEAL_LABELS[d.meal_type]}, {len(d.foods)} item(ns), {fmt(tot)} kcal)")
                d.foods = []  # evita salvar de novo se outra parte falhar
            for a in list(d.activities):
                aid = records.save_activity(
                    self.conn, ActivityIn(date=d.day, activity_type=a.activity_type, duration_min=a.duration_min,
                                          distance_km=a.distance_km, intensity=a.intensity, description=a.specific,
                                          source_text=d.source_text),
                    allow_duplicate=allow_duplicate, specific=a.specific, origin="chat")
                saved.append(f"atividade #{aid} ({ACTIVITY_LABELS[a.activity_type]}, {fmt(a.kcal_net)} kcal líquidas)")
                d.activities.remove(a)
            if d.weight_kg is not None:
                wid = records.save_weight(self.conn, WeightIn(date=d.day, weight_kg=d.weight_kg),
                                          replace=d.weight_exists is not None, origin="chat")
                saved.append(f"peso #{wid} ({fmt(d.weight_kg, 1)} kg)")
                d.weight_kg = None
        except records.DuplicateError as e:
            prefix = ("Registrado: " + "; ".join(saved) + ".\n\n") if saved else ""
            return Reply(prefix + f"⚠️ {e} Para registrar mesmo assim, use o botão **Registrar mesmo assim**.", d, bool(saved))
        when = "hoje" if d.day == self.today else f"em {d.day:%d/%m/%Y}"
        return Reply(f"✅ Registrado {when}: " + "; ".join(saved) + ". Seus totais foram atualizados.", None, True)


def merge_parses(llm: LLMParse, rules: LLMParse) -> LLMParse:
    """Completa campos nulos do LLM com o que o interpretador de regras extraiu (mesmo texto)."""
    foods = []
    for f in llm.foods:
        match = next((r for r in rules.foods if set(tokens(r.food)) & set(tokens(f.food))), None)
        if match and f.quantity is None and match.quantity is not None:
            f = f.model_copy(update={"quantity": match.quantity, "unit": match.unit, "size": f.size or match.size})
        foods.append(f)
    acts = []
    for a in llm.activities:
        match = next((r for r in rules.activities if r.activity_type == a.activity_type), None)
        if match:
            upd = {k: getattr(match, k) for k in ("duration_min", "distance_km", "intensity")
                   if getattr(a, k) is None and getattr(match, k) is not None}
            a = a.model_copy(update=upd) if upd else a
        acts.append(a)
    if not acts and rules.activities and llm.intent in ("registrar_atividades", "registrar_alimentos"):
        acts = rules.activities
    return llm.model_copy(update={"foods": foods, "activities": acts,
                                  "weight_kg": llm.weight_kg if llm.weight_kg is not None else rules.weight_kg,
                                  "date_ref": llm.date_ref or rules.date_ref,
                                  "meal_type": llm.meal_type or rules.meal_type})


def describe_record(conn: sqlite3.Connection, kind: str, rid: int) -> str:
    if kind == "refeicao":
        m = records.get_meal(conn, rid)
        if m:
            return f"{MEAL_LABELS.get(m['meal_type'])} de {m['date']}: " + ", ".join(
                f"{i['food_name']} ({i['grams']:.0f} g)" for i in m["items"])
    if kind == "atividade":
        a = conn.execute("SELECT * FROM activities WHERE id=?", (rid,)).fetchone()
        if a:
            return f"{ACTIVITY_LABELS.get(a['activity_type'])} em {a['date']}, {a['duration_min']:.0f} min."
    if kind == "peso":
        w = conn.execute("SELECT * FROM weights WHERE id=?", (rid,)).fetchone()
        if w:
            return f"Peso de {w['weight_kg']:.1f} kg em {w['date']}."
    return ""


def render_draft(d: Draft) -> str:
    lines = [f"**Rascunho para {d.day:%d/%m/%Y}** — interpretado por: {d.interpreter}", ""]
    if d.foods:
        lines.append(f"🍽️ **{MEAL_LABELS[d.meal_type]}** — identifiquei {len(d.foods)} alimento(s):")
        for f in d.foods:
            if f.issue:
                lines.append(f"- ❓ **{f.raw_name}** → {f.food_name or 'não encontrado'}: {f.issue}")
                continue
            amb = " ⚠️ *vários alimentos parecidos — confira a escolha*" if f.ambiguous else ""
            lines.append(f"- **{f.food_name}** — {fmt(f.grams)} g ({f.basis}): {fmt(f.kcal)} kcal · P {fmt(f.protein_g, 1)} g · "
                         f"C {fmt(f.carbs_g, 1)} g · G {fmt(f.fat_g, 1)} g{amb}")
        ok = [f for f in d.foods if not f.issue]
        if ok:
            lines.append("")
            lines.append(f"**Total:** {fmt(sum(f.kcal for f in ok))} kcal · P {fmt(sum(f.protein_g for f in ok), 1)} g · "
                         f"C {fmt(sum(f.carbs_g for f in ok), 1)} g · G {fmt(sum(f.fat_g for f in ok), 1)} g")
    if d.activities:
        lines.append("🏃 **Atividades:**")
        for a in d.activities:
            label = ACTIVITY_LABELS[a.activity_type] + (f" ({a.specific})" if a.specific else "")
            if a.issue:
                lines.append(f"- ❓ **{label}**: {a.issue}")
                continue
            dist = f", {fmt(a.distance_km, 1)} km" if a.distance_km else ""
            lines.append(f"- **{label}** — {fmt(a.duration_min)} min{dist}: MET {fmt(a.met, 1)} → {fmt(a.kcal_gross)} kcal brutas, "
                         f"**{fmt(a.kcal_net)} kcal líquidas** somadas ao gasto")
    if d.weight_kg is not None:
        extra = f" (substituirá {fmt(d.weight_exists, 1)} kg já registrado nesse dia)" if d.weight_exists else ""
        lines.append(f"⚖️ **Peso:** {fmt(d.weight_kg, 1)} kg{extra}")
    lines.append("")
    lines.append("Confirme com **sim** (ou o botão), corrija no cartão abaixo, ou **cancelar**." if d.ready
                 else "Complete as informações marcadas com ❓ no cartão abaixo (ou responda com mais detalhes).")
    return "\n".join(lines)


def draft_to_dict(d: Draft) -> dict:
    return asdict(d)
