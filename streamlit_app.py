from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from babel.numbers import format_currency
try:
    from PIL import Image
except ImportError:  # pragma: no cover - Streamlit installe normalement Pillow.
    Image = None
from st_aggrid import AgGrid, DataReturnMode, JsCode
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from perspectiv.audit import record_audit
from perspectiv.charts import (
    budget_bar,
    budget_pie,
    critical_path,
    gantt_figure,
    hours_by_user_bar,
    projects_gantt,
    starcost_hours_month_bar,
    tasks_status_pie,
    workload_bar,
)
from perspectiv.database import init_db, session_scope
from perspectiv.models import Risk, RiskAssessment, RiskIteration, User
from perspectiv.reports import build_project_pdf
from perspectiv.settings import OIDC_ISSUER
from perspectiv.services import (
    add_assignment,
    add_budget,
    add_budget_line,
    add_dependency,
    add_time_entry,
    authenticate,
    assignments_df,
    budget_options,
    budget_df,
    budget_lines_df,
    create_project,
    create_task,
    create_user,
    delete_record,
    deletion_preview,
    dependencies_df,
    direct_task_options,
    ensure_support_project,
    ensure_user_project,
    get_grid_visible_columns,
    get_project,
    kpis,
    monthly_completion_df,
    planned_time_entries_df,
    project_options,
    projects_df,
    create_risk,
    create_risk_assessment,
    create_risk_iteration,
    decide_risk_acceptance,
    risk_assessments_df,
    risk_iterations_df,
    risk_kpis,
    risk_matrix_paths,
    risks_df,
    RISK_CONSEQUENCE_DEFINITIONS,
    RISK_LIFECYCLE_PHASES,
    RISK_LIKELIHOOD_DEFINITIONS,
    RISK_MATRIX,
    set_risk_assessment_status,
    starcost_hours_by_month_df,
    task_options,
    tasks_df,
    time_entries_df,
    save_weekly_planning,
    save_weekly_timesheet,
    save_grid_visible_columns,
    update_budget_from_df,
    update_budget_lines_from_df,
    update_projects_from_df,
    update_risk,
    update_risk_assessment,
    update_planned_time_entries_from_df,
    update_tasks_from_df,
    update_time_entries_from_df,
    update_task_budget_and_expense,
    update_users_from_df,
    user_name_options,
    user_options,
    verify_risk_iteration,
    week_day_columns,
    week_start,
    weekly_planning_df,
    weekly_timesheet_df,
    users_df,
)


APP_DIR = Path(__file__).resolve().parent
ASSET_DIR = APP_DIR / "assets"
ICON_PATH = ASSET_DIR / "perspectiv_icon.png"
LOGO_PATH = ASSET_DIR / "perspectiv_logo.png"
LOGIN_PANEL_PATH = ASSET_DIR / "perspectiv_login_panel.png"
HERO_PATH = ASSET_DIR / "perspectiv_hero.png"


def page_icon() -> object:
    if Image is not None and ICON_PATH.exists():
        return Image.open(ICON_PATH)
    return "P"


st.set_page_config(page_title="PerspectiV", page_icon=page_icon(), layout="wide")
init_db()
with session_scope() as session:
    ensure_support_project(session)


PAGES = [
    "Tableau de bord",
    "Projets",
    "Tâches et Gantt",
    "Timesheet",
    "Planification",
    "Budget",
    "Gestion des risques",
    "Rapports PDF",
    "Utilisateurs",
]

PAGE_ICONS = {
    "Tableau de bord": ":material/dashboard:",
    "Projets": ":material/folder_open:",
    "Tâches et Gantt": ":material/account_tree:",
    "Timesheet": ":material/schedule:",
    "Planification": ":material/event_available:",
    "Budget": ":material/account_balance_wallet:",
    "Gestion des risques": ":material/health_and_safety:",
    "Rapports PDF": ":material/picture_as_pdf:",
    "Utilisateurs": ":material/group:",
}

LEVEL_COLORS = {
    1: "#f3f4f6",
    2: "#fff8d6",
    3: "#e0f2fe",
    4: "#ffffff",
}

LEVEL_TEXT_STYLES = {
    1: "font-weight: 700; text-decoration: underline;",
    2: "",
    3: "font-style: italic;",
    4: "font-style: italic; font-size: 12px;",
}

DAY_INITIALS = ["L", "M", "M", "J", "V", "S", "D"]
TODAY_COLUMN_COLOR = "#ffedd5"
TODAY_COLUMN_STRONG_COLOR = "#fed7aa"
TODAY_COLUMN_TEXT = "#9a3412"
TODAY_COLUMN_BORDER = "#fdba74"
TODAY_AGGRID_CSS = {
    ".pv-center-cell": {
        "display": "flex !important",
        "align-items": "center !important",
        "justify-content": "center !important",
        "text-align": "center !important",
    },
    ".pv-left-cell": {
        "display": "flex !important",
        "align-items": "center !important",
        "justify-content": "flex-start !important",
        "text-align": "left !important",
    },
    ".pv-center-cell .ag-cell-wrapper": {
        "justify-content": "center !important",
        "width": "100% !important",
    },
    ".pv-left-cell .ag-cell-wrapper": {
        "justify-content": "flex-start !important",
        "width": "100% !important",
    },
    ".pv-center-header .ag-header-cell-label": {
        "justify-content": "center !important",
        "text-align": "center !important",
        "width": "100% !important",
    },
    ".pv-left-header .ag-header-cell-label": {
        "justify-content": "flex-start !important",
        "text-align": "left !important",
        "width": "100% !important",
    },
    ".today-column-header": {
        "background-color": f"{TODAY_COLUMN_COLOR} !important",
        "border-left": f"1px solid {TODAY_COLUMN_BORDER} !important",
        "border-right": f"1px solid {TODAY_COLUMN_BORDER} !important",
        "font-weight": "700 !important",
    },
    ".today-column-header .ag-header-cell-label": {
        "color": f"{TODAY_COLUMN_TEXT} !important",
        "justify-content": "center",
    },
    ".vertical-day-header": {
        "align-items": "center !important",
        "justify-content": "center !important",
        "padding": "2px 0 !important",
    },
    ".vertical-day-header .ag-header-cell-label": {
        "align-items": "center !important",
        "justify-content": "center !important",
        "height": "100% !important",
        "line-height": "1.05 !important",
        "writing-mode": "vertical-rl",
        "transform": "rotate(180deg)",
        "white-space": "nowrap",
    },
    ".vertical-day-header .ag-header-cell-text": {
        "overflow": "visible !important",
        "text-overflow": "clip !important",
    },
    ".week-group-header .ag-header-group-cell-label": {
        "justify-content": "center",
        "font-weight": "700",
    },
    ".week-day-header .ag-header-cell-label": {
        "justify-content": "center",
    },
    ".weekend-column-header": {
        "background-color": "#eef0f3 !important",
    },
    ".weekend-column-header .ag-header-cell-label": {
        "color": "#374151 !important",
        "justify-content": "center",
    },
}

TASK_DISPLAY_COLUMNS = [
    "Libellé",
    "Niveau",
    "Enfants",
    "Mode calcul",
    "STARCOST",
    "Statut",
    "Début",
    "Fin estimée",
    "Date de clôture",
    "Temps prévu",
    "Temps passé",
    "Temps planifié",
    "Coût prévu",
    "Dépense directe",
    "Coût réel total",
    "Avancement",
    "Budget",
    "Ressources",
]


def eur(value: float) -> str:
    return format_currency(value or 0, "EUR", locale="fr_FR")


def level_color(level: object) -> str:
    try:
        return LEVEL_COLORS.get(int(level), "#ffffff")
    except (TypeError, ValueError):
        return "#ffffff"


def level_text_style(level: object) -> str:
    try:
        return LEVEL_TEXT_STYLES.get(int(level), "")
    except (TypeError, ValueError):
        return ""


LEFT_ALIGNED_TABLE_COLUMNS = {
    "Projet",
    "Tâche",
    "Libellé",
    "Titre",
    "Prédécesseur",
    "Successeur",
}


def styled_plain_table(data: pd.DataFrame):
    left_columns = [column for column in data.columns if column in LEFT_ALIGNED_TABLE_COLUMNS]
    styler = data.style.set_properties(
        **{
            "text-align": "center",
            "vertical-align": "middle",
        }
    )
    if left_columns:
        styler = styler.set_properties(
            subset=left_columns,
            **{
                "text-align": "left",
                "vertical-align": "middle",
            },
        )
    return styler.set_table_styles(
        [
            {"selector": "th", "props": [("text-align", "center"), ("vertical-align", "middle")]},
            {"selector": "td", "props": [("vertical-align", "middle")]},
        ]
    )


def styled_task_table(data: pd.DataFrame, visible_columns: list[str] | None = None):
    allowed_columns = set(visible_columns) if visible_columns is not None else None
    columns = [
        column
        for column in TASK_DISPLAY_COLUMNS
        if column in data.columns and (allowed_columns is None or column in allowed_columns)
    ]
    display = data[columns].copy()
    source_levels = data["Niveau"] if "Niveau" in data.columns else None

    def row_style(row: pd.Series) -> list[str]:
        level_value = source_levels.loc[row.name] if source_levels is not None and row.name in source_levels.index else row.get("Niveau")
        color = level_color(level_value)
        text_style = level_text_style(level_value)
        try:
            level = int(level_value or 0)
        except (TypeError, ValueError):
            level = 0
        separator = "border-top: 1px solid #d1d5db;" if level == 1 else ""
        return [
            f"background-color: {color}; color: #111827; font-size: 13px; {separator} {text_style}"
            for _ in row
        ]

    number_columns = [
        "Temps prévu",
        "Temps passé",
        "Temps planifié",
        "Coût prévu",
        "Dépense directe",
        "Coût réel total",
        "Avancement",
    ]
    formatters = {column: "{:.1f}" for column in number_columns if column in display.columns}
    styler = (
        display.style.apply(row_style, axis=1)
        .set_properties(**{"text-align": "center", "vertical-align": "middle"})
        .set_properties(
            subset=[column for column in ["Libellé", "Titre", "Projet", "Tâche"] if column in display.columns],
            **{"text-align": "left", "vertical-align": "middle"},
        )
        .set_table_styles(
            [
                {"selector": "th", "props": [("text-align", "center"), ("vertical-align", "middle")]},
                {"selector": "td", "props": [("vertical-align", "middle")]},
            ]
        )
    )
    return styler.format(formatters, na_rep="")


def task_level_legend() -> None:
    labels = {
        1: "Niveau 1",
        2: "Niveau 2",
        3: "Niveau 3",
        4: "Niveau 4",
    }
    legend = "".join(
        f"<span style='display:inline-flex;align-items:center;gap:6px;margin-right:14px;"
        f"background:{LEVEL_COLORS[level]};border:1px solid #d8dee8;border-radius:4px;"
        f"padding:2px 8px;color:#111827;font-size:13px;{LEVEL_TEXT_STYLES.get(level, '')}'>"
        f"{label}</span>"
        for level, label in labels.items()
    )
    st.markdown(legend, unsafe_allow_html=True)


def task_label(row: dict) -> str:
    return f"{row.get('Référence', '')} - {row.get('Titre', '')}".strip()


def project_label_for_id(options: dict[str, int], project_id: int | None) -> str | None:
    if not project_id:
        return None
    return next((label for label, option_id in options.items() if option_id == project_id), None)


def navigate_to_project_tasks(project_id: int) -> None:
    st.session_state["selected_project_id"] = project_id
    st.session_state["force_project_selector"] = True
    st.session_state["navigate_to_page"] = "Tâches et Gantt"


def aggrid_data(response: object, fallback: pd.DataFrame) -> pd.DataFrame:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if isinstance(data, pd.DataFrame):
        return data
    if isinstance(data, list):
        return pd.DataFrame(data)
    return fallback


TECHNICAL_GRID_COLUMNS = {"ID", "Projet ID", "Tâche ID", "Budget ID", "_time_editable"}


def ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def grid_column_visibility_selector(
    grid_key: str,
    columns: list[str],
    *,
    required_columns: list[str] | None = None,
    default_columns: list[str] | None = None,
    technical_columns: set[str] | None = None,
    column_labels: dict[str, str] | None = None,
) -> list[str]:
    labels = column_labels or {}
    all_columns = ordered_unique([column for column in columns if column])
    technical = technical_columns or TECHNICAL_GRID_COLUMNS
    valid_columns = [column for column in all_columns if column not in technical]
    required = [column for column in ordered_unique(required_columns or []) if column in valid_columns]
    default_visible = [
        column
        for column in (default_columns or valid_columns)
        if column in valid_columns
    ]
    if not default_visible:
        default_visible = valid_columns
    default_visible = [column for column in valid_columns if column in set(required + default_visible)]
    selectable_columns = [column for column in valid_columns if column not in set(required)]
    if not selectable_columns:
        return [column for column in valid_columns if column in set(required or default_visible)]

    user_id = int(st.session_state["user"]["id"])
    with session_scope() as session:
        stored_visible = get_grid_visible_columns(session, user_id, grid_key, default_visible, valid_columns)
    stored_set = set(required + stored_visible)
    selected_defaults = [column for column in selectable_columns if column in stored_set]
    widget_key = f"{grid_key}_visible_columns"
    selector_col, reset_col = st.columns([5, 1], vertical_alignment="bottom")
    if reset_col.button("Réinitialiser", key=f"{grid_key}_reset_columns", use_container_width=True):
        with session_scope() as session:
            save_grid_visible_columns(session, user_id, grid_key, default_visible)
        st.session_state.pop(widget_key, None)
        st.rerun()
    if widget_key not in st.session_state:
        st.session_state[widget_key] = selected_defaults
    else:
        st.session_state[widget_key] = [
            column for column in st.session_state[widget_key] if column in selectable_columns
        ]
    selected_optional = selector_col.multiselect(
        "Colonnes affichées",
        selectable_columns,
        key=widget_key,
        format_func=lambda column: labels.get(column, column),
    )
    required_labels = ", ".join(labels.get(column, column) for column in required)
    if required_labels:
        selector_col.caption(f"Toujours visibles : {required_labels}")
    selected_set = set(required + selected_optional)
    visible_columns = [column for column in valid_columns if column in selected_set]
    if set(visible_columns) != set(stored_visible):
        with session_scope() as session:
            save_grid_visible_columns(session, user_id, grid_key, visible_columns)
    return visible_columns


def apply_aggrid_column_visibility(
    column_defs: list[dict],
    visible_columns: list[str],
    *,
    required_columns: list[str] | None = None,
    technical_columns: set[str] | None = None,
) -> list[dict]:
    visible_set = set(visible_columns) | set(required_columns or [])
    technical = technical_columns or TECHNICAL_GRID_COLUMNS
    updated_defs = []
    for column_def in column_defs:
        updated = dict(column_def)
        field = updated.get("field")
        if field:
            if field in technical or field not in visible_set:
                updated["hide"] = True
            else:
                updated.pop("hide", None)
        updated_defs.append(updated)
    return updated_defs


def visible_columns_for_editor(data: pd.DataFrame, visible_columns: list[str]) -> list[str]:
    visible_set = set(visible_columns)
    return [column for column in data.columns if column in visible_set]


def compact_grid_height(
    row_count: int,
    row_height: int,
    header_height: int,
    *,
    group_header_height: int = 0,
    pinned_bottom_height: int = 0,
    extra: int = 18,
    min_height: int = 112,
    max_height: int = 720,
) -> int:
    rows = max(int(row_count or 0), 1)
    height = group_header_height + header_height + pinned_bottom_height + rows * row_height + extra
    return max(min_height, min(max_height, height))


def aggrid_event_data(response: object) -> dict:
    grid_response = getattr(response, "grid_response", None)
    if not isinstance(grid_response, dict) and isinstance(response, dict):
        grid_response = response
    if not isinstance(grid_response, dict):
        return {}
    event_data = grid_response.get("eventData") or getattr(response, "event_data", None) or {}
    return event_data if isinstance(event_data, dict) else {}


def aggrid_event_name(response: object) -> str:
    grid_response = getattr(response, "grid_response", None)
    if not isinstance(grid_response, dict) and isinstance(response, dict):
        grid_response = response
    event_data = aggrid_event_data(response)
    for source in (event_data, grid_response if isinstance(grid_response, dict) else {}):
        for key in ("type", "eventType", "streamlitRerunEventTriggerName", "name"):
            value = source.get(key)
            if value:
                return str(value)
    return ""


def double_clicked_project_id(response: object) -> int | None:
    if aggrid_event_name(response) != "rowDoubleClicked":
        return None
    event_data = aggrid_event_data(response)
    row_data = event_data.get("data")
    if not isinstance(row_data, dict):
        node = event_data.get("node")
        row_data = node.get("data") if isinstance(node, dict) else None
    if not isinstance(row_data, dict):
        selected = getattr(response, "selected_rows", None)
        if isinstance(selected, pd.DataFrame) and not selected.empty:
            row_data = selected.iloc[0].to_dict()
    try:
        return int(row_data["ID"]) if row_data and row_data.get("ID") else None
    except (TypeError, ValueError):
        return None


