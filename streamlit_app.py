from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from babel.numbers import format_currency
from st_aggrid import AgGrid, DataReturnMode, JsCode
from sqlalchemy.exc import IntegrityError

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
from perspectiv.reports import build_project_pdf
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
    get_project,
    kpis,
    monthly_completion_df,
    project_options,
    projects_df,
    starcost_hours_by_month_df,
    task_options,
    tasks_df,
    time_entries_df,
    save_weekly_timesheet,
    update_budget_from_df,
    update_budget_lines_from_df,
    update_projects_from_df,
    update_tasks_from_df,
    update_time_entries_from_df,
    update_task_budget_and_expense,
    update_users_from_df,
    user_name_options,
    user_options,
    week_day_columns,
    week_start,
    weekly_timesheet_df,
    users_df,
)


st.set_page_config(page_title="PerspectiV", layout="wide")
init_db()


PAGES = ["Tableau de bord", "Projets", "Tâches et Gantt", "Timesheet", "Budget", "Rapports PDF", "Utilisateurs"]

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


def styled_task_table(data: pd.DataFrame):
    columns = [column for column in TASK_DISPLAY_COLUMNS if column in data.columns]
    display = data[columns].copy()

    def row_style(row: pd.Series) -> list[str]:
        color = level_color(row.get("Niveau"))
        text_style = level_text_style(row.get("Niveau"))
        try:
            level = int(row.get("Niveau") or 0)
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
        "Coût prévu",
        "Dépense directe",
        "Coût réel total",
        "Avancement",
    ]
    formatters = {column: "{:.1f}" for column in number_columns if column in display.columns}
    return display.style.apply(row_style, axis=1).format(formatters, na_rep="")


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


