from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.request_id import current_request_id
from app.models import AuditLog, User


def record(
    db: Session,
    *,
    actor: User | None,
    organization_id: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID | None,
    action: str,
    project_id: uuid.UUID | None = None,
    field: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
) -> None:
    """Append an audit row in the caller's transaction (audit_logs is append-only)."""
    db.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=actor.id if actor else None,
            actor_display=actor.full_name if actor else None,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            action=action,
            field=field,
            old_value=old_value,
            new_value=new_value,
            request_id=current_request_id(),
        )
    )
