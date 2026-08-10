from __future__ import annotations

import html
from datetime import timedelta

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


STATUS_COLORS = {
    "Non commencé": "#94a3b8",
    "En cours": "#2563eb",
    "Terminé": "#16a34a",
    "En attente": "#f59e0b",
    "Bloqué": "#dc2626",
}


PROJECT_STATUS_COLORS = {
    "Non commencé": "#9ca3af",
    "En cours": "#38bdf8",
    "Terminé": "#86efac",
    "Archivé": "#c4b5fd",
    "En attente": "#fde68a",
}

GANTT_ROW_HEIGHT_PX = 30
GANTT_VERTICAL_CHROME_PX = 105


def task_level_label(label: object, level: object) -> str:
    escaped = html.escape(str(label or ""))
    try:
        level_num = int(level)
    except (TypeError, ValueError):
        level_num = 0
    if level_num == 1:
        return f"<b><u>{escaped}</u></b>"
    if level_num == 2:
        return escaped
    if level_num == 3:
        return f"<i>{escaped}</i>"
    if level_num == 4:
        return f"<span style='font-size:12px'><i>{escaped}</i></span>"
    return escaped


def task_level_annotation(label: object, level: object) -> str:
    escaped = html.escape(str(label or ""))
    try:
        level_num = int(level)
    except (TypeError, ValueError):
        level_num = 0
    if level_num == 1:
        return f"<b><u>{escaped}</u></b>"
    if level_num == 3:
        return f"<i>{escaped}</i>"
    if level_num == 4:
        return f"<span style='font-size:12px'><i>{escaped}</i></span>"
    return escaped


def empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=20))
    return fig


def projects_gantt(projects: pd.DataFrame, color_field: str = "Budget") -> go.Figure:
    if projects.empty:
        return empty_figure("Aucun projet à afficher")
    df = projects.dropna(subset=["Début", "Fin"]).copy()
    if df.empty:
        return empty_figure("Renseignez les dates de début et fin pour afficher le Gantt projets")
    df["Fin affichée"] = pd.to_datetime(df["Fin"]) + pd.to_timedelta(1, unit="D")
    df["Début"] = pd.to_datetime(df["Début"])
    df["Libellé"] = df["Code"].astype(str) + " - " + df["Projet"].astype(str)
    if color_field not in df.columns:
        color_field = "Budget" if "Budget" in df.columns else "Statut"
    if color_field in df.columns and color_field != "Statut":
        df[color_field] = pd.to_numeric(df[color_field], errors="coerce").fillna(0)
        color_args = {
            "color": color_field,
            "color_continuous_scale": ["#dbeafe", "#99f6e4", "#fde68a", "#f9a8d4"],
        }
    else:
        color_args = {"color": "Statut", "color_discrete_map": PROJECT_STATUS_COLORS}
    fig = px.timeline(
        df,
        x_start="Début",
        x_end="Fin affichée",
        y="Libellé",
        **color_args,
        hover_data=["Responsable", "Priorité", "Budget", "Budget heures"],
    )
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(
        title="",
        showgrid=True,
        type="date",
        rangeselector=dict(
            buttons=[
                dict(count=7, label="1w", step="day", stepmode="backward"),
                dict(count=1, label="1m", step="month", stepmode="backward"),
                dict(count=6, label="6m", step="month", stepmode="backward"),
                dict(count=1, label="YTD", step="year", stepmode="todate"),
                dict(count=1, label="1y", step="year", stepmode="backward"),
                dict(label="all", step="all"),
            ],
            bgcolor="#eef2f7",
            activecolor="#dbeafe",
            bordercolor="#cbd5e1",
            borderwidth=1,
            font=dict(size=11, color="#1f2937"),
            x=0,
            y=1.12,
        ),
        rangeslider=dict(visible=True, thickness=0.08),
    )
    fig.update_layout(
        height=max(170, min(760, GANTT_VERTICAL_CHROME_PX + len(df) * GANTT_ROW_HEIGHT_PX)),
        margin=dict(l=12, r=12, t=70, b=20),
        legend_title_text=color_field,
        coloraxis_colorbar=dict(title=color_field),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        bargap=0.28,
    )
    return fig


