from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Collection
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import recompute_actuals
from .models import (
    Budget,
    BudgetLine,
    PlannedTimeEntry,
    Project,
    Risk,
    RiskAssessment,
    RiskIteration,
    RiskIterationTask,
    Task,
    TaskAssignment,
    TaskDependency,
    TimeEntry,
    User,
    UserGridPreference,
)
from .security import hash_password, verify_password
from .task_hierarchy import MAX_TASK_LEVEL, normalize_task_level


RISK_LEVELS = ["Low", "Medium", "High", "Extreme"]
RISK_LEVEL_RANK = {name: index for index, name in enumerate(RISK_LEVELS)}
RISK_MATRIX = {
    "A": ["Medium", "Medium", "High", "Extreme", "Extreme"],
    "B": ["Low", "Medium", "High", "High", "Extreme"],
    "C": ["Low", "Medium", "Medium", "High", "High"],
    "D": ["Low", "Low", "Medium", "Medium", "Medium"],
    "E": ["Low", "Low", "Low", "Low", "Medium"],
}
LIKELIHOOD_DEFINITIONS = {
    "A": ("Almost Certain", "Attendu dans la plupart des circonstances; événement annuel ou circonstances déjà engagées."),
    "B": ("Likely", "Déjà survenu ces dernières années, récemment dans une organisation comparable, ou attendu à court terme."),
    "C": ("Possible", "Déjà survenu au moins une fois ou probabilité annuelle estimée à environ 5 %."),
    "D": ("Unlikely", "Jamais survenu localement mais observé rarement ailleurs, ou probabilité annuelle proche de 1 %."),
    "E": ("Rare", "Circonstances exceptionnelles uniquement; très nettement moins de 1 % de probabilité annuelle."),
}
CONSEQUENCE_DEFINITIONS = {
    1: ("Insignificant", "Affection ne nécessitant pas de traitement médical."),
    2: ("Minor", "Blessure mineure nécessitant des premiers soins."),
    3: ("Significant", "Une blessure grave avec hospitalisation ou plusieurs blessures mineures."),
    4: ("Major", "Une blessure mettant la vie en danger ou plusieurs blessures graves avec hospitalisation."),
    5: ("Catastrophic", "Un décès ou plusieurs blessures mettant la vie en danger."),
}
RISK_LIKELIHOOD_DEFINITIONS = {
    key: f"{name} - {description}" for key, (name, description) in LIKELIHOOD_DEFINITIONS.items()
}
RISK_CONSEQUENCE_DEFINITIONS = {
    key: f"{name} - {description}" for key, (name, description) in CONSEQUENCE_DEFINITIONS.items()
}
RISK_LIFECYCLE_PHASES = [
    "Conception",
    "Fabrication",
    "Montage et essais",
    "Emballage, stockage et transport",
    "Installation",
    "Mise en service",
    "Utilisation",
    "Maintenance",
    "Démantèlement",
]


def risk_level(likelihood: str, consequence: int) -> str:
    likelihood = str(likelihood).strip().upper()
    consequence = int(consequence)
    if likelihood not in RISK_MATRIX or consequence not in range(1, 6):
        raise ValueError("La vraisemblance doit être comprise entre A et E et la conséquence entre 1 et 5.")
    return RISK_MATRIX[likelihood][consequence - 1]


def risk_is_within_threshold(level: str, threshold: str) -> bool:
    return RISK_LEVEL_RANK[level] <= RISK_LEVEL_RANK[threshold]


def decimal_to_float(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username.strip().lower(), User.active.is_(True)))
    if user and verify_password(password, user.password_hash):
        return user
    return None


def user_options(session: Session) -> dict[str, int]:
    users = session.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)).all()
    return {f"{u.full_name} ({u.role})": u.id for u in users}


def project_options(session: Session) -> dict[str, int]:
    projects = session.scalars(select(Project).order_by(Project.code)).all()
    return {f"{p.code} - {p.name}": p.id for p in projects}


def _project_ids(project_id: int | None, project_ids: Collection[int] | None) -> list[int]:
    if project_ids is not None:
        return list(dict.fromkeys(int(value) for value in project_ids))
    return [int(project_id)] if project_id else []


def user_name_options(session: Session) -> dict[str, int]:
    users = session.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)).all()
    return {u.full_name: u.id for u in users}


def _filtered_columns(columns: list[str], valid_columns: list[str]) -> list[str]:
    valid_set = set(valid_columns)
    return [column for column in columns if column in valid_set]


def get_grid_visible_columns(
    session: Session,
    user_id: int,
    grid_key: str,
    defaults: list[str],
    valid_columns: list[str],
) -> list[str]:
    default_columns = _filtered_columns(defaults, valid_columns)
    preference = session.scalar(
        select(UserGridPreference).where(
            UserGridPreference.user_id == user_id,
            UserGridPreference.grid_key == grid_key,
        )
    )
    if not preference:
        return default_columns
    try:
        stored_columns = json.loads(preference.visible_columns or "[]")
    except json.JSONDecodeError:
        return default_columns
    if not isinstance(stored_columns, list):
        return default_columns
    visible_columns = _filtered_columns([str(column) for column in stored_columns], valid_columns)
    return visible_columns or default_columns


def save_grid_visible_columns(session: Session, user_id: int, grid_key: str, visible_columns: list[str]) -> None:
    preference = session.scalar(
        select(UserGridPreference).where(
            UserGridPreference.user_id == user_id,
            UserGridPreference.grid_key == grid_key,
        )
    )
    if not preference:
        preference = UserGridPreference(user_id=user_id, grid_key=grid_key)
        session.add(preference)
    preference.visible_columns = json.dumps(list(dict.fromkeys(visible_columns)), ensure_ascii=False)


def task_options(session: Session, project_id: int | None = None) -> dict[str, int]:
    stmt = select(Task).order_by(Task.project_id, Task.sort_order, Task.reference)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    tasks = session.scalars(stmt).all()
    return {f"{t.reference} - {t.title}": t.id for t in tasks}


def direct_task_options(session: Session, project_id: int | None = None) -> dict[str, int]:
    stmt = select(Task).order_by(Task.project_id, Task.sort_order, Task.reference)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    tasks = session.scalars(stmt).all()
    aggregate_ids = _aggregate_task_ids(tasks)
    return {f"{t.reference} - {t.title}": t.id for t in tasks if t.id not in aggregate_ids}


def direct_tasks(session: Session, project_id: int) -> list[Task]:
    tasks = session.scalars(
        select(Task).where(Task.project_id == project_id).order_by(Task.sort_order, Task.reference)
    ).all()
    aggregate_ids = _aggregate_task_ids(tasks)
    return [task for task in tasks if task.id not in aggregate_ids]


def budget_options(session: Session, project_id: int | None = None) -> dict[str, int]:
    stmt = select(Budget).join(Project).order_by(Project.code, Budget.reference)
    if project_id:
        stmt = stmt.where(Budget.project_id == project_id)
    budgets = session.scalars(stmt).all()
    return {f"{b.reference} - {b.label}": b.id for b in budgets}


def _children_by_parent(tasks: list[Task]) -> dict[int, list[Task]]:
    task_ids = {task.id for task in tasks}
    children_by_parent: dict[int, list[Task]] = {}
    for task in tasks:
        if task.parent_id and task.parent_id in task_ids and task.parent_id != task.id:
            children_by_parent.setdefault(task.parent_id, []).append(task)
    return children_by_parent


def _ordered_tasks(tasks: list[Task], children_by_parent: dict[int, list[Task]] | None = None) -> list[Task]:
    children = children_by_parent or _children_by_parent(tasks)
    for siblings in children.values():
        siblings.sort(key=lambda item: (item.sort_order, item.reference, item.id))

    task_by_id = {task.id: task for task in tasks}
    roots = [
        task
        for task in tasks
        if not task.parent_id or task.parent_id not in task_by_id or task.parent_id == task.id
    ]
    roots.sort(key=lambda item: (item.project_id, item.sort_order, item.reference, item.id))

    ordered: list[Task] = []
    seen: set[int] = set()

    def walk(task: Task) -> None:
        if task.id in seen:
            return
        seen.add(task.id)
        ordered.append(task)
        for child in children.get(task.id, []):
            walk(child)

    for root in roots:
        walk(root)
    for task in tasks:
        walk(task)
    return ordered


def project_tasks(session: Session, project_id: int) -> list[Task]:
    tasks = session.scalars(
        select(Task).where(Task.project_id == project_id).order_by(Task.sort_order, Task.reference)
    ).all()
    return _ordered_tasks(tasks)


def _aggregate_task_ids(tasks: list[Task]) -> set[int]:
    return set(_children_by_parent(tasks))


def _parent_task_ids(tasks: list[Task]) -> set[int]:
    return _aggregate_task_ids(tasks)


def _detail_tasks(tasks: list[Task]) -> list[Task]:
    parent_ids = _parent_task_ids(tasks)
    return [task for task in tasks if task.id not in parent_ids]


def task_level_prefix(level: int | None) -> str:
    try:
        level_num = int(level or 1)
    except (TypeError, ValueError):
        level_num = 1
    return "| " * (normalize_task_level(level_num) - 1)


def get_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError("Projet introuvable")
    return project


def ensure_direct_time_task(session: Session, task_id: int, project_id: int | None = None) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise ValueError("Tâche introuvable.")
    if project_id and task.project_id != project_id:
        raise ValueError("La tâche sélectionnée n'appartient pas au projet courant.")
    child_count = session.scalar(
        select(func.count(Task.id)).where(
            Task.project_id == task.project_id,
            Task.parent_id == task.id,
            Task.id != task.id,
        )
    ) or 0
    if child_count:
        raise ValueError(
            f"Pointage interdit sur {task.reference} : cette tâche est en mode de calcul agrégé. "
            "Sélectionnez une tâche directe sans sous-tâche."
        )
    return task


def _code_fragment(value: str, max_length: int = 19) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    fragment = re.sub(r"[^A-Za-z0-9]+", "", ascii_value).upper()
    return (fragment or "UTILISATEUR")[:max_length]


def user_project_code(user: User) -> str:
    tokens = [token for token in re.split(r"\s+", user.full_name.strip()) if token]
    if len(tokens) >= 2:
        raw_code = f"{tokens[0][0]}{tokens[-1]}"
    else:
        raw_code = user.username or user.full_name
    return f"USER-{_code_fragment(raw_code)}"


def _unique_project_code(session: Session, base_code: str, owner_id: int | None = None) -> str:
    existing = session.scalar(select(Project).where(Project.code == base_code))
    if not existing or (owner_id and existing.owner_id == owner_id):
        return base_code

    for index in range(2, 100):
        suffix = f"-{index}"
        candidate = f"{base_code[:24 - len(suffix)]}{suffix}"
        existing = session.scalar(select(Project).where(Project.code == candidate))
        if not existing or (owner_id and existing.owner_id == owner_id):
            return candidate
    raise ValueError(f"Impossible de générer un code projet unique à partir de {base_code}.")


