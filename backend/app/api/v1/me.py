from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import DB, Auth
from app.api.envelope import Envelope, ok
from app.core.errors import AppError
from app.models import Organization, OrganizationMember, User
from app.services import audit
from app.services.ai_extraction import ai_used
from app.services.plans import current_plan, projects_used

router = APIRouter(tags=["account"])

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    email_verified: bool
    locale: str
    has_password: bool


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    is_personal: bool
    gstin: str | None
    state_code: str | None
    address: str | None


class SubscriptionOut(BaseModel):
    plan_code: str
    plan_name: str
    status: str
    current_period_end: datetime
    limits: dict[str, Any]
    features: dict[str, Any]


class UsageOut(BaseModel):
    projects: int
    ai_generations: int


class MeOut(BaseModel):
    user: UserOut
    organization: OrganizationOut
    subscription: SubscriptionOut
    usage: UsageOut


def _org_out(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> OrganizationOut:
    org = db.get(Organization, org_id)
    member = db.get(OrganizationMember, (org_id, user_id))
    if org is None or member is None:
        raise AppError("NOT_FOUND", "Workspace not found.", 404)
    return OrganizationOut(
        id=org.id, name=org.name, role=member.role, is_personal=org.is_personal,
        gstin=org.gstin, state_code=org.state_code, address=org.address,
    )  # fmt: skip


def build_me(db: Session, user: User, org_id: uuid.UUID) -> MeOut:
    state = current_plan(db, org_id)
    return MeOut(
        user=UserOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            email_verified=user.email_verified_at is not None,
            locale=user.locale,
            has_password=user.password_hash is not None,
        ),
        organization=_org_out(db, org_id, user.id),
        subscription=SubscriptionOut(
            plan_code=state.plan.code,
            plan_name=state.plan.name,
            status=state.subscription.status,
            current_period_end=state.subscription.current_period_end,
            limits=state.plan.limits,
            features=state.plan.features,
        ),
        # Only metered (LLM) generations count; the rules-based parser is free.
        usage=UsageOut(projects=projects_used(db, org_id), ai_generations=ai_used(db, org_id)),
    )


class MePatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        cleaned = re.sub(r"[\s-]", "", value)
        if not re.fullmatch(r"\+?\d{10,15}", cleaned):
            raise ValueError("Enter a valid phone number, e.g. +91 98765 43210.")
        return cleaned


class OrganizationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    gstin: str | None = Field(default=None, max_length=15)
    state_code: str | None = Field(default=None, max_length=4)
    address: str | None = Field(default=None, max_length=500)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        value = value.strip().upper()
        if not GSTIN_RE.fullmatch(value):
            raise ValueError("GSTIN must be 15 characters, e.g. 36AABCU9603R1ZM.")
        return value


@router.get("/me", response_model=Envelope[MeOut])
def get_me(auth: Auth, db: DB) -> Envelope[MeOut]:
    return ok(build_me(db, auth.user, auth.organization_id))


@router.patch("/me", response_model=Envelope[MeOut])
def patch_me(body: MePatch, auth: Auth, db: DB) -> Envelope[MeOut]:
    user = db.merge(auth.user)
    for field in body.model_fields_set:
        value = getattr(body, field)
        if field == "full_name":
            value = value.strip() if value else value
            if not value:
                raise AppError("VALIDATION_ERROR", "Please enter your name.")
        setattr(user, field, value)
    db.commit()
    return ok(build_me(db, user, auth.organization_id))


@router.get("/organizations/{org_id}", response_model=Envelope[OrganizationOut])
def get_organization(org_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[OrganizationOut]:
    if org_id != auth.organization_id:
        raise AppError("NOT_FOUND", "Workspace not found.", 404)
    return ok(_org_out(db, org_id, auth.user.id))


@router.patch("/organizations/{org_id}", response_model=Envelope[OrganizationOut])
def patch_organization(
    org_id: uuid.UUID, body: OrganizationPatch, auth: Auth, db: DB
) -> Envelope[OrganizationOut]:
    if org_id != auth.organization_id:
        raise AppError("NOT_FOUND", "Workspace not found.", 404)
    if not auth.is_org_admin:
        raise AppError("FORBIDDEN", "Only workspace owners and admins can change this.", 403)
    org = db.get(Organization, org_id)
    assert org is not None
    changes: dict[str, Any] = {}
    for field in body.model_fields_set:
        new = getattr(body, field)
        if field == "name" and not (new or "").strip():
            raise AppError("VALIDATION_ERROR", "Workspace name cannot be empty.")
        old = getattr(org, field)
        if old != new:
            changes[field] = (old, new)
            setattr(org, field, new)
    for field, (old, new) in changes.items():
        audit.record(
            db, actor=auth.user, organization_id=org.id, entity_type="organization",
            entity_id=org.id, action="update", field=field, old_value=old, new_value=new,
        )  # fmt: skip
    db.commit()
    return ok(_org_out(db, org_id, auth.user.id))
