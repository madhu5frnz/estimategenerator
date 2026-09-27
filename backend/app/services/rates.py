"""Rate sources and rate items (the rate list estimates pick rates from).

* A workspace sees the platform-wide sources (organization NULL, e.g. the demo rates) and
  its own sources. Another workspace's sources are "not found".
* Only workspace owners/admins add, change or delete sources and items, and only their own.
  Platform sources are read-only.
* Rates a workspace enters are marked ``user_entered``. The demo source is marked ``demo``
  and every use of it is labelled "Not official SOR".
* Changing a rate item never changes estimates: an estimate keeps a snapshot of the rate
  it picked.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.ids import new_id
from app.core.security import now_utc
from app.domain.numeric import InvalidNumberError, round_half_up, to_decimal
from app.domain.units import default_registry
from app.models import BoqItem, RateItem, RateSource
from app.services import audit
from app.services.context import AuthContext

YEAR = re.compile(r"^\d{4}-\d{2}$")
SOURCE_TEXT = {
    "state": 80,
    "department": 120,
    "sor_name": 200,
    "source_reference": 300,
    "notes": 2000,
}
DEMO_LABEL = "Demo rate — not official SOR"


def source_label(source: RateSource) -> str:
    return f"{source.sor_name} {source.year}"


def is_expired(source: RateSource, today: date | None = None) -> bool:
    return source.effective_to is not None and source.effective_to < (today or date.today())


# ------------------------------------------------------------------ access
def _visible_sources(ctx: AuthContext) -> Select[RateSource]:
    return select(RateSource).where(
        or_(RateSource.organization_id.is_(None), RateSource.organization_id == ctx.organization_id)
    )


def _require_admin(ctx: AuthContext) -> None:
    if not ctx.is_org_admin:
        raise AppError(
            "FORBIDDEN", "Only workspace owners and admins can change the rate list.", 403
        )


def get_source(
    db: Session, ctx: AuthContext, source_id: uuid.UUID, *, writable: bool = False
) -> RateSource:
    source = db.scalar(_visible_sources(ctx).where(RateSource.id == source_id))
    if source is None:
        raise AppError("NOT_FOUND", "Rate source not found.", 404)
    if writable:
        _require_admin(ctx)
        if source.organization_id is None:
            raise AppError(
                "RATE_SOURCE_READ_ONLY",
                "This rate source is provided with the app and cannot be changed. "
                "Add your own source instead.",
                409,
            )
    return source


def get_item(
    db: Session, ctx: AuthContext, item_id: uuid.UUID, *, writable: bool = False
) -> tuple[RateItem, RateSource]:
    row = db.execute(
        _visible_sources(ctx)
        .add_columns(RateItem)
        .join(RateItem, RateItem.rate_source_id == RateSource.id)
        .where(RateItem.id == item_id)
    ).first()
    if row is None:
        raise AppError("NOT_FOUND", "Rate item not found.", 404)
    source, item = row
    if writable:
        get_source(db, ctx, source.id, writable=True)
    return item, source


# ------------------------------------------------------------------ helpers
def _text(data: dict[str, Any], name: str, limit: int, *, required: bool) -> str | None:
    value = (data.get(name) or "").strip()
    if not value:
        if required:
            raise AppError(
                "VALIDATION_ERROR",
                f"{name.replace('_', ' ').capitalize()} is required.",
                details={"field": name},
            )
        return None
    return value[:limit]


def _date(value: Any, label: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise AppError("VALIDATION_ERROR", f"{label} must be a date (YYYY-MM-DD).") from exc


def _money(value: Any, label: str) -> Decimal:
    try:
        number = to_decimal(value)
    except InvalidNumberError as exc:
        raise AppError("VALIDATION_ERROR", f"{label}: {exc}", details={"field": "rate"}) from exc
    if number < 0:
        raise AppError(
            "VALIDATION_ERROR", f"{label} cannot be negative.", details={"field": "rate"}
        )
    if number != round_half_up(number, 2):
        raise AppError(
            "VALIDATION_ERROR",
            f"{label} can have at most 2 decimal places.",
            details={"field": "rate"},
        )
    return round_half_up(number, 2)


def _unit(value: Any) -> str:
    if not value or not str(value).strip():
        raise AppError("VALIDATION_ERROR", "Unit is required.", details={"field": "unit"})
    try:
        return default_registry().parse(str(value)).code
    except ValueError as exc:
        raise AppError(
            "UNKNOWN_UNIT", f"Unknown unit '{value}'.", details={"field": "unit"}
        ) from exc


def _audit(
    ctx: AuthContext,
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    old: Any = None,
    new: Any = None,
) -> None:
    audit.record(
        db,
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=old,
        new_value=new,
    )


# ------------------------------------------------------------------ sources
@dataclass(frozen=True)
class SourceSummary:
    source: RateSource
    item_count: int


def list_sources(db: Session, ctx: AuthContext) -> list[SourceSummary]:
    counts = dict(
        db.execute(
            select(RateItem.rate_source_id, func.count()).group_by(RateItem.rate_source_id)
        ).all()
    )
    sources = db.scalars(
        _visible_sources(ctx).order_by(
            RateSource.organization_id.is_(None), RateSource.sor_name, RateSource.year.desc()
        )
    ).all()
    return [SourceSummary(s, int(counts.get(s.id, 0))) for s in sources]


def _source_fields(data: dict[str, Any], current: RateSource | None) -> dict[str, Any]:
    def has(name: str) -> bool:
        return current is None or name in data

    out: dict[str, Any] = {}
    for name, limit in SOURCE_TEXT.items():
        if has(name):
            out[name] = _text(
                data, name, limit, required=name in ("state", "department", "sor_name")
            )
    if has("year"):
        year = (data.get("year") or "").strip()
        if not YEAR.fullmatch(year):
            raise AppError(
                "VALIDATION_ERROR", "Year must look like 2026-27.", details={"field": "year"}
            )
        out["year"] = year
    if has("effective_from"):
        start = _date(data.get("effective_from"), "Effective from")
        if start is None:
            raise AppError(
                "VALIDATION_ERROR",
                "Effective from is required.",
                details={"field": "effective_from"},
            )
        out["effective_from"] = start
    if has("effective_to"):
        out["effective_to"] = _date(data.get("effective_to"), "Effective to")
    start = out.get("effective_from", current.effective_from if current else None)
    end = out.get("effective_to", current.effective_to if current else None)
    if start and end and end < start:
        raise AppError(
            "VALIDATION_ERROR",
            "Effective to must be on or after effective from.",
            details={"field": "effective_to"},
        )
    return out


def create_source(db: Session, ctx: AuthContext, data: dict[str, Any]) -> RateSource:
    _require_admin(ctx)
    source = RateSource(
        id=new_id(),
        organization_id=ctx.organization_id,
        verification_status="user_entered",
        created_by=ctx.user.id,
        **_source_fields(data, None),
    )
    db.add(source)
    _audit(
        ctx,
        db,
        "rate_source",
        source.id,
        "create",
        new={"sor_name": source.sor_name, "year": source.year},
    )
    db.commit()
    return source


def update_source(
    db: Session, ctx: AuthContext, source_id: uuid.UUID, data: dict[str, Any]
) -> RateSource:
    source = get_source(db, ctx, source_id, writable=True)
    for name, value in _source_fields(data, source).items():
        old = getattr(source, name)
        if old != value:
            setattr(source, name, value)
            _audit(
                ctx,
                db,
                "rate_source",
                source.id,
                "update",
                old={name: str(old) if old is not None else None},
                new={name: str(value) if value is not None else None},
            )
    db.commit()
    return source


def _in_use(db: Session, item_ids: Select[Any] | list[uuid.UUID]) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(BoqItem).where(BoqItem.rate_item_id.in_(item_ids))
        )
        or 0
    )


def delete_source(db: Session, ctx: AuthContext, source_id: uuid.UUID) -> None:
    source = get_source(db, ctx, source_id, writable=True)
    used = _in_use(db, select(RateItem.id).where(RateItem.rate_source_id == source.id))
    if used:
        raise AppError(
            "RATE_IN_USE",
            f"Rates from this source are used by {used} BOQ item(s) and cannot be deleted.",
            409,
        )
    _audit(
        ctx,
        db,
        "rate_source",
        source.id,
        "delete",
        old={"sor_name": source.sor_name, "year": source.year},
    )
    db.delete(source)
    db.commit()


# ------------------------------------------------------------------ items
@dataclass(frozen=True)
class SearchResult:
    rows: list[tuple[RateItem, RateSource]]
    total: int


def search(
    db: Session,
    ctx: AuthContext,
    *,
    q: str | None = None,
    source_id: uuid.UUID | None = None,
    unit: str | None = None,
    include_expired: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> SearchResult:
    stmt = (
        _visible_sources(ctx)
        .add_columns(RateItem)
        .join(RateItem, RateItem.rate_source_id == RateSource.id)
    )
    if source_id:
        stmt = stmt.where(RateSource.id == source_id)
    if unit:
        stmt = stmt.where(RateItem.unit_code == _unit(unit))
    if not include_expired:
        stmt = stmt.where(
            or_(RateSource.effective_to.is_(None), RateSource.effective_to >= date.today())
        )
    text = (q or "").strip()
    order: list[Any] = []
    if text:
        vector: Any = literal_column("rate_items.search_vector")
        query = func.plainto_tsquery("english", text)
        like = re.sub(r"([%_\\])", r"\\\1", text)
        stmt = stmt.where(
            or_(
                vector.op("@@")(query),
                RateItem.description.ilike(f"%{like}%"),
                RateItem.item_code.ilike(f"{like}%"),
            )
        )
        order.append(RateItem.item_code.ilike(f"{like}%").desc())
        order.append(func.ts_rank(vector, query).desc())
    order += [RateSource.sor_name, RateItem.item_code]
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(*order).limit(limit).offset(offset)).all()
    return SearchResult([(item, source) for source, item in rows], int(total))


def _item_fields(data: dict[str, Any], current: RateItem | None) -> dict[str, Any]:
    def has(name: str) -> bool:
        return current is None or name in data

    out: dict[str, Any] = {}
    if has("item_code"):
        out["item_code"] = _text(data, "item_code", 50, required=True)
    if has("description"):
        out["description"] = _text(data, "description", 5000, required=True)
    if has("specification"):
        out["specification"] = _text(data, "specification", 5000, required=False)
    if has("unit"):
        out["unit_code"] = _unit(data.get("unit"))
    if has("rate"):
        rate = _money(data.get("rate"), "Rate")
        out["basic_rate"] = rate
        out["total_rate"] = rate
    return out


def _save(db: Session, code: str | None) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "RATE_CODE_TAKEN",
            f"Item code {code} already exists in this source.",
            409,
            {"field": "item_code"},
        ) from exc


def create_item(
    db: Session, ctx: AuthContext, source_id: uuid.UUID, data: dict[str, Any]
) -> tuple[RateItem, RateSource]:
    source = get_source(db, ctx, source_id, writable=True)
    item = RateItem(id=new_id(), rate_source_id=source.id, **_item_fields(data, None))
    db.add(item)
    _audit(
        ctx,
        db,
        "rate_item",
        item.id,
        "create",
        new={
            "item_code": item.item_code,
            "unit": item.unit_code,
            "rate": format(item.basic_rate, "f"),
        },
    )
    _save(db, item.item_code)
    return item, source


def update_item(
    db: Session, ctx: AuthContext, item_id: uuid.UUID, data: dict[str, Any]
) -> tuple[RateItem, RateSource]:
    item, source = get_item(db, ctx, item_id, writable=True)
    for name, value in _item_fields(data, item).items():
        old = getattr(item, name)
        if old != value:
            setattr(item, name, value)
            if name != "total_rate":
                _audit(
                    ctx,
                    db,
                    "rate_item",
                    item.id,
                    "update",
                    old={name: str(old) if old is not None else None},
                    new={name: str(value) if value is not None else None},
                )
    _save(db, item.item_code)
    return item, source


def delete_item(db: Session, ctx: AuthContext, item_id: uuid.UUID) -> None:
    item, _ = get_item(db, ctx, item_id, writable=True)
    used = _in_use(db, [item.id])
    if used:
        raise AppError(
            "RATE_IN_USE", f"This rate is used by {used} BOQ item(s) and cannot be deleted.", 409
        )
    _audit(
        ctx,
        db,
        "rate_item",
        item.id,
        "delete",
        old={"item_code": item.item_code, "rate": format(item.basic_rate, "f")},
    )
    db.delete(item)
    db.commit()


def snapshot(item: RateItem, source: RateSource) -> dict[str, Any]:
    """What a BOQ item keeps of the rate it picked (the rate list may change later)."""
    return {
        "source_id": str(source.id),
        "sor_name": source.sor_name,
        "year": source.year,
        "state": source.state,
        "department": source.department,
        "item_code": item.item_code,
        "description": item.description,
        "unit": item.unit_code,
        "basic_rate": format(item.basic_rate, "f"),
        "verification_status": source.verification_status,
        "effective_from": source.effective_from.isoformat(),
        "effective_to": source.effective_to.isoformat() if source.effective_to else None,
        "picked_at": now_utc().isoformat(),
    }
