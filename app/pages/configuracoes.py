from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app.components.ui import disclaimer, get_conn, header
from backend.ai import ollama_client
from backend.ai.queries import fmt
from backend.database import backup
from backend.energy.metabolism import ACTIVITY_FACTORS, bmr_mifflin, suggest_goals
from backend.models.schemas import GOAL_LABELS, LEVEL_LABELS, GoalIn, ProfileIn
from backend.services import audit as audit_svc
from backend.services import records, settings_service

conn = get_conn()
prof = records.get_profile(conn)
first_run = prof is None


def profile_form(p: dict | None, submit_label: str) -> ProfileIn | None:
    """Na primeira execução os campos começam VAZIOS: nada é presumido sobre o usuário."""
    p = p or {}

    def idx(options, key):
        return options.index(p[key]) if p.get(key) in options else None

    with st.form("profile"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Como quer ser chamado (opcional)", value=p.get("name") or "")
        sex = c2.selectbox("Sexo usado na equação metabólica *", ["M", "F"], index=idx(["M", "F"], "sex"),
                           format_func={"M": "Masculino", "F": "Feminino"}.get, placeholder="Selecione")
        age = c3.number_input("Idade *", min_value=10, max_value=120, value=p.get("age"), placeholder="anos")
        c4, c5, c6 = st.columns(3)
        height = c4.number_input("Altura (cm) *", min_value=100.0, max_value=250.0, value=p.get("height_cm"), step=0.5,
                                 placeholder="ex.: 175")
        weight = c5.number_input("Peso atual (kg) *", min_value=25.0, max_value=350.0, value=p.get("initial_weight_kg"),
                                 step=0.1, format="%.1f", placeholder="ex.: 72,5")
        target = c6.number_input("Peso-meta (kg, opcional)", min_value=25.0, max_value=350.0, value=p.get("target_weight_kg"),
                                 step=0.5, format="%.1f", placeholder="opcional")
        c7, c8, c9 = st.columns(3)
        levels = list(LEVEL_LABELS)
        level = c7.selectbox("Nível de atividade *", levels, index=idx(levels, "activity_level"),
                             format_func=LEVEL_LABELS.get, placeholder="Selecione")
        goals = list(GOAL_LABELS)
        goal = c8.selectbox("Objetivo principal *", goals, index=idx(goals, "goal"), format_func=GOAL_LABELS.get,
                            placeholder="Selecione")
        rate = c9.number_input("Ritmo desejado (kg/semana, opcional; negativo = perder)", min_value=-1.5, max_value=1.0,
                               value=p.get("weekly_rate_kg"), step=0.05, format="%.2f", placeholder="opcional")
        st.markdown("**Método de gasto energético diário**")
        methods = {"sedentario_mais_exercicio": "TMB × fator sedentário + gasto LÍQUIDO dos treinos registrados (recomendado)",
                   "fator_atividade": "TMB × fator do nível de atividade (treinos registrados NÃO são somados)"}
        m1, m2 = st.columns([3, 1])
        method = m1.radio("Método", list(methods), format_func=methods.get,
                          index=list(methods).index(p.get("energy_method", "sedentario_mais_exercicio")), label_visibility="collapsed")
        sf = m2.number_input("Fator sedentário", min_value=1.0, max_value=1.6, value=float(p.get("sedentary_factor") or 1.2), step=0.05)
        if st.form_submit_button(submit_label, type="primary"):
            missing = [n for n, v in (("sexo", sex), ("idade", age), ("altura", height), ("peso", weight),
                                      ("nível de atividade", level), ("objetivo", goal)) if v is None]
            if missing:
                st.error("Preencha os campos obrigatórios: " + ", ".join(missing) + ".")
                return None
            try:
                return ProfileIn(name=name or None, sex=sex, age=age, height_cm=height, initial_weight_kg=weight,
                                 activity_level=level, goal=goal, energy_method=method, sedentary_factor=sf,
                                 target_weight_kg=target, weekly_rate_kg=rate)
            except ValidationError as e:
                st.error("; ".join(err["msg"] for err in e.errors()))
    return None


# ================================================================== primeira execução
if first_run:
    header("Bem-vindo ao FitTrack AI", "Configure seu perfil para calcular metabolismo, metas e balanço energético.", "Configuração inicial")
    st.info("Seus dados ficam **somente neste computador** (SQLite local). Nenhum campo é preenchido por suposição — "
            "revise todos os valores.")
    step = st.session_state.get("setup_step", 1)
    if step == 1:
        st.markdown("### 1. Seus dados")
        p = profile_form(None, "Continuar")
        if p:
            st.session_state.setup_profile = p
            st.session_state.setup_step = 2
            st.rerun()
    else:
        p: ProfileIn = st.session_state.setup_profile
        sug = suggest_goals(sex=p.sex, weight_kg=p.initial_weight_kg, height_cm=p.height_cm, age=p.age,
                            activity_level=p.activity_level, goal=p.goal)
        bmr = bmr_mifflin(p.sex, p.initial_weight_kg, p.height_cm, p.age)
        st.markdown("### 2. Metas diárias")
        st.caption(f"TMB estimada (Mifflin-St Jeor): **{fmt(bmr)} kcal**. Gasto total estimado pelo nível de atividade: "
                   f"**{fmt(sug['tdee_estimado'])} kcal**. Sugestões abaixo são um ponto de partida editável — "
                   "o ideal é definir metas com um nutricionista.")
        with st.form("goals_setup"):
            c = st.columns(5)
            kcal = c[0].number_input("Calorias (kcal)", 800.0, 8000.0, float(sug["kcal"]), 10.0)
            prot = c[1].number_input("Proteína (g)", 0.0, 600.0, float(sug["protein_g"]), 1.0)
            carb = c[2].number_input("Carboidratos (g)", 0.0, 1500.0, float(sug["carbs_g"]), 1.0)
            fat = c[3].number_input("Gorduras (g)", 0.0, 500.0, float(sug["fat_g"]), 1.0)
            fib = c[4].number_input("Fibras (g)", 0.0, 150.0, float(sug["fiber_g"]), 1.0)
            b1, b2 = st.columns([1, 5])
            back = b1.form_submit_button("Voltar")
            if b2.form_submit_button("Concluir configuração", type="primary"):
                records.save_profile(conn, p)
                records.save_goal(conn, GoalIn(start_date=date(2000, 1, 1), kcal=kcal, protein_g=prot, carbs_g=carb, fat_g=fat, fiber_g=fib))
                st.session_state.pop("setup_step", None)
                st.success("Perfil criado!")
                st.rerun()
            if back:
                st.session_state.setup_step = 1
                st.rerun()
    disclaimer()
    st.stop()

# ================================================================== configurações
header("Configurações", "Perfil, metas, inteligência artificial local, backup e exportação.", "Análises")
t1, t2, t3, t4, t5 = st.tabs(["Perfil", "Metas", "IA local (Ollama)", "Backup e exportação", "Histórico de alterações"])

with t1:
    p = profile_form(prof, "Salvar perfil")
    if p:
        records.save_profile(conn, p)
        st.success("Perfil atualizado. Os cálculos de gasto usam os novos parâmetros em todo o histórico.")
        st.rerun()
    w = records.body_weight_for(conn, date.today())
    bmr = bmr_mifflin(prof["sex"], w, prof["height_cm"], prof["age"])
    st.caption(f"Com o peso mais recente ({fmt(w, 1)} kg): TMB ≈ {fmt(bmr)} kcal · base sedentária ≈ "
               f"{fmt(bmr * prof['sedentary_factor'])} kcal · pelo fator de atividade ≈ "
               f"{fmt(bmr * ACTIVITY_FACTORS[prof['activity_level']])} kcal.")

with t2:
    cur = records.goal_for(conn, date.today())
    st.caption("Metas são versionadas por data: dias anteriores continuam avaliados pela meta vigente na época.")
    with st.form("goals"):
        c = st.columns(6)
        start = c[0].date_input("Vale a partir de", value=date.today(), format="DD/MM/YYYY")
        kcal = c[1].number_input("Calorias", 800.0, 8000.0, float(cur["kcal"]) if cur else 2000.0, 10.0)
        prot = c[2].number_input("Proteína (g)", 0.0, 600.0, float(cur["protein_g"]) if cur else 120.0, 1.0)
        carb = c[3].number_input("Carboidratos (g)", 0.0, 1500.0, float(cur["carbs_g"]) if cur else 200.0, 1.0)
        fat = c[4].number_input("Gorduras (g)", 0.0, 500.0, float(cur["fat_g"]) if cur else 60.0, 1.0)
        fib = c[5].number_input("Fibras (g)", 0.0, 150.0, float(cur["fiber_g"] or 0) if cur else 25.0, 1.0)
        if st.form_submit_button("Salvar metas", type="primary"):
            records.save_goal(conn, GoalIn(start_date=start, kcal=kcal, protein_g=prot, carbs_g=carb, fat_g=fat, fiber_g=fib or None))
            st.success("Metas salvas.")
            st.rerun()
    macro_kcal = (prot * 4 + carb * 4 + fat * 9)
    st.caption(f"As metas de macros somam {fmt(macro_kcal)} kcal (meta calórica: {fmt(kcal)} kcal).")
    sug = suggest_goals(sex=prof["sex"], weight_kg=records.body_weight_for(conn, date.today()), height_cm=prof["height_cm"],
                        age=prof["age"], activity_level=prof["activity_level"], goal=prof["goal"])
    st.caption(f"Sugestão automática para o perfil atual: {fmt(sug['kcal'])} kcal · P {sug['protein_g']} g · "
               f"C {sug['carbs_g']} g · G {sug['fat_g']} g · fibras {sug['fiber_g']} g.")
    hist = records.all_goals(conn)
    if hist:
        st.dataframe(pd.DataFrame(hist)[["start_date", "kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]],
                     hide_index=True, width="stretch")

with t3:
    s = settings_service.get_all(conn)
    st.markdown("A IA local é **opcional**: sem ela, um interpretador por regras em português funciona offline. "
                "Com ela, o modelo apenas converte sua mensagem em JSON; os cálculos continuam no motor determinístico "
                "e quantidades não presentes na mensagem são descartadas.")
    with st.form("ai"):
        enabled = st.toggle("Ativar IA local (Ollama)", value=s["ai_enabled"].lower() == "true")
        c1, c2, c3 = st.columns([2, 1.5, 1])
        url = c1.text_input("Endereço do Ollama", value=s["ollama_url"])
        st_now = ollama_client.status(url) if url else None
        models = st_now.models if st_now and st_now.reachable else []
        if models:
            model = c2.selectbox("Modelo", models, index=models.index(s["ollama_model"]) if s["ollama_model"] in models else 0)
        else:
            model = c2.text_input("Modelo", value=s["ollama_model"])
        timeout = c3.number_input("Tempo máximo (s)", min_value=5, max_value=600, value=int(float(s["ollama_timeout"])))
        if st.form_submit_button("Salvar", type="primary"):
            if url and not url.startswith(("http://localhost", "http://127.0.0.1", "http://[::1]")):
                st.warning("Atenção: o endereço não é local — suas mensagens seriam enviadas para outra máquina.")
            settings_service.set_many(conn, {"ai_enabled": str(enabled).lower(), "ollama_url": url, "ollama_model": model,
                                             "ollama_timeout": str(timeout)})
            st.success("Configurações de IA salvas.")
            st.rerun()
    if st_now and st_now.reachable:
        st.success(f"Ollama acessível em {url}. Modelos instalados: {', '.join(models) or 'nenhum'}.")
        if not models:
            st.info("Instale um modelo pequeno, ex.: `ollama pull qwen2.5:3b` (≈2 GB) ou `qwen2.5:7b` (≈4,7 GB).")
    else:
        st.warning("Ollama não está acessível. O app continua funcionando com o interpretador por regras. "
                   "Para usar IA local: instale em https://ollama.com, rode `ollama pull qwen2.5:3b` e ative acima.")
    if st.button("Testar interpretação com a IA"):
        with st.spinner("Consultando o modelo local…"):
            r = ollama_client.parse_with_llm("Comi 2 ovos e 1 pão francês e corri 5 km em 30 minutos", s["ollama_url"],
                                              s["ollama_model"], float(s["ollama_timeout"]))
        st.json(r.model_dump(exclude_none=True) if r else {"erro": "sem resposta válida (veja se o modelo está instalado)"})
    st.markdown("**Outros parâmetros**")
    with st.form("other"):
        c1, c2, c3 = st.columns(3)
        kpk = c1.number_input("kcal por kg (estimativa teórica)", 3000.0, 9500.0, float(s["kcal_per_kg"]), 100.0,
                              help="Usado apenas para converter saldo em equivalência teórica de peso.")
        band = c2.number_input("Faixa de manutenção (± kcal)", 0.0, 500.0, float(s["maintenance_band_kcal"]), 10.0)
        abd = c3.number_input("Backup automático a cada N dias (0 = desligado)", 0.0, 30.0, float(s["auto_backup_days"]), 1.0)
        if st.form_submit_button("Salvar parâmetros"):
            settings_service.set_many(conn, {"kcal_per_kg": str(kpk), "maintenance_band_kcal": str(band), "auto_backup_days": str(abd)})
            st.success("Parâmetros salvos.")

with t4:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Backup do banco**")
        if st.button("Criar backup agora", type="primary", icon=":material/backup:"):
            path = backup.create_backup(conn, "manual", keep=int(float(settings_service.get(conn, "backup_keep"))))
            st.success(f"Backup criado: `{path.name}`")
        files = backup.list_backups()
        st.caption(f"{len(files)} backup(s) em `data/backups/`.")
        if files:
            sel = st.selectbox("Backups", files, format_func=lambda x: Path(x).name)
            st.download_button("Baixar backup selecionado", Path(sel).read_bytes(), file_name=Path(sel).name)
            if st.button("Restaurar este backup"):
                st.session_state.confirm_restore = str(sel)
            if st.session_state.get("confirm_restore"):
                st.warning("Restaurar substitui TODOS os dados atuais pelo backup. Um backup de segurança do estado atual "
                           "será criado antes (pre-restore). Confirmar?")
                x1, x2 = st.columns(2)
                if x1.button("Sim, restaurar", type="primary"):
                    safety = backup.restore_backup(conn, Path(st.session_state.pop("confirm_restore")))
                    st.success(f"Restaurado. Estado anterior salvo em `{safety.name}`.")
                    st.rerun()
                if x2.button("Cancelar restauração"):
                    st.session_state.pop("confirm_restore")
                    st.rerun()
    with c2:
        st.markdown("**Exportação CSV**")
        st.caption("Gera um .zip com uma planilha CSV por tabela (separador ';', UTF-8 — abre no Excel).")
        if st.button("Gerar exportação", icon=":material/download:"):
            out, data = backup.export_csv_zip(conn)
            st.session_state.export = (out.name, data)
        if st.session_state.get("export"):
            name, data = st.session_state.export
            st.download_button(f"Baixar {name}", data, file_name=name, mime="application/zip")

with t5:
    rows = audit_svc.recent(conn, 200)
    if rows:
        st.dataframe(pd.DataFrame(rows)[["ts", "entity", "entity_id", "action", "origin"]].rename(
            columns={"ts": "Quando", "entity": "Tabela", "entity_id": "ID", "action": "Ação", "origin": "Origem"}),
            hide_index=True, width="stretch")
    else:
        st.caption("Sem alterações registradas.")
disclaimer()
