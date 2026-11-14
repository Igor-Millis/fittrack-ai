from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.ui import (COLORS, card, cards_row, disclaimer, get_conn, header, macro_bar,
                               period_filter, require_profile, ring_svg, status_pill)
from backend.ai.queries import fmt
from backend.analytics.daily import daily_summary, weight_series
from backend.models.schemas import ACTIVITY_LABELS, MEAL_LABELS
from backend.services import records

conn = get_conn()
prof = require_profile(conn)
today = date.today()
DOW = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
greet = f"Olá, {prof['name']}" if prof.get("name") else "Seu dia"
header(greet, f"{DOW[today.weekday()].capitalize()}, {today:%d/%m/%Y}", "Dashboard")

t = daily_summary(conn, today, today).iloc[0]
goal_kcal = t["goal_kcal"]
kcal_in = t["kcal_in"] if t["has_food"] else 0.0

# ------------------------------------------------------------------ hero do dia
frac = kcal_in / goal_kcal if goal_kcal and not pd.isna(goal_kcal) else float("nan")
remaining = (goal_kcal - kcal_in) if not pd.isna(goal_kcal) else None
ring = ring_svg(frac, fmt(kcal_in), f"de {fmt(goal_kcal)} kcal" if not pd.isna(goal_kcal) else "kcal", COLORS["consumo"])
last_w = conn.execute("SELECT date, weight_kg FROM weights ORDER BY date DESC LIMIT 1").fetchone()
ws = weight_series(conn, today - timedelta(days=60), today)
ma7 = ws["ma7"].iloc[-1] if not ws.empty else None
rem_txt = (f"{fmt(remaining)}<small> kcal</small>" if remaining is not None and remaining >= 0
           else f"−{fmt(-remaining)}<small> kcal acima</small>" if remaining is not None else "—")
st.markdown(f"""
<div class="ft-hero">
  <div class="ring">{ring}</div>
  <div class="stats">
    <div class="stat"><div class="k">Restante da meta</div><div class="v">{rem_txt}</div></div>
    <div class="stat"><div class="k">Gasto estimado</div><div class="v">{fmt(t['tdee'])}<small> kcal</small></div></div>
    <div class="stat"><div class="k">Saldo estimado</div><div class="v" style="font-size:1rem;margin-top:.3rem">{status_pill(t['status'], t['balance'])}</div></div>
    <div class="stat"><div class="k">Exercício (líquido)</div><div class="v">{fmt(t['exercise_net'])}<small> kcal</small></div></div>
    <div class="stat"><div class="k">Peso atual</div><div class="v">{fmt(last_w['weight_kg'], 1) if last_w else '—'}<small> kg</small></div></div>
    <div class="stat"><div class="k">Média 7 dias</div><div class="v">{fmt(ma7, 1)}<small> kg</small></div></div>
  </div>
</div>""", unsafe_allow_html=True)
if t["has_food"]:
    st.caption("O saldo de hoje é parcial: muda conforme você registra refeições e treinos ao longo do dia.")

# ------------------------------------------------------------------ macros + registros do dia
c1, c2, c3 = st.columns([1.05, 1, 1], gap="medium")
with c1:
    with st.container(border=True):
        st.markdown('<div class="ft-section" style="margin-top:0">Macronutrientes de hoje</div>', unsafe_allow_html=True)
        st.markdown(
            macro_bar("Proteína", t["protein_g"], t["goal_protein"], COLORS["proteina"])
            + macro_bar("Carboidratos", t["carbs_g"], t["goal_carbs"], COLORS["carbo"])
            + macro_bar("Gorduras", t["fat_g"], t["goal_fat"], COLORS["gordura"])
            + f'<div class="foot" style="color:#8a8984;font-size:.78rem">Fibras: {fmt(t["fiber_g"], 1)} g (quando disponível na TACO)</div>',
            unsafe_allow_html=True)
