"""Componentes visuais reutilizáveis e acesso ao banco na interface."""
from __future__ import annotations

import html
import math
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from backend import config
from backend.ai.queries import fmt
from backend.database.connection import connect, init_db

CSS_FILE = Path(__file__).resolve().parent.parent / "styles" / "theme.css"

COLORS = {
    "consumo": "#2a78d6", "gasto": "#eb6834", "proteina": "#1baf7a", "carbo": "#eda100",
    "gordura": "#e87ba4", "peso": "#6250d6", "deficit": "#2a78d6", "superavit": "#e34948",
    "neutro": "#c3c2b7", "meta": "#52514e",
}


@st.cache_resource(show_spinner="Preparando banco de dados…")
def _bootstrap(db_file: str) -> bool:
    conn = init_db(Path(db_file))  # migrations + carga da TACO na 1ª execução
    from backend.services.maintenance import auto_backup
    auto_backup(conn)
    conn.close()
    return True


def get_conn():
    """Uma conexão por sessão do navegador (o SQLite serializa as escritas)."""
    db_file = str(config.db_path())
    _bootstrap(db_file)
    if "conn" not in st.session_state or st.session_state.get("conn_db") != db_file:
        st.session_state.conn = connect(Path(db_file))
        st.session_state.conn_db = db_file
    return st.session_state.conn


def inject_css() -> None:
    st.markdown(f"<style>{CSS_FILE.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    st.markdown(
        f"""<div class="ft-header"><div>
        <div class="eyebrow">{html.escape(eyebrow)}</div>
        <div class="title">{html.escape(title)}</div>
        <div class="sub">{html.escape(subtitle)}</div></div></div>""",
        unsafe_allow_html=True)


def card(label: str, value: str, unit: str = "", foot: str = "", color: str | None = None,
         progress: float | None = None) -> str:
    dot = f'<span class="dot" style="background:{color}"></span>' if color else ""
    bar = ""
    if progress is not None and not math.isnan(progress):
        pct = max(0.0, min(progress, 1.0)) * 100
        bar = f'<div class="bar"><span style="width:{pct:.0f}%;background:{color or COLORS["consumo"]}"></span></div>'
    return (f'<div class="ft-card"><div class="label">{dot}{html.escape(label)}</div>'
            f'<div class="value">{value}<small>{html.escape(unit)}</small></div>{bar}'
            f'<div class="foot">{foot}</div></div>')


def cards_row(cards: list[str]) -> None:
    cols = st.columns(len(cards))
    for c, h in zip(cols, cards):
        c.markdown(h, unsafe_allow_html=True)


def ring_svg(fraction: float, center_big: str, center_small: str, color: str, size: int = 168) -> str:
    """Anel de progresso (ex.: calorias consumidas / meta)."""
    r, sw = (size - 18) / 2, 14
    circ = 2 * math.pi * r
    frac = 0 if fraction is None or math.isnan(fraction) else max(0.0, min(fraction, 1.0))
    over = fraction is not None and not math.isnan(fraction) and fraction > 1
    stroke = "#e34948" if over else color
    return f"""<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img"
      aria-label="{html.escape(center_big)} {html.escape(center_small)}">
      <circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="#efeeea" stroke-width="{sw}"/>
      <circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round"
        stroke-dasharray="{circ*frac:.1f} {circ:.1f}" transform="rotate(-90 {size/2} {size/2})"/>
      <text x="50%" y="47%" text-anchor="middle" font-family="Inter, sans-serif" font-size="28" font-weight="800" fill="#0b0b0b">{html.escape(center_big)}</text>
      <text x="50%" y="62%" text-anchor="middle" font-family="Inter, sans-serif" font-size="12" font-weight="600" fill="#8a8984">{html.escape(center_small)}</text>
    </svg>"""


def macro_bar(label: str, value: float | None, goal: float | None, color: str) -> str:
    v = 0 if value is None or (isinstance(value, float) and math.isnan(value)) else value
    g = None if goal is None or (isinstance(goal, float) and math.isnan(goal)) else goal
    pct = min(v / g, 1) * 100 if g else 0
    goal_txt = f" / {fmt(g)} g" if g else " g"
    return (f'<div class="ft-macro"><div class="row"><span>{html.escape(label)}</span><span><b>{fmt(v)}</b>{goal_txt}</span></div>'
            f'<div class="bar"><span style="width:{pct:.0f}%;background:{color}"></span></div></div>')


def status_pill(status: str, balance: float | None) -> str:
    labels = {"deficit": "Déficit", "superavit": "Superávit", "manutencao": "Manutenção", "sem_registro": "Sem registro"}
    txt = labels.get(status, status)
    if balance is not None and not (isinstance(balance, float) and math.isnan(balance)):
        txt += f" · {fmt(abs(balance))} kcal"
    return f'<span class="ft-pill {status}">{txt}</span>'


def period_filter(key: str, default: str = "Últimos 30 dias") -> tuple[date, date, str]:
    options = ["Hoje", "Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias", "Personalizado"]
    choice = st.segmented_control("Período", options, default=default, key=f"{key}_period",
                                  label_visibility="collapsed") or default
    today = date.today()
    if choice == "Hoje":
        return today, today, choice
    if choice == "Personalizado":
        rng = st.date_input("Intervalo", value=(today - timedelta(days=13), today), max_value=today,
                            format="DD/MM/YYYY", key=f"{key}_range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            return rng[0], rng[1], f"{rng[0]:%d/%m/%Y} a {rng[1]:%d/%m/%Y}"
        return today - timedelta(days=13), today, choice
    days = {"Últimos 7 dias": 7, "Últimos 30 dias": 30, "Últimos 90 dias": 90}[choice]
    return today - timedelta(days=days - 1), today, choice


def disclaimer() -> None:
    st.markdown(f'<div class="ft-disclaimer">⚠️ {config.DISCLAIMER.replace("**", "")}</div>', unsafe_allow_html=True)


def require_profile(conn) -> dict:
    from backend.services import records
    prof = records.get_profile(conn)
    if not prof:
        st.info("Configure seu perfil para começar.")
        st.page_link("pages/configuracoes.py", label="Abrir configuração inicial", icon="⚙️")
        st.stop()
    return prof
