from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app.components import charts
from app.components.ui import COLORS, card, cards_row, disclaimer, get_conn, header, require_profile
from backend.ai.queries import fmt
from backend.analytics.daily import daily_summary
from backend.models.schemas import MEAL_LABELS, CustomFoodIn, MealIn, MealItemIn, PortionIn
from backend.nutrition import foods as food_repo
from backend.nutrition.calculator import compute_item
from backend.nutrition.importer import import_generic_csv
from backend.nutrition.units import ALL_UNITS, ConversionError
from backend.services import records

conn = get_conn()
require_profile(conn)
header("Alimentação", "Refeições registradas, cadastro manual e base nutricional (TACO).", "Registros")

tab_day, tab_add, tab_db, tab_custom = st.tabs(["Diário", "Adicionar manualmente", "Base de alimentos", "Cadastrar alimento"])

# ------------------------------------------------------------------ diário
with tab_day:
    day = st.date_input("Dia", value=date.today(), max_value=date.today(), format="DD/MM/YYYY", key="food_day")
    s = daily_summary(conn, day, day).iloc[0]
    cards_row([
        card("Calorias", fmt(s["kcal_in"]), " kcal", f"meta {fmt(s['goal_kcal'])} kcal", COLORS["consumo"],
             (s["kcal_in"] or 0) / s["goal_kcal"] if s["goal_kcal"] else None),
        card("Proteína", fmt(s["protein_g"], 1), " g", f"meta {fmt(s['goal_protein'])} g", COLORS["proteina"],
             (s["protein_g"] or 0) / s["goal_protein"] if s["goal_protein"] else None),
        card("Carboidratos", fmt(s["carbs_g"], 1), " g", f"meta {fmt(s['goal_carbs'])} g", COLORS["carbo"],
             (s["carbs_g"] or 0) / s["goal_carbs"] if s["goal_carbs"] else None),
        card("Gorduras", fmt(s["fat_g"], 1), " g", f"meta {fmt(s['goal_fat'])} g", COLORS["gordura"],
             (s["fat_g"] or 0) / s["goal_fat"] if s["goal_fat"] else None),
        card("Fibras", fmt(s["fiber_g"], 1), " g", "quando disponível", "#8a8984"),
    ])
    meals = records.list_meals(conn, day, day)
    if not meals:
        st.info("Nenhuma refeição neste dia. Use o **Assistente** ou a aba **Adicionar manualmente**.")
    for m in meals:
        tot = sum(i["kcal"] for i in m["items"])
        with st.expander(f"{MEAL_LABELS.get(m['meal_type'])} · {fmt(tot)} kcal · #{m['id']}" + (f" · {m['time']}" if m["time"] else ""),
                         expanded=True):
            df = pd.DataFrame(m["items"])[["id", "food_name", "quantity", "unit", "grams", "kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]]
            edited = st.data_editor(
                df, hide_index=True, width="stretch", key=f"ed_{m['id']}", disabled=["id", "food_name", "kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "grams"],
                column_config={
                    "id": None, "food_name": "Alimento",
                    "quantity": st.column_config.NumberColumn("Qtd.", min_value=0.01, format="%.2f"),
                    "unit": st.column_config.SelectboxColumn("Unidade", options=ALL_UNITS),
                    "grams": st.column_config.NumberColumn("Gramas", format="%.0f"),
                    "kcal": st.column_config.NumberColumn("kcal", format="%.0f"),
                    "protein_g": st.column_config.NumberColumn("Prot. (g)", format="%.1f"),
                    "carbs_g": st.column_config.NumberColumn("Carb. (g)", format="%.1f"),
                    "fat_g": st.column_config.NumberColumn("Gord. (g)", format="%.1f"),
                    "fiber_g": st.column_config.NumberColumn("Fibra (g)", format="%.1f"),
                })
            if m["source_text"]:
                st.caption(f"Mensagem original: “{m['source_text']}”")
            c1, c2, _ = st.columns([1.3, 1.3, 3])
            if c1.button("Salvar correções", key=f"save_{m['id']}"):
                errors = []
                for orig, new in zip(df.itertuples(), edited.itertuples()):
                    if orig.quantity != new.quantity or orig.unit != new.unit:
                        try:
                            records.update_meal_item(conn, int(new.id), float(new.quantity), new.unit)
                        except (ConversionError, ValueError) as e:
                            errors.append(f"{new.food_name}: {e}")
                if errors:
                    st.error("\n".join(errors))
                else:
                    st.success("Quantidades atualizadas e nutrientes recalculados.")
                    st.rerun()
            if c2.button("Excluir refeição", key=f"del_{m['id']}"):
                st.session_state[f"confirm_del_{m['id']}"] = True
            if st.session_state.get(f"confirm_del_{m['id']}"):
                st.warning("Confirma a exclusão desta refeição? (fica registrada no histórico de alterações)")
                x1, x2, _ = st.columns([1, 1, 4])
                if x1.button("Sim, excluir", key=f"yes_{m['id']}", type="primary"):
                    records.delete_meal(conn, m["id"])
                    st.session_state.pop(f"confirm_del_{m['id']}")
                    st.rerun()
                if x2.button("Não", key=f"no_{m['id']}"):
                    st.session_state.pop(f"confirm_del_{m['id']}")
                    st.rerun()

    st.markdown('<div class="ft-section">Últimos 14 dias</div>', unsafe_allow_html=True)
    df14 = daily_summary(conn, date.today() - timedelta(days=13), date.today())
    a, b = st.columns([1.6, 1])
    with a:
        with st.container(border=True):
            st.plotly_chart(charts.macro_stack(df14), width="stretch", config={"displayModeBar": False})
    with b:
        with st.container(border=True):
            lg = df14[df14["has_food"]]
            st.plotly_chart(charts.macro_split(lg["protein_g"].sum(), lg["carbs_g"].sum(), lg["fat_g"].sum()),
                            width="stretch", config={"displayModeBar": False})

# ------------------------------------------------------------------ adicionar manualmente
with tab_add:
    st.caption("Monte a refeição escolhendo alimentos da base. Os valores são calculados pela TACO/cadastros.")
    if "manual_items" not in st.session_state:
        st.session_state.manual_items = []
    c1, c2 = st.columns(2)
    mday = c1.date_input("Data", value=date.today(), max_value=date.today(), format="DD/MM/YYYY", key="m_day")
    mtype = c2.selectbox("Refeição", list(MEAL_LABELS), format_func=MEAL_LABELS.get, key="m_type")
    q = st.text_input("Buscar alimento", placeholder="ex.: arroz integral, banana prata, patinho grelhado")
    if q:
        res = food_repo.match_food(conn, q, limit=10)
        if not res.candidates:
            st.warning("Nada encontrado. Cadastre o alimento na aba **Cadastrar alimento**.")
        else:
            opts = {c.food_id: c.name for c in res.candidates}
            r1, r2, r3, r4 = st.columns([3, 1, 1.5, 1])
            fid = r1.selectbox("Resultado", list(opts), format_func=opts.get)
            qty = r2.number_input("Quantidade", min_value=0.01, value=100.0, step=10.0)
            unit = r3.selectbox("Unidade", ALL_UNITS, index=0)
            portions = food_repo.get_portions(conn, fid)
            if portions:
                st.caption("Medidas cadastradas: " + "; ".join(f"{p.unit} ({p.size}) = {fmt(p.grams)} g" for p in portions))
            if r4.button("Adicionar", type="primary", width="stretch"):
                try:
                    compute_item(conn, fid, qty, unit)
                    st.session_state.manual_items.append({"food_id": fid, "name": opts[fid], "quantity": qty, "unit": unit})
                except ConversionError as e:
                    st.error(str(e))
    items = st.session_state.manual_items
    if items:
        rows = []
        for it in items:
            c = compute_item(conn, it["food_id"], it["quantity"], it["unit"])
            n = c.nutrients.rounded()
            rows.append({"Alimento": c.food_name, "Qtd.": f"{fmt(it['quantity'], 2)} {it['unit']}", "Gramas": c.grams,
                         "kcal": n.kcal, "Prot. (g)": n.protein_g, "Carb. (g)": n.carbs_g, "Gord. (g)": n.fat_g})
        tdf = pd.DataFrame(rows)
        st.dataframe(tdf, hide_index=True, width="stretch")
        st.markdown(f"**Total:** {fmt(tdf['kcal'].sum())} kcal · P {fmt(tdf['Prot. (g)'].sum(), 1)} g · "
                    f"C {fmt(tdf['Carb. (g)'].sum(), 1)} g · G {fmt(tdf['Gord. (g)'].sum(), 1)} g")
        b1, b2, _ = st.columns([1.3, 1, 3])
        if b1.button("Registrar refeição", type="primary"):
            try:
                mid = records.save_meal(conn, MealIn(date=mday, meal_type=mtype, items=[
                    MealItemIn(food_id=i["food_id"], quantity=i["quantity"], unit=i["unit"]) for i in items]))
                st.session_state.manual_items = []
                st.success(f"Refeição #{mid} registrada.")
                st.rerun()
            except records.DuplicateError as e:
                st.warning(str(e))
        if b2.button("Limpar"):
            st.session_state.manual_items = []
            st.rerun()

# ------------------------------------------------------------------ base de alimentos
with tab_db:
    q = st.text_input("Pesquisar na base", placeholder="ex.: feijão", key="db_q")
    sql = "SELECT id, name, category, kcal, protein_g, carbs_g, fat_g, fiber_g, density_g_ml, source FROM foods WHERE active=1"
    df = pd.read_sql_query(sql + " ORDER BY name", conn)
    if q:
        ids = [c.food_id for c in food_repo.search_foods(conn, q, limit=50)]
        df = df.set_index("id").loc[[i for i in ids if i in set(df["id"])]].reset_index()
    st.dataframe(df.rename(columns={"name": "Alimento", "category": "Categoria", "kcal": "kcal/100 g", "protein_g": "Prot.",
                                    "carbs_g": "Carb.", "fat_g": "Gord.", "fiber_g": "Fibra", "density_g_ml": "Densidade (g/mL)",
                                    "source": "Fonte"}),
                 hide_index=True, width="stretch", height=380)
    st.caption(f"{len(df)} alimentos exibidos. Valores por 100 g de parte comestível. Fonte principal: TACO 4ª ed. "
               "(NEPA/UNICAMP, 2011). Itens sem valor analisado na TACO (ex.: leite integral fluido) não foram importados — "
               "cadastre-os pelo rótulo.")
    with st.expander("Adicionar medida caseira ou densidade a um alimento"):
        fq = st.text_input("Alimento", key="pf_q")
        if fq:
            cands = food_repo.search_foods(conn, fq, limit=10)
            if cands:
                opts = {c.food_id: c.name for c in cands}
                fid = st.selectbox("Escolha", list(opts), format_func=opts.get, key="pf_sel")
                c1, c2, c3, c4 = st.columns(4)
                unit = c1.selectbox("Unidade", ["unidade", "fatia", "porcao", "colher de sopa", "colher de cha", "concha",
                                                "xicara", "copo", "pote", "quadrado", "pedaco", "lata", "escumadeira"])
                size = c2.selectbox("Tamanho", ["medio", "pequeno", "grande"])
                grams = c3.number_input("Gramas", min_value=0.1, value=50.0)
                if c4.button("Salvar medida"):
                    food_repo.add_portion(conn, fid, unit, grams, size)
                    st.success("Medida salva.")
                dens = st.number_input("Densidade (g/mL) — permite registrar em mL", min_value=0.0, max_value=3.0, value=0.0, step=0.01)
                if st.button("Salvar densidade") and dens:
                    food_repo.set_density(conn, fid, dens)
                    st.success("Densidade salva.")
    with st.expander("Importar base nutricional (CSV)"):
        st.markdown("Colunas obrigatórias: `nome, energia_kcal, proteina_g, carboidrato_g, lipidios_g` (por 100 g). "
                    "Opcionais: `categoria, fibra_g, densidade_g_ml, codigo`. Importe apenas dados que você tem direito de usar "
                    "(ex.: TBCA conforme os termos da USP, tabelas de rótulos).")
        up = st.file_uploader("Arquivo CSV", type=["csv"])
        src = st.text_input("Nome da fonte", value="Importação do usuário")
        delim = st.selectbox("Separador", [",", ";"])
        if up and st.button("Importar"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                tmp.write(up.getvalue())
            try:
                n, errs = import_generic_csv(conn, Path(tmp.name), src, delim)
                st.success(f"{n} alimentos importados.")
                if errs:
                    st.warning(f"{len(errs)} linha(s) ignoradas: " + "; ".join(errs[:10]))
            except ValueError as e:
                st.error(str(e))
            finally:
                Path(tmp.name).unlink(missing_ok=True)

# ------------------------------------------------------------------ cadastro
with tab_custom:
    st.caption("Use os valores do rótulo (convertidos para 100 g) ou de outra fonte confiável.")
    with st.form("custom_food", clear_on_submit=True):
        name = st.text_input("Nome", placeholder="ex.: Whey protein concentrado (marca X)")
        c1, c2, c3 = st.columns(3)
        kcal = c1.number_input("kcal por 100 g", min_value=0.0, max_value=950.0)
        prot = c2.number_input("Proteína (g/100 g)", min_value=0.0, max_value=100.0)
        carb = c3.number_input("Carboidratos (g/100 g)", min_value=0.0, max_value=100.0)
        c4, c5, c6 = st.columns(3)
        fat = c4.number_input("Gorduras (g/100 g)", min_value=0.0, max_value=100.0)
        fib = c5.number_input("Fibras (g/100 g)", min_value=0.0, max_value=100.0)
        dens = c6.number_input("Densidade g/mL (opcional, para líquidos)", min_value=0.0, max_value=3.0)
        c7, c8, c9 = st.columns(3)
        p_unit = c7.selectbox("Medida caseira (opcional)", ["", "unidade", "fatia", "porcao", "colher de sopa", "colher de cha", "pote", "copo"])
        p_grams = c8.number_input("Gramas da medida", min_value=0.0)
        source = c9.text_input("Fonte", value="Rótulo do produto")
        if st.form_submit_button("Cadastrar alimento", type="primary"):
            try:
                portions = [PortionIn(unit=p_unit, grams=p_grams)] if p_unit and p_grams else []
                fid = food_repo.add_custom_food(conn, CustomFoodIn(
                    name=name, kcal=kcal, protein_g=prot, carbs_g=carb, fat_g=fat, fiber_g=fib or None,
                    density_g_ml=dens or None, source=source, portions=portions))
                st.success(f"'{name}' cadastrado (#{fid}). Já pode ser usado no chat.")
            except ValidationError as e:
                st.error("; ".join(err["msg"] for err in e.errors()))
            except Exception as e:  # noqa: BLE001
                st.error(f"Não foi possível cadastrar: {e}")
    custom = pd.read_sql_query("SELECT id, name, kcal, protein_g, carbs_g, fat_g, fiber_g, source FROM foods WHERE is_custom=1", conn)
    if not custom.empty:
        st.markdown("**Seus alimentos cadastrados**")
        st.dataframe(custom, hide_index=True, width="stretch")
disclaimer()
