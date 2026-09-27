"""Estimate validation: calculation and consistency checks.

The result is never "engineering quantity confirmed". A clean run means the calculation
checks passed: arithmetic, units, and consistency. Engineering judgement stays with the
engineer.

Severity: red = error (the estimate is wrong or incomplete); yellow = review required;
green = no findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from app.domain.estimate.totals import line_amount, measured_quantity

Severity = Literal["red", "yellow"]
PASSED_MESSAGE = "Calculation checks passed"
STANDARD_GST_RATES = {Decimal(0), Decimal(5), Decimal(12), Decimal(18), Decimal(28)}

# Plausibility bounds (canonical units). Values outside are flagged for review, never
# rejected: they are sanity checks, not engineering standards.
BOUNDS = {
    ("road_layer", "thickness"): (Decimal("0.02"), Decimal("0.6"), "m"),
    ("road_layer", "width"): (Decimal("2.0"), Decimal("30"), "m"),
    ("wall_masonry", "T"): (Decimal("0.075"), Decimal("1.0"), "m"),
    ("wall_masonry", "H"): (Decimal("0.3"), Decimal("12"), "m"),
}
HIGH_QUANTITY = Decimal("1000000")


@dataclass(frozen=True)
class LineFacts:
    id: str
    quantity: Decimal | None
    is_deduction: bool
    recomputed: Decimal | None  # engine result now, in the item unit (None if it failed)
    recompute_error: str | None
    template_id: str | None
    canonical_inputs: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class ItemFacts:
    id: str
    sl_no: str
    description: str
    unit: str | None
    unit_places: int
    quantity: Decimal | None
    quantity_source: str
    rate: Decimal | None
    amount: Decimal | None
    rate_item_id: str | None
    rate_unit: str | None
    rate_verification: str | None
    rate_effective_to: date | None
    provenance: str
    lines: tuple[LineFacts, ...] = ()


@dataclass(frozen=True)
class ParamFacts:
    id: str
    name: str
    label: str
    value: Decimal | None
    provenance: str
    used_by: int


@dataclass(frozen=True)
class VersionFacts:
    items: tuple[ItemFacts, ...]
    params: tuple[ParamFacts, ...]
    gst_applicable: bool
    gst_rate: Decimal | None
    gst_mode: str
    works_subtotal: Decimal  # recomputed from item amounts
    snapshot_works_subtotal: Decimal | None  # frozen versions only
    today: date


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str
    entity_type: str | None = None
    entity_id: str | None = None
    sl_no: str | None = None


@dataclass(frozen=True)
class Report:
    status: Literal["green", "yellow", "red"]
    findings: tuple[Finding, ...]

    @property
    def message(self) -> str:
        if self.status == "green":
            return PASSED_MESSAGE
        reds = sum(f.severity == "red" for f in self.findings)
        yellows = len(self.findings) - reds
        parts = [f"{reds} error(s)"] if reds else []
        if yellows:
            parts.append(f"{yellows} item(s) to review")
        return ", ".join(parts)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def validate(facts: VersionFacts) -> Report:
    out: list[Finding] = []

    def add(rule: str, severity: Severity, message: str, item: ItemFacts | None = None,
            entity_type: str | None = None, entity_id: str | None = None) -> None:  # fmt: skip
        out.append(
            Finding(rule, severity, message,
                    entity_type or ("boq_item" if item else None),
                    entity_id or (item.id if item else None),
                    item.sl_no if item else None)
        )  # fmt: skip

    if not facts.items:
        add("EMPTY_ESTIMATE", "yellow", "The estimate has no BOQ items yet.")

    seen_desc: dict[tuple[str, str | None], ItemFacts] = {}
    seen_rate: dict[str, ItemFacts] = {}
    generated = 0
    for item in facts.items:
        label = f"Item {item.sl_no}"
        if item.unit is None:
            add("UNIT_MISSING", "red", f"{label} has no unit.", item)
        if item.quantity is None:
            add("QTY_MISSING", "yellow", f"{label} has no quantity yet.", item)
        elif item.quantity < 0:
            add(
                "QTY_NEGATIVE",
                "red",
                f"{label} has a negative quantity ({item.quantity}); deductions exceed additions.",
                item,
            )
        elif item.quantity == 0:
            add("QTY_ZERO", "yellow", f"{label} has a zero quantity.", item)
        elif item.quantity > HIGH_QUANTITY:
            add(
                "QTY_OUTLIER_HIGH",
                "yellow",
                f"{label} has an unusually large quantity ({item.quantity}); check the units.",
                item,
            )
        if item.quantity not in (None, Decimal(0)) and item.rate is None:
            add("RATE_MISSING", "red", f"{label} has a quantity but no rate.", item)
        if item.rate_unit and item.unit and item.rate_unit != item.unit:
            add(
                "UNIT_RATE_MISMATCH",
                "red",
                f"{label} is in {item.unit} but its rate is per {item.rate_unit}.",
                item,
            )
        if item.rate_verification == "demo":
            add(
                "DEMO_RATE_USED",
                "yellow",
                f"{label} uses a demo rate, not an official SOR rate.",
                item,
            )
        if item.rate_effective_to and item.rate_effective_to < facts.today:
            add(
                "RATE_EXPIRED",
                "yellow",
                f"{label} uses a rate that expired on {item.rate_effective_to:%d-%m-%Y}.",
                item,
            )

        expected_amount = line_amount(item.quantity, item.rate)
        if expected_amount != item.amount:
            add(
                "TOTAL_MISMATCH",
                "red",
                f"{label}: stored amount {item.amount} does not equal quantity × rate ({expected_amount}).",
                item,
            )
        if item.lines:
            lines_total = measured_quantity(
                ((line.quantity or Decimal(0), line.is_deduction) for line in item.lines),
                item.unit_places,
            )
            if item.quantity_source != "measurements" or lines_total != item.quantity:
                add(
                    "TOTAL_MISMATCH",
                    "red",
                    f"{label}: quantity {item.quantity} does not equal its measurement lines ({lines_total}).",
                    item,
                )
        for line in item.lines:
            if line.recompute_error:
                add(
                    "FORMULA_ERROR",
                    "red",
                    f"{label}: a measurement line cannot be calculated: {line.recompute_error}",
                    item,
                    "measurement",
                    line.id,
                )
            elif line.recomputed is not None and line.recomputed != line.quantity:
                add(
                    "LINE_RECALC_MISMATCH",
                    "red",
                    f"{label}: a measurement line shows {line.quantity} but recalculates to {line.recomputed}.",
                    item,
                    "measurement",
                    line.id,
                )
            for (template, name), (low, high, unit) in BOUNDS.items():
                value = line.canonical_inputs.get(name)
                if line.template_id == template and value is not None and not low <= value <= high:
                    add(
                        "INPUT_OUTLIER",
                        "yellow",
                        f"{label}: {name} = {value} {unit} is outside the usual range {low}–{high} {unit}.",
                        item,
                        "measurement",
                        line.id,
                    )

        key = (_norm(item.description), item.unit)
        if key[0] and key in seen_desc:
            add(
                "DUPLICATE_ITEM",
                "yellow",
                f"{label} looks like a duplicate of item {seen_desc[key].sl_no}.",
                item,
            )
        seen_desc.setdefault(key, item)
        if item.rate_item_id:
            if item.rate_item_id in seen_rate:
                add(
                    "DUPLICATE_ITEM",
                    "yellow",
                    f"{label} uses the same SOR item as item {seen_rate[item.rate_item_id].sl_no}.",
                    item,
                )
            seen_rate.setdefault(item.rate_item_id, item)
        if item.provenance in ("ai_extracted", "rule_extracted", "ai_suggested"):
            generated += 1

    if generated:
        add(
            "AI_REVIEW",
            "yellow",
            f"{generated} item(s) were created from a description; check their descriptions and specifications.",
        )

    for p in facts.params:
        if p.value is None:
            add(
                "PARAM_MISSING",
                "red" if p.used_by else "yellow",
                f"Parameter '{p.label}' has no value.",
                None,
                "parameter",
                p.id,
            )
        if p.provenance == "default_accepted":
            add(
                "DEFAULT_ACCEPTED",
                "yellow",
                f"Parameter '{p.label}' uses an accepted suggested value; verify it.",
                None,
                "parameter",
                p.id,
            )

    if facts.gst_applicable:
        if facts.gst_rate is None:
            add("GST_INCONSISTENT", "red", "GST is switched on but no rate is set.")
        elif not Decimal(0) <= facts.gst_rate <= Decimal(28):
            add("GST_INCONSISTENT", "red", f"GST rate {facts.gst_rate} % is outside 0–28 %.")
        elif facts.gst_rate not in STANDARD_GST_RATES:
            add(
                "GST_UNUSUAL_RATE",
                "yellow",
                f"GST rate {facts.gst_rate} % is not a standard slab; confirm it applies.",
            )

    if (
        facts.snapshot_works_subtotal is not None
        and facts.snapshot_works_subtotal != facts.works_subtotal
    ):
        add(
            "ABSTRACT_MISMATCH",
            "red",
            f"Saved works subtotal {facts.snapshot_works_subtotal} differs from the items ({facts.works_subtotal}).",
        )

    status: Literal["green", "yellow", "red"] = (
        "red" if any(f.severity == "red" for f in out) else "yellow" if out else "green"
    )
    order = {"red": 0, "yellow": 1}
    return Report(status, tuple(sorted(out, key=lambda f: order[f.severity])))