def _project_period() -> tuple[date, date]:
    today = date.today()
    return date(today.year, 1, 1), date(today.year, 12, 31)


def _ensure_project_budget(session: Session, project: Project, label: str, category: str) -> Budget:
    budget = session.scalar(select(Budget).where(Budget.project_id == project.id).order_by(Budget.reference))
    if not budget:
        budget = Budget(
            project_id=project.id,
            reference=next_budget_reference(session, project.id),
            label=label,
            status="Actif",
        )
        session.add(budget)
        session.flush()

    line = session.scalar(select(BudgetLine).where(BudgetLine.budget_id == budget.id).order_by(BudgetLine.id))
    if not line:
        session.add(
            BudgetLine(
                project_id=project.id,
                budget_id=budget.id,
                category=category,
                label=label,
                planned_amount=Decimal("0.00"),
                committed_amount=Decimal("0.00"),
            )
        )
        session.flush()
    return budget


def _ensure_direct_project_tasks(
    session: Session,
    project: Project,
    titles: list[str],
    budget: Budget | None,
    assigned_user_id: int | None = None,
) -> None:
    existing_titles = {
        task.title.strip().lower()
        for task in session.scalars(select(Task).where(Task.project_id == project.id)).all()
    }
    max_order = session.scalar(select(func.max(Task.sort_order)).where(Task.project_id == project.id)) or 0
    for title in titles:
        if title.strip().lower() in existing_titles:
            continue
        max_order += 10
        task = Task(
            project_id=project.id,
            budget_id=budget.id if budget else None,
            reference=next_task_reference(session, project.id),
            title=title,
            level=1,
            parent_id=None,
            status="Non commencé",
            priority="Normale",
            start_date=project.start_date,
            due_date=project.end_date,
            planned_hours=Decimal("0.00"),
            planned_cost=Decimal("0.00"),
            progress=0,
            sort_order=int(max_order),
        )
        session.add(task)
        session.flush()
        if assigned_user_id:
            assigned_user = session.get(User, assigned_user_id)
            session.add(
                TaskAssignment(
                    task_id=task.id,
                    user_id=assigned_user_id,
                    role="Suivi personnel",
                    planned_hours=Decimal("0.00"),
                    cost_rate=assigned_user.hourly_rate if assigned_user else Decimal("0.00"),
                )
            )
            session.flush()
        existing_titles.add(title.strip().lower())


def ensure_user_project(session: Session, user_id: int) -> Project:
    user = session.get(User, user_id)
    if not user:
        raise ValueError("Utilisateur introuvable.")

    project = session.scalar(
        select(Project)
        .where(Project.owner_id == user.id, Project.code.like("USER-%"))
        .order_by(Project.id)
    )
    if not project:
        start, end = _project_period()
        code = _unique_project_code(session, user_project_code(user), user.id)
        project = Project(
            code=code,
            name=f"Suivi utilisateur - {user.full_name}",
            owner_id=user.id,
            category="Utilisateur",
            priority="Normale",
            status="En cours",
            start_date=start,
            end_date=end,
            budget_amount=Decimal("0.00"),
            budget_hours=Decimal("0.00"),
            description="Projet personnel pour absences, formations, aléas et objectifs personnels.",
        )
        session.add(project)
        session.flush()

    budget = _ensure_project_budget(session, project, "Temps utilisateur", "Temps utilisateur")
    _ensure_direct_project_tasks(
        session,
        project,
        ["Absences", "Formations", "Aléas", "Objectifs personnels"],
        budget,
        assigned_user_id=user.id,
    )
    recompute_actuals(session)
    return project


def ensure_support_project(session: Session) -> Project:
    project = session.scalar(select(Project).where(Project.code == "SUPPORT"))
    if not project:
        start, end = _project_period()
        project = Project(
            code="SUPPORT",
            name="Support services",
            owner_id=None,
            category="Support",
            priority="Normale",
            status="En cours",
            start_date=start,
            end_date=end,
            budget_amount=Decimal("0.00"),
            budget_hours=Decimal("0.00"),
            description="Projet support pour suivre les temps d'assistance aux différents services.",
        )
        session.add(project)
        session.flush()

    budget = _ensure_project_budget(session, project, "Temps support", "Support")
    _ensure_direct_project_tasks(
        session,
        project,
        ["Support direction", "Support finance", "Support production", "Support IT", "Support commercial", "Support RH", "Autres supports"],
        budget,
    )
    recompute_actuals(session)
    return project


def create_user(
    session: Session,
    username: str,
    full_name: str,
    email: str,
    role: str,
    password: str,
    hourly_rate: float,
) -> None:
    user = User(
        username=username.strip().lower(),
        full_name=full_name.strip(),
        email=email.strip() or None,
        role=role,
        password_hash=hash_password(password),
        hourly_rate=Decimal(str(hourly_rate)),
    )
    session.add(user)
    session.flush()
    ensure_user_project(session, user.id)
    return user


def create_project(
    session: Session,
    code: str,
    name: str,
    owner_id: int | None,
    category: str,
    priority: str,
    status: str,
    start_date: date | None,
    end_date: date | None,
    budget_amount: float,
    budget_hours: float,
    description: str,
) -> None:
    project = Project(
        code=code.strip().upper(),
        name=name.strip(),
        owner_id=owner_id,
        category=category,
        priority=priority,
        status=status,
        start_date=start_date,
        end_date=end_date,
        budget_amount=Decimal(str(budget_amount)),
        budget_hours=Decimal(str(budget_hours)),
        description=description.strip() or None,
    )
    session.add(project)


def next_task_reference(session: Session, project_id: int) -> str:
    project = get_project(session, project_id)
    count = session.scalar(select(func.count(Task.id)).where(Task.project_id == project_id)) or 0
    return f"{project.code}-T{count + 1:03d}"


def next_budget_reference(session: Session, project_id: int) -> str:
    project = get_project(session, project_id)
    count = session.scalar(select(func.count(Budget.id)).where(Budget.project_id == project_id)) or 0
    return f"{project.code}-BDG-{count + 1:02d}"


def add_budget(session: Session, project_id: int, label: str, status: str = "Actif") -> Budget:
    budget = Budget(
        project_id=project_id,
        reference=next_budget_reference(session, project_id),
        label=label.strip(),
        status=status,
    )
    session.add(budget)
    session.flush()
    recompute_actuals(session)
    return budget


def create_task(
    session: Session,
    project_id: int,
    budget_id: int | None,
    title: str,
    level: int,
    parent_id: int | None,
    status: str,
    priority: str,
    start_date: date | None,
    due_date: date | None,
    planned_hours: float,
    planned_cost: float,
    actual_expense_amount: float,
    progress: int,
    assigned_user_id: int | None,
    starcost: bool,
    description: str,
) -> Task:
    normalized_level = normalize_task_level(level)
    if normalized_level != int(level):
        raise ValueError(f"Le niveau de tâche doit être compris entre 1 et {MAX_TASK_LEVEL}.")
    if parent_id:
        parent = session.get(Task, parent_id)
        if not parent or parent.project_id != project_id:
            raise ValueError("La tâche parente doit appartenir au même projet.")
    if budget_id:
        budget = session.get(Budget, budget_id)
        if not budget or budget.project_id != project_id:
            raise ValueError("Le budget doit appartenir au même projet que la tâche.")
    max_order = session.scalar(select(func.max(Task.sort_order)).where(Task.project_id == project_id)) or 0
    task = Task(
        project_id=project_id,
        budget_id=budget_id,
        reference=next_task_reference(session, project_id),
        title=title.strip(),
        level=normalized_level,
        parent_id=parent_id,
        status=status,
        priority=priority,
        starcost=starcost,
        start_date=start_date,
        due_date=due_date,
        planned_hours=Decimal(str(planned_hours)),
        planned_cost=Decimal(str(planned_cost)),
        actual_expense_amount=Decimal(str(actual_expense_amount)),
        progress=progress,
        sort_order=int(max_order) + 10,
        description=description.strip() or None,
    )
    session.add(task)
    session.flush()
    if assigned_user_id:
        user = session.get(User, assigned_user_id)
        session.add(
            TaskAssignment(
                task_id=task.id,
                user_id=assigned_user_id,
                role="Affecte",
                planned_hours=Decimal(str(planned_hours)),
                cost_rate=user.hourly_rate if user else Decimal("0.00"),
            )
        )
    recompute_actuals(session)
    return task


def update_task_budget_and_expense(
    session: Session,
    task_id: int,
    budget_id: int | None,
    actual_expense_amount: float,
) -> None:
    task = session.get(Task, task_id)
    if not task:
        raise ValueError("Tâche introuvable.")
    if budget_id:
        budget = session.get(Budget, budget_id)
        if not budget or budget.project_id != task.project_id:
            raise ValueError("Le budget doit appartenir au même projet que la tâche.")
    task.budget_id = budget_id
    task.actual_expense_amount = Decimal(str(actual_expense_amount))
    recompute_actuals(session)


def add_assignment(session: Session, task_id: int, user_id: int, role: str, planned_hours: float, cost_rate: float) -> None:
    session.add(
        TaskAssignment(
            task_id=task_id,
            user_id=user_id,
            role=role.strip() or None,
            planned_hours=Decimal(str(planned_hours)),
            cost_rate=Decimal(str(cost_rate)),
        )
    )
    session.flush()
    recompute_actuals(session)


def add_dependency(session: Session, predecessor_id: int, successor_id: int, link_type: str, lag_days: int) -> None:
    if predecessor_id == successor_id:
        raise ValueError("Une tâche ne peut pas dépendre d'elle-même.")
    predecessor = session.get(Task, predecessor_id)
    successor = session.get(Task, successor_id)
    if not predecessor or not successor:
        raise ValueError("Tâche de dépendance introuvable.")
    if predecessor.project_id != successor.project_id:
        raise ValueError("Une dépendance ne peut relier que des tâches du même projet.")
    session.add(
        TaskDependency(
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            link_type=link_type,
            lag_days=lag_days,
        )
    )


def add_time_entry(
    session: Session,
    project_id: int,
    task_id: int,
    user_id: int,
    entry_date: date,
    hours: float,
    note: str,
) -> None:
    ensure_direct_time_task(session, task_id, project_id)
    session.add(
        TimeEntry(
            project_id=project_id,
            task_id=task_id,
            user_id=user_id,
            entry_date=entry_date,
            hours=Decimal(str(hours)),
            note=note.strip() or None,
        )
    )
    session.flush()
    recompute_actuals(session)


