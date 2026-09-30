from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import jwt
import pandas as pd
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from sqlalchemy import select

from .audit import record_audit
from .auth import Principal, _decode_token, require_manager, require_scope
from .database import session_scope
from .models import (
    Budget,
    BudgetLine,
    DeleteConfirmation,
    IdempotencyRecord,
    PlannedTimeEntry,
    Project,
    Risk,
    RiskAssessment,
    RiskIteration,
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
    BudgetLinePatch,
    BudgetPatch,
    DependencyCreate,
    DependencyPatch,
    ProjectCreate,
    ProjectPatch,
    TaskCreate,
    TaskPatch,
    WeeklyEntries,
)
from .services import (
    add_budget,
    add_budget_line,
    add_assignment,
    add_dependency,
    budget_df,
    create_task,
    create_project,
    create_risk,
    create_risk_assessment,
    create_risk_iteration,
    decide_risk_acceptance,
    delete_record,
    deletion_preview,
    ensure_direct_time_task,
    kpis,
    recompute_actuals,
    risk_matrix_paths,
    risks_df,
    set_risk_assessment_status,
    save_weekly_planning,
    save_weekly_timesheet,
    tasks_df,
    validate_task_tree,
    verify_risk_iteration,
    week_day_columns,
    week_start,
)
from .settings import (
    AUTH_DISABLED,
    DELETE_CONFIRMATION_TTL_SECONDS,
    MCP_ALLOWED_HOSTS,
    MCP_ALLOWED_ORIGINS,
    OIDC_AUDIENCE,
    OIDC_ISSUER,
    PUBLIC_URL,
)
from .version import __version__


SCOPES = ["read", "timesheet:write", "planning:write", "projects:write", "delete", "admin"]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


class KeycloakTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = _decode_token(token)
        except (jwt.PyJWTError, ValueError):
            return None
        raw_scope = claims.get("scope", "")
        scopes = raw_scope.split() if isinstance(raw_scope, str) else list(raw_scope or [])
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or "chatgpt"),
            scopes=scopes,
            expires_at=claims.get("exp"),
            resource=f"{PUBLIC_URL}/mcp",
            subject=str(claims.get("sub", "")),
            claims=claims,
        )


def _server() -> MCPServer:
    kwargs: dict[str, Any] = {}
    if OIDC_ISSUER and not AUTH_DISABLED:
        kwargs = {
            "token_verifier": KeycloakTokenVerifier(),
            "auth": AuthSettings(
                issuer_url=AnyHttpUrl(OIDC_ISSUER),
                resource_server_url=AnyHttpUrl(f"{PUBLIC_URL}/mcp"),
                required_scopes=["read"],
                validate_token_resource=False,
            ),
        }
    return MCPServer(
        "PerspectiV",
        version=__version__,
        instructions=(
            "Toujours rechercher les projets et tâches avant une mutation. "
            "Ne pointer que sur une tâche directe. Prévisualiser toute suppression puis demander une confirmation explicite."
        ),
        **kwargs,
    )


mcp = _server()


def _principal() -> Principal:
    token = get_access_token()
    claims = dict(token.claims or {}) if token else {}
    subject = str(claims.get("sub") or (token.subject if token else ""))
    username = str(claims.get("preferred_username", "")).lower()
    with session_scope() as session:
        user = session.scalar(select(User).where(User.oidc_subject == subject)) if subject else None
        if not user and username:
            user = session.scalar(select(User).where(User.username == username))
        if not user and AUTH_DISABLED:
            user = session.scalar(select(User).where(User.username == "admin"))
        if not user or not user.active:
            raise ValueError("Compte PerspectiV inconnu ou inactif.")
        scopes = frozenset(token.scopes or SCOPES) if token else frozenset(SCOPES)
        return Principal(user.id, user.username, user.full_name, user.role, scopes, subject or None)


def _weekly_frame(payload: WeeklyEntries) -> pd.DataFrame:
    labels = [label for _, label in week_day_columns(week_start(payload.week_start))]
    rows = []
    for entry in payload.entries:
        if any(value < 0 or value > 24 for value in entry.hours):
            raise ValueError("Chaque durée journalière doit être comprise entre 0 et 24 heures.")
        rows.append({"Tâche ID": entry.task_id, **dict(zip(labels, entry.hours, strict=True))})
    return pd.DataFrame(rows, columns=["Tâche ID", *labels])


