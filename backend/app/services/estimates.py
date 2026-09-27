"""Estimates, versions, sections, BOQ items, measurement lines and parameters.

Rules enforced here (and, for frozen versions, again by database triggers):

* Every read and write goes through the project access check (tenant + project role).
  Viewing needs ``viewer``; changing anything needs ``professional``; deleting an estimate
  needs ``admin``.
* Only the draft version can change. Freezing a draft stores its totals, makes it
  read-only, and copies it into the next draft. ``line_key`` values are copied so versions
  can be compared row by row.
* Quantities come from the calculation engine. A BOQ item either has a manual quantity or
  takes the sum of its measurement lines (deductions subtract). Amount = quantity × rate,
  recalculated whenever either changes. Changing a parameter recalculates every line that
  uses it, and every item those lines belong to, in the same transaction.
* Every change is written to the audit log with the old and new value.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.ids import new_id
from app.core.security import now_utc
from app.domain import ENGINE_VERSION
from app.domain.estimate.measurement import dimensions_calculation
from app.domain.estimate.totals import (
    SectionTotal,
    line_amount,
    measured_quantity,
    section_total,
    works_subtotal,
)
from app.domain.money import amount_in_words, format_inr
from app.domain.numeric import InvalidNumberError, round_half_up, to_decimal
from app.domain.quantity import (
    BUILTIN_TEMPLATES,
    CalculationError,
    CalculationResult,
    CalculationStep,
    ParamInput,
    evaluate_expression,
    evaluate_template,
)
from app.domain.units import default_registry
from app.models import (
    BoqItem,
    Calculation,
    Estimate,
    EstimateSection,
    EstimateVersion,
    Measurement,
    Project,
    QuantityInput,
)
from app.services import audit
from app.services import projects as project_service
from app.services.context import AuthContext
from app.services.projects import ProjectAccess

EDIT_ROLE = "professional"
PARAM_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
DEFAULT_SECTION = "General works"


# =============================================================================
# Access
# =============================================================================
@dataclass(frozen=True)
class VersionScope:
    version: EstimateVersion
    estimate: Estimate
    access: ProjectAccess

    @property
    def project_id(self) -> uuid.UUID:
        return self.estimate.project_id


def get_estimate(
    db: Session, ctx: AuthContext, estimate_id: uuid.UUID, minimum: str = "viewer"
) -> tuple[Estimate, ProjectAccess]:
    estimate = db.scalar(
        select(Estimate).where(
            Estimate.id == estimate_id,
            Estimate.organization_id == ctx.organization_id,
            Estimate.deleted_at.is_(None),
        )
    )
    if estimate is None:
        raise AppError("NOT_FOUND", "Estimate not found.", 404)
    access = project_service.get_access(db, ctx, estimate.project_id, minimum)
    return estimate, access


def get_version(
    db: Session,
    ctx: AuthContext,
    version_id: uuid.UUID,
    minimum: str = "viewer",
    *,
    writable: bool = False,
) -> VersionScope:
    version = db.scalar(
        select(EstimateVersion).where(
            EstimateVersion.id == version_id,
            EstimateVersion.organization_id == ctx.organization_id,
        )
    )
    if version is None:
        raise AppError("NOT_FOUND", "Estimate version not found.", 404)
    estimate, access = get_estimate(db, ctx, version.estimate_id, minimum)
    if writable and version.status != "draft":
        draft_no = db.scalar(
            select(EstimateVersion.version_no).where(
                EstimateVersion.estimate_id == estimate.id, EstimateVersion.status == "draft"
            )
        )
        raise AppError(
            "VERSION_FROZEN",
            f"V{version.version_no} is frozen and cannot be changed. Edit the current draft"
            + (f" (V{draft_no})." if draft_no else "."),
            409,
            {"draft_version_no": draft_no},
        )
    return VersionScope(version=version, estimate=estimate, access=access)


def _scope_for(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, minimum: str = EDIT_ROLE
) -> VersionScope:
    return get_version(db, ctx, version_id, minimum, writable=True)


def _audit(
    db: Session,
    ctx: AuthContext,
    scope: VersionScope,
    *,
    entity_type: str,
    entity_id: uuid.UUID | None,
    action: str,
    field_name: str | None = None,
    old: Any = None,
    new: Any = None,
) -> None:
    audit.record(
        db,
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        project_id=scope.project_id,
        version_id=scope.version.id,
        action=action,
        field=field_name,
        old_value=_json(old),
        new_value=_json(new),
    )


def _finish(db: Session, commit: bool) -> None:
    """Commit, or only flush when the caller wraps several operations in one transaction."""
    if commit:
        db.commit()
    else:
        db.flush()


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _decimal(
    value: Any, label: str, *, places: int | None = None, allow_none: bool = True
) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise AppError("VALIDATION_ERROR", f"{label} is required.")
    try:
        number = to_decimal(value)
    except InvalidNumberError as exc:
        raise AppError("VALIDATION_ERROR", f"{label}: {exc}") from exc
    if number < 0:
        raise AppError("VALIDATION_ERROR", f"{label} cannot be negative.")
    if places is not None and number != round_half_up(number, places):
        raise AppError("VALIDATION_ERROR", f"{label} can have at most {places} decimal places.")
    return number


# =============================================================================
# Estimates and versions
# =============================================================================
def _next_estimate_number(db: Session, organization_id: uuid.UUID) -> str:
    year = now_utc().year
    prefix = f"EST-{year}-"
    count = db.scalar(
        select(func.count())
        .select_from(Estimate)
        .where(
            Estimate.organization_id == organization_id,
            Estimate.estimate_number.like(f"{prefix}%"),
        )
    )
    return f"{prefix}{int(count or 0) + 1:04d}"


def create_estimate(
    db: Session,
    ctx: AuthContext,
    project_id: uuid.UUID,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> Estimate:
    project_service.get_access(db, ctx, project_id, EDIT_ROLE)
    number = (data.pop("estimate_number", None) or "").strip()
    for attempt in range(5):
        candidate = number or _next_estimate_number(db, ctx.organization_id)
        if number and attempt:
            break
        estimate = Estimate(
            id=new_id(),
            organization_id=ctx.organization_id,
            project_id=project_id,
            estimate_number=candidate,
            created_by=ctx.user.id,
            **data,
        )
        try:
            with db.begin_nested():
                db.add(estimate)
                db.flush()
        except IntegrityError:
            if number:
                raise AppError(
                    "ESTIMATE_NUMBER_TAKEN",
                    f"Estimate number {number} is already used in this workspace.",
                    409,
                    {"field": "estimate_number"},
                ) from None
            continue
        version = EstimateVersion(
            id=new_id(),
            organization_id=ctx.organization_id,
            estimate_id=estimate.id,
            version_no=1,
            status="draft",
            created_by=ctx.user.id,
            engine_version=ENGINE_VERSION,
        )
        db.add(version)
        db.flush()
        db.add(
            EstimateSection(
                id=new_id(),
                organization_id=ctx.organization_id,
                version_id=version.id,
                line_key=new_id(),
                title=DEFAULT_SECTION,
                sequence=1,
            )
        )
        audit.record(
            db,
            actor=ctx.user,
            organization_id=ctx.organization_id,
            entity_type="estimate",
            entity_id=estimate.id,
            project_id=project_id,
            version_id=version.id,
            action="create",
            new_value={"estimate_number": candidate, "title": estimate.title},
        )
        _finish(db, commit)
        return estimate
    raise AppError("ESTIMATE_NUMBER_TAKEN", "Could not allocate an estimate number.", 409)


def update_estimate(
    db: Session, ctx: AuthContext, estimate_id: uuid.UUID, changes: dict[str, Any]
) -> Estimate:
    estimate, _ = get_estimate(db, ctx, estimate_id, EDIT_ROLE)
    for name, new in changes.items():
        old = getattr(estimate, name)
        if old == new:
            continue
        setattr(estimate, name, new)
        audit.record(
            db,
            actor=ctx.user,
            organization_id=ctx.organization_id,
            entity_type="estimate",
            entity_id=estimate.id,
            project_id=estimate.project_id,
            action="update",
            field=name,
            old_value=old,
            new_value=new,
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "ESTIMATE_NUMBER_TAKEN",
            "That estimate number is already used.",
            409,
            {"field": "estimate_number"},
        ) from exc
    return estimate


def delete_estimate(db: Session, ctx: AuthContext, estimate_id: uuid.UUID) -> None:
    estimate, _ = get_estimate(db, ctx, estimate_id, "admin")
    estimate.deleted_at = now_utc()
    audit.record(
        db,
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type="estimate",
        entity_id=estimate.id,
        project_id=estimate.project_id,
        action="delete",
    )
    db.commit()


@dataclass(frozen=True)
class EstimateSummary:
    estimate: Estimate
    project_name: str
    draft_version_id: uuid.UUID
    draft_version_no: int
    version_count: int
    works_subtotal: Decimal
    item_count: int


def summaries(db: Session, estimates: Sequence[Estimate]) -> list[EstimateSummary]:
    if not estimates:
        return []
    ids = [e.id for e in estimates]
    versions = db.execute(
        select(
            EstimateVersion.estimate_id,
            EstimateVersion.id,
            EstimateVersion.version_no,
            EstimateVersion.status,
        ).where(EstimateVersion.estimate_id.in_(ids))
    ).all()
    drafts = {row.estimate_id: row for row in versions if row.status == "draft"}
    counts: dict[uuid.UUID, int] = defaultdict(int)
    for row in versions:
        counts[row.estimate_id] += 1
    draft_ids = [row.id for row in drafts.values()]
    sums = {
        row.version_id: (row.total, row.items)
        for row in db.execute(
            select(
                BoqItem.version_id,
                func.coalesce(func.sum(BoqItem.amount), 0).label("total"),
                func.count().label("items"),
            )
            .where(BoqItem.version_id.in_(draft_ids))
            .group_by(BoqItem.version_id)
        ).all()
    }
    names = dict(
        db.execute(
            select(Project.id, Project.name).where(
                Project.id.in_({e.project_id for e in estimates})
            )
        ).all()
    )
    out = []
    for e in estimates:
        draft = drafts[e.id]
        total, items = sums.get(draft.id, (Decimal(0), 0))
        out.append(
            EstimateSummary(
                estimate=e,
                project_name=names.get(e.project_id, ""),
                draft_version_id=draft.id,
                draft_version_no=draft.version_no,
                version_count=counts[e.id],
                works_subtotal=round_half_up(Decimal(total), 2),
                item_count=int(items),
            )
        )
    return out


def list_for_project(db: Session, ctx: AuthContext, project_id: uuid.UUID) -> list[EstimateSummary]:
    project_service.get_access(db, ctx, project_id, "viewer")
    rows = db.scalars(
        select(Estimate)
        .where(Estimate.project_id == project_id, Estimate.deleted_at.is_(None))
        .order_by(Estimate.created_at)
    ).all()
    return summaries(db, rows)


def list_recent(db: Session, ctx: AuthContext, limit: int = 10) -> list[EstimateSummary]:
    visible = project_service.visible_project_ids(ctx)
    rows = db.scalars(
        select(Estimate)
        .where(
            Estimate.organization_id == ctx.organization_id,
            Estimate.deleted_at.is_(None),
            Estimate.project_id.in_(visible),
        )
        .order_by(Estimate.updated_at.desc(), Estimate.id.desc())
        .limit(limit)
    ).all()
    return summaries(db, rows)


def list_versions(db: Session, ctx: AuthContext, estimate_id: uuid.UUID) -> list[dict[str, Any]]:
    get_estimate(db, ctx, estimate_id)
    versions = db.scalars(
        select(EstimateVersion)
        .where(EstimateVersion.estimate_id == estimate_id)
        .order_by(EstimateVersion.version_no.desc())
    ).all()
    live = {
        row.version_id: row.total
        for row in db.execute(
            select(BoqItem.version_id, func.coalesce(func.sum(BoqItem.amount), 0).label("total"))
            .where(BoqItem.version_id.in_([v.id for v in versions]))
            .group_by(BoqItem.version_id)
        ).all()
    }
    out = []
    for v in versions:
        total = (
            Decimal(v.totals_snapshot["works_subtotal"])
            if v.status == "frozen" and v.totals_snapshot
            else round_half_up(Decimal(live.get(v.id, 0)), 2)
        )
        out.append({"version": v, "works_subtotal": total})
    return out


# --------------------------------------------------------------------- freeze
def freeze(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, change_note: str
) -> EstimateVersion:
    note = change_note.strip()
    if not note:
        raise AppError(
            "VALIDATION_ERROR", "Describe what this version is (e.g. 'Initial estimate')."
        )
    scope = _scope_for(db, ctx, version_id)
    view = load_version(db, scope)
    version = scope.version
    version.totals_snapshot = view.snapshot()
    version.status = "frozen"
    version.change_note = note[:300]
    version.frozen_at = now_utc()
    version.frozen_by = ctx.user.id
    version.engine_version = ENGINE_VERSION
    db.flush()
    draft = _clone(db, ctx, version)
    _audit(
        db,
        ctx,
        scope,
        entity_type="estimate_version",
        entity_id=version.id,
        action="freeze",
        new={
            "version_no": version.version_no,
            "change_note": version.change_note,
            "works_subtotal": version.totals_snapshot["works_subtotal"],
        },
    )
    db.commit()
    return draft


def _clone(db: Session, ctx: AuthContext, source: EstimateVersion) -> EstimateVersion:
    draft = EstimateVersion(
        id=new_id(),
        organization_id=source.organization_id,
        estimate_id=source.estimate_id,
        version_no=source.version_no + 1,
        status="draft",
        parent_version_id=source.id,
        gst_config=dict(source.gst_config),
        rounding_config=dict(source.rounding_config),
        engine_version=ENGINE_VERSION,
        created_by=ctx.user.id,
    )
    db.add(draft)
    db.flush()
    org = source.organization_id
    section_map: dict[uuid.UUID, uuid.UUID] = {}
    for s in db.scalars(select(EstimateSection).where(EstimateSection.version_id == source.id)):
        section_map[s.id] = new_id()
        db.add(
            EstimateSection(
                id=section_map[s.id],
                organization_id=org,
                version_id=draft.id,
                line_key=s.line_key,
                title=s.title,
                sequence=s.sequence,
            )
        )
    db.flush()
    item_map: dict[uuid.UUID, uuid.UUID] = {}
    item_fields = (
        "line_key",
        "sequence",
        "item_no",
        "description",
        "specification",
        "unit_code",
        "quantity",
        "quantity_raw",
        "quantity_source",
        "rate",
        "rate_source_type",
        "rate_item_id",
        "rate_snapshot",
        "amount",
        "remarks",
        "provenance",
        "ai_generation_id",
    )
    for i in db.scalars(select(BoqItem).where(BoqItem.version_id == source.id)):
        item_map[i.id] = new_id()
        db.add(
            BoqItem(
                id=item_map[i.id],
                organization_id=org,
                version_id=draft.id,
                section_id=section_map[i.section_id],
                **{f: getattr(i, f) for f in item_fields},
            )
        )
    db.flush()
    line_map: dict[uuid.UUID, uuid.UUID] = {}
    line_fields = (
        "line_key",
        "sequence",
        "mode",
        "description",
        "nos",
        "length",
        "breadth",
        "depth_height",
        "dimension_unit",
        "quantity",
        "quantity_raw",
        "is_deduction",
        "provenance",
    )
    for m in db.scalars(select(Measurement).where(Measurement.version_id == source.id)):
        line_map[m.id] = new_id()
        db.add(
            Measurement(
                id=line_map[m.id],
                organization_id=org,
                version_id=draft.id,
                boq_item_id=item_map[m.boq_item_id],
                **{f: getattr(m, f) for f in line_fields},
            )
        )
    db.flush()
    calc_fields = (
        "template_id",
        "template_version",
        "expression",
        "input_parameters",
        "substituted",
        "steps",
        "result_raw",
        "result_unit",
        "engine_version",
        "calculated_at",
    )
    if line_map:
        for c in db.scalars(
            select(Calculation).where(Calculation.estimate_item_id.in_(list(line_map)))
        ):
            db.add(
                Calculation(
                    id=new_id(),
                    organization_id=org,
                    estimate_item_id=line_map[c.estimate_item_id],
                    **{f: getattr(c, f) for f in calc_fields},
                )
            )
    param_fields = (
        "line_key",
        "name",
        "label",
        "value",
        "unit_code",
        "provenance",
        "source_text",
        "source_document_id",
        "confirmed_by",
        "confirmed_at",
    )
    for p in db.scalars(select(QuantityInput).where(QuantityInput.version_id == source.id)):
        db.add(
            QuantityInput(
                id=new_id(),
                organization_id=org,
                version_id=draft.id,
                **{f: getattr(p, f) for f in param_fields},
            )
        )
    db.flush()
    return draft


# =============================================================================
# Loading a whole version
# =============================================================================
@dataclass
class LineView:
    line: Measurement
    calculation: Calculation | None


@dataclass
class ItemView:
    item: BoqItem
    sl_no: str
    lines: list[LineView] = field(default_factory=list)


@dataclass
class SectionView:
    section: EstimateSection
    sl_no: int
    items: list[ItemView]
    total: SectionTotal


@dataclass
class VersionView:
    version: EstimateVersion
    estimate: Estimate
    sections: list[SectionView]
    parameters: list[QuantityInput]
    parameter_usage: dict[str, int]
    works_subtotal: Decimal

    @property
    def item_count(self) -> int:
        return sum(s.total.item_count for s in self.sections)

    @property
    def unpriced_count(self) -> int:
        return sum(s.total.item_count - s.total.priced_count for s in self.sections)

    def snapshot(self) -> dict[str, Any]:
        return {
            "works_subtotal": format(self.works_subtotal, "f"),
            "item_count": self.item_count,
            "unpriced_count": self.unpriced_count,
            "sections": {
                str(s.section.line_key): format(s.total.subtotal, "f") for s in self.sections
            },
        }

    @property
    def display_total(self) -> Decimal:
        if self.version.status == "frozen" and self.version.totals_snapshot:
            return Decimal(self.version.totals_snapshot["works_subtotal"])
        return self.works_subtotal

    @property
    def words(self) -> str:
        total = self.display_total
        return amount_in_words(total) if total >= 0 else ""

    @property
    def total_display(self) -> str:
        return format_inr(self.display_total)


def load_version(db: Session, scope: VersionScope) -> VersionView:
    vid = scope.version.id
    sections = db.scalars(
        select(EstimateSection)
        .where(EstimateSection.version_id == vid)
        .order_by(EstimateSection.sequence, EstimateSection.id)
    ).all()
    items = db.scalars(
        select(BoqItem).where(BoqItem.version_id == vid).order_by(BoqItem.sequence, BoqItem.id)
    ).all()
    lines = db.scalars(
        select(Measurement)
        .where(Measurement.version_id == vid)
        .order_by(Measurement.sequence, Measurement.id)
    ).all()
    calcs = (
        {
            c.estimate_item_id: c
            for c in db.scalars(
                select(Calculation).where(Calculation.estimate_item_id.in_([m.id for m in lines]))
            )
        }
        if lines
        else {}
    )
    params = db.scalars(
        select(QuantityInput).where(QuantityInput.version_id == vid).order_by(QuantityInput.name)
    ).all()

    lines_by_item: dict[uuid.UUID, list[LineView]] = defaultdict(list)
    usage: dict[str, int] = defaultdict(int)
    for m in lines:
        calc = calcs.get(m.id)
        lines_by_item[m.boq_item_id].append(LineView(m, calc))
        for ref in _refs(calc):
            usage[ref] += 1
    items_by_section: dict[uuid.UUID, list[BoqItem]] = defaultdict(list)
    for i in items:
        items_by_section[i.section_id].append(i)

    section_views = []
    for s_no, s in enumerate(sections, start=1):
        views = [
            ItemView(item=i, sl_no=f"{s_no}.{i_no}", lines=lines_by_item.get(i.id, []))
            for i_no, i in enumerate(items_by_section.get(s.id, []), start=1)
        ]
        section_views.append(
            SectionView(s, s_no, views, section_total(v.item.amount for v in views))
        )
    return VersionView(
        version=scope.version,
        estimate=scope.estimate,
        sections=section_views,
        parameters=list(params),
        parameter_usage=dict(usage),
        works_subtotal=works_subtotal(sv.total for sv in section_views),
    )


def _refs(calc: Calculation | None) -> Iterable[str]:
    if calc is None:
        return ()
    return (
        str(spec["ref"])
        for spec in calc.input_parameters.values()
        if isinstance(spec, dict) and spec.get("ref")
    )


# =============================================================================
# Sections
# =============================================================================
def add_section(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, title: str, *, commit: bool = True
) -> VersionScope:
    scope = _scope_for(db, ctx, version_id)
    title = title.strip()
    if not title:
        raise AppError("VALIDATION_ERROR", "Section title is required.")
    last = db.scalar(
        select(func.max(EstimateSection.sequence)).where(EstimateSection.version_id == version_id)
    )
    section = EstimateSection(
        id=new_id(),
        organization_id=ctx.organization_id,
        version_id=version_id,
        line_key=new_id(),
        title=title[:200],
        sequence=int(last or 0) + 1,
    )
    db.add(section)
    _audit(db, ctx, scope, entity_type="section", entity_id=section.id, action="create", new=title)
    _finish(db, commit)
    return scope


def _section(
    db: Session, ctx: AuthContext, section_id: uuid.UUID
) -> tuple[EstimateSection, VersionScope]:
    section = db.scalar(
        select(EstimateSection).where(
            EstimateSection.id == section_id,
            EstimateSection.organization_id == ctx.organization_id,
        )
    )
    if section is None:
        raise AppError("NOT_FOUND", "Section not found.", 404)
    return section, _scope_for(db, ctx, section.version_id)


def rename_section(
    db: Session, ctx: AuthContext, section_id: uuid.UUID, title: str
) -> VersionScope:
    section, scope = _section(db, ctx, section_id)
    title = title.strip()
    if not title:
        raise AppError("VALIDATION_ERROR", "Section title is required.")
    if title != section.title:
        _audit(
            db,
            ctx,
            scope,
            entity_type="section",
            entity_id=section.id,
            action="update",
            field_name="title",
            old=section.title,
            new=title,
        )
        section.title = title[:200]
    db.commit()
    return scope


def delete_section(db: Session, ctx: AuthContext, section_id: uuid.UUID) -> VersionScope:
    section, scope = _section(db, ctx, section_id)
    count = db.scalar(
        select(func.count()).select_from(BoqItem).where(BoqItem.section_id == section.id)
    )
    _audit(
        db,
        ctx,
        scope,
        entity_type="section",
        entity_id=section.id,
        action="delete",
        old={"title": section.title, "items": count},
    )
    db.delete(section)  # items, lines and calculations cascade
    db.commit()
    return scope


def reorder_sections(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, ordered: list[uuid.UUID]
) -> VersionScope:
    scope = _scope_for(db, ctx, version_id)
    sections = db.scalars(
        select(EstimateSection).where(EstimateSection.version_id == version_id)
    ).all()
    if sorted(s.id for s in sections) != sorted(ordered) or len(set(ordered)) != len(ordered):
        raise AppError("VALIDATION_ERROR", "The new order must list every section exactly once.")
    position = {sid: n for n, sid in enumerate(ordered, start=1)}
    for s in sections:
        s.sequence = position[s.id]
    _audit(
        db,
        ctx,
        scope,
        entity_type="section",
        entity_id=None,
        action="reorder",
        new=[str(i) for i in ordered],
    )
    db.commit()
    return scope


# =============================================================================
# BOQ items
# =============================================================================
ITEM_TEXT_FIELDS = {"item_no": 50, "description": 5000, "specification": 5000, "remarks": 1000}
AUDIT_NAMES = {
    "boq_items": "boq_item",
    "estimate_items": "measurement",
    "quantity_inputs": "parameter",
    "estimate_sections": "section",
}


def _item(db: Session, ctx: AuthContext, item_id: uuid.UUID) -> tuple[BoqItem, VersionScope]:
    item = db.scalar(
        select(BoqItem).where(BoqItem.id == item_id, BoqItem.organization_id == ctx.organization_id)
    )
    if item is None:
        raise AppError("NOT_FOUND", "BOQ item not found.", 404)
    return item, _scope_for(db, ctx, item.version_id)


def _unit_code(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return default_registry().parse(str(value)).code
    except ValueError as exc:
        raise AppError(
            "UNKNOWN_UNIT", f"Unknown unit '{value}'.", details={"field": "unit"}
        ) from exc


def _quantity_places(unit_code: str | None) -> int:
    return default_registry().get(unit_code).decimal_places if unit_code else 3


def _reprice(item: BoqItem) -> None:
    item.amount = line_amount(item.quantity, item.rate)


def add_item(
    db: Session,
    ctx: AuthContext,
    version_id: uuid.UUID,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> tuple[VersionScope, BoqItem]:
    scope = _scope_for(db, ctx, version_id)
    section_id = data.get("section_id")
    section = db.get(EstimateSection, section_id) if section_id else None
    if section is None or section.version_id != version_id:
        raise AppError(
            "VALIDATION_ERROR", "Choose a section of this version.", details={"field": "section_id"}
        )
    description = (data.get("description") or "").strip()
    if not description:
        raise AppError(
            "VALIDATION_ERROR", "Item description is required.", details={"field": "description"}
        )
    unit = _unit_code(data.get("unit"))
    quantity = _decimal(data.get("quantity"), "Quantity")
    if quantity is not None:
        quantity = round_half_up(quantity, _quantity_places(unit))
    rate = _decimal(data.get("rate"), "Rate", places=2)
    last = db.scalar(select(func.max(BoqItem.sequence)).where(BoqItem.section_id == section.id))
    item = BoqItem(
        id=new_id(),
        organization_id=ctx.organization_id,
        version_id=version_id,
        section_id=section.id,
        line_key=new_id(),
        sequence=int(last or 0) + 1,
        item_no=(data.get("item_no") or None),
        description=description[:5000],
        specification=(data.get("specification") or None),
        unit_code=unit,
        quantity=quantity,
        quantity_raw=quantity,
        quantity_source="manual",
        rate=rate,
        rate_source_type="manual" if rate is not None else None,
        remarks=(data.get("remarks") or None),
        provenance=data.get("provenance", "user_entered"),
    )
    _reprice(item)
    db.add(item)
    _audit(
        db,
        ctx,
        scope,
        entity_type="boq_item",
        entity_id=item.id,
        action="create",
        new={
            "description": description,
            "unit": unit,
            "quantity": _json(quantity),
            "rate": _json(rate),
        },
    )
    _finish(db, commit)
    return scope, item


def update_item(
    db: Session, ctx: AuthContext, item_id: uuid.UUID, changes: dict[str, Any]
) -> VersionScope:
    item, scope = _item(db, ctx, item_id)
    has_lines = bool(
        db.scalar(
            select(func.count()).select_from(Measurement).where(Measurement.boq_item_id == item.id)
        )
    )
    for name, raw in changes.items():
        if name in ITEM_TEXT_FIELDS:
            value = (raw or "").strip() or None
            if name == "description" and not value:
                raise AppError(
                    "VALIDATION_ERROR",
                    "Item description is required.",
                    details={"field": "description"},
                )
            _set(db, ctx, scope, item, name, value[: ITEM_TEXT_FIELDS[name]] if value else None)
        elif name == "unit":
            new_unit = _unit_code(raw)
            if new_unit != item.unit_code:
                if has_lines and new_unit is None:
                    raise AppError(
                        "VALIDATION_ERROR", "An item with measurement lines needs a unit."
                    )
                _set(db, ctx, scope, item, "unit_code", new_unit)
                if has_lines:
                    _recalculate_item(db, item)
                elif item.quantity is not None:
                    item.quantity = round_half_up(item.quantity, _quantity_places(new_unit))
        elif name == "quantity":
            if has_lines:
                raise AppError(
                    "QUANTITY_FROM_MEASUREMENTS",
                    "This quantity is the total of its measurement lines. Edit the lines instead.",
                    409,
                    {"field": "quantity"},
                )
            value = _decimal(raw, "Quantity")
            if value is not None:
                value = round_half_up(value, _quantity_places(item.unit_code))
            _set(db, ctx, scope, item, "quantity", value)
            item.quantity_raw = value
        elif name == "rate":
            value = _decimal(raw, "Rate", places=2)
            if value != item.rate:
                _set(db, ctx, scope, item, "rate", value)
                item.rate_source_type = "manual" if value is not None else None
                item.rate_item_id = None
                item.rate_snapshot = None
        elif name == "section_id":
            target = db.get(EstimateSection, raw) if raw else None
            if target is None or target.version_id != item.version_id:
                raise AppError("VALIDATION_ERROR", "Choose a section of this version.")
            if target.id != item.section_id:
                last = db.scalar(
                    select(func.max(BoqItem.sequence)).where(BoqItem.section_id == target.id)
                )
                _set(db, ctx, scope, item, "section_id", target.id)
                item.sequence = int(last or 0) + 1
    _reprice(item)
    db.commit()
    return scope


def _set(
    db: Session, ctx: AuthContext, scope: VersionScope, obj: Any, name: str, value: Any
) -> None:
    old = getattr(obj, name)
    if old == value:
        return
    setattr(obj, name, value)
    _audit(
        db,
        ctx,
        scope,
        entity_type=AUDIT_NAMES[obj.__tablename__],
        entity_id=obj.id,
        action="update",
        field_name=name,
        old=old,
        new=value,
    )


def delete_item(db: Session, ctx: AuthContext, item_id: uuid.UUID) -> VersionScope:
    item, scope = _item(db, ctx, item_id)
    _audit(
        db,
        ctx,
        scope,
        entity_type="boq_item",
        entity_id=item.id,
        action="delete",
        old={
            "description": item.description,
            "quantity": _json(item.quantity),
            "rate": _json(item.rate),
            "amount": _json(item.amount),
        },
    )
    db.delete(item)
    db.commit()
    return scope


def duplicate_item(db: Session, ctx: AuthContext, item_id: uuid.UUID) -> VersionScope:
    item, scope = _item(db, ctx, item_id)
    for later in db.scalars(
        select(BoqItem).where(
            BoqItem.section_id == item.section_id, BoqItem.sequence > item.sequence
        )
    ):
        later.sequence += 1
    copy = BoqItem(
        id=new_id(),
        organization_id=item.organization_id,
        version_id=item.version_id,
        section_id=item.section_id,
        line_key=new_id(),
        sequence=item.sequence + 1,
        item_no=None,
        description=item.description,
        specification=item.specification,
        unit_code=item.unit_code,
        quantity=item.quantity,
        quantity_raw=item.quantity_raw,
        quantity_source=item.quantity_source,
        rate=item.rate,
        rate_source_type=item.rate_source_type,
        rate_item_id=item.rate_item_id,
        rate_snapshot=item.rate_snapshot,
        amount=item.amount,
        remarks=item.remarks,
        provenance=item.provenance,
    )
    db.add(copy)
    db.flush()
    for line in db.scalars(select(Measurement).where(Measurement.boq_item_id == item.id)):
        calc = db.scalar(select(Calculation).where(Calculation.estimate_item_id == line.id))
        new_line = Measurement(
            id=new_id(),
            organization_id=line.organization_id,
            version_id=line.version_id,
            boq_item_id=copy.id,
            line_key=new_id(),
            sequence=line.sequence,
            mode=line.mode,
            description=line.description,
            nos=line.nos,
            length=line.length,
            breadth=line.breadth,
            depth_height=line.depth_height,
            dimension_unit=line.dimension_unit,
            quantity=line.quantity,
            quantity_raw=line.quantity_raw,
            is_deduction=line.is_deduction,
            provenance=line.provenance,
        )
        db.add(new_line)
        db.flush()
        if calc is not None:
            db.add(
                Calculation(
                    id=new_id(),
                    organization_id=calc.organization_id,
                    estimate_item_id=new_line.id,
                    template_id=calc.template_id,
                    template_version=calc.template_version,
                    expression=calc.expression,
                    input_parameters=calc.input_parameters,
                    substituted=calc.substituted,
                    steps=calc.steps,
                    result_raw=calc.result_raw,
                    result_unit=calc.result_unit,
                    engine_version=calc.engine_version,
                )
            )
    _audit(
        db,
        ctx,
        scope,
        entity_type="boq_item",
        entity_id=copy.id,
        action="duplicate",
        old=str(item.id),
    )
    db.commit()
    return scope


def reorder_items(
    db: Session,
    ctx: AuthContext,
    version_id: uuid.UUID,
    section_id: uuid.UUID,
    ordered: list[uuid.UUID],
) -> VersionScope:
    scope = _scope_for(db, ctx, version_id)
    items = db.scalars(
        select(BoqItem).where(BoqItem.version_id == version_id, BoqItem.section_id == section_id)
    ).all()
    if sorted(i.id for i in items) != sorted(ordered) or len(set(ordered)) != len(ordered):
        raise AppError(
            "VALIDATION_ERROR", "The new order must list every item of the section once."
        )
    position = {iid: n for n, iid in enumerate(ordered, start=1)}
    for i in items:
        i.sequence = position[i.id]
    _audit(
        db,
        ctx,
        scope,
        entity_type="boq_item",
        entity_id=None,
        action="reorder",
        new=[str(i) for i in ordered],
    )
    db.commit()
    return scope


# =============================================================================
# Measurement lines and calculations
# =============================================================================
@dataclass(frozen=True)
class LineSpec:
    mode: str
    description: str
    is_deduction: bool
    nos: Decimal
    length: Decimal | None
    breadth: Decimal | None
    depth_height: Decimal | None
    dimension_unit: str | None
    template_id: str | None
    expression: str | None
    inputs: dict[str, dict[str, Any]]


def _line_spec(
    data: dict[str, Any], current: Measurement | None = None, calc: Calculation | None = None
) -> LineSpec:
    def pick(name: str, default: Any) -> Any:
        return data.get(name, default)

    mode = pick("mode", current.mode if current else "dimensions")
    if mode not in ("dimensions", "formula"):
        raise AppError("VALIDATION_ERROR", "mode must be 'dimensions' or 'formula'.")
    description = (pick("description", current.description if current else "") or "").strip()
    nos = _decimal(pick("nos", current.nos if current else 1), "No.", allow_none=False)
    assert nos is not None
    spec = LineSpec(
        mode=mode,
        description=description[:500] or ("Formula" if mode == "formula" else "Measurement"),
        is_deduction=bool(pick("is_deduction", current.is_deduction if current else False)),
        nos=nos,
        length=_decimal(pick("length", current.length if current else None), "L"),
        breadth=_decimal(pick("breadth", current.breadth if current else None), "B"),
        depth_height=_decimal(
            pick("depth_height", current.depth_height if current else None), "D/H"
        ),
        dimension_unit=_unit_code(
            pick("dimension_unit", current.dimension_unit if current else "m")
        ),
        template_id=pick(
            "template_id",
            calc.template_id if calc and current and current.mode == "formula" else None,
        ),
        expression=pick(
            "expression",
            calc.expression
            if calc and calc.template_id is None and current and current.mode == "formula"
            else None,
        ),
        inputs=pick(
            "inputs",
            calc.input_parameters if calc and current and current.mode == "formula" else {},
        )
        or {},
    )
    if mode == "formula" and bool(spec.template_id) == bool(spec.expression):
        raise AppError(
            "VALIDATION_ERROR", "A formula line needs either a template or a custom formula."
        )
    return spec


def _compute(
    db: Session, item: BoqItem, spec: LineSpec
) -> tuple[CalculationResult, dict[str, Any], str | None, int | None, str]:
    """Returns (result, stored inputs, template id, template version, source expression)."""
    if not item.unit_code:
        raise AppError("UNIT_REQUIRED", "Set the item's unit before adding measurement lines.")
    registry = default_registry()
    if spec.mode == "dimensions":
        result = dimensions_calculation(
            item_unit=item.unit_code,
            nos=spec.nos,
            length=spec.length,
            breadth=spec.breadth,
            depth_height=spec.depth_height,
            dimension_unit=spec.dimension_unit,
        )
        stored_dims: dict[str, Any] = {
            name: {"value": format(i.value, "f"), "unit": i.unit}
            for name, i in ((r.name, r) for r in result.inputs)
        }
        dims = (("L", spec.length), ("B", spec.breadth), ("D", spec.depth_height))
        source = " * ".join(["nos", *(name for name, value in dims if value is not None)])
        return result, stored_dims, None, None, source

    params = {
        p.name: p
        for p in db.scalars(
            select(QuantityInput).where(QuantityInput.version_id == item.version_id)
        )
    }
    inputs: dict[str, ParamInput] = {}
    stored: dict[str, Any] = {}
    for name, raw in spec.inputs.items():
        if not isinstance(raw, dict):
            raise AppError("VALIDATION_ERROR", f"Input '{name}' must be an object.")
        ref = raw.get("ref")
        if ref:
            param = params.get(str(ref))
            if param is None:
                raise AppError(
                    "UNKNOWN_PARAMETER",
                    f"There is no parameter named '{ref}'.",
                    details={"parameter": ref},
                )
            if param.value is None:
                raise AppError(
                    "MISSING_PARAMETER",
                    f"Parameter '{param.label}' has no value yet.",
                    details={"parameters": [param.name]},
                )
            inputs[name] = ParamInput(param.value, param.unit_code)
            stored[name] = {
                "ref": param.name,
                "value": format(param.value, "f"),
                "unit": param.unit_code,
            }
        else:
            inputs[name] = ParamInput(raw.get("value"), raw.get("unit"))
            stored[name] = {"value": raw.get("value"), "unit": raw.get("unit")}

    if spec.template_id:
        template = next((t for t in BUILTIN_TEMPLATES if t.id == spec.template_id), None)
        if template is None:
            raise AppError("NOT_FOUND", f"Unknown calculation template '{spec.template_id}'.", 404)
        result = evaluate_template(template, inputs, registry)
        if result.unit != item.unit_code:
            result = _convert_result(result, item.unit_code)
        return result, stored, template.id, template.version, template.expression
    assert spec.expression is not None
    result = evaluate_expression(spec.expression, inputs, item.unit_code, registry)
    return result, stored, None, None, spec.expression


def _convert_result(result: CalculationResult, unit_code: str) -> CalculationResult:
    registry = default_registry()
    target = registry.get(unit_code)
    try:
        raw = registry.convert(result.value_raw, result.unit, unit_code)
    except ValueError as exc:
        raise AppError(
            "UNIT_MISMATCH",
            f"This formula gives {result.unit_display}, but the item is measured in "
            f"{target.display_name}.",
        ) from exc
    value = round_half_up(raw, target.decimal_places)
    step = CalculationStep(
        "result",
        f"= {format(value, 'f')} {target.display_name} (converted from {result.unit_display})",
    )
    return CalculationResult(
        value=value,
        value_raw=raw,
        unit=target.code,
        unit_display=target.display_name,
        expression=result.expression,
        substituted=result.substituted,
        inputs=result.inputs,
        steps=(*result.steps, step),
        template_id=result.template_id,
        template_version=result.template_version,
    )


def _store(
    db: Session,
    line: Measurement,
    calc: Calculation | None,
    computed: tuple[CalculationResult, dict[str, Any], str | None, int | None, str],
) -> None:
    result, stored, template_id, template_version, source = computed
    line.quantity = result.value
    line.quantity_raw = result.value_raw
    fields = {
        "template_id": template_id,
        "template_version": template_version,
        "expression": source,
        "input_parameters": stored,
        "substituted": result.substituted,
        "steps": [{"kind": s.kind, "text": s.text} for s in result.steps],
        "result_raw": result.value_raw,
        "result_unit": result.unit,
        "engine_version": result.engine_version,
        "calculated_at": now_utc(),
    }
    if calc is None:
        db.add(
            Calculation(
                id=new_id(),
                organization_id=line.organization_id,
                estimate_item_id=line.id,
                **fields,
            )
        )
    else:
        for k, v in fields.items():
            setattr(calc, k, v)


def _calculation_error(exc: CalculationError) -> AppError:
    return AppError(exc.code, exc.message, 400, exc.details)


def _refresh_item_quantity(db: Session, item: BoqItem) -> None:
    db.flush()
    lines = db.scalars(select(Measurement).where(Measurement.boq_item_id == item.id)).all()
    if lines:
        item.quantity_source = "measurements"
        item.quantity = measured_quantity(
            ((m.quantity or Decimal(0), m.is_deduction) for m in lines),
            _quantity_places(item.unit_code),
        )
        item.quantity_raw = item.quantity
    else:
        item.quantity_source = "manual"
        item.quantity = None
        item.quantity_raw = None
    _reprice(item)


def _recalculate_item(db: Session, item: BoqItem) -> None:
    """Re-run every line of an item (after its unit changed)."""
    for line in db.scalars(select(Measurement).where(Measurement.boq_item_id == item.id)):
        calc = db.scalar(select(Calculation).where(Calculation.estimate_item_id == line.id))
        try:
            _store(db, line, calc, _compute(db, item, _line_spec({}, line, calc)))
        except CalculationError as exc:
            raise _calculation_error(exc) from exc
    _refresh_item_quantity(db, item)


def add_line(
    db: Session,
    ctx: AuthContext,
    item_id: uuid.UUID,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> VersionScope:
    item, scope = _item(db, ctx, item_id)
    spec = _line_spec(data)
    try:
        computed = _compute(db, item, spec)
    except CalculationError as exc:
        raise _calculation_error(exc) from exc
    last = db.scalar(
        select(func.max(Measurement.sequence)).where(Measurement.boq_item_id == item.id)
    )
    line = Measurement(
        id=new_id(),
        organization_id=ctx.organization_id,
        version_id=item.version_id,
        boq_item_id=item.id,
        line_key=new_id(),
        sequence=int(last or 0) + 1,
        mode=spec.mode,
        description=spec.description,
        nos=spec.nos,
        length=spec.length if spec.mode == "dimensions" else None,
        breadth=spec.breadth if spec.mode == "dimensions" else None,
        depth_height=spec.depth_height if spec.mode == "dimensions" else None,
        dimension_unit=spec.dimension_unit if spec.mode == "dimensions" else None,
        is_deduction=spec.is_deduction,
        provenance=data.get("provenance", "user_entered"),
    )
    db.add(line)
    db.flush()
    _store(db, line, None, computed)
    before = item.quantity
    _refresh_item_quantity(db, item)
    _audit(
        db,
        ctx,
        scope,
        entity_type="measurement",
        entity_id=line.id,
        action="create",
        new={
            "item": str(item.id),
            "description": line.description,
            "quantity": _json(line.quantity),
            "calculation": computed[0].substituted,
        },
    )
    if before != item.quantity:
        _audit(
            db,
            ctx,
            scope,
            entity_type="boq_item",
            entity_id=item.id,
            action="recalculate",
            field_name="quantity",
            old=before,
            new=item.quantity,
        )
    _finish(db, commit)
    return scope


def _line(
    db: Session, ctx: AuthContext, line_id: uuid.UUID
) -> tuple[Measurement, BoqItem, VersionScope]:
    line = db.scalar(
        select(Measurement).where(
            Measurement.id == line_id, Measurement.organization_id == ctx.organization_id
        )
    )
    if line is None:
        raise AppError("NOT_FOUND", "Measurement line not found.", 404)
    item = db.get(BoqItem, line.boq_item_id)
    assert item is not None
    return line, item, _scope_for(db, ctx, line.version_id)


def update_line(
    db: Session, ctx: AuthContext, line_id: uuid.UUID, data: dict[str, Any]
) -> VersionScope:
    line, item, scope = _line(db, ctx, line_id)
    calc = db.scalar(select(Calculation).where(Calculation.estimate_item_id == line.id))
    spec = _line_spec(data, line, calc)
    try:
        computed = _compute(db, item, spec)
    except CalculationError as exc:
        raise _calculation_error(exc) from exc
    old = {
        "description": line.description,
        "quantity": _json(line.quantity),
        "calculation": calc.substituted if calc else None,
    }
    line.mode, line.description, line.nos, line.is_deduction = (
        spec.mode,
        spec.description,
        spec.nos,
        spec.is_deduction,
    )
    dims = spec.mode == "dimensions"
    line.length = spec.length if dims else None
    line.breadth = spec.breadth if dims else None
    line.depth_height = spec.depth_height if dims else None
    line.dimension_unit = spec.dimension_unit if dims else None
    _store(db, line, calc, computed)
    before = item.quantity
    _refresh_item_quantity(db, item)
    _audit(
        db,
        ctx,
        scope,
        entity_type="measurement",
        entity_id=line.id,
        action="update",
        old=old,
        new={
            "description": line.description,
            "quantity": _json(line.quantity),
            "calculation": computed[0].substituted,
        },
    )
    if before != item.quantity:
        _audit(
            db,
            ctx,
            scope,
            entity_type="boq_item",
            entity_id=item.id,
            action="recalculate",
            field_name="quantity",
            old=before,
            new=item.quantity,
        )
    db.commit()
    return scope


def delete_line(db: Session, ctx: AuthContext, line_id: uuid.UUID) -> VersionScope:
    line, item, scope = _line(db, ctx, line_id)
    _audit(
        db,
        ctx,
        scope,
        entity_type="measurement",
        entity_id=line.id,
        action="delete",
        old={"description": line.description, "quantity": _json(line.quantity)},
    )
    db.delete(line)
    before = item.quantity
    _refresh_item_quantity(db, item)
    if before != item.quantity:
        _audit(
            db,
            ctx,
            scope,
            entity_type="boq_item",
            entity_id=item.id,
            action="recalculate",
            field_name="quantity",
            old=before,
            new=item.quantity,
        )
    db.commit()
    return scope


def get_line_calculation(
    db: Session, ctx: AuthContext, line_id: uuid.UUID
) -> tuple[Measurement, Calculation]:
    line = db.scalar(
        select(Measurement).where(
            Measurement.id == line_id, Measurement.organization_id == ctx.organization_id
        )
    )
    if line is None:
        raise AppError("NOT_FOUND", "Measurement line not found.", 404)
    get_version(db, ctx, line.version_id)
    calc = db.scalar(select(Calculation).where(Calculation.estimate_item_id == line.id))
    if calc is None:
        raise AppError("NOT_FOUND", "This line has no calculation.", 404)
    return line, calc


# =============================================================================
# Parameters
# =============================================================================
def _param(
    db: Session, ctx: AuthContext, param_id: uuid.UUID
) -> tuple[QuantityInput, VersionScope]:
    param = db.scalar(
        select(QuantityInput).where(
            QuantityInput.id == param_id, QuantityInput.organization_id == ctx.organization_id
        )
    )
    if param is None:
        raise AppError("NOT_FOUND", "Parameter not found.", 404)
    return param, _scope_for(db, ctx, param.version_id)


def _dependent_lines(
    db: Session, version_id: uuid.UUID, name: str
) -> list[tuple[Measurement, Calculation]]:
    rows = db.execute(
        select(Measurement, Calculation)
        .join(Calculation, Calculation.estimate_item_id == Measurement.id)
        .where(Measurement.version_id == version_id, Measurement.mode == "formula")
    ).all()
    return [(m, c) for m, c in rows if name in set(_refs(c))]


def add_parameter(
    db: Session,
    ctx: AuthContext,
    version_id: uuid.UUID,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> VersionScope:
    scope = _scope_for(db, ctx, version_id)
    name = (data.get("name") or "").strip()
    if not PARAM_NAME.fullmatch(name):
        raise AppError(
            "VALIDATION_ERROR",
            "Name must start with a letter and use only lowercase letters, digits and _ "
            "(e.g. road_length).",
            details={"field": "name"},
        )
    label = (data.get("label") or "").strip() or name.replace("_", " ").capitalize()
    value = _decimal(data.get("value"), label)
    unit = _unit_code(data.get("unit"))
    if db.scalar(
        select(QuantityInput.id).where(
            QuantityInput.version_id == version_id, QuantityInput.name == name
        )
    ):
        raise AppError(
            "PARAMETER_EXISTS",
            f"A parameter named '{name}' already exists.",
            409,
            {"field": "name"},
        )
    param = QuantityInput(
        id=new_id(),
        organization_id=ctx.organization_id,
        version_id=version_id,
        line_key=new_id(),
        name=name,
        label=label[:200],
        value=value,
        unit_code=unit,
        provenance=data.get("provenance", "user_entered"),
        source_text=data.get("source_text"),
        confirmed_by=ctx.user.id if value is not None else None,
        confirmed_at=now_utc() if value is not None else None,
    )
    db.add(param)
    _audit(
        db,
        ctx,
        scope,
        entity_type="parameter",
        entity_id=param.id,
        action="create",
        new={"name": name, "value": _json(value), "unit": unit},
    )
    _finish(db, commit)
    return scope


@dataclass(frozen=True)
class ParameterUpdate:
    scope: VersionScope
    recalculated_lines: int
    affected_items: int


def update_parameter(
    db: Session, ctx: AuthContext, param_id: uuid.UUID, data: dict[str, Any]
) -> ParameterUpdate:
    param, scope = _param(db, ctx, param_id)
    if "label" in data:
        label = (data.get("label") or "").strip()
        if not label:
            raise AppError("VALIDATION_ERROR", "Label is required.", details={"field": "label"})
        _set(db, ctx, scope, param, "label", label[:200])
    changed = False
    if "value" in data:
        value = _decimal(data["value"], param.label)
        if value != param.value:
            _set(db, ctx, scope, param, "value", value)
            param.provenance = "user_entered"
            param.confirmed_by, param.confirmed_at = ctx.user.id, now_utc()
            changed = True
    if "unit" in data:
        unit = _unit_code(data["unit"])
        if unit != param.unit_code:
            _set(db, ctx, scope, param, "unit_code", unit)
            changed = True
    lines = _dependent_lines(db, param.version_id, param.name) if changed else []
    if lines and param.value is None:
        raise AppError(
            "PARAMETER_IN_USE",
            f"'{param.label}' is used by {len(lines)} measurement line(s) "
            "and cannot be left empty.",
            409,
        )
    items: dict[uuid.UUID, BoqItem] = {}
    db.flush()
    for line, calc in lines:
        item = items.setdefault(line.boq_item_id, db.get(BoqItem, line.boq_item_id))  # type: ignore[arg-type]
        try:
            _store(db, line, calc, _compute(db, item, _line_spec({}, line, calc)))
        except CalculationError as exc:
            raise _calculation_error(exc) from exc
    for item in items.values():
        before = item.quantity
        _refresh_item_quantity(db, item)
        if before != item.quantity:
            _audit(
                db,
                ctx,
                scope,
                entity_type="boq_item",
                entity_id=item.id,
                action="recalculate",
                field_name="quantity",
                old=before,
                new=item.quantity,
            )
    db.commit()
    return ParameterUpdate(scope, len(lines), len(items))


def delete_parameter(db: Session, ctx: AuthContext, param_id: uuid.UUID) -> VersionScope:
    param, scope = _param(db, ctx, param_id)
    used = _dependent_lines(db, param.version_id, param.name)
    if used:
        raise AppError(
            "PARAMETER_IN_USE",
            f"'{param.label}' is used by {len(used)} measurement line(s). "
            "Change those lines first.",
            409,
        )
    _audit(
        db,
        ctx,
        scope,
        entity_type="parameter",
        entity_id=param.id,
        action="delete",
        old={"name": param.name, "value": _json(param.value)},
    )
    db.execute(sa_delete(QuantityInput).where(QuantityInput.id == param.id))
    db.commit()
    return scope
