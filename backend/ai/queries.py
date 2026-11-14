"""Respostas a consultas sobre o histórico. Todo número vem do banco via analytics;
os textos são montados por templates determinísticos (o LLM não redige números)."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd

from backend.ai.dates import Period, parse_period, resolve_date_ref
from backend.analytics.daily import daily_summary, period_stats, weight_trend
from backend.models.schemas import ACTIVITY_LABELS
from backend.services import records, settings_service
from backend.textutil import light_norm


def fmt(x: float | None, nd: int = 0, unit: str = "") -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    s = f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s}{(' ' + unit) if unit else ''}"


def balance_phrase(balance: float | None, band: float) -> str:
    if balance is None or pd.isna(balance):
        return "sem alimentação registrada"
    if balance > band:
        return f"**déficit** estimado de {fmt(balance)} kcal"
    if balance < -band:
        return f"**superávit** estimado de {fmt(-balance)} kcal"
    return f"**manutenção** estimada (saldo de {fmt(balance)} kcal)"


def with_prep(label: str) -> str:
    """'esta semana' -> 'nesta semana', 'últimos 7 dias' -> 'nos últimos 7 dias'..."""
    table = {"esta semana": "nesta semana", "semana passada": "na semana passada", "este mês": "neste mês",
             "mês passado": "no mês passado", "hoje": "hoje", "ontem": "ontem", "anteontem": "anteontem"}
    if label in table:
        return table[label]
    return f"nos {label}" if label.startswith("últimos") else f"em {label}"


def _day_row(conn, day: date) -> pd.Series:
    return daily_summary(conn, day, day).iloc[0]


def answer(conn: sqlite3.Connection, kind: str, message: str, today: date,
           period_days: int | None = None, date_ref: str | None = None) -> str:
    t = light_norm(message)
    band = settings_service.get_float(conn, "maintenance_band_kcal")
    period = parse_period(t, today)
    if period_days and not period.explicit:  # período vindo do LLM só quando o texto não define um
        period = Period(today - timedelta(days=period_days - 1), today, f"últimos {period_days} dias")
    day = resolve_date_ref(date_ref, today) if date_ref else today

    if kind == "status_hoje":
        r = _day_row(conn, day)
        label = "Hoje" if day == today else f"Em {day:%d/%m/%Y}"
        if not r["has_food"]:
            return (f"{label} ainda não há alimentação registrada, então não dá para calcular o saldo. "
                    f"Gasto estimado até agora: {fmt(r['tdee'])} kcal.")
        return (f"{label}: consumo de {fmt(r['kcal_in'])} kcal e gasto estimado de {fmt(r['tdee'])} kcal "
                f"(base {fmt(r['baseline'])} + exercícios {fmt(r['exercise_counted'])}). "
                f"Resultado: {balance_phrase(r['balance'], band)}.")

    if kind == "restante_hoje":
        r = _day_row(conn, today)
        consumed = r["kcal_in"] if r["has_food"] else 0.0
        goal = r["goal_kcal"]
        lines = []
        if not pd.isna(goal):
            rest = goal - consumed
            lines.append(f"Pela sua meta de {fmt(goal)} kcal, " + (
                f"ainda restam **{fmt(rest)} kcal** hoje." if rest >= 0 else f"você já passou **{fmt(-rest)} kcal** da meta."))
            rp = r["goal_protein"] - (r["protein_g"] if r["has_food"] else 0)
            lines.append(f"Proteína: faltam {fmt(max(rp, 0))} g para a meta de {fmt(r['goal_protein'])} g."
                         if rp > 0 else f"Meta de proteína ({fmt(r['goal_protein'])} g) já atingida.")
        lines.append(f"Para ficar em manutenção estimada (gasto de {fmt(r['tdee'])} kcal), o limite seria "
                     f"{fmt(r['tdee'] - consumed)} kcal a mais.")
        return " ".join(lines)

    if kind == "consumo_dia":
        r = _day_row(conn, day)
        label = "hoje" if day == today else ("ontem" if day == today - timedelta(days=1) else f"em {day:%d/%m/%Y}")
        if not r["has_food"]:
            return f"Não há alimentação registrada {label}."
        return (f"Consumo {label}: **{fmt(r['kcal_in'])} kcal** — proteína {fmt(r['protein_g'], 1)} g, "
                f"carboidratos {fmt(r['carbs_g'], 1)} g, gorduras {fmt(r['fat_g'], 1)} g, "
                f"fibras {fmt(r['fiber_g'], 1)} g, em {int(r['n_meals'])} refeição(ões).")

    s = period_stats(conn, period.start, period.end)
    span = f"{with_prep(period.label)} ({period.start:%d/%m} a {period.end:%d/%m})"
    coverage = f"{s.days_logged} de {s.days} dias com alimentação registrada"

    if kind == "proteina_periodo":
        if not s.days_logged:
            return f"Sem alimentação registrada {span}."
        return (f"Proteína {span}: total de **{fmt(s.total_protein)} g**, média de {fmt(s.avg_protein)} g/dia "
                f"({coverage}). Meta média: {fmt(s.goal_protein_avg)} g/dia; meta atingida em "
                f"{s.days_protein_goal_met} dia(s).")

    if kind == "proteina_suficiente":
        if not s.days_logged:
            return f"Sem alimentação registrada {span} para avaliar."
        prof = records.get_profile(conn)
        w = records.body_weight_for(conn, today)
        per_kg = s.avg_protein / w if w else None
        verdict = ("acima" if s.avg_protein >= (s.goal_protein_avg or 0) else "abaixo")
        return (f"{span[0].upper() + span[1:]}, sua média foi de **{fmt(s.avg_protein)} g/dia** ({fmt(per_kg, 2)} g/kg), {verdict} da sua "
                f"meta de {fmt(s.goal_protein_avg)} g/dia; meta atingida em {s.days_protein_goal_met} de "
                f"{s.days_logged} dias registrados. Referência geral para quem treina: 1,4–2,0 g/kg/dia (ISSN). "
                f"Isso não é recomendação individual — ajuste com um nutricionista"
                + (" (objetivo: " + prof["goal"].replace("_", " ") + ")." if prof else "."))

    if kind == "saldo_periodo":
        if not s.days_logged:
            return f"Sem alimentação registrada {span}."
        kpk = settings_service.get_float(conn, "kcal_per_kg")
        word = "déficit" if s.total_balance > 0 else "superávit"
        return (f"Saldo acumulado {span}: **{word} de {fmt(abs(s.total_balance))} kcal** "
                f"(média {fmt(s.avg_balance)} kcal/dia; {coverage}). "
                f"Equivalência teórica: ~{fmt(abs(s.total_balance) / kpk, 2)} kg (a {fmt(kpk)} kcal/kg) — é só uma "
                f"aproximação; a variação real do peso pode diferir bastante.")

    if kind == "media_periodo":
        if not s.days_logged:
            return f"Sem alimentação registrada {span}."
        return (f"Médias {span} ({coverage}): consumo **{fmt(s.avg_kcal_in)} kcal/dia**, gasto estimado "
                f"{fmt(s.avg_tdee)} kcal/dia, saldo médio {fmt(s.avg_balance)} kcal/dia; proteína {fmt(s.avg_protein)} g, "
                f"carboidratos {fmt(s.avg_carbs)} g, gorduras {fmt(s.avg_fat)} g.")

    if kind == "comparar_semanas":
        this_start = today - timedelta(days=today.weekday())
        prev_start = this_start - timedelta(days=7)
        a = period_stats(conn, this_start, today)
        b = period_stats(conn, prev_start, this_start - timedelta(days=1))

        def row(label, x, y, nd=0, unit=""):
            diff = None if x is None or y is None else x - y
            sign = "" if diff is None else ("+" if diff >= 0 else "")
            return f"| {label} | {fmt(x, nd, unit)} | {fmt(y, nd, unit)} | {sign}{fmt(diff, nd)} |"

        return "\n".join([
            f"Comparação: esta semana ({this_start:%d/%m}–{today:%d/%m}) × semana anterior "
            f"({prev_start:%d/%m}–{(this_start - timedelta(days=1)):%d/%m}).", "",
            "| Indicador | Esta semana | Anterior | Diferença |", "|---|---|---|---|",
            row("Dias registrados", a.days_logged, b.days_logged),
            row("Consumo médio (kcal)", a.avg_kcal_in, b.avg_kcal_in),
            row("Gasto médio (kcal)", a.avg_tdee, b.avg_tdee),
            row("Saldo médio (kcal)", a.avg_balance, b.avg_balance),
            row("Proteína média (g)", a.avg_protein, b.avg_protein),
            row("Atividades", a.activities, b.activities),
            row("Minutos de exercício", a.exercise_minutes, b.exercise_minutes),
            row("Peso médio 7d (kg)", a.weight_end, b.weight_end, 1),
        ])

    if kind == "dias_acima_meta":
        df = daily_summary(conn, period.start, period.end)
        above = df[df["above_goal"]]
        if not s.days_logged:
            return f"Sem alimentação registrada {span}."
        if above.empty:
            return f"{span[0].upper() + span[1:]} você não passou da meta calórica em nenhum dia registrado ({coverage})."
        lst = ", ".join(f"{r.date:%d/%m} ({fmt(r.kcal_in)} kcal, +{fmt(r.kcal_in - r.goal_kcal)})" for r in above.itertuples())
        return f"Dias acima da meta {span}: {lst}. Total: {len(above)} de {s.days_logged} dias registrados."

    if kind == "ritmo_peso":
        wt = weight_trend(conn, today, days=max(period.days, 28))
        prof = records.get_profile(conn)
        parts = [f"Análise dos últimos {max(period.days, 28)} dias: {wt.n_weighins} pesagem(ns) em {wt.span_days} dias."]
        if wt.slope_kg_week is not None:
            parts.append(f"Tendência observada: **{fmt(wt.slope_kg_week, 2)} kg/semana** (regressão linear das pesagens).")
        if wt.expected_kg_week is not None:
            parts.append(f"Esperado pelo saldo calculado: {fmt(wt.expected_kg_week, 2)} kg/semana.")
        if prof and prof.get("weekly_rate_kg") is not None:
            parts.append(f"Sua meta de ritmo: {fmt(prof['weekly_rate_kg'], 2)} kg/semana.")
        parts.append(wt.message)
        parts.append("Oscilações diárias (água, sal, glicogênio, intestino) não indicam ganho/perda de gordura; "
                     "use a média de 7 dias.")
        return " ".join(parts)

    if kind == "peso_atual":
        last = conn.execute("SELECT date, weight_kg FROM weights ORDER BY date DESC LIMIT 1").fetchone()
        if not last:
            return "Ainda não há peso registrado. Ex.: 'Hoje acordei com 71,2 kg'."
        ws = daily_summary(conn, today - timedelta(days=6), today)["weight"].dropna()
        from backend.analytics.daily import weight_series
        wser = weight_series(conn, today - timedelta(days=60), today)
        ma = wser["ma7"].iloc[-1] if not wser.empty else None
        return (f"Último peso: **{fmt(last['weight_kg'], 1)} kg** em {date.fromisoformat(last['date']):%d/%m/%Y}. "
                f"Média móvel de 7 dias: {fmt(ma, 1)} kg ({len(ws)} pesagem(ns) nos últimos 7 dias).")

    if kind == "atividades_periodo":
        acts = records.list_activities(conn, period.start, period.end)
        if not acts:
            return f"Nenhuma atividade registrada {span}."
        by: dict[str, list] = {}
        for a in acts:
            by.setdefault(a["activity_type"], []).append(a)
        lines = [f"Atividades {span}: {len(acts)} sessão(ões), {fmt(sum(a['duration_min'] for a in acts))} min, "
                 f"gasto líquido estimado {fmt(sum(a['kcal_net'] for a in acts))} kcal."]
        for k, lst in by.items():
            km = sum(a["distance_km"] or 0 for a in lst)
            lines.append(f"- {ACTIVITY_LABELS.get(k, k)}: {len(lst)}x, {fmt(sum(a['duration_min'] for a in lst))} min"
                         + (f", {fmt(km, 1)} km" if km else ""))
        return "\n".join(lines)

    if kind == "relatorio":
        return period_report(conn, period.start, period.end, period.label)

    return "Não entendi a pergunta. Digite **ajuda** para ver exemplos."


def period_report(conn: sqlite3.Connection, start: date, end: date, label: str | None = None) -> str:
    s = period_stats(conn, start, end)
    label = label or f"{start:%d/%m} a {end:%d/%m}"
    band = settings_service.get_float(conn, "maintenance_band_kcal")
    if not s.days_logged and not s.activities and s.weight_start is None:
        return f"Não há registros em {label}."
    parts = [f"**Relatório — {label} ({start:%d/%m/%Y} a {end:%d/%m/%Y})**"]
    if s.days_logged:
        parts.append(
            f"Nos {s.days_logged} dia(s) com alimentação registrada (de {s.days}), sua ingestão média foi de "
            f"**{fmt(s.avg_kcal_in)} kcal**, com {fmt(s.avg_protein)} g de proteína, {fmt(s.avg_carbs)} g de "
            f"carboidratos e {fmt(s.avg_fat)} g de gorduras por dia. O gasto médio estimado foi de "
            f"{fmt(s.avg_tdee)} kcal/dia, resultando em {balance_phrase(s.avg_balance, band)} por dia em média "
            f"e saldo acumulado de {fmt(s.total_balance)} kcal.")
        parts.append(
            f"Dias em déficit: {s.days_deficit}; em superávit: {s.days_surplus}; manutenção: {s.days_maintenance}. "
            f"Acima da meta calórica: {s.days_above_goal}. Meta de proteína atingida: {s.days_protein_goal_met}.")
    else:
        parts.append("Nenhuma alimentação registrada no período.")
    parts.append(f"Atividades: {s.activities} sessão(ões), {fmt(s.exercise_minutes)} min, gasto líquido estimado "
                 f"{fmt(s.exercise_net_total)} kcal.")
    if s.weight_start is not None:
        parts.append(f"Peso (média móvel 7 dias): de {fmt(s.weight_start, 1)} para {fmt(s.weight_end, 1)} kg "
                     f"(variação de {fmt(s.weight_change, 2)} kg).")
    parts.append("\n_Valores estimados; não substituem avaliação profissional._")
    return "\n\n".join(parts)