@mcp.tool(annotations=READ_ONLY)
def get_profile() -> dict[str, Any]:
    """Retourne le compte PerspectiV authentifié et ses permissions."""
    principal = _principal()
    return {"id": principal.user_id, "username": principal.username, "name": principal.full_name, "role": principal.role, "scopes": sorted(principal.scopes)}


@mcp.tool(annotations=READ_ONLY)
def list_projects(search: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """Recherche les projets par code ou par nom avant toute autre action."""
    principal = _principal()
    require_scope(principal, "read")
    with session_scope() as session:
        stmt = select(Project)
        if search.strip():
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(Project.code.ilike(pattern) | Project.name.ilike(pattern))
        projects = session.scalars(stmt.order_by(Project.code).limit(min(max(limit, 1), 500))).all()
        return [{"id": p.id, "code": p.code, "name": p.name, "status": p.status, "start_date": p.start_date, "end_date": p.end_date} for p in projects]


@mcp.tool(annotations=READ_ONLY)
def list_tasks(project_id: int, include_aggregate: bool = True) -> list[dict[str, Any]]:
    """Liste les tâches d'un projet et indique si chacune accepte du pointage direct."""
    principal = _principal()
    require_scope(principal, "read")
    with session_scope() as session:
        tasks = session.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.sort_order, Task.id)).all()
        parent_ids = {task.parent_id for task in tasks if task.parent_id}
        result = []
        for task in tasks:
            direct = task.id not in parent_ids
            if include_aggregate or direct:
                result.append({"id": task.id, "reference": task.reference, "title": task.title, "level": task.level, "parent_id": task.parent_id, "direct": direct, "status": task.status, "start_date": task.start_date, "due_date": task.due_date, "progress": task.progress})
        return result


@mcp.tool(annotations=READ_ONLY)
def list_budgets(project_id: int) -> list[dict[str, Any]]:
    """Liste les budgets d'un projet et leurs montants prévu, engagé et restant."""
    principal = _principal()
    require_scope(principal, "read")
    with session_scope() as session:
        budgets = session.scalars(select(Budget).where(Budget.project_id == project_id).order_by(Budget.reference)).all()
        return [
            {
                "id": item.id,
                "reference": item.reference,
                "label": item.label,
                "status": item.status,
                "planned_amount": float(item.planned_amount),
                "committed_amount": float(item.committed_amount),
                "remaining_amount": float(item.planned_amount - item.committed_amount),
            }
            for item in budgets
        ]


@mcp.tool(annotations=READ_ONLY)
def list_time_entries(project_id: int | None = None, user_id: int | None = None, planned: bool = False, limit: int = 200) -> list[dict[str, Any]]:
    """Consulte les pointages effectifs ou les planifications, avec filtres facultatifs."""
    principal = _principal()
    require_scope(principal, "read")
    model = PlannedTimeEntry if planned else TimeEntry
    with session_scope() as session:
        stmt = select(model)
        target_user = principal.user_id if principal.role == "member" else user_id
        if target_user:
            stmt = stmt.where(model.user_id == target_user)
        if project_id:
            stmt = stmt.where(model.project_id == project_id)
        entries = session.scalars(stmt.order_by(model.entry_date.desc(), model.id.desc()).limit(min(max(limit, 1), 1000))).all()
        return [
            {
                "id": item.id,
                "project_id": item.project_id,
                "task_id": item.task_id,
                "user_id": item.user_id,
                "date": item.entry_date,
                "hours": float(item.hours),
                "planned": planned,
                "note": item.note,
            }
            for item in entries
        ]


@mcp.tool(annotations=WRITE)
def create_project_record(payload: ProjectCreate) -> dict[str, Any]:
    """Crée un projet après validation de son code métier unique."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        create_project(session, **payload.model_dump())
        session.flush()
        project = session.scalar(select(Project).where(Project.code == payload.code.strip().upper()))
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="project", entity_id=project.id, after=project)
        return {"id": project.id, "code": project.code, "name": project.name, "status": project.status}


@mcp.tool(annotations=WRITE)
def update_project(project_id: int, payload: ProjectPatch) -> dict[str, Any]:
    """Met à jour uniquement les champs fournis d'un projet."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        project = session.get(Project, project_id)
        if not project:
            raise ValueError("Projet introuvable.")
        before = {column.name: getattr(project, column.name) for column in Project.__table__.columns}
        for field, value in payload.model_dump(exclude_unset=True).items():
            if field in {"budget_amount", "budget_hours"} and value is not None:
                value = Decimal(str(value))
            setattr(project, field, value)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="update", entity_type="project", entity_id=project.id, before=before, after=project)
        return {"id": project.id, "code": project.code, "name": project.name, "status": project.status}


