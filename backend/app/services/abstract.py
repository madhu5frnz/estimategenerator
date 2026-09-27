"""Abstract of an estimate version: charges, GST, rounding and the grand total.

The numbers come from ``app.domain.estimate.abstract``; this module stores the
configuration (charges rows, ``gst_config``, ``rounding_config``), checks it, and audits
every change. Nothing is applied by default: GST is off and there are no charges until
the user (or the workspace's estimate defaults) adds them. There is no default GST rate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.ids import new_id
from app.domain.estimate.abstract import (
    ROUNDING_STEPS,
    Abstract,
    AbstractError,
    ChargeBase,
    ChargeSpec,
    GstConfig,
    Rounding,
    SectionAmount,
    compute_abstract,
)
from app.domain.numeric import InvalidNumberError, round_half_up, to_decimal
from app.models import EstimateCharge, EstimateSection, EstimateVersion, Setting
from app.services import audit
from app.services import estimates as estimates_service
from app.services.context import AuthContext

CHARGE_KINDS = (
    "contingency",
    "work_charged_establishment",
    "labour_cess",
    "seigniorage",
    "royalty",
    "other",
)
CHARGE_BASES = ("works_subtotal", "running_total", "sections")
ROUNDING_MODES = ("none", *ROUNDING_STEPS)
DEFAULTS_KEY = "estimate.defaults"
MAX_CHARGES = 20
ROUNDING_CONFIG = {"quantity_dp": 3, "amount_dp": 2, "grand_total": "nearest_rupee"}


# =============================================================================
# Reading
# =============================================================================
@dataclass(frozen=True)
class AbstractView:
    scope: estimates_service.VersionScope
    view: estimates_service.VersionView
    charges: list[EstimateCharge]
    gst: dict[str, Any]
    rounding: str
    result: Abstract
    error: AppError | None  # configuration problem; the result is computed without GST


def charges_of(db: Session, version_id: uuid.UUID) -> list[EstimateCharge]:
    return list(
        db.scalars(
            select(EstimateCharge)
            .where(EstimateCharge.version_id == version_id)
            .order_by(EstimateCharge.sequence, EstimateCharge.id)
        )
    )


def gst_of(version: EstimateVersion) -> dict[str, Any]:
    cfg = dict(version.gst_config or {})
    return {
        "applicable": bool(cfg.get("applicable", False)),
        "mode": cfg.get("mode", "exclusive"),
        "supply": cfg.get("supply", "intra"),
        "rate_pct": cfg.get("rate_pct"),
        "base": cfg.get("base", "after_charges"),
    }


def rounding_of(version: EstimateVersion) -> str:
    mode = (version.rounding_config or {}).get("grand_total", "none")
    return mode if mode in ROUNDING_MODES else "none"


def _spec(c: EstimateCharge) -> ChargeSpec:
    applies = c.applies_to or {}
    return ChargeSpec(
        key=str(c.line_key),
        name=c.name,
        kind=c.kind,
        percentage=c.percentage,
        fixed_amount=c.fixed_amount,
        base=cast(ChargeBase, applies.get("base", "works_subtotal")),
        section_keys=tuple(str(k) for k in applies.get("section_keys", [])),
        enabled=c.enabled,
    )


def compute(
    view: estimates_service.VersionView, charges: list[EstimateCharge]
) -> tuple[Abstract, AppError | None]:
    sections = [
        SectionAmount(str(s.section.line_key), s.sl_no, s.section.title, s.total.subtotal)
        for s in view.sections
    ]
    gst = gst_of(view.version)
    config = GstConfig(
        applicable=gst["applicable"],
        mode=gst["mode"],
        supply=gst["supply"],
        rate_pct=Decimal(gst["rate_pct"]) if gst["rate_pct"] is not None else None,
        base=gst["base"],
    )
    rounding = cast(Rounding, rounding_of(view.version))
    specs = [_spec(c) for c in charges]
    try:
        return compute_abstract(sections, specs, config, rounding), None
    except AbstractError as exc:
        error = AppError(exc.code, exc.message)
    # Show what can be computed and say what is missing, rather than failing the page.
    return compute_abstract(sections, specs, GstConfig(), rounding), error


def load(db: Session, scope: estimates_service.VersionScope) -> AbstractView:
    view = estimates_service.load_version(db, scope)
    charges = charges_of(db, scope.version.id)
    result, error = compute(view, charges)
    return AbstractView(
        scope, view, charges, gst_of(scope.version), rounding_of(scope.version), result, error
    )


def grand_total(db: Session, scope: estimates_service.VersionScope) -> Decimal:
    return load(db, scope).result.grand_total


# =============================================================================
# Validation helpers
# =============================================================================
def _pct(value: Any, label: str, *, high: Decimal = Decimal(100)) -> Decimal:
    try:
        number = to_decimal(value)
    except InvalidNumberError as exc:
        raise AppError("VALIDATION_ERROR", f"{label}: {exc}") from exc
    if not Decimal(0) <= number <= high:
        raise AppError("VALIDATION_ERROR", f"{label} must be between 0 and {high} %.")
    if number != round_half_up(number, 4):
        raise AppError("VALIDATION_ERROR", f"{label} can have at most 4 decimal places.")
    return number


def _amount(value: Any, label: str) -> Decimal:
    try:
        number = to_decimal(value)
    except InvalidNumberError as exc:
        raise AppError("VALIDATION_ERROR", f"{label}: {exc}") from exc
    if number < 0:
        raise AppError("VALIDATION_ERROR", f"{label} cannot be negative.")
    if number != round_half_up(number, 2):
        raise AppError("VALIDATION_ERROR", f"{label} can have at most 2 decimal places.")
    return round_half_up(number, 2)


def clean_charge(
    data: dict[str, Any], current: EstimateCharge | None = None, *, section_keys: set[str] | None
) -> dict[str, Any]:
    """Checks a charge; ``section_keys`` None means section bases are not allowed."""

    def pick(name: str, default: Any) -> Any:
        return data.get(name, default)

    name = (pick("name", current.name if current else "") or "").strip()
    if not name:
        raise AppError("VALIDATION_ERROR", "Charge name is required.", details={"field": "name"})
    kind = pick("kind", current.kind if current else "other") or "other"
    if kind not in CHARGE_KINDS:
        raise AppError(
            "VALIDATION_ERROR", f"Unknown charge type '{kind}'.", details={"field": "kind"}
        )
    pct = pick("percentage", current.percentage if current else None)
    fixed = pick("fixed_amount", current.fixed_amount if current else None)
    if "percentage" in data and data["percentage"] is not None and "fixed_amount" not in data:
        fixed = None
    if "fixed_amount" in data and data["fixed_amount"] is not None and "percentage" not in data:
        pct = None
    if (pct is None) == (fixed is None):
        raise AppError(
            "VALIDATION_ERROR",
            "Enter either a percentage or a fixed amount.",
            details={"field": "percentage"},
        )
    applies = dict(current.applies_to) if current else {"base": "works_subtotal"}
    base = pick("base", applies.get("base", "works_subtotal"))
    if base not in CHARGE_BASES:
        raise AppError("VALIDATION_ERROR", f"Unknown base '{base}'.", details={"field": "base"})
    keys = [str(k) for k in pick("section_keys", applies.get("section_keys", [])) or []]
    if base == "sections":
        if section_keys is None:
            raise AppError(
                "VALIDATION_ERROR",
                "Defaults cannot apply to chosen sections.",
                details={"field": "base"},
            )
        keys = list(dict.fromkeys(keys))
        if not keys or not set(keys) <= section_keys:
            raise AppError(
                "VALIDATION_ERROR",
                "Choose one or more sections of this version.",
                details={"field": "section_keys"},
            )
    return {
        "name": name[:120],
        "kind": kind,
        "percentage": _pct(pct, name) if pct is not None else None,
        "fixed_amount": _amount(fixed, name) if fixed is not None else None,
        "applies_to": {"base": base, "section_keys": keys}
        if base == "sections"
        else {"base": base},
        "enabled": bool(pick("enabled", current.enabled if current else True)),
    }


def clean_gst(data: dict[str, Any]) -> dict[str, Any]:
    applicable = bool(data.get("applicable", False))
    mode = data.get("mode") or "exclusive"
    supply = data.get("supply") or "intra"
    base = data.get("base") or "after_charges"
    if mode not in ("exclusive", "inclusive"):
        raise AppError("VALIDATION_ERROR", "GST mode must be exclusive or inclusive.")
    if supply not in ("intra", "inter"):
        raise AppError("VALIDATION_ERROR", "Supply must be intra-state or inter-state.")
    if base not in ("after_charges", "works_subtotal"):
        raise AppError("VALIDATION_ERROR", "GST base must be after_charges or works_subtotal.")
    raw = data.get("rate_pct")
    rate = None if raw is None or raw == "" else _pct(raw, "GST rate", high=Decimal(28))
    if applicable and rate is None:
        raise AppError(
            "GST_RATE_REQUIRED",
            "Enter the GST rate that applies to this work.",
            details={"field": "rate_pct"},
        )
    return {
        "applicable": applicable,
        "mode": mode,
        "supply": supply,
        "rate_pct": format(rate.normalize(), "f") if rate is not None else None,
        "base": base,
    }


def clean_rounding(mode: Any) -> str:
    if mode not in ROUNDING_MODES:
        raise AppError("VALIDATION_ERROR", f"Rounding must be one of {', '.join(ROUNDING_MODES)}.")
    return str(mode)


# =============================================================================
# Changes
# =============================================================================
def _section_keys(db: Session, version_id: uuid.UUID) -> set[str]:
    return {
        str(k)
        for k in db.scalars(
            select(EstimateSection.line_key).where(EstimateSection.version_id == version_id)
        )
    }


def _audit(
    db: Session,
    ctx: AuthContext,
    scope: estimates_service.VersionScope,
    *,
    entity_type: str,
    entity_id: uuid.UUID | None,
    action: str,
    field: str | None = None,
    old: Any = None,
    new: Any = None,
) -> None:
    estimates_service._audit(
        db,
        ctx,
        scope,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        field_name=field,
        old=old,
        new=new,
    )


def _charge_json(values: dict[str, Any]) -> dict[str, Any]:
    return {k: format(v, "f") if isinstance(v, Decimal) else v for k, v in values.items()}


def add_charge(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, data: dict[str, Any]
) -> estimates_service.VersionScope:
    scope = estimates_service._scope_for(db, ctx, version_id)
    count = db.scalar(
        select(func.count())
        .select_from(EstimateCharge)
        .where(EstimateCharge.version_id == version_id)
    )
    if int(count or 0) >= MAX_CHARGES:
        raise AppError("VALIDATION_ERROR", f"An estimate can have at most {MAX_CHARGES} charges.")
    values = clean_charge(data, section_keys=_section_keys(db, version_id))
    last = db.scalar(
        select(func.max(EstimateCharge.sequence)).where(EstimateCharge.version_id == version_id)
    )
    charge = EstimateCharge(
        id=new_id(),
        organization_id=ctx.organization_id,
        version_id=version_id,
        line_key=new_id(),
        sequence=int(last or 0) + 1,
        **values,
    )
    db.add(charge)
    _audit(
        db,
        ctx,
        scope,
        entity_type="charge",
        entity_id=charge.id,
        action="create",
        new=_charge_json(values),
    )
    db.commit()
    return scope


def _charge(
    db: Session, ctx: AuthContext, charge_id: uuid.UUID
) -> tuple[EstimateCharge, estimates_service.VersionScope]:
    charge = db.scalar(
        select(EstimateCharge).where(
            EstimateCharge.id == charge_id, EstimateCharge.organization_id == ctx.organization_id
        )
    )
    if charge is None:
        raise AppError("NOT_FOUND", "Charge not found.", 404)
    return charge, estimates_service._scope_for(db, ctx, charge.version_id)


def update_charge(
    db: Session, ctx: AuthContext, charge_id: uuid.UUID, data: dict[str, Any]
) -> estimates_service.VersionScope:
    charge, scope = _charge(db, ctx, charge_id)
    values = clean_charge(data, charge, section_keys=_section_keys(db, charge.version_id))
    for name, value in values.items():
        old = getattr(charge, name)
        if old != value:
            _audit(
                db,
                ctx,
                scope,
                entity_type="charge",
                entity_id=charge.id,
                action="update",
                field=name,
                old=_charge_json({name: old})[name],
                new=_charge_json({name: value})[name],
            )
            setattr(charge, name, value)
    db.commit()
    return scope


def delete_charge(
    db: Session, ctx: AuthContext, charge_id: uuid.UUID
) -> estimates_service.VersionScope:
    charge, scope = _charge(db, ctx, charge_id)
    _audit(
        db,
        ctx,
        scope,
        entity_type="charge",
        entity_id=charge.id,
        action="delete",
        old={
            "name": charge.name,
            "percentage": _charge_json({"p": charge.percentage})["p"],
            "fixed_amount": _charge_json({"f": charge.fixed_amount})["f"],
        },
    )
    db.delete(charge)
    db.commit()
    return scope


def reorder_charges(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, ordered: list[uuid.UUID]
) -> estimates_service.VersionScope:
    scope = estimates_service._scope_for(db, ctx, version_id)
    charges = charges_of(db, version_id)
    if sorted(c.id for c in charges) != sorted(ordered) or len(set(ordered)) != len(ordered):
        raise AppError("VALIDATION_ERROR", "The new order must list every charge exactly once.")
    position = {cid: n for n, cid in enumerate(ordered, start=1)}
    for c in charges:
        c.sequence = position[c.id]
    _audit(
        db,
        ctx,
        scope,
        entity_type="charge",
        entity_id=None,
        action="reorder",
        new=[str(i) for i in ordered],
    )
    db.commit()
    return scope


def set_gst(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, data: dict[str, Any]
) -> estimates_service.VersionScope:
    scope = estimates_service._scope_for(db, ctx, version_id)
    new = clean_gst(data)
    old = gst_of(scope.version)
    if new != old:
        scope.version.gst_config = new
        _audit(
            db,
            ctx,
            scope,
            entity_type="estimate_version",
            entity_id=scope.version.id,
            action="update",
            field="gst_config",
            old=old,
            new=new,
        )
    db.commit()
    return scope


def set_rounding(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, mode: str
) -> estimates_service.VersionScope:
    scope = estimates_service._scope_for(db, ctx, version_id)
    mode = clean_rounding(mode)
    old = rounding_of(scope.version)
    if mode != old:
        scope.version.rounding_config = {
            **(scope.version.rounding_config or {}),
            "grand_total": mode,
        }
        _audit(
            db,
            ctx,
            scope,
            entity_type="estimate_version",
            entity_id=scope.version.id,
            action="update",
            field="rounding",
            old=old,
            new=mode,
        )
    db.commit()
    return scope


def copy_charges(db: Session, source_version_id: uuid.UUID, target: EstimateVersion) -> None:
    """Freeze → next draft: charges are copied with their line keys."""
    for c in charges_of(db, source_version_id):
        db.add(
            EstimateCharge(
                id=new_id(),
                organization_id=target.organization_id,
                version_id=target.id,
                line_key=c.line_key,
                name=c.name,
                kind=c.kind,
                percentage=c.percentage,
                fixed_amount=c.fixed_amount,
                applies_to=dict(c.applies_to),
                enabled=c.enabled,
                sequence=c.sequence,
            )
        )


# =============================================================================
# Workspace estimate defaults
# =============================================================================
EMPTY_DEFAULTS: dict[str, Any] = {
    "gst": {
        "applicable": False,
        "mode": "exclusive",
        "supply": "intra",
        "rate_pct": None,
        "base": "after_charges",
    },
    "charges": [],
    "rounding": "nearest_rupee",
}


def get_defaults(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    row = db.scalar(
        select(Setting).where(
            Setting.scope == "organization",
            Setting.scope_id == organization_id,
            Setting.key == DEFAULTS_KEY,
        )
    )
    if row is None:
        return {**EMPTY_DEFAULTS, "charges": []}
    return {**EMPTY_DEFAULTS, **row.value}


def put_defaults(
    db: Session, ctx: AuthContext, organization_id: uuid.UUID, data: dict[str, Any]
) -> dict[str, Any]:
    if organization_id != ctx.organization_id:
        raise AppError("NOT_FOUND", "Workspace not found.", 404)
    if not ctx.is_org_admin:
        raise AppError("FORBIDDEN", "Only workspace owners and admins can change defaults.", 403)
    charges = data.get("charges") or []
    if len(charges) > MAX_CHARGES:
        raise AppError("VALIDATION_ERROR", f"At most {MAX_CHARGES} default charges.")
    value = {
        "gst": clean_gst(data.get("gst") or {}),
        "charges": [
            _charge_json({k: v for k, v in clean_charge(c, section_keys=None).items()})
            for c in charges
        ],
        "rounding": clean_rounding(data.get("rounding", "nearest_rupee")),
    }
    row = db.scalar(
        select(Setting).where(
            Setting.scope == "organization",
            Setting.scope_id == organization_id,
            Setting.key == DEFAULTS_KEY,
        )
    )
    old = row.value if row else None
    if row is None:
        db.add(
            Setting(
                scope="organization",
                scope_id=organization_id,
                key=DEFAULTS_KEY,
                value=value,
                updated_by=ctx.user.id,
            )
        )
    else:
        row.value = value
        row.updated_by = ctx.user.id
    audit.record(
        db,
        actor=ctx.user,
        organization_id=organization_id,
        entity_type="setting",
        entity_id=None,
        action="update",
        field=DEFAULTS_KEY,
        old_value=old,
        new_value=value,
    )
    db.commit()
    return value


def apply_defaults(db: Session, version: EstimateVersion) -> None:
    """A new estimate starts from the workspace's defaults (none unless set)."""
    defaults = get_defaults(db, version.organization_id)
    version.gst_config = dict(defaults["gst"])
    version.rounding_config = {
        **ROUNDING_CONFIG,
        **(version.rounding_config or {}),
        "grand_total": defaults["rounding"],
    }
    for n, c in enumerate(defaults["charges"], start=1):
        db.add(
            EstimateCharge(
                id=new_id(),
                organization_id=version.organization_id,
                version_id=version.id,
                line_key=new_id(),
                sequence=n,
                name=c["name"],
                kind=c["kind"],
                percentage=Decimal(c["percentage"]) if c.get("percentage") is not None else None,
                fixed_amount=Decimal(c["fixed_amount"])
                if c.get("fixed_amount") is not None
                else None,
                applies_to=dict(c["applies_to"]),
                enabled=bool(c.get("enabled", True)),
            )
        )