def add_budget_line(
    session: Session,
    budget_id: int,
    category: str,
    label: str,
    planned_amount: float,
) -> None:
    budget = session.get(Budget, budget_id)
    if not budget:
        raise ValueError("Budget introuvable.")
    session.add(
        BudgetLine(
            project_id=budget.project_id,
            budget_id=budget.id,
            category=category,
            label=label.strip(),
            planned_amount=Decimal(str(planned_amount)),
            committed_amount=Decimal("0.00"),
        )
    )
    session.flush()
    recompute_actuals(session)


def projects_df(session: Session) -> pd.DataFrame:
    rows = []
    for project, owner in session.execute(
        select(Project, User.full_name).outerjoin(User, Project.owner_id == User.id).order_by(Project.code)
    ):
        rows.append(
            {
                "ID": project.id,
                "Code": project.code,
                "Projet": project.name,
                "Responsable": owner or "",
                "Catégorie": project.category,
                "Statut": project.status,
                "Priorité": project.priority,
                "Début": project.start_date,
                "Fin": project.end_date,
                "Budget": float(project.budget_amount),
                "Budget heures": float(project.budget_hours),
                "Description": project.description or "",
            }
        )
    return pd.DataFrame(rows)


def tasks_df(
    session: Session,
    project_id: int | None = None,
    *,
    project_ids: Collection[int] | None = None,
) -> pd.DataFrame:
    stmt = (
        select(Task, Project.code, Project.name)
        .join(Project, Task.project_id == Project.id)
        .order_by(Task.project_id, Task.sort_order, Task.reference)
    )
    selected_project_ids = _project_ids(project_id, project_ids)
    if project_ids is not None and not selected_project_ids:
        return pd.DataFrame()
    if selected_project_ids:
        stmt = stmt.where(Task.project_id.in_(selected_project_ids))
    records = session.execute(stmt).all()
    project_meta: dict[int, tuple[str, str]] = {}
    tasks_by_id: dict[int, Task] = {}
    for task, project_code, project_name in records:
        tasks_by_id[task.id] = task
        project_meta[task.id] = (project_code, project_name)
    children_by_parent = _children_by_parent(list(tasks_by_id.values()))
    future_planned_direct: dict[int, Decimal] = {}
    if tasks_by_id:
        future_planned_direct = dict(
            session.execute(
                select(PlannedTimeEntry.task_id, func.coalesce(func.sum(PlannedTimeEntry.hours), 0))
                .where(
                    PlannedTimeEntry.task_id.in_(list(tasks_by_id)),
                    PlannedTimeEntry.entry_date >= date.today(),
                )
                .group_by(PlannedTimeEntry.task_id)
            ).all()
        )
    future_planned_cache: dict[int, Decimal] = {}

    def future_planned_hours(task: Task) -> Decimal:
        if task.id in future_planned_cache:
            return future_planned_cache[task.id]
        children = children_by_parent.get(task.id, [])
        if children:
            total = sum((future_planned_hours(child) for child in children), Decimal("0.00"))
        else:
            total = Decimal(future_planned_direct.get(task.id, Decimal("0.00")))
        future_planned_cache[task.id] = total
        return total

    for siblings in children_by_parent.values():
        siblings.sort(key=lambda item: (item.sort_order, item.reference, item.id))

    roots = [
        task
        for task in tasks_by_id.values()
        if not task.parent_id or task.parent_id not in tasks_by_id or task.parent_id == task.id
    ]
    roots.sort(key=lambda item: (item.project_id, item.sort_order, item.reference, item.id))

    ordered_tasks: list[Task] = []
    seen: set[int] = set()

    def walk(task: Task) -> None:
        if task.id in seen:
            return
        seen.add(task.id)
        ordered_tasks.append(task)
        for child in children_by_parent.get(task.id, []):
            walk(child)

    for root in roots:
        walk(root)
    for task in tasks_by_id.values():
        walk(task)

    rows = []
    for task in ordered_tasks:
        project_code, project_name = project_meta[task.id]
        assignees = session.execute(
            select(User.full_name)
            .join(TaskAssignment, TaskAssignment.user_id == User.id)
            .where(TaskAssignment.task_id == task.id)
            .order_by(User.full_name)
        ).scalars().all()
        child_count = len(children_by_parent.get(task.id, []))
        parent_ref = ""
        if task.parent_id:
            parent = session.get(Task, task.parent_id)
            parent_ref = f"{parent.reference} - {parent.title}" if parent else ""
        budget_label = ""
        if task.budget_id:
            budget = session.get(Budget, task.budget_id)
            if budget:
                budget_label = f"{budget.reference} - {budget.label}"
        elif task.budget_line_id:
            budget_line = session.get(BudgetLine, task.budget_line_id)
            if budget_line and budget_line.budget_id:
                budget = session.get(Budget, budget_line.budget_id)
                budget_label = f"{budget.reference} - {budget.label}" if budget else ""
        rows.append(
            {
                "ID": task.id,
                "Projet ID": task.project_id,
                "Projet Code": project_code,
                "Projet": f"{project_code} - {project_name}",
                "Référence": task.reference,
                "Titre": task.title,
                "Libellé": f"{task_level_prefix(task.level)}{task.reference} · {task.title}",
                "Niveau": task.level,
                "Enfants": child_count,
                "Mode calcul": "Agrégé" if child_count else "Direct",
                "Parent": parent_ref,
                "Parent ID": task.parent_id,
                "Budget": budget_label,
                "STARCOST": bool(task.starcost),
                "Statut": task.status,
                "Priorité": task.priority,
                "Début": task.start_date,
                "Fin estimée": task.due_date,
                "Date de clôture": task.actual_end_date,
                "Temps prévu": float(task.planned_hours),
                "Temps passé": float(task.actual_hours),
                "Temps planifié": float(future_planned_hours(task)),
                "Coût prévu": float(task.planned_cost),
                "Coût temps réel": float(task.actual_labor_cost),
                "Dépense directe": float(task.actual_expense_amount),
                "Coût réel total": float(task.actual_total_cost),
                "Avancement": task.progress,
                "Ressources": ", ".join(assignees),
                "Description": task.description or "",
            }
        )
    return pd.DataFrame(rows)


def visible_task_rows(
    data: pd.DataFrame,
    max_level: int = MAX_TASK_LEVEL,
    collapsed_task_ids: Collection[int] | None = None,
) -> pd.DataFrame:
    """Return the visible hierarchy without discarding columns or reordering rows."""
    if data.empty:
        return data.copy()
    collapsed = {int(value) for value in (collapsed_task_ids or [])}
    parent_by_id: dict[int, int | None] = {}
    project_by_id: dict[int, int | None] = {}
    for row in data.to_dict("records"):
        task_id = int(row["ID"])
        parent_value = row.get("Parent ID")
        parent_by_id[task_id] = int(parent_value) if pd.notna(parent_value) and parent_value not in (None, "") else None
        project_value = row.get("Projet ID")
        project_by_id[task_id] = int(project_value) if pd.notna(project_value) and project_value not in (None, "") else None

    def is_visible(row: pd.Series) -> bool:
        try:
            if int(row.get("Niveau") or 1) > max(1, min(int(max_level), MAX_TASK_LEVEL)):
                return False
            task_id = int(row["ID"])
        except (TypeError, ValueError):
            return False
        project_id = project_by_id.get(task_id)
        current = parent_by_id.get(task_id)
        seen = {task_id}
        while current is not None and current not in seen:
            if current in collapsed:
                return False
            if project_by_id.get(current) != project_id:
                break
            seen.add(current)
            current = parent_by_id.get(current)
        return True

    return data.loc[data.apply(is_visible, axis=1)].copy()


def dependencies_df(
    session: Session,
    project_id: int | None = None,
    *,
    project_ids: Collection[int] | None = None,
) -> pd.DataFrame:
    pred = Task.__table__.alias("pred")
    succ = Task.__table__.alias("succ")
    project = Project.__table__
    stmt = (
        select(
            TaskDependency.id,
            pred.c.id.label("predecessor_id"),
            pred.c.reference.label("predecessor_ref"),
            pred.c.title.label("predecessor_title"),
            succ.c.id.label("successor_id"),
            succ.c.reference.label("successor_ref"),
            succ.c.title.label("successor_title"),
            TaskDependency.link_type,
            TaskDependency.lag_days,
            succ.c.project_id.label("project_id"),
            project.c.code,
        )
        .join(pred, TaskDependency.predecessor_id == pred.c.id)
        .join(succ, TaskDependency.successor_id == succ.c.id)
        .join(project, succ.c.project_id == project.c.id)
        .order_by(project.c.code, pred.c.reference)
    )
    selected_project_ids = _project_ids(project_id, project_ids)
    if project_ids is not None and not selected_project_ids:
        return pd.DataFrame()
    if selected_project_ids:
        stmt = stmt.where(succ.c.project_id.in_(selected_project_ids))
    rows = []
    for row in session.execute(stmt):
        rows.append(
            {
                "ID": row.id,
                "Projet ID": row.project_id,
                "Projet": row.code,
                "Prédécesseur ID": row.predecessor_id,
                "Successeur ID": row.successor_id,
                "Prédécesseur": f"{row.predecessor_ref} - {row.predecessor_title}",
                "Successeur": f"{row.successor_ref} - {row.successor_title}",
                "Type": row.link_type,
                "Décalage": row.lag_days,
            }
        )
    return pd.DataFrame(rows)


def assignments_df(
    session: Session,
    project_id: int | None = None,
    *,
    project_ids: Collection[int] | None = None,
) -> pd.DataFrame:
    stmt = (
        select(TaskAssignment, Task.project_id, Project.code, Project.name, Task.reference, Task.title, User.full_name)
        .join(Task, TaskAssignment.task_id == Task.id)
        .join(Project, Task.project_id == Project.id)
        .join(User, TaskAssignment.user_id == User.id)
        .order_by(Project.code, Task.reference, User.full_name)
    )
    selected_project_ids = _project_ids(project_id, project_ids)
    if project_ids is not None and not selected_project_ids:
        return pd.DataFrame()
    if selected_project_ids:
        stmt = stmt.where(Task.project_id.in_(selected_project_ids))

    rows = []
    for assignment, project_id_value, project_code, project_name, task_ref, task_title, user_name in session.execute(stmt):
        rows.append(
            {
                "ID": assignment.id,
                "Projet ID": project_id_value,
                "Projet": f"{project_code} - {project_name}",
                "Tâche": f"{task_ref} - {task_title}",
                "Utilisateur": user_name,
                "Rôle": assignment.role or "",
                "Charge prévue": float(assignment.planned_hours),
                "Taux": float(assignment.cost_rate),
            }
        )
    return pd.DataFrame(rows)


