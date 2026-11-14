from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from app.components import charts
from app.components.ui import COLORS, card, cards_row, disclaimer, get_conn, header, period_filter, require_profile
from backend.ai.queries import fmt, period_report
from backend.analytics.daily import daily_summary, period_stats

conn = get_conn()
require_profile(conn)
header("Relatórios", "Indicadores do período calculados a partir dos seus registros.", "Análises")

start, end, label = period_filter("rep", default="Últimos 30 dias")
df = daily_summary(conn, start, end)
s = period_stats(conn, start, end, df)
consistency = s.days_logged / s.days if s.days else 0
cards_row([
    card("Média calórica", fmt(s.avg_kcal_in), " kcal/dia", f"meta média {fmt(s.goal_kcal_avg)} kcal", COLORS["consumo"]),
    card("Proteína média", fmt(s.avg_protein), " g/dia", f"meta atingida em {s.days_protein_goal_met} dia(s)", COLORS["proteina"]),
    card("Saldo acumulado", fmt(s.total_balance), " kcal", f"{s.days_deficit} déficit · {s.days_surplus} superávit · "
         f"{s.days_maintenance} manutenção", COLORS["deficit"]),
    card("Consistência", fmt(consistency * 100), " %", f"{s.days_logged} de {s.days} dias registrados", COLORS["gasto"], consistency),
])
st.write("")
cards_row([
    card("Dias acima da meta", fmt(s.days_above_goal), "", "consumo > meta calórica", COLORS["superavit"]),
    card("Frequência de treinos", fmt(s.activities), " sessões", f"{fmt(s.exercise_minutes)} min no período", COLORS["gasto"]),
    card("Gasto em exercício", fmt(s.exercise_net_total), " kcal", "líquido (sem repouso)", COLORS["gasto"]),
    card("Peso (média 7d)", f"{fmt(s.weight_start, 1)} → {fmt(s.weight_end, 1)}", " kg",
         f"variação {fmt(s.weight_change, 2)} kg" if s.weight_change is not None else "sem pesagens", COLORS["peso"]),
])
st.write("")
a, b = st.columns(2, gap="medium")
with a:
    with st.container(border=True):
        st.plotly_chart(charts.weekly_comparison(df), width="stretch", config={"displayModeBar": False})
with b:
    with st.container(border=True):
        st.plotly_chart(charts.macro_stack(df), width="stretch", config={"displayModeBar": False})

st.markdown('<div class="ft-section">Resumo em linguagem natural</div>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown(period_report(conn, start, end, label))

with st.expander("Comparar dois períodos"):
    c1, c2 = st.columns(2)
    today = date.today()
    p1 = c1.date_input("Período A", value=(today - timedelta(days=6), today), max_value=today, format="DD/MM/YYYY", key="pa")
    p2 = c2.date_input("Período B", value=(today - timedelta(days=13), today - timedelta(days=7)), max_value=today,
                       format="DD/MM/YYYY", key="pb")
    if isinstance(p1, tuple) and len(p1) == 2 and isinstance(p2, tuple) and len(p2) == 2:
        A, B = period_stats(conn, *p1), period_stats(conn, *p2)
        rows = [("Dias registrados", A.days_logged, B.days_logged, 0), ("Consumo médio (kcal)", A.avg_kcal_in, B.avg_kcal_in, 0),
                ("Gasto médio (kcal)", A.avg_tdee, B.avg_tdee, 0), ("Saldo médio (kcal)", A.avg_balance, B.avg_balance, 0),
                ("Proteína média (g)", A.avg_protein, B.avg_protein, 0), ("Sessões de treino", A.activities, B.activities, 0),
                ("Peso médio 7d final (kg)", A.weight_end, B.weight_end, 1)]
        st.dataframe([{"Indicador": r[0], "A": fmt(r[1], r[3]), "B": fmt(r[2], r[3]),
                       "A − B": fmt(None if r[1] is None or r[2] is None else r[1] - r[2], r[3])} for r in rows],
                     hide_index=True, width="stretch")

with st.expander("Tabela diária completa"):
    show = df.copy()
    show["date"] = show["date"].dt.strftime("%d/%m/%Y")
    st.dataframe(show.round(1), hide_index=True, width="stretch")
    st.download_button("Baixar CSV do período", show.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       file_name=f"fittrack_{start}_{end}.csv", mime="text/csv")
disclaimer()
