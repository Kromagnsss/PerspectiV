from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    AuditLog,
    Base,
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
)
from .security import hash_password
from .settings import (
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_NAME,
    BOOTSTRAP_ADMIN_PASSWORD,
    BOOTSTRAP_ADMIN_USERNAME,
    DATABASE_URL,
    ENVIRONMENT,
)


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    if ENVIRONMENT == "production":
        if "users" not in set(inspect(engine).get_table_names()):
            raise RuntimeError("Schéma absent : exécutez 'alembic upgrade head' avant de démarrer PerspectiV.")
    else:
        Base.metadata.create_all(engine)
        migrate_schema()
    with session_scope() as session:
        user_count = session.scalar(select(func.count(User.id)))
        if not user_count:
            if ENVIRONMENT == "production":
                seed_production_admin(session)
            else:
                seed_demo(session)
            recompute_actuals(session)
        else:
            ensure_budget_links(session)
            recompute_actuals(session)


def migrate_schema() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "tasks" in tables:
        task_columns = {column["name"] for column in inspector.get_columns("tasks")}
        task_additions = {
            "budget_id": "INTEGER",
            "budget_line_id": "INTEGER",
            "starcost": "BOOLEAN DEFAULT 0",
            "actual_labor_cost": "NUMERIC(14, 2) DEFAULT 0",
            "actual_expense_amount": "NUMERIC(14, 2) DEFAULT 0",
            "actual_total_cost": "NUMERIC(14, 2) DEFAULT 0",
        }
        with engine.begin() as connection:
            for column, ddl in task_additions.items():
                if column not in task_columns:
                    connection.execute(text(f"ALTER TABLE tasks ADD COLUMN {column} {ddl}"))

    inspector = inspect(engine)
    if "budget_lines" in set(inspector.get_table_names()):
        budget_line_columns = {column["name"] for column in inspector.get_columns("budget_lines")}
        budget_line_additions = {
            "budget_id": "INTEGER",
        }
        with engine.begin() as connection:
            for column, ddl in budget_line_additions.items():
                if column not in budget_line_columns:
                    connection.execute(text(f"ALTER TABLE budget_lines ADD COLUMN {column} {ddl}"))

    inspector = inspect(engine)
    if "time_entries" in set(inspector.get_table_names()):
        time_columns = {column["name"] for column in inspector.get_columns("time_entries")}
        time_additions = {
            "cost_rate": "NUMERIC(12, 2) DEFAULT 0",
            "cost_amount": "NUMERIC(14, 2) DEFAULT 0",
        }
        with engine.begin() as connection:
            for column, ddl in time_additions.items():
                if column not in time_columns:
                    connection.execute(text(f"ALTER TABLE time_entries ADD COLUMN {column} {ddl}"))

    inspector = inspect(engine)
    if "users" in set(inspector.get_table_names()):
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "oidc_subject" not in user_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN oidc_subject VARCHAR(255)"))