def _time_entries_df(session: Session, entry_model, project_id: int | None = None, include_cost: bool = False) -> pd.DataFrame:
    stmt = (
        select(entry_model, Project.code, Project.name, Task.reference, Task.title, User.full_name)
        .join(Project, entry_model.project_id == Project.id)
        .join(Task, entry_model.task_id == Task.id)
        .join(User, entry_model.user_id == User.id)
        .order_by(entry_model.entry_date.desc(), entry_model.id.desc())
    )
    if project_id:
        stmt = stmt.where(entry_model.project_id == project_id)
    rows = []
    for entry, project_code, project_name, task_ref, task_title, user_name in session.execute(stmt):
        row = {
            "ID": entry.id,
            "Date": entry.entry_date,
            "Projet": f"{project_code} - {project_name}",
            "Tâche": f"{task_ref} - {task_title}",
            "Utilisateur": user_name,
            "Heures": float(entry.hours),
            "Note": entry.note or "",
        }
        if include_cost:
            row["Taux"] = float(entry.cost_rate)
            row["Coût"] = float(entry.cost_amount)
        rows.append(row)
    return pd.DataFrame(rows)


def time_entries_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    return _time_entries_df(session, TimeEntry, project_id, include_cost=True)


def planned_time_entries_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    return _time_entries_df(session, PlannedTimeEntry, project_id, include_cost=False)


WEEKDAY_LABELS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def week_dates(start: date) -> list[date]:
    monday = week_start(start)
    return [monday + timedelta(days=index) for index in range(7)]


def week_day_columns(start: date) -> list[tuple[date, str]]:
    return [(day, f"{WEEKDAY_LABELS[index]} {day:%d/%m/%Y}") for index, day in enumerate(week_dates(start))]


def _weekly_entries_df(session: Session, project_id: int, user_id: int, start: date, entry_model) -> pd.DataFrame:
    days = week_day_columns(start)
    day_dates = [day for day, _ in days]
    tasks = project_tasks(session, project_id)
    children_by_parent = _children_by_parent(tasks)
    aggregate_ids = set(children_by_parent)
    totals = {
        (task_id, entry_date): hours
        for task_id, entry_date, hours in session.execute(
            select(entry_model.task_id, entry_model.entry_date, func.coalesce(func.sum(entry_model.hours), 0))
            .where(
                entry_model.project_id == project_id,
                entry_model.user_id == user_id,
                entry_model.entry_date >= day_dates[0],
                entry_model.entry_date <= day_dates[-1],
            )
            .group_by(entry_model.task_id, entry_model.entry_date)
        ).all()
    }
    descendant_cache: dict[int, list[int]] = {}

    def descendant_ids(task_id: int) -> list[int]:
        if task_id in descendant_cache:
            return descendant_cache[task_id]
        ids: list[int] = []
        seen: set[int] = set()

        def walk(parent_id: int) -> None:
            for child in children_by_parent.get(parent_id, []):
                if child.id in seen:
                    continue
                seen.add(child.id)
                ids.append(child.id)
                walk(child.id)

        walk(task_id)
        descendant_cache[task_id] = ids
        return ids

    rows = []
    for task in tasks:
        is_direct = task.id not in aggregate_ids
        row = {
            "Tâche ID": task.id,
            "_time_editable": is_direct,
            "Tâche": f"{task_level_prefix(task.level)}{task.reference} - {task.title}",
            "Mode calcul": "Direct" if is_direct else "Agrégé",
        }
        for day, label in days:
            if is_direct:
                hours = totals.get((task.id, day), 0)
            else:
                hours = sum(totals.get((child_id, day), 0) or 0 for child_id in descendant_ids(task.id))
            row[label] = float(hours or 0)
        rows.append(row)
    return pd.DataFrame(
        rows,
        columns=["Tâche ID", "_time_editable", "Tâche", "Mode calcul"] + [label for _, label in days],
    )


def weekly_timesheet_df(session: Session, project_id: int, user_id: int, start: date) -> pd.DataFrame:
    return _weekly_entries_df(session, project_id, user_id, start, TimeEntry)


def weekly_planning_df(session: Session, project_id: int, user_id: int, start: date) -> pd.DataFrame:
    return _weekly_entries_df(session, project_id, user_id, start, PlannedTimeEntry)


def _save_weekly_entries(
    session: Session,
    project_id: int,
    user_id: int,
    start: date,
    data: pd.DataFrame,
    entry_model,
    note: str,
) -> None:
    days = week_day_columns(start)
    day_dates = [day for day, _ in days]
    valid_task_ids = {task.id for task in direct_tasks(session, project_id)}
    task_ids = []
    for row in data.to_dict("records"):
        task_id = int(_float(row.get("Tâche ID")))
        if task_id in valid_task_ids:
            task_ids.append(task_id)
    if task_ids:
        session.execute(
            delete(entry_model).where(
                entry_model.project_id == project_id,
                entry_model.user_id == user_id,
                entry_model.task_id.in_(task_ids),
                entry_model.entry_date >= day_dates[0],
                entry_model.entry_date <= day_dates[-1],
            )
        )

    for row in data.to_dict("records"):
        task_id = int(_float(row.get("Tâche ID")))
        if task_id not in valid_task_ids:
            continue
        ensure_direct_time_task(session, task_id, project_id)
        for day, label in days:
            hours = _float(row.get(label))
            if hours < 0 or hours > 24:
                raise ValueError("Chaque cellule de pointage doit être comprise entre 0 et 24 heures.")
            if hours > 0:
                session.add(
                    entry_model(
                        project_id=project_id,
                        task_id=task_id,
                        user_id=user_id,
                        entry_date=day,
                        hours=Decimal(str(hours)),
                        note=note,
                    )
                )
    session.flush()


def save_weekly_timesheet(
    session: Session,
    project_id: int,
    user_id: int,
    start: date,
    data: pd.DataFrame,
) -> None:
    _save_weekly_entries(session, project_id, user_id, start, data, TimeEntry, "Saisie hebdomadaire")
    recompute_actuals(session)


def save_weekly_planning(
    session: Session,
    project_id: int,
    user_id: int,
    start: date,
    data: pd.DataFrame,
) -> None:
    _save_weekly_entries(session, project_id, user_id, start, data, PlannedTimeEntry, "Planification hebdomadaire")


def starcost_hours_by_month_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    stmt = (
        select(TimeEntry.entry_date, TimeEntry.hours)
        .join(Task, TimeEntry.task_id == Task.id)
        .where(Task.starcost.is_(True))
        .order_by(TimeEntry.entry_date)
    )
    if project_id:
        stmt = stmt.where(TimeEntry.project_id == project_id)

    rows: list[dict[str, object]] = []
    for entry_date, hours in session.execute(stmt):
        if not entry_date:
            continue
        rows.append({"Mois": entry_date.strftime("%Y-%m"), "Heures STARCOST": float(hours or 0)})
    if not rows:
        return pd.DataFrame(columns=["Mois", "Heures STARCOST"])
    data = pd.DataFrame(rows)
    return data.groupby("Mois", as_index=False)["Heures STARCOST"].sum().sort_values("Mois")


