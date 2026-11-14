"""FitTrack AI — ponto de entrada da interface (Streamlit).

Executar a partir da raiz do projeto:  streamlit run app/main.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.components.ui import get_conn, inject_css  # noqa: E402
from backend.services import records, settings_service  # noqa: E402
from backend.services.maintenance import setup_logging  # noqa: E402

st.set_page_config(page_title="FitTrack AI", page_icon="🥗", layout="wide", initial_sidebar_state="expanded")
setup_logging()
inject_css()
conn = get_conn()
has_profile = records.get_profile(conn) is not None

PAGES = Path(__file__).resolve().parent / "pages"
dashboard = st.Page(str(PAGES / "dashboard.py"), title="Dashboard", icon=":material/space_dashboard:", default=has_profile)
chat = st.Page(str(PAGES / "chat.py"), title="Assistente", icon=":material/forum:")
food = st.Page(str(PAGES / "alimentacao.py"), title="Alimentação", icon=":material/restaurant:")
exercise = st.Page(str(PAGES / "exercicios.py"), title="Exercícios", icon=":material/directions_run:")
weight = st.Page(str(PAGES / "peso.py"), title="Peso corporal", icon=":material/monitor_weight:")
reports = st.Page(str(PAGES / "relatorios.py"), title="Relatórios", icon=":material/insights:")
settings = st.Page(str(PAGES / "configuracoes.py"), title="Configurações", icon=":material/settings:", default=not has_profile)

with st.sidebar:
    st.markdown('<div class="ft-brand"><div class="logo">FT</div><div><div class="name">FitTrack AI</div>'
                '<div class="tag">Diário nutricional local</div></div></div>', unsafe_allow_html=True)

if has_profile:
    nav = st.navigation({"": [dashboard, chat], "Registros": [food, exercise, weight], "Análises": [reports, settings]})
else:
    nav = st.navigation([settings])

with st.sidebar:
    ai_on = settings_service.get_bool(conn, "ai_enabled")
    st.caption(("🟢 IA local (Ollama) ativada" if ai_on else "⚪ IA desativada — interpretador por regras")
               + " · dados 100% locais")
    if os.environ.get("FITTRACK_DEMO"):
        st.warning("**Demonstração pública** com dados fictícios gerados automaticamente. Não digite dados pessoais: "
                   "este ambiente é compartilhado e reiniciado periodicamente. Para uso real, rode localmente "
                   "(github.com/Igor-Millis/fittrack-ai).")

nav.run()