def _save_week(payload: WeeklyEntries, kind: str) -> dict[str, Any]:
    principal = _principal()
    scope = "timesheet:write" if kind == "timesheet" else "planning:write"
    require_scope(principal, scope)
    user_id = payload.user_id or principal.user_id
    if principal.role == "member" and user_id != principal.user_id:
        raise ValueError("Un membre ne peut modifier que ses propres données.")
    start = week_start(payload.week_start)
    with session_scope() as session:
        operation = f"weekly-{kind}"
        if payload.idempotency_key:
            existing = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == principal.user_id,
                    IdempotencyRecord.operation == operation,
                    IdempotencyRecord.idempotency_key == payload.idempotency_key,
                )
            )
            if existing:
                return json.loads(existing.response_json)
        for entry in payload.entries:
            ensure_direct_time_task(session, entry.task_id, payload.project_id)
        frame = _weekly_frame(payload)
        if kind == "timesheet":
            save_weekly_timesheet(session, payload.project_id, user_id, start, frame)
        else:
            save_weekly_planning(session, payload.project_id, user_id, start, frame)
        result = {"status": "saved", "kind": kind, "project_id": payload.project_id, "user_id": user_id, "week_start": start.isoformat()}
        if payload.idempotency_key:
            session.add(
                IdempotencyRecord(
                    user_id=principal.user_id,
                    operation=operation,
                    idempotency_key=payload.idempotency_key,
                    response_json=json.dumps(result, ensure_ascii=True),
                )
            )
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="weekly_upsert", entity_type=kind, entity_id=f"{payload.project_id}:{user_id}:{start}", after=result)
        return result


@mcp.tool(annotations=WRITE)
def save_timesheet_week(payload: WeeklyEntries) -> dict[str, Any]:
    """Remplace atomiquement les heures d'une semaine sur des tâches directes."""
    return _save_week(payload, "timesheet")


@mcp.tool(annotations=WRITE)
def save_planning_week(payload: WeeklyEntries) -> dict[str, Any]:
    """Remplace atomiquement la planification d'une semaine sur des tâches directes."""
    return _save_week(payload, "planning")


@mcp.tool(annotations=WRITE)
def create_project_task(project_id: int, payload: TaskCreate) -> dict[str, Any]:
    """Crée une tâche dans un projet après identification certaine du projet."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        task = create_task(session, project_id=project_id, **payload.model_dump())
        session.flush()
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="task", entity_id=task.id, after=task)
        return {"id": task.id, "reference": task.reference, "title": task.title}


@mcp.tool(annotations=WRITE)
def update_task(task_id: int, payload: TaskPatch) -> dict[str, Any]:
    """Met à jour les champs fournis d'une tâche existante."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            raise ValueError("Tâche introuvable.")
        before = {column.name: getattr(task, column.name) for column in Task.__table__.columns}
        values = payload.model_dump(exclude_unset=True)
        if values.get("parent_id") == task.id:
            raise ValueError("Une tâche ne peut pas être son propre parent.")
        for field, value in values.items():
            setattr(task, field, value)
        validate_task_tree(session, task.project_id)
        recompute_actuals(session)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="update", entity_type="task", entity_id=task.id, before=before, after=task)
        return {"id": task.id, "reference": task.reference, "title": task.title, "status": task.status, "progress": task.progress}


@mcp.tool(annotations=WRITE)
def close_task(task_id: int, closed_on: date | None = None) -> dict[str, Any]:
    """Clôture une tâche à 100 % avec une date effective explicite ou la date du jour."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            raise ValueError("Tâche introuvable.")
        before = {column.name: getattr(task, column.name) for column in Task.__table__.columns}
        task.status, task.progress, task.actual_end_date = "Terminé", 100, closed_on or date.today()
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="close", entity_type="task", entity_id=task.id, before=before, after=task)
        return {"id": task.id, "reference": task.reference, "status": task.status, "actual_end_date": task.actual_end_date}


@mcp.tool(annotations=WRITE)
def create_budget(project_id: int, label: str, status: str = "Actif") -> dict[str, Any]:
    """Crée un budget rattaché à un projet."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        budget = add_budget(session, project_id, label, status)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="budget", entity_id=budget.id, after=budget)
        return {"id": budget.id, "reference": budget.reference, "label": budget.label}