with c2:
    with st.container(border=True):
        st.markdown('<div class="ft-section" style="margin-top:0">Refeições de hoje</div>', unsafe_allow_html=True)
        meals = records.list_meals(conn, today, today)
        if not meals:
            st.caption("Nenhuma refeição registrada hoje.")
        items = "".join(
            f'<div class="ft-list-item"><div><div class="t">{MEAL_LABELS.get(m["meal_type"])}</div>'
            f'<div class="s">{", ".join(i["food_name"].split(",")[0] for i in m["items"])[:60]}</div></div>'
            f'<div class="n">{fmt(sum(i["kcal"] for i in m["items"]))} kcal</div></div>' for m in meals)
        st.markdown(items, unsafe_allow_html=True)
        st.page_link("pages/chat.py", label="Registrar pelo assistente", icon=":material/forum:")
with c3:
    with st.container(border=True):
        st.markdown('<div class="ft-section" style="margin-top:0">Atividades de hoje</div>', unsafe_allow_html=True)
        acts = records.list_activities(conn, today, today)
        if not acts:
            st.caption("Nenhuma atividade registrada hoje.")
        st.markdown("".join(
            f'<div class="ft-list-item"><div><div class="t">{ACTIVITY_LABELS.get(a["activity_type"])}</div>'
            f'<div class="s">{fmt(a["duration_min"])} min' + (f' · {fmt(a["distance_km"], 1)} km' if a["distance_km"] else "")
            + f'</div></div><div class="n">{fmt(a["kcal_net"])} kcal</div></div>' for a in acts), unsafe_allow_html=True)
        st.page_link("pages/exercicios.py", label="Ver exercícios", icon=":material/directions_run:")

# ------------------------------------------------------------------ período
st.markdown('<div class="ft-section">Tendências</div>', unsafe_allow_html=True)
start, end, label = period_filter("dash")
df = daily_summary(conn, start, end)
logged = df[df["has_food"]]
avg_in = logged["kcal_in"].mean() if len(logged) else None
avg_bal = logged["balance"].mean() if len(logged) else None
tot_bal = logged["balance"].sum() if len(logged) else None
cards_row([
    card("Consumo médio", fmt(avg_in), " kcal/dia", f"{len(logged)} de {len(df)} dias registrados", COLORS["consumo"]),
    card("Gasto médio estimado", fmt(df["tdee"].mean()), " kcal/dia", "TMB × fator + exercícios", COLORS["gasto"]),
    card("Saldo médio", fmt(avg_bal), " kcal/dia", "positivo = déficit", COLORS["deficit"]),
    card("Saldo acumulado", fmt(tot_bal), " kcal", f"{int((df['status'] == 'deficit').sum())} dias em déficit · "
         f"{int((df['status'] == 'superavit').sum())} em superávit", COLORS["deficit"]),
])
st.write("")
a, b = st.columns(2, gap="medium")
with a:
    with st.container(border=True):
        st.plotly_chart(charts.intake_vs_expenditure(df), width="stretch", config={"displayModeBar": False})
with b:
    with st.container(border=True):
        st.plotly_chart(charts.balance_bars(df), width="stretch", config={"displayModeBar": False})
a, b = st.columns(2, gap="medium")
with a:
    with st.container(border=True):
        st.plotly_chart(charts.weight_chart(weight_series(conn, start, end), prof.get("target_weight_kg")),
                        width="stretch", config={"displayModeBar": False})
with b:
    with st.container(border=True):
        st.plotly_chart(charts.protein_chart(df), width="stretch", config={"displayModeBar": False})

with st.expander("Ver dados diários em tabela"):
    show = df[["date", "kcal_in", "protein_g", "carbs_g", "fat_g", "tdee", "exercise_net", "balance", "status", "weight"]].copy()
    show["date"] = show["date"].dt.strftime("%d/%m/%Y")
    st.dataframe(show.rename(columns={
        "date": "Data", "kcal_in": "Consumo (kcal)", "protein_g": "Proteína (g)", "carbs_g": "Carbo (g)", "fat_g": "Gordura (g)",
        "tdee": "Gasto est. (kcal)", "exercise_net": "Exercício líq. (kcal)", "balance": "Saldo (kcal)", "status": "Status",
        "weight": "Peso (kg)"}).round(1), hide_index=True, width="stretch")
disclaimer()
