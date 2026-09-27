from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.api.deps import DB, Auth
from app.api.envelope import Envelope, Meta, ok
from app.core.request_id import current_request_id
from app.models import Project, WorkCategory
from app.models.project import PROJECT_TYPES
from app.services import projects as service

router = APIRouter(tags=["projects"])

ProjectType = Literal[
    "building", "road", "drain", "culvert", "bridge", "irrigation", "canal", "tank",
    "lift_irrigation", "water_supply", "sewerage", "electrical", "other",
]  # fmt: skip
Status = Literal["draft", "in_progress", "completed", "archived"]
TYPE_LABELS = {
    "building": "Building", "road": "Road", "drain": "Drain", "culvert": "Culvert",
    "bridge": "Bridge", "irrigation": "Irrigation", "canal": "Canal", "tank": "Tank",
    "lift_irrigation": "Lift Irrigation", "water_supply": "Water Supply",
    "sewerage": "Sewerage", "electrical": "Electrical", "other": "Other",
}  # fmt: skip
assert set(TYPE_LABELS) == set(PROJECT_TYPES)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


class _ProjectFields(BaseModel):
    client_department: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    district: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    engineer_name: str | None = Field(default=None, max_length=120)
    contractor_name: str | None = Field(default=None, max_length=120)
    reference_number: str | None = Field(default=None, max_length=100)
    project_date: date | None = None
    work_category_id: uuid.UUID | None = None
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)

    @field_validator(
        "client_department", "location", "district", "description", "engineer_name",
        "contractor_name", "reference_number", mode="before",
    )  # fmt: skip
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ProjectCreate(_ProjectFields):
    name: str = Field(min_length=1, max_length=200)
    project_type: ProjectType
    state: str = Field(default="Telangana", min_length=1, max_length=60)

    @field_validator("name", "state")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required.")
        return value


class ProjectPatch(_ProjectFields):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    project_type: ProjectType | None = None
    state: str | None = Field(default=None, min_length=1, max_length=60)
    status: Status | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    project_type: str
    project_type_label: str
    work_category_id: uuid.UUID | None
    client_department: str | None
    location: str | None
    district: str | None
    state: str
    estimated_value: str | None
    description: str | None
    engineer_name: str | None
    contractor_name: str | None
    reference_number: str | None
    project_date: date | None
    status: str
    my_role: str
    created_at: datetime
    updated_at: datetime


class ProjectPage(BaseModel):
    success: bool = True
    data: list[ProjectOut]
    meta: dict[str, Any]


class Option(BaseModel):
    code: str
    label: str


class CategoryOut(BaseModel):
    id: uuid.UUID
    project_type: str
    name: str


def project_out(p: Project, role: str) -> ProjectOut:
    return ProjectOut(
        id=p.id, name=p.name, project_type=p.project_type,
        project_type_label=TYPE_LABELS.get(p.project_type, p.project_type),
        work_category_id=p.work_category_id, client_department=p.client_department,
        location=p.location, district=p.district, state=p.state,
        estimated_value=_money(p.estimated_value), description=p.description,
        engineer_name=p.engineer_name, contractor_name=p.contractor_name,
        reference_number=p.reference_number, project_date=p.project_date, status=p.status,
        my_role=role, created_at=p.created_at, updated_at=p.updated_at,
    )  # fmt: skip


@router.get("/project-types", response_model=Envelope[list[Option]])
def project_types() -> Envelope[list[Option]]:
    return ok([Option(code=c, label=TYPE_LABELS[c]) for c in PROJECT_TYPES])


@router.get("/work-categories", response_model=Envelope[list[CategoryOut]])
def work_categories(
    auth: Auth, db: DB, project_type: ProjectType | None = None
) -> Envelope[list[CategoryOut]]:
    query = select(WorkCategory).where(
        WorkCategory.is_active.is_(True),
        or_(
            WorkCategory.organization_id.is_(None),
            WorkCategory.organization_id == auth.organization_id,
        ),
    )
    if project_type:
        query = query.where(WorkCategory.project_type == project_type)
    rows = db.scalars(query.order_by(WorkCategory.project_type, WorkCategory.name)).all()
    return ok([CategoryOut(id=r.id, project_type=r.project_type, name=r.name) for r in rows])


@router.get("/projects", response_model=ProjectPage)
def list_projects(
    auth: Auth,
    db: DB,
    q: str | None = Query(default=None, max_length=100),
    status: Status | None = None,
    project_type: ProjectType | None = Query(default=None, alias="type"),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=25, ge=1, le=100),
) -> ProjectPage:
    rows, total = service.search(
        db, auth, q=q, status=status, project_type=project_type, page=page, page_size=page_size
    )
    roles = service.roles_for(db, auth, [p.id for p in rows])
    return ProjectPage(
        data=[project_out(p, roles.get(p.id, "viewer")) for p in rows],
        meta={
            **Meta(request_id=current_request_id()).model_dump(),
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.post("/projects", response_model=Envelope[ProjectOut], status_code=201)
def create_project(body: ProjectCreate, auth: Auth, db: DB) -> Envelope[ProjectOut]:
    access = service.create(db, auth, body.model_dump())
    return ok(project_out(access.project, access.role))


@router.get("/projects/{project_id}", response_model=Envelope[ProjectOut])
def get_project(project_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[ProjectOut]:
    access = service.get_access(db, auth, project_id)
    return ok(project_out(access.project, access.role))


@router.patch("/projects/{project_id}", response_model=Envelope[ProjectOut])
def patch_project(
    project_id: uuid.UUID, body: ProjectPatch, auth: Auth, db: DB
) -> Envelope[ProjectOut]:
    changes = {f: getattr(body, f) for f in body.model_fields_set}
    for required in ("name", "project_type", "state", "status"):
        if required in changes and changes[required] is None:
            changes.pop(required)
    access = service.update(db, auth, project_id, changes)
    return ok(project_out(access.project, access.role))


@router.delete("/projects/{project_id}", response_model=Envelope[dict[str, bool]])
def delete_project(project_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[dict[str, bool]]:
    service.delete(db, auth, project_id)
    return ok({"deleted": True})
