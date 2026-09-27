from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

VersionStatusType = ENUM("draft", "frozen", name="version_status", create_type=False)
ProvenanceType = ENUM(
    "user_entered", "ai_extracted", "rule_extracted", "ai_suggested", "default_accepted",
    "document_extracted", "drawing_derived", "rate_database", "calculated",
    name="provenance", create_type=False,
)  # fmt: skip


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    estimate_number: Mapped[str]
    title: Mapped[str]
    prepared_by: Mapped[str | None]
    checked_by: Mapped[str | None]
    approved_by: Mapped[str | None]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None]


class EstimateVersion(Base):
    __tablename__ = "estimate_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    estimate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"))
    version_no: Mapped[int]
    status: Mapped[str] = mapped_column(VersionStatusType, server_default="draft")
    change_note: Mapped[str | None]
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("estimate_versions.id"))
    gst_config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default='{"applicable":false}')
    rounding_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default='{"quantity_dp":3,"amount_dp":2,"grand_total":"nearest_rupee"}'
    )
    totals_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    engine_version: Mapped[str | None]
    frozen_at: Mapped[datetime | None]
    frozen_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class EstimateSection(Base):
    __tablename__ = "estimate_sections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("estimate_versions.id", ondelete="CASCADE")
    )
    line_key: Mapped[uuid.UUID]
    title: Mapped[str]
    sequence: Mapped[int]


class BoqItem(Base):
    __tablename__ = "boq_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("estimate_versions.id", ondelete="CASCADE")
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("estimate_sections.id", ondelete="CASCADE")
    )
    line_key: Mapped[uuid.UUID]
    sequence: Mapped[int]
    item_no: Mapped[str | None]
    description: Mapped[str]
    specification: Mapped[str | None]
    unit_code: Mapped[str | None]
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    quantity_raw: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    quantity_source: Mapped[str] = mapped_column(server_default="manual")
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    rate_source_type: Mapped[str | None]
    rate_item_id: Mapped[uuid.UUID | None]
    rate_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    remarks: Mapped[str | None]
    provenance: Mapped[str] = mapped_column(ProvenanceType)
    ai_generation_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Measurement(Base):
    """A detailed-estimate line (table ``estimate_items``)."""

    __tablename__ = "estimate_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("estimate_versions.id", ondelete="CASCADE")
    )
    boq_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boq_items.id", ondelete="CASCADE"))
    line_key: Mapped[uuid.UUID]
    sequence: Mapped[int]
    mode: Mapped[str] = mapped_column(server_default="dimensions")
    description: Mapped[str]
    nos: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default="1")
    length: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    breadth: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    depth_height: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    dimension_unit: Mapped[str | None]
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    quantity_raw: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    is_deduction: Mapped[bool] = mapped_column(server_default="false")
    provenance: Mapped[str] = mapped_column(ProvenanceType)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Calculation(Base):
    __tablename__ = "calculations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    estimate_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("estimate_items.id", ondelete="CASCADE"), unique=True
    )
    template_id: Mapped[str | None]
    template_version: Mapped[int | None]
    expression: Mapped[str]
    input_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    substituted: Mapped[str]
    steps: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    result_raw: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    result_unit: Mapped[str]
    engine_version: Mapped[str]
    calculated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class QuantityInput(Base):
    """A named parameter of a version (e.g. road_length) that formulas can reference."""

    __tablename__ = "quantity_inputs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("estimate_versions.id", ondelete="CASCADE")
    )
    line_key: Mapped[uuid.UUID]
    name: Mapped[str]
    label: Mapped[str]
    value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    unit_code: Mapped[str | None]
    provenance: Mapped[str] = mapped_column(ProvenanceType)
    source_text: Mapped[str | None]
    source_document_id: Mapped[uuid.UUID | None]
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None]
