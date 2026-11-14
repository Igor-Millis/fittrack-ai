"""Gráficos Plotly com estilo consistente (eixo único, marcas finas, grade discreta, hover)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.components.ui import COLORS
from backend.models.schemas import ACTIVITY_LABELS

FONT = "Inter, system-ui, sans-serif"


def _layout(fig: go.Figure, title: str | None = None, height: int = 320, yaxis_title: str | None = None,
            legend: bool = True) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, family=FONT, color="#0b0b0b"), x=0, xanchor="left",
                   y=1, yref="container", yanchor="top", pad=dict(t=14)) if title else None,
        height=height, margin=dict(l=8, r=8, t=74 if (title and legend) else 48 if title else 16, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color="#52514e"),
        hovermode="x unified", showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title=None,
                    font=dict(size=12), traceorder="normal"),
        bargap=0.35, bargroupgap=0.08,
        hoverlabel=dict(bgcolor="#ffffff", bordercolor="#e7e6e2", font=dict(family=FONT, color="#0b0b0b")),
    )
    fig.update_xaxes(showgrid=False, linecolor="#e7e6e2", tickformat="%d/%m", ticks="", zeroline=False)
    fig.update_yaxes(gridcolor="#efeeea", zeroline=False, title=yaxis_title, title_font=dict(size=12),
                     separatethousands=True, tickformat=",.0f")
    fig.update_layout(separators=",.")
    return fig


def empty_figure(message: str, height: int = 260) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=13, color="#8a8984", family=FONT),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _layout(fig, height=height, legend=False)


def intake_vs_expenditure(df: pd.DataFrame) -> go.Figure:
    """1+2: consumo (barras) e gasto estimado (linha) por dia, mesma escala kcal; meta tracejada."""
    if not df["has_food"].any() and df["tdee"].isna().all():
        return empty_figure("Sem dados no período")
    fig = go.Figure()
    fig.add_bar(x=df["date"], y=df["kcal_in"], name="Consumo", marker_color=COLORS["consumo"],
                marker=dict(cornerradius=4), hovertemplate="%{y:,.0f} kcal")
    fig.add_scatter(x=df["date"], y=df["tdee"], name="Gasto estimado", mode="lines+markers",
                    line=dict(color=COLORS["gasto"], width=2), marker=dict(size=7), hovertemplate="%{y:,.0f} kcal")
    if df["goal_kcal"].notna().any():
        fig.add_scatter(x=df["date"], y=df["goal_kcal"], name="Meta", mode="lines",
                        line=dict(color=COLORS["meta"], width=1.5, dash="dot"), hovertemplate="%{y:,.0f} kcal")
    return _layout(fig, "Consumo × gasto energético (kcal/dia)", yaxis_title="kcal")


def balance_bars(df: pd.DataFrame) -> go.Figure:
    """3: saldo diário divergente — azul = déficit, vermelho = superávit."""
    d = df[df["has_food"]]
    if d.empty:
        return empty_figure("Registre refeições para ver o saldo diário")
    colors = [COLORS["deficit"] if b > 0 else COLORS["superavit"] for b in d["balance"]]
    labels = ["Déficit" if b > 0 else "Superávit" for b in d["balance"]]
    fig = go.Figure(go.Bar(x=d["date"], y=d["balance"], marker_color=colors, marker=dict(cornerradius=4),
                           customdata=labels, hovertemplate="%{customdata}: %{y:,.0f} kcal<extra></extra>",
                           name="Saldo"))
    fig.add_hline(y=0, line_color="#c3c2b7", line_width=1)
    fig = _layout(fig, "Saldo energético diário (+ déficit / − superávit)", yaxis_title="kcal", legend=False)
    fig.update_layout(hovermode="closest")
    return fig


def weight_chart(ws: pd.DataFrame, target: float | None = None) -> go.Figure:
    """4: pesagens (pontos) e média móvel de 7 dias (linha)."""
    if ws.empty:
        return empty_figure("Nenhum peso registrado no período")
    fig = go.Figure()
    fig.add_scatter(x=ws["date"], y=ws["weight_kg"], mode="markers", name="Pesagem",
                    marker=dict(size=8, color="#ffffff", line=dict(color=COLORS["peso"], width=2)),
                    hovertemplate="%{y:.1f} kg")
    fig.add_scatter(x=ws["date"], y=ws["ma7"], mode="lines", name="Média móvel 7 dias",
                    line=dict(color=COLORS["peso"], width=2.5, shape="spline", smoothing=0.6), hovertemplate="%{y:.2f} kg")
    if target:
        fig.add_hline(y=target, line_dash="dot", line_color=COLORS["meta"], annotation_text=f"Meta {target:.1f} kg".replace(".", ","),
                      annotation_position="top left", annotation_font_size=11)
    fig = _layout(fig, "Evolução do peso (kg)", yaxis_title="kg")
    fig.update_yaxes(tickformat=",.1f")
    return fig


def protein_chart(df: pd.DataFrame) -> go.Figure:
    """5: proteína diária com meta."""
    d = df[df["has_food"]]
    if d.empty:
        return empty_figure("Sem refeições no período")
    fig = go.Figure()
    fig.add_bar(x=d["date"], y=d["protein_g"], name="Proteína", marker_color=COLORS["proteina"],
                marker=dict(cornerradius=4), hovertemplate="%{y:.0f} g")
    fig.add_scatter(x=d["date"], y=d["goal_protein"], name="Meta", mode="lines",
                    line=dict(color=COLORS["meta"], width=1.5, dash="dot"), hovertemplate="%{y:.0f} g")
    return _layout(fig, "Proteína por dia (g)", yaxis_title="g")


def macro_stack(df: pd.DataFrame) -> go.Figure:
    """6: kcal vindas de cada macronutriente (4/4/9) empilhadas por dia."""
    d = df[df["has_food"]].copy()
    if d.empty:
        return empty_figure("Sem refeições no período")
    fig = go.Figure()
    for col, name, color, factor in (("protein_g", "Proteína", COLORS["proteina"], 4), ("carbs_g", "Carboidratos", COLORS["carbo"], 4),
                                     ("fat_g", "Gorduras", COLORS["gordura"], 9)):
        fig.add_bar(x=d["date"], y=d[col] * factor, name=name, marker_color=color,
                    marker=dict(line=dict(color="#ffffff", width=2)), customdata=d[col],
                    hovertemplate="%{customdata:.0f} g (%{y:,.0f} kcal)")
    fig = _layout(fig, "Macronutrientes por dia (kcal de cada macro)", yaxis_title="kcal")
    fig.update_layout(barmode="stack")
    return fig


def macro_split(protein: float, carbs: float, fat: float) -> go.Figure:
    total = protein * 4 + carbs * 4 + fat * 9
    if total <= 0:
        return empty_figure("Sem refeições", height=230)
    vals = [protein * 4, carbs * 4, fat * 9]
    fig = go.Figure(go.Pie(labels=["Proteína", "Carboidratos", "Gorduras"], values=vals, hole=0.66, sort=False,
                           marker=dict(colors=[COLORS["proteina"], COLORS["carbo"], COLORS["gordura"]],
                                       line=dict(color="#ffffff", width=2)),
                           customdata=[protein, carbs, fat], textinfo="percent",
                           hovertemplate="%{label}: %{customdata:.0f} g · %{value:,.0f} kcal (%{percent})<extra></extra>"))
    fig = _layout(fig, "Distribuição calórica dos macros", height=280)
    fig.update_layout(hovermode="closest", legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center"))
    return fig


def activity_chart(acts: pd.DataFrame, start, end) -> go.Figure:
    """7: minutos de atividade por dia, empilhados por tipo (ordem fixa de cores)."""
    if acts.empty:
        return empty_figure("Nenhuma atividade no período")
    order = ["musculacao", "corrida", "caminhada", "bicicleta_ergometrica", "ciclismo", "natacao", "esportes", "outra"]
    palette = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
    acts = acts.copy()
    acts["date"] = pd.to_datetime(acts["date"])
    fig = go.Figure()
    for t, color in zip(order, palette):
        sub = acts[acts["activity_type"] == t]
        if sub.empty:
            continue
        g = sub.groupby("date").agg(minutes=("duration_min", "sum"), kcal=("kcal_net", "sum")).reset_index()
        fig.add_bar(x=g["date"], y=g["minutes"], name=ACTIVITY_LABELS[t], marker_color=color,
                    marker=dict(line=dict(color="#ffffff", width=2)), customdata=g["kcal"],
                    hovertemplate="%{y:.0f} min · %{customdata:,.0f} kcal líquidas")
    fig = _layout(fig, "Atividades (minutos por dia)", yaxis_title="min")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(range=[pd.Timestamp(start) - pd.Timedelta(hours=12), pd.Timestamp(end) + pd.Timedelta(hours=12)])
    return fig


def weekly_comparison(df: pd.DataFrame) -> go.Figure:
    """8: médias semanais (consumo e gasto), semanas iniciando na segunda-feira."""
    d = df.copy()
    d["semana"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    g = d.groupby("semana").apply(lambda x: pd.Series({
        "consumo": x.loc[x["has_food"], "kcal_in"].mean() if x["has_food"].any() else None,
        "gasto": x["tdee"].mean(),
    }), include_groups=False).reset_index()
    if g["consumo"].isna().all():
        return empty_figure("Sem refeições no período")
    labels = [f"Sem. {s:%d/%m}" for s in g["semana"]]
    fig = go.Figure()
    fig.add_bar(x=labels, y=g["consumo"], name="Consumo médio", marker_color=COLORS["consumo"],
                marker=dict(cornerradius=4), hovertemplate="%{y:,.0f} kcal/dia")
    fig.add_bar(x=labels, y=g["gasto"], name="Gasto médio estimado", marker_color=COLORS["gasto"],
                marker=dict(cornerradius=4), hovertemplate="%{y:,.0f} kcal/dia")
    fig = _layout(fig, "Comparativo semanal (média kcal/dia)", yaxis_title="kcal/dia")
    fig.update_xaxes(type="category", tickformat=None)
    fig.update_layout(barmode="group")
    return fig