def gantt_figure(tasks: pd.DataFrame, color_field: str = "Temps prévu") -> go.Figure:
    if tasks.empty:
        return empty_figure("Aucune tâche à afficher")
    df = tasks.dropna(subset=["Début", "Fin estimée"]).copy()
    if df.empty:
        return empty_figure("Renseignez les dates de début et fin pour afficher le Gantt")
    df["Fin affichée"] = pd.to_datetime(df["Fin estimée"]) + pd.to_timedelta(1, unit="D")
    df["Début"] = pd.to_datetime(df["Début"])
    df["Progression"] = df["Avancement"].astype(str) + "%"
    df["Ligne Gantt"] = range(len(df))
    df["Libellé Gantt"] = df.apply(lambda row: task_level_annotation(row.get("Libellé"), row.get("Niveau")), axis=1)
    if color_field not in df.columns:
        color_field = "Temps prévu" if "Temps prévu" in df.columns else "Statut"
    if color_field in df.columns and color_field != "Statut":
        df[color_field] = pd.to_numeric(df[color_field], errors="coerce").fillna(0)
        color_args = {
            "color": color_field,
            "color_continuous_scale": ["#e0f2fe", "#bbf7d0", "#fde68a", "#fecdd3"],
        }
    else:
        color_args = {"color": "Statut", "color_discrete_map": STATUS_COLORS}
    hover_columns = [
        column
        for column in [
            "Référence",
            "Ressources",
            "Budget",
            "Mode calcul",
            "Temps prévu",
            "Temps passé",
            "Coût prévu",
            "Coût réel total",
            "Progression",
        ]
        if column in df.columns
    ]
    fig = px.timeline(
        df,
        x_start="Début",
        x_end="Fin affichée",
        y="Ligne Gantt",
        **color_args,
        hover_name="Libellé",
        hover_data={column: True for column in hover_columns},
    )
    fig.update_yaxes(
        range=[len(df) - 0.5, -0.5],
        title="",
        showticklabels=False,
        ticks="",
        showgrid=False,
        zeroline=False,
    )
    fig.update_xaxes(
        title="",
        showgrid=True,
        type="date",
        rangeselector=dict(
            buttons=[
                dict(count=7, label="1w", step="day", stepmode="backward"),
                dict(count=1, label="1m", step="month", stepmode="backward"),
                dict(count=6, label="6m", step="month", stepmode="backward"),
                dict(count=1, label="YTD", step="year", stepmode="todate"),
                dict(count=1, label="1y", step="year", stepmode="backward"),
                dict(label="all", step="all"),
            ],
            bgcolor="#eef2f7",
            activecolor="#dbeafe",
            bordercolor="#cbd5e1",
            borderwidth=1,
            font=dict(size=11, color="#1f2937"),
            x=0,
            y=1.12,
        ),
        rangeslider=dict(visible=True, thickness=0.08),
        domain=[0.28, 1],
    )
    for row in df.to_dict("records"):
        fig.add_annotation(
            xref="paper",
            x=0.01,
            xanchor="left",
            yref="y",
            y=row["Ligne Gantt"],
            text=row["Libellé Gantt"],
            showarrow=False,
            align="left",
            font=dict(size=13, color="#111827"),
        )
        try:
            level = int(row.get("Niveau") or 0)
        except (TypeError, ValueError):
            level = 0
        if level == 1:
            fig.add_shape(
                type="line",
                xref="paper",
                x0=0,
                x1=1,
                yref="y",
                y0=row["Ligne Gantt"] - 0.5,
                y1=row["Ligne Gantt"] - 0.5,
                line=dict(color="#d1d5db", width=0.6),
                layer="below",
            )
    fig.update_layout(
        height=max(170, min(820, GANTT_VERTICAL_CHROME_PX + len(df) * GANTT_ROW_HEIGHT_PX)),
        margin=dict(l=20, r=20, t=70, b=20),
        legend_title_text=color_field,
        coloraxis_colorbar=dict(title=color_field),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        bargap=0.28,
    )
    return fig


def tasks_status_pie(tasks: pd.DataFrame) -> go.Figure:
    if tasks.empty:
        return empty_figure("Aucune tâche")
    counts = tasks.groupby("Statut", as_index=False).size()
    return px.pie(counts, names="Statut", values="size", hole=0.48, color="Statut", color_discrete_map=STATUS_COLORS)


def legacy_budget_pie(budget: pd.DataFrame) -> go.Figure:
    if budget.empty:
        return empty_figure("Aucune ligne budgétaire")
    grouped = budget.groupby("Catégorie", as_index=False)["Prévu"].sum()
    return px.pie(grouped, names="Catégorie", values="Prévu", hole=0.42)


