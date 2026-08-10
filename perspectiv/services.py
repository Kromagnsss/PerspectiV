from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import recompute_actuals
from .models import Budget, BudgetLine, Project, Task, TaskAssignment, TaskDependency, TimeEntry, User
from .security import hash_password, verify_password


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


def user_name_options(session: Session) -> dict[str, int]:
    users = session.scalars(select(User).where(User.active.is_(True)).order_by(User.full_name)).all()
    return {u.full_name: u.id for u in users}


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
    return "| " * max(min(level_num, 4) - 1, 0)


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
    max_order = session.scalar(select(func.max(Task.sort_order)).where(Task.project_id == project_id)) or 0
    task = Task(
        project_id=project_id,
        budget_id=budget_id,
        reference=next_task_reference(session, project_id),
        title=title.strip(),
        level=level,
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


def tasks_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    stmt = (
        select(Task, Project.code, Project.name)
        .join(Project, Task.project_id == Project.id)
        .order_by(Task.project_id, Task.sort_order, Task.reference)
    )
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    records = session.execute(stmt).all()
    project_meta: dict[int, tuple[str, str]] = {}
    tasks_by_id: dict[int, Task] = {}
    for task, project_code, project_name in records:
        tasks_by_id[task.id] = task
        project_meta[task.id] = (project_code, project_name)
    children_by_parent = _children_by_parent(list(tasks_by_id.values()))

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
                "Projet": f"{project_code} - {project_name}",
                "Référence": task.reference,
                "Titre": task.title,
                "Libellé": f"{task_level_prefix(task.level)}{task.reference} · {task.title}",
                "Niveau": task.level,
                "Enfants": child_count,
                "Mode calcul": "Agrégé" if child_count else "Direct",
                "Parent": parent_ref,
                "Budget": budget_label,
                "STARCOST": bool(task.starcost),
                "Statut": task.status,
                "Priorité": task.priority,
                "Début": task.start_date,
                "Fin estimée": task.due_date,
                "Date de clôture": task.actual_end_date,
                "Temps prévu": float(task.planned_hours),
                "Temps passé": float(task.actual_hours),
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


def dependencies_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
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
            project.c.code,
        )
        .join(pred, TaskDependency.predecessor_id == pred.c.id)
        .join(succ, TaskDependency.successor_id == succ.c.id)
        .join(project, succ.c.project_id == project.c.id)
        .order_by(project.c.code, pred.c.reference)
    )
    if project_id:
        stmt = stmt.where(succ.c.project_id == project_id)
    rows = []
    for row in session.execute(stmt):
        rows.append(
            {
                "ID": row.id,
                "Prédécesseur ID": row.predecessor_id,
                "Successeur ID": row.successor_id,
                "Prédécesseur": f"{row.predecessor_ref} - {row.predecessor_title}",
                "Successeur": f"{row.successor_ref} - {row.successor_title}",
                "Type": row.link_type,
                "Décalage": row.lag_days,
            }
        )
    return pd.DataFrame(rows)


def assignments_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    stmt = (
        select(TaskAssignment, Project.code, Project.name, Task.reference, Task.title, User.full_name)
        .join(Task, TaskAssignment.task_id == Task.id)
        .join(Project, Task.project_id == Project.id)
        .join(User, TaskAssignment.user_id == User.id)
        .order_by(Project.code, Task.reference, User.full_name)
    )
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)

    rows = []
    for assignment, project_code, project_name, task_ref, task_title, user_name in session.execute(stmt):
        rows.append(
            {
                "ID": assignment.id,
                "Projet": f"{project_code} - {project_name}",
                "Tâche": f"{task_ref} - {task_title}",
                "Utilisateur": user_name,
                "Rôle": assignment.role or "",
                "Charge prévue": float(assignment.planned_hours),
                "Taux": float(assignment.cost_rate),
            }
        )
    return pd.DataFrame(rows)


def time_entries_df(session: Session, project_id: int | None = None) -> pd.DataFrame:
    stmt = (
        select(TimeEntry, Project.code, Project.name, Task.reference, Task.title, User.full_name)
        .join(Project, TimeEntry.project_id == Project.id)
        .join(Task, TimeEntry.task_id == Task.id)
        .join(User, TimeEntry.user_id == User.id)
        .order_by(TimeEntry.entry_date.desc(), TimeEntry.id.desc())
    )
    if project_id:
        stmt = stmt.where(TimeEntry.project_id == project_id)
    rows = []
    for entry, project_code, project_name, task_ref, task_title, user_name in session.execute(stmt):
        rows.append(
            {
                "ID": entry.id,
                "Date": entry.entry_date,
                "Projet": f"{project_code} - {project_name}",
                "Tâche": f"{task_ref} - {task_title}",
                "Utilisateur": user_name,
                "Heures": float(entry.hours),
                "Taux": float(entry.cost_rate),
                "Coût": float(entry.cost_amount),
                "Note": entry.note or "",
            }
        )
    return pd.DataFrame(rows)


WEEKDAY_LABELS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def week_dates(start: date) -> list[date]:
    monday = week_start(start)
    return [monday + timedelta(days=index) for index in range(7)]


def week_day_columns(start: date) -> list[tuple[date, str]]:
    return [(day, f"{WEEKDAY_LABELS[index]} {day:%d/%m/%Y}") for index, day in enumerate(week_dates(start))]