@mcp.tool(annotations=WRITE)
def update_budget(budget_id: int, payload: BudgetPatch) -> dict[str, Any]:
    """Met à jour le libellé ou le statut d'un budget; les montants restent calculés."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        budget = session.get(Budget, budget_id)
        if not budget:
            raise ValueError("Budget introuvable.")
        before = {column.name: getattr(budget, column.name) for column in Budget.__table__.columns}
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(budget, field, value)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="update", entity_type="budget", entity_id=budget.id, before=before, after=budget)
        return {"id": budget.id, "reference": budget.reference, "label": budget.label, "status": budget.status}


@mcp.tool(annotations=WRITE)
def create_budget_line(budget_id: int, category: str, label: str, planned_amount: float = 0) -> dict[str, Any]:
    """Ajoute une ligne de frais prévue à un budget."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        add_budget_line(session, budget_id, category, label, planned_amount)
        line = session.scalar(select(BudgetLine).where(BudgetLine.budget_id == budget_id).order_by(BudgetLine.id.desc()))
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="budget_line", entity_id=line.id, after=line)
        return {"id": line.id, "budget_id": line.budget_id, "label": line.label, "planned_amount": float(line.planned_amount)}


@mcp.tool(annotations=WRITE)
def update_budget_line(line_id: int, payload: BudgetLinePatch) -> dict[str, Any]:
    """Met à jour une ligne de frais puis recalcule les agrégats du projet et du budget."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        line = session.get(BudgetLine, line_id)
        if not line:
            raise ValueError("Ligne de budget introuvable.")
        before = {column.name: getattr(line, column.name) for column in BudgetLine.__table__.columns}
        for field, value in payload.model_dump(exclude_unset=True).items():
            if field in {"planned_amount", "actual_amount"} and value is not None:
                value = Decimal(str(value))
            setattr(line, field, value)
        recompute_actuals(session)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="update", entity_type="budget_line", entity_id=line.id, before=before, after=line)
        return {"id": line.id, "budget_id": line.budget_id, "label": line.label, "actual_amount": float(line.actual_amount)}


@mcp.tool(annotations=WRITE)
def create_assignment(payload: AssignmentCreate) -> dict[str, Any]:
    """Affecte un utilisateur à une tâche avec sa charge et son taux de coût."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        add_assignment(session, **payload.model_dump())
        assignment = session.scalar(select(TaskAssignment).where(TaskAssignment.task_id == payload.task_id, TaskAssignment.user_id == payload.user_id))
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="assignment", entity_id=assignment.id, after=assignment)
        return {"id": assignment.id, "task_id": assignment.task_id, "user_id": assignment.user_id}


@mcp.tool(annotations=WRITE)
def update_assignment(assignment_id: int, payload: AssignmentPatch) -> dict[str, Any]:
    """Met à jour la charge, le rôle ou le taux d'une affectation existante."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        assignment = session.get(TaskAssignment, assignment_id)
        if not assignment:
            raise ValueError("Affectation introuvable.")
        before = {column.name: getattr(assignment, column.name) for column in TaskAssignment.__table__.columns}
        for field, value in payload.model_dump(exclude_unset=True).items():
            if field in {"planned_hours", "cost_rate"} and value is not None:
                value = Decimal(str(value))
            setattr(assignment, field, value)
        recompute_actuals(session)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="update", entity_type="assignment", entity_id=assignment.id, before=before, after=assignment)
        return {"id": assignment.id, "task_id": assignment.task_id, "user_id": assignment.user_id}


@mcp.tool(annotations=WRITE)
def create_dependency(payload: DependencyCreate) -> dict[str, Any]:
    """Crée une dépendance explicite entre deux tâches."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        add_dependency(session, **payload.model_dump())
        session.flush()
        dependency = session.scalar(select(TaskDependency).where(TaskDependency.predecessor_id == payload.predecessor_id, TaskDependency.successor_id == payload.successor_id))
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="dependency", entity_id=dependency.id, after=dependency)
        return {"id": dependency.id, "predecessor_id": dependency.predecessor_id, "successor_id": dependency.successor_id}