def legacy_budget_bar(budget: pd.DataFrame) -> go.Figure:
    if budget.empty:
        return empty_figure("Aucune ligne budgétaire")
    grouped = budget.groupby("Catégorie", as_index=False)[["Prévu", "Engagé", "Réel"]].sum()
    fig = px.bar(grouped, x="Catégorie", y=["Prévu", "Engagé", "Réel"], barmode="group")
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=25, b=20), legend_title_text="")
    return fig


def budget_pie(budget: pd.DataFrame) -> go.Figure:
    if budget.empty:
        return empty_figure("Aucun budget")
    label_col = "Budget" if "Budget" in budget.columns else "Catégorie"
    grouped = budget.groupby(label_col, as_index=False)["Prévu"].sum()
    return px.pie(grouped, names=label_col, values="Prévu", hole=0.42)


def budget_bar(budget: pd.DataFrame) -> go.Figure:
    if budget.empty:
        return empty_figure("Aucun budget")
    label_col = "Budget" if "Budget" in budget.columns else "Catégorie"
    value_cols = [column for column in ["Prévu", "Engagé", "Reste"] if column in budget.columns]
    grouped = budget.groupby(label_col, as_index=False)[value_cols].sum()
    fig = px.bar(grouped, x=label_col, y=value_cols, barmode="group")
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=25, b=20), legend_title_text="")
    return fig


def hours_by_user_bar(time_entries: pd.DataFrame) -> go.Figure:
    if time_entries.empty:
        return empty_figure("Aucune saisie de temps")
    grouped = time_entries.groupby("Utilisateur", as_index=False)["Heures"].sum().sort_values("Heures", ascending=False)
    fig = px.bar(grouped, x="Utilisateur", y="Heures", color="Utilisateur")
    fig.update_layout(height=320, showlegend=False, margin=dict(l=20, r=20, t=25, b=20))
    return fig


def starcost_hours_month_bar(data: pd.DataFrame) -> go.Figure:
    if data.empty:
        return empty_figure("Aucune heure STARCOST")
    fig = px.bar(data, x="Mois", y="Heures STARCOST", text_auto=".1f")
    fig.update_traces(marker_color="#0f766e", textposition="outside", cliponaxis=False)
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=25, b=20), showlegend=False)
    return fig


def workload_bar(tasks: pd.DataFrame) -> go.Figure:
    if tasks.empty:
        return empty_figure("Aucune charge")
    if "Mode calcul" in tasks.columns:
        tasks = tasks[tasks["Mode calcul"] == "Direct"].copy()
        if tasks.empty:
            return empty_figure("Aucune tâche de détail")
    grouped = tasks.groupby("Ressources", as_index=False)[["Temps prévu", "Temps passé"]].sum()
    grouped = grouped[grouped["Ressources"].astype(str).str.len() > 0]
    if grouped.empty:
        return empty_figure("Aucune ressource affectée")
    fig = px.bar(grouped, x="Ressources", y=["Temps prévu", "Temps passé"], barmode="group")
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=25, b=20), legend_title_text="")
    return fig


def critical_path(tasks: pd.DataFrame, dependencies: pd.DataFrame) -> list[str]:
    if tasks.empty or dependencies.empty:
        return []
    durations = {}
    refs = {}
    for row in tasks.to_dict("records"):
        task_id = row["ID"]
        start = row.get("Début")
        end = row.get("Fin estimée")
        if pd.isna(start) or pd.isna(end):
            duration = max(float(row.get("Temps prévu", 1)), 1)
        else:
            duration = max((pd.to_datetime(end) - pd.to_datetime(start)).days + 1, 1)
        durations[task_id] = duration
        refs[task_id] = row["Référence"]
    graph = nx.DiGraph()
    graph.add_nodes_from(durations)
    for dep in dependencies.to_dict("records"):
        pred = dep["Prédécesseur ID"]
        succ = dep["Successeur ID"]
        if pred in durations and succ in durations:
            graph.add_edge(pred, succ, weight=durations[pred])
    if not nx.is_directed_acyclic_graph(graph):
        return ["Cycle de dépendances détecté"]
    path = nx.dag_longest_path(graph, weight="weight")
    return [refs[node] for node in path]
