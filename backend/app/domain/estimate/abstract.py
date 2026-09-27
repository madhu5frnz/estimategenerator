"""Abstract estimate: section totals → charges → GST → rounding → grand total.

Every step is explicit and shown to the user with its base and percentage; nothing is
hidden or fixed by the system. All percentages come from the estimate's configuration.

Charges are applied in order. Each one's base is either the works subtotal, the running
total so far (subtotal plus earlier charges), or chosen sections.

GST (only when switched on, with a rate the user chose):
* exclusive: added on top. Intra-state = CGST + SGST (half each); inter-state = IGST.
* inclusive: the rates already include GST. The GST contained in the base is shown for
  information but not added again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.domain.numeric import ENGINE_CONTEXT, round_half_up

ChargeBase = Literal["works_subtotal", "running_total", "sections"]
Rounding = Literal["none", "nearest_rupee", "nearest_10", "nearest_100", "nearest_1000"]
ROUNDING_STEPS: dict[str, Decimal] = {
    "nearest_rupee": Decimal(1),
    "nearest_10": Decimal(10),
    "nearest_100": Decimal(100),
    "nearest_1000": Decimal(1000),
}
HUNDRED = Decimal(100)


def paise(value: Decimal) -> Decimal:
    return round_half_up(value, 2)


@dataclass(frozen=True)
class SectionAmount:
    key: str
    sl_no: int
    title: str
    amount: Decimal


@dataclass(frozen=True)
class ChargeSpec:
    key: str
    name: str
    kind: str
    percentage: Decimal | None = None
    fixed_amount: Decimal | None = None
    base: ChargeBase = "works_subtotal"
    section_keys: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True)
class GstConfig:
    applicable: bool = False
    mode: Literal["exclusive", "inclusive"] = "exclusive"
    supply: Literal["intra", "inter"] = "intra"
    rate_pct: Decimal | None = None
    base: Literal["after_charges", "works_subtotal"] = "after_charges"


@dataclass(frozen=True)
class ChargeLine:
    key: str
    name: str
    kind: str
    base_label: str  # "works subtotal" | "running total" | "sections 1, 3"
    base_amount: Decimal
    percentage: Decimal | None
    amount: Decimal
    enabled: bool


@dataclass(frozen=True)
class GstLine:
    name: str  # CGST | SGST | IGST
    rate_pct: Decimal
    base_amount: Decimal
    amount: Decimal
    included: bool  # True = contained in the rates, not added


@dataclass(frozen=True)
class Abstract:
    sections: tuple[SectionAmount, ...]
    works_subtotal: Decimal
    charges: tuple[ChargeLine, ...]
    subtotal_before_gst: Decimal
    gst: tuple[GstLine, ...]
    gst_added: Decimal
    total_before_rounding: Decimal
    rounding: Rounding
    rounding_adjustment: Decimal
    grand_total: Decimal
    notes: tuple[str, ...] = field(default_factory=tuple)


class AbstractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _pct(amount: Decimal, pct: Decimal) -> Decimal:
    return paise(ENGINE_CONTEXT.divide(ENGINE_CONTEXT.multiply(amount, pct), HUNDRED))


def compute_abstract(
    sections: Sequence[SectionAmount],
    charges: Sequence[ChargeSpec] = (),
    gst: GstConfig | None = None,
    rounding: Rounding = "none",
) -> Abstract:
    gst = gst or GstConfig()
    works = paise(sum((s.amount for s in sections), Decimal(0)))
    by_key = {s.key: s for s in sections}
    running = works
    lines: list[ChargeLine] = []
    notes: list[str] = []

    for charge in charges:
        if (charge.percentage is None) == (charge.fixed_amount is None):
            raise AbstractError(
                "CHARGE_INVALID", f"'{charge.name}' needs either a percentage or a fixed amount."
            )
        if charge.base == "works_subtotal":
            base, label = works, "works subtotal"
        elif charge.base == "running_total":
            base, label = running, "running total"
        else:
            chosen = [by_key[k] for k in charge.section_keys if k in by_key]
            base = paise(sum((s.amount for s in chosen), Decimal(0)))
            label = (
                "section " + ", ".join(str(s.sl_no) for s in chosen) if chosen else "no sections"
            )
        if charge.percentage is not None:
            amount = _pct(base, charge.percentage)
        else:
            assert charge.fixed_amount is not None
            amount, label = paise(charge.fixed_amount), "fixed amount"
        lines.append(
            ChargeLine(
                key=charge.key, name=charge.name, kind=charge.kind, base_label=label,
                base_amount=base, percentage=charge.percentage,
                amount=amount if charge.enabled else Decimal("0.00"), enabled=charge.enabled,
            )
        )  # fmt: skip
        if charge.enabled:
            running = paise(running + amount)

    subtotal = running
    gst_lines: list[GstLine] = []
    added = Decimal("0.00")
    if gst.applicable:
        if gst.rate_pct is None:
            raise AbstractError(
                "GST_RATE_REQUIRED", "Enter the GST rate that applies to this work."
            )
        rate = gst.rate_pct
        base = subtotal if gst.base == "after_charges" else works
        parts = (
            [("CGST", rate / 2), ("SGST", rate / 2)] if gst.supply == "intra" else [("IGST", rate)]
        )
        if gst.mode == "exclusive":
            for name, part in parts:
                amount = _pct(base, part)
                gst_lines.append(GstLine(name, part, base, amount, included=False))
                added += amount
        else:
            # GST contained in an inclusive amount: base × r / (100 + r).
            contained = ENGINE_CONTEXT.divide(ENGINE_CONTEXT.multiply(base, rate), HUNDRED + rate)
            for name, part in parts:
                share = paise(ENGINE_CONTEXT.divide(ENGINE_CONTEXT.multiply(contained, part), rate))
                gst_lines.append(GstLine(name, part, base, share, included=True))
            notes.append("Rates include GST; the GST shown is contained in the amounts, not added.")

    total = paise(subtotal + added)
    step = ROUNDING_STEPS.get(rounding)
    grand = (
        total
        if step is None
        else (total / step).quantize(Decimal(1), rounding="ROUND_HALF_UP") * step
    )
    grand = paise(grand)
    return Abstract(
        sections=tuple(sections), works_subtotal=works, charges=tuple(lines),
        subtotal_before_gst=subtotal, gst=tuple(gst_lines), gst_added=paise(added),
        total_before_rounding=total, rounding=rounding, rounding_adjustment=paise(grand - total),
        grand_total=grand, notes=tuple(notes),
    )  # fmt: skip
