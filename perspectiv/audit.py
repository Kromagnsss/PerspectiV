from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from .models import AuditLog


def _json_default(value: Any) -> str | float:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def snapshot(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    state = inspect(value)
    return {column.key: getattr(value, column.key) for column in state.mapper.column_attrs}


def record_audit(
    session: Session,
    *,
    actor_user_id: int | None,
    source: str,
    action: str,
    entity_type: str,
    entity_id: int | str | None,
    before: Any = None,
    after: Any = None,
    result: str = "success",
    request_id: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            source=source[:24],
            action=action[:80],
            entity_type=entity_type[:80],
            entity_id=str(entity_id) if entity_id is not None else None,
            before_json=json.dumps(snapshot(before), default=_json_default, ensure_ascii=True) if before is not None else None,
            after_json=json.dumps(snapshot(after), default=_json_default, ensure_ascii=True) if after is not None else None,
            result=result[:24],
            request_id=request_id,
        )
    )
