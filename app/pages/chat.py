from __future__ import annotations

import uuid
from datetime import date

import streamlit as st

from app.components.ui import disclaimer, get_conn, header, require_profile
from backend.ai.assistant import Assistant, Draft, render_draft
from backend.models.schemas import ACTIVITY_LABELS, MEAL_LABELS
from backend.nutrition.foods import search_foods
from backend.nutrition.units import ALL_UNITS
from backend.services import chat_history

conn = get_conn()
require_profile(conn)
header("Assistente", "Converse para registrar refeições, treinos e peso — ou pergunte sobre seus números.", "Chat")

if "draft" not in st.session_state:
    st.session_state.draft = None
    st.session_state.draft_key = None


def set_draft(d: Draft | None) -> None:
    st.session_state.draft = d
    st.session_state.draft_key = uuid.uuid4().hex[:8] if d else None


def process(message: str, allow_duplicate: bool = False, show_user: bool = True) -> None:
    assistant = Assistant(conn)
    if show_user:
        chat_history.add(conn, "user", message)
    if allow_duplicate and st.session_state.draft:
        reply = assistant.confirm(st.session_state.draft, allow_duplicate=True)
    else:
        with st.spinner("Interpretando…"):
            reply = assistant.handle(message, st.session_state.draft)
    chat_history.add(conn, "assistant", reply.text)
    if reply.draft is not st.session_state.draft or reply.draft is None:
        set_draft(reply.draft)


# ------------------------------------------------------------------ histórico
top = st.columns([1, 1, 4])
if top[0].button("Limpar conversa", icon=":material/delete_sweep:"):
    st.session_state.confirm_clear = True
if st.session_state.get("confirm_clear"):
    st.warning("Apagar o histórico da conversa? (Os registros de alimentação/treino NÃO são afetados.)")
    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("Sim, apagar", type="primary"):
        chat_history.clear(conn)
        st.session_state.confirm_clear = False
        set_draft(None)
        st.rerun()
    if c2.button("Não"):
        st.session_state.confirm_clear = False
        st.rerun()

history = chat_history.recent(conn)
if not history:
    with st.chat_message("assistant", avatar="🥗"):
        st.markdown("Olá! Me conte o que você comeu, como treinou ou quanto pesou hoje. "
                    "Ex.: *Comi 150 g de arroz, 100 g de feijão e 180 g de peito de frango*. "
                    "Digite **ajuda** para ver tudo o que sei fazer.")
for m in history:
    with st.chat_message(m["role"], avatar="🥗" if m["role"] == "assistant" else "🙂"):
        st.markdown(m["content"])

