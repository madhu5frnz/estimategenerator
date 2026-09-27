from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Plan, Project, Subscription

LIVE_STATUSES = ("active", "trialing", "pending", "halted")


@dataclass(frozen=True)
class PlanState:
    subscription: Subscription
    plan: Plan

    def limit(self, key: str) -> int | None:
        """None = no limit."""
        value: Any = self.plan.limits.get(key)
        return None if value is None else int(value)

    def feature(self, key: str) -> bool:
        return bool(self.plan.features.get(key, False))


def current_plan(db: Session, organization_id: uuid.UUID) -> PlanState:
    row = db.execute(
        select(Subscription, Plan)
        .join(Plan, Plan.code == Subscription.plan_code)
        .where(
            Subscription.organization_id == organization_id,
            Subscription.status.in_(LIVE_STATUSES),
        )
        .limit(1)
    ).first()
    if row is None:
        raise AppError("NO_SUBSCRIPTION", "This workspace has no active plan.", 403)
    return PlanState(subscription=row[0], plan=row[1])


def projects_used(db: Session, organization_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Project)
            .where(Project.organization_id == organization_id, Project.deleted_at.is_(None))
        )
        or 0
    )
