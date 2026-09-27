"""Abstract (charges, GST, rounding, grand total), validation, and estimate defaults.

Charge, GST and rounding changes return the recalculated abstract.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DB, Auth
from app.api.envelope import Envelope, ok
from app.core.errors import AppError
from app.domain.money import amount_in_words, format_inr
from app.services import abstract as service
from app.services import estimates as estimates_service
from app.services import validation as validation_service
from app.services.context import AuthContext
from app.services.projects import ROLE_RANK

router = APIRouter(tags=["abstract"])

Number = str | int | float | None
Base = Literal["works_subtotal", "running_total", "sections"]
Kind = Literal[
    "contingency", "work_charged_establishment", "labour_cess", "seigniorage", "royalty", "other"
]
RoundingMode = Literal["none", "nearest_rupee", "nearest_10", "nearest_100", "nearest_1000"]


def _m(value: Decimal) -> str:
    return format(value, "f")


# ================================================================== schemas
class AbstractSectionOut(BaseModel):
    id: uuid.UUID
    line_key: uuid.UUID
    sl_no: int
    title: str
    amount: str
    amount_display: str
    item_count: int


class ChargeOut(BaseModel):
    id: uuid.UUID
    line_key: uuid.UUID
    name: str
    kind: str
    percentage: str | None
    fixed_amount: str | None
    base: str
    section_keys: list[str]
    enabled: bool
    base_label: str
    base_amount: str
    amount: str
    amount_display: str


class GstConfigOut(BaseModel):
    applicable: bool
    mode: Literal["exclusive", "inclusive"]
    supply: Literal["intra", "inter"]
    rate_pct: str | None
    base: Literal["after_charges", "works_subtotal"]


class GstLineOut(BaseModel):
    name: str
    rate_pct: str
    base_amount: str
    amount: str
    amount_display: str
    included: bool


class ProblemOut(BaseModel):
    code: str
    message: str


class AbstractOut(BaseModel):
    version_id: uuid.UUID
    version_no: int
    status: str
    can_edit: bool
    sections: list[AbstractSectionOut]
    works_subtotal: str
    works_subtotal_display: str
    charges: list[ChargeOut]
    subtotal_before_gst: str
    subtotal_before_gst_display: str
    gst_config: GstConfigOut
    gst: list[GstLineOut]
    gst_added: str
    gst_added_display: str
    total_before_rounding: str
    total_before_rounding_display: str
    rounding: str
    rounding_adjustment: str
    grand_total: str
    grand_total_display: str
    amount_in_words: str
    notes: list[str]
    problem: ProblemOut | None


class ChargeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "other"
    percentage: Number = None
    fixed_amount: Number = None
    base: Base = "works_subtotal"
    section_keys: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    enabled: bool = True


class ChargePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    kind: Kind | None = None
    percentage: Number = None
    fixed_amount: Number = None
    base: Base | None = None
    section_keys: list[uuid.UUID] | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class OrderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class GstIn(BaseModel):
    applicable: bool
    mode: Literal["exclusive", "inclusive"] = "exclusive"
    supply: Literal["intra", "inter"] = "intra"
    rate_pct: Number = None
    base: Literal["after_charges", "works_subtotal"] = "after_charges"


class RoundingIn(BaseModel):
    grand_total: RoundingMode


class FindingOut(BaseModel):
    rule_id: str
    severity: Literal["red", "yellow"]
    message: str
    entity_type: str | None
    entity_id: str | None
    sl_no: str | None


class ValidationOut(BaseModel):
    version_id: uuid.UUID
    status: Literal["green", "yellow", "red"]
    message: str
    red_count: int
    yellow_count: int
    findings: list[FindingOut]


class DefaultChargeIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "other"
    percentage: Number = None
    fixed_amount: Number = None
    base: Literal["works_subtotal", "running_total"] = "works_subtotal"
    enabled: bool = True


class DefaultChargeOut(BaseModel):
    name: str
    kind: str
    percentage: str | None
    fixed_amount: str | None
    base: str
    enabled: bool


class DefaultsIn(BaseModel):
    gst: GstIn
    charges: list[DefaultChargeIn] = Field(default_factory=list, max_length=20)
    rounding: RoundingMode = "nearest_rupee"


class DefaultsOut(BaseModel):
    gst: GstConfigOut
    charges: list[DefaultChargeOut]
    rounding: str
    can_edit: bool


# ================================================================ builders
def abstract_out(db: DB, ctx: AuthContext, scope: estimates_service.VersionScope) -> AbstractOut:
    loaded = service.load(db, scope)
    r = loaded.result
    v = scope.version
    lines = {c.key: c for c in r.charges}
    can_edit = v.status == "draft" and ROLE_RANK[scope.access.role] >= ROLE_RANK["professional"]
    charges = []
    for c in loaded.charges:
        line = lines[str(c.line_key)]
        charges.append(
            ChargeOut(
                id=c.id,
                line_key=c.line_key,
                name=c.name,
                kind=c.kind,
                percentage=_m(c.percentage.normalize()) if c.percentage is not None else None,
                fixed_amount=_m(c.fixed_amount) if c.fixed_amount is not None else None,
                base=(c.applies_to or {}).get("base", "works_subtotal"),
                section_keys=[str(k) for k in (c.applies_to or {}).get("section_keys", [])],
                enabled=c.enabled,
                base_label=line.base_label,
                base_amount=_m(line.base_amount),
                amount=_m(line.amount),
                amount_display=format_inr(line.amount),
            )
        )
    return AbstractOut(
        version_id=v.id,
        version_no=v.version_no,
        status=v.status,
        can_edit=can_edit,
        sections=[
            AbstractSectionOut(
                id=s.section.id,
                line_key=s.section.line_key,
                sl_no=s.sl_no,
                title=s.section.title,
                amount=_m(s.total.subtotal),
                amount_display=format_inr(s.total.subtotal),
                item_count=s.total.item_count,
            )
            for s in loaded.view.sections
        ],
        works_subtotal=_m(r.works_subtotal),
        works_subtotal_display=format_inr(r.works_subtotal),
        charges=charges,
        subtotal_before_gst=_m(r.subtotal_before_gst),
        subtotal_before_gst_display=format_inr(r.subtotal_before_gst),
        gst_config=GstConfigOut(**loaded.gst),
        gst=[
            GstLineOut(
                name=g.name,
                rate_pct=_m(g.rate_pct.normalize()),
                base_amount=_m(g.base_amount),
                amount=_m(g.amount),
                amount_display=format_inr(g.amount),
                included=g.included,
            )
            for g in r.gst
        ],
        gst_added=_m(r.gst_added),
        gst_added_display=format_inr(r.gst_added),
        total_before_rounding=_m(r.total_before_rounding),
        total_before_rounding_display=format_inr(r.total_before_rounding),
        rounding=r.rounding,
        rounding_adjustment=_m(r.rounding_adjustment),
        grand_total=_m(r.grand_total),
        grand_total_display=format_inr(r.grand_total),
        amount_in_words=amount_in_words(r.grand_total) if r.grand_total >= 0 else "",
        notes=list(r.notes),
        problem=ProblemOut(code=loaded.error.error_code, message=loaded.error.message)
        if loaded.error
        else None,
    )


def _reload(
    db: DB, ctx: AuthContext, scope: estimates_service.VersionScope
) -> Envelope[AbstractOut]:
    return ok(abstract_out(db, ctx, estimates_service.get_version(db, ctx, scope.version.id)))


def _charge_data(body: BaseModel) -> dict[str, Any]:
    data = {k: getattr(body, k) for k in body.model_fields_set}
    if data.get("section_keys") is not None:
        data["section_keys"] = [str(k) for k in data["section_keys"]]
    return data


def defaults_out(ctx: AuthContext, value: dict[str, Any]) -> DefaultsOut:
    return DefaultsOut(
        gst=GstConfigOut(**value["gst"]),
        charges=[
            DefaultChargeOut(
                name=c["name"],
                kind=c["kind"],
                percentage=c.get("percentage"),
                fixed_amount=c.get("fixed_amount"),
                base=c.get("applies_to", {}).get("base", "works_subtotal"),
                enabled=c.get("enabled", True),
            )
            for c in value["charges"]
        ],
        rounding=value["rounding"],
        can_edit=ctx.is_org_admin,
    )


# ================================================================= abstract
@router.get("/versions/{version_id}/abstract", response_model=Envelope[AbstractOut])
def get_abstract(version_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[AbstractOut]:
    return ok(abstract_out(db, auth, estimates_service.get_version(db, auth, version_id)))


@router.post(
    "/versions/{version_id}/charges", response_model=Envelope[AbstractOut], status_code=201
)
def add_charge(
    version_id: uuid.UUID, body: ChargeCreate, auth: Auth, db: DB
) -> Envelope[AbstractOut]:
    data = body.model_dump()
    data["section_keys"] = [str(k) for k in body.section_keys]
    return _reload(db, auth, service.add_charge(db, auth, version_id, data))


@router.patch("/charges/{charge_id}", response_model=Envelope[AbstractOut])
def patch_charge(
    charge_id: uuid.UUID, body: ChargePatch, auth: Auth, db: DB
) -> Envelope[AbstractOut]:
    return _reload(db, auth, service.update_charge(db, auth, charge_id, _charge_data(body)))


@router.delete("/charges/{charge_id}", response_model=Envelope[AbstractOut])
def delete_charge(charge_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[AbstractOut]:
    return _reload(db, auth, service.delete_charge(db, auth, charge_id))


@router.post("/versions/{version_id}/charges/reorder", response_model=Envelope[AbstractOut])
def reorder_charges(
    version_id: uuid.UUID, body: OrderIn, auth: Auth, db: DB
) -> Envelope[AbstractOut]:
    return _reload(db, auth, service.reorder_charges(db, auth, version_id, body.ids))


@router.put("/versions/{version_id}/gst", response_model=Envelope[AbstractOut])
def put_gst(version_id: uuid.UUID, body: GstIn, auth: Auth, db: DB) -> Envelope[AbstractOut]:
    return _reload(db, auth, service.set_gst(db, auth, version_id, body.model_dump()))


@router.put("/versions/{version_id}/rounding", response_model=Envelope[AbstractOut])
def put_rounding(
    version_id: uuid.UUID, body: RoundingIn, auth: Auth, db: DB
) -> Envelope[AbstractOut]:
    return _reload(db, auth, service.set_rounding(db, auth, version_id, body.grand_total))


# =============================================================== validation
@router.get("/versions/{version_id}/validation", response_model=Envelope[ValidationOut])
def validate_version(version_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[ValidationOut]:
    scope = estimates_service.get_version(db, auth, version_id)
    report = validation_service.run(db, scope)
    reds = sum(f.severity == "red" for f in report.findings)
    return ok(
        ValidationOut(
            version_id=version_id,
            status=report.status,
            message=report.message,
            red_count=reds,
            yellow_count=len(report.findings) - reds,
            findings=[
                FindingOut(
                    rule_id=f.rule_id,
                    severity=f.severity,
                    message=f.message,
                    entity_type=f.entity_type,
                    entity_id=f.entity_id,
                    sl_no=f.sl_no,
                )
                for f in report.findings
            ],
        )
    )


# ================================================================= defaults
@router.get(
    "/organizations/{org_id}/settings/estimate-defaults", response_model=Envelope[DefaultsOut]
)
def get_defaults(org_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[DefaultsOut]:
    if org_id != auth.organization_id:
        raise AppError("NOT_FOUND", "Workspace not found.", 404)
    return ok(defaults_out(auth, service.get_defaults(db, org_id)))


@router.put(
    "/organizations/{org_id}/settings/estimate-defaults", response_model=Envelope[DefaultsOut]
)
def put_defaults(org_id: uuid.UUID, body: DefaultsIn, auth: Auth, db: DB) -> Envelope[DefaultsOut]:
    return ok(defaults_out(auth, service.put_defaults(db, auth, org_id, body.model_dump())))
