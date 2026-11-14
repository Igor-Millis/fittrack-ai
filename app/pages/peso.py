from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from app.components import charts
from app.components.ui import COLORS, card, cards_row, disclaimer, get_conn, header, period_filter, require_profile
from backend.ai.queries import fmt
from backend.analytics.daily import weight_series, weight_trend
from backend.models.schemas import WeightIn
from backend.services import records

conn = get_conn()
prof = require_profile(conn)
header("Peso corporal", "Pesagens, média móvel de 7 dias e tendência.", "Registros")

with st.container(border=True):
    c1, c2, c3, c4 = st.columns([1.2, 1, 2, 1])
    wday = c1.date_input("Data", value=date.today(), max_value=date.today(), format="DD/MM/YYYY")
    last = conn.execute("SELECT weight_kg FROM weights ORDER BY date DESC LIMIT 1").fetchone()
    wkg = c2.number_input("Peso (kg)", min_value=25.0, max_value=350.0, step=0.1, format="%.1f",
                          value=float(last["weight_kg"] if last else prof["initial_weight_kg"]))
    notes = c3.text_input("Observação (opcional)", placeholder="ex.: em jejum, após o banheiro")
    c4.write("")
    existing = records.get_weight(conn, wday)
    if c4.button("Registrar", type="primary", width="stretch"):
        if existing and not st.session_state.get("replace_ok"):
            st.session_state.replace_ok = True
            st.warning(f"Já existe {fmt(existing['weight_kg'], 1)} kg em {wday:%d/%m}. Clique em Registrar de novo para substituir.")
        else:
            records.save_weight(conn, WeightIn(date=wday, weight_kg=wkg, notes=notes or None), replace=bool(existing))
            st.session_state.replace_ok = False
            st.success("Peso registrado.")
            st.rerun()

start, end, label = period_filter("peso", default="Últimos 90 dias")
ws = weight_series(conn, start, end)
wt = weight_trend(conn, date.today(), days=28)
cur = ws["weight_kg"].iloc[-1] if not ws.empty else None
ma = ws["ma7"].iloc[-1] if not ws.empty else None
week_ago = weight_series(conn, date.today() - timedelta(days=40), date.today() - timedelta(days=7))
weekly = (ma - week_ago["ma7"].iloc[-1]) if (ma is not None and not week_ago.empty) else None
month_ago = weight_series(conn, date.today() - timedelta(days=90), date.today() - timedelta(days=30))
monthly = (ma - month_ago["ma7"].iloc[-1]) if (ma is not None and not month_ago.empty) else None
cards_row([
    card("Última pesagem", fmt(cur, 1), " kg", f"{ws['date'].iloc[-1]:%d/%m/%Y}" if not ws.empty else "sem registros", COLORS["peso"]),
    card("Média móvel 7 dias", fmt(ma, 1), " kg", "suaviza oscilações de água/sal", COLORS["peso"]),
    card("Variação semanal", (("+" if weekly and weekly > 0 else "") + fmt(weekly, 2)) if weekly is not None else "—", " kg",
         "média 7d vs. 7 dias atrás", COLORS["consumo"]),
    card("Variação mensal", (("+" if monthly and monthly > 0 else "") + fmt(monthly, 2)) if monthly is not None else "—", " kg",
         "média 7d vs. 30 dias atrás", COLORS["consumo"]),
    card("Tendência (28 dias)", fmt(wt.slope_kg_week, 2) if wt.slope_kg_week is not None else "—", " kg/sem",
         f"esperado pelo saldo: {fmt(wt.expected_kg_week, 2)}" if wt.expected_kg_week is not None else "regressão linear",
         COLORS["gasto"]),
])
st.write("")
with st.container(border=True):
    st.plotly_chart(charts.weight_chart(ws, prof.get("target_weight_kg")), width="stretch", config={"displayModeBar": False})

st.info(f"**Observado × estimado:** {wt.message}  \n"
        + (f"Gasto implícito pela tendência real: **{fmt(wt.observed_tdee)} kcal/dia** × estimado pelo app: "
           f"{fmt(wt.estimated_tdee)} kcal/dia." if wt.observed_tdee else "")
        + "  \nVariações de um dia para o outro refletem principalmente água, sódio, glicogênio e conteúdo intestinal — "
          "não ganho ou perda real de gordura. Observe a média móvel e a tendência de semanas.")

with st.expander("Pesagens registradas"):
    allw = conn.execute("SELECT id, date, weight_kg, notes FROM weights ORDER BY date DESC").fetchall()
    if allw:
        st.dataframe([dict(r) for r in allw], hide_index=True, width="stretch")
        c1, c2, _ = st.columns([2, 1, 3])
        wid = c1.selectbox("Excluir pesagem #", [""] + [str(r["id"]) for r in allw])
        if wid and c2.button("Excluir"):
            st.session_state.confirm_w = int(wid)
        if st.session_state.get("confirm_w"):
            st.warning(f"Confirma excluir a pesagem #{st.session_state.confirm_w}?")
            x1, x2, _ = st.columns([1, 1, 4])
            if x1.button("Sim, excluir", type="primary"):
                records.delete_weight(conn, st.session_state.pop("confirm_w"))
                st.rerun()
            if x2.button("Cancelar"):
                st.session_state.pop("confirm_w")
                st.rerun()
disclaimer()