@mcp.tool(annotations=WRITE)
def update_dependency(dependency_id: int, payload: DependencyPatch) -> dict[str, Any]:
    """Met à jour le type ou le décalage d'une dépendance."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        dependency = session.get(TaskDependency, dependency_id)
        if not dependency:
            raise ValueError("Dépendance introuvable.")
        before = {column.name: getattr(dependency, column.name) for column in TaskDependency.__table__.columns}
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(dependency, field, value)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="update", entity_type="dependency", entity_id=dependency.id, before=before, after=dependency)
        return {"id": dependency.id, "link_type": dependency.link_type, "lag_days": dependency.lag_days}


@mcp.tool(annotations=READ_ONLY)
def list_project_risks(project_id: int) -> dict[str, Any]:
    """Liste les analyses, risques, cotations courantes et chemins de réduction d'un projet."""
    principal = _principal()
    require_scope(principal, "read")
    with session_scope() as session:
        assessments = session.scalars(select(RiskAssessment).where(RiskAssessment.project_id == project_id).order_by(RiskAssessment.reference)).all()
        assessment_ids = [item.id for item in assessments]
        risks = session.scalars(select(Risk).where(Risk.assessment_id.in_(assessment_ids)).order_by(Risk.reference)).all() if assessment_ids else []
        return {
            "analyses": [{"id": item.id, "reference": item.reference, "title": item.title, "status": item.status, "threshold": item.acceptance_threshold} for item in assessments],
            "risks": [{"id": item.id, "assessment_id": item.assessment_id, "reference": item.reference, "hazard": item.hazard, "initial_level": item.initial_level, "acceptance": item.acceptance_status} for item in risks],
            "matrix_paths": risk_matrix_paths(session, assessment_ids),
        }


@mcp.tool(annotations=WRITE)
def create_risk_analysis(project_id: int, title: str, leader_id: int | None = None, acceptance_threshold: str = "Low", scope: str = "") -> dict[str, Any]:
    """Crée une analyse de risques produit rattachée à un projet."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        item = create_risk_assessment(session, project_id, title, leader_id, scope=scope, acceptance_threshold=acceptance_threshold)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="risk_assessment", entity_id=item.id, after=item)
        return {"id": item.id, "reference": item.reference, "title": item.title, "status": item.status}


@mcp.tool(annotations=WRITE)
def create_project_risk(assessment_id: int, activity: str, hazard: str, potential_consequence: str, initial_likelihood: str, initial_consequence: int, lifecycle_phase: str = "Conception", cause: str = "", existing_controls: str = "", owner_id: int | None = None) -> dict[str, Any]:
    """Ajoute un risque et calcule sa cotation initiale avec la matrice PerspectiV."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        item = create_risk(session, assessment_id, lifecycle_phase, activity, hazard, cause, potential_consequence, existing_controls, owner_id, initial_likelihood, initial_consequence)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="risk", entity_id=item.id, after=item)
        return {"id": item.id, "reference": item.reference, "initial_level": item.initial_level}


@mcp.tool(annotations=WRITE)
def add_risk_reduction_iteration(risk_id: int, treatment: str, target_likelihood: str, target_consequence: int, task_ids: list[int] | None = None, reduction_objective: str = "", additional_controls: str = "", contingency_plan: str = "") -> dict[str, Any]:
    """Ajoute une itération de réduction et lie les actions aux tâches du même projet."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        item = create_risk_iteration(session, risk_id, treatment, reduction_objective, additional_controls, contingency_plan, target_likelihood, target_consequence, task_ids)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="create", entity_type="risk_iteration", entity_id=item.id, after=item)
        return {"id": item.id, "sequence": item.sequence, "target_level": item.target_level, "verification_status": item.verification_status}


@mcp.tool(annotations=WRITE)
def verify_risk_reduction(iteration_id: int, likelihood: str, consequence: int, evidence: str) -> dict[str, Any]:
    """Vérifie une itération; la cotation résiduelle devient alors la cotation officielle."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        item = verify_risk_iteration(session, iteration_id, likelihood, consequence, evidence, principal.user_id)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="verify", entity_type="risk_iteration", entity_id=item.id, after=item)
        return {"id": item.id, "verified_level": item.verified_level, "verification_status": item.verification_status}


