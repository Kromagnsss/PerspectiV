from __future__ import annotations

import hashlib
import contextlib
import json
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit, snapshot
from .auth import CurrentPrincipal, Principal, require_admin, require_manager, require_scope
from .database import SessionLocal, init_db
from .models import (
    AuditLog,
    Budget,
    BudgetLine,
    DeleteConfirmation,
    IdempotencyRecord,
    PlannedTimeEntry,
    Project,
    Task,
    TaskAssignment,
    TaskDependency,
    TimeEntry,
    User,
)
from .reports import build_project_pdf
from .schemas import (
    AssignmentCreate,
    AssignmentPatch,
    BudgetCreate,
    BudgetLineCreate,
    BudgetLinePatch,
    BudgetPatch,
    DeleteConfirm,
    DependencyCreate,
    DependencyPatch,
    Page,
    ProjectCreate,
    ProjectPatch,
    TaskCreate,
    TaskPatch,
    UserCreate,
    UserPatch,
    WeeklyEntries,
)
from .services import (
    add_assignment,
    add_budget,
    add_budget_line,
    add_dependency,
    budget_df,
    create_project,
    create_task,
    create_user,
    delete_record,
    deletion_preview,
    ensure_direct_time_task,
    kpis,
    recompute_actuals,
    save_weekly_planning,
    save_weekly_timesheet,
    tasks_df,
    validate_task_tree,
    week_day_columns,
    week_start,
)
from .settings import DELETE_CONFIRMATION_TTL_SECONDS, PUBLIC_URL
from .version import __version__
from .mcp_server import mcp, mcp_app


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def model_dict(instance: Any) -> dict[str, Any]:
    return {key: _value(value) for key, value in (snapshot(instance) or {}).items()}


def page(items: list[Any], total: int, limit: int, offset: int) -> Page:
    return Page(items=[model_dict(item) for item in items], total=total, limit=limit, offset=offset)


def get_or_404(session: Session, model: type, record_id: int, label: str):
    record = session.get(model, record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"{label} introuvable.")
    return record


def _member_can_target(principal: Principal, user_id: int) -> None:
    if principal.role == "member" and principal.user_id != user_id:
        raise HTTPException(status_code=403, detail="Un membre ne peut modifier que ses propres données.")


def _weekly_dataframe(session: Session, payload: WeeklyEntries) -> pd.DataFrame:
    labels = [label for _, label in week_day_columns(week_start(payload.week_start))]
    rows = []
    for entry in payload.entries:
        ensure_direct_time_task(session, entry.task_id, payload.project_id)
        if any(hours < 0 or hours > 24 for hours in entry.hours):
            raise HTTPException(status_code=422, detail="Chaque durée journalière doit être comprise entre 0 et 24 heures.")
        row: dict[str, Any] = {"Tâche ID": entry.task_id}
        row.update(dict(zip(labels, entry.hours, strict=True)))
        rows.append(row)
    return pd.DataFrame(rows, columns=["Tâche ID", *labels])


def _idempotent_result(session: Session, user_id: int, operation: str, key: str | None) -> dict | None:
    if not key:
        return None
    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    return json.loads(record.response_json) if record else None


def _store_idempotent(session: Session, user_id: int, operation: str, key: str | None, result: dict) -> None:
    if key:
        session.add(
            IdempotencyRecord(
                user_id=user_id,
                operation=operation,
                idempotency_key=key,
                response_json=json.dumps(result, ensure_ascii=True),
            )
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="PerspectiV API",
    version=__version__,
    description="API métier locale pour PerspectiV. Aucun accès SQL générique n'est exposé.",
    lifespan=lifespan,
)


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": str(exc)})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "conflict", "detail": str(exc.orig)})


@app.get("/health", tags=["system"])
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__, "database": "ok"}


@app.get("/api/v1/profile", tags=["identity"])
def profile(principal: CurrentPrincipal) -> dict[str, Any]:
    return {
        "id": principal.user_id,
        "username": principal.username,
        "full_name": principal.full_name,
        "role": principal.role,
        "scopes": sorted(principal.scopes),
    }


