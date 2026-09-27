from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.types import ProjectRoleType

PROJECT_TYPES: tuple[str, ...] = (
    "building", "road", "drain", "culvert", "bridge", "irrigation", "canal", "tank",
    "lift_irrigation", "water_supply", "sewerage", "electrical", "other",
)  # fmt: skip
PROJECT_STATUSES: tuple[str, ...] = ("draft", "in_progress", "completed", "archived")


class WorkCategory(Base):
    __tablename__ = "work_categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    project_type: Mapped[str]
    name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(server_default="true")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str]
    project_type: Mapped[str]
    work_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_categories.id"))
    client_department: Mapped[str | None]
    location: Mapped[str | None]
    district: Mapped[str | None]
    state: Mapped[str] = mapped_column(server_default="Telangana")
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    description: Mapped[str | None]
    engineer_name: Mapped[str | None]
    contractor_name: Mapped[str | None]
    reference_number: Mapped[str | None]
    project_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default="draft")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None]


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(ProjectRoleType)
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
