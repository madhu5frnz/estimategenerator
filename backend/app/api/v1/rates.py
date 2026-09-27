"""Rate list: sources (SOR books) and their items, search, and workspace-owned CRUD."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import DB, Auth
from app.api.envelope import Envelope, ok
from app.domain.money import format_inr
from app.domain.units import default_registry
from app.models import RateItem, RateSource
from app.services import rates as service
from app.services.context import AuthContext

router = APIRouter(tags=["rates"])


class RateSourceOut(BaseModel):
    id: uuid.UUID
    state: str
    department: str
    sor_name: str
    year: str
    effective_from: date
    effective_to: date | None
    verification_status: str
    is_demo: bool
    is_expired: bool
    source_reference: str | None
    notes: str | None
    item_count: int
    owned: bool  # belongs to this workspace (platform sources are read-only)
    can_edit: bool
    created_at: datetime


class RateItemOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_label: str
    verification_status: str
    is_demo: bool
    is_expired: bool
    item_code: str
    description: str
    specification: str | None
    unit: str
    unit_display: str
    rate: str
    rate_display: str
    can_edit: bool


class RateSearchOut(BaseModel):
    items: list[RateItemOut]
    total: int
    limit: int
    offset: int


class SourceCreate(BaseModel):
    state: str = Field(min_length=1, max_length=80)
    department: str = Field(min_length=1, max_length=120)
    sor_name: str = Field(min_length=1, max_length=200)
    year: str = Field(min_length=7, max_length=7)
    effective_from: date
    effective_to: date | None = None
    source_reference: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)


class SourcePatch(BaseModel):
    state: str | None = Field(default=None, max_length=80)
    department: str | None = Field(default=None, max_length=120)
    sor_name: str | None = Field(default=None, max_length=200)
    year: str | None = Field(default=None, max_length=7)
    effective_from: date | None = None
    effective_to: date | None = None
    source_reference: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)


class ItemCreate(BaseModel):
    item_code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=5000)
    specification: str | None = Field(default=None, max_length=5000)
    unit: str = Field(min_length=1, max_length=40)
    rate: str | int | float


class ItemPatch(BaseModel):
    item_code: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    specification: str | None = Field(default=None, max_length=5000)
    unit: str | None = Field(default=None, max_length=40)
    rate: str | int | float | None = None


def _can_edit(ctx: AuthContext, source: RateSource) -> bool:
    return source.organization_id is not None and ctx.is_org_admin


def source_out(ctx: AuthContext, summary: service.SourceSummary) -> RateSourceOut:
    s = summary.source
    return RateSourceOut(
        id=s.id,
        state=s.state,
        department=s.department,
        sor_name=s.sor_name,
        year=s.year,
        effective_from=s.effective_from,
        effective_to=s.effective_to,
        verification_status=s.verification_status,
        is_demo=s.verification_status == "demo",
        is_expired=service.is_expired(s),
        source_reference=s.source_reference,
        notes=s.notes,
        item_count=summary.item_count,
        owned=s.organization_id is not None,
        can_edit=_can_edit(ctx, s),
        created_at=s.created_at,
    )


def item_out(ctx: AuthContext, item: RateItem, source: RateSource) -> RateItemOut:
    unit = default_registry().get(item.unit_code)
    return RateItemOut(
        id=item.id,
        source_id=source.id,
        source_label=service.source_label(source),
        verification_status=source.verification_status,
        is_demo=source.verification_status == "demo",
        is_expired=service.is_expired(source),
        item_code=item.item_code,
        description=item.description,
        specification=item.specification,
        unit=item.unit_code,
        unit_display=unit.display_name,
        rate=format(item.basic_rate, "f"),
        rate_display=format_inr(item.basic_rate),
        can_edit=_can_edit(ctx, source),
    )


def _source(db: DB, ctx: AuthContext, source: RateSource) -> RateSourceOut:
    summary = next(s for s in service.list_sources(db, ctx) if s.source.id == source.id)
    return source_out(ctx, summary)


@router.get("/rate-sources", response_model=Envelope[list[RateSourceOut]])
def list_sources(auth: Auth, db: DB) -> Envelope[list[RateSourceOut]]:
    return ok([source_out(auth, s) for s in service.list_sources(db, auth)])


@router.post("/rate-sources", response_model=Envelope[RateSourceOut], status_code=201)
def create_source(body: SourceCreate, auth: Auth, db: DB) -> Envelope[RateSourceOut]:
    return ok(_source(db, auth, service.create_source(db, auth, body.model_dump())))


@router.patch("/rate-sources/{source_id}", response_model=Envelope[RateSourceOut])
def patch_source(
    source_id: uuid.UUID, body: SourcePatch, auth: Auth, db: DB
) -> Envelope[RateSourceOut]:
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    return ok(_source(db, auth, service.update_source(db, auth, source_id, changes)))


@router.delete("/rate-sources/{source_id}", response_model=Envelope[dict[str, bool]])
def delete_source(source_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[dict[str, bool]]:
    service.delete_source(db, auth, source_id)
    return ok({"deleted": True})


@router.get("/rate-items", response_model=Envelope[RateSearchOut])
def search_items(
    auth: Auth,
    db: DB,
    q: str | None = Query(default=None, max_length=200),
    source_id: uuid.UUID | None = None,
    unit: str | None = Query(default=None, max_length=40),
    include_expired: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Envelope[RateSearchOut]:
    result = service.search(
        db,
        auth,
        q=q,
        source_id=source_id,
        unit=unit,
        include_expired=include_expired,
        limit=limit,
        offset=offset,
    )
    return ok(
        RateSearchOut(
            items=[item_out(auth, i, s) for i, s in result.rows],
            total=result.total,
            limit=limit,
            offset=offset,
        )
    )


@router.post(
    "/rate-sources/{source_id}/items", response_model=Envelope[RateItemOut], status_code=201
)
def create_item(
    source_id: uuid.UUID, body: ItemCreate, auth: Auth, db: DB
) -> Envelope[RateItemOut]:
    item, source = service.create_item(db, auth, source_id, body.model_dump())
    return ok(item_out(auth, item, source))


@router.patch("/rate-items/{item_id}", response_model=Envelope[RateItemOut])
def patch_item(item_id: uuid.UUID, body: ItemPatch, auth: Auth, db: DB) -> Envelope[RateItemOut]:
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    item, source = service.update_item(db, auth, item_id, changes)
    return ok(item_out(auth, item, source))


@router.delete("/rate-items/{item_id}", response_model=Envelope[dict[str, bool]])
def delete_item(item_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[dict[str, bool]]:
    service.delete_item(db, auth, item_id)
    return ok({"deleted": True})