def seed_demo(session: Session) -> None:
    admin = User(
        username="admin",
        full_name="Administrateur",
        email="admin.local@perspectiv",
        role="admin",
        password_hash=hash_password("admin"),
        hourly_rate=Decimal("95.00"),
    )
    benoit = User(
        username="benoit",
        full_name="Benoit Gantiez",
        email="benoit.local@perspectiv",
        role="manager",
        password_hash=hash_password("demo"),
        hourly_rate=Decimal("90.00"),
    )
    paul = User(
        username="paul",
        full_name="Paul Bachimont",
        email="paul.local@perspectiv",
        role="member",
        password_hash=hash_password("demo"),
        hourly_rate=Decimal("75.00"),
    )
    session.add_all([admin, benoit, paul])
    session.flush()
    project = Project(
        code="PRJ-001",
        name="Refonte outil projets local",
        owner_id=benoit.id,
        category="Produit interne",
        priority="Haute",
        status="En cours",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 9, 15),
        budget_amount=Decimal("68000.00"),
        budget_hours=Decimal("720.00"),
        description="MVP local inspire d'OpenProject et ClickUp, simplifie pour usage equipe.",
    )
    session.add(project)
    session.flush()

    budgets = [
        Budget(project_id=project.id, reference="PRJ-001-BDG-01", label="Cadrage", status="Actif"),
        Budget(project_id=project.id, reference="PRJ-001-BDG-02", label="Conception et developpement", status="Actif"),
        Budget(project_id=project.id, reference="PRJ-001-BDG-03", label="Outillage", status="Actif"),
        Budget(project_id=project.id, reference="PRJ-001-BDG-04", label="Recette et deploiement", status="Actif"),
    ]
    session.add_all(budgets)
    session.flush()

    budget_lines = [
        BudgetLine(project_id=project.id, budget_id=budgets[0].id, category="Phase", label="Cadrage et ateliers", planned_amount=Decimal("14500"), committed_amount=Decimal("0")),
        BudgetLine(project_id=project.id, budget_id=budgets[1].id, category="Phase", label="Conception et developpement", planned_amount=Decimal("38000"), committed_amount=Decimal("0")),
        BudgetLine(project_id=project.id, budget_id=budgets[2].id, category="Outillage", label="Librairies et packaging", planned_amount=Decimal("2500"), committed_amount=Decimal("0")),
        BudgetLine(project_id=project.id, budget_id=budgets[3].id, category="Phase", label="Recette et deploiement", planned_amount=Decimal("13000"), committed_amount=Decimal("0")),
    ]
    session.add_all(budget_lines)
    session.flush()

    tasks = [
        Task(project_id=project.id, budget_id=budgets[0].id, budget_line_id=budget_lines[0].id, reference="PRJ-001-T001", title="Cadrage", level=1, start_date=date(2026, 7, 1), due_date=date(2026, 7, 12), planned_hours=60, planned_cost=5400, progress=70, status="En cours", sort_order=10),
        Task(project_id=project.id, budget_id=budgets[0].id, budget_line_id=budget_lines[0].id, reference="PRJ-001-T002", title="Ateliers besoins", level=2, start_date=date(2026, 7, 1), due_date=date(2026, 7, 5), planned_hours=24, planned_cost=2160, progress=100, status="Termine", sort_order=20),
        Task(project_id=project.id, budget_id=budgets[0].id, budget_line_id=budget_lines[0].id, reference="PRJ-001-T003", title="Cartographie processus", level=3, start_date=date(2026, 7, 4), due_date=date(2026, 7, 9), planned_hours=32, planned_cost=2400, progress=80, status="En cours", sort_order=30),
        Task(project_id=project.id, budget_id=budgets[0].id, budget_line_id=budget_lines[0].id, reference="PRJ-001-T004", title="Consolidation compte rendu", level=4, start_date=date(2026, 7, 9), due_date=date(2026, 7, 12), planned_hours=12, planned_cost=900, progress=40, status="En cours", sort_order=40),
        Task(project_id=project.id, budget_id=budgets[1].id, budget_line_id=budget_lines[1].id, reference="PRJ-001-T005", title="Conception", level=1, start_date=date(2026, 7, 13), due_date=date(2026, 7, 31), planned_hours=140, planned_cost=11900, progress=35, status="En cours", sort_order=50, actual_expense_amount=Decimal("300")),
        Task(project_id=project.id, budget_id=budgets[1].id, budget_line_id=budget_lines[1].id, reference="PRJ-001-T006", title="Modele de donnees", level=2, start_date=date(2026, 7, 15), due_date=date(2026, 7, 24), planned_hours=64, planned_cost=4800, progress=40, status="En cours", sort_order=60),
        Task(project_id=project.id, budget_id=budgets[1].id, budget_line_id=budget_lines[1].id, reference="PRJ-001-T007", title="Frontend Streamlit", level=2, start_date=date(2026, 7, 22), due_date=date(2026, 8, 10), planned_hours=130, planned_cost=11700, progress=10, status="Non commence", sort_order=70),
        Task(project_id=project.id, budget_id=budgets[3].id, budget_line_id=budget_lines[3].id, reference="PRJ-001-T008", title="Tests et recette", level=1, start_date=date(2026, 8, 11), due_date=date(2026, 8, 31), planned_hours=110, planned_cost=9350, progress=0, status="Non commence", sort_order=80),
        Task(project_id=project.id, budget_id=budgets[3].id, budget_line_id=budget_lines[3].id, reference="PRJ-001-T009", title="Deploiement local", level=1, start_date=date(2026, 9, 1), due_date=date(2026, 9, 15), planned_hours=80, planned_cost=6800, progress=0, status="Non commence", sort_order=90),
    ]
    session.add_all(tasks)
    session.flush()

    tasks[1].parent_id = tasks[0].id
    tasks[2].parent_id = tasks[0].id
    tasks[3].parent_id = tasks[2].id
    tasks[5].parent_id = tasks[4].id
    tasks[6].parent_id = tasks[4].id

    session.add_all(
        [
            TaskAssignment(task_id=tasks[0].id, user_id=benoit.id, role="Pilotage", planned_hours=40, cost_rate=90),
            TaskAssignment(task_id=tasks[1].id, user_id=benoit.id, role="Animation", planned_hours=24, cost_rate=90),
            TaskAssignment(task_id=tasks[2].id, user_id=paul.id, role="Analyse", planned_hours=32, cost_rate=75),
            TaskAssignment(task_id=tasks[4].id, user_id=benoit.id, role="Architecture", planned_hours=60, cost_rate=90),
            TaskAssignment(task_id=tasks[5].id, user_id=paul.id, role="Data", planned_hours=64, cost_rate=75),
            TaskAssignment(task_id=tasks[6].id, user_id=benoit.id, role="UX", planned_hours=50, cost_rate=90),
            TaskAssignment(task_id=tasks[6].id, user_id=paul.id, role="Dev", planned_hours=80, cost_rate=75),
        ]
    )

    session.add_all(
        [
            TaskDependency(predecessor_id=tasks[0].id, successor_id=tasks[4].id),
            TaskDependency(predecessor_id=tasks[4].id, successor_id=tasks[7].id),
            TaskDependency(predecessor_id=tasks[7].id, successor_id=tasks[8].id),
            TaskDependency(predecessor_id=tasks[2].id, successor_id=tasks[3].id),
        ]
    )

    session.add_all(
        [
            TimeEntry(project_id=project.id, task_id=tasks[1].id, user_id=benoit.id, entry_date=date(2026, 7, 2), hours=Decimal("6.00"), note="Atelier besoin"),
            TimeEntry(project_id=project.id, task_id=tasks[1].id, user_id=benoit.id, entry_date=date(2026, 7, 3), hours=Decimal("5.50"), note="Synthese atelier"),
            TimeEntry(project_id=project.id, task_id=tasks[3].id, user_id=paul.id, entry_date=date(2026, 7, 6), hours=Decimal("7.00"), note="Cartographie initiale"),
            TimeEntry(project_id=project.id, task_id=tasks[5].id, user_id=paul.id, entry_date=date(2026, 7, 16), hours=Decimal("4.00"), note="Modele entites"),
        ]
    )

    assessment = RiskAssessment(
        project_id=project.id,
        reference="PRJ-001-RSK-01",
        title="Analyse de risques de la refonte",
        leader_id=benoit.id,
        product_or_change="Application PerspectiV",
        scope="Conception, développement, validation et déploiement local.",
        assumptions="Cinq utilisateurs sur le réseau d'entreprise.",
        applicable_requirements="Disponibilité, intégrité des données et traçabilité.",
        acceptance_threshold="Low",
        is_itns=False,
        graded_approach_rationale="Approche proportionnée à un outil interne non lié à la sûreté.",
    )
    session.add(assessment)
    session.flush()
    risk = Risk(
        assessment_id=assessment.id,
        reference="PRJ-001-RSK-01-R001",
        lifecycle_phase="Conception",
        activity="Migration et stockage des données",
        hazard="Perte ou altération de données projet",
        cause="Migration incomplète ou sauvegarde indisponible",
        potential_consequence="Perte de traçabilité et reconstitution manuelle des données.",
        existing_controls="Sauvegarde avant migration et contrôle de santé après redémarrage.",
        owner_id=benoit.id,
        initial_likelihood="C",
        initial_consequence=4,
        initial_level="High",
        acceptance_status="À statuer",
    )
    session.add(risk)
    session.flush()
    iteration = RiskIteration(
        risk_id=risk.id,
        sequence=1,
        treatment="Tester la restauration automatique sur une copie de production.",
        reduction_objective="Ramener la vraisemblance à improbable.",
        additional_controls="Test de restauration et journal de migration.",
        target_likelihood="D",
        target_consequence=3,
        target_level="Medium",
    )
    session.add(iteration)
    session.flush()
    session.add(RiskIterationTask(iteration_id=iteration.id, task_id=tasks[7].id))

    session.flush()
    recompute_actuals(session)