# ------------------------------------------------------------------ cartão do rascunho
d: Draft | None = st.session_state.draft
if d is not None and not d.pending_delete:
    k = st.session_state.draft_key
    with st.container(border=True):
        st.markdown("**📝 Rascunho — revise antes de salvar**")
        c1, c2 = st.columns(2)
        new_day = c1.date_input("Data", value=d.day, max_value=date.today(), format="DD/MM/YYYY", key=f"{k}_day")
        if d.foods:
            meal_keys = list(MEAL_LABELS)
            new_meal = c2.selectbox("Refeição", meal_keys, index=meal_keys.index(d.meal_type),
                                    format_func=MEAL_LABELS.get, key=f"{k}_meal")
            d.meal_type = new_meal
        d.day = new_day

        for i, f in enumerate(d.foods):
            st.markdown(f"<div style='margin-top:.6rem;font-weight:600'>{i + 1}. “{f.raw_name}”</div>", unsafe_allow_html=True)
            cols = st.columns([3.2, 1.1, 1.6, 1.1, 0.6])
            options = list(f.candidates)
            extra = cols[0].text_input("Buscar outro alimento", key=f"{k}_s{i}", placeholder="ex.: leite desnatado",
                                       label_visibility="collapsed")
            if extra:
                for c in search_foods(conn, extra, limit=8):
                    if c.food_id not in [o[0] for o in options]:
                        options.append((c.food_id, c.name))
            if options:
                ids = [o[0] for o in options]
                names = dict(options)
                sel = cols[0].selectbox("Alimento", ids, index=ids.index(f.food_id) if f.food_id in ids else None,
                                        format_func=lambda x: names[x], placeholder="Escolha o alimento correto",
                                        key=f"{k}_f{i}_{len(ids)}")
                if sel is not None:
                    f.food_id, f.food_name = sel, names[sel]
            else:
                cols[0].error("Não encontrado — busque outro nome ou cadastre na página Alimentação.")
            f.quantity = cols[1].number_input("Qtd.", min_value=0.0, value=float(f.quantity or 0), step=0.5,
                                              key=f"{k}_q{i}") or None
            units = ALL_UNITS
            f.unit = cols[2].selectbox("Unidade", units, index=units.index(f.unit) if f.unit in units else 0, key=f"{k}_u{i}")
            go = cols[3].number_input("ou gramas", min_value=0.0, value=float(f.grams_override or 0), step=10.0,
                                      key=f"{k}_g{i}", help="Peso exato em gramas (substitui a conversão da unidade)")
            f.grams_override = go or None
            if cols[4].button("✕", key=f"{k}_rm{i}", help="Remover item"):
                d.foods.pop(i)
                st.rerun()

        for i, a in enumerate(d.activities):
            st.markdown(f"<div style='margin-top:.6rem;font-weight:600'>🏃 Atividade {i + 1}</div>", unsafe_allow_html=True)
            cols = st.columns([2, 1, 1, 1.4, 0.6])
            types = list(ACTIVITY_LABELS)
            a.activity_type = cols[0].selectbox("Tipo", types, index=types.index(a.activity_type),
                                                format_func=ACTIVITY_LABELS.get, key=f"{k}_at{i}")
            a.duration_min = cols[1].number_input("Minutos", min_value=0.0, value=float(a.duration_min or 0), step=5.0,
                                                  key=f"{k}_ad{i}") or None
            a.distance_km = cols[2].number_input("Km", min_value=0.0, value=float(a.distance_km or 0), step=0.5,
                                                 key=f"{k}_ak{i}") or None
            ints = ["(não informada)", "leve", "moderada", "vigorosa"]
            sel = cols[3].selectbox("Intensidade", ints, index=ints.index(a.intensity) if a.intensity else 0, key=f"{k}_ai{i}")
            a.intensity = None if sel.startswith("(") else sel
            if cols[4].button("✕", key=f"{k}_arm{i}", help="Remover atividade"):
                d.activities.pop(i)
                st.rerun()

        if d.weight_kg is not None:
            d.weight_kg = st.number_input("Peso (kg)", min_value=25.0, max_value=350.0, value=float(d.weight_kg),
                                          step=0.1, format="%.1f", key=f"{k}_w")

        Assistant(conn).recompute(d)
        st.markdown(render_draft(d).split("\n\nConfirme")[0].split("\n\nComplete")[0])
        b1, b2, b3, _ = st.columns([1.3, 1.6, 1, 2])
        if b1.button("Confirmar registro", type="primary", disabled=not d.ready or d.empty, icon=":material/check:"):
            process("sim")
            st.rerun()
        if b2.button("Registrar mesmo assim", help="Ignora o aviso de registro duplicado", icon=":material/content_copy:"):
            process("registrar mesmo assim", allow_duplicate=True, show_user=False)
            st.rerun()
        if b3.button("Cancelar", icon=":material/close:"):
            process("cancelar")
            st.rerun()
elif d is not None and d.pending_delete:
    with st.container(border=True):
        st.warning(f"Confirmar exclusão de **{d.pending_delete[0]} #{d.pending_delete[1]}**? Esta ação fica registrada no histórico.")
        b1, b2, _ = st.columns([1, 1, 4])
        if b1.button("Excluir", type="primary"):
            process("sim")
            st.rerun()
        if b2.button("Manter"):
            process("cancelar")
            st.rerun()

# ------------------------------------------------------------------ sugestões + entrada
if not history:
    st.caption("Sugestões")
    sug = st.columns(3)
    examples = ["Comi 150 g de arroz, 100 g de feijão e 180 g de peito de frango",
                "Fiz musculação por 1 hora e 20 minutos", "Estou em déficit hoje?"]
    for col, ex in zip(sug, examples):
        if col.button(ex, width="stretch"):
            process(ex)
            st.rerun()

msg = st.chat_input("Ex.: Corri 5 km em 30 minutos · Quanto ainda posso comer hoje?")
if msg:
    process(msg)
    st.rerun()

disclaimer()