@mcp.tool(annotations=WRITE)
def decide_risk(risk_id: int, decision: str, justification: str) -> dict[str, Any]:
    """Enregistre la décision humaine d'acceptation ou de refus d'un risque."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        item = decide_risk_acceptance(session, risk_id, decision, justification, principal.user_id)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="acceptance", entity_type="risk", entity_id=item.id, after=item)
        return {"id": item.id, "reference": item.reference, "acceptance": item.acceptance_status}


@mcp.tool(annotations=WRITE)
def change_risk_analysis_status(assessment_id: int, status: str) -> dict[str, Any]:
    """Ouvre ou clôture une analyse après contrôle de toutes les décisions et vérifications."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "projects:write")
    with session_scope() as session:
        item = set_risk_assessment_status(session, assessment_id, status)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="status", entity_type="risk_assessment", entity_id=item.id, after=item)
        return {"id": item.id, "reference": item.reference, "status": item.status}


@mcp.tool(annotations=DESTRUCTIVE)
def preview_deletion(entity: str, record_id: int) -> dict[str, Any]:
    """Prévisualise tous les impacts d'une suppression et produit un jeton temporaire à confirmer."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "delete")
    with session_scope() as session:
        preview = deletion_preview(session, entity, record_id)
        raw_token = secrets.token_urlsafe(32)
        session.add(DeleteConfirmation(token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), user_id=principal.user_id, entity_type=entity, entity_id=record_id, expires_at=datetime.utcnow() + timedelta(seconds=DELETE_CONFIRMATION_TTL_SECONDS)))
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="delete_preview", entity_type=entity, entity_id=record_id)
        return {**preview, "confirmation_token": raw_token, "expires_in": DELETE_CONFIRMATION_TTL_SECONDS}


@mcp.tool(annotations=DESTRUCTIVE)
def confirm_deletion(entity: str, record_id: int, confirmation_token: str) -> dict[str, Any]:
    """Supprime après confirmation explicite avec le jeton provenant de preview_deletion."""
    principal = _principal()
    require_manager(principal)
    require_scope(principal, "delete")
    token_hash = hashlib.sha256(confirmation_token.encode()).hexdigest()
    with session_scope() as session:
        confirmation = session.scalar(select(DeleteConfirmation).where(DeleteConfirmation.token_hash == token_hash, DeleteConfirmation.user_id == principal.user_id, DeleteConfirmation.entity_type == entity, DeleteConfirmation.entity_id == record_id, DeleteConfirmation.used_at.is_(None), DeleteConfirmation.expires_at >= datetime.utcnow()))
        if not confirmation:
            raise ValueError("Confirmation absente, expirée ou déjà utilisée.")
        confirmation.used_at = datetime.utcnow()
        delete_record(session, entity, record_id)
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="delete", entity_type=entity, entity_id=record_id)
        return {"status": "deleted", "entity": entity, "id": record_id}


@mcp.tool(annotations=READ_ONLY)
def generate_project_report(project_id: int) -> dict[str, Any]:
    """Génère un rapport PDF du projet et retourne son chemin serveur."""
    principal = _principal()
    require_scope(principal, "read")
    with session_scope() as session:
        project = session.get(Project, project_id)
        if not project:
            raise ValueError("Projet introuvable.")
        assessment_ids = session.scalars(select(RiskAssessment.id).where(RiskAssessment.project_id == project_id)).all()
        output = build_project_pdf(
            f"{project.code} - {project.name}",
            kpis(session, project_id),
            tasks_df(session, project_id),
            budget_df(session, project_id),
            risks_df(session, assessment_ids),
        )
        record_audit(session, actor_user_id=principal.user_id, source="mcp", action="generate", entity_type="report", entity_id=project_id)
        return {"project_id": project_id, "filename": output.name, "download_url": f"{PUBLIC_URL}/api/v1/projects/{project_id}/reports/pdf"}


transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=MCP_ALLOWED_HOSTS,
    allowed_origins=MCP_ALLOWED_ORIGINS,
)

mcp_app = mcp.streamable_http_app(
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
    transport_security=transport_security,
    host="0.0.0.0",
)