def seed_production_admin(session: Session) -> None:
    if len(BOOTSTRAP_ADMIN_PASSWORD) < 14:
        raise RuntimeError(
            "PERSPECTIV_BOOTSTRAP_ADMIN_PASSWORD doit contenir au moins 14 caractères lors du premier démarrage."
        )
    session.add(
        User(
            username=BOOTSTRAP_ADMIN_USERNAME,
            full_name=BOOTSTRAP_ADMIN_NAME,
            email=BOOTSTRAP_ADMIN_EMAIL or None,
            role="admin",
            password_hash=hash_password(BOOTSTRAP_ADMIN_PASSWORD),
            hourly_rate=Decimal("0.00"),
            active=True,
        )
    )
    session.flush()


def legacy_ensure_budget_line_links(session: Session) -> None:
    for project in session.scalars(select(Project)).all():
        budgets = session.scalars(
            select(BudgetLine).where(BudgetLine.project_id == project.id).order_by(BudgetLine.id)
        ).all()
        if not budgets:
            continue
        fallback = budgets[0]
        conception = next((line for line in budgets if "conception" in line.label.lower()), fallback)
        recette = next(
            (line for line in budgets if "recette" in line.label.lower() or "deploiement" in line.label.lower()),
            fallback,
        )
        for task in session.scalars(select(Task).where(Task.project_id == project.id, Task.budget_line_id.is_(None))):
            title = task.title.lower()
            if any(word in title for word in ("test", "recette", "deploiement", "déploiement")):
                task.budget_line_id = recette.id
            elif any(word in title for word in ("conception", "modele", "frontend", "developpement", "développement")):
                task.budget_line_id = conception.id
            else:
                task.budget_line_id = fallback.id


