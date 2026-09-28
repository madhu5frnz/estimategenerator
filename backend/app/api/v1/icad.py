"""Telangana I&CAD method: settings, data sheets, lead statement, seigniorage, General
Abstract. Every change returns the recalculated view it belongs to."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DB, Auth
from app.api.envelope import Envelope, ok
from app.core.errors import AppError
from app.domain.icad.rate_analysis import DataResult
from app.domain.money import amount_in_words, format_inr
from app.models import RateItem
from app.services import estimates as es
from app.services import icad as service
from app.services.context import AuthContext
from app.services.projects import ROLE_RANK

router = APIRouter(tags=["icad"])
Number = str | int | float | None


def _s(value: Decimal | None, places: str | None = None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(places)) if places else value, "f")


def _can_edit(scope: es.VersionScope) -> bool:
    return (
        scope.version.status == "draft"
        and ROLE_RANK[scope.access.role] >= ROLE_RANK["professional"]
    )


# ================================================================ settings
class SettingsOut(BaseModel):
    version_id: uuid.UUID
    can_edit: bool
    config: dict[str, Any]
    zones: list[str]
    material_classes: dict[str, str]
    seigniorage_materials: dict[str, str]
    seigniorage_note: str
    area_allowances: list[dict[str, str]]


class SettingsIn(BaseModel):
    zone: Literal["I", "II", "III"] | None = None
    area_allowance: str | None = None
    abstract: dict[str, Any] | None = None
    seigniorage: dict[str, Any] | None = None


def settings_out(scope: es.VersionScope) -> SettingsOut:
    basic = service.basic_rates()
    classes = basic["lead"]["mechanical_classes"]
    return SettingsOut(
        version_id=scope.version.id,
        can_edit=_can_edit(scope),
        config=service.config_of(scope.version),
        zones=list(service.ZONES),
        material_classes={k: classes[k] for k in service.MATERIAL_CLASSES},
        seigniorage_materials={
            k: v["label"] for k, v in basic["seigniorage_defaults"]["rates"].items()
        },
        seigniorage_note=basic["seigniorage_defaults"]["status"],
        area_allowances=basic["area_allowances"],
    )


@router.get("/versions/{version_id}/method-settings", response_model=Envelope[SettingsOut])
def get_settings(version_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[SettingsOut]:
    return ok(settings_out(es.get_version(db, auth, version_id)))


@router.patch("/versions/{version_id}/method-settings", response_model=Envelope[SettingsOut])
def patch_settings(
    version_id: uuid.UUID, body: SettingsIn, auth: Auth, db: DB
) -> Envelope[SettingsOut]:
    changes = {k: getattr(body, k) for k in body.model_fields_set if getattr(body, k) is not None}
    service.update_config(db, auth, version_id, changes)
    return ok(settings_out(es.get_version(db, auth, version_id)))


# ============================================================ lead statement
class LeadOut(BaseModel):
    id: uuid.UUID
    line_key: uuid.UUID
    sequence: int
    material: str
    source: str | None
    unit: str
    material_class: str
    distance_km: str | None
    initial_km: int
    manual_amount: str | None
    note: str | None
    amount: str
    working: str
    problem: str | None


class LeadStatementOut(BaseModel):
    version_id: uuid.UUID
    zone: str
    can_edit: bool
    entries: list[LeadOut]


class LeadIn(BaseModel):
    material: str | None = Field(default=None, max_length=120)
    source: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=20)
    material_class: Literal["earth_sand", "aggregate_stone", "cement_steel"] | None = None
    distance_km: Number = None
    initial_km: int | None = None
    manual_amount: Number = None
    note: str | None = Field(default=None, max_length=500)


def lead_out(db: DB, auth: AuthContext, version_id: uuid.UUID) -> LeadStatementOut:
    scope = es.get_version(db, auth, version_id)
    return LeadStatementOut(
        version_id=version_id,
        zone=service.config_of(scope.version)["zone"],
        can_edit=_can_edit(scope),
        entries=[
            LeadOut(
                id=v.entry.id,
                line_key=v.entry.line_key,
                sequence=v.entry.sequence,
                material=v.entry.material,
                source=v.entry.source,
                unit=v.entry.unit,
                material_class=v.entry.material_class,
                distance_km=_s(v.entry.distance_km),
                initial_km=v.entry.initial_km,
                manual_amount=_s(v.entry.manual_amount),
                note=v.entry.note,
                amount=_s(v.amount, "0.01") or "0.00",
                working=v.working,
                problem=v.problem,
            )
            for v in service.lead_statement(db, scope.version)
        ],
    )


def _fields(body: BaseModel) -> dict[str, Any]:
    return {k: getattr(body, k) for k in body.model_fields_set}


@router.get("/versions/{version_id}/lead-statement", response_model=Envelope[LeadStatementOut])
def get_lead(version_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[LeadStatementOut]:
    return ok(lead_out(db, auth, version_id))


@router.post(
    "/versions/{version_id}/lead-entries",
    response_model=Envelope[LeadStatementOut],
    status_code=201,
)
def add_lead(version_id: uuid.UUID, body: LeadIn, auth: Auth, db: DB) -> Envelope[LeadStatementOut]:
    service.add_lead(db, auth, version_id, _fields(body))
    return ok(lead_out(db, auth, version_id))


@router.patch("/lead-entries/{entry_id}", response_model=Envelope[LeadStatementOut])
def patch_lead(entry_id: uuid.UUID, body: LeadIn, auth: Auth, db: DB) -> Envelope[LeadStatementOut]:
    scope = service.update_lead(db, auth, entry_id, _fields(body))
    return ok(lead_out(db, auth, scope.version.id))


@router.delete("/lead-entries/{entry_id}", response_model=Envelope[LeadStatementOut])
def delete_lead(entry_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[LeadStatementOut]:
    scope = service.delete_lead(db, auth, entry_id)
    return ok(lead_out(db, auth, scope.version.id))


# ============================================================== data sheets
class AnalysisRowOut(BaseModel):
    index: int
    section: str
    description: str
    unit: str
    quantity: str | None
    rate: str | None
    pct: str | None
    amount: str
    deleted: bool


class AmountLineOut(BaseModel):
    description: str
    pct: str | None = None
    quantity: str | None = None
    rate: str | None = None
    amount: str
    kind: str | None = None
    lead_key: str | None = None


class AnalysisOut(BaseModel):
    item_id: uuid.UUID
    item_description: str
    item_unit: str | None
    item_rate: str | None
    has_analysis: bool
    can_edit: bool
    code: str | None = None
    status: str | None = None
    book_rate: str | None = None
    book_status: str | None = None
    book_note: str | None = None
    analysis_qty: str | None = None
    analysis_unit: str | None = None
    rows: list[AnalysisRowOut] = []
    materials: str | None = None
    machinery: str | None = None
    labour: str | None = None
    additions: list[AmountLineOut] = []
    ohp_pct: str | None = None
    ohp: str | None = None
    extras: list[AmountLineOut] = []
    total: str | None = None
    rate_before_adjustments: str | None = None
    adjustments: list[AmountLineOut] = []
    rate_exact: str | None = None
    rate: str | None = None
    labour_per_unit: str | None = None
    labour_per_unit_with_ohp: str | None = None
    raw: dict[str, Any] | None = None
    lead_options: list[dict[str, str]] = []


class AnalysisIn(BaseModel):
    rows: list[dict[str, Any]] | None = Field(default=None, max_length=400)
    deleted_rows: list[int] | None = Field(default=None, max_length=400)
    adjustments: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    additions: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    or_say_step: str | None = None


def analysis_out(db: DB, auth: AuthContext, item_id: uuid.UUID) -> AnalysisOut:
    item, analysis, scope = service.get_analysis(db, auth, item_id)
    book = db.get(RateItem, item.rate_item_id) if item.rate_item_id else None
    leads = service.lead_statement(db, scope.version)
    base = AnalysisOut(
        item_id=item.id,
        item_description=item.description,
        item_unit=item.unit_code,
        item_rate=_s(item.rate),
        has_analysis=analysis is not None,
        can_edit=_can_edit(scope),
        book_rate=_s(book.basic_rate) if book else None,
        book_status=book.analysis_status if book else None,
        book_note=book.analysis_note if book else None,
        code=book.item_code if book else None,
        lead_options=[
            {
                "lead_key": str(v.entry.line_key),
                "label": v.entry.material,
                "amount": _s(v.amount, "0.01") or "0",
            }
            for v in leads
        ],
    )
    if analysis is None:
        return base
    lookup = {str(v.entry.line_key): v.amount for v in leads}
    r: DataResult = service.evaluate(analysis, item.description, lookup)
    data = analysis.analysis
    adjustments = []
    for spec, (adj, amount) in zip(data.get("adjustments", []), r.adjustments, strict=True):
        adjustments.append(
            AmountLineOut(
                description=adj.description,
                quantity=_s(adj.quantity),
                rate=_s(adj.rate),
                amount=_s(amount) or "0",
                kind=spec.get("kind"),
                lead_key=spec.get("lead_key"),
            )
        )
    return base.model_copy(
        update={
            "code": analysis.code,
            "status": analysis.status,
            "analysis_qty": str(data.get("analysis_qty")),
            "analysis_unit": data.get("unit"),
            "rows": [
                AnalysisRowOut(
                    index=x.index,
                    section=x.row.section,
                    description=x.row.description,
                    unit=x.row.unit,
                    quantity=_s(x.row.quantity),
                    rate=_s(x.row.rate),
                    pct=_s(x.row.pct),
                    amount=_s(x.amount) or "0",
                    deleted=x.deleted,
                )
                for x in r.rows
            ],
            "materials": _s(r.materials),
            "machinery": _s(r.machinery),
            "labour": _s(r.labour),
            "additions": [
                AmountLineOut(description=a.description, pct=_s(a.pct), amount=_s(v) or "0")
                for a, v in r.additions
            ],
            "ohp_pct": str(data.get("ohp_pct", "13.615")),
            "ohp": _s(r.ohp),
            "extras": [
                AmountLineOut(description=e["description"], amount=e["amount"])
                for e in data.get("extras", [])
            ],
            "total": _s(r.total, "0.01"),
            "rate_before_adjustments": _s(r.rate_before_adjustments, "0.01"),
            "adjustments": adjustments,
            "rate_exact": _s(r.rate_exact, "0.01"),
            "rate": _s(r.rate),
            "labour_per_unit": _s(r.labour_per_unit),
            "labour_per_unit_with_ohp": _s(r.labour_per_unit_with_ohp),
            "raw": data,
        }
    )


@router.get("/boq-items/{item_id}/analysis", response_model=Envelope[AnalysisOut])
def get_analysis(item_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[AnalysisOut]:
    return ok(analysis_out(db, auth, item_id))


@router.patch("/boq-items/{item_id}/analysis", response_model=Envelope[AnalysisOut])
def patch_analysis(
    item_id: uuid.UUID, body: AnalysisIn, auth: Auth, db: DB
) -> Envelope[AnalysisOut]:
    service.update_analysis(
        db, auth, item_id, {k: v for k, v in _fields(body).items() if v is not None}
    )
    return ok(analysis_out(db, auth, item_id))


@router.post("/boq-items/{item_id}/analysis/auto-conveyance", response_model=Envelope[AnalysisOut])
def auto_conveyance(item_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[AnalysisOut]:
    service.auto_conveyance(db, auth, item_id)
    return ok(analysis_out(db, auth, item_id))


# =============================================================== seigniorage
class SeigLineOut(BaseModel):
    id: uuid.UUID
    label: str
    material: str
    boq_item_line_key: uuid.UUID | None
    item_quantity: str
    follows_item: bool
    factor: str
    material_quantity: str
    rate: str
    amount: str


class SeigniorageOut(BaseModel):
    version_id: uuid.UUID
    can_edit: bool
    lines: list[SeigLineOut]
    by_material: dict[str, str]
    total: str
    dmf: str
    smet: str
    permit_fee: str
    settings: dict[str, Any]
    note: str


class SeigIn(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    material: str | None = Field(default=None, max_length=20)
    boq_item_line_key: uuid.UUID | None = None
    item_quantity: Number = None
    factor: Number = None
    rate: Number = None


def seig_out(db: DB, auth: AuthContext, version_id: uuid.UUID) -> SeigniorageOut:
    scope = es.get_version(db, auth, version_id)
    rows, result = service.seigniorage(db, scope.version)
    return SeigniorageOut(
        version_id=version_id,
        can_edit=_can_edit(scope),
        lines=[
            SeigLineOut(
                id=line.id,
                label=line.label,
                material=line.material,
                boq_item_line_key=line.boq_item_line_key,
                item_quantity=_s(qty) or "0",
                follows_item=line.boq_item_line_key is not None,
                factor=_s(line.factor.normalize()) or "0",
                material_quantity=_s(mq, "0.001") or "0",
                rate=_s(line.rate) or "0",
                amount=_s(amount) or "0",
            )
            for (line, qty), (_, mq, amount) in zip(rows, result.lines, strict=True)
        ],
        by_material={k: _s(v) or "0" for k, v in result.by_material.items()},
        total=_s(result.total) or "0",
        dmf=_s(result.dmf) or "0",
        smet=_s(result.smet) or "0",
        permit_fee=_s(result.permit_fee, "0.01") or "0",
        settings=service.config_of(scope.version)["seigniorage"],
        note=service.basic_rates()["seigniorage_defaults"]["status"],
    )


@router.get("/versions/{version_id}/seigniorage", response_model=Envelope[SeigniorageOut])
def get_seigniorage(version_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[SeigniorageOut]:
    return ok(seig_out(db, auth, version_id))


@router.post(
    "/versions/{version_id}/seigniorage-lines",
    response_model=Envelope[SeigniorageOut],
    status_code=201,
)
def add_seig(version_id: uuid.UUID, body: SeigIn, auth: Auth, db: DB) -> Envelope[SeigniorageOut]:
    service.add_seigniorage_line(db, auth, version_id, _fields(body))
    return ok(seig_out(db, auth, version_id))


@router.post("/versions/{version_id}/seigniorage/suggest", response_model=Envelope[SeigniorageOut])
def suggest_seig(version_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[SeigniorageOut]:
    service.suggest_seigniorage(db, auth, version_id)
    return ok(seig_out(db, auth, version_id))


@router.patch("/seigniorage-lines/{line_id}", response_model=Envelope[SeigniorageOut])
def patch_seig(line_id: uuid.UUID, body: SeigIn, auth: Auth, db: DB) -> Envelope[SeigniorageOut]:
    scope = service.update_seigniorage_line(db, auth, line_id, _fields(body))
    return ok(seig_out(db, auth, scope.version.id))


@router.delete("/seigniorage-lines/{line_id}", response_model=Envelope[SeigniorageOut])
def delete_seig(line_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[SeigniorageOut]:
    scope = service.delete_seigniorage_line(db, auth, line_id)
    return ok(seig_out(db, auth, scope.version.id))


# ========================================================== general abstract
class GaItemOut(BaseModel):
    sl_no: str
    item_id: uuid.UUID
    code: str
    description: str
    quantity: str | None
    rate: str | None
    unit: str | None
    amount: str
    has_analysis: bool


class GaLineOut(BaseModel):
    label: str
    amount: str
    amount_display: str


class GeneralAbstractOut(BaseModel):
    version_id: uuid.UUID
    can_edit: bool
    items: list[GaItemOut]
    ecv: str
    ecv_display: str
    part_b: list[GaLineOut]
    part_b_total: str
    subtotal: str
    subtotal_display: str
    gst_pct: str
    gst: str
    gst_display: str
    after_gst: list[GaLineOut]
    rounding_off: str
    total: str
    total_display: str
    total_in_lakhs: str
    amount_in_words: str
    settings: dict[str, Any]


def _line(label: str, amount: Decimal) -> GaLineOut:
    value = amount.quantize(Decimal("0.01"))
    return GaLineOut(label=label, amount=format(value, "f"), amount_display=format_inr(value))


@router.get("/versions/{version_id}/general-abstract", response_model=Envelope[GeneralAbstractOut])
def get_general_abstract(version_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[GeneralAbstractOut]:
    scope = es.get_version(db, auth, version_id)
    g = service.general_abstract(db, scope)
    r = g.result
    with_analysis = {a.boq_item_id for a in service._analyses(db, version_id)}
    total = r.total.quantize(Decimal("0.01"))
    two = Decimal("0.01")
    if total < 0:
        raise AppError("NEGATIVE_TOTAL", "The estimate total is negative.")
    return ok(
        GeneralAbstractOut(
            version_id=version_id,
            can_edit=_can_edit(scope),
            items=[
                GaItemOut(
                    sl_no=sl,
                    item_id=i.id,
                    code=i.item_no or sl,
                    description=i.description,
                    quantity=_s(i.quantity),
                    rate=_s(i.rate),
                    unit=i.unit_code,
                    amount=format(a.quantize(two), "f"),
                    has_analysis=i.id in with_analysis,
                )
                for sl, i, a in g.items
            ],
            ecv=format(r.ecv.quantize(two), "f"),
            ecv_display=format_inr(r.ecv.quantize(two)),
            part_b=[_line(line.label, line.amount) for line in r.part_b],
            part_b_total=format(r.part_b_total.quantize(two), "f"),
            subtotal=format(r.subtotal.quantize(two), "f"),
            subtotal_display=format_inr(r.subtotal.quantize(two)),
            gst_pct=str(g.config["abstract"]["gst_pct"]),
            gst=format(r.gst.quantize(two), "f"),
            gst_display=format_inr(r.gst.quantize(two)),
            after_gst=[_line(line.label, line.amount) for line in r.after_gst],
            rounding_off=format(r.rounding_off.quantize(two), "f"),
            total=format(total, "f"),
            total_display=format_inr(total),
            total_in_lakhs=format(r.total_in_lakhs.quantize(two), "f"),
            amount_in_words=amount_in_words(total),
            settings=g.config["abstract"],
        )
    )
