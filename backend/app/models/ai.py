from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

JobStatusType = ENUM(
    "queued", "running", "needs_input", "succeeded", "failed", "cancelled",
    name="job_status", create_type=False,
)  # fmt: skip


class AiGeneration(Base):
    """One AI (or rules) interpretation: the cost ledger and the audit of what was proposed."""

    __tablename__ = "ai_generations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    purpose: Mapped[str]
    prompt_id: Mapped[str]
    prompt_version: Mapped[int]
    model: Mapped[str]
    input_hash: Mapped[str]
    input_text: Mapped[str | None]
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validated_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_errors: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(JobStatusType)
    input_tokens: Mapped[int] = mapped_column(server_default="0")
    output_tokens: Mapped[int] = mapped_column(server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    latency_ms: Mapped[int | None]
    served_from_cache: Mapped[bool] = mapped_column(server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UsageCounter(Base):
    __tablename__ = "usage_counters"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    metric: Mapped[str] = mapped_column(primary_key=True)
    period_start: Mapped[date] = mapped_column(primary_key=True)
    used: Mapped[int] = mapped_column(server_default="0")