def ensure_budget_links(session: Session) -> None:
    for project in session.scalars(select(Project)).all():
        budgets = session.scalars(
            select(Budget).where(Budget.project_id == project.id).order_by(Budget.reference, Budget.id)
        ).all()
        budget_lines = session.scalars(
            select(BudgetLine).where(BudgetLine.project_id == project.id).order_by(BudgetLine.id)
        ).all()

        if not budgets:
            if budget_lines:
                budgets = []
                for index, line in enumerate(budget_lines, start=1):
                    budget = Budget(
                        project_id=project.id,
                        reference=f"{project.code}-BDG-{index:02d}",
                        label=line.label,
                        status="Actif",
                    )
                    session.add(budget)
                    session.flush()
                    line.budget_id = budget.id
                    budgets.append(budget)
            else:
                budget = Budget(
                    project_id=project.id,
                    reference=f"{project.code}-BDG-01",
                    label="Budget principal",
                    status="Actif",
                )
                session.add(budget)
                session.flush()
                session.add(
                    BudgetLine(
                        project_id=project.id,
                        budget_id=budget.id,
                        category="Budget",
                        label="Enveloppe principale",
                        planned_amount=Decimal(project.budget_amount or 0),
                        committed_amount=Decimal("0.00"),
                    )
                )
                session.flush()
                budgets = [budget]
                budget_lines = session.scalars(
                    select(BudgetLine).where(BudgetLine.project_id == project.id).order_by(BudgetLine.id)
                ).all()

        fallback = budgets[0]
        for line in budget_lines:
            if line.budget_id is None:
                line.budget_id = fallback.id

        lines_by_id = {line.id: line for line in budget_lines}
        conception = next((budget for budget in budgets if "conception" in budget.label.lower()), fallback)
        recette = next(
            (budget for budget in budgets if "recette" in budget.label.lower() or "deploiement" in budget.label.lower()),
            fallback,
        )
        for task in session.scalars(select(Task).where(Task.project_id == project.id, Task.budget_id.is_(None))):
            legacy_line = lines_by_id.get(task.budget_line_id) if task.budget_line_id else None
            if legacy_line and legacy_line.budget_id:
                task.budget_id = legacy_line.budget_id
                continue
            title = task.title.lower()
            if any(word in title for word in ("test", "recette", "deploiement")):
                task.budget_id = recette.id
            elif any(word in title for word in ("conception", "modele", "frontend", "developpement")):
                task.budget_id = conception.id
            else:
                task.budget_id = fallback.id


def entry_rate(session: Session, entry: TimeEntry) -> Decimal:
    assignment = session.scalar(
        select(TaskAssignment).where(
            TaskAssignment.task_id == entry.task_id,
            TaskAssignment.user_id == entry.user_id,
        )
    )
    if assignment and assignment.cost_rate:
        return Decimal(assignment.cost_rate)
    user = session.get(User, entry.user_id)
    return Decimal(user.hourly_rate) if user and user.hourly_rate else Decimal("0.00")