@app.get("/api/v1/projects", response_model=Page, tags=["projects"])
def list_projects(
    principal: CurrentPrincipal,
    session: Session = Depends(get_session),
    q: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page:
    require_scope(principal, "read")
    stmt = select(Project)
    count_stmt = select(func.count(Project.id))
    if q:
        pattern = f"%{q.strip()}%"
        clause = Project.code.ilike(pattern) | Project.name.ilike(pattern)
        stmt, count_stmt = stmt.where(clause), count_stmt.where(clause)
    items = session.scalars(stmt.order_by(Project.code).offset(offset).limit(limit)).all()
    return page(items, session.scalar(count_stmt) or 0, limit, offset)


@app.post("/api/v1/projects", tags=["projects"], status_code=201)
def post_project(payload: ProjectCreate, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    create_project(session, **payload.model_dump())
    session.flush()
    project = session.scalar(select(Project).where(Project.code == payload.code.strip().upper()))
    record_audit(session, actor_user_id=principal.user_id, source="api", action="create", entity_type="project", entity_id=project.id, after=project)
    return model_dict(project)


@app.patch("/api/v1/projects/{project_id}", tags=["projects"])
def patch_project(project_id: int, payload: ProjectPatch, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    project = get_or_404(session, Project, project_id, "Projet")
    before = model_dict(project)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in {"budget_amount", "budget_hours"} and value is not None:
            value = Decimal(str(value))
        setattr(project, field, value)
    session.flush()
    record_audit(session, actor_user_id=principal.user_id, source="api", action="update", entity_type="project", entity_id=project.id, before=before, after=project)
    return model_dict(project)


@app.get("/api/v1/projects/{project_id}/tasks", response_model=Page, tags=["tasks"])
def list_tasks(project_id: int, principal: CurrentPrincipal, session: Session = Depends(get_session), limit: int = Query(250, ge=1, le=1000), offset: int = Query(0, ge=0)) -> Page:
    require_scope(principal, "read")
    total = session.scalar(select(func.count(Task.id)).where(Task.project_id == project_id)) or 0
    items = session.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.sort_order, Task.id).offset(offset).limit(limit)).all()
    return page(items, total, limit, offset)


@app.post("/api/v1/projects/{project_id}/tasks", tags=["tasks"], status_code=201)
def post_task(project_id: int, payload: TaskCreate, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    task = create_task(session, project_id=project_id, **payload.model_dump())
    session.flush()
    record_audit(session, actor_user_id=principal.user_id, source="api", action="create", entity_type="task", entity_id=task.id, after=task)
    return model_dict(task)


@app.patch("/api/v1/tasks/{task_id}", tags=["tasks"])
def patch_task(task_id: int, payload: TaskPatch, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    task = get_or_404(session, Task, task_id, "Tâche")
    before = model_dict(task)
    values = payload.model_dump(exclude_unset=True)
    if values.get("parent_id") == task.id:
        raise HTTPException(status_code=422, detail="Une tâche ne peut pas être son propre parent.")
    for field, value in values.items():
        if field in {"planned_hours", "planned_cost", "actual_expense_amount"} and value is not None:
            value = Decimal(str(value))
        setattr(task, field, value)
    validate_task_tree(session, task.project_id)
    recompute_actuals(session)
    session.flush()
    record_audit(session, actor_user_id=principal.user_id, source="api", action="update", entity_type="task", entity_id=task.id, before=before, after=task)
    return model_dict(task)


@app.post("/api/v1/tasks/{task_id}/close", tags=["tasks"])
def close_task(task_id: int, principal: CurrentPrincipal, session: Session = Depends(get_session), closed_on: date | None = None) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    task = get_or_404(session, Task, task_id, "Tâche")
    before = model_dict(task)
    task.status, task.progress, task.actual_end_date = "Terminé", 100, closed_on or date.today()
    record_audit(session, actor_user_id=principal.user_id, source="api", action="close", entity_type="task", entity_id=task.id, before=before, after=task)
    return model_dict(task)


@app.get("/api/v1/projects/{project_id}/budgets", response_model=Page, tags=["budgets"])
def list_budgets(project_id: int, principal: CurrentPrincipal, session: Session = Depends(get_session), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> Page:
    require_scope(principal, "read")
    total = session.scalar(select(func.count(Budget.id)).where(Budget.project_id == project_id)) or 0
    items = session.scalars(select(Budget).where(Budget.project_id == project_id).order_by(Budget.reference).offset(offset).limit(limit)).all()
    return page(items, total, limit, offset)


@app.post("/api/v1/projects/{project_id}/budgets", tags=["budgets"], status_code=201)
def post_budget(project_id: int, payload: BudgetCreate, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    budget = add_budget(session, project_id, payload.label, payload.status)
    record_audit(session, actor_user_id=principal.user_id, source="api", action="create", entity_type="budget", entity_id=budget.id, after=budget)
    return model_dict(budget)


@app.patch("/api/v1/budgets/{budget_id}", tags=["budgets"])
def patch_budget(budget_id: int, payload: BudgetPatch, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    budget = get_or_404(session, Budget, budget_id, "Budget")
    before = model_dict(budget)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(budget, field, value)
    record_audit(session, actor_user_id=principal.user_id, source="api", action="update", entity_type="budget", entity_id=budget.id, before=before, after=budget)
    return model_dict(budget)


@app.get("/api/v1/budgets/{budget_id}/lines", response_model=Page, tags=["budgets"])
def list_budget_lines(budget_id: int, principal: CurrentPrincipal, session: Session = Depends(get_session), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> Page:
    require_scope(principal, "read")
    total = session.scalar(select(func.count(BudgetLine.id)).where(BudgetLine.budget_id == budget_id)) or 0
    items = session.scalars(select(BudgetLine).where(BudgetLine.budget_id == budget_id).order_by(BudgetLine.id).offset(offset).limit(limit)).all()
    return page(items, total, limit, offset)


@app.post("/api/v1/budgets/{budget_id}/lines", tags=["budgets"], status_code=201)
def post_budget_line(budget_id: int, payload: BudgetLineCreate, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    add_budget_line(session, budget_id, payload.category, payload.label, payload.planned_amount)
    line = session.scalar(select(BudgetLine).where(BudgetLine.budget_id == budget_id).order_by(BudgetLine.id.desc()))
    record_audit(session, actor_user_id=principal.user_id, source="api", action="create", entity_type="budget_line", entity_id=line.id, after=line)
    return model_dict(line)


@app.patch("/api/v1/budget-lines/{line_id}", tags=["budgets"])
def patch_budget_line(line_id: int, payload: BudgetLinePatch, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    line = get_or_404(session, BudgetLine, line_id, "Ligne de budget")
    before = model_dict(line)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in {"planned_amount", "actual_amount"} and value is not None:
            value = Decimal(str(value))
        setattr(line, field, value)
    recompute_actuals(session)
    record_audit(session, actor_user_id=principal.user_id, source="api", action="update", entity_type="budget_line", entity_id=line.id, before=before, after=line)
    return model_dict(line)


@app.post("/api/v1/assignments", tags=["projects"], status_code=201)
def post_assignment(payload: AssignmentCreate, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    add_assignment(session, **payload.model_dump())
    assignment = session.scalar(select(TaskAssignment).where(TaskAssignment.task_id == payload.task_id, TaskAssignment.user_id == payload.user_id))
    record_audit(session, actor_user_id=principal.user_id, source="api", action="create", entity_type="assignment", entity_id=assignment.id, after=assignment)
    return model_dict(assignment)


@app.patch("/api/v1/assignments/{assignment_id}", tags=["projects"])
def patch_assignment(assignment_id: int, payload: AssignmentPatch, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    assignment = get_or_404(session, TaskAssignment, assignment_id, "Affectation")
    before = model_dict(assignment)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in {"planned_hours", "cost_rate"} and value is not None:
            value = Decimal(str(value))
        setattr(assignment, field, value)
    recompute_actuals(session)
    record_audit(session, actor_user_id=principal.user_id, source="api", action="update", entity_type="assignment", entity_id=assignment.id, before=before, after=assignment)
    return model_dict(assignment)


@app.post("/api/v1/dependencies", tags=["projects"], status_code=201)
def post_dependency(payload: DependencyCreate, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    add_dependency(session, **payload.model_dump())
    session.flush()
    dependency = session.scalar(select(TaskDependency).where(TaskDependency.predecessor_id == payload.predecessor_id, TaskDependency.successor_id == payload.successor_id))
    record_audit(session, actor_user_id=principal.user_id, source="api", action="create", entity_type="dependency", entity_id=dependency.id, after=dependency)
    return model_dict(dependency)


@app.patch("/api/v1/dependencies/{dependency_id}", tags=["projects"])
def patch_dependency(dependency_id: int, payload: DependencyPatch, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "projects:write")
    dependency = get_or_404(session, TaskDependency, dependency_id, "Dépendance")
    before = model_dict(dependency)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(dependency, field, value)
    record_audit(session, actor_user_id=principal.user_id, source="api", action="update", entity_type="dependency", entity_id=dependency.id, before=before, after=dependency)
    return model_dict(dependency)


def _save_week(payload: WeeklyEntries, principal: Principal, session: Session, kind: str, idempotency_key: str | None) -> dict:
    scope = "timesheet:write" if kind == "timesheet" else "planning:write"
    require_scope(principal, scope)
    user_id = payload.user_id or principal.user_id
    _member_can_target(principal, user_id)
    operation = f"weekly-{kind}"
    cached = _idempotent_result(session, principal.user_id, operation, idempotency_key)
    if cached is not None:
        return cached
    data = _weekly_dataframe(session, payload)
    start = week_start(payload.week_start)
    if kind == "timesheet":
        save_weekly_timesheet(session, payload.project_id, user_id, start, data)
    else:
        save_weekly_planning(session, payload.project_id, user_id, start, data)
    result = {"status": "saved", "kind": kind, "project_id": payload.project_id, "user_id": user_id, "week_start": start.isoformat()}
    _store_idempotent(session, principal.user_id, operation, idempotency_key, result)
    record_audit(session, actor_user_id=principal.user_id, source="api", action="weekly_upsert", entity_type=kind, entity_id=f"{payload.project_id}:{user_id}:{start}", after=result)
    return result


@app.put("/api/v1/timesheets/week", tags=["timesheets"])
def put_timesheet_week(payload: WeeklyEntries, principal: CurrentPrincipal, session: Session = Depends(get_session), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    return _save_week(payload, principal, session, "timesheet", idempotency_key)


@app.put("/api/v1/planning/week", tags=["planning"])
def put_planning_week(payload: WeeklyEntries, principal: CurrentPrincipal, session: Session = Depends(get_session), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    return _save_week(payload, principal, session, "planning", idempotency_key)


@app.get("/api/v1/time-entries", response_model=Page, tags=["timesheets"])
def list_time_entries(principal: CurrentPrincipal, session: Session = Depends(get_session), user_id: int | None = None, project_id: int | None = None, planned: bool = False, limit: int = Query(250, ge=1, le=1000), offset: int = Query(0, ge=0)) -> Page:
    require_scope(principal, "read")
    model = PlannedTimeEntry if planned else TimeEntry
    stmt = select(model)
    count_stmt = select(func.count(model.id))
    target_user = user_id
    if principal.role == "member":
        target_user = principal.user_id
    if target_user:
        stmt, count_stmt = stmt.where(model.user_id == target_user), count_stmt.where(model.user_id == target_user)
    if project_id:
        stmt, count_stmt = stmt.where(model.project_id == project_id), count_stmt.where(model.project_id == project_id)
    items = session.scalars(stmt.order_by(model.entry_date.desc(), model.id.desc()).offset(offset).limit(limit)).all()
    return page(items, session.scalar(count_stmt) or 0, limit, offset)


@app.get("/api/v1/users", response_model=Page, tags=["users"])
def list_users(principal: CurrentPrincipal, session: Session = Depends(get_session), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> Page:
    require_manager(principal)
    total = session.scalar(select(func.count(User.id))) or 0
    return page(session.scalars(select(User).order_by(User.full_name).offset(offset).limit(limit)).all(), total, limit, offset)


@app.post("/api/v1/users", tags=["users"], status_code=201)
def post_user(payload: UserCreate, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_admin(principal)
    password = payload.password or secrets.token_urlsafe(32)
    user = create_user(session, payload.username, payload.full_name, payload.email, payload.role, password, payload.hourly_rate)
    user.oidc_subject = payload.oidc_subject
    record_audit(session, actor_user_id=principal.user_id, source="api", action="create", entity_type="user", entity_id=user.id, after=user)
    return model_dict(user)


@app.patch("/api/v1/users/{user_id}", tags=["users"])
def patch_user(user_id: int, payload: UserPatch, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_admin(principal)
    user = get_or_404(session, User, user_id, "Utilisateur")
    before = model_dict(user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "hourly_rate" and value is not None:
            value = Decimal(str(value))
        setattr(user, field, value)
    record_audit(session, actor_user_id=principal.user_id, source="api", action="update", entity_type="user", entity_id=user.id, before=before, after=user)
    return model_dict(user)


@app.get("/api/v1/projects/{project_id}/kpis", tags=["reports"])
def project_kpis(project_id: int, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_scope(principal, "read")
    return kpis(session, project_id)


@app.post("/api/v1/projects/{project_id}/reports/pdf", tags=["reports"])
def project_report(project_id: int, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> FileResponse:
    require_scope(principal, "read")
    project = get_or_404(session, Project, project_id, "Projet")
    output = build_project_pdf(f"{project.code} - {project.name}", kpis(session, project_id), tasks_df(session, project_id), budget_df(session, project_id))
    record_audit(session, actor_user_id=principal.user_id, source="api", action="generate", entity_type="report", entity_id=project_id)
    return FileResponse(Path(output), media_type="application/pdf", filename=Path(output).name)


@app.post("/api/v1/delete/{entity}/{record_id}/preview", tags=["deletion"])
def preview_delete(entity: str, record_id: int, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "delete")
    preview = deletion_preview(session, entity, record_id)
    raw_token = secrets.token_urlsafe(32)
    session.add(
        DeleteConfirmation(
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            user_id=principal.user_id,
            entity_type=entity,
            entity_id=record_id,
            expires_at=datetime.utcnow() + timedelta(seconds=DELETE_CONFIRMATION_TTL_SECONDS),
        )
    )
    record_audit(session, actor_user_id=principal.user_id, source="api", action="delete_preview", entity_type=entity, entity_id=record_id)
    return {**preview, "confirmation_token": raw_token, "expires_in": DELETE_CONFIRMATION_TTL_SECONDS}


@app.post("/api/v1/delete/{entity}/{record_id}/confirm", tags=["deletion"])
def confirm_delete(entity: str, record_id: int, payload: DeleteConfirm, principal: CurrentPrincipal, session: Session = Depends(get_session)) -> dict:
    require_manager(principal)
    require_scope(principal, "delete")
    token_hash = hashlib.sha256(payload.confirmation_token.encode()).hexdigest()
    confirmation = session.scalar(
        select(DeleteConfirmation).where(
            DeleteConfirmation.token_hash == token_hash,
            DeleteConfirmation.user_id == principal.user_id,
            DeleteConfirmation.entity_type == entity,
            DeleteConfirmation.entity_id == record_id,
            DeleteConfirmation.used_at.is_(None),
            DeleteConfirmation.expires_at >= datetime.utcnow(),
        )
    )
    if not confirmation:
        raise HTTPException(status_code=409, detail="Confirmation absente, expirée ou déjà utilisée.")
    confirmation.used_at = datetime.utcnow()
    delete_record(session, entity, record_id)
    record_audit(session, actor_user_id=principal.user_id, source="api", action="delete", entity_type=entity, entity_id=record_id)
    return {"status": "deleted", "entity": entity, "id": record_id}


@app.get("/api/v1/audit", response_model=Page, tags=["audit"])
def list_audit(principal: CurrentPrincipal, session: Session = Depends(get_session), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> Page:
    require_admin(principal)
    total = session.scalar(select(func.count(AuditLog.id))) or 0
    items = session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)).all()
    return page(items, total, limit, offset)


@app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def oauth_resource_metadata() -> dict[str, Any]:
    from .settings import OIDC_ISSUER

    return {
        "resource": f"{PUBLIC_URL}/mcp",
        "authorization_servers": [OIDC_ISSUER] if OIDC_ISSUER else [],
        "scopes_supported": ["read", "timesheet:write", "planning:write", "projects:write", "delete", "admin"],
        "bearer_methods_supported": ["header"],
    }


app.mount("/mcp", mcp_app, name="mcp")
