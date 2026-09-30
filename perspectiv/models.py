from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(32), default="member")
    password_hash: Mapped[str] = mapped_column(String(220))
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("85.00"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)

    assignments: Mapped[list["TaskAssignment"]] = relationship(back_populates="user")
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="user")
    planned_time_entries: Mapped[list["PlannedTimeEntry"]] = relationship(back_populates="user")
    grid_preferences: Mapped[list["UserGridPreference"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserGridPreference(Base):
    __tablename__ = "user_grid_preferences"
    __table_args__ = (UniqueConstraint("user_id", "grid_key", name="uq_user_grid_preference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    grid_key: Mapped[str] = mapped_column(String(120), index=True)
    visible_columns: Mapped[str] = mapped_column(Text, default="[]")

    user: Mapped[User] = relationship(back_populates="grid_preferences")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(80), default="Interne")
    priority: Mapped[str] = mapped_column(String(32), default="Normale")
    status: Mapped[str] = mapped_column(String(32), default="En cours")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    budget_hours: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped[User | None] = relationship()
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    planned_time_entries: Mapped[list["PlannedTimeEntry"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    budgets: Mapped[list["Budget"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    budget_lines: Mapped[list["BudgetLine"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("budgets.id"), index=True)
    budget_line_id: Mapped[int | None] = mapped_column(ForeignKey("budget_lines.id"), index=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    level: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    status: Mapped[str] = mapped_column(String(32), default="Non commencé")
    priority: Mapped[str] = mapped_column(String(32), default="Normale")
    starcost: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    planned_hours: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    planned_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    actual_hours: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    actual_labor_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    actual_expense_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    actual_total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    actual_end_date: Mapped[date | None] = mapped_column(Date)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="tasks")
    budget: Mapped["Budget | None"] = relationship(back_populates="tasks")
    budget_line: Mapped["BudgetLine | None"] = relationship(back_populates="tasks")
    parent: Mapped["Task | None"] = relationship(remote_side=[id])
    assignments: Mapped[list["TaskAssignment"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    planned_time_entries: Mapped[list["PlannedTimeEntry"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskAssignment(Base):
    __tablename__ = "task_assignments"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str | None] = mapped_column(String(100))
    planned_hours: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    cost_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    task: Mapped[Task] = relationship(back_populates="assignments")
    user: Mapped[User] = relationship(back_populates="assignments")


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("predecessor_id", "successor_id", name="uq_dependency_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    predecessor_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    successor_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    link_type: Mapped[str] = mapped_column(String(32), default="Fin-Début")
    lag_days: Mapped[int] = mapped_column(Integer, default=0)


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, default=date.today)
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    cost_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="time_entries")
    task: Mapped[Task] = relationship(back_populates="time_entries")
    user: Mapped[User] = relationship(back_populates="time_entries")


class PlannedTimeEntry(Base):
    __tablename__ = "planned_time_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, default=date.today)
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="planned_time_entries")
    task: Mapped[Task] = relationship(back_populates="planned_time_entries")
    user: Mapped[User] = relationship(back_populates="planned_time_entries")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("project_id", "reference", name="uq_project_budget_reference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(32), default="Actif")
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    committed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    actual_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))

    project: Mapped[Project] = relationship(back_populates="budgets")
    lines: Mapped[list["BudgetLine"]] = relationship(back_populates="budget", cascade="all, delete-orphan")
    tasks: Mapped[list[Task]] = relationship(back_populates="budget")


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("budgets.id"), index=True)
    category: Mapped[str] = mapped_column(String(80), default="Main d'oeuvre")
    label: Mapped[str] = mapped_column(String(180))
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    committed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    actual_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))

    project: Mapped[Project] = relationship(back_populates="budget_lines")
    budget: Mapped[Budget | None] = relationship(back_populates="lines")
    tasks: Mapped[list[Task]] = relationship(back_populates="budget_line")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (UniqueConstraint("project_id", "reference", name="uq_project_risk_assessment_reference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    reference: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    status: Mapped[str] = mapped_column(String(24), default="Ouverte")
    product_or_change: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[str | None] = mapped_column(Text)
    applicable_requirements: Mapped[str | None] = mapped_column(Text)
    standards: Mapped[str] = mapped_column(
        Text, default="ISO 9001:2026; ISO 29001:2020; ISO 19443:2018"
    )
    acceptance_threshold: Mapped[str] = mapped_column(String(16), default="Low")
    leader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    is_itns: Mapped[bool] = mapped_column(Boolean, default=False)
    safety_importance: Mapped[str] = mapped_column(String(32), default="Non applicable")
    graded_approach_rationale: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, default=date.today)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="risk_assessments")
    leader: Mapped[User | None] = relationship(foreign_keys=[leader_id])
    risks: Mapped[list["Risk"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")


class Risk(Base):
    __tablename__ = "risks"
    __table_args__ = (UniqueConstraint("assessment_id", "reference", name="uq_assessment_risk_reference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("risk_assessments.id"), index=True)
    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    lifecycle_phase: Mapped[str] = mapped_column(String(80), default="Conception")
    activity: Mapped[str] = mapped_column(String(220))
    hazard: Mapped[str] = mapped_column(String(220))
    cause: Mapped[str | None] = mapped_column(Text)
    potential_consequence: Mapped[str] = mapped_column(Text)
    existing_controls: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    initial_likelihood: Mapped[str] = mapped_column(String(1))
    initial_consequence: Mapped[int] = mapped_column(Integer)
    initial_level: Mapped[str] = mapped_column(String(16))
    acceptance_status: Mapped[str] = mapped_column(String(32), default="À statuer")
    acceptance_justification: Mapped[str | None] = mapped_column(Text)
    acceptance_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    acceptance_date: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    assessment: Mapped[RiskAssessment] = relationship(back_populates="risks")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    acceptance_user: Mapped[User | None] = relationship(foreign_keys=[acceptance_user_id])
    iterations: Mapped[list["RiskIteration"]] = relationship(
        back_populates="risk", cascade="all, delete-orphan", order_by="RiskIteration.sequence"
    )


class RiskIteration(Base):
    __tablename__ = "risk_iterations"
    __table_args__ = (UniqueConstraint("risk_id", "sequence", name="uq_risk_iteration_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    risk_id: Mapped[int] = mapped_column(ForeignKey("risks.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    treatment: Mapped[str] = mapped_column(Text)
    reduction_objective: Mapped[str | None] = mapped_column(Text)
    additional_controls: Mapped[str | None] = mapped_column(Text)
    contingency_plan: Mapped[str | None] = mapped_column(Text)
    target_likelihood: Mapped[str] = mapped_column(String(1))
    target_consequence: Mapped[int] = mapped_column(Integer)
    target_level: Mapped[str] = mapped_column(String(16))
    verification_status: Mapped[str] = mapped_column(String(32), default="À vérifier")
    verified_likelihood: Mapped[str | None] = mapped_column(String(1))
    verified_consequence: Mapped[int | None] = mapped_column(Integer)
    verified_level: Mapped[str | None] = mapped_column(String(16))
    verification_evidence: Mapped[str | None] = mapped_column(Text)
    verifier_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    risk: Mapped[Risk] = relationship(back_populates="iterations")
    verifier: Mapped[User | None] = relationship(foreign_keys=[verifier_id])
    task_links: Mapped[list["RiskIterationTask"]] = relationship(
        back_populates="iteration", cascade="all, delete-orphan"
    )


class RiskIterationTask(Base):
    __tablename__ = "risk_iteration_tasks"
    __table_args__ = (UniqueConstraint("iteration_id", "task_id", name="uq_risk_iteration_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iteration_id: Mapped[int] = mapped_column(ForeignKey("risk_iterations.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)

    iteration: Mapped[RiskIteration] = relationship(back_populates="task_links")
    task: Mapped[Task] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(24), default="api", index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), index=True)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(24), default="success")
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("user_id", "operation", "idempotency_key", name="uq_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    operation: Mapped[str] = mapped_column(String(80), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class DeleteConfirmation(Base):
    __tablename__ = "delete_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
