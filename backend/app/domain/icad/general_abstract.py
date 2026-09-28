"""General Abstract of a Telangana I&CAD estimate.

    Part A  Estimated Cost of Works (ECV) = sum of item amounts (qty x rate)
    Part B  Labour cess 1 % of ECV
            NAC 0.1 % of ECV
            Seigniorage, DMF, SMET, permit fee (from the seigniorage statement)
            other lump-sum provisions before GST
    GST 18 % on (Part A + Part B)
    Lump-sum provisions after GST (advertisement, stationery ...)
    Rounding off and unforeseen expenditure
    Total, and total in lakhs

Every percentage and rounding convention is a setting, because estimates differ: the
UT estimate keeps paise throughout, the SLRB estimate rounds item amounts to the rupee
and rounds the total up to the next Rs 1,000 plus Rs 2,000 unforeseen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal

HUNDRED = Decimal(100)
LAKH = Decimal(100000)
Rounding = Literal["none", "paise", "rupee"]


def _round(value: Decimal, mode: Rounding) -> Decimal:
    if mode == "paise":
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if mode == "rupee":
        return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return value


@dataclass(frozen=True)
class AbstractItem:
    sl_no: str
    code: str
    description: str
    quantity: Decimal
    unit: str
    rate: Decimal


@dataclass(frozen=True)
class LumpSum:
    label: str
    amount: Decimal


@dataclass(frozen=True)
class AbstractSettings:
    item_rounding: Rounding = "none"  # qty x rate: "none" keeps full value (UT), "rupee" (SLRB)
    labour_cess_pct: Decimal = Decimal(1)
    nac_pct: Decimal = Decimal("0.1")
    cess_rounding: Rounding = "paise"
    nac_rounding: Rounding = "paise"
    gst_pct: Decimal = Decimal(18)
    gst_rounding: Rounding = "paise"
    final: Literal["none", "round_up_1000_plus_unforeseen"] = "none"
    unforeseen: Decimal = Decimal(0)


@dataclass(frozen=True)
class AbstractLine:
    label: str
    amount: Decimal
    kind: Literal["item", "ecv", "provision", "subtotal", "gst", "after_gst", "rounding", "total"]


@dataclass(frozen=True)
class AbstractResult:
    item_amounts: tuple[Decimal, ...]
    ecv: Decimal
    part_b: tuple[AbstractLine, ...]
    part_b_total: Decimal
    subtotal: Decimal  # A + B
    gst: Decimal
    after_gst: tuple[AbstractLine, ...]
    rounding_off: Decimal
    total: Decimal

    @property
    def total_in_lakhs(self) -> Decimal:
        return self.total / LAKH


def compute(
    items: Sequence[AbstractItem],
    *,
    seigniorage: Decimal = Decimal(0),
    dmf: Decimal = Decimal(0),
    smet: Decimal = Decimal(0),
    permit_fee: Decimal = Decimal(0),
    before_gst: Sequence[LumpSum] = (),
    after_gst: Sequence[LumpSum] = (),
    settings: AbstractSettings | None = None,
) -> AbstractResult:
    s = settings or AbstractSettings()
    amounts = tuple(_round(i.quantity * i.rate, s.item_rounding) for i in items)
    ecv = sum(amounts, Decimal(0))
    part_b = [
        AbstractLine(
            f"Provision for Labour Cess @ {s.labour_cess_pct.normalize()} %",
            _round(ecv * s.labour_cess_pct / HUNDRED, s.cess_rounding),
            "provision",
        ),
        AbstractLine(
            f"Provision for NAC @ {s.nac_pct.normalize()} %",
            _round(ecv * s.nac_pct / HUNDRED, s.nac_rounding),
            "provision",
        ),
        AbstractLine("Provision for Seigniorage charges", seigniorage, "provision"),
        AbstractLine("Provision for DMF on Seigniorage charges", dmf, "provision"),
        AbstractLine("Provision for SMET on Seigniorage charges", smet, "provision"),
        AbstractLine("Permit fee payable", permit_fee, "provision"),
        *(AbstractLine(p.label, p.amount, "provision") for p in before_gst),
    ]
    part_b_total = sum((line.amount for line in part_b), Decimal(0))
    subtotal = ecv + part_b_total
    gst = _round(subtotal * s.gst_pct / HUNDRED, s.gst_rounding)
    after = tuple(AbstractLine(p.label, p.amount, "after_gst") for p in after_gst)
    before_rounding = subtotal + gst + sum((line.amount for line in after), Decimal(0))
    rounding_off = Decimal(0)
    if s.final == "round_up_1000_plus_unforeseen":
        thousands = (before_rounding / 1000).quantize(Decimal(1), rounding=ROUND_CEILING)
        rounding_off = thousands * 1000 - before_rounding + s.unforeseen
    return AbstractResult(
        item_amounts=amounts,
        ecv=ecv,
        part_b=tuple(part_b),
        part_b_total=part_b_total,
        subtotal=subtotal,
        gst=gst,
        after_gst=after,
        rounding_off=rounding_off,
        total=before_rounding + rounding_off,
    )
