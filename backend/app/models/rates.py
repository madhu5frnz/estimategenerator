from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

VerificationType = ENUM(
    "demo", "user_entered", "imported_unverified", "verified_official",
    name="rate_verification", create_type=False,
)  # fmt: skip


class RateSource(Base):
    __tablename__ = "rate_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    state: Mapped[str]
    department: Mapped[str]
    sor_name: Mapped[str]
    year: Mapped[str]
    effective_from: Mapped[date]
    effective_to: Mapped[date | None]
    verification_status: Mapped[str] = mapped_column(VerificationType)
    source_reference: Mapped[str | None]
    source_document_id: Mapped[uuid.UUID | None]
    notes: Mapped[str | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RateItem(Base):
    __tablename__ = "rate_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    rate_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rate_sources.id", ondelete="CASCADE")
    )
    import_batch_id: Mapped[uuid.UUID | None]
    item_code: Mapped[str]
    description: Mapped[str]
    specification: Mapped[str | None]
    unit_code: Mapped[str]
    basic_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    gst_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    total_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
