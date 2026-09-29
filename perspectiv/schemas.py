from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class ProjectCreate(BaseModel):
    code: str = Field(min_length=2, max_length=24)
    name: str = Field(min_length=1, max_length=180)
    owner_id: int | None = None
    category: str = "Interne"
    priority: str = "Normale"
    status: str = "En cours"
    start_date: date | None = None
    end_date: date | None = None
    budget_amount: float = Field(default=0, ge=0)
    budget_hours: float = Field(default=0, ge=0)
    description: str = ""


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    owner_id: int | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    budget_amount: float | None = Field(default=None, ge=0)
    budget_hours: float | None = Field(default=None, ge=0)
    description: str | None = None


class TaskCreate(BaseModel):
    budget_id: int | None = None
    title: str = Field(min_length=1, max_length=220)
    level: int = Field(default=1, ge=1, le=4)
    parent_id: int | None = None
    status: str = "Non commencé"
    priority: str = "Normale"
    start_date: date | None = None
    due_date: date | None = None
    planned_hours: float = Field(default=0, ge=0)
    planned_cost: float = Field(default=0, ge=0)
    actual_expense_amount: float = Field(default=0, ge=0)
    progress: int = Field(default=0, ge=0, le=100)
    assigned_user_id: int | None = None
    starcost: bool = False
    description: str = ""


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    budget_id: int | None = None
    level: int | None = Field(default=None, ge=1, le=4)
    parent_id: int | None = None
    status: str | None = None
    priority: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    actual_end_date: date | None = None
    planned_hours: float | None = Field(default=None, ge=0)
    planned_cost: float | None = Field(default=None, ge=0)
    actual_expense_amount: float | None = Field(default=None, ge=0)
    progress: int | None = Field(default=None, ge=0, le=100)
    starcost: bool | None = None
    description: str | None = None


class BudgetCreate(BaseModel):
    label: str = Field(min_length=1, max_length=180)
    status: str = "Actif"


class BudgetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, min_length=1, max_length=180)
    status: str | None = None


class BudgetLineCreate(BaseModel):
    category: str = "Frais"
    label: str = Field(min_length=1, max_length=180)
    planned_amount: float = Field(default=0, ge=0)


class BudgetLinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = None
    label: str | None = Field(default=None, min_length=1, max_length=180)
    planned_amount: float | None = Field(default=None, ge=0)
    actual_amount: float | None = Field(default=None, ge=0)


class AssignmentCreate(BaseModel):
    task_id: int
    user_id: int
    role: str = "Affecté"
    planned_hours: float = Field(default=0, ge=0)
    cost_rate: float = Field(default=0, ge=0)


class AssignmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str | None = None
    planned_hours: float | None = Field(default=None, ge=0)
    cost_rate: float | None = Field(default=None, ge=0)


class DependencyCreate(BaseModel):
    predecessor_id: int
    successor_id: int
    link_type: str = "Fin-Début"
    lag_days: int = 0


class DependencyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link_type: str | None = None
    lag_days: int | None = None


class DayHours(BaseModel):
    task_id: int
    hours: list[float] = Field(min_length=7, max_length=7)


class WeeklyEntries(BaseModel):
    project_id: int
    user_id: int | None = None
    week_start: date
    entries: list[DayHours]
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    full_name: str = Field(min_length=1, max_length=160)
    email: str = ""
    role: Literal["member", "manager", "admin"] = "member"
    password: str = Field(default="", min_length=0, max_length=200)
    hourly_rate: float = Field(default=0, ge=0)
    oidc_subject: str | None = None


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = None
    role: Literal["member", "manager", "admin"] | None = None
    hourly_rate: float | None = Field(default=None, ge=0)
    active: bool | None = None
    oidc_subject: str | None = None


class DeleteConfirm(BaseModel):
    confirmation_token: str = Field(min_length=20)
