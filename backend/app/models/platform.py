from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[uuid.UUID | None]
    actor_user_id: Mapped[uuid.UUID | None]
    actor_display: Mapped[str | None]
    entity_type: Mapped[str]
    entity_id: Mapped[uuid.UUID | None]
    project_id: Mapped[uuid.UUID | None]
    version_id: Mapped[uuid.UUID | None]
    action: Mapped[str]
    field: Mapped[str | None]
    old_value: Mapped[Any | None] = mapped_column(JSONB)
    new_value: Mapped[Any | None] = mapped_column(JSONB)
    request_id: Mapped[str | None]
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Setting(Base):
    __tablename__ = "settings"
    __mapper_args__ = {"primary_key": ["scope", "scope_id", "key"]}  # noqa: RUF012

    scope: Mapped[str]
    scope_id: Mapped[uuid.UUID | None]
    key: Mapped[str]
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