def monthly_completion_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    stmt = select(Task).order_by(Task.project_id, Task.due_date, Task.reference)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    tasks = session.scalars(stmt).all()
    detail_tasks = _detail_tasks(tasks)

    rows: list[dict[str, object]] = []
    for task in detail_tasks:
        if not task.due_date:
            continue
        on_time = bool(task.actual_end_date and task.actual_end_date < task.due_date)
        rows.append(
            {
                "Mois": task.due_date.strftime("%Y-%m"),
                "Tâches prévues": 1,
                "Terminées à temps": 1 if on_time else 0,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["Mois", "Tâches prévues", "Terminées à temps"])
    data = pd.DataFrame(rows)
    return data.groupby("Mois", as_index=False)[["Tâches prévues", "Terminées à temps"]].sum().sort_values("Mois")


def legacy_budget_lines_summary_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    stmt = select(BudgetLine, Project.code, Project.name).join(Project).order_by(Project.code, BudgetLine.category)
    if project_id:
        stmt = stmt.where(BudgetLine.project_id == project_id)
    rows = []
    for line, project_code, project_name in session.execute(stmt):
        project_tasks = session.scalars(select(Task).where(Task.project_id == line.project_id)).all()
        parent_ids = _parent_task_ids(project_tasks)
        linked_tasks = [task for task in project_tasks if task.budget_line_id == line.id]
        detail_tasks = [task for task in linked_tasks if task.id not in parent_ids]
        planned_task_cost = sum(float(task.planned_cost) for task in detail_tasks)
        actual_hours = sum(float(task.actual_hours) for task in detail_tasks)
        actual_labor = sum(float(task.actual_labor_cost) for task in detail_tasks)
        actual_expense = sum(float(task.actual_expense_amount) for task in detail_tasks)
        actual_total = sum(float(task.actual_total_cost) for task in detail_tasks)
        rows.append(
            {
                "ID": line.id,
                "Projet ID": line.project_id,
                "Projet": f"{project_code} - {project_name}",
                "Catégorie": line.category,
                "Libellé": line.label,
                "Prévu": float(line.planned_amount),
                "Engagé": float(line.committed_amount),
                "Coût tâches prévu": planned_task_cost,
                "Temps passé": actual_hours,
                "Coût temps réel": actual_labor,
                "Dépenses tâches": actual_expense,
                "Réel": actual_total,
                "Tâches": len(linked_tasks),
                "Tâches détail": len(detail_tasks),
                "Reste": float(line.planned_amount - line.actual_amount),
            }
        )
    return pd.DataFrame(rows)


def budget_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    recompute_actuals(session)
    stmt = select(Budget, Project.code, Project.name).join(Project).order_by(Project.code, Budget.reference)
    if project_id:
        stmt = stmt.where(Budget.project_id == project_id)

    rows = []
    tasks_by_project: dict[int, list[Task]] = {}
    line_counts = dict(
        session.execute(select(BudgetLine.budget_id, func.count(BudgetLine.id)).group_by(BudgetLine.budget_id)).all()
    )
    for budget, project_code, project_name in session.execute(stmt):
        project_tasks = tasks_by_project.setdefault(
            budget.project_id,
            session.scalars(select(Task).where(Task.project_id == budget.project_id)).all(),
        )
        linked_tasks = [task for task in project_tasks if task.budget_id == budget.id]
        parent_ids = _parent_task_ids(project_tasks)
        detail_tasks = [task for task in linked_tasks if task.id not in parent_ids]
        planned = Decimal(budget.planned_amount or 0)
        committed = Decimal(budget.committed_amount or 0)
        rows.append(
            {
                "ID": budget.id,
                "Projet ID": budget.project_id,
                "Projet": f"{project_code} - {project_name}",
                "Référence": budget.reference,
                "Budget": budget.label,
                "Statut": budget.status,
                "Prévu": float(planned),
                "Engagé": float(committed),
                "Reste": float(planned - committed),
                "Tâches": len(linked_tasks),
                "Tâches détail": len(detail_tasks),
                "Lignes de frais": int(line_counts.get(budget.id, 0)),
            }
        )
    return pd.DataFrame(rows)


def budget_lines_df(session: Session, project_id: int | None = None, budget_id: int | None = None) -> pd.DataFrame:
    stmt = (
        select(BudgetLine, Budget.reference, Budget.label, Project.code, Project.name)
        .join(Budget, BudgetLine.budget_id == Budget.id)
        .join(Project, BudgetLine.project_id == Project.id)
        .order_by(Project.code, Budget.reference, BudgetLine.category, BudgetLine.label)
    )
    if project_id:
        stmt = stmt.where(BudgetLine.project_id == project_id)
    if budget_id:
        stmt = stmt.where(BudgetLine.budget_id == budget_id)

    rows = []
    for line, budget_reference, budget_label, project_code, project_name in session.execute(stmt):
        rows.append(
            {
                "ID": line.id,
                "Projet ID": line.project_id,
                "Budget ID": line.budget_id,
                "Projet": f"{project_code} - {project_name}",
                "Budget": f"{budget_reference} - {budget_label}",
                "Catégorie": line.category,
                "Libellé": line.label,
                "Prévu": float(line.planned_amount),
            }
        )
    return pd.DataFrame(rows)


def users_df(session: Session) -> pd.DataFrame:
    rows = []
    for user in session.scalars(select(User).order_by(User.full_name)):
        user_project = session.scalar(
            select(Project).where(Project.owner_id == user.id, Project.code.like("USER-%")).order_by(Project.id)
        )
        rows.append(
            {
                "ID": user.id,
                "Utilisateur": user.username,
                "Nom": user.full_name,
                "Email": user.email or "",
                "Rôle": user.role,
                "Taux horaire": float(user.hourly_rate),
                "Actif": user.active,
                "Projet utilisateur": user_project.code if user_project else "",
            }
        )
    return pd.DataFrame(rows)


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except TypeError:
        pass
    if isinstance(value, str):
        value = value.strip().replace(" ", "")
        if not value:
            return 0.0
        value = value.replace(",", ".")
    return float(value)


def _int(value: Any) -> int:
    return int(round(_float(value)))


def _bool(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "vrai", "oui", "yes", "x"}
    return bool(value)


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def update_projects_from_df(session: Session, data: pd.DataFrame) -> None:
    users = user_name_options(session)
    for row in data.to_dict("records"):
        project = session.get(Project, int(row["ID"]))
        if not project:
            continue
        project.code = _text(row.get("Code")).upper()
        project.name = _text(row.get("Projet"))
        project.owner_id = users.get(_text(row.get("Responsable")))
        project.category = _text(row.get("Catégorie")) or project.category
        project.status = _text(row.get("Statut")) or project.status
        project.priority = _text(row.get("Priorité")) or project.priority
        project.start_date = _date(row.get("Début"))
        project.end_date = _date(row.get("Fin"))
        project.budget_amount = Decimal(str(_float(row.get("Budget"))))
        project.budget_hours = Decimal(str(_float(row.get("Budget heures"))))
        project.description = _text(row.get("Description")) or None


def _update_task_rows(session: Session, data: pd.DataFrame, project_id: int) -> None:
    budgets = budget_options(session, project_id)
    task_labels = task_options(session, project_id)
    for row in data.to_dict("records"):
        task = session.get(Task, int(row["ID"]))
        if not task:
            continue
        if task.project_id != project_id or int(row.get("Projet ID") or project_id) != project_id:
            raise ValueError("Une tâche ne peut pas être déplacée vers un autre projet depuis la grille.")
        parent_value = _text(row.get("Parent"))
        parent_id = task_labels.get(parent_value)
        if parent_value and parent_id is None:
            raise ValueError(f"Le parent de {task.reference} doit appartenir au même projet.")
        if parent_id == task.id:
            raise ValueError(f"La tâche {task.reference} ne peut pas être son propre parent.")
        budget_value = _text(row.get("Budget"))
        budget_id = budgets.get(budget_value)
        if budget_value and budget_id is None:
            raise ValueError(f"Le budget de {task.reference} doit appartenir au même projet.")
        task.title = _text(row.get("Titre")) or task.title
        task.level = normalize_task_level(row.get("Niveau"))
        task.parent_id = parent_id
        task.budget_id = budget_id
        task.starcost = _bool(row.get("STARCOST"))
        task.status = _text(row.get("Statut")) or task.status
        task.priority = _text(row.get("Priorité")) or task.priority
        task.start_date = _date(row.get("Début"))
        task.due_date = _date(row.get("Fin estimée"))
        task.actual_end_date = _date(row.get("Date de clôture"))
        task.planned_hours = Decimal(str(_float(row.get("Temps prévu"))))
        task.planned_cost = Decimal(str(_float(row.get("Coût prévu"))))
        task.actual_expense_amount = Decimal(str(_float(row.get("Dépense directe"))))
        task.progress = min(max(_int(row.get("Avancement")), 0), 100)
        task.description = _text(row.get("Description")) or None


def update_tasks_from_df(session: Session, data: pd.DataFrame, project_id: int) -> None:
    _update_task_rows(session, data, project_id)
    validate_task_tree(session, project_id)
    recompute_actuals(session)


def update_tasks_from_projects_df(session: Session, data: pd.DataFrame, project_ids: Collection[int]) -> None:
    allowed_project_ids = set(_project_ids(None, project_ids))
    if not allowed_project_ids:
        return
    row_project_ids = {
        int(value)
        for value in data.get("Projet ID", pd.Series(dtype=int)).dropna().tolist()
    }
    if not row_project_ids.issubset(allowed_project_ids):
        raise ValueError("La grille contient une tâche d'un projet non sélectionné.")
    for project_id in sorted(row_project_ids):
        project_rows = data.loc[pd.to_numeric(data["Projet ID"], errors="coerce") == project_id]
        _update_task_rows(session, project_rows, project_id)
        validate_task_tree(session, project_id)
    recompute_actuals(session)


def validate_task_tree(session: Session, project_id: int) -> None:
    tasks = session.scalars(select(Task).where(Task.project_id == project_id)).all()
    parent_by_id = {task.id: task.parent_id for task in tasks}
    ref_by_id = {task.id: task.reference for task in tasks}
    task_ids = set(parent_by_id)
    for task_id in task_ids:
        seen: set[int] = set()
        current = task_id
        while current:
            if current in seen:
                raise ValueError(f"Cycle parent/enfant détecté autour de {ref_by_id.get(task_id, task_id)}.")
            seen.add(current)
            current = parent_by_id.get(current)
            if current not in task_ids:
                break


def update_budget_from_df(session: Session, data: pd.DataFrame) -> None:
    for row in data.to_dict("records"):
        budget = session.get(Budget, int(row["ID"]))
        if not budget:
            continue
        budget.label = _text(row.get("Budget")) or budget.label
        budget.status = _text(row.get("Statut")) or budget.status
    recompute_actuals(session)


def update_budget_lines_from_df(session: Session, data: pd.DataFrame, project_id: int) -> None:
    budgets = budget_options(session, project_id)
    for row in data.to_dict("records"):
        line = session.get(BudgetLine, int(row["ID"]))
        if not line:
            continue
        budget_id = budgets.get(_text(row.get("Budget")))
        if not budget_id:
            raise ValueError("Chaque ligne de frais doit rester rattachee a un budget.")
        budget = session.get(Budget, budget_id)
        if not budget or budget.project_id != project_id:
            raise ValueError("Budget invalide pour cette ligne de frais.")
        line.project_id = project_id
        line.budget_id = budget_id
        line.category = _text(row.get("Catégorie")) or line.category
        line.label = _text(row.get("Libellé")) or line.label
        line.planned_amount = Decimal(str(_float(row.get("Prévu"))))
    recompute_actuals(session)


def _update_time_entries_from_df(session: Session, data: pd.DataFrame, entry_model, project_id: int | None = None) -> None:
    users = user_name_options(session)
    tasks = direct_task_options(session, project_id)
    for row in data.to_dict("records"):
        entry = session.get(entry_model, int(row["ID"]))
        if not entry:
            continue
        task_id = tasks.get(_text(row.get("Tâche")))
        user_id = users.get(_text(row.get("Utilisateur")))
        if not task_id:
            raise ValueError("Pointage interdit : sélectionnez une tâche directe sans sous-tâche.")
        if not task_id or not user_id:
            raise ValueError("Chaque pointage doit conserver une tâche et un utilisateur valides.")
        task = ensure_direct_time_task(session, task_id, project_id)
        entry.project_id = task.project_id
        entry.task_id = task_id
        entry.user_id = user_id
        entry.entry_date = _date(row.get("Date")) or date.today()
        entry.hours = Decimal(str(_float(row.get("Heures"))))
        entry.note = _text(row.get("Note")) or None
    session.flush()


def update_time_entries_from_df(session: Session, data: pd.DataFrame, project_id: int | None = None) -> None:
    _update_time_entries_from_df(session, data, TimeEntry, project_id)
    recompute_actuals(session)


def update_planned_time_entries_from_df(session: Session, data: pd.DataFrame, project_id: int | None = None) -> None:
    _update_time_entries_from_df(session, data, PlannedTimeEntry, project_id)


def update_users_from_df(session: Session, data: pd.DataFrame) -> None:
    for row in data.to_dict("records"):
        user = session.get(User, int(row["ID"]))
        if not user:
            continue
        user.username = _text(row.get("Utilisateur")).lower() or user.username
        user.full_name = _text(row.get("Nom")) or user.full_name
        user.email = _text(row.get("Email")) or None
        user.role = _text(row.get("Rôle")) or user.role
        user.hourly_rate = Decimal(str(_float(row.get("Taux horaire"))))
        user.active = bool(row.get("Actif"))
    recompute_actuals(session)


def next_risk_assessment_reference(session: Session, project_id: int) -> str:
    project = get_project(session, project_id)
    references = session.scalars(
        select(RiskAssessment.reference).where(RiskAssessment.project_id == project_id)
    ).all()
    prefix = f"{project.code}-RSK-"
    numbers = [int(ref.removeprefix(prefix)) for ref in references if ref.startswith(prefix) and ref.removeprefix(prefix).isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:02d}"


def create_risk_assessment(
    session: Session,
    project_id: int,
    title: str,
    leader_id: int | None,
    product_or_change: str = "",
    scope: str = "",
    assumptions: str = "",
    applicable_requirements: str = "",
    acceptance_threshold: str = "Low",
    is_itns: bool = False,
    safety_importance: str = "Non applicable",
    graded_approach_rationale: str = "",
) -> RiskAssessment:
    if acceptance_threshold not in RISK_LEVELS:
        raise ValueError("Seuil d'acceptation invalide.")
    assessment = RiskAssessment(
        project_id=project_id,
        reference=next_risk_assessment_reference(session, project_id),
        title=title.strip(),
        leader_id=leader_id,
        product_or_change=product_or_change.strip() or None,
        scope=scope.strip() or None,
        assumptions=assumptions.strip() or None,
        applicable_requirements=applicable_requirements.strip() or None,
        acceptance_threshold=acceptance_threshold,
        is_itns=bool(is_itns),
        safety_importance=safety_importance,
        graded_approach_rationale=graded_approach_rationale.strip() or None,
    )
    if not assessment.title:
        raise ValueError("Le titre de l'analyse est obligatoire.")
    session.add(assessment)
    session.flush()
    return assessment


def update_risk_assessment(session: Session, assessment_id: int, **changes: Any) -> RiskAssessment:
    assessment = session.get(RiskAssessment, assessment_id)
    if not assessment:
        raise ValueError("Analyse de risques introuvable.")
    if assessment.status == "Clôturée" and set(changes) - {"status"}:
        raise ValueError("Rouvrez l'analyse avant de la modifier.")
    allowed = {
        "title", "leader_id", "product_or_change", "scope", "assumptions",
        "applicable_requirements", "acceptance_threshold", "is_itns",
        "safety_importance", "graded_approach_rationale", "start_date",
    }
    for field, value in changes.items():
        if field not in allowed or value is None:
            continue
        if field == "acceptance_threshold" and value not in RISK_LEVELS:
            raise ValueError("Seuil d'acceptation invalide.")
        if isinstance(value, str):
            value = value.strip()
        setattr(assessment, field, value)
    if not assessment.title:
        raise ValueError("Le titre de l'analyse est obligatoire.")
    session.flush()
    return assessment


def next_risk_reference(session: Session, assessment: RiskAssessment) -> str:
    references = session.scalars(select(Risk.reference).where(Risk.assessment_id == assessment.id)).all()
    prefix = f"{assessment.reference}-R"
    numbers = [int(ref.removeprefix(prefix)) for ref in references if ref.startswith(prefix) and ref.removeprefix(prefix).isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def create_risk(
    session: Session,
    assessment_id: int,
    lifecycle_phase: str,
    activity: str,
    hazard: str,
    cause: str,
    potential_consequence: str,
    existing_controls: str,
    owner_id: int | None,
    initial_likelihood: str,
    initial_consequence: int,
) -> Risk:
    assessment = session.get(RiskAssessment, assessment_id)
    if not assessment:
        raise ValueError("Analyse de risques introuvable.")
    if assessment.status == "Clôturée":
        raise ValueError("Une analyse clôturée ne peut plus recevoir de risque.")
    level = risk_level(initial_likelihood, initial_consequence)
    risk = Risk(
        assessment_id=assessment_id,
        reference=next_risk_reference(session, assessment),
        lifecycle_phase=lifecycle_phase,
        activity=activity.strip(),
        hazard=hazard.strip(),
        cause=cause.strip() or None,
        potential_consequence=potential_consequence.strip(),
        existing_controls=existing_controls.strip() or None,
        owner_id=owner_id,
        initial_likelihood=initial_likelihood.upper(),
        initial_consequence=int(initial_consequence),
        initial_level=level,
    )
    if not risk.activity or not risk.hazard or not risk.potential_consequence:
        raise ValueError("Activité, danger et conséquence potentielle sont obligatoires.")
    session.add(risk)
    session.flush()
    return risk


def update_risk(session: Session, risk_id: int, **changes: Any) -> Risk:
    risk = session.get(Risk, risk_id)
    if not risk:
        raise ValueError("Risque introuvable.")
    if risk.assessment.status == "Clôturée":
        raise ValueError("Rouvrez l'analyse avant de modifier un risque.")
    allowed = {
        "lifecycle_phase", "activity", "hazard", "cause", "potential_consequence",
        "existing_controls", "owner_id", "initial_likelihood", "initial_consequence",
    }
    for field, value in changes.items():
        if field not in allowed or value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
        setattr(risk, field, value)
    risk.initial_likelihood = risk.initial_likelihood.upper()
    risk.initial_consequence = int(risk.initial_consequence)
    risk.initial_level = risk_level(risk.initial_likelihood, risk.initial_consequence)
    if not risk.activity or not risk.hazard or not risk.potential_consequence:
        raise ValueError("Activité, danger et conséquence potentielle sont obligatoires.")
    risk.acceptance_status = "À statuer"
    risk.acceptance_justification = None
    risk.acceptance_user_id = None
    risk.acceptance_date = None
    session.flush()
    return risk


def risk_kpis(session: Session, project_id: int | None = None) -> dict[str, int]:
    assessment_stmt = select(RiskAssessment.id)
    if project_id:
        assessment_stmt = assessment_stmt.where(RiskAssessment.project_id == project_id)
    assessment_ids = session.scalars(assessment_stmt).all()
    risks = session.scalars(select(Risk).where(Risk.assessment_id.in_(assessment_ids))).all() if assessment_ids else []
    levels = [current_risk_rating(risk)[2] for risk in risks]
    return {
        "analyses": len(assessment_ids),
        "risks": len(risks),
        "high_or_extreme": sum(level in {"High", "Extreme"} for level in levels),
        "pending_acceptance": sum(risk.acceptance_status == "À statuer" for risk in risks),
    }


def current_risk_rating(risk: Risk) -> tuple[str, int, str]:
    verified = [item for item in risk.iterations if item.verification_status == "Vérifiée" and item.verified_level]
    if verified:
        latest = max(verified, key=lambda item: item.sequence)
        return str(latest.verified_likelihood), int(latest.verified_consequence), str(latest.verified_level)
    return risk.initial_likelihood, risk.initial_consequence, risk.initial_level


def create_risk_iteration(
    session: Session,
    risk_id: int,
    treatment: str,
    reduction_objective: str,
    additional_controls: str,
    contingency_plan: str,
    target_likelihood: str,
    target_consequence: int,
    task_ids: list[int] | None = None,
) -> RiskIteration:
    risk = session.get(Risk, risk_id)
    if not risk:
        raise ValueError("Risque introuvable.")
    if risk.assessment.status == "Clôturée":
        raise ValueError("L'analyse est clôturée.")
    sequence = (session.scalar(select(func.max(RiskIteration.sequence)).where(RiskIteration.risk_id == risk_id)) or 0) + 1
    iteration = RiskIteration(
        risk_id=risk_id,
        sequence=sequence,
        treatment=treatment.strip(),
        reduction_objective=reduction_objective.strip() or None,
        additional_controls=additional_controls.strip() or None,
        contingency_plan=contingency_plan.strip() or None,
        target_likelihood=target_likelihood.upper(),
        target_consequence=int(target_consequence),
        target_level=risk_level(target_likelihood, target_consequence),
    )
    if not iteration.treatment:
        raise ValueError("Le traitement du risque est obligatoire.")
    session.add(iteration)
    session.flush()
    for task_id in dict.fromkeys(task_ids or []):
        task = session.get(Task, int(task_id))
        if not task or task.project_id != risk.assessment.project_id:
            raise ValueError("Toutes les actions doivent appartenir au projet de l'analyse.")
        session.add(RiskIterationTask(iteration_id=iteration.id, task_id=task.id))
    session.flush()
    return iteration


def verify_risk_iteration(
    session: Session,
    iteration_id: int,
    likelihood: str,
    consequence: int,
    evidence: str,
    verifier_id: int,
) -> RiskIteration:
    iteration = session.get(RiskIteration, iteration_id)
    if not iteration:
        raise ValueError("Itération introuvable.")
    if not evidence.strip():
        raise ValueError("Une preuve de vérification est obligatoire.")
    finished_statuses = {"termine", "terminee", "cloture", "cloturee"}
    unfinished = [
        link.task.reference
        for link in iteration.task_links
        if link.task.status.lower().replace("é", "e").replace("ô", "o") not in finished_statuses
    ]
    if unfinished:
        raise ValueError("Les actions liées doivent être terminées avant vérification : " + ", ".join(unfinished))
    iteration.verified_likelihood = likelihood.upper()
    iteration.verified_consequence = int(consequence)
    iteration.verified_level = risk_level(likelihood, consequence)
    iteration.verification_evidence = evidence.strip()
    iteration.verification_status = "Vérifiée"
    iteration.verifier_id = verifier_id
    iteration.verified_at = datetime.utcnow()
    iteration.risk.acceptance_status = "À statuer"
    iteration.risk.acceptance_justification = None
    iteration.risk.acceptance_user_id = None
    iteration.risk.acceptance_date = None
    session.flush()
    return iteration


def decide_risk_acceptance(
    session: Session,
    risk_id: int,
    decision: str,
    justification: str,
    user_id: int,
) -> Risk:
    risk = session.get(Risk, risk_id)
    if not risk:
        raise ValueError("Risque introuvable.")
    allowed = {"À statuer", "Accepté", "Non accepté", "Accepté par dérogation"}
    if decision not in allowed:
        raise ValueError("Décision d'acceptation invalide.")
    _, _, level = current_risk_rating(risk)
    within = risk_is_within_threshold(level, risk.assessment.acceptance_threshold)
    if decision == "Accepté" and not within:
        raise ValueError("Ce niveau dépasse le seuil; utilisez une dérogation motivée.")
    if decision in {"Accepté", "Non accepté", "Accepté par dérogation"} and not justification.strip():
        raise ValueError("La justification de la décision est obligatoire.")
    risk.acceptance_status = decision
    risk.acceptance_justification = justification.strip() or None
    risk.acceptance_user_id = user_id if decision != "À statuer" else None
    risk.acceptance_date = datetime.utcnow() if decision != "À statuer" else None
    session.flush()
    return risk


def set_risk_assessment_status(session: Session, assessment_id: int, status: str) -> RiskAssessment:
    assessment = session.get(RiskAssessment, assessment_id)
    if not assessment:
        raise ValueError("Analyse de risques introuvable.")
    if status not in {"Ouverte", "Clôturée"}:
        raise ValueError("Statut d'analyse invalide.")
    if status == "Clôturée":
        if not assessment.risks:
            raise ValueError("Une analyse vide ne peut pas être clôturée.")
        unresolved = [risk.reference for risk in assessment.risks if risk.acceptance_status not in {"Accepté", "Accepté par dérogation"}]
        pending = [risk.reference for risk in assessment.risks if any(item.verification_status != "Vérifiée" for item in risk.iterations)]
        if unresolved:
            raise ValueError("Risques sans décision acceptable : " + ", ".join(unresolved))
        if pending:
            raise ValueError("Risques avec itération non vérifiée : " + ", ".join(pending))
        assessment.closed_at = datetime.utcnow()
    else:
        assessment.closed_at = None
    assessment.status = status
    session.flush()
    return assessment


def risk_assessments_df(session: Session, project_id: int) -> pd.DataFrame:
    rows = []
    assessments = session.scalars(select(RiskAssessment).where(RiskAssessment.project_id == project_id).order_by(RiskAssessment.reference)).all()
    for item in assessments:
        rows.append({
            "ID": item.id,
            "Référence": item.reference,
            "Analyse": item.title,
            "Statut": item.status,
            "Seuil": item.acceptance_threshold,
            "Responsable": item.leader.full_name if item.leader else "",
            "Produit / modification": item.product_or_change or "",
            "Périmètre": item.scope or "",
            "Hypothèses": item.assumptions or "",
            "Exigences": item.applicable_requirements or "",
            "ITNS": item.is_itns,
            "Importance sûreté": item.safety_importance,
            "Approche graduée": item.graded_approach_rationale or "",
            "Normes": item.standards,
        })
    return pd.DataFrame(rows)


def risks_df(session: Session, assessment_ids: list[int]) -> pd.DataFrame:
    if not assessment_ids:
        return pd.DataFrame()
    rows = []
    risks = session.scalars(select(Risk).where(Risk.assessment_id.in_(assessment_ids)).order_by(Risk.reference)).all()
    for item in risks:
        likelihood, consequence, level = current_risk_rating(item)
        rows.append({
            "ID": item.id,
            "Analyse ID": item.assessment_id,
            "Analyse": item.assessment.reference,
            "Référence": item.reference,
            "Phase": item.lifecycle_phase,
            "Activité": item.activity,
            "Danger": item.hazard,
            "Cause": item.cause or "",
            "Conséquence potentielle": item.potential_consequence,
            "Maîtrises existantes": item.existing_controls or "",
            "Responsable": item.owner.full_name if item.owner else "",
            "Vraisemblance initiale": item.initial_likelihood,
            "Conséquence initiale": item.initial_consequence,
            "Niveau initial": item.initial_level,
            "Vraisemblance courante": likelihood,
            "Conséquence courante": consequence,
            "Niveau courant": level,
            "Acceptation": item.acceptance_status,
            "Justification": item.acceptance_justification or "",
        })
    return pd.DataFrame(rows)


def risk_iterations_df(session: Session, risk_id: int) -> pd.DataFrame:
    rows = []
    items = session.scalars(select(RiskIteration).where(RiskIteration.risk_id == risk_id).order_by(RiskIteration.sequence)).all()
    for item in items:
        rows.append({
            "ID": item.id,
            "Itération": item.sequence,
            "Traitement": item.treatment,
            "Objectif": item.reduction_objective or "",
            "Maîtrises ajoutées": item.additional_controls or "",
            "Contingence": item.contingency_plan or "",
            "Cible": f"{item.target_likelihood}{item.target_consequence} - {item.target_level}",
            "Statut vérification": item.verification_status,
            "Résiduel vérifié": (
                f"{item.verified_likelihood}{item.verified_consequence} - {item.verified_level}"
                if item.verified_level else ""
            ),
            "Preuve": item.verification_evidence or "",
            "Actions": ", ".join(link.task.reference for link in item.task_links),
        })
    return pd.DataFrame(rows)


def risk_matrix_paths(session: Session, assessment_ids: list[int]) -> list[dict[str, Any]]:
    if not assessment_ids:
        return []
    paths = []
    for risk in session.scalars(select(Risk).where(Risk.assessment_id.in_(assessment_ids)).order_by(Risk.reference)).all():
        points = [{"likelihood": risk.initial_likelihood, "consequence": risk.initial_consequence, "level": risk.initial_level, "kind": "Initiale"}]
        for item in sorted(risk.iterations, key=lambda value: value.sequence):
            if item.verification_status == "Vérifiée" and item.verified_level:
                points.append({"likelihood": item.verified_likelihood, "consequence": item.verified_consequence, "level": item.verified_level, "kind": f"Itération {item.sequence}"})
        pending = next((item for item in reversed(risk.iterations) if item.verification_status != "Vérifiée"), None)
        paths.append({
            "risk_id": risk.id,
            "reference": risk.reference,
            "hazard": risk.hazard,
            "acceptance": risk.acceptance_status,
            "points": points,
            "pending_target": ({"likelihood": pending.target_likelihood, "consequence": pending.target_consequence, "level": pending.target_level} if pending else None),
        })
    return paths


def _task_descendant_ids(session: Session, task_id: int) -> list[int]:
    root = session.get(Task, task_id)
    if not root:
        return []
    project_tasks = session.scalars(select(Task).where(Task.project_id == root.project_id)).all()
    children_by_parent: dict[int, list[int]] = {}
    for task in project_tasks:
        if task.parent_id and task.parent_id != task.id:
            children_by_parent.setdefault(task.parent_id, []).append(task.id)

    ordered_ids: list[int] = []

    def walk(current_id: int) -> None:
        if current_id in ordered_ids:
            return
        ordered_ids.append(current_id)
        for child_id in children_by_parent.get(current_id, []):
            walk(child_id)

    walk(task_id)
    return ordered_ids


def _count_task_links(session: Session, task_ids: list[int]) -> dict[str, int]:
    if not task_ids:
        return {"assignments": 0, "time_entries": 0, "planned_time_entries": 0, "dependencies": 0, "risk_actions": 0}
    return {
        "assignments": session.scalar(select(func.count(TaskAssignment.id)).where(TaskAssignment.task_id.in_(task_ids))) or 0,
        "time_entries": session.scalar(select(func.count(TimeEntry.id)).where(TimeEntry.task_id.in_(task_ids))) or 0,
        "planned_time_entries": session.scalar(
            select(func.count(PlannedTimeEntry.id)).where(PlannedTimeEntry.task_id.in_(task_ids))
        )
        or 0,
        "dependencies": session.scalar(
            select(func.count(TaskDependency.id)).where(
                or_(TaskDependency.predecessor_id.in_(task_ids), TaskDependency.successor_id.in_(task_ids))
            )
        )
        or 0,
        "risk_actions": session.scalar(
            select(func.count(RiskIterationTask.id)).where(RiskIterationTask.task_id.in_(task_ids))
        )
        or 0,
    }


def deletion_preview(session: Session, entity: str, record_id: int) -> dict[str, Any]:
    if entity == "project":
        project = session.get(Project, record_id)
        if not project:
            raise ValueError("Projet introuvable.")
        task_ids = [task.id for task in session.scalars(select(Task).where(Task.project_id == project.id)).all()]
        task_links = _count_task_links(session, task_ids)
        budgets = session.scalar(select(func.count(Budget.id)).where(Budget.project_id == project.id)) or 0
        budget_lines = session.scalar(select(func.count(BudgetLine.id)).where(BudgetLine.project_id == project.id)) or 0
        assessment_ids = session.scalars(
            select(RiskAssessment.id).where(RiskAssessment.project_id == project.id)
        ).all()
        risk_ids = session.scalars(select(Risk.id).where(Risk.assessment_id.in_(assessment_ids))).all() if assessment_ids else []
        iterations = session.scalar(
            select(func.count(RiskIteration.id)).where(RiskIteration.risk_id.in_(risk_ids))
        ) if risk_ids else 0
        return {
            "label": f"{project.code} - {project.name}",
            "impacts": [
                f"{len(task_ids)} tâche(s) supprimée(s)",
                f"{task_links['assignments']} affectation(s) supprimée(s)",
                f"{task_links['time_entries']} pointage(s) supprimé(s)",
                f"{task_links['planned_time_entries']} planification(s) supprimée(s)",
                f"{task_links['dependencies']} dépendance(s) supprimée(s)",
                f"{budgets} budget(s) supprimé(s)",
                f"{budget_lines} ligne(s) de frais supprimée(s)",
                f"{len(assessment_ids)} analyse(s) de risques supprimée(s)",
                f"{len(risk_ids)} risque(s) et {iterations or 0} itération(s) supprimé(s)",
            ],
        }

    if entity == "task":
        task = session.get(Task, record_id)
        if not task:
            raise ValueError("Tâche introuvable.")
        task_ids = _task_descendant_ids(session, task.id)
        task_links = _count_task_links(session, task_ids)
        return {
            "label": f"{task.reference} - {task.title}",
            "impacts": [
                f"{len(task_ids) - 1} sous-tâche(s) supprimée(s)",
                f"{task_links['assignments']} affectation(s) supprimée(s)",
                f"{task_links['time_entries']} pointage(s) supprimé(s)",
                f"{task_links['planned_time_entries']} planification(s) supprimée(s)",
                f"{task_links['dependencies']} dépendance(s) supprimée(s)",
                f"{task_links['risk_actions']} lien(s) action/risque supprimé(s)",
            ],
        }

    if entity == "dependency":
        dependency = session.get(TaskDependency, record_id)
        if not dependency:
            raise ValueError("Dépendance introuvable.")
        predecessor = session.get(Task, dependency.predecessor_id)
        successor = session.get(Task, dependency.successor_id)
        return {
            "label": f"{predecessor.reference if predecessor else dependency.predecessor_id} -> {successor.reference if successor else dependency.successor_id}",
            "impacts": ["1 dépendance supprimée"],
        }

    if entity == "assignment":
        assignment = session.get(TaskAssignment, record_id)
        if not assignment:
            raise ValueError("Affectation introuvable.")
        task = session.get(Task, assignment.task_id)
        user = session.get(User, assignment.user_id)
        return {
            "label": f"{task.reference if task else assignment.task_id} - {user.full_name if user else assignment.user_id}",
            "impacts": ["1 affectation supprimée", "Les coûts de temps seront recalculés si le taux appliqué change."],
        }

    if entity == "time_entry":
        entry = session.get(TimeEntry, record_id)
        if not entry:
            raise ValueError("Pointage introuvable.")
        task = session.get(Task, entry.task_id)
        user = session.get(User, entry.user_id)
        return {
            "label": f"{entry.entry_date} - {task.reference if task else entry.task_id} - {user.full_name if user else entry.user_id}",
            "impacts": ["1 pointage supprimé", "La tâche et le budget associé seront recalculés."],
        }

    if entity == "planned_time_entry":
        entry = session.get(PlannedTimeEntry, record_id)
        if not entry:
            raise ValueError("Planification introuvable.")
        task = session.get(Task, entry.task_id)
        user = session.get(User, entry.user_id)
        return {
            "label": f"{entry.entry_date} - {task.reference if task else entry.task_id} - {user.full_name if user else entry.user_id}",
            "impacts": ["1 ligne de planification supprimée", "Le temps planifié futur de la tâche sera recalculé."],
        }

    if entity == "budget":
        budget = session.get(Budget, record_id)
        if not budget:
            raise ValueError("Budget introuvable.")
        line_ids = [line.id for line in session.scalars(select(BudgetLine).where(BudgetLine.budget_id == budget.id)).all()]
        linked_tasks = session.scalar(select(func.count(Task.id)).where(Task.budget_id == budget.id)) or 0
        legacy_tasks = (
            session.scalar(select(func.count(Task.id)).where(Task.budget_line_id.in_(line_ids))) if line_ids else 0
        ) or 0
        return {
            "label": f"{budget.reference} - {budget.label}",
            "impacts": [
                f"{len(line_ids)} ligne(s) de frais supprimée(s)",
                f"{linked_tasks} tâche(s) détachée(s) de ce budget",
                f"{legacy_tasks} lien(s) historique(s) tâche/ligne de frais nettoyé(s)",
            ],
        }

    if entity == "budget_line":
        line = session.get(BudgetLine, record_id)
        if not line:
            raise ValueError("Ligne de frais introuvable.")
        linked_tasks = session.scalar(select(func.count(Task.id)).where(Task.budget_line_id == line.id)) or 0
        return {
            "label": f"{line.category} - {line.label}",
            "impacts": [
                "1 ligne de frais supprimée",
                f"{linked_tasks} lien(s) historique(s) tâche/ligne de frais nettoyé(s)",
            ],
        }

    if entity == "risk_assessment":
        assessment = session.get(RiskAssessment, record_id)
        if not assessment:
            raise ValueError("Analyse de risques introuvable.")
        risk_ids = [risk.id for risk in assessment.risks]
        iterations = session.scalar(
            select(func.count(RiskIteration.id)).where(RiskIteration.risk_id.in_(risk_ids))
        ) if risk_ids else 0
        return {
            "label": f"{assessment.reference} - {assessment.title}",
            "impacts": [f"{len(risk_ids)} risque(s) supprimé(s)", f"{iterations or 0} itération(s) et leurs liens d'action supprimés"],
        }

    if entity == "risk":
        risk = session.get(Risk, record_id)
        if not risk:
            raise ValueError("Risque introuvable.")
        return {
            "label": f"{risk.reference} - {risk.hazard}",
            "impacts": [f"{len(risk.iterations)} itération(s) et leurs liens d'action supprimés"],
        }

    if entity == "risk_iteration":
        iteration = session.get(RiskIteration, record_id)
        if not iteration:
            raise ValueError("Itération introuvable.")
        return {
            "label": f"{iteration.risk.reference} - itération {iteration.sequence}",
            "impacts": [f"{len(iteration.task_links)} lien(s) vers des tâches supprimé(s)"],
        }

    if entity == "user":
        user = session.get(User, record_id)
        if not user:
            raise ValueError("Utilisateur introuvable.")
        owned_projects = session.scalar(select(func.count(Project.id)).where(Project.owner_id == user.id)) or 0
        assignments = session.scalar(select(func.count(TaskAssignment.id)).where(TaskAssignment.user_id == user.id)) or 0
        time_entries = session.scalar(select(func.count(TimeEntry.id)).where(TimeEntry.user_id == user.id)) or 0
        planned_time_entries = (
            session.scalar(select(func.count(PlannedTimeEntry.id)).where(PlannedTimeEntry.user_id == user.id)) or 0
        )
        grid_preferences = (
            session.scalar(select(func.count(UserGridPreference.id)).where(UserGridPreference.user_id == user.id)) or 0
        )
        return {
            "label": user.full_name,
            "impacts": [
                f"{owned_projects} projet(s) sans responsable",
                f"{assignments} affectation(s) supprimée(s)",
                f"{time_entries} pointage(s) supprimé(s)",
                f"{planned_time_entries} planification(s) supprimée(s)",
                f"{grid_preferences} préférence(s) d'affichage supprimée(s)",
            ],
        }

    raise ValueError("Type d'enregistrement non supporté.")


def delete_record(session: Session, entity: str, record_id: int) -> None:
    if entity == "project":
        project = session.get(Project, record_id)
        if not project:
            raise ValueError("Projet introuvable.")
        task_ids = [task.id for task in session.scalars(select(Task).where(Task.project_id == project.id)).all()]
        if task_ids:
            session.execute(delete(RiskIterationTask).where(RiskIterationTask.task_id.in_(task_ids)))
            session.execute(
                delete(TaskDependency).where(
                    or_(TaskDependency.predecessor_id.in_(task_ids), TaskDependency.successor_id.in_(task_ids))
                )
            )
        session.delete(project)
        session.flush()
        recompute_actuals(session)
        return

    if entity == "task":
        task_ids = _task_descendant_ids(session, record_id)
        if not task_ids:
            raise ValueError("Tâche introuvable.")
        session.execute(
            delete(RiskIterationTask).where(RiskIterationTask.task_id.in_(task_ids))
        )
        session.execute(
            delete(TaskDependency).where(
                or_(TaskDependency.predecessor_id.in_(task_ids), TaskDependency.successor_id.in_(task_ids))
            )
        )
        for task_id in reversed(task_ids):
            task = session.get(Task, task_id)
            if task:
                session.delete(task)
        session.flush()
        recompute_actuals(session)
        return

    if entity == "dependency":
        dependency = session.get(TaskDependency, record_id)
        if not dependency:
            raise ValueError("Dépendance introuvable.")
        session.delete(dependency)
        session.flush()
        recompute_actuals(session)
        return

    if entity == "assignment":
        assignment = session.get(TaskAssignment, record_id)
        if not assignment:
            raise ValueError("Affectation introuvable.")
        session.delete(assignment)
        session.flush()
        recompute_actuals(session)
        return

    if entity == "time_entry":
        entry = session.get(TimeEntry, record_id)
        if not entry:
            raise ValueError("Pointage introuvable.")
        session.delete(entry)
        session.flush()
        recompute_actuals(session)
        return

    if entity == "planned_time_entry":
        entry = session.get(PlannedTimeEntry, record_id)
        if not entry:
            raise ValueError("Planification introuvable.")
        session.delete(entry)
        session.flush()
        return

    if entity == "budget":
        budget = session.get(Budget, record_id)
        if not budget:
            raise ValueError("Budget introuvable.")
        line_ids = [line.id for line in session.scalars(select(BudgetLine).where(BudgetLine.budget_id == budget.id)).all()]
        for task in session.scalars(select(Task).where(Task.budget_id == budget.id)).all():
            task.budget_id = None
        if line_ids:
            for task in session.scalars(select(Task).where(Task.budget_line_id.in_(line_ids))).all():
                task.budget_line_id = None
        session.delete(budget)
        session.flush()
        recompute_actuals(session)
        return

    if entity == "budget_line":
        line = session.get(BudgetLine, record_id)
        if not line:
            raise ValueError("Ligne de frais introuvable.")
        for task in session.scalars(select(Task).where(Task.budget_line_id == line.id)).all():
            task.budget_line_id = None
        session.delete(line)
        session.flush()
        recompute_actuals(session)
        return

    if entity == "risk_assessment":
        assessment = session.get(RiskAssessment, record_id)
        if not assessment:
            raise ValueError("Analyse de risques introuvable.")
        session.delete(assessment)
        session.flush()
        return

    if entity == "risk":
        risk = session.get(Risk, record_id)
        if not risk:
            raise ValueError("Risque introuvable.")
        session.delete(risk)
        session.flush()
        return

    if entity == "risk_iteration":
        iteration = session.get(RiskIteration, record_id)
        if not iteration:
            raise ValueError("Itération introuvable.")
        session.delete(iteration)
        session.flush()
        return

    if entity == "user":
        user = session.get(User, record_id)
        if not user:
            raise ValueError("Utilisateur introuvable.")
        active_admins = session.scalar(
            select(func.count(User.id)).where(User.role == "admin", User.active.is_(True), User.id != user.id)
        ) or 0
        if user.role == "admin" and user.active and active_admins == 0:
            raise ValueError("Impossible de supprimer le dernier administrateur actif.")
        for project in session.scalars(select(Project).where(Project.owner_id == user.id)).all():
            project.owner_id = None
        session.execute(delete(TaskAssignment).where(TaskAssignment.user_id == user.id))
        session.execute(delete(TimeEntry).where(TimeEntry.user_id == user.id))
        session.execute(delete(PlannedTimeEntry).where(PlannedTimeEntry.user_id == user.id))
        session.execute(delete(UserGridPreference).where(UserGridPreference.user_id == user.id))
        for assessment in session.scalars(select(RiskAssessment).where(RiskAssessment.leader_id == user.id)).all():
            assessment.leader_id = None
        for risk in session.scalars(select(Risk).where(Risk.owner_id == user.id)).all():
            risk.owner_id = None
        for risk in session.scalars(select(Risk).where(Risk.acceptance_user_id == user.id)).all():
            risk.acceptance_user_id = None
        for iteration in session.scalars(select(RiskIteration).where(RiskIteration.verifier_id == user.id)).all():
            iteration.verifier_id = None
        session.delete(user)
        session.flush()
        recompute_actuals(session)
        return

    raise ValueError("Type d'enregistrement non supporté.")


def kpis(session: Session, project_id: int | None = None) -> dict[str, float | int]:
    recompute_actuals(session)
    task_stmt = select(Task)
    budget_stmt = select(Budget)
    project_stmt = select(Project)
    if project_id:
        task_stmt = task_stmt.where(Task.project_id == project_id)
        budget_stmt = budget_stmt.where(Budget.project_id == project_id)
        project_stmt = project_stmt.where(Project.id == project_id)

    tasks = session.scalars(task_stmt).all()
    projects = session.scalars(project_stmt).all()
    budget_lines = session.scalars(budget_stmt).all()
    detail_tasks = _detail_tasks(tasks)

    planned_hours = sum(float(t.planned_hours) for t in detail_tasks)
    actual_hours = sum(float(t.actual_hours) for t in detail_tasks)
    planned_cost = sum(float(t.planned_cost) for t in detail_tasks)
    actual_labor_cost = sum(float(t.actual_labor_cost) for t in detail_tasks)
    actual_expense_amount = sum(float(t.actual_expense_amount) for t in detail_tasks)
    actual_budget = sum(float(b.actual_amount) for b in budget_lines)
    planned_budget = sum(float(b.planned_amount) for b in budget_lines)
    progress = round(sum(t.progress for t in detail_tasks) / len(detail_tasks), 1) if detail_tasks else 0
    late = sum(
        1
        for t in detail_tasks
        if t.due_date and t.due_date < date.today() and t.status not in {"Termine", "Terminé"}
    )

    return {
        "projects": len(projects),
        "tasks": len(tasks),
        "planned_hours": planned_hours,
        "actual_hours": actual_hours,
        "planned_cost": planned_cost,
        "planned_budget": planned_budget,
        "actual_budget": actual_budget,
        "actual_labor_cost": actual_labor_cost,
        "actual_expense_amount": actual_expense_amount,
        "progress": progress,
        "late_tasks": late,
    }


def safe_commit(operation) -> tuple[bool, str]:
    try:
        operation()
        return True, "Opération enregistrée."
    except IntegrityError as exc:
        return False, f"Contrainte de données : {exc.orig}"
    except Exception as exc:
        return False, str(exc)
