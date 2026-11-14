from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app.components import charts
from app.components.ui import COLORS, card, cards_row, disclaimer, get_conn, header, period_filter, require_profile
from backend.ai.queries import fmt
from backend.exercise.mets import SPECIFIC_MET
from backend.models.schemas import ACTIVITY_LABELS, ActivityIn
from backend.services import records

conn = get_conn()
require_profile(conn)
header("Exercícios", "Treinos registrados e gasto energético estimado por METs.", "Registros")

with st.expander("➕ Registrar atividade", expanded=False):
    with st.form("act_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        day = c1.date_input("Data", value=date.today(), max_value=date.today(), format="DD/MM/YYYY")
        types = list(ACTIVITY_LABELS)
        atype = c2.selectbox("Tipo", types, format_func=ACTIVITY_LABELS.get)
        specific = c3.selectbox("Modalidade específica (opcional)", [""] + sorted(SPECIFIC_MET))
        c4, c5, c6 = st.columns(3)
        dur = c4.number_input("Duração (min)", min_value=0.0, max_value=1440.0, step=5.0)
        dist = c5.number_input("Distância (km, opcional)", min_value=0.0, max_value=500.0, step=0.5)
        inten = c6.selectbox("Intensidade", ["moderada", "leve", "vigorosa"])
        notes = st.text_input("Observações")
        if st.form_submit_button("Registrar", type="primary"):
            try:
                a = ActivityIn(date=day, activity_type=atype, duration_min=dur, distance_km=dist or None, intensity=inten,
                               description=specific or None, notes=notes or None)
                aid = records.save_activity(conn, a, specific=specific or None)
                st.success(f"Atividade #{aid} registrada.")
            except ValidationError as e:
                st.error("; ".join(err["msg"] for err in e.errors()))
            except records.DuplicateError as e:
                st.warning(str(e))

start, end, label = period_filter("ex")
acts = pd.DataFrame(records.list_activities(conn, start, end))
if acts.empty:
    cards_row([card("Sessões", "0", "", label, COLORS["consumo"]), card("Minutos", "0", " min", "", COLORS["gasto"]),
               card("Gasto líquido", "0", " kcal", "", COLORS["proteina"]), card("Distância", "0", " km", "", COLORS["peso"])])
else:
    cards_row([
        card("Sessões", fmt(len(acts)), "", f"{acts['date'].nunique()} dias ativos", COLORS["consumo"]),
        card("Tempo total", fmt(acts["duration_min"].sum()), " min", f"média {fmt(acts['duration_min'].mean())} min/sessão", COLORS["gasto"]),
        card("Gasto líquido", fmt(acts["kcal_net"].sum()), " kcal", f"bruto {fmt(acts['kcal_gross'].sum())} kcal", COLORS["proteina"]),
        card("Distância", fmt(acts["distance_km"].fillna(0).sum(), 1), " km", "corrida, caminhada, ciclismo", COLORS["peso"]),
    ])
st.write("")
with st.container(border=True):
    st.plotly_chart(charts.activity_chart(acts, start, end), width="stretch", config={"displayModeBar": False})

st.markdown('<div class="ft-section">Histórico</div>', unsafe_allow_html=True)
if acts.empty:
    st.caption("Nenhuma atividade no período.")
else:
    view = acts.sort_values(["date", "id"], ascending=False).copy()
    view["Tipo"] = view["activity_type"].map(ACTIVITY_LABELS)
    view["Ritmo"] = [f"{int(p)}:{int(round((p % 1) * 60)):02d} /km" if p == p and p else "" for p in
                     (view["duration_min"] / view["distance_km"]).where(view["activity_type"].isin(["corrida", "caminhada"]))]
    st.dataframe(view[["id", "date", "Tipo", "description", "duration_min", "distance_km", "Ritmo", "intensity", "met",
                       "kcal_gross", "kcal_net", "met_source"]].rename(columns={
        "id": "#", "date": "Data", "description": "Modalidade", "duration_min": "Min", "distance_km": "Km", "intensity": "Intensidade",
        "met": "MET", "kcal_gross": "kcal brutas", "kcal_net": "kcal líquidas", "met_source": "Fonte do MET"}),
        hide_index=True, width="stretch")
    c1, c2, _ = st.columns([2, 1, 3])
    del_id = c1.selectbox("Excluir atividade #", [""] + view["id"].astype(str).tolist())
    if del_id and c2.button("Excluir", type="primary"):
        st.session_state.confirm_act = int(del_id)
    if st.session_state.get("confirm_act"):
        st.warning(f"Confirma excluir a atividade #{st.session_state.confirm_act}?")
        x1, x2, _ = st.columns([1, 1, 4])
        if x1.button("Sim, excluir"):
            records.delete_activity(conn, st.session_state.pop("confirm_act"))
            st.rerun()
        if x2.button("Cancelar"):
            st.session_state.pop("confirm_act")
            st.rerun()

with st.expander("Como o gasto é estimado"):
    st.markdown("""
- **MET** (equivalente metabólico) vem do *Compendium of Physical Activities* (Ainsworth et al., 2011; atualização 2024).
  Para corrida, caminhada e ciclismo com distância e tempo, o MET é **interpolado pela velocidade**.
- **Gasto bruto** = MET × peso (kg) × horas. **Gasto líquido** = (MET − 1) × peso × horas.
- Apenas o **líquido** é somado ao gasto diário no método padrão, porque a linha de base (TMB × 1,2) já inclui o
  gasto de repouso durante o treino — isso evita **contar duas vezes**.
- O peso usado é o último registrado até a data do treino.
- Limitações: METs são médias populacionais; condicionamento, técnica, terreno e intensidade real alteram o gasto.
  Musculação tem estimativa especialmente imprecisa (pausas, volume, carga).
""")
disclaimer()