def recompute_actuals(session: Session) -> None:
    ensure_budget_links(session)

    for entry in session.scalars(select(TimeEntry)).all():
        rate = entry_rate(session, entry)
        entry.cost_rate = rate
        entry.cost_amount = Decimal(entry.hours or 0) * rate

    hour_totals = dict(
        session.execute(
            select(TimeEntry.task_id, func.coalesce(func.sum(TimeEntry.hours), 0)).group_by(TimeEntry.task_id)
        ).all()
    )
    labor_totals = dict(
        session.execute(
            select(TimeEntry.task_id, func.coalesce(func.sum(TimeEntry.cost_amount), 0)).group_by(TimeEntry.task_id)
        ).all()
    )
    tasks = session.scalars(select(Task).order_by(Task.project_id, Task.sort_order, Task.id)).all()
    for task in tasks:
        task.actual_hours = Decimal(hour_totals.get(task.id, Decimal("0.00")))
        task.actual_labor_cost = Decimal(labor_totals.get(task.id, Decimal("0.00")))
        task.actual_expense_amount = Decimal(task.actual_expense_amount or 0)
        task.actual_total_cost = task.actual_labor_cost + task.actual_expense_amount

    rollup_parent_tasks(tasks)

    parent_ids = aggregate_task_ids(tasks)
    budget_totals: dict[int, Decimal] = {}
    for task in tasks:
        if not task.budget_id or task.id in parent_ids:
            continue
        budget_totals[task.budget_id] = budget_totals.get(task.budget_id, Decimal("0.00")) + Decimal(
            task.actual_total_cost or 0
        )
    planned_totals = dict(
        session.execute(
            select(BudgetLine.budget_id, func.coalesce(func.sum(BudgetLine.planned_amount), 0))
            .where(BudgetLine.budget_id.is_not(None))
            .group_by(BudgetLine.budget_id)
        ).all()
    )
    for budget in session.scalars(select(Budget)).all():
        budget.planned_amount = Decimal(planned_totals.get(budget.id, Decimal("0.00")))
        budget.committed_amount = Decimal(budget_totals.get(budget.id, Decimal("0.00")))
        budget.actual_amount = budget.committed_amount

    line_totals: dict[int, Decimal] = {}
    for task in tasks:
        if not task.budget_line_id or task.id in parent_ids:
            continue
        line_totals[task.budget_line_id] = line_totals.get(task.budget_line_id, Decimal("0.00")) + Decimal(
            task.actual_total_cost or 0
        )
    for line in session.scalars(select(BudgetLine)).all():
        line.actual_amount = Decimal(line_totals.get(line.id, Decimal("0.00")))


def recompute_actual_hours(session: Session) -> None:
    recompute_actuals(session)


def aggregate_task_ids(tasks: list[Task]) -> set[int]:
    task_ids = {task.id for task in tasks}
    return {
        task.parent_id
        for task in tasks
        if task.parent_id and task.parent_id in task_ids and task.parent_id != task.id
    }


def rollup_parent_tasks(tasks: list[Task]) -> None:
    tasks_by_id = {task.id: task for task in tasks}
    children_by_parent: dict[int, list[Task]] = {}
    for task in tasks:
        if task.parent_id and task.parent_id in tasks_by_id and task.parent_id != task.id:
            children_by_parent.setdefault(task.parent_id, []).append(task)

    visited: set[int] = set()
    visiting: set[int] = set()

    def apply_rollup(task: Task) -> None:
        if task.id in visited:
            return
        if task.id in visiting:
            return
        visiting.add(task.id)
        children = children_by_parent.get(task.id, [])
        for child in children:
            apply_rollup(child)
        if children:
            start_dates = [child.start_date for child in children if child.start_date]
            end_dates = [child.due_date for child in children if child.due_date]
            task.start_date = min(start_dates) if start_dates else None
            task.due_date = max(end_dates) if end_dates else None
            task.planned_hours = sum((Decimal(child.planned_hours or 0) for child in children), Decimal("0.00"))
            task.planned_cost = sum((Decimal(child.planned_cost or 0) for child in children), Decimal("0.00"))
            task.actual_hours = sum((Decimal(child.actual_hours or 0) for child in children), Decimal("0.00"))
            task.actual_labor_cost = sum((Decimal(child.actual_labor_cost or 0) for child in children), Decimal("0.00"))
            task.actual_expense_amount = sum((Decimal(child.actual_expense_amount or 0) for child in children), Decimal("0.00"))
            task.actual_total_cost = sum((Decimal(child.actual_total_cost or 0) for child in children), Decimal("0.00"))
            total_weight = sum(float(child.planned_hours or 0) for child in children)
            if total_weight > 0:
                task.progress = int(round(sum(child.progress * float(child.planned_hours or 0) for child in children) / total_weight))
            else:
                task.progress = int(round(sum(child.progress for child in children) / len(children)))
        visiting.remove(task.id)
        visited.add(task.id)

    for task in tasks:
        apply_rollup(task)
