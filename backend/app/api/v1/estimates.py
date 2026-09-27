"""Estimates, versions, BOQ, measurement lines and parameters.

Every change returns the whole recalculated version, so the client always shows the
server's numbers and never does estimate arithmetic itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import DB, Auth
from app.api.envelope import Envelope, ok
from app.domain.money import amount_in_words, format_inr
from app.domain.numeric import round_half_up
from app.domain.units import default_registry
from app.models import Calculation, Project, User
from app.services import abstract as abstract_service
from app.services import estimates as service
from app.services.context import AuthContext
from app.services.projects import ROLE_RANK

router = APIRouter(tags=["estimates"])

Number = str | int | float | None


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _qty(value: Decimal | None, unit_code: str | None) -> str | None:
    """Quantities are shown to the precision of their unit (Cum 3, Sq.m 2, Nos 0)."""
    if value is None:
        return None
    places = default_registry().get(unit_code).decimal_places if unit_code else 3
    return format(round_half_up(value, places), "f")


# ================================================================== schemas
class EstimateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    estimate_number: str | None = Field(default=None, max_length=50)
    prepared_by: str | None = Field(default=None, max_length=120)
    checked_by: str | None = Field(default=None, max_length=120)
    approved_by: str | None = Field(default=None, max_length=120)


class EstimatePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    estimate_number: str | None = Field(default=None, min_length=1, max_length=50)
    prepared_by: str | None = Field(default=None, max_length=120)
    checked_by: str | None = Field(default=None, max_length=120)
    approved_by: str | None = Field(default=None, max_length=120)


class EstimateOut(BaseModel):
    id: uuid.UUID
    estimate_number: str
    title: str
    project_id: uuid.UUID
    project_name: str
    prepared_by: str | None
    checked_by: str | None
    approved_by: str | None
    draft_version_id: uuid.UUID
    draft_version_no: int
    version_count: int
    works_subtotal: str
    works_subtotal_display: str
    item_count: int
    created_at: datetime
    updated_at: datetime


class VersionSummaryOut(BaseModel):
    id: uuid.UUID
    version_no: int
    status: str
    change_note: str | None
    frozen_at: datetime | None
    created_at: datetime
    works_subtotal: str
    works_subtotal_display: str


class LineCalculationOut(BaseModel):
    template_id: str | None
    template_version: int | None
    expression: str
    substituted: str
    inputs: dict[str, Any]
    steps: list[dict[str, str]]
    result: str
    result_unit: str
    engine_version: str
    calculated_at: datetime


class LineOut(BaseModel):
    id: uuid.UUID
    line_key: uuid.UUID
    sequence: int
    mode: str
    description: str
    nos: str
    length: str | None
    breadth: str | None
    depth_height: str | None
    dimension_unit: str | None
    quantity: str | None
    is_deduction: bool
    provenance: str
    calculation: LineCalculationOut | None


class RateInfoOut(BaseModel):
    rate_item_id: uuid.UUID | None
    item_code: str
    sor_name: str
    year: str
    unit: str
    basic_rate: str
    verification_status: str
    is_demo: bool
    label: str


class ItemOut(BaseModel):
    id: uuid.UUID
    line_key: uuid.UUID
    section_id: uuid.UUID
    sl_no: str
    item_no: str | None
    item_no_display: str
    description: str
    specification: str | None
    unit: str | None
    unit_display: str | None
    quantity: str | None
    quantity_source: str
    rate: str | None
    rate_source_type: str | None
    rate_info: RateInfoOut | None
    amount: str | None
    remarks: str | None
    provenance: str
    lines: list[LineOut]


class SectionOut(BaseModel):
    id: uuid.UUID
    line_key: uuid.UUID
    sl_no: int
    title: str
    subtotal: str
    subtotal_display: str
    item_count: int
    unpriced_count: int
    items: list[ItemOut]


class ParameterOut(BaseModel):
    id: uuid.UUID
    name: str
    label: str
    value: str | None
    unit: str | None
    unit_display: str | None
    provenance: str
    source_text: str | None
    used_by: int


class TotalsOut(BaseModel):
    works_subtotal: str
    works_subtotal_display: str
    amount_in_words: str
    grand_total: str
    grand_total_display: str
    grand_total_in_words: str
    item_count: int
    unpriced_count: int


class VersionInfo(BaseModel):
    id: uuid.UUID
    version_no: int
    status: str
    change_note: str | None
    frozen_at: datetime | None
    frozen_by_name: str | None
    engine_version: str | None
    created_at: datetime


class EstimateRef(BaseModel):
    id: uuid.UUID
    estimate_number: str
    title: str
    project_id: uuid.UUID
    project_name: str


class VersionOut(BaseModel):
    version: VersionInfo
    estimate: EstimateRef
    my_role: str
    can_edit: bool
    sections: list[SectionOut]
    parameters: list[ParameterOut]
    totals: TotalsOut
    notice: str | None = None
    focus_id: uuid.UUID | None = None


class FreezeIn(BaseModel):
    change_note: str = Field(min_length=1, max_length=300)


class TitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class OrderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)


class ItemOrderIn(OrderIn):
    section_id: uuid.UUID


class ItemCreate(BaseModel):
    section_id: uuid.UUID
    item_no: str | None = Field(default=None, max_length=50)
    description: str = Field(min_length=1, max_length=5000)
    specification: str | None = Field(default=None, max_length=5000)
    unit: str | None = Field(default=None, max_length=40)
    quantity: Number = None
    rate: Number = None
    remarks: str | None = Field(default=None, max_length=1000)


class ItemPatch(BaseModel):
    section_id: uuid.UUID | None = None
    item_no: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    specification: str | None = Field(default=None, max_length=5000)
    unit: str | None = Field(default=None, max_length=40)
    quantity: Number = None
    rate: Number = None
    remarks: str | None = Field(default=None, max_length=1000)


class SetRateIn(BaseModel):
    rate_item_id: uuid.UUID
    confirm_overwrite: bool = False


class FormulaInput(BaseModel):
    value: Number = None
    unit: str | None = Field(default=None, max_length=40)
    ref: str | None = Field(default=None, max_length=63)


class LineIn(BaseModel):
    mode: Literal["dimensions", "formula"] | None = None
    description: str | None = Field(default=None, max_length=500)
    is_deduction: bool | None = None
    nos: Number = None
    length: Number = None
    breadth: Number = None
    depth_height: Number = None
    dimension_unit: str | None = Field(default=None, max_length=40)
    template_id: str | None = Field(default=None, max_length=64)
    expression: str | None = Field(default=None, max_length=500)
    inputs: dict[str, FormulaInput] | None = Field(default=None, max_length=30)


class ParameterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    label: str | None = Field(default=None, max_length=200)
    value: Number = None
    unit: str | None = Field(default=None, max_length=40)


class ParameterPatch(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    value: Number = None
    unit: str | None = Field(default=None, max_length=40)


# ================================================================ builders
def estimate_out(summary: service.EstimateSummary) -> EstimateOut:
    e = summary.estimate
    return EstimateOut(
        id=e.id,
        estimate_number=e.estimate_number,
        title=e.title,
        project_id=e.project_id,
        project_name=summary.project_name,
        prepared_by=e.prepared_by,
        checked_by=e.checked_by,
        approved_by=e.approved_by,
        draft_version_id=summary.draft_version_id,
        draft_version_no=summary.draft_version_no,
        version_count=summary.version_count,
        works_subtotal=format(summary.works_subtotal, "f"),
        works_subtotal_display=format_inr(summary.works_subtotal),
        item_count=summary.item_count,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def _calc_out(c: Calculation | None) -> LineCalculationOut | None:
    if c is None:
        return None
    return LineCalculationOut(
        template_id=c.template_id,
        template_version=c.template_version,
        expression=c.expression,
        substituted=c.substituted,
        inputs=c.input_parameters,
        steps=c.steps,
        result=format(c.result_raw.normalize(), "f"),
        result_unit=c.result_unit,
        engine_version=c.engine_version,
        calculated_at=c.calculated_at,
    )


def rate_info(i: Any) -> RateInfoOut | None:
    snap = i.rate_snapshot
    if i.rate_source_type != "rate_database" or not snap:
        return None
    demo = snap.get("verification_status") == "demo"
    return RateInfoOut(
        rate_item_id=i.rate_item_id,
        item_code=snap.get("item_code", ""),
        sor_name=snap.get("sor_name", ""),
        year=snap.get("year", ""),
        unit=snap.get("unit", ""),
        basic_rate=snap.get("basic_rate", ""),
        verification_status=snap.get("verification_status", ""),
        is_demo=demo,
        label=f"{snap.get('item_code', '')} · {snap.get('sor_name', '')} {snap.get('year', '')}",
    )


def _grand_total(db: Session, view: service.VersionView) -> Decimal:
    snap = view.version.totals_snapshot
    if view.version.status == "frozen" and snap and "grand_total" in snap:
        return Decimal(snap["grand_total"])
    result, _ = abstract_service.compute(view, abstract_service.charges_of(db, view.version.id))
    return result.grand_total


def version_out(
    db: Session,
    ctx: AuthContext,
    scope: service.VersionScope,
    *,
    notice: str | None = None,
    focus_id: uuid.UUID | None = None,
) -> VersionOut:
    view = service.load_version(db, scope)
    registry = default_registry()
    units = {u.code: u.display_name for u in registry.units}
    v = view.version
    frozen_by = db.get(User, v.frozen_by) if v.frozen_by else None
    project = db.get(Project, scope.estimate.project_id)
    can_edit = v.status == "draft" and ROLE_RANK[scope.access.role] >= ROLE_RANK["professional"]

    sections = []
    for sv in view.sections:
        items = []
        for iv in sv.items:
            i = iv.item
            items.append(
                ItemOut(
                    id=i.id,
                    line_key=i.line_key,
                    section_id=i.section_id,
                    sl_no=iv.sl_no,
                    item_no=i.item_no,
                    item_no_display=i.item_no or iv.sl_no,
                    description=i.description,
                    specification=i.specification,
                    unit=i.unit_code,
                    unit_display=units.get(i.unit_code) if i.unit_code else None,
                    quantity=_qty(i.quantity, i.unit_code),
                    quantity_source=i.quantity_source,
                    rate=_s(i.rate),
                    rate_source_type=i.rate_source_type,
                    rate_info=rate_info(i),
                    amount=_s(i.amount),
                    remarks=i.remarks,
                    provenance=i.provenance,
                    lines=[
                        LineOut(
                            id=lv.line.id,
                            line_key=lv.line.line_key,
                            sequence=lv.line.sequence,
                            mode=lv.line.mode,
                            description=lv.line.description,
                            nos=format(lv.line.nos.normalize(), "f"),
                            length=_s(
                                lv.line.length.normalize() if lv.line.length is not None else None
                            ),
                            breadth=_s(
                                lv.line.breadth.normalize() if lv.line.breadth is not None else None
                            ),
                            depth_height=_s(
                                lv.line.depth_height.normalize()
                                if lv.line.depth_height is not None
                                else None
                            ),
                            dimension_unit=lv.line.dimension_unit,
                            quantity=_qty(lv.line.quantity, i.unit_code),
                            is_deduction=lv.line.is_deduction,
                            provenance=lv.line.provenance,
                            calculation=_calc_out(lv.calculation),
                        )
                        for lv in iv.lines
                    ],
                )
            )
        sections.append(
            SectionOut(
                id=sv.section.id,
                line_key=sv.section.line_key,
                sl_no=sv.sl_no,
                title=sv.section.title,
                subtotal=format(sv.total.subtotal, "f"),
                subtotal_display=format_inr(sv.total.subtotal),
                item_count=sv.total.item_count,
                unpriced_count=sv.total.item_count - sv.total.priced_count,
                items=items,
            )
        )
    total = view.display_total
    grand = _grand_total(db, view)
    return VersionOut(
        version=VersionInfo(
            id=v.id,
            version_no=v.version_no,
            status=v.status,
            change_note=v.change_note,
            frozen_at=v.frozen_at,
            frozen_by_name=frozen_by.full_name if frozen_by else None,
            engine_version=v.engine_version,
            created_at=v.created_at,
        ),
        estimate=EstimateRef(
            id=scope.estimate.id,
            estimate_number=scope.estimate.estimate_number,
            title=scope.estimate.title,
            project_id=scope.estimate.project_id,
            project_name=project.name if project else "",
        ),
        my_role=scope.access.role,
        can_edit=can_edit,
        sections=sections,
        parameters=[
            ParameterOut(
                id=p.id,
                name=p.name,
                label=p.label,
                value=_s(p.value.normalize() if p.value is not None else None),
                unit=p.unit_code,
                unit_display=units.get(p.unit_code) if p.unit_code else None,
                provenance=p.provenance,
                source_text=p.source_text,
                used_by=view.parameter_usage.get(p.name, 0),
            )
            for p in view.parameters
        ],
        totals=TotalsOut(
            works_subtotal=format(total, "f"),
            works_subtotal_display=format_inr(total),
            amount_in_words=view.words,
            grand_total=format(grand, "f"),
            grand_total_display=format_inr(grand),
            grand_total_in_words=amount_in_words(grand) if grand >= 0 else "",
            item_count=view.item_count,
            unpriced_count=view.unpriced_count,
        ),
        notice=notice,
        focus_id=focus_id,
    )


def _reload(
    db: Session, auth: AuthContext, scope: service.VersionScope, **kw: Any
) -> Envelope[VersionOut]:
    # Re-read with the caller's current role (the scope used for the write had it too).
    fresh = service.get_version(db, auth, scope.version.id)
    return ok(version_out(db, auth, fresh, **kw))


def _changes(model: BaseModel) -> dict[str, Any]:
    return {name: getattr(model, name) for name in model.model_fields_set}


# ================================================================ estimates
@router.get("/projects/{project_id}/estimates", response_model=Envelope[list[EstimateOut]])
def list_project_estimates(
    project_id: uuid.UUID, auth: Auth, db: DB
) -> Envelope[list[EstimateOut]]:
    return ok([estimate_out(s) for s in service.list_for_project(db, auth, project_id)])


@router.post(
    "/projects/{project_id}/estimates", response_model=Envelope[EstimateOut], status_code=201
)
def create_estimate(
    project_id: uuid.UUID, body: EstimateCreate, auth: Auth, db: DB
) -> Envelope[EstimateOut]:
    estimate = service.create_estimate(db, auth, project_id, body.model_dump())
    return ok(estimate_out(service.summaries(db, [estimate])[0]))


@router.get("/estimates", response_model=Envelope[list[EstimateOut]])
def recent_estimates(
    auth: Auth, db: DB, limit: int = Query(default=10, ge=1, le=50)
) -> Envelope[list[EstimateOut]]:
    return ok([estimate_out(s) for s in service.list_recent(db, auth, limit)])


@router.get("/estimates/{estimate_id}", response_model=Envelope[EstimateOut])
def get_estimate(estimate_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[EstimateOut]:
    estimate, _ = service.get_estimate(db, auth, estimate_id)
    return ok(estimate_out(service.summaries(db, [estimate])[0]))


@router.patch("/estimates/{estimate_id}", response_model=Envelope[EstimateOut])
def patch_estimate(
    estimate_id: uuid.UUID, body: EstimatePatch, auth: Auth, db: DB
) -> Envelope[EstimateOut]:
    changes = {
        k: v
        for k, v in _changes(body).items()
        if not (k in ("title", "estimate_number") and v is None)
    }
    for key in ("title", "estimate_number"):
        if key in changes and isinstance(changes[key], str):
            changes[key] = changes[key].strip()
    estimate = service.update_estimate(db, auth, estimate_id, changes)
    return ok(estimate_out(service.summaries(db, [estimate])[0]))


@router.delete("/estimates/{estimate_id}", response_model=Envelope[dict[str, bool]])
def delete_estimate(estimate_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[dict[str, bool]]:
    service.delete_estimate(db, auth, estimate_id)
    return ok({"deleted": True})


@router.get("/estimates/{estimate_id}/versions", response_model=Envelope[list[VersionSummaryOut]])
def list_versions(estimate_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[list[VersionSummaryOut]]:
    return ok(
        [
            VersionSummaryOut(
                id=row["version"].id,
                version_no=row["version"].version_no,
                status=row["version"].status,
                change_note=row["version"].change_note,
                frozen_at=row["version"].frozen_at,
                created_at=row["version"].created_at,
                works_subtotal=format(row["works_subtotal"], "f"),
                works_subtotal_display=format_inr(row["works_subtotal"]),
            )
            for row in service.list_versions(db, auth, estimate_id)
        ]
    )


# ================================================================= versions
@router.get("/versions/{version_id}", response_model=Envelope[VersionOut])
def get_version(version_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return ok(version_out(db, auth, service.get_version(db, auth, version_id)))


@router.post("/versions/{version_id}/freeze", response_model=Envelope[VersionOut])
def freeze_version(
    version_id: uuid.UUID, body: FreezeIn, auth: Auth, db: DB
) -> Envelope[VersionOut]:
    draft = service.freeze(db, auth, version_id, body.change_note)
    scope = service.get_version(db, auth, draft.id)
    return ok(
        version_out(
            db,
            auth,
            scope,
            notice=f"V{draft.version_no - 1} saved. You are now editing V{draft.version_no}.",
        )
    )


# ================================================================= sections
@router.post("/versions/{version_id}/sections", response_model=Envelope[VersionOut])
def add_section(version_id: uuid.UUID, body: TitleIn, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.add_section(db, auth, version_id, body.title))


@router.patch("/sections/{section_id}", response_model=Envelope[VersionOut])
def rename_section(
    section_id: uuid.UUID, body: TitleIn, auth: Auth, db: DB
) -> Envelope[VersionOut]:
    return _reload(db, auth, service.rename_section(db, auth, section_id, body.title))


@router.delete("/sections/{section_id}", response_model=Envelope[VersionOut])
def delete_section(section_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.delete_section(db, auth, section_id))


@router.post("/versions/{version_id}/sections/reorder", response_model=Envelope[VersionOut])
def reorder_sections(
    version_id: uuid.UUID, body: OrderIn, auth: Auth, db: DB
) -> Envelope[VersionOut]:
    return _reload(db, auth, service.reorder_sections(db, auth, version_id, body.ids))


# ================================================================ BOQ items
@router.post(
    "/versions/{version_id}/boq-items", response_model=Envelope[VersionOut], status_code=201
)
def add_item(version_id: uuid.UUID, body: ItemCreate, auth: Auth, db: DB) -> Envelope[VersionOut]:
    scope, item = service.add_item(db, auth, version_id, body.model_dump())
    return _reload(db, auth, scope, focus_id=item.id)


@router.patch("/boq-items/{item_id}", response_model=Envelope[VersionOut])
def patch_item(item_id: uuid.UUID, body: ItemPatch, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.update_item(db, auth, item_id, _changes(body)))


@router.delete("/boq-items/{item_id}", response_model=Envelope[VersionOut])
def delete_item(item_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.delete_item(db, auth, item_id))


@router.post("/boq-items/{item_id}/set-rate", response_model=Envelope[VersionOut])
def set_rate(item_id: uuid.UUID, body: SetRateIn, auth: Auth, db: DB) -> Envelope[VersionOut]:
    scope = service.set_rate(
        db, auth, item_id, body.rate_item_id, confirm_overwrite=body.confirm_overwrite
    )
    return _reload(db, auth, scope, focus_id=item_id)


@router.post("/boq-items/{item_id}/duplicate", response_model=Envelope[VersionOut])
def duplicate_item(item_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.duplicate_item(db, auth, item_id))


@router.post("/versions/{version_id}/boq-items/reorder", response_model=Envelope[VersionOut])
def reorder_items(
    version_id: uuid.UUID, body: ItemOrderIn, auth: Auth, db: DB
) -> Envelope[VersionOut]:
    return _reload(db, auth, service.reorder_items(db, auth, version_id, body.section_id, body.ids))


# ======================================================== measurement lines
def _line_data(body: LineIn) -> dict[str, Any]:
    data = _changes(body)
    if "inputs" in data and data["inputs"] is not None:
        data["inputs"] = {k: v.model_dump(exclude_none=True) for k, v in data["inputs"].items()}
    return data


@router.post(
    "/boq-items/{item_id}/measurements", response_model=Envelope[VersionOut], status_code=201
)
def add_line(item_id: uuid.UUID, body: LineIn, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.add_line(db, auth, item_id, _line_data(body)))


@router.patch("/measurements/{line_id}", response_model=Envelope[VersionOut])
def patch_line(line_id: uuid.UUID, body: LineIn, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.update_line(db, auth, line_id, _line_data(body)))


@router.delete("/measurements/{line_id}", response_model=Envelope[VersionOut])
def delete_line(line_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.delete_line(db, auth, line_id))


@router.get("/measurements/{line_id}/calculation", response_model=Envelope[LineCalculationOut])
def line_calculation(line_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[LineCalculationOut]:
    _, calc = service.get_line_calculation(db, auth, line_id)
    out = _calc_out(calc)
    assert out is not None
    return ok(out)


# =============================================================== parameters
@router.post(
    "/versions/{version_id}/parameters", response_model=Envelope[VersionOut], status_code=201
)
def add_parameter(
    version_id: uuid.UUID, body: ParameterCreate, auth: Auth, db: DB
) -> Envelope[VersionOut]:
    return _reload(db, auth, service.add_parameter(db, auth, version_id, body.model_dump()))


@router.patch("/parameters/{param_id}", response_model=Envelope[VersionOut])
def patch_parameter(
    param_id: uuid.UUID, body: ParameterPatch, auth: Auth, db: DB
) -> Envelope[VersionOut]:
    result = service.update_parameter(db, auth, param_id, _changes(body))
    notice = None
    if result.recalculated_lines:
        notice = (
            f"Recalculated {result.recalculated_lines} measurement line(s) in "
            f"{result.affected_items} item(s)."
        )
    return _reload(db, auth, result.scope, notice=notice)


@router.delete("/parameters/{param_id}", response_model=Envelope[VersionOut])
def delete_parameter(param_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[VersionOut]:
    return _reload(db, auth, service.delete_parameter(db, auth, param_id))