def project_grid(data: pd.DataFrame, user_names: dict[str, int]):
    grid_data = project_grid_data(data)
    column_defs = [
        {"field": "ID", "hide": True, "editable": False},
        {"field": "Code", "pinned": "left", "editable": True, "width": 110},
        {"field": "Projet", "pinned": "left", "editable": True, "width": 240},
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
    grid_options = {
        "columnDefs": column_defs,
        "defaultColDef": {
            "editable": True,
            "filter": True,
            "sortable": True,
            "resizable": True,
            "minWidth": 95,
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
        height=560,
        data_return_mode=DataReturnMode.AS_INPUT,
        update_on=["cellValueChanged", "rowDoubleClicked"],
        allow_unsafe_jscode=True,
        theme="streamlit",
        show_toolbar=True,
        show_search=True,
        show_download_button=False,
        key="projects_grid",
    )


def task_color_options(task_data: pd.DataFrame) -> list[str]:
    candidates = [
        "Temps prévu",
        "Temps passé",
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
        {"field": "Libellé", "headerName": "Tâche", "editable": False, "pinned": "left", "width": 290},
        {"field": "Référence", "editable": False, "width": 135},
        {"field": "Titre", "editable": True, "width": 220},
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
        {"field": "Coût prévu", "editable": True, "width": 120, "type": "numericColumn"},
        {"field": "Coût temps réel", "editable": False, "width": 140, "type": "numericColumn"},
        {"field": "Dépense directe", "editable": True, "width": 145, "type": "numericColumn"},
        {"field": "Coût réel total", "editable": False, "width": 145, "type": "numericColumn"},
        {"field": "Avancement", "editable": True, "width": 120, "type": "numericColumn"},
        {"field": "Ressources", "editable": False, "width": 180},
        {"field": "Description", "editable": True, "width": 260},
    ]
    grid_options = {
        "columnDefs": [col for col in column_defs if col["field"] in grid_data.columns],
        "defaultColDef": {
            "filter": True,
            "sortable": True,
            "resizable": True,
            "minWidth": 85,
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
        height=max(280, min(620, 105 + len(grid_data) * 32)),
        data_return_mode=DataReturnMode.AS_INPUT,
        update_on=["cellValueChanged"],
        allow_unsafe_jscode=True,
        theme="streamlit",
        show_toolbar=True,
        show_search=True,
        show_download_button=False,
        key=f"tasks_grid_{project_id}",
    )
    return aggrid_data(response, grid_data)


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
    st.dataframe(styled_task_table(task_data), use_container_width=True, hide_index=True)

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
            st.dataframe(styled_task_table(pd.DataFrame(subtree)), use_container_width=True, hide_index=True)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #dfe5ef;
            border-radius: 8px;
            padding: 12px 14px;
        }
        [data-testid="stSidebar"] {background: #111827;}
        [data-testid="stSidebar"] * {color: #f8fafc;}
        h1, h2, h3 {letter-spacing: 0;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def login() -> None:
    st.title("PerspectiV")
    st.caption("Gestion de projets locale avec backend SQL et frontend Python.")
    with st.form("login_form"):
        username = st.text_input("Utilisateur", value="admin")
        password = st.text_input("Mot de passe", type="password", value="admin")
        submitted = st.form_submit_button("Se connecter", use_container_width=True)
    if submitted:
        with session_scope() as session:
            user = authenticate(session, username, password)
            if user:
                st.session_state["user"] = {"id": user.id, "name": user.full_name, "role": user.role}
                st.rerun()
            st.error("Identifiant ou mot de passe incorrect.")
    st.info("Compte de démonstration : admin / admin. À changer avant usage réel.")


def require_login() -> None:
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

    st.sidebar.title("PerspectiV")
    st.sidebar.caption(f"{user['name']} · {user['role']}")
    page = st.sidebar.radio(
        "Navigation",
        PAGES,
        key="navigation_page",
    )
    if st.sidebar.button("Déconnexion", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    return page


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
    st.title("Tableau de bord")
    project_id = select_project("Périmètre", include_all=True)
    with session_scope() as session:
        metrics = kpis(session, project_id)
        task_data = tasks_df(session, project_id)
        time_data = time_entries_df(session, project_id)
        budget_data = budget_df(session, project_id)
        starcost_monthly = starcost_hours_by_month_df(session, project_id)
        completion_monthly = monthly_completion_df(session, project_id)
        deps = dependencies_df(session, project_id)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Projets", int(metrics["projects"]))
    c2.metric("Tâches", int(metrics["tasks"]), f"{metrics['late_tasks']} en retard")
    c3.metric("Avancement moyen", f"{metrics['progress']}%")
    c4.metric("Heures", f"{metrics['actual_hours']:.1f} / {metrics['planned_hours']:.1f}")
    c5.metric("Réel budget", eur(metrics["actual_budget"]))

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
    st.title("Projets")
    with session_scope() as session:
        users = user_options(session)
        user_names = user_name_options(session)
        data = projects_df(session)

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

    st.subheader("Gantt projets")
    st.caption("Modifiez les dates ou les montants : le Gantt se met à jour automatiquement. Double-cliquez une ligne pour ouvrir ses tâches.")
    color_options = [column for column in ["Budget", "Budget heures"] if column in data.columns]
    color_field = st.selectbox("Colorer les projets par", color_options or ["Budget"], index=0)

    gantt_container = st.container()
    st.subheader("Table projets")
    table_container = st.container()
    with table_container:
        grid_response = project_grid(data, user_names)
        edited = aggrid_data(grid_response, data)
        project_id = double_clicked_project_id(grid_response)
        if project_id:
            navigate_to_project_tasks(project_id)
            st.rerun()

    with gantt_container:
        st.plotly_chart(projects_gantt(edited, color_field), width="stretch")

    if st.button("Enregistrer les modifications projets", type="primary"):
        try:
            with session_scope() as session:
                update_projects_from_df(session, edited)
            st.success("Projets mis à jour.")
            st.rerun()
        except IntegrityError:
            st.error("Un code projet existe déjà.")
        except Exception as exc:
            st.error(str(exc))


    delete_record_control("project", data, ["Code", "Projet"], "projects")


def show_tasks() -> None:
    st.title("Tâches et Gantt")
    project_id = select_project()
    if not project_id:
        return
    with session_scope() as session:
        task_data = tasks_df(session, project_id)
        deps = dependencies_df(session, project_id)
        assignments = assignments_df(session, project_id)
        users = user_options(session)
        task_labels = task_options(session, project_id)
        budget_labels = budget_options(session, project_id)

    gantt_tab, grouped_tab, create_tab, task_budget_tab, deps_tab, assign_tab = st.tabs(
        ["Gantt", "Vue groupée", "Nouvelle tâche", "Budget tâche", "Dépendances", "Affectations"]
    )

    with gantt_tab:
        st.subheader("Gantt tâches")
        color_options = task_color_options(task_data)
        color_field = st.selectbox("Colorer les tâches par", color_options or ["Temps prévu"], index=0)
        gantt_container = st.container()
        st.subheader("Table tâches")
        edited_tasks = task_editor(task_data, task_labels, budget_labels, project_id)
        with gantt_container:
            st.plotly_chart(gantt_figure(edited_tasks, color_field), width="stretch")
        if not deps.empty:
            st.caption("Dépendances")
            st.dataframe(deps[["Prédécesseur", "Successeur", "Type", "Décalage"]], width="stretch", hide_index=True)
        if st.button("Enregistrer les modifications tâches", type="primary"):
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
            st.dataframe(deps[["Prédécesseur", "Successeur", "Type", "Décalage"]], width="stretch", hide_index=True)
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
            st.dataframe(assignments, width="stretch", hide_index=True)
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
    edited_entries = st.data_editor(
        entries,
        key=f"time_editor_{project_id}",
        use_container_width=True,
        hide_index=True,
        disabled=["ID", "Projet", "Taux", "Coût"],
        column_config={
            "Date": st.column_config.DateColumn("Date"),
            "Tâche": st.column_config.SelectboxColumn("Tâche", options=list(task_labels.keys())),
            "Utilisateur": st.column_config.SelectboxColumn("Utilisateur", options=list(user_names.keys())),
            "Heures": st.column_config.NumberColumn("Heures", min_value=0.0, max_value=24.0, step=0.25),
        },
    )
    if st.button("Enregistrer les modifications timesheet", type="primary"):
        try:
            with session_scope() as session:
                update_time_entries_from_df(session, edited_entries, project_id)
            st.success("Pointages mis à jour, tâches et budgets recalculés.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


    delete_record_control("time_entry", entries, ["Date", "Tâche", "Utilisateur"], f"time_entries_{project_id}")


def show_timesheet() -> None:
    st.title("Timesheet")
    project_id = select_project()
    if not project_id:
        return

    with session_scope() as session:
        user_names = user_name_options(session)

    if not user_names:
        st.warning("Aucun utilisateur actif disponible.")
        return

    c1, c2, c3, c4 = st.columns([3, 1, 3, 1])
    user_labels = list(user_names.keys())
    current_user_name = st.session_state.get("user", {}).get("name")
    user_index = user_labels.index(current_user_name) if current_user_name in user_labels else 0
    selected_user = c1.selectbox("Utilisateur", user_labels, index=user_index)
    user_id = user_names[selected_user]

    week_key = f"timesheet_week_{project_id}"
    if week_key not in st.session_state:
        st.session_state[week_key] = week_start(date.today())
    if c2.button("←", key=f"{week_key}_previous", use_container_width=True):
        st.session_state[week_key] = week_start(st.session_state[week_key]) - timedelta(days=7)
        st.rerun()
    selected_day = c3.date_input("Semaine", key=week_key)
    if c4.button("→", key=f"{week_key}_next", use_container_width=True):
        st.session_state[week_key] = week_start(st.session_state[week_key]) + timedelta(days=7)
        st.rerun()

    selected_week = week_start(selected_day)
    iso_year, iso_week, _ = selected_week.isocalendar()
    week_end = selected_week + timedelta(days=6)
    st.subheader(f"Semaine {iso_week}/{iso_year}")
    st.caption(f"Du {selected_week:%d/%m/%Y} au {week_end:%d/%m/%Y}. Les tâches agrégées sont exclues du pointage.")

    with session_scope() as session:
        weekly_data = weekly_timesheet_df(session, project_id, user_id, selected_week)
        entries = time_entries_df(session, project_id)

    day_columns = [label for _, label in week_day_columns(selected_week)]
    if weekly_data.empty:
        st.info("Aucune tâche directe disponible pour ce projet.")
    else:
        editor_data = weekly_data.set_index("Tâche ID")
        column_config = {
            "Tâche": st.column_config.TextColumn("Tâche", disabled=True, width="large"),
        }
        for label in day_columns:
            column_config[label] = st.column_config.NumberColumn(label, min_value=0.0, max_value=24.0, step=0.25)

        edited_week = st.data_editor(
            editor_data,
            key=f"weekly_timesheet_{project_id}_{user_id}_{selected_week:%Y%m%d}",
            use_container_width=True,
            hide_index=True,
            column_order=["Tâche"] + day_columns,
            disabled=["Tâche"],
            column_config=column_config,
        )

        daily_totals = edited_week[day_columns].apply(pd.to_numeric, errors="coerce").fillna(0).sum()
        total_hours = float(daily_totals.sum())
        st.caption("Total semaine : " + f"{total_hours:.2f} h")
        st.dataframe(
            pd.DataFrame([{"Jour": day, "Heures": float(hours)} for day, hours in daily_totals.items()]),
            use_container_width=True,
            hide_index=True,
        )

        if st.button("Enregistrer la semaine", type="primary"):
            try:
                with session_scope() as session:
                    save_weekly_timesheet(session, project_id, user_id, selected_week, edited_week.reset_index())
                st.success("Pointages hebdomadaires enregistrés, tâches et budgets recalculés.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    st.subheader("Historique des pointages")
    user_entries = entries[entries["Utilisateur"] == selected_user].copy() if not entries.empty else entries
    if user_entries.empty:
        st.info("Aucun pointage pour cet utilisateur sur ce projet.")
        return

    with session_scope() as session:
        task_labels = direct_task_options(session, project_id)
    edited_entries = st.data_editor(
        user_entries,
        key=f"time_history_editor_{project_id}_{user_id}",
        use_container_width=True,
        hide_index=True,
        disabled=["ID", "Projet", "Utilisateur", "Taux", "Coût"],
        column_config={
            "Date": st.column_config.DateColumn("Date"),
            "Tâche": st.column_config.SelectboxColumn("Tâche", options=list(task_labels.keys())),
            "Heures": st.column_config.NumberColumn("Heures", min_value=0.0, max_value=24.0, step=0.25),
        },
    )
    if st.button("Enregistrer les corrections de l'historique", type="secondary"):
        try:
            with session_scope() as session:
                update_time_entries_from_df(session, edited_entries, project_id)
            st.success("Pointages mis à jour, tâches et budgets recalculés.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    delete_record_control("time_entry", user_entries, ["Date", "Tâche", "Utilisateur"], f"time_entries_{project_id}_{user_id}")


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
    edited_budget = st.data_editor(
        data,
        key=f"budget_editor_{project_id}",
        use_container_width=True,
        hide_index=True,
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
    if st.button("Enregistrer les modifications budget", type="primary"):
        try:
            with session_scope() as session:
                update_budget_from_df(session, edited_budget)
            st.success("Budgets mis à jour, réel recalculé.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def show_budget() -> None:
    st.title("Budget")
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
        edited_budget = st.data_editor(
            data[[column for column in display_columns if column in data.columns]],
            key=f"budget_header_editor_{project_id}",
            use_container_width=True,
            hide_index=True,
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
        if st.button("Enregistrer les budgets", type="primary"):
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

    edited_lines = st.data_editor(
        lines,
        key=f"budget_line_editor_{project_id}",
        use_container_width=True,
        hide_index=True,
        disabled=["ID", "Projet ID", "Budget ID", "Projet"],
        column_config={
            "Budget": st.column_config.SelectboxColumn("Budget", options=list(budget_labels.keys())),
            "Catégorie": st.column_config.SelectboxColumn(
                "Catégorie", options=["Phase", "Main d'oeuvre", "Outillage", "Sous-traitance", "Recette", "Divers"]
            ),
            "Prévu": st.column_config.NumberColumn("Prévu", min_value=0.0, step=100.0, format="%.2f €"),
        },
    )
    if st.button("Enregistrer les lignes de frais", type="primary"):
        try:
            with session_scope() as session:
                update_budget_lines_from_df(session, edited_lines, project_id)
            st.success("Lignes de frais mises à jour, budgets recalculés.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    delete_record_control("budget_line", lines, ["Budget", "Catégorie", "Libellé"], f"budget_lines_{project_id}")


def show_reports() -> None:
    st.title("Rapports PDF")
    project_id = select_project()
    if not project_id:
        return
    with session_scope() as session:
        project = get_project(session, project_id)
        project_label = f"{project.code} - {project.name}"
        metrics = kpis(session, project_id)
        task_data = tasks_df(session, project_id)
        budget_data = budget_df(session, project_id)
    st.write("Génère un PDF synthétique avec KPI, tâches principales et budget.")
    if st.button("Générer le PDF", type="primary"):
        output = build_project_pdf(project_label, metrics, task_data, budget_data)
        st.success(f"Rapport généré : {output.name}")
        st.download_button(
            "Télécharger",
            data=output.read_bytes(),
            file_name=output.name,
            mime="application/pdf",
            use_container_width=True,
        )


def show_users() -> None:
    st.title("Utilisateurs")
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
                    create_user(session, username, full_name, email, role, password, rate)
                st.success("Utilisateur créé.")
                st.rerun()
            except IntegrityError:
                st.error("Cet identifiant existe déjà.")

    edited_users = st.data_editor(
        data,
        key="users_editor",
        use_container_width=True,
        hide_index=True,
        disabled=["ID"],
        column_config={
            "Rôle": st.column_config.SelectboxColumn("Rôle", options=["member", "manager", "admin"]),
            "Taux horaire": st.column_config.NumberColumn("Taux horaire", min_value=0.0, step=5.0),
            "Actif": st.column_config.CheckboxColumn("Actif"),
        },
    )
    if st.button("Enregistrer les modifications utilisateurs", type="primary"):
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
    elif page == "Budget":
        show_budget()
    elif page == "Rapports PDF":
        show_reports()
    elif page == "Utilisateurs":
        show_users()


if __name__ == "__main__":
    main()