def parse_date(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def row_delete_label(row: dict, columns: list[str]) -> str:
    parts = []
    for column in columns:
        value = row.get(column)
        if value is not None and str(value).strip():
            parts.append(str(value).strip())
    label = " - ".join(parts) if parts else "Enregistrement"
    return f"{label} (ID {row.get('ID')})"


def top_right_save_button(key: str, button_type: str = "primary") -> bool:
    _, button_col = st.columns([5, 1], vertical_alignment="bottom")
    return button_col.button("Enregistrer", type=button_type, key=key, use_container_width=True)


def sticky_header_title(title: str) -> None:
    st.markdown(f'<div class="pv-sticky-title">{title}</div>', unsafe_allow_html=True)


def sticky_page_header(key: str, title: str | None = None):
    container = st.container(key=f"pv_sticky_header_{key}")
    if title:
        with container:
            sticky_header_title(title)
    st.markdown(
        f'<div class="pv-sticky-spacer pv-sticky-header-spacer pv-sticky-header-spacer-{key}"></div>',
        unsafe_allow_html=True,
    )
    return container


def sticky_toolbar(key: str):
    container = st.container(key=f"pv_sticky_toolbar_{key}")
    st.markdown(
        f'<div class="pv-sticky-spacer pv-sticky-toolbar-spacer pv-sticky-toolbar-spacer-{key}"></div>',
        unsafe_allow_html=True,
    )
    return container


def sticky_tabs(key: str, labels: list[str]):
    with st.container(key=f"pv_sticky_tabs_{key}"):
        return st.tabs(labels)


def delete_record_control(
    entity: str,
    data: pd.DataFrame,
    label_columns: list[str],
    key: str,
    protected_ids: set[int] | None = None,
    protected_message: str | None = None,
) -> None:
    if data.empty or "ID" not in data.columns:
        return
    protected_ids = protected_ids or set()
    rows = data.to_dict("records")
    options = {row_delete_label(row, label_columns): int(row["ID"]) for row in rows if row.get("ID")}
    if not options:
        return

    st.caption("Suppression")
    c1, c2 = st.columns([4, 1])
    selected_label = c1.selectbox("Ligne à supprimer", list(options.keys()), key=f"{key}_delete_select")
    selected_id = options[selected_label]
    is_protected = selected_id in protected_ids
    if is_protected:
        c1.info(protected_message or "Cette ligne ne peut pas être supprimée.")
    if c2.button("Supprimer", key=f"{key}_delete_prepare", disabled=is_protected):
        st.session_state[f"{key}_pending_delete"] = selected_id

    pending_id = st.session_state.get(f"{key}_pending_delete")
    if not pending_id:
        return

    try:
        with session_scope() as session:
            preview = deletion_preview(session, entity, int(pending_id))
    except Exception as exc:
        st.error(str(exc))
        st.session_state.pop(f"{key}_pending_delete", None)
        return

    st.warning(f"Vous allez supprimer : {preview['label']}")
    st.markdown("Les enregistrements liés suivants seront également impactés :")
    st.markdown("\n".join(f"- {impact}" for impact in preview["impacts"]))
    confirm = st.checkbox("Je confirme la suppression définitive.", key=f"{key}_delete_confirm")
    c3, c4 = st.columns([1, 1])
    if c3.button("Confirmer la suppression", type="primary", disabled=not confirm, key=f"{key}_delete_confirm_button"):
        try:
            with session_scope() as session:
                delete_record(session, entity, int(pending_id))
                record_audit(
                    session,
                    actor_user_id=int(st.session_state["user"]["id"]),
                    source="ui",
                    action="delete",
                    entity_type=entity,
                    entity_id=int(pending_id),
                )
            st.session_state.pop(f"{key}_pending_delete", None)
            st.success("Suppression effectuée.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if c4.button("Annuler", key=f"{key}_delete_cancel"):
        st.session_state.pop(f"{key}_pending_delete", None)
        st.rerun()


def project_grid_data(data: pd.DataFrame) -> pd.DataFrame:
    grid_data = data.copy()

    def iso_date(value: object) -> str:
        parsed = parse_date(value)
        return parsed.isoformat() if parsed else ""

    for column in ["Début", "Fin"]:
        grid_data[column] = grid_data[column].apply(iso_date)
    return grid_data


def project_grid(data: pd.DataFrame, user_names: dict[str, int], key: str = "projects_grid"):
    grid_data = project_grid_data(data)
    technical_columns = {"ID"}
    column_defs = [
        {"field": "ID", "hide": True, "editable": False},
        {"field": "Code", "pinned": "left", "editable": True, "width": 110},
        {
            "field": "Projet",
            "pinned": "left",
            "editable": True,
            "width": 240,
            "cellClass": "pv-left-cell",
            "headerClass": "pv-left-header",
        },
        {
            "field": "Responsable",
            "editable": True,
            "width": 180,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": [""] + list(user_names.keys())},
        },
        {"field": "Catégorie", "editable": True, "width": 150},
        {
            "field": "Statut",
            "editable": True,
            "width": 140,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": ["Non commencé", "En cours", "En attente", "Terminé", "Archivé"]},
        },
        {
            "field": "Priorité",
            "editable": True,
            "width": 120,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": ["Basse", "Normale", "Haute", "Critique"]},
        },
        {"field": "Début", "editable": True, "width": 120},
        {"field": "Fin", "editable": True, "width": 120},
        {"field": "Budget", "editable": True, "type": "numericColumn", "width": 120},
        {"field": "Budget heures", "editable": True, "type": "numericColumn", "width": 145},
        {"field": "Description", "editable": True, "width": 220},
    ]
    visible_columns = grid_column_visibility_selector(
        "projects_grid",
        [column["field"] for column in column_defs if column.get("field")],
        required_columns=["Code", "Projet"],
        technical_columns=technical_columns,
    )
    column_defs = apply_aggrid_column_visibility(
        column_defs,
        visible_columns,
        required_columns=["Code", "Projet"],
        technical_columns=technical_columns,
    )
    grid_options = {
        "columnDefs": column_defs,
        "defaultColDef": {
            "editable": True,
            "filter": True,
            "sortable": True,
            "resizable": True,
            "minWidth": 95,
            "cellClass": "pv-center-cell",
            "headerClass": "pv-center-header",
        },
        "rowSelection": "single",
        "suppressRowDeselection": True,
        "stopEditingWhenCellsLoseFocus": True,
        "singleClickEdit": False,
        "animateRows": False,
        "rowHeight": 42,
        "headerHeight": 32,
        "suppressMovableColumns": False,
    }
    return AgGrid(
        grid_data,
        gridOptions=grid_options,
        height=compact_grid_height(len(grid_data), row_height=42, header_height=32, min_height=136, max_height=560),
        data_return_mode=DataReturnMode.AS_INPUT,
        update_on=["cellValueChanged", "rowDoubleClicked"],
        allow_unsafe_jscode=True,
        theme="streamlit",
        show_toolbar=True,
        show_search=True,
        show_download_button=False,
        custom_css=TODAY_AGGRID_CSS,
        key=key,
    )


def task_color_options(task_data: pd.DataFrame) -> list[str]:
    candidates = [
        "Temps prévu",
        "Temps passé",
        "Temps planifié",
        "Coût prévu",
        "Coût temps réel",
        "Dépense directe",
        "Coût réel total",
        "Avancement",
        "Niveau",
        "Enfants",
    ]
    return [column for column in candidates if column in task_data.columns]


def task_grid_data(data: pd.DataFrame) -> pd.DataFrame:
    grid_data = data.copy()

    def iso_date(value: object) -> str:
        parsed = parse_date(value)
        return parsed.isoformat() if parsed else ""

    for column in ["Début", "Fin estimée", "Date de clôture"]:
        if column in grid_data.columns:
            grid_data[column] = grid_data[column].apply(iso_date)
    if "STARCOST" in grid_data.columns:
        grid_data["STARCOST"] = grid_data["STARCOST"].fillna(False).astype(bool)
    return grid_data


def task_editor(
    task_data: pd.DataFrame,
    task_labels: dict[str, int],
    budget_labels: dict[str, int],
    project_id: int,
) -> pd.DataFrame:
    st.caption("Les lignes en Mode calcul = Agrégé sont recalculées depuis leurs sous-tâches à l'enregistrement.")
    task_level_legend()
    grid_data = task_grid_data(task_data)
    row_style = JsCode(
        """
        function(params) {
            const level = Number(params.data.Niveau || 0);
            const base = {fontSize: '13px', color: '#111827'};
            if (level === 1) {
                return {...base, backgroundColor: '#f3f4f6', fontWeight: '700', textDecoration: 'underline', borderTop: '1px solid #d1d5db'};
            }
            if (level === 2) {
                return {...base, backgroundColor: '#fff8d6'};
            }
            if (level === 3) {
                return {...base, backgroundColor: '#e0f2fe', fontStyle: 'italic'};
            }
            if (level === 4) {
                return {...base, backgroundColor: '#ffffff', fontStyle: 'italic', fontSize: '12px'};
            }
            return base;
        }
        """
    )
    column_defs = [
        {"field": "ID", "hide": True, "editable": False},
        {"field": "Projet ID", "hide": True, "editable": False},
        {"field": "Projet", "hide": True, "editable": False},
        {
            "field": "Libellé",
            "headerName": "Tâche",
            "editable": False,
            "pinned": "left",
            "width": 290,
            "cellClass": "pv-left-cell",
            "headerClass": "pv-left-header",
        },
        {"field": "Référence", "editable": False, "width": 135},
        {
            "field": "Titre",
            "editable": True,
            "width": 220,
            "cellClass": "pv-left-cell",
            "headerClass": "pv-left-header",
        },
        {
            "field": "Niveau",
            "editable": True,
            "width": 95,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": [1, 2, 3, 4]},
        },
        {"field": "Enfants", "editable": False, "width": 95, "type": "numericColumn"},
        {"field": "Mode calcul", "editable": False, "width": 125},
        {
            "field": "Parent",
            "editable": True,
            "width": 260,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": [""] + list(task_labels.keys())},
        },
        {
            "field": "Budget",
            "editable": True,
            "width": 260,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": [""] + list(budget_labels.keys())},
        },
        {
            "field": "STARCOST",
            "editable": True,
            "width": 115,
            "cellRenderer": "agCheckboxCellRenderer",
            "cellEditor": "agCheckboxCellEditor",
        },
        {
            "field": "Statut",
            "editable": True,
            "width": 140,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": ["Non commencé", "En cours", "En attente", "Bloqué", "Terminé"]},
        },
        {
            "field": "Priorité",
            "editable": True,
            "width": 120,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": ["Basse", "Normale", "Haute", "Critique"]},
        },
        {"field": "Début", "editable": True, "width": 120},
        {"field": "Fin estimée", "editable": True, "width": 130},
        {"field": "Date de clôture", "editable": True, "width": 145},
        {"field": "Temps prévu", "editable": True, "width": 125, "type": "numericColumn"},
        {"field": "Temps passé", "editable": False, "width": 125, "type": "numericColumn"},
        {"field": "Temps planifié", "editable": False, "width": 140, "type": "numericColumn"},
        {"field": "Coût prévu", "editable": True, "width": 120, "type": "numericColumn"},
        {"field": "Coût temps réel", "editable": False, "width": 140, "type": "numericColumn"},
        {"field": "Dépense directe", "editable": True, "width": 145, "type": "numericColumn"},
        {"field": "Coût réel total", "editable": False, "width": 145, "type": "numericColumn"},
        {"field": "Avancement", "editable": True, "width": 120, "type": "numericColumn"},
        {"field": "Ressources", "editable": False, "width": 180},
        {"field": "Description", "editable": True, "width": 260},
    ]
    available_column_defs = [col for col in column_defs if col["field"] in grid_data.columns]
    visible_columns = grid_column_visibility_selector(
        "tasks_grid",
        [column["field"] for column in available_column_defs if column.get("field")],
        required_columns=["Libellé", "Référence"],
        technical_columns={"ID", "Projet ID", "Projet"},
        column_labels={"Libellé": "Tâche"},
    )
    column_defs = apply_aggrid_column_visibility(
        available_column_defs,
        visible_columns,
        required_columns=["Libellé", "Référence"],
        technical_columns={"ID", "Projet ID", "Projet"},
    )
    grid_options = {
        "columnDefs": column_defs,
        "defaultColDef": {
            "filter": True,
            "sortable": True,
            "resizable": True,
            "minWidth": 85,
            "cellClass": "pv-center-cell",
            "headerClass": "pv-center-header",
        },
        "getRowStyle": row_style,
        "rowSelection": "single",
        "stopEditingWhenCellsLoseFocus": True,
        "singleClickEdit": False,
        "animateRows": False,
        "rowHeight": 32,
        "headerHeight": 34,
        "suppressMovableColumns": False,
    }
    response = AgGrid(
        grid_data,
        gridOptions=grid_options,
        height=compact_grid_height(len(grid_data), row_height=32, header_height=34, min_height=136, max_height=620),
        data_return_mode=DataReturnMode.AS_INPUT,
        update_on=["cellValueChanged"],
        allow_unsafe_jscode=True,
        theme="streamlit",
        show_toolbar=True,
        show_search=True,
        show_download_button=False,
        custom_css=TODAY_AGGRID_CSS,
        key=f"tasks_grid_{project_id}",
    )
    return aggrid_data(response, grid_data)


def weekly_timesheet_editor(
    weekly_data: pd.DataFrame,
    day_columns: list[str],
    project_key: str,
    user_id: int,
    selected_week: date,
    grid_key_prefix: str = "weekly_timesheet",
    user_label: str | None = None,
) -> pd.DataFrame:
    grid_data = weekly_data.copy()
    total_label = f"Total {user_label or 'utilisateur'}"
    week_specs = [
        {"date": day, "field": label, "day": DAY_INITIALS[index], "weekend": index >= 5}
        for index, (day, label) in enumerate(week_day_columns(selected_week))
        if label in day_columns
    ]
    _, week_number, _ = week_start(selected_week).isocalendar()
    week_label = f"S{week_number:02d}"
    today_columns = {
        str(spec["field"]) for spec in week_specs if spec["date"] == date.today()
    }
    weekend_columns = {str(spec["field"]) for spec in week_specs if spec["weekend"]}
    editable_rows = (
        grid_data["_time_editable"].astype(str).str.lower().isin(["true", "1", "yes"])
        if "_time_editable" in grid_data.columns
        else pd.Series(True, index=grid_data.index)
    )
    pinned_total_row = {
        "Projet ID": None,
        "Tâche ID": None,
        "_time_editable": False,
        "Projet": "",
        "Tâche": total_label,
        "Mode calcul": "Agrégé",
    }
    for label in day_columns:
        pinned_total_row[label] = float(
            pd.to_numeric(grid_data.loc[editable_rows, label], errors="coerce").fillna(0).sum()
        )
    editable_cell = JsCode(
        """
        function(params) {
            return params.node && params.node.rowPinned !== 'bottom' && params.data && params.data._time_editable === true;
        }
        """
    )
    row_style = JsCode(
        """
        function(params) {
            const base = {fontSize: '13px', color: '#111827'};
            if (params.node && params.node.rowPinned === 'bottom') {
                return {...base, backgroundColor: '#fef3c7', fontWeight: '700', borderTop: '2px solid #d6b247'};
            }
            if (params.data && params.data._time_editable !== true) {
                return {...base, backgroundColor: '#eef2f7', color: '#64748b', fontStyle: 'italic'};
            }
            return {...base, backgroundColor: '#ffffff'};
        }
        """
    )
    day_cell_style = JsCode(
        f"""
        function(params) {{
            const center = {{display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center'}};
            const todayColumns = {json.dumps(sorted(today_columns), ensure_ascii=False)};
            const weekendColumns = {json.dumps(sorted(weekend_columns), ensure_ascii=False)};
            const isToday = todayColumns.includes(params.colDef.field);
            const isWeekend = weekendColumns.includes(params.colDef.field);
            if (params.node && params.node.rowPinned === 'bottom') {{
                if (isToday) {{
                    return {{...center, backgroundColor: '{TODAY_COLUMN_STRONG_COLOR}', color: '{TODAY_COLUMN_TEXT}', fontWeight: '700'}};
                }}
                return {{...center, backgroundColor: '#fef3c7', color: '#111827', fontWeight: '700'}};
            }}
            if (params.data && params.data._time_editable !== true) {{
                if (isToday) {{
                    return {{...center, backgroundColor: '{TODAY_COLUMN_COLOR}', color: '#64748b'}};
                }}
                if (isWeekend) {{
                    return {{...center, backgroundColor: '#e5e7eb', color: '#64748b'}};
                }}
                return {{...center, backgroundColor: '#e5e7eb', color: '#64748b'}};
            }}
            if (isToday) {{
                return {{...center, backgroundColor: '{TODAY_COLUMN_COLOR}', color: '#111827'}};
            }}
            if (isWeekend) {{
                return {{...center, backgroundColor: '#eef0f3', color: '#374151'}};
            }}
            return {{...center, backgroundColor: '#ffffff', color: '#111827'}};
        }}
        """
    )
    hour_parser = JsCode(
        """
        function(params) {
            if (params.newValue === null || params.newValue === undefined || params.newValue === '') {
                return 0;
            }
            const value = Number(String(params.newValue).replace(',', '.'));
            if (Number.isNaN(value)) {
                return params.oldValue || 0;
            }
            return Math.max(0, Math.min(24, value));
        }
        """
    )
    refresh_totals = JsCode(
        f"""
        function(params) {{
            const dayColumns = {json.dumps(day_columns, ensure_ascii=False)};
            const totalRow = {{
                "Projet ID": null,
                "Tâche ID": null,
                "_time_editable": false,
                "Projet": "",
                "Tâche": {json.dumps(total_label, ensure_ascii=False)},
                "Mode calcul": "Agrégé"
            }};
            dayColumns.forEach(function(column) {{
                totalRow[column] = 0;
            }});
            params.api.forEachNode(function(node) {{
                if (!node.rowPinned && node.data && node.data._time_editable === true) {{
                    dayColumns.forEach(function(column) {{
                        const rawValue = node.data[column];
                        const value = Number(String(rawValue === null || rawValue === undefined ? 0 : rawValue).replace(',', '.'));
                        if (!Number.isNaN(value)) {{
                            totalRow[column] += value;
                        }}
                    }});
                }}
            }});
            dayColumns.forEach(function(column) {{
                totalRow[column] = Math.round((totalRow[column] + Number.EPSILON) * 100) / 100;
            }});
            if (params.api.setGridOption) {{
                params.api.setGridOption('pinnedBottomRowData', [totalRow]);
            }} else if (params.api.setPinnedBottomRowData) {{
                params.api.setPinnedBottomRowData([totalRow]);
            }}
        }}
        """
    )
    column_defs = [
        {"field": "Projet ID", "hide": True, "editable": False},
        {"field": "Tâche ID", "hide": True, "editable": False},
        {"field": "_time_editable", "hide": True, "editable": False},
        {
            "field": "Projet",
            "editable": False,
            "pinned": "left",
            "width": 180,
            "cellClass": "pv-left-cell",
            "headerClass": "pv-left-header",
        },
        {
            "field": "Tâche",
            "editable": False,
            "pinned": "left",
            "width": 360,
            "cellClass": "pv-left-cell",
            "headerClass": "pv-left-header",
        },
        {"field": "Mode calcul", "editable": False, "width": 105},
    ]
    day_children = []
    for spec in week_specs:
        field = str(spec["field"])
        header_classes = ["week-day-header"]
        if field in weekend_columns:
            header_classes.append("weekend-column-header")
        if field in today_columns:
            header_classes.append("today-column-header")
        day_children.append(
            {
                "field": field,
                "headerName": str(spec["day"]),
                "editable": editable_cell,
                "filter": False,
                "resizable": False,
                "suppressMenu": True,
                "suppressHeaderMenuButton": True,
                "menuTabs": [],
                "cellStyle": day_cell_style,
                "valueParser": hour_parser,
                "type": "numericColumn",
                "width": 48,
                "minWidth": 44,
                "maxWidth": 54,
                "headerClass": " ".join(["pv-center-header", *header_classes]),
            }
        )
    column_defs.append({"headerName": week_label, "headerClass": "pv-center-header week-group-header", "children": day_children})
    visible_columns = grid_column_visibility_selector(
        f"{grid_key_prefix}_grid",
        [column["field"] for column in column_defs if column.get("field")],
        required_columns=["Projet", "Tâche"],
        default_columns=["Projet", "Tâche", "Mode calcul"],
        technical_columns={"Projet ID", "Tâche ID", "_time_editable"},
    )
    column_defs = apply_aggrid_column_visibility(
        column_defs,
        visible_columns,
        required_columns=["Projet", "Tâche"],
        technical_columns={"Projet ID", "Tâche ID", "_time_editable"},
    )
    grid_options = {
        "columnDefs": column_defs,
        "defaultColDef": {
            "filter": True,
            "sortable": False,
            "resizable": True,
            "minWidth": 90,
            "cellClass": "pv-center-cell",
            "headerClass": "pv-center-header",
        },
        "getRowStyle": row_style,
        "rowSelection": "single",
        "stopEditingWhenCellsLoseFocus": True,
        "singleClickEdit": True,
        "animateRows": False,
        "rowHeight": 30,
        "pinnedBottomRowHeight": 32,
        "headerHeight": 32,
        "groupHeaderHeight": 30,
        "suppressMovableColumns": True,
        "pinnedBottomRowData": [pinned_total_row],
        "onGridReady": refresh_totals,
        "onCellValueChanged": refresh_totals,
    }
    response = AgGrid(
        grid_data,
        gridOptions=grid_options,
        height=compact_grid_height(
            len(grid_data),
            row_height=30,
            header_height=32,
            group_header_height=30,
            pinned_bottom_height=32,
            min_height=150,
            max_height=720,
        ),
        data_return_mode=DataReturnMode.AS_INPUT,
        update_on=["cellValueChanged"],
        allow_unsafe_jscode=True,
        theme="streamlit",
        show_toolbar=True,
        show_search=True,
        show_download_button=False,
        custom_css=TODAY_AGGRID_CSS,
        key=f"{grid_key_prefix}_{project_key}_{user_id}_{selected_week:%Y%m%d}",
    )
    return aggrid_data(response, grid_data)


def recap_period_weeks(start_day: date) -> list[date]:
    start_week = week_start(start_day)
    return [start_week + timedelta(days=7 * index) for index in range(4)]


def time_recap_table_data(entries: pd.DataFrame, start_day: date) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    weeks = recap_period_weeks(start_day)
    period_start = weeks[0]
    period_end = weeks[-1] + timedelta(days=6)
    day_specs: list[dict[str, object]] = []
    for week_index, week in enumerate(weeks):
        _, week_number, _ = week.isocalendar()
        for day_index in range(7):
            current_day = week + timedelta(days=day_index)
            day_specs.append(
                {
                    "field": f"w{week_index}_d{day_index}",
                    "week": f"S{week_number:02d}",
                    "day": DAY_INITIALS[day_index],
                    "date": current_day,
                    "weekend": day_index >= 5,
                }
            )

    columns = ["Utilisateur", "Tâche"] + [str(spec["field"]) for spec in day_specs]
    if entries.empty:
        return pd.DataFrame(columns=columns), day_specs

    data = entries.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce").dt.date
    data["Heures"] = pd.to_numeric(data["Heures"], errors="coerce").fillna(0)
    data = data[
        data["Date"].notna()
        & (data["Date"] >= period_start)
        & (data["Date"] <= period_end)
        & (data["Heures"] > 0)
    ].copy()
    if data.empty:
        return pd.DataFrame(columns=columns), day_specs

    date_to_field = {spec["date"]: str(spec["field"]) for spec in day_specs}
    rows_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for row in data.to_dict("records"):
        field = date_to_field.get(row.get("Date"))
        if not field:
            continue
        user = str(row.get("Utilisateur") or "").strip()
        task = f"{row.get('Projet') or ''} · {row.get('Tâche') or ''}".strip(" ·")
        key = (user, task)
        output_row = rows_by_key.setdefault(
            key,
            {"Utilisateur": user, "Tâche": task, **{str(spec["field"]): 0.0 for spec in day_specs}},
        )
        output_row[field] = float(output_row.get(field) or 0) + float(row.get("Heures") or 0)

    if not rows_by_key:
        return pd.DataFrame(columns=columns), day_specs
    rows = sorted(rows_by_key.values(), key=lambda item: (str(item["Utilisateur"]).lower(), str(item["Tâche"]).lower()))
    return pd.DataFrame(rows, columns=columns), day_specs


def time_recap_grid(data: pd.DataFrame, day_specs: list[dict[str, object]], key: str):
    number_formatter = JsCode(
        """
        function(params) {
            const value = Number(params.value || 0);
            if (!value) {
                return '';
            }
            return value.toLocaleString('fr-FR', {maximumFractionDigits: 2});
        }
        """
    )
    column_defs = [
        {"field": "Utilisateur", "pinned": "left", "editable": False, "width": 135, "minWidth": 110, "filter": True},
        {
            "field": "Tâche",
            "pinned": "left",
            "editable": False,
            "width": 270,
            "minWidth": 220,
            "filter": True,
            "cellClass": "pv-left-cell",
            "headerClass": "pv-left-header",
        },
    ]
    for week_label in dict.fromkeys(str(spec["week"]) for spec in day_specs):
        week_children = []
        for spec in [item for item in day_specs if str(item["week"]) == week_label]:
            weekend = bool(spec["weekend"])
            is_today = spec["date"] == date.today()
            background_color = TODAY_COLUMN_COLOR if is_today else ("#eef0f3" if weekend else "#ffffff")
            text_color = TODAY_COLUMN_TEXT if is_today else ("#374151" if weekend else "#111827")
            week_children.append(
                {
                    "field": str(spec["field"]),
                    "headerName": str(spec["day"]),
                    "editable": False,
                    "filter": False,
                    "sortable": False,
                    "resizable": False,
                    "suppressMenu": True,
                    "suppressHeaderMenuButton": True,
                    "menuTabs": [],
                    "type": "numericColumn",
                    "width": 30,
                    "minWidth": 28,
                    "maxWidth": 36,
                    "headerClass": "pv-center-header today-column-header" if is_today else "pv-center-header",
                    "valueFormatter": number_formatter,
                    "cellStyle": {
                        "display": "flex",
                        "alignItems": "center",
                        "justifyContent": "center",
                        "textAlign": "center",
                        "backgroundColor": background_color,
                        "color": text_color,
                        **({"fontWeight": "700"} if is_today else {}),
                    },
                }
            )
        column_defs.append({"headerName": week_label, "headerClass": "pv-center-header week-group-header", "children": week_children})

    grid_options = {
        "columnDefs": column_defs,
        "defaultColDef": {
            "editable": False,
            "filter": False,
            "sortable": False,
            "resizable": True,
            "minWidth": 28,
            "suppressMenu": True,
            "suppressHeaderMenuButton": True,
            "menuTabs": [],
            "cellClass": "pv-center-cell",
            "headerClass": "pv-center-header",
        },
        "rowSelection": "single",
        "animateRows": False,
        "rowHeight": 30,
        "headerHeight": 30,
        "groupHeaderHeight": 30,
        "suppressMovableColumns": True,
    }
    return AgGrid(
        data,
        gridOptions=grid_options,
        height=compact_grid_height(
            len(data),
            row_height=30,
            header_height=30,
            group_header_height=30,
            min_height=140,
            max_height=720,
        ),
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=True,
        theme="streamlit",
        show_toolbar=True,
        show_search=True,
        show_download_button=True,
        fit_columns_on_grid_load=True,
        custom_css=TODAY_AGGRID_CSS,
        key=key,
    )


def task_tree(data: pd.DataFrame) -> tuple[list[dict], dict[str, list[dict]]]:
    rows = data.to_dict("records")
    existing_labels = {task_label(row) for row in rows}
    children_by_parent: dict[str, list[dict]] = {}
    roots: list[dict] = []
    for row in rows:
        parent = str(row.get("Parent") or "").strip()
        if parent and parent in existing_labels:
            children_by_parent.setdefault(parent, []).append(row)
        else:
            roots.append(row)
    return roots, children_by_parent


def task_subtree(root: dict, children_by_parent: dict[str, list[dict]]) -> list[dict]:
    rows: list[dict] = []

    def walk(row: dict) -> None:
        rows.append(row)
        for child in children_by_parent.get(task_label(row), []):
            walk(child)

    walk(root)
    return rows


def show_grouped_tasks(task_data: pd.DataFrame) -> None:
    if task_data.empty:
        st.info("Aucune tâche disponible.")
        return
    task_level_legend()
    visible_columns = grid_column_visibility_selector(
        "grouped_tasks_grid",
        [column for column in TASK_DISPLAY_COLUMNS if column in task_data.columns],
        required_columns=["Libellé"],
        column_labels={"Libellé": "Tâche"},
    )
    st.dataframe(styled_task_table(task_data, visible_columns), use_container_width=True, hide_index=True)

    roots, children_by_parent = task_tree(task_data)
    st.subheader("Regroupement par tâche maîtresse")
    for index, root in enumerate(roots):
        subtree = task_subtree(root, children_by_parent)
        child_count = max(len(subtree) - 1, 0)
        label = str(root.get("Libellé") or task_label(root)).strip()
        with st.expander(f"{label} - {child_count} sous-tâche(s)", expanded=index == 0):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Période", f"{root.get('Début') or ''} -> {root.get('Fin estimée') or ''}")
            c2.metric("Heures", f"{float(root.get('Temps passé') or 0):.1f} / {float(root.get('Temps prévu') or 0):.1f}")
            c3.metric("Coût réel", eur(float(root.get("Coût réel total") or 0)))
            c4.metric("Avancement", f"{float(root.get('Avancement') or 0):.0f}%")
            st.dataframe(styled_task_table(pd.DataFrame(subtree), visible_columns), use_container_width=True, hide_index=True)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --pv-navy: #061735;
            --pv-night: #0b2348;
            --pv-blue: #1f6feb;
            --pv-sky: #2bb7ff;
            --pv-ice: #f3f8ff;
            --pv-line: #d7e8ff;
            --pv-sun: #ffd18a;
        }
        .stApp {
            background:
                radial-gradient(circle at 82% 8%, rgba(43, 183, 255, 0.13), transparent 28rem),
                linear-gradient(180deg, #f7fbff 0%, #f2f6fb 58%, #ffffff 100%);
            color: var(--pv-navy);
        }
        .block-container {padding-top: 2rem; padding-bottom: 1.1rem;}
        [data-testid="stVerticalBlock"] {gap: 0.55rem;}
        [data-testid="stHorizontalBlock"] {gap: 0.65rem;}
        [data-testid="stAppViewContainer"] main div[data-testid="stMarkdownContainer"],
        [data-testid="stAppViewContainer"] main div[data-testid="stHeadingWithActionElements"] {
            overflow: visible !important;
        }
        [data-testid="stAppViewContainer"] main h1,
        [data-testid="stAppViewContainer"] main h2,
        [data-testid="stAppViewContainer"] main h3 {
            line-height: 1.35 !important;
            padding-top: 0.35rem !important;
            padding-bottom: 0.05rem !important;
            margin-top: 0 !important;
            overflow: visible !important;
        }
        div[data-testid="stCaptionContainer"] {margin-top: -0.2rem;}
        div[data-testid="stExpander"] {margin-bottom: 0.25rem;}
        div[data-testid="stTabs"] [data-baseweb="tab-list"] {margin-bottom: 0.35rem;}
        header[data-testid="stHeader"] {
            background: transparent !important;
            box-shadow: none !important;
            z-index: 100 !important;
        }
        header[data-testid="stHeader"] [data-testid="stToolbar"],
        header[data-testid="stHeader"] .stDeployButton,
        header[data-testid="stHeader"] [data-testid="stDecoration"],
        #MainMenu,
        footer {
            display: none !important;
        }
        [class*="st-key-pv_sticky_header_"] {
            position: fixed !important;
            top: 0.45rem;
            left: 20rem;
            right: 1.15rem;
            width: calc(100vw - 21.15rem) !important;
            box-sizing: border-box;
            z-index: 2147483000;
            min-height: 4rem;
            background: rgba(255, 255, 255, 0.99);
            border: 1px solid #bcd7ff;
            border-left: 4px solid var(--pv-blue);
            box-shadow: 0 12px 30px rgba(6, 23, 53, 0.13);
            backdrop-filter: blur(10px);
            margin: 0;
            padding: 0.55rem 0.9rem 0.6rem;
        }
        .pv-sticky-spacer {
            display: block;
            width: 100%;
            pointer-events: none;
        }
        .pv-sticky-header-spacer {
            height: 5.55rem;
        }
        .pv-sticky-header-spacer-timesheet,
        .pv-sticky-header-spacer-planning,
        .pv-sticky-header-spacer-users {
            height: 4.8rem;
        }
        .pv-sticky-title {
            color: var(--pv-navy);
            font-size: clamp(1.75rem, 2.35vw, 2.45rem);
            font-weight: 800;
            line-height: 1.1;
            white-space: nowrap;
            padding: 0.25rem 0 0.1rem;
        }
        [class*="st-key-pv_sticky_header_"] [data-testid="stVerticalBlock"],
        [class*="st-key-pv_sticky_toolbar_"] [data-testid="stVerticalBlock"] {
            gap: 0.1rem;
        }
        [class*="st-key-pv_sticky_header_"] [data-testid="stHorizontalBlock"],
        [class*="st-key-pv_sticky_toolbar_"] [data-testid="stHorizontalBlock"] {
            gap: 0.5rem;
        }
        [class*="st-key-pv_sticky_header_"] [data-testid="column"] {
            min-width: 0 !important;
        }
        [class*="st-key-pv_sticky_header_"] label,
        [class*="st-key-pv_sticky_toolbar_"] label {
            color: #264665 !important;
            font-weight: 650 !important;
            margin-bottom: 0.08rem !important;
            line-height: 1.1 !important;
        }
        [class*="st-key-pv_sticky_header_"] [data-baseweb="select"] > div,
        [class*="st-key-pv_sticky_toolbar_"] [data-baseweb="select"] > div {
            width: 100% !important;
            min-width: 0 !important;
            min-height: 2.45rem !important;
            max-height: 2.45rem !important;
            overflow: hidden !important;
            flex-wrap: nowrap !important;
        }
        [class*="st-key-pv_sticky_header_"] [data-baseweb="select"] span,
        [class*="st-key-pv_sticky_header_"] [data-baseweb="select"] input,
        [class*="st-key-pv_sticky_header_"] [data-testid="stDateInput"] input {
            min-width: 0 !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            white-space: nowrap !important;
        }
        [class*="st-key-pv_sticky_header_"] button {
            min-width: 2.1rem !important;
            height: 2.45rem !important;
            padding: 0 0.25rem !important;
        }
        [class*="st-key-pv_sticky_header_"] button p {
            font-size: 1.1rem !important;
            line-height: 1 !important;
        }
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        div[role="listbox"] {
            z-index: 2147483647 !important;
        }
        [class*="st-key-pv_sticky_tabs_"] [data-baseweb="tab-list"] {
            position: static !important;
            box-sizing: border-box;
            background: rgba(255, 255, 255, 0.99);
            border: 1px solid #d7e8ff;
            border-radius: 7px;
            box-shadow: 0 8px 20px rgba(6, 23, 53, 0.09);
            padding: 0.22rem 0.45rem 0.32rem;
            backdrop-filter: blur(10px);
        }
        [class*="st-key-pv_sticky_tabs_"] [data-baseweb="tab-panel"] {
            padding-top: 0.25rem;
        }
        [class*="st-key-pv_sticky_toolbar_"] {
            position: fixed !important;
            left: 20rem;
            right: 1.15rem;
            width: calc(100vw - 21.15rem) !important;
            box-sizing: border-box;
            top: 8.05rem;
            z-index: 2147482980;
            min-height: 3.35rem;
            background: rgba(255, 255, 255, 0.99);
            border: 1px solid #bcd7ff;
            border-radius: 8px;
            box-shadow: 0 10px 22px rgba(6, 23, 53, 0.11);
            backdrop-filter: blur(10px);
            margin: 0 0 0.6rem;
            padding: 0.45rem 0.7rem 0.5rem;
        }
        .st-key-pv_sticky_toolbar_tasks_gantt {
            top: 8.05rem;
        }
        .pv-sticky-toolbar-spacer {
            height: 4.7rem;
        }
        .pv-sticky-toolbar-spacer-tasks_gantt {
            height: 4.7rem;
        }
        .pv-sticky-header-spacer-timesheet,
        .pv-sticky-header-spacer-planning {
            height: 6.35rem;
        }
        .pv-sticky-header-spacer-dashboard,
        .pv-sticky-header-spacer-projects,
        .pv-sticky-header-spacer-tasks,
        .pv-sticky-header-spacer-budget,
        .pv-sticky-header-spacer-reports {
            height: 6.1rem;
        }
        @media (max-width: 900px) {
            [class*="st-key-pv_sticky_header_"] {
                left: 4.7rem;
                right: 0.6rem;
                width: calc(100vw - 5.3rem) !important;
                margin-left: 0;
                margin-right: 0;
                padding-left: 0.4rem;
                padding-right: 0.4rem;
            }
            .pv-sticky-header-spacer-timesheet,
            .pv-sticky-header-spacer-planning {
                height: 11rem;
            }
            [class*="st-key-pv_sticky_toolbar_"] {
                left: 4.7rem;
                right: 0.6rem;
                width: calc(100vw - 5.3rem) !important;
                top: 7.95rem;
            }
            .st-key-pv_sticky_toolbar_tasks_gantt {
                top: 7.95rem;
            }
        }
        hr {margin: 0.55rem 0 !important;}
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid var(--pv-line);
            border-radius: 8px;
            padding: 8px 12px;
            box-shadow: 0 8px 20px rgba(6, 23, 53, 0.04);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #061735 0%, #0a244c 62%, #0f3266 100%);
            border-right: 1px solid rgba(43, 183, 255, 0.24);
        }
        [data-testid="stSidebar"] * {color: #f8fafc;}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap: 0.35rem;}
        .pv-sidebar-brand {
            color: #ffffff;
            font-size: 1.45rem;
            font-weight: 800;
            line-height: 1.05;
            padding-top: 0.24rem;
        }
        .pv-sidebar-brand span {color: var(--pv-sky);}
        .pv-sidebar-user {
            color: #bcd7ff;
            font-size: 0.78rem;
            margin-top: 0.2rem;
        }
        [data-testid="stSidebar"] button {
            background: rgba(255, 255, 255, 0.07) !important;
            border: 1px solid rgba(188, 215, 255, 0.24) !important;
            color: #e5edf7 !important;
            justify-content: flex-start;
            min-height: 2.25rem;
            overflow: hidden;
            white-space: nowrap;
            box-shadow: none !important;
        }
        [data-testid="stSidebar"] button:hover {
            background: rgba(43, 183, 255, 0.14) !important;
            border-color: rgba(43, 183, 255, 0.76) !important;
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] button:focus-visible {
            outline: 2px solid #93c5fd !important;
            outline-offset: 2px;
        }
        [data-testid="stSidebar"] button[kind="primary"],
        [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
            background: linear-gradient(90deg, #1f6feb 0%, #2bb7ff 100%) !important;
            border-color: rgba(43, 183, 255, 0.82) !important;
            color: #ffffff !important;
            box-shadow: 0 8px 18px rgba(31, 111, 235, 0.28) !important;
        }
        [data-testid="stSidebar"] button[kind="secondary"],
        [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
            background: rgba(255, 255, 255, 0.07) !important;
            border-color: rgba(188, 215, 255, 0.24) !important;
            color: #e5edf7 !important;
        }
        [data-testid="stSidebar"] button[kind="secondary"]:hover,
        [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover {
            background: rgba(43, 183, 255, 0.14) !important;
            border-color: rgba(43, 183, 255, 0.76) !important;
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] button[kind="primary"]:hover,
        [data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:hover {
            background: linear-gradient(90deg, #155bd4 0%, #18a7f2 100%) !important;
            border-color: #7aa2ff !important;
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] button *,
        [data-testid="stSidebar"] button p,
        [data-testid="stSidebar"] button span {
            color: inherit !important;
        }
        [data-testid="stSidebar"] button [data-testid="stIconMaterial"],
        [data-testid="stSidebar"] button svg,
        [data-testid="stSidebar"] button span[aria-hidden="true"] {
            flex: 0 0 auto;
            margin-right: 0.35rem;
        }
        [data-testid="stSidebar"] button p {
            color: inherit !important;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] {
            display: block;
            min-width: 2.55rem !important;
            max-width: 2.55rem !important;
            width: 2.55rem !important;
            margin-left: 0 !important;
            transform: translateX(0) !important;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] > div:first-child {
            min-width: 2.55rem !important;
            max-width: 2.55rem !important;
            width: 2.55rem !important;
            padding-left: 0.28rem;
            padding-right: 0.28rem;
            overflow: hidden;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] h1,
        section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stCaptionContainer"],
        section[data-testid="stSidebar"][aria-expanded="false"] .pv-sidebar-brand,
        section[data-testid="stSidebar"][aria-expanded="false"] .pv-sidebar-user {
            display: none;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stImage"] img {
            max-width: 1.75rem !important;
            border-radius: 0.38rem;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] button {
            min-width: 1.9rem !important;
            max-width: 1.9rem !important;
            width: 1.9rem !important;
            height: 2.1rem;
            padding-left: 0.38rem;
            padding-right: 0;
            justify-content: flex-start;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] button [data-testid="stIconMaterial"],
        section[data-testid="stSidebar"][aria-expanded="false"] button svg,
        section[data-testid="stSidebar"][aria-expanded="false"] button span[aria-hidden="true"] {
            margin-right: 0;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] button p {
            display: none;
        }
        h1, h2, h3 {letter-spacing: 0;}
        [data-testid="stForm"] {
            border-color: var(--pv-line);
            box-shadow: 0 14px 30px rgba(6, 23, 53, 0.05);
        }
        .pv-login-title {
            color: var(--pv-navy);
            font-size: clamp(2rem, 4vw, 3.4rem);
            font-weight: 800;
            line-height: 1.08;
            margin: 0 0 0.35rem 0;
        }
        .pv-login-title span {color: var(--pv-sky);}
        .pv-login-subtitle {
            color: #3f5f87;
            font-size: 1rem;
            margin-bottom: 1rem;
        }
        .pv-login-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 0.6rem;
        }
        .pv-login-badges span {
            background: rgba(31, 111, 235, 0.08);
            border: 1px solid rgba(31, 111, 235, 0.16);
            border-radius: 999px;
            color: #0b3b78;
            font-size: 0.76rem;
            font-weight: 600;
            padding: 0.28rem 0.62rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def login() -> None:
    hero_col, login_col = st.columns([1.35, 0.65], gap="large")
    with hero_col:
        if HERO_PATH.exists():
            st.image(str(HERO_PATH), width="stretch")
        elif LOGIN_PANEL_PATH.exists():
            st.image(str(LOGIN_PANEL_PATH), width="stretch")
        else:
            st.markdown(
                """
                <div class="pv-login-title">Perspecti<span>V</span></div>
                <div class="pv-login-subtitle">Voir loin. Planifier mieux. Réussir ensemble.</div>
                """,
                unsafe_allow_html=True,
            )

    with login_col:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=330)
        else:
            st.markdown('<div class="pv-login-title">Perspecti<span>V</span></div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="pv-login-subtitle">
                Gestion de projets locale, budgets, Gantt, temps et planification.
            </div>
            <div class="pv-login-badges">
                <span>Vision claire</span>
                <span>Planification</span>
                <span>Collaboration</span>
                <span>Performance</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.subheader("Connexion")
        if OIDC_ISSUER:
            st.button(
                "Se connecter avec PerspectiV SSO",
                type="primary",
                use_container_width=True,
                on_click=st.login,
                args=("keycloak",),
            )
            submitted = False
            username = password = ""
        else:
            with st.form("login_form"):
                username = st.text_input("Utilisateur", value="admin")
                password = st.text_input("Mot de passe", type="password", value="admin")
                submitted = st.form_submit_button("Se connecter", type="primary", use_container_width=True)
    if submitted:
        with session_scope() as session:
            user = authenticate(session, username, password)
            if user:
                st.session_state["user"] = {"id": user.id, "name": user.full_name, "role": user.role}
                st.rerun()
            st.error("Identifiant ou mot de passe incorrect.")
    if not OIDC_ISSUER:
        st.info("Compte de démonstration : admin / admin. À changer avant usage réel.")


def require_login() -> None:
    if OIDC_ISSUER and getattr(st.user, "is_logged_in", False):
        subject = str(getattr(st.user, "sub", "") or "")
        username = str(getattr(st.user, "preferred_username", "") or "").lower()
        email = str(getattr(st.user, "email", "") or "").lower()
        with session_scope() as session:
            user = session.scalar(select(User).where(User.oidc_subject == subject)) if subject else None
            if not user and (username or email):
                user = session.scalar(select(User).where(or_(User.username == username, User.email == email)))
                if user and subject and not user.oidc_subject:
                    user.oidc_subject = subject
            if not user or not user.active:
                st.error("Ce compte SSO n'est pas rattaché à un utilisateur PerspectiV actif.")
                if st.button("Se déconnecter"):
                    st.logout()
                st.stop()
            st.session_state["user"] = {"id": user.id, "name": user.full_name, "role": user.role}
    if "user" not in st.session_state:
        login()
        st.stop()


def sidebar() -> str:
    user = st.session_state["user"]
    target_page = st.session_state.pop("navigate_to_page", None)
    if target_page in PAGES:
        st.session_state["navigation_page"] = target_page
    elif "navigation_page" not in st.session_state:
        st.session_state["navigation_page"] = PAGES[0]

    logo_col, brand_col = st.sidebar.columns([0.27, 0.73], gap="small")
    with logo_col:
        if ICON_PATH.exists():
            st.image(str(ICON_PATH), width=42)
    with brand_col:
        st.markdown('<div class="pv-sidebar-brand">Perspecti<span>V</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="pv-sidebar-user">{user["name"]} · {user["role"]}</div>', unsafe_allow_html=True)
    page = st.session_state["navigation_page"]
    for index, nav_page in enumerate(PAGES):
        if st.sidebar.button(
            nav_page,
            key=f"nav_page_{index}",
            icon=PAGE_ICONS.get(nav_page),
            type="primary" if nav_page == page else "secondary",
            use_container_width=True,
        ):
            st.session_state["navigation_page"] = nav_page
            st.rerun()
    if st.sidebar.button("Déconnexion", icon=":material/logout:", use_container_width=True):
        st.session_state.clear()
        if OIDC_ISSUER and getattr(st.user, "is_logged_in", False):
            st.logout()
        else:
            st.rerun()
    return st.session_state["navigation_page"]


def select_project(label: str = "Projet", include_all: bool = False) -> int | None:
    with session_scope() as session:
        options = project_options(session)
    if include_all:
        labels = ["Tous les projets"] + list(options.keys())
        selected = st.selectbox(label, labels)
        return None if selected == "Tous les projets" else options[selected]
    if not options:
        st.warning("Créez d'abord un projet.")
        return None
    labels = list(options.keys())
    selector_key = "selected_project_label"
    forced = st.session_state.pop("force_project_selector", False)
    selected_label = project_label_for_id(options, st.session_state.get("selected_project_id"))
    if forced and selected_label:
        st.session_state[selector_key] = selected_label
    elif selector_key not in st.session_state or st.session_state[selector_key] not in labels:
        st.session_state[selector_key] = selected_label or labels[0]
    selected = st.selectbox(label, labels, key=selector_key)
    st.session_state["selected_project_id"] = options[selected]
    return options[selected]


def show_dashboard() -> None:
    header = sticky_page_header("dashboard")
    with header:
        title_col, filter_col, month_col = st.columns([1.1, 2.25, 1.0], vertical_alignment="center")
        with title_col:
            sticky_header_title("Tableau de bord")
        with filter_col:
            project_id = select_project("Périmètre", include_all=True)
        month_placeholder = month_col.empty()
    with session_scope() as session:
        metrics = kpis(session, project_id)
        task_data = tasks_df(session, project_id)
        time_data = time_entries_df(session, project_id)
        budget_data = budget_df(session, project_id)
        starcost_monthly = starcost_hours_by_month_df(session, project_id)
        completion_monthly = monthly_completion_df(session, project_id)
        deps = dependencies_df(session, project_id)
        risk_metrics = risk_kpis(session, project_id)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Projets", int(metrics["projects"]))
    c2.metric("Tâches", int(metrics["tasks"]), f"{metrics['late_tasks']} en retard")
    c3.metric("Avancement moyen", f"{metrics['progress']}%")
    c4.metric("Heures", f"{metrics['actual_hours']:.1f} / {metrics['planned_hours']:.1f}")
    c5.metric("Réel budget", eur(metrics["actual_budget"]))

    r1, r2, r3 = st.columns(3)
    r1.metric("Analyses de risques", risk_metrics["analyses"])
    r2.metric("Risques High / Extreme", risk_metrics["high_or_extreme"])
    r3.metric("Décisions de risques en attente", risk_metrics["pending_acceptance"])

    c5, c6 = st.columns(2)
    c5.plotly_chart(tasks_status_pie(task_data), use_container_width=True)
    c6.plotly_chart(budget_pie(budget_data), use_container_width=True)

    c7, c8 = st.columns(2)
    c7.plotly_chart(hours_by_user_bar(time_data), use_container_width=True)
    c8.plotly_chart(workload_bar(task_data), use_container_width=True)

    st.subheader("Suivi mensuel")
    months = sorted(set(starcost_monthly.get("Mois", pd.Series(dtype=str))).union(completion_monthly.get("Mois", pd.Series(dtype=str))))
    current_month = date.today().strftime("%Y-%m")
    if not months:
        months = [current_month]
    month_index = months.index(current_month) if current_month in months else len(months) - 1
    with month_placeholder:
        selected_month = st.selectbox("Mois", months, index=month_index)
    completion_row = completion_monthly[completion_monthly["Mois"] == selected_month]
    planned_tasks = int(completion_row["Tâches prévues"].iloc[0]) if not completion_row.empty else 0
    on_time_tasks = int(completion_row["Terminées à temps"].iloc[0]) if not completion_row.empty else 0
    c9, c10 = st.columns([1, 2])
    c9.metric(
        "Tâches terminées à temps",
        f"{on_time_tasks} tâches terminées à temps sur {planned_tasks} prévues sur le mois",
    )
    c10.plotly_chart(starcost_hours_month_bar(starcost_monthly), use_container_width=True)

    path = critical_path(task_data, deps)
    if path:
        st.subheader("Chemin critique indicatif")
        st.write(" -> ".join(path))


def show_projects() -> None:
    with session_scope() as session:
        users = user_options(session)
        user_names = user_name_options(session)
        data = projects_df(session)

    header = sticky_page_header("projects")
    if not data.empty:
        project_label_by_id = {
            int(row["ID"]): f"{row.get('Code', '')} - {row.get('Projet', '')}"
            for row in data.to_dict("records")
            if row.get("ID")
        }
        project_ids_by_label = {label: project_id for project_id, label in project_label_by_id.items()}
        project_label_list = [project_label_by_id[int(row["ID"])] for row in data.to_dict("records") if row.get("ID")]
        default_project = project_label_by_id.get(int(st.session_state.get("selected_project_id") or 0))
        default_selection = [default_project or project_label_list[0]]
        selector_key = "projects_view_project_labels"
        existing_projects = st.session_state.get(selector_key)
        if isinstance(existing_projects, list):
            valid_existing = [label for label in existing_projects if label in project_ids_by_label]
            st.session_state[selector_key] = valid_existing or default_selection
        else:
            st.session_state[selector_key] = default_selection

        with header:
            title_col, filter_col, color_col = st.columns([0.65, 2.7, 0.95], vertical_alignment="center")
            with title_col:
                sticky_header_title("Projets")
            selected_project_labels = filter_col.multiselect("Projets", project_label_list, key=selector_key)
            color_placeholder = color_col.empty()
    else:
        with header:
            sticky_header_title("Projets")
        selected_project_labels = []
        color_placeholder = None

    with st.expander("Créer un projet", expanded=False):
        with st.form("project_form"):
            c1, c2 = st.columns(2)
            code = c1.text_input("Code", value="PRJ-002")
            name = c2.text_input("Nom du projet")
            owner_label = st.selectbox("Responsable", [""] + list(users.keys()))
            c3, c4, c5 = st.columns(3)
            category = c3.text_input("Catégorie", value="Interne")
            priority = c4.selectbox("Priorité", ["Basse", "Normale", "Haute", "Critique"], index=1)
            status = c5.selectbox("Statut", ["Non commencé", "En cours", "En attente", "Terminé", "Archivé"], index=1)
            c6, c7, c8, c9 = st.columns(4)
            start = c6.date_input("Début", value=date.today())
            end = c7.date_input("Fin cible", value=date.today())
            budget_amount = c8.number_input("Budget", min_value=0.0, step=500.0)
            budget_hours = c9.number_input("Budget heures", min_value=0.0, step=8.0)
            description = st.text_area("Description")
            submitted = st.form_submit_button("Créer le projet")
        if submitted:
            try:
                with session_scope() as session:
                    create_project(
                        session,
                        code,
                        name,
                        users.get(owner_label),
                        category,
                        priority,
                        status,
                        start,
                        end,
                        budget_amount,
                        budget_hours,
                        description,
                    )
                st.success("Projet créé.")
                st.rerun()
            except IntegrityError:
                st.error("Ce code projet existe déjà.")

    if data.empty:
        st.info("Aucun projet disponible.")
        return

    if not selected_project_labels:
        st.warning("Sélectionnez au moins un projet pour afficher le Gantt et la grille.")
        return
    selected_project_ids = [project_ids_by_label[label] for label in selected_project_labels]
    st.session_state["selected_project_id"] = selected_project_ids[0]
    filtered_data = data[data["ID"].isin(selected_project_ids)].copy()
    project_key = "_".join(str(project_id) for project_id in selected_project_ids)

    st.subheader("Gantt projets")
    st.caption("Modifiez les dates ou les montants : le Gantt se met à jour automatiquement. Double-cliquez une ligne pour ouvrir ses tâches.")
    color_options = [column for column in ["Budget", "Budget heures"] if column in filtered_data.columns]
    with color_placeholder:
        color_field = st.selectbox("Colorer les projets par", color_options or ["Budget"], index=0)

    gantt_container = st.container()
    st.subheader("Table projets")
    save_projects = top_right_save_button("projects_save")
    table_container = st.container()
    with table_container:
        grid_response = project_grid(filtered_data, user_names, key=f"projects_grid_{project_key}")
        edited = aggrid_data(grid_response, filtered_data)
        project_id = double_clicked_project_id(grid_response)
        if project_id:
            navigate_to_project_tasks(project_id)
            st.rerun()

    with gantt_container:
        st.plotly_chart(projects_gantt(edited, color_field), width="stretch")

    if save_projects:
        try:
            with session_scope() as session:
                update_projects_from_df(session, edited)
            st.success("Projets mis à jour.")
            st.rerun()
        except IntegrityError:
            st.error("Un code projet existe déjà.")
        except Exception as exc:
            st.error(str(exc))

    delete_record_control("project", filtered_data, ["Code", "Projet"], "projects")


def show_tasks() -> None:
    header = sticky_page_header("tasks")
    with header:
        title_col, filter_col, color_col = st.columns([1.1, 2.1, 1.05], vertical_alignment="center")
        with title_col:
            sticky_header_title("Tâches et Gantt")
        with filter_col:
            project_id = select_project()
        color_placeholder = color_col.empty()
    if not project_id:
        return
    with session_scope() as session:
        task_data = tasks_df(session, project_id)
        deps = dependencies_df(session, project_id)
        assignments = assignments_df(session, project_id)
        users = user_options(session)
        task_labels = task_options(session, project_id)
        budget_labels = budget_options(session, project_id)
    with color_placeholder:
        color_options = task_color_options(task_data)
        color_field = st.selectbox("Colorer les tâches par", color_options or ["Temps prévu"], index=0)

    gantt_tab, grouped_tab, create_tab, task_budget_tab, deps_tab, assign_tab = sticky_tabs(
        "tasks",
        ["Gantt", "Vue groupée", "Nouvelle tâche", "Budget tâche", "Dépendances", "Affectations"]
    )

    with gantt_tab:
        st.subheader("Gantt tâches")
        gantt_container = st.container()
        st.subheader("Table tâches")
        save_tasks = top_right_save_button(f"tasks_save_{project_id}")
        edited_tasks = task_editor(task_data, task_labels, budget_labels, project_id)
        with gantt_container:
            st.plotly_chart(gantt_figure(edited_tasks, color_field), width="stretch")
        if not deps.empty:
            st.caption("Dépendances")
            deps_display = deps[["Prédécesseur", "Successeur", "Type", "Décalage"]]
            deps_visible_columns = grid_column_visibility_selector(
                "task_gantt_dependencies_grid",
                list(deps_display.columns),
                required_columns=["Prédécesseur", "Successeur"],
            )
            st.dataframe(
                styled_plain_table(deps_display[visible_columns_for_editor(deps_display, deps_visible_columns)]),
                width="stretch",
                hide_index=True,
            )
        if save_tasks:
            try:
                with session_scope() as session:
                    update_tasks_from_df(session, edited_tasks, project_id)
                st.success("Tâches mises à jour, budgets recalculés.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        delete_record_control("task", task_data, ["Référence", "Titre"], f"tasks_{project_id}")

    with grouped_tab:
        show_grouped_tasks(task_data)

    with create_tab:
        with st.form("task_form"):
            title = st.text_input("Titre")
            c1, c2, c3, c4 = st.columns(4)
            level = c1.selectbox("Niveau", [1, 2, 3, 4])
            status = c2.selectbox("Statut", ["Non commencé", "En cours", "En attente", "Bloqué", "Terminé"], index=0)
            priority = c3.selectbox("Priorité", ["Basse", "Normale", "Haute", "Critique"], index=1)
            progress = c4.slider("Avancement", 0, 100, 0)
            parent_label = st.selectbox("Parent", [""] + list(task_labels.keys()))
            c5, c6, c7, c8 = st.columns(4)
            start = c5.date_input("Début", value=date.today())
            end = c6.date_input("Fin estimée", value=date.today())
            planned_hours = c7.number_input("Temps prévu", min_value=0.0, step=1.0)
            planned_cost = c8.number_input("Coût prévu", min_value=0.0, step=100.0)
            budget_label = st.selectbox("Budget de rattachement", [""] + list(budget_labels.keys()))
            starcost = st.checkbox("STARCOST")
            actual_expense = st.number_input("Montant déjà dépensé sur la tâche", min_value=0.0, step=100.0)
            assigned_label = st.selectbox("Ressource principale", [""] + list(users.keys()))
            description = st.text_area("Description")
            submitted = st.form_submit_button("Créer la tâche")
        if submitted:
            try:
                with session_scope() as session:
                    create_task(
                        session,
                        project_id,
                        budget_labels.get(budget_label),
                        title,
                        level,
                        task_labels.get(parent_label),
                        status,
                        priority,
                        start,
                        end,
                        planned_hours,
                        planned_cost,
                        actual_expense,
                        progress,
                        users.get(assigned_label),
                        starcost,
                        description,
                    )
                st.success("Tâche créée.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with task_budget_tab:
        if task_data.empty:
            st.info("Aucune tâche disponible.")
        else:
            with st.form("task_budget_form"):
                task_label = st.selectbox("Tâche", list(task_labels.keys()))
                current = task_data.loc[task_data["ID"] == task_labels[task_label]].iloc[0]
                budget_values = [""] + list(budget_labels.keys())
                current_budget = current.get("Budget", "")
                current_index = budget_values.index(current_budget) if current_budget in budget_values else 0
                budget_label = st.selectbox("Budget affecté", budget_values, index=current_index)
                actual_expense = st.number_input(
                    "Dépense directe de la tâche",
                    min_value=0.0,
                    value=float(current.get("Dépense directe", 0.0)),
                    step=100.0,
                )
                st.caption("Le réel du budget = coût des temps pointés sur ses tâches + dépenses directes de ces tâches.")
                submitted = st.form_submit_button("Mettre à jour et recalculer")
            if submitted:
                with session_scope() as session:
                    update_task_budget_and_expense(
                        session,
                        task_labels[task_label],
                        budget_labels.get(budget_label),
                        actual_expense,
                    )
                st.success("Budget de tâche mis à jour et budget projet recalculé.")
                st.rerun()

    with deps_tab:
        with st.form("dependency_form"):
            c1, c2, c3, c4 = st.columns([3, 3, 2, 1])
            pred_label = c1.selectbox("Prédécesseur", list(task_labels.keys()))
            succ_label = c2.selectbox("Successeur", list(task_labels.keys()))
            link_type = c3.selectbox("Type", ["Fin-Début", "Début-Début", "Fin-Fin"])
            lag_days = c4.number_input("Décalage", value=0, step=1)
            submitted = st.form_submit_button("Ajouter le lien")
        if submitted:
            try:
                with session_scope() as session:
                    add_dependency(session, task_labels[pred_label], task_labels[succ_label], link_type, int(lag_days))
                st.success("Dépendance ajoutée.")
                st.rerun()
            except IntegrityError:
                st.error("Cette dépendance existe déjà.")
            except Exception as exc:
                st.error(str(exc))

        if deps.empty:
            st.info("Aucune dépendance.")
        else:
            deps_display = deps[["Prédécesseur", "Successeur", "Type", "Décalage"]]
            deps_visible_columns = grid_column_visibility_selector(
                "task_dependencies_grid",
                list(deps_display.columns),
                required_columns=["Prédécesseur", "Successeur"],
            )
            st.dataframe(
                styled_plain_table(deps_display[visible_columns_for_editor(deps_display, deps_visible_columns)]),
                width="stretch",
                hide_index=True,
            )
            delete_record_control("dependency", deps, ["Prédécesseur", "Successeur"], f"dependencies_{project_id}")

    with assign_tab:
        with st.form("assignment_form"):
            c1, c2 = st.columns(2)
            task_label = c1.selectbox("Tâche", list(task_labels.keys()))
            user_label = c2.selectbox("Utilisateur", list(users.keys()))
            c3, c4, c5 = st.columns(3)
            role = c3.text_input("Rôle", value="Contributeur")
            planned_hours = c4.number_input("Charge prévue", min_value=0.0, step=1.0)
            cost_rate = c5.number_input("Taux horaire", min_value=0.0, value=85.0, step=5.0)
            submitted = st.form_submit_button("Affecter")
        if submitted:
            try:
                with session_scope() as session:
                    add_assignment(session, task_labels[task_label], users[user_label], role, planned_hours, cost_rate)
                st.success("Affectation ajoutée.")
                st.rerun()
            except IntegrityError:
                st.error("Cet utilisateur est déjà affecté à cette tâche.")

        if assignments.empty:
            st.info("Aucune affectation.")
        else:
            assignments_visible_columns = grid_column_visibility_selector(
                "assignments_grid",
                list(assignments.columns),
                required_columns=["Tâche", "Utilisateur"],
                technical_columns={"ID", "Tâche ID", "Utilisateur ID"},
            )
            st.dataframe(
                styled_plain_table(assignments[visible_columns_for_editor(assignments, assignments_visible_columns)]),
                width="stretch",
                hide_index=True,
            )
            delete_record_control("assignment", assignments, ["Tâche", "Utilisateur"], f"assignments_{project_id}")


def legacy_show_timesheet() -> None:
    st.title("Timesheet")
    project_id = select_project()
    if not project_id:
        return
    with session_scope() as session:
        users = user_options(session)
        user_names = user_name_options(session)
        task_labels = direct_task_options(session, project_id)
        entries = time_entries_df(session, project_id)

    st.caption("La Timesheet accepte uniquement les tâches directes, sans sous-tâches. Les tâches agrégées sont exclues.")
    invalid_entries = entries[~entries["Tâche"].isin(task_labels.keys())] if not entries.empty else entries
    if not invalid_entries.empty:
        st.warning(
            f"{len(invalid_entries)} pointage(s) existant(s) sont rattaché(s) à une tâche agrégée. "
            "Réaffectez-les à une tâche directe ou supprimez-les avant d'enregistrer les modifications."
        )

    if not task_labels:
        st.info("Aucune tâche directe disponible pour ce projet.")
    else:
        with st.form("time_form"):
            c1, c2, c3, c4 = st.columns([2, 4, 3, 2])
            entry_date = c1.date_input("Date", value=date.today())
            task_label = c2.selectbox("Tâche directe", list(task_labels.keys()))
            user_label = c3.selectbox("Utilisateur", list(users.keys()))
            hours = c4.number_input("Heures", min_value=0.0, max_value=24.0, step=0.25)
            note = st.text_area("Note")
            submitted = st.form_submit_button("Enregistrer le temps")
        if submitted:
            with session_scope() as session:
                add_time_entry(session, project_id, task_labels[task_label], users[user_label], entry_date, hours, note)
            st.success("Temps enregistré : la tâche et son budget sont recalculés.")
            st.rerun()

    st.plotly_chart(hours_by_user_bar(entries), use_container_width=True)
    save_legacy_timesheet = top_right_save_button(f"legacy_timesheet_save_{project_id}")
    legacy_time_visible_columns = grid_column_visibility_selector(
        "legacy_timesheet_grid",
        list(entries.columns),
        required_columns=["Date", "Tâche", "Heures"],
        technical_columns={"ID", "Projet ID", "Tâche ID", "Utilisateur ID"},
    )
    edited_entries = st.data_editor(
        entries,
        key=f"time_editor_{project_id}",
        use_container_width=True,
        hide_index=True,
        column_order=visible_columns_for_editor(entries, legacy_time_visible_columns),
        disabled=["ID", "Projet", "Taux", "Coût"],
        column_config={
            "Date": st.column_config.DateColumn("Date"),
            "Tâche": st.column_config.SelectboxColumn("Tâche", options=list(task_labels.keys())),
            "Utilisateur": st.column_config.SelectboxColumn("Utilisateur", options=list(user_names.keys())),
            "Heures": st.column_config.NumberColumn("Heures", min_value=0.0, max_value=24.0, step=0.25),
        },
    )
    if save_legacy_timesheet:
        try:
            with session_scope() as session:
                update_time_entries_from_df(session, edited_entries, project_id)
            st.success("Pointages mis à jour, tâches et budgets recalculés.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


    delete_record_control("time_entry", entries, ["Date", "Tâche", "Utilisateur"], f"time_entries_{project_id}")


def show_weekly_time_capture(
    title: str,
    key_prefix: str,
    weekly_df_func,
    entries_df_func,
    save_weekly_func,
    update_entries_func,
    delete_entity: str,
    history_title: str,
    empty_grid_message: str,
    empty_history_message: str,
    save_success: str,
    update_success: str,
    caption_extra: str = "",
    title_level: str = "title",
    filters_container=None,
    filter_columns=None,
) -> None:
    if title:
        if title_level == "subheader":
            st.subheader(title)
        else:
            st.title(title)

    with session_scope() as session:
        project_labels = project_options(session)
        user_names = user_name_options(session)

    if not project_labels:
        st.warning("Créez d'abord un projet.")
        return
    if not user_names:
        st.warning("Aucun utilisateur actif disponible.")
        return

    project_label_list = list(project_labels.keys())
    project_label_by_id = {project_id: label for label, project_id in project_labels.items()}
    default_project = project_label_by_id.get(st.session_state.get("selected_project_id"), project_label_list[0])
    project_selector_key = f"{key_prefix}_project_labels"
    existing_projects = st.session_state.get(project_selector_key)
    if isinstance(existing_projects, list):
        valid_existing = [label for label in existing_projects if label in project_labels]
        st.session_state[project_selector_key] = valid_existing or [default_project]
    else:
        st.session_state[project_selector_key] = [default_project]

    user_labels = list(user_names.keys())
    current_user_name = st.session_state.get("user", {}).get("name")
    user_selector_key = f"{key_prefix}_user_name"
    if st.session_state.get(user_selector_key) not in user_labels:
        st.session_state[user_selector_key] = current_user_name if current_user_name in user_labels else user_labels[0]

    week_key = f"{key_prefix}_week"
    if week_key not in st.session_state:
        st.session_state[week_key] = week_start(date.today())

    if filter_columns is None:
        controls_container = filters_container or sticky_toolbar(f"{key_prefix}_entry")
        with controls_container:
            project_col, user_col, week_prev_col, week_date_col, week_next_col = st.columns(
                [2.75, 1.3, 0.32, 0.95, 0.32],
                vertical_alignment="bottom",
            )
    else:
        project_col, user_col, week_prev_col, week_date_col, week_next_col = filter_columns

    selected_project_labels = project_col.multiselect(
        "Projets",
        project_label_list,
        key=project_selector_key,
        format_func=lambda label: str(label).split(" - ", 1)[0] if filter_columns is not None else label,
    )
    selected_user = user_col.selectbox("Utilisateur", user_labels, key=user_selector_key)

    if week_prev_col.button("‹", key=f"{week_key}_previous", use_container_width=True):
        st.session_state[week_key] = week_start(st.session_state[week_key]) - timedelta(days=7)
        st.rerun()
    selected_day = week_date_col.date_input("Semaine", key=week_key)
    if week_next_col.button("›", key=f"{week_key}_next", use_container_width=True):
        st.session_state[week_key] = week_start(st.session_state[week_key]) + timedelta(days=7)
        st.rerun()

    user_id = user_names[selected_user]

    if not selected_project_labels:
        st.warning("Sélectionnez au moins un projet pour afficher la grille.")
        return

    selected_project_ids = [project_labels[label] for label in selected_project_labels]
    st.session_state["selected_project_id"] = selected_project_ids[0]
    project_key = "_".join(str(project_id) for project_id in selected_project_ids)

    selected_week = week_start(selected_day)
    iso_year, iso_week, _ = selected_week.isocalendar()
    week_end = selected_week + timedelta(days=6)
    st.subheader(f"Semaine {iso_week}/{iso_year}")
    caption = (
        f"Du {selected_week:%d/%m/%Y} au {week_end:%d/%m/%Y}. "
        "Les tâches agrégées sont visibles en gris et verrouillées à la saisie."
    )
    if caption_extra:
        caption = f"{caption} {caption_extra}"
    st.caption(caption)

    with session_scope() as session:
        weekly_frames = []
        entry_frames = []
        for project_label, project_id in zip(selected_project_labels, selected_project_ids, strict=False):
            project_week = weekly_df_func(session, project_id, user_id, selected_week)
            if not project_week.empty:
                project_week = project_week.copy()
                project_week.insert(0, "Projet ID", project_id)
                project_week.insert(1, "Projet", project_label)
                weekly_frames.append(project_week)
            project_entries = entries_df_func(session, project_id)
            if not project_entries.empty:
                entry_frames.append(project_entries)
        weekly_data = pd.concat(weekly_frames, ignore_index=True) if weekly_frames else pd.DataFrame()
        entries = pd.concat(entry_frames, ignore_index=True) if entry_frames else pd.DataFrame()

    day_columns = [label for _, label in week_day_columns(selected_week)]
    if weekly_data.empty:
        st.info(empty_grid_message)
    else:
        save_week = top_right_save_button(f"{key_prefix}_save_week")
        edited_week = weekly_timesheet_editor(
            weekly_data,
            day_columns,
            project_key,
            user_id,
            selected_week,
            grid_key_prefix=f"weekly_{key_prefix}",
            user_label=selected_user,
        )
        editable_rows = (
            edited_week["_time_editable"].astype(str).str.lower().isin(["true", "1", "yes"])
            if "_time_editable" in edited_week.columns
            else pd.Series(True, index=edited_week.index)
        )
        direct_week = edited_week[editable_rows]
        daily_totals = direct_week[day_columns].apply(pd.to_numeric, errors="coerce").fillna(0).sum()
        total_hours = float(daily_totals.sum())
        st.caption("Total semaine : " + f"{total_hours:.2f} h")
        st.dataframe(
            styled_plain_table(pd.DataFrame([{"Jour": day, "Heures": float(hours)} for day, hours in daily_totals.items()])),
            use_container_width=True,
            hide_index=True,
        )

        if save_week:
            try:
                with session_scope() as session:
                    project_id_values = pd.to_numeric(edited_week["Projet ID"], errors="coerce")
                    for project_id in selected_project_ids:
                        project_week = edited_week[project_id_values == project_id]
                        if not project_week.empty:
                            save_weekly_func(session, project_id, user_id, selected_week, project_week)
                st.success(save_success)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    st.subheader(history_title)
    user_entries = entries[entries["Utilisateur"] == selected_user].copy() if not entries.empty else entries
    if user_entries.empty:
        st.info(empty_history_message)
        return

    with session_scope() as session:
        task_labels = {}
        for project_id in selected_project_ids:
            task_labels.update(direct_task_options(session, project_id))

    disabled_columns = ["ID", "Projet", "Utilisateur"] + [
        column for column in ["Taux", "Coût"] if column in user_entries.columns
    ]
    save_history = top_right_save_button(f"{key_prefix}_save_history", button_type="secondary")
    history_visible_columns = grid_column_visibility_selector(
        f"{key_prefix}_history_grid",
        list(user_entries.columns),
        required_columns=["Date", "Tâche"],
        technical_columns={"ID", "Projet ID", "Tâche ID", "Utilisateur ID"},
    )
    edited_entries = st.data_editor(
        user_entries,
        key=f"{key_prefix}_history_editor_{project_key}_{user_id}",
        use_container_width=True,
        hide_index=True,
        column_order=visible_columns_for_editor(user_entries, history_visible_columns),
        disabled=disabled_columns,
        column_config={
            "Date": st.column_config.DateColumn("Date"),
            "Tâche": st.column_config.SelectboxColumn("Tâche", options=list(task_labels.keys())),
            "Heures": st.column_config.NumberColumn("Heures", min_value=0.0, max_value=24.0, step=0.25),
        },
    )
    if save_history:
        try:
            with session_scope() as session:
                update_entries_func(session, edited_entries, None)
            st.success(update_success)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    delete_record_control(
        delete_entity,
        user_entries,
        ["Date", "Tâche", "Utilisateur"],
        f"{key_prefix}_entries_{project_key}_{user_id}",
    )


def show_time_recap(
    title: str,
    key_prefix: str,
    entries_df_func,
    default_start: date,
    empty_message: str,
    filters_container=None,
    filter_columns=None,
) -> None:
    st.subheader(title)
    if filter_columns is None:
        recap_controls = filters_container or sticky_toolbar(f"{key_prefix}_recap")
        with recap_controls:
            recap_date_col, filter_user_col, filter_project_col = st.columns(
                [1.1, 1.9, 1.9],
                vertical_alignment="bottom",
            )
    else:
        recap_date_col, filter_user_col, filter_project_col = filter_columns

    selected_day = recap_date_col.date_input(
        "Date de démarrage",
        value=default_start,
        key=f"{key_prefix}_recap_start",
    )
    selected_start = week_start(selected_day)
    selected_end = selected_start + timedelta(days=27)
    if selected_start != selected_day:
        st.caption(f"La date est alignée sur le lundi de la semaine : {selected_start:%d/%m/%Y}.")
    st.caption(f"Période affichée : du {selected_start:%d/%m/%Y} au {selected_end:%d/%m/%Y}.")

    with session_scope() as session:
        entries = entries_df_func(session, None)

    period_entries = entries.copy()
    if not period_entries.empty:
        period_entries["Date"] = pd.to_datetime(period_entries["Date"], errors="coerce").dt.date
        period_entries["Heures"] = pd.to_numeric(period_entries["Heures"], errors="coerce").fillna(0)
        period_entries = period_entries[
            period_entries["Date"].notna()
            & (period_entries["Date"] >= selected_start)
            & (period_entries["Date"] <= selected_end)
            & (period_entries["Heures"] > 0)
        ].copy()

    user_filter_options = (
        sorted(period_entries["Utilisateur"].dropna().astype(str).unique().tolist())
        if not period_entries.empty and "Utilisateur" in period_entries.columns
        else []
    )
    project_filter_options = (
        sorted(period_entries["Projet"].dropna().astype(str).unique().tolist())
        if not period_entries.empty and "Projet" in period_entries.columns
        else []
    )
    user_key = f"{key_prefix}_recap_users_{selected_start:%Y%m%d}"
    project_key = f"{key_prefix}_recap_projects_{selected_start:%Y%m%d}"
    if user_key not in st.session_state:
        st.session_state[user_key] = user_filter_options
    else:
        st.session_state[user_key] = [value for value in st.session_state[user_key] if value in user_filter_options]
    if project_key not in st.session_state:
        st.session_state[project_key] = project_filter_options
    else:
        st.session_state[project_key] = [value for value in st.session_state[project_key] if value in project_filter_options]

    selected_users = filter_user_col.multiselect(
        "Utilisateurs",
        user_filter_options,
        key=user_key,
        placeholder="Sélectionner un ou plusieurs utilisateurs",
    )
    selected_projects = filter_project_col.multiselect(
        "Projets",
        project_filter_options,
        key=project_key,
        placeholder="Sélectionner un ou plusieurs projets",
    )

    filtered_entries = period_entries.copy()
    if selected_users:
        filtered_entries = filtered_entries[filtered_entries["Utilisateur"].isin(selected_users)]
    else:
        filtered_entries = filtered_entries.iloc[0:0]
    if selected_projects:
        filtered_entries = filtered_entries[filtered_entries["Projet"].isin(selected_projects)]
    else:
        filtered_entries = filtered_entries.iloc[0:0]

    recap_data, day_specs = time_recap_table_data(filtered_entries, selected_start)
    day_fields = [str(spec["field"]) for spec in day_specs]
    total_hours = float(recap_data[day_fields].sum().sum()) if not recap_data.empty else 0.0
    c1, c2, c3 = st.columns(3)
    c1.metric("Utilisateurs", recap_data["Utilisateur"].nunique() if not recap_data.empty else 0)
    c2.metric("Tâches", recap_data["Tâche"].nunique() if not recap_data.empty else 0)
    c3.metric("Heures", f"{total_hours:.2f} h")
    if recap_data.empty:
        st.info(empty_message)
        return
    time_recap_grid(recap_data, day_specs, key=f"{key_prefix}_recap_grid_{selected_start:%Y%m%d}")


def show_timesheet() -> None:
    header = sticky_page_header("timesheet")
    timesheet_views = ["Saisie", "Récap."]
    legacy_timesheet_views = {"Saisie Timesheet": "Saisie", "Récap. Timesheet": "Récap."}
    if st.session_state.get("timesheet_view") in legacy_timesheet_views:
        st.session_state["timesheet_view"] = legacy_timesheet_views[st.session_state["timesheet_view"]]
    current_view = st.session_state.get("timesheet_view", timesheet_views[0])
    if current_view not in timesheet_views:
        st.session_state["timesheet_view"] = timesheet_views[0]
        current_view = timesheet_views[0]
    with header:
        if current_view == "Saisie":
            title_col, view_col, project_col, user_col, prev_col, week_col, next_col = st.columns(
                [0.72, 0.55, 1.7, 0.9, 0.24, 0.72, 0.24],
                vertical_alignment="bottom",
            )
        else:
            title_col, view_col, date_col, users_col, projects_col = st.columns(
                [0.72, 0.55, 0.85, 1.55, 1.55],
                vertical_alignment="bottom",
            )
        with title_col:
            sticky_header_title("Timesheet")
        active_view = view_col.selectbox(
            "Vue Timesheet",
            timesheet_views,
            index=timesheet_views.index(current_view),
            key="timesheet_view",
        )
    if active_view == "Saisie":
        show_weekly_time_capture(
            title="Saisie hebdomadaire",
            key_prefix="timesheet",
            weekly_df_func=weekly_timesheet_df,
            entries_df_func=time_entries_df,
            save_weekly_func=save_weekly_timesheet,
            update_entries_func=update_time_entries_from_df,
            delete_entity="time_entry",
            history_title="Historique des pointages",
            empty_grid_message="Aucune tâche disponible pour les projets sélectionnés.",
            empty_history_message="Aucun pointage pour cet utilisateur sur les projets sélectionnés.",
            save_success="Pointages hebdomadaires enregistrés, tâches et budgets recalculés.",
            update_success="Pointages mis à jour, tâches et budgets recalculés.",
            title_level="subheader",
            filters_container=header,
            filter_columns=(project_col, user_col, prev_col, week_col, next_col),
        )
    else:
        show_time_recap(
            title="Récap. Timesheet",
            key_prefix="timesheet",
            entries_df_func=time_entries_df,
            default_start=week_start(date.today()) - timedelta(weeks=3),
            empty_message="Aucun pointage sur les 4 semaines affichées.",
            filters_container=header,
            filter_columns=(date_col, users_col, projects_col),
        )


def show_planning() -> None:
    header = sticky_page_header("planning")
    planning_views = ["Saisie", "Récap."]
    legacy_planning_views = {"Saisie Planification": "Saisie", "Récap. Planification": "Récap."}
    if st.session_state.get("planning_view") in legacy_planning_views:
        st.session_state["planning_view"] = legacy_planning_views[st.session_state["planning_view"]]
    current_view = st.session_state.get("planning_view", planning_views[0])
    if current_view not in planning_views:
        st.session_state["planning_view"] = planning_views[0]
        current_view = planning_views[0]
    with header:
        if current_view == "Saisie":
            title_col, view_col, project_col, user_col, prev_col, week_col, next_col = st.columns(
                [0.9, 0.55, 1.55, 0.85, 0.24, 0.72, 0.24],
                vertical_alignment="bottom",
            )
        else:
            title_col, view_col, date_col, users_col, projects_col = st.columns(
                [0.9, 0.55, 0.85, 1.45, 1.45],
                vertical_alignment="bottom",
            )
        with title_col:
            sticky_header_title("Planification")
        active_view = view_col.selectbox(
            "Vue Planification",
            planning_views,
            index=planning_views.index(current_view),
            key="planning_view",
        )
    if active_view == "Saisie":
        show_weekly_time_capture(
            title="Saisie hebdomadaire",
            key_prefix="planning",
            weekly_df_func=weekly_planning_df,
            entries_df_func=planned_time_entries_df,
            save_weekly_func=save_weekly_planning,
            update_entries_func=update_planned_time_entries_from_df,
            delete_entity="planned_time_entry",
            history_title="Historique de planification",
            empty_grid_message="Aucune tâche disponible pour les projets sélectionnés.",
            empty_history_message="Aucune planification pour cet utilisateur sur les projets sélectionnés.",
            save_success="Planification hebdomadaire enregistrée. Le temps planifié futur des tâches est à jour.",
            update_success="Planification mise à jour. Le temps planifié futur des tâches est à jour.",
            caption_extra="Seules les dates à partir d'aujourd'hui alimentent le champ Temps planifié des tâches.",
            title_level="subheader",
            filters_container=header,
            filter_columns=(project_col, user_col, prev_col, week_col, next_col),
        )
    else:
        show_time_recap(
            title="Récap. Planification",
            key_prefix="planning",
            entries_df_func=planned_time_entries_df,
            default_start=week_start(date.today()),
            empty_message="Aucune planification sur les 4 semaines affichées.",
            filters_container=header,
            filter_columns=(date_col, users_col, projects_col),
        )


def legacy_show_budget_lines() -> None:
    st.title("Budget")
    project_id = select_project()
    if not project_id:
        return
    with session_scope() as session:
        data = budget_df(session, project_id)

    with st.form("budget_form"):
        c1, c2 = st.columns([2, 4])
        category = c1.selectbox("Catégorie", ["Phase", "Main d'oeuvre", "Outillage", "Sous-traitance", "Recette", "Divers"])
        label = c2.text_input("Libellé")
        c3, c4 = st.columns(2)
        planned = c3.number_input("Prévu", min_value=0.0, step=100.0)
        committed = c4.number_input("Engagé", min_value=0.0, step=100.0)
        st.caption("Le réel est calculé depuis les tâches rattachées : temps pointé valorisé + dépenses directes.")
        submitted = st.form_submit_button("Ajouter la ligne")
    if submitted:
        with session_scope() as session:
            add_budget_line(session, project_id, category, label, planned, committed)
        st.success("Ligne budgétaire ajoutée.")
        st.rerun()

    c1, c2 = st.columns(2)
    c1.plotly_chart(budget_bar(data), use_container_width=True)
    c2.plotly_chart(budget_pie(data), use_container_width=True)
    if not data.empty:
        totals = data[["Prévu", "Engagé", "Réel", "Reste"]].sum()
        c3, c4, c5, c6 = st.columns(4)
        c3.metric("Prévu", eur(totals["Prévu"]))
        c4.metric("Engagé", eur(totals["Engagé"]))
        c5.metric("Réel", eur(totals["Réel"]))
        c6.metric("Reste", eur(totals["Reste"]))
    save_legacy_budget = top_right_save_button(f"legacy_budget_save_{project_id}")
    legacy_budget_visible_columns = grid_column_visibility_selector(
        "legacy_budget_grid",
        list(data.columns),
        required_columns=["Catégorie", "Libellé"],
        technical_columns={"ID", "Projet ID"},
    )
    edited_budget = st.data_editor(
        data,
        key=f"budget_editor_{project_id}",
        use_container_width=True,
        hide_index=True,
        column_order=visible_columns_for_editor(data, legacy_budget_visible_columns),
        disabled=[
            "ID",
            "Projet ID",
            "Projet",
            "Coût tâches prévu",
            "Temps passé",
            "Coût temps réel",
            "Dépenses tâches",
            "Réel",
            "Tâches",
            "Tâches détail",
            "Reste",
        ],
        column_config={
            "Catégorie": st.column_config.SelectboxColumn(
                "Catégorie", options=["Phase", "Main d'oeuvre", "Outillage", "Sous-traitance", "Recette", "Divers"]
            ),
            "Prévu": st.column_config.NumberColumn("Prévu", min_value=0.0, step=100.0),
            "Engagé": st.column_config.NumberColumn("Engagé", min_value=0.0, step=100.0),
        },
    )
    if save_legacy_budget:
        try:
            with session_scope() as session:
                update_budget_from_df(session, edited_budget)
            st.success("Budgets mis à jour, réel recalculé.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def show_budget() -> None:
    header = sticky_page_header("budget")
    with header:
        title_col, filter_col = st.columns([0.8, 3.2], vertical_alignment="center")
        with title_col:
            sticky_header_title("Budget")
        with filter_col:
            project_id = select_project()
    if not project_id:
        return

    with session_scope() as session:
        data = budget_df(session, project_id)
        lines = budget_lines_df(session, project_id)
        budget_labels = budget_options(session, project_id)

    with st.expander("Créer un budget", expanded=False):
        with st.form("budget_header_form"):
            c1, c2 = st.columns([4, 1])
            label = c1.text_input("Libellé du budget")
            status = c2.selectbox("Statut", ["Actif", "En attente", "Clôturé"])
            submitted = st.form_submit_button("Créer le budget")
        if submitted:
            if not label.strip():
                st.error("Le libellé du budget est obligatoire.")
            else:
                with session_scope() as session:
                    budget = add_budget(session, project_id, label, status)
                st.success(f"Budget créé : {budget.reference}")
                st.rerun()

    if data.empty:
        st.info("Aucun budget pour ce projet.")
    else:
        totals = data[["Prévu", "Engagé", "Reste"]].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Prévu", eur(totals["Prévu"]))
        c2.metric("Engagé", eur(totals["Engagé"]))
        c3.metric("Reste", eur(totals["Reste"]))

        c4, c5 = st.columns(2)
        c4.plotly_chart(budget_bar(data), use_container_width=True)
        c5.plotly_chart(budget_pie(data), use_container_width=True)

        st.subheader("Budgets")
        save_budget = top_right_save_button(f"budget_header_save_{project_id}")
        display_columns = [
            "ID",
            "Projet ID",
            "Projet",
            "Référence",
            "Budget",
            "Statut",
            "Prévu",
            "Engagé",
            "Reste",
            "Tâches",
            "Lignes de frais",
        ]
        budget_editor_data = data[[column for column in display_columns if column in data.columns]]
        budget_visible_columns = grid_column_visibility_selector(
            "budget_header_grid",
            list(budget_editor_data.columns),
            required_columns=["Référence", "Budget"],
            technical_columns={"ID", "Projet ID"},
        )
        edited_budget = st.data_editor(
            budget_editor_data,
            key=f"budget_header_editor_{project_id}",
            use_container_width=True,
            hide_index=True,
            column_order=visible_columns_for_editor(budget_editor_data, budget_visible_columns),
            disabled=[
                "ID",
                "Projet ID",
                "Projet",
                "Référence",
                "Prévu",
                "Engagé",
                "Reste",
                "Tâches",
                "Lignes de frais",
            ],
            column_config={
                "Statut": st.column_config.SelectboxColumn("Statut", options=["Actif", "En attente", "Clôturé"]),
                "Prévu": st.column_config.NumberColumn("Prévu", format="%.2f €"),
                "Engagé": st.column_config.NumberColumn("Engagé", format="%.2f €"),
                "Reste": st.column_config.NumberColumn("Reste", format="%.2f €"),
            },
        )
        if save_budget:
            try:
                with session_scope() as session:
                    update_budget_from_df(session, edited_budget)
                st.success("Budgets mis à jour.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        delete_record_control("budget", data, ["Référence", "Budget"], f"budgets_{project_id}")

    st.divider()
    st.subheader("Lignes de frais")
    with st.form("budget_line_form"):
        c1, c2, c3 = st.columns([3, 2, 4])
        budget_label = c1.selectbox("Budget", list(budget_labels.keys()) if budget_labels else [""])
        category = c2.selectbox("Catégorie", ["Phase", "Main d'oeuvre", "Outillage", "Sous-traitance", "Recette", "Divers"])
        label = c3.text_input("Libellé")
        planned = st.number_input("Montant prévu", min_value=0.0, step=100.0)
        submitted = st.form_submit_button("Ajouter la ligne de frais")
    if submitted:
        if not budget_labels or not budget_label:
            st.error("Créez d'abord un budget.")
        elif not label.strip():
            st.error("Le libellé de la ligne est obligatoire.")
        else:
            with session_scope() as session:
                add_budget_line(session, budget_labels[budget_label], category, label, planned)
            st.success("Ligne de frais ajoutée.")
            st.rerun()

    if lines.empty:
        st.info("Aucune ligne de frais pour ce projet.")
        return

    save_lines = top_right_save_button(f"budget_line_save_{project_id}")
    line_visible_columns = grid_column_visibility_selector(
        "budget_lines_grid",
        list(lines.columns),
        required_columns=["Budget", "Libellé"],
        technical_columns={"ID", "Projet ID", "Budget ID"},
    )
    edited_lines = st.data_editor(
        lines,
        key=f"budget_line_editor_{project_id}",
        use_container_width=True,
        hide_index=True,
        column_order=visible_columns_for_editor(lines, line_visible_columns),
        disabled=["ID", "Projet ID", "Budget ID", "Projet"],
        column_config={
            "Budget": st.column_config.SelectboxColumn("Budget", options=list(budget_labels.keys())),
            "Catégorie": st.column_config.SelectboxColumn(
                "Catégorie", options=["Phase", "Main d'oeuvre", "Outillage", "Sous-traitance", "Recette", "Divers"]
            ),
            "Prévu": st.column_config.NumberColumn("Prévu", min_value=0.0, step=100.0, format="%.2f €"),
        },
    )
    if save_lines:
        try:
            with session_scope() as session:
                update_budget_lines_from_df(session, edited_lines, project_id)
            st.success("Lignes de frais mises à jour, budgets recalculés.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    delete_record_control("budget_line", lines, ["Budget", "Catégorie", "Libellé"], f"budget_lines_{project_id}")


def risk_matrix_figure(paths: list[dict]) -> go.Figure:
    likelihoods = ["A", "B", "C", "D", "E"]
    consequences = [1, 2, 3, 4, 5]
    ranks = {"Low": 0, "Medium": 1, "High": 2, "Extreme": 3}
    colors = ["#dcfce7", "#fef3c7", "#fed7aa", "#fecaca"]
    z = [[ranks[RISK_MATRIX[likelihood][consequence - 1]] for consequence in consequences] for likelihood in likelihoods]
    text_values = [[RISK_MATRIX[likelihood][consequence - 1] for consequence in consequences] for likelihood in likelihoods]
    figure = go.Figure(
        go.Heatmap(
            x=consequences,
            y=likelihoods,
            z=z,
            text=text_values,
            texttemplate="%{text}",
            hovertemplate="Vraisemblance %{y}<br>Conséquence %{x}<br>Niveau %{text}<extra></extra>",
            colorscale=[
                [0.00, colors[0]], [0.2499, colors[0]],
                [0.25, colors[1]], [0.4999, colors[1]],
                [0.50, colors[2]], [0.7499, colors[2]],
                [0.75, colors[3]], [1.00, colors[3]],
            ],
            zmin=0,
            zmax=3,
            showscale=False,
            xgap=2,
            ygap=2,
        )
    )
    for path in paths:
        points = path["points"]
        for index, point in enumerate(points):
            figure.add_trace(
                go.Scatter(
                    x=[point["consequence"]],
                    y=[point["likelihood"]],
                    mode="markers+text" if index == 0 else "markers",
                    text=[path["reference"]] if index == 0 else None,
                    textposition="top center",
                    marker={"size": 11, "color": "#0b2a59", "line": {"color": "white", "width": 2}},
                    hovertemplate=f"{path['reference']}<br>{path['hazard']}<br>{point['kind']}<extra></extra>",
                    showlegend=False,
                )
            )
            if index:
                previous = points[index - 1]
                figure.add_annotation(
                    x=point["consequence"], y=point["likelihood"],
                    ax=previous["consequence"], ay=previous["likelihood"],
                    xref="x", yref="y", axref="x", ayref="y",
                    showarrow=True, arrowhead=3, arrowsize=1.2, arrowwidth=2, arrowcolor="#2563eb",
                )
        pending = path.get("pending_target")
        if pending:
            previous = points[-1]
            figure.add_trace(
                go.Scatter(
                    x=[previous["consequence"], pending["consequence"]],
                    y=[previous["likelihood"], pending["likelihood"]],
                    mode="lines+markers",
                    line={"color": "#64748b", "width": 2, "dash": "dot"},
                    marker={"symbol": ["circle", "diamond-open"], "size": [1, 12]},
                    hovertemplate="Cible non vérifiée<extra></extra>",
                    showlegend=False,
                )
            )
    figure.update_layout(
        height=510,
        margin={"l": 80, "r": 25, "t": 35, "b": 70},
        plot_bgcolor="white",
        xaxis={"title": "Conséquence", "tickmode": "array", "tickvals": consequences, "side": "bottom", "fixedrange": True},
        yaxis={"title": "Vraisemblance", "categoryorder": "array", "categoryarray": list(reversed(likelihoods)), "fixedrange": True},
    )
    return figure


def _option_label(options: dict[str, int], selected_id: int | None) -> str | None:
    return next((label for label, value in options.items() if value == selected_id), None)


def show_risks() -> None:
    header = sticky_page_header("risks")
    with header:
        title_col, project_col, analysis_col = st.columns([1.0, 1.4, 2.2], vertical_alignment="center")
        with title_col:
            sticky_header_title("Gestion des risques")
        with project_col:
            project_id = select_project()
        with session_scope() as session:
            header_assessments = risk_assessments_df(session, project_id) if project_id else pd.DataFrame()
        assessment_options = {
            f"{row['Référence']} - {row['Analyse']}": int(row["ID"])
            for row in header_assessments.to_dict("records")
        }
        with analysis_col:
            selected_labels = st.multiselect(
                "Analyses",
                list(assessment_options),
                default=list(assessment_options),
                key=f"risk_analysis_filter_{project_id}",
                placeholder="Toutes les analyses",
            )
    if not project_id:
        return

    selected_ids = [assessment_options[label] for label in selected_labels]
    with session_scope() as session:
        project = get_project(session, project_id)
        users = user_options(session)
        tasks = task_options(session, project_id)
        assessments = risk_assessments_df(session, project_id)
        risks = risks_df(session, selected_ids)
        paths = risk_matrix_paths(session, selected_ids)
        metrics = risk_kpis(session, project_id)

    can_manage_risks = st.session_state["user"]["role"] in {"manager", "admin"}
    if not can_manage_risks:
        st.info("Lecture seule : la modification des analyses de risques est réservée aux managers et administrateurs.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Analyses", metrics["analyses"])
        c2.metric("Risques", len(risks))
        c3.metric("High / Extreme", sum(level in {"High", "Extreme"} for level in risks.get("Niveau courant", [])))
        c4.metric("À statuer", sum(value == "À statuer" for value in risks.get("Acceptation", [])))
        st.subheader("Matrice des risques")
        st.plotly_chart(risk_matrix_figure(paths), use_container_width=True, config={"displaylogo": False})
        st.subheader("Registre des risques")
        if risks.empty:
            st.info("Aucun risque dans les analyses sélectionnées.")
        else:
            st.dataframe(risks.drop(columns=["ID", "Analyse ID"], errors="ignore"), use_container_width=True, hide_index=True)
        return

    with st.expander("Créer une analyse de risques", expanded=assessments.empty):
        with st.form(f"risk_assessment_create_{project_id}"):
            c1, c2, c3 = st.columns([2, 1, 1])
            analysis_title = c1.text_input("Titre de l'analyse")
            leader_label = c2.selectbox("Responsable", [""] + list(users))
            threshold = c3.selectbox("Seuil d'acceptation", ["Low", "Medium", "High", "Extreme"])
            product_or_change = st.text_input("Produit ou modification concernée")
            scope = st.text_area("Périmètre")
            c4, c5 = st.columns(2)
            assumptions = c4.text_area("Hypothèses")
            requirements = c5.text_area("Exigences applicables")
            c6, c7 = st.columns([1, 2])
            is_itns = c6.checkbox("ITNS")
            safety = c6.selectbox("Importance pour la sûreté", ["Non applicable", "Faible", "Modérée", "Élevée"])
            graded = c7.text_area("Justification de l'approche graduée")
            st.caption("Référentiel : ISO 9001:2026 · ISO 29001:2020 · ISO 19443:2018")
            create_assessment = st.form_submit_button("Créer l'analyse", type="primary")
        if create_assessment:
            try:
                with session_scope() as session:
                    created = create_risk_assessment(
                        session, project_id, analysis_title, users.get(leader_label), product_or_change,
                        scope, assumptions, requirements, threshold, is_itns, safety, graded,
                    )
                    record_audit(session, actor_user_id=int(st.session_state["user"]["id"]), source="ui", action="create", entity_type="risk_assessment", entity_id=created.id, after=created)
                st.success(f"Analyse créée : {created.reference}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Analyses", metrics["analyses"])
    c2.metric("Risques", len(risks))
    c3.metric("High / Extreme", sum(level in {"High", "Extreme"} for level in risks.get("Niveau courant", [])))
    c4.metric("À statuer", sum(value == "À statuer" for value in risks.get("Acceptation", [])))

    st.subheader("Matrice des risques")
    st.plotly_chart(risk_matrix_figure(paths), use_container_width=True, config={"displaylogo": False})
    st.caption("Trait plein : cotation résiduelle vérifiée. Trait pointillé et losange : cible en attente de vérification.")

    registry_tab, iterations_tab, analyses_tab = st.tabs(["Registre des risques", "Itérations et actions", "Analyses"])
    with registry_tab:
        if not selected_ids:
            st.info("Sélectionnez au moins une analyse dans le bandeau.")
        else:
            with st.expander("Ajouter un risque", expanded=risks.empty):
                with st.form(f"risk_create_{project_id}"):
                    c1, c2, c3 = st.columns([1.5, 1.2, 1.2])
                    target_analysis = c1.selectbox("Analyse", selected_labels)
                    phase = c2.selectbox("Phase du cycle de vie", RISK_LIFECYCLE_PHASES)
                    owner_label = c3.selectbox("Responsable du risque", [""] + list(users))
                    activity = st.text_input("Activité / fonction")
                    c4, c5 = st.columns(2)
                    hazard = c4.text_area("Danger / événement redouté")
                    cause = c5.text_area("Cause")
                    c6, c7 = st.columns(2)
                    consequence_text = c6.text_area("Conséquence potentielle")
                    controls = c7.text_area("Maîtrises existantes")
                    c8, c9 = st.columns(2)
                    likelihood = c8.selectbox("Vraisemblance initiale", list(RISK_LIKELIHOOD_DEFINITIONS), format_func=lambda value: f"{value} - {RISK_LIKELIHOOD_DEFINITIONS[value]}")
                    consequence = c9.selectbox("Conséquence initiale", list(RISK_CONSEQUENCE_DEFINITIONS), format_func=lambda value: f"{value} - {RISK_CONSEQUENCE_DEFINITIONS[value]}")
                    create_risk_clicked = st.form_submit_button("Ajouter le risque", type="primary")
                if create_risk_clicked:
                    try:
                        with session_scope() as session:
                            created = create_risk(
                                session, assessment_options[target_analysis], phase, activity, hazard, cause,
                                consequence_text, controls, users.get(owner_label), likelihood, consequence,
                            )
                            record_audit(session, actor_user_id=int(st.session_state["user"]["id"]), source="ui", action="create", entity_type="risk", entity_id=created.id, after=created)
                        st.success(f"Risque créé : {created.reference}")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            if risks.empty:
                st.info("Aucun risque dans les analyses sélectionnées.")
            else:
                visible = grid_column_visibility_selector(
                    "risks_grid", list(risks.columns),
                    required_columns=["Référence", "Danger", "Niveau courant", "Acceptation"],
                    technical_columns={"ID", "Analyse ID"},
                )
                st.dataframe(risks, use_container_width=True, hide_index=True, column_order=visible_columns_for_editor(risks, visible))
                risk_labels = {f"{row['Référence']} - {row['Danger']}": int(row["ID"]) for row in risks.to_dict("records")}
                edit_label = st.selectbox("Risque à modifier", list(risk_labels), key="risk_edit_select")
                edit_id = risk_labels[edit_label]
                with session_scope() as session:
                    item = session.get(Risk, edit_id)
                    owner_id = item.owner_id
                    values = {
                        "phase": item.lifecycle_phase, "activity": item.activity, "hazard": item.hazard,
                        "cause": item.cause or "", "consequence": item.potential_consequence,
                        "controls": item.existing_controls or "", "likelihood": item.initial_likelihood,
                        "severity": item.initial_consequence,
                    }
                with st.expander("Modifier le risque"):
                    with st.form(f"risk_edit_{edit_id}"):
                        ec1, ec2, ec3 = st.columns(3)
                        ephase = ec1.selectbox("Phase", RISK_LIFECYCLE_PHASES, index=RISK_LIFECYCLE_PHASES.index(values["phase"]) if values["phase"] in RISK_LIFECYCLE_PHASES else 0)
                        eowner = ec2.selectbox("Responsable", [""] + list(users), index=([""] + list(users)).index(_option_label(users, owner_id)) if _option_label(users, owner_id) else 0)
                        eactivity = ec3.text_input("Activité", values["activity"])
                        ehazard = st.text_area("Danger", values["hazard"])
                        ecause = st.text_area("Cause", values["cause"])
                        econsequence = st.text_area("Conséquence potentielle", values["consequence"])
                        econtrols = st.text_area("Maîtrises existantes", values["controls"])
                        ec4, ec5 = st.columns(2)
                        elikelihood = ec4.selectbox("Vraisemblance initiale", list(RISK_LIKELIHOOD_DEFINITIONS), index=list(RISK_LIKELIHOOD_DEFINITIONS).index(values["likelihood"]))
                        eseverity = ec5.selectbox("Conséquence initiale", list(RISK_CONSEQUENCE_DEFINITIONS), index=list(RISK_CONSEQUENCE_DEFINITIONS).index(values["severity"]))
                        save_risk = st.form_submit_button("Enregistrer", type="primary")
                    if save_risk:
                        try:
                            with session_scope() as session:
                                updated = update_risk(session, edit_id, lifecycle_phase=ephase, owner_id=users.get(eowner), activity=eactivity, hazard=ehazard, cause=ecause, potential_consequence=econsequence, existing_controls=econtrols, initial_likelihood=elikelihood, initial_consequence=eseverity)
                                record_audit(session, actor_user_id=int(st.session_state["user"]["id"]), source="ui", action="update", entity_type="risk", entity_id=updated.id, after=updated)
                            st.success("Risque mis à jour.")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                delete_record_control("risk", risks, ["Référence", "Danger"], f"risks_{project_id}")

    with iterations_tab:
        if risks.empty:
            st.info("Créez d'abord un risque.")
        else:
            risk_labels = {f"{row['Référence']} - {row['Danger']}": int(row["ID"]) for row in risks.to_dict("records")}
            selected_risk_label = st.selectbox("Risque", list(risk_labels), key="risk_iteration_risk")
            risk_id = risk_labels[selected_risk_label]
            with session_scope() as session:
                iterations = risk_iterations_df(session, risk_id)
            with st.expander("Ajouter une itération de réduction", expanded=iterations.empty):
                with st.form(f"risk_iteration_create_{risk_id}"):
                    treatment = st.text_area("Traitement décidé")
                    c1, c2 = st.columns(2)
                    objective = c1.text_area("Objectif de réduction")
                    added_controls = c2.text_area("Maîtrises supplémentaires")
                    contingency = st.text_area("Plan de contingence")
                    action_labels = st.multiselect("Actions du projet", list(tasks))
                    c3, c4 = st.columns(2)
                    target_likelihood = c3.selectbox("Vraisemblance cible", list(RISK_LIKELIHOOD_DEFINITIONS))
                    target_consequence = c4.selectbox("Conséquence cible", list(RISK_CONSEQUENCE_DEFINITIONS))
                    add_iteration = st.form_submit_button("Ajouter l'itération", type="primary")
                if add_iteration:
                    try:
                        with session_scope() as session:
                            created = create_risk_iteration(session, risk_id, treatment, objective, added_controls, contingency, target_likelihood, target_consequence, [tasks[label] for label in action_labels])
                            record_audit(session, actor_user_id=int(st.session_state["user"]["id"]), source="ui", action="create", entity_type="risk_iteration", entity_id=created.id, after=created)
                        st.success("Itération ajoutée.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            if not iterations.empty:
                st.dataframe(iterations, use_container_width=True, hide_index=True)
                pending_rows = iterations[iterations["Statut vérification"] != "Vérifiée"]
                if not pending_rows.empty:
                    verify_options = {f"Itération {row['Itération']} - {row['Cible']}": int(row["ID"]) for row in pending_rows.to_dict("records")}
                    with st.expander("Vérifier une cotation résiduelle"):
                        with st.form(f"risk_verify_{risk_id}"):
                            verify_label = st.selectbox("Itération", list(verify_options))
                            vc1, vc2 = st.columns(2)
                            verified_likelihood = vc1.selectbox("Vraisemblance constatée", list(RISK_LIKELIHOOD_DEFINITIONS))
                            verified_consequence = vc2.selectbox("Conséquence constatée", list(RISK_CONSEQUENCE_DEFINITIONS))
                            evidence = st.text_area("Preuve de vérification")
                            verify_clicked = st.form_submit_button("Valider la cotation résiduelle", type="primary")
                        if verify_clicked:
                            try:
                                with session_scope() as session:
                                    verified = verify_risk_iteration(session, verify_options[verify_label], verified_likelihood, verified_consequence, evidence, int(st.session_state["user"]["id"]))
                                    record_audit(session, actor_user_id=int(st.session_state["user"]["id"]), source="ui", action="verify", entity_type="risk_iteration", entity_id=verified.id, after=verified)
                                st.success("Cotation résiduelle vérifiée et rendue officielle.")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
                with st.expander("Décision d'acceptation"):
                    with st.form(f"risk_accept_{risk_id}"):
                        decision = st.selectbox("Décision", ["À statuer", "Accepté", "Non accepté", "Accepté par dérogation"])
                        justification = st.text_area("Justification")
                        decide_clicked = st.form_submit_button("Enregistrer la décision", type="primary")
                    if decide_clicked:
                        try:
                            with session_scope() as session:
                                decided = decide_risk_acceptance(session, risk_id, decision, justification, int(st.session_state["user"]["id"]))
                                record_audit(session, actor_user_id=int(st.session_state["user"]["id"]), source="ui", action="acceptance", entity_type="risk", entity_id=decided.id, after=decided)
                            st.success("Décision enregistrée.")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                delete_record_control("risk_iteration", iterations, ["Itération", "Traitement"], f"risk_iterations_{risk_id}")

    with analyses_tab:
        if assessments.empty:
            st.info("Aucune analyse pour ce projet.")
        else:
            st.dataframe(assessments, use_container_width=True, hide_index=True)
            analysis_labels = {f"{row['Référence']} - {row['Analyse']}": int(row["ID"]) for row in assessments.to_dict("records")}
            selected_analysis_label = st.selectbox("Analyse à modifier", list(analysis_labels), key="risk_assessment_edit_select")
            assessment_id = analysis_labels[selected_analysis_label]
            with session_scope() as session:
                item = session.get(RiskAssessment, assessment_id)
                assessment_values = {
                    "title": item.title, "leader_id": item.leader_id, "product": item.product_or_change or "",
                    "scope": item.scope or "", "assumptions": item.assumptions or "",
                    "requirements": item.applicable_requirements or "", "threshold": item.acceptance_threshold,
                    "itns": item.is_itns, "safety": item.safety_importance, "graded": item.graded_approach_rationale or "",
                    "status": item.status,
                }
            with st.expander("Modifier ou clôturer l'analyse"):
                with st.form(f"risk_assessment_edit_{assessment_id}"):
                    ac1, ac2, ac3 = st.columns([2, 1, 1])
                    atitle = ac1.text_input("Titre", assessment_values["title"])
                    aleader = ac2.selectbox("Responsable", [""] + list(users), index=([""] + list(users)).index(_option_label(users, assessment_values["leader_id"])) if _option_label(users, assessment_values["leader_id"]) else 0)
                    athreshold = ac3.selectbox("Seuil", ["Low", "Medium", "High", "Extreme"], index=["Low", "Medium", "High", "Extreme"].index(assessment_values["threshold"]))
                    aproduct = st.text_input("Produit ou modification", assessment_values["product"])
                    ascope = st.text_area("Périmètre", assessment_values["scope"])
                    aa1, aa2 = st.columns(2)
                    aassumptions = aa1.text_area("Hypothèses", assessment_values["assumptions"])
                    arequirements = aa2.text_area("Exigences applicables", assessment_values["requirements"])
                    aitns = st.checkbox("ITNS", value=assessment_values["itns"])
                    asafety = st.selectbox("Importance pour la sûreté", ["Non applicable", "Faible", "Modérée", "Élevée"], index=["Non applicable", "Faible", "Modérée", "Élevée"].index(assessment_values["safety"]) if assessment_values["safety"] in ["Non applicable", "Faible", "Modérée", "Élevée"] else 0)
                    agrade = st.text_area("Approche graduée", assessment_values["graded"])
                    astatus = st.selectbox("Statut", ["Ouverte", "Clôturée"], index=["Ouverte", "Clôturée"].index(assessment_values["status"]))
                    save_analysis = st.form_submit_button("Enregistrer", type="primary")
                if save_analysis:
                    try:
                        with session_scope() as session:
                            current = session.get(RiskAssessment, assessment_id)
                            if current.status == "Clôturée" and astatus == "Ouverte":
                                set_risk_assessment_status(session, assessment_id, "Ouverte")
                            update_risk_assessment(session, assessment_id, title=atitle, leader_id=users.get(aleader), product_or_change=aproduct, scope=ascope, assumptions=aassumptions, applicable_requirements=arequirements, acceptance_threshold=athreshold, is_itns=aitns, safety_importance=asafety, graded_approach_rationale=agrade)
                            updated = set_risk_assessment_status(session, assessment_id, astatus)
                            record_audit(session, actor_user_id=int(st.session_state["user"]["id"]), source="ui", action="update", entity_type="risk_assessment", entity_id=updated.id, after=updated)
                        st.success("Analyse mise à jour.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            delete_record_control("risk_assessment", assessments, ["Référence", "Analyse"], f"risk_assessments_{project_id}")


def show_reports() -> None:
    header = sticky_page_header("reports")
    with header:
        title_col, filter_col = st.columns([1.0, 3.0], vertical_alignment="center")
        with title_col:
            sticky_header_title("Rapports PDF")
        with filter_col:
            project_id = select_project()
    if not project_id:
        return
    with session_scope() as session:
        project = get_project(session, project_id)
        project_label = f"{project.code} - {project.name}"
        metrics = kpis(session, project_id)
        task_data = tasks_df(session, project_id)
        budget_data = budget_df(session, project_id)
        assessment_data = risk_assessments_df(session, project_id)
        risk_data = risks_df(session, assessment_data["ID"].astype(int).tolist()) if not assessment_data.empty else pd.DataFrame()
    st.write("Génère un PDF synthétique avec KPI, tâches principales, budget et risques.")
    if st.button("Générer le PDF", type="primary"):
        output = build_project_pdf(project_label, metrics, task_data, budget_data, risk_data)
        st.success(f"Rapport généré : {output.name}")
        st.download_button(
            "Télécharger",
            data=output.read_bytes(),
            file_name=output.name,
            mime="application/pdf",
            use_container_width=True,
        )


def show_users() -> None:
    sticky_page_header("users", "Utilisateurs")
    if st.session_state["user"]["role"] != "admin":
        st.warning("Page réservée aux administrateurs.")
        return
    with session_scope() as session:
        data = users_df(session)

    with st.expander("Créer un utilisateur", expanded=False):
        with st.form("user_form"):
            c1, c2 = st.columns(2)
            username = c1.text_input("Identifiant")
            full_name = c2.text_input("Nom complet")
            c3, c4, c5 = st.columns(3)
            email = c3.text_input("Email")
            role = c4.selectbox("Rôle", ["member", "manager", "admin"])
            rate = c5.number_input("Taux horaire", min_value=0.0, value=85.0, step=5.0)
            password = st.text_input("Mot de passe initial", type="password")
            submitted = st.form_submit_button("Créer l'utilisateur")
        if submitted:
            try:
                with session_scope() as session:
                    user = create_user(session, username, full_name, email, role, password, rate)
                    project = ensure_user_project(session, user.id)
                st.success(f"Utilisateur créé avec son projet personnel : {project.code}.")
                st.rerun()
            except IntegrityError:
                st.error("Cet identifiant existe déjà.")

    st.subheader("Projets utilisateur et support")
    user_project_options = {
        f"{row['Nom']} ({row['Utilisateur']})": int(row["ID"])
        for row in data.to_dict("records")
    }
    c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
    selected_project_user = c1.selectbox("Utilisateur", list(user_project_options.keys()) if user_project_options else [""])
    if c2.button("Créer le projet utilisateur", use_container_width=True, disabled=not user_project_options):
        try:
            with session_scope() as session:
                project = ensure_user_project(session, user_project_options[selected_project_user])
            st.success(f"Projet utilisateur disponible : {project.code}.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if c3.button("Créer le projet SUPPORT", use_container_width=True):
        try:
            with session_scope() as session:
                project = ensure_support_project(session)
            st.success(f"Projet support disponible : {project.code}.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    save_users = top_right_save_button("users_save")
    user_visible_columns = grid_column_visibility_selector(
        "users_grid",
        list(data.columns),
        required_columns=["Utilisateur", "Nom"],
        technical_columns={"ID"},
    )
    edited_users = st.data_editor(
        data,
        key="users_editor",
        use_container_width=True,
        hide_index=True,
        column_order=visible_columns_for_editor(data, user_visible_columns),
        disabled=["ID", "Projet utilisateur"],
        column_config={
            "Rôle": st.column_config.SelectboxColumn("Rôle", options=["member", "manager", "admin"]),
            "Taux horaire": st.column_config.NumberColumn("Taux horaire", min_value=0.0, step=5.0),
            "Actif": st.column_config.CheckboxColumn("Actif"),
        },
    )
    if save_users:
        try:
            with session_scope() as session:
                update_users_from_df(session, edited_users)
            st.success("Utilisateurs mis à jour.")
            st.rerun()
        except IntegrityError:
            st.error("Un identifiant utilisateur existe déjà.")
        except Exception as exc:
            st.error(str(exc))


    delete_record_control(
        "user",
        data,
        ["Utilisateur", "Nom"],
        "users",
        protected_ids={int(st.session_state["user"]["id"])},
        protected_message="Vous ne pouvez pas supprimer l'utilisateur actuellement connecté.",
    )


def main() -> None:
    inject_css()
    require_login()
    page = sidebar()
    if page == "Tableau de bord":
        show_dashboard()
    elif page == "Projets":
        show_projects()
    elif page == "Tâches et Gantt":
        show_tasks()
    elif page == "Timesheet":
        show_timesheet()
    elif page == "Planification":
        show_planning()
    elif page == "Budget":
        show_budget()
    elif page == "Gestion des risques":
        show_risks()
    elif page == "Rapports PDF":
        show_reports()
    elif page == "Utilisateurs":
        show_users()


if __name__ == "__main__":
    main()
