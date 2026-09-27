from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Plan(Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    price_inr_monthly: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    price_inr_yearly: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    razorpay_plan_id_monthly: Mapped[str | None]
    razorpay_plan_id_yearly: Mapped[str | None]
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(server_default="true")
    sort_order: Mapped[int] = mapped_column(server_default="0")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"))
    status: Mapped[str]
    razorpay_subscription_id: Mapped[str | None]
    razorpay_customer_id: Mapped[str | None]
    current_period_start: Mapped[datetime]
    current_period_end: Mapped[datetime]
    cancel_at_period_end: Mapped[bool] = mapped_column(server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
