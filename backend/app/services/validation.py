"""Collect the facts of a version and run the validation rules on them.

Every measurement line is recalculated from its stored inputs with the current engine, so
a stored quantity that no longer matches its formula (or a row changed outside the app)
is reported. Nothing is changed by validating.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.domain.numeric import round_half_up
from app.domain.quantity import CalculationError
from app.domain.units import default_registry
from app.domain.validation.rules import (
    ItemFacts,
    LineFacts,
    ParamFacts,
    Report,
    VersionFacts,
    validate,
)
from app.models import BoqItem
from app.services import estimates as estimates_service
from app.services.abstract import gst_of


def _line_facts(db: Session, item: BoqItem, lv: estimates_service.LineView) -> LineFacts:
    line, calc = lv.line, lv.calculation
    recomputed: Decimal | None = None
    error: str | None = None
    canonical: dict[str, Decimal] = {}
    try:
        spec = estimates_service._line_spec({}, line, calc)
        result = estimates_service._compute(db, item, spec)[0]
        recomputed = result.value
        for i in result.inputs:
            canonical[i.name] = i.formula_value
    except CalculationError as exc:
        error = exc.message
    except AppError as exc:
        error = exc.message
    return LineFacts(
        id=str(line.id),
        quantity=line.quantity,
        is_deduction=line.is_deduction,
        recomputed=recomputed,
        recompute_error=error,
        template_id=calc.template_id if calc and line.mode == "formula" else None,
        canonical_inputs=canonical,
    )


def _date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def facts(db: Session, scope: estimates_service.VersionScope) -> VersionFacts:
    view = estimates_service.load_version(db, scope)
    registry = default_registry()
    items: list[ItemFacts] = []
    works = Decimal("0.00")
    for sv in view.sections:
        for iv in sv.items:
            i = iv.item
            snap = i.rate_snapshot or {}
            items.append(
                ItemFacts(
                    id=str(i.id),
                    sl_no=iv.sl_no,
                    description=i.description,
                    unit=i.unit_code,
                    unit_places=registry.get(i.unit_code).decimal_places if i.unit_code else 3,
                    quantity=i.quantity,
                    quantity_source=i.quantity_source,
                    rate=i.rate,
                    amount=i.amount,
                    rate_item_id=str(i.rate_item_id) if i.rate_item_id else None,
                    rate_unit=snap.get("unit") if i.rate_source_type == "rate_database" else None,
                    rate_verification=snap.get("verification_status"),
                    rate_effective_to=_date(snap.get("effective_to")),
                    provenance=i.provenance,
                    lines=tuple(_line_facts(db, i, lv) for lv in iv.lines),
                )
            )
            works += i.amount or Decimal(0)
    params = tuple(
        ParamFacts(
            id=str(p.id),
            name=p.name,
            label=p.label,
            value=p.value,
            provenance=p.provenance,
            used_by=view.parameter_usage.get(p.name, 0),
        )
        for p in view.parameters
    )
    gst = gst_of(scope.version)
    snapshot = scope.version.totals_snapshot if scope.version.status == "frozen" else None
    return VersionFacts(
        items=tuple(items),
        params=params,
        gst_applicable=gst["applicable"],
        gst_rate=Decimal(gst["rate_pct"]) if gst["rate_pct"] is not None else None,
        gst_mode=gst["mode"],
        works_subtotal=round_half_up(works, 2),
        snapshot_works_subtotal=Decimal(snapshot["works_subtotal"]) if snapshot else None,
        today=date.today(),
    )


def run(db: Session, scope: estimates_service.VersionScope) -> Report:
    return validate(facts(db, scope))