def weekly_timesheet_df(session: Session, project_id: int, user_id: int, start: date) -> pd.DataFrame:
    days = week_day_columns(start)
    day_dates = [day for day, _ in days]
    tasks = direct_tasks(session, project_id)
    totals = {
        (task_id, entry_date): hours
        for task_id, entry_date, hours in session.execute(
            select(TimeEntry.task_id, TimeEntry.entry_date, func.coalesce(func.sum(TimeEntry.hours), 0))
            .where(
                TimeEntry.project_id == project_id,
                TimeEntry.user_id == user_id,
                TimeEntry.entry_date >= day_dates[0],
                TimeEntry.entry_date <= day_dates[-1],
            )
            .group_by(TimeEntry.task_id, TimeEntry.entry_date)
        ).all()
    }

    rows = []
    for task in tasks:
        row = {"Tâche ID": task.id, "Tâche": f"{task_level_prefix(task.level)}{task.reference} - {task.title}"}
        for day, label in days:
            row[label] = float(totals.get((task.id, day), 0) or 0)
        rows.append(row)
    return pd.DataFrame(rows, columns=["Tâche ID", "Tâche"] + [label for _, label in days])


def save_weekly_timesheet(
    session: Session,
    project_id: int,
    user_id: int,
    start: date,
    data: pd.DataFrame,
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
            delete(TimeEntry).where(
                TimeEntry.project_id == project_id,
                TimeEntry.user_id == user_id,
                TimeEntry.task_id.in_(task_ids),
                TimeEntry.entry_date >= day_dates[0],
                TimeEntry.entry_date <= day_dates[-1],
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
                    TimeEntry(
                        project_id=project_id,
                        task_id=task_id,
                        user_id=user_id,
                        entry_date=day,
                        hours=Decimal(str(hours)),
                        note="Saisie hebdomadaire",
                    )
                )
    session.flush()
    recompute_actuals(session)


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
        rows.append(
            {
                "ID": user.id,
                "Utilisateur": user.username,
                "Nom": user.full_name,
                "Email": user.email or "",
                "Rôle": user.role,
                "Taux horaire": float(user.hourly_rate),
                "Actif": user.active,
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


def update_tasks_from_df(session: Session, data: pd.DataFrame, project_id: int) -> None:
    budgets = budget_options(session, project_id)
    task_labels = task_options(session, project_id)
    for row in data.to_dict("records"):
        task = session.get(Task, int(row["ID"]))
        if not task:
            continue
        parent_value = _text(row.get("Parent"))
        parent_id = task_labels.get(parent_value)
        if parent_id == task.id:
            raise ValueError(f"La tâche {task.reference} ne peut pas être son propre parent.")
        task.title = _text(row.get("Titre")) or task.title
        task.level = min(max(_int(row.get("Niveau")), 1), 4)
        task.parent_id = parent_id
        task.budget_id = budgets.get(_text(row.get("Budget")))
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


def update_time_entries_from_df(session: Session, data: pd.DataFrame, project_id: int) -> None:
    users = user_name_options(session)
    tasks = direct_task_options(session, project_id)
    for row in data.to_dict("records"):
        entry = session.get(TimeEntry, int(row["ID"]))
        if not entry:
            continue
        task_id = tasks.get(_text(row.get("Tâche")))
        user_id = users.get(_text(row.get("Utilisateur")))
        if not task_id:
            raise ValueError("Pointage interdit : sélectionnez une tâche directe sans sous-tâche.")
        if not task_id or not user_id:
            raise ValueError("Chaque pointage doit conserver une tâche et un utilisateur valides.")
        ensure_direct_time_task(session, task_id, project_id)
        entry.project_id = project_id
        entry.task_id = task_id
        entry.user_id = user_id
        entry.entry_date = _date(row.get("Date")) or date.today()
        entry.hours = Decimal(str(_float(row.get("Heures"))))
        entry.note = _text(row.get("Note")) or None
    recompute_actuals(session)


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
        return {"assignments": 0, "time_entries": 0, "dependencies": 0}
    return {
        "assignments": session.scalar(select(func.count(TaskAssignment.id)).where(TaskAssignment.task_id.in_(task_ids))) or 0,
        "time_entries": session.scalar(select(func.count(TimeEntry.id)).where(TimeEntry.task_id.in_(task_ids))) or 0,
        "dependencies": session.scalar(
            select(func.count(TaskDependency.id)).where(
                or_(TaskDependency.predecessor_id.in_(task_ids), TaskDependency.successor_id.in_(task_ids))
            )
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
        return {
            "label": f"{project.code} - {project.name}",
            "impacts": [
                f"{len(task_ids)} tâche(s) supprimée(s)",
                f"{task_links['assignments']} affectation(s) supprimée(s)",
                f"{task_links['time_entries']} pointage(s) supprimé(s)",
                f"{task_links['dependencies']} dépendance(s) supprimée(s)",
                f"{budgets} budget(s) supprimé(s)",
                f"{budget_lines} ligne(s) de frais supprimée(s)",
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
                f"{task_links['dependencies']} dépendance(s) supprimée(s)",
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

    if entity == "user":
        user = session.get(User, record_id)
        if not user:
            raise ValueError("Utilisateur introuvable.")
        owned_projects = session.scalar(select(func.count(Project.id)).where(Project.owner_id == user.id)) or 0
        assignments = session.scalar(select(func.count(TaskAssignment.id)).where(TaskAssignment.user_id == user.id)) or 0
        time_entries = session.scalar(select(func.count(TimeEntry.id)).where(TimeEntry.user_id == user.id)) or 0
        return {
            "label": user.full_name,
            "impacts": [
                f"{owned_projects} projet(s) sans responsable",
                f"{assignments} affectation(s) supprimée(s)",
                f"{time_entries} pointage(s) supprimé(s)",
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
