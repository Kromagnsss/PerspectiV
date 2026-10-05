from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from perspectiv.charts import gantt_figure
from perspectiv.database import SessionLocal, init_db
from perspectiv.models import Project, Task
from perspectiv.schemas import TaskCreate
from perspectiv.services import (
    add_dependency,
    task_level_prefix,
    tasks_df,
    update_tasks_from_projects_df,
    visible_task_rows,
)
from perspectiv.task_hierarchy import MAX_TASK_LEVEL, TASK_LEVEL_STYLES


def hierarchy_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ID": 1, "Projet ID": 10, "Parent ID": None, "Niveau": 1},
            {"ID": 2, "Projet ID": 10, "Parent ID": 1, "Niveau": 2},
            {"ID": 3, "Projet ID": 10, "Parent ID": 2, "Niveau": 3},
            {"ID": 6, "Projet ID": 10, "Parent ID": 3, "Niveau": 4},
            {"ID": 7, "Projet ID": 10, "Parent ID": 6, "Niveau": 5},
            {"ID": 8, "Projet ID": 10, "Parent ID": 7, "Niveau": 6},
            {"ID": 4, "Projet ID": 20, "Parent ID": None, "Niveau": 1},
            {"ID": 5, "Projet ID": 20, "Parent ID": 4, "Niveau": 2},
        ]
    )


def test_visible_task_rows_combines_depth_and_recursive_collapse() -> None:
    data = hierarchy_frame()
    assert visible_task_rows(data, max_level=2)["ID"].tolist() == [1, 2, 4, 5]
    assert visible_task_rows(data, max_level=6)["ID"].tolist() == [1, 2, 3, 6, 7, 8, 4, 5]
    assert visible_task_rows(data, max_level=5)["ID"].tolist() == [1, 2, 3, 6, 7, 4, 5]
    assert visible_task_rows(data, max_level=6, collapsed_task_ids={1})["ID"].tolist() == [1, 4, 5]
    assert visible_task_rows(data, max_level=6, collapsed_task_ids={2})["ID"].tolist() == [1, 2, 4, 5]


def test_collapse_is_isolated_between_projects() -> None:
    visible = visible_task_rows(hierarchy_frame(), max_level=6, collapsed_task_ids={4})
    assert visible["ID"].tolist() == [1, 2, 3, 6, 7, 8, 4]


def test_six_levels_are_valid_and_have_progressive_indentation() -> None:
    assert MAX_TASK_LEVEL == 6
    assert TaskCreate(title="Détail opérationnel", level=6).level == 6
    with pytest.raises(ValueError):
        TaskCreate(title="Trop profond", level=7)
    assert task_level_prefix(1) == ""
    assert task_level_prefix(6) == "| | | | | "


def test_gantt_has_bottom_separators_for_levels_one_and_two() -> None:
    tasks = pd.DataFrame([
        {
            "ID": level,
            "Projet ID": 10,
            "Projet Code": "PRJ-A",
            "Libellé": f"{'| ' * (level - 1)}PRJ-A-T00{level} · Niveau {level}",
            "Référence": f"PRJ-A-T00{level}",
            "Niveau": level,
            "Début": date(2026, 1, level),
            "Fin estimée": date(2026, 1, level + 2),
            "Avancement": 0,
            "Temps prévu": 8 - level,
            "Statut": "Non commencé",
        }
        for level in range(1, MAX_TASK_LEVEL + 1)
    ])
    figure = gantt_figure(tasks)
    horizontal_lines = [shape for shape in figure.layout.shapes if shape.type == "line" and shape.yref == "y"]
    assert [(line.y0, line.y1, line.line.width) for line in horizontal_lines] == [(0.5, 0.5, 1), (1.5, 1.5, 1)]
    row_backgrounds = [shape for shape in figure.layout.shapes if shape.type == "rect" and shape.yref == "y"]
    assert [shape.fillcolor for shape in row_backgrounds] == [
        TASK_LEVEL_STYLES[level]["background_color"] for level in range(1, MAX_TASK_LEVEL + 1)
    ]


def test_dependency_rejects_tasks_from_different_projects() -> None:
    init_db()
    session = SessionLocal()
    try:
        first_project = Project(code="TEST-HIER-A", name="Projet A")
        second_project = Project(code="TEST-HIER-B", name="Projet B")
        session.add_all([first_project, second_project])
        session.flush()
        first_task = Task(project_id=first_project.id, reference="TEST-HIER-A-T001", title="A")
        second_task = Task(project_id=second_project.id, reference="TEST-HIER-B-T001", title="B")
        session.add_all([first_task, second_task])
        session.flush()
        with pytest.raises(ValueError, match="même projet"):
            add_dependency(session, first_task.id, second_task.id, "Fin-Début", 0)
    finally:
        session.rollback()
        session.close()


def test_multi_project_grid_updates_each_project_and_rejects_cross_parent() -> None:
    init_db()
    session = SessionLocal()
    try:
        first_project = Project(code="TEST-GRID-A", name="Projet grille A")
        second_project = Project(code="TEST-GRID-B", name="Projet grille B")
        session.add_all([first_project, second_project])
        session.flush()
        first_task = Task(project_id=first_project.id, reference="TEST-GRID-A-T001", title="Initial A", level=1)
        second_task = Task(project_id=second_project.id, reference="TEST-GRID-B-T001", title="Initial B", level=1)
        session.add_all([first_task, second_task])
        session.flush()

        data = tasks_df(session, project_ids=[first_project.id, second_project.id])
        data.loc[data["ID"] == first_task.id, "Titre"] = "Modifié A"
        data.loc[data["ID"] == second_task.id, "Titre"] = "Modifié B"
        update_tasks_from_projects_df(session, data, [first_project.id, second_project.id])
        assert first_task.title == "Modifié A"
        assert second_task.title == "Modifié B"

        data.loc[data["ID"] == first_task.id, "Parent"] = "TEST-GRID-B-T001 - Modifié B"
        with pytest.raises(ValueError, match="même projet"):
            update_tasks_from_projects_df(session, data, [first_project.id, second_project.id])
    finally:
        session.rollback()
        session.close()
