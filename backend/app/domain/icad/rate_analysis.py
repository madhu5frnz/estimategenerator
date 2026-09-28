"""Rate analysis ("data") as prepared in Telangana I&CAD estimates.

A data sheet works out the cost of an analysis quantity (e.g. 15.38 cum), then the rate
for one unit:

    A. Materials + B. Machinery + C. Labour          (rows: quantity x rate)
    + additions (% of A+B+C, e.g. conveyor system 3 %)
    D. contractor's profit and overheads, 13.615 % of the above
    rate = (A + B + C + additions + D) / analysis quantity
    + corrections per unit (e.g. present cement rate - SSR cement rate)
    + conveyance per unit (quantity of material per unit x lead charge)
    "or say" = rounded, usually to Rs 0.10

Lead charges already include 13.615 %, so they are never inside D (SoR lead note 13).
The labour component per unit (with 13.615 %) is reported separately because area
allowances apply to it.

Items taken straight from the SoR (not a data item) are priced as rate + 13.615 % + lead.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal

from app.domain.numeric import ENGINE_CONTEXT

OHP_PCT = Decimal("13.615")
HUNDRED = Decimal(100)
Section = Literal["A", "B", "C"]


def r2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def or_say(value: Decimal, step: Decimal) -> Decimal:
    """Round to the nearest step (0.1, 1 ...), half up, as 'Or say Rs.' in the sheets."""
    if step <= 0:
        return value
    return (value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


@dataclass(frozen=True)
class Row:
    section: Section
    description: str
    unit: str
    quantity: Decimal | None = None
    rate: Decimal | None = None
    # A row can instead be a percentage of another row, e.g. scaffolding @ 10 % of
    # shuttering: give `pct_of_row` (index within the same section) and `pct`.
    pct: Decimal | None = None
    pct_of_row: int | None = None
    is_labour: bool = False  # machinery crew rows are labour for the labour component


@dataclass(frozen=True)
class Addition:
    description: str
    pct: Decimal  # of (A + B + C)


@dataclass(frozen=True)
class Extra:
    """A fixed amount added after overheads for the whole analysis quantity (e.g. the
    book's 'Lead charges for 1 km for FA 84 cum @ 48.2')."""

    description: str
    amount: Decimal


@dataclass(frozen=True)
class PerUnitAdjustment:
    """Added after the unit rate: a correction or conveyance for one unit of the item."""

    description: str
    quantity: Decimal  # e.g. 0.40 cum of sand per cum, or 263 kg cement for a correction
    rate: Decimal  # e.g. lead charge Rs/cum, or (present - SSR) cement rate
    with_ohp: bool = False  # cement/steel corrections carry 13.615 %; lead charges do not

    @property
    def amount(self) -> Decimal:
        base = ENGINE_CONTEXT.multiply(self.quantity, self.rate)
        return r2(base * (1 + OHP_PCT / HUNDRED)) if self.with_ohp else r2(base)


@dataclass(frozen=True)
class DataSheet:
    code: str
    description: str
    unit: str
    analysis_qty: Decimal
    rows: Sequence[Row] = ()
    additions: Sequence[Addition] = ()
    extras: Sequence[Extra] = ()
    adjustments: Sequence[PerUnitAdjustment] = ()
    ohp_pct: Decimal = OHP_PCT
    or_say_step: Decimal = Decimal("0.1")
    deleted_rows: frozenset[int] = field(default_factory=frozenset)  # engineer may drop inputs


@dataclass(frozen=True)
class RowResult:
    index: int
    row: Row
    amount: Decimal
    deleted: bool


@dataclass(frozen=True)
class DataResult:
    rows: tuple[RowResult, ...]
    materials: Decimal
    machinery: Decimal
    labour: Decimal
    additions: tuple[tuple[Addition, Decimal], ...]
    subtotal: Decimal  # A + B + C + additions
    ohp: Decimal
    extras: Decimal
    total: Decimal
    rate_before_adjustments: Decimal  # unrounded
    adjustments: tuple[tuple[PerUnitAdjustment, Decimal], ...]
    rate_exact: Decimal
    rate: Decimal  # "or say"
    labour_per_unit: Decimal
    labour_per_unit_with_ohp: Decimal


class DataSheetError(ValueError):
    pass


def compute(sheet: DataSheet) -> DataResult:
    if sheet.analysis_qty <= 0:
        raise DataSheetError(f"{sheet.code}: analysis quantity must be positive.")
    results: list[RowResult] = []
    by_section: dict[str, list[RowResult]] = {"A": [], "B": [], "C": []}
    for index, row in enumerate(sheet.rows):
        deleted = index in sheet.deleted_rows
        if row.pct is not None:
            siblings = by_section[row.section]
            if row.pct_of_row is None or row.pct_of_row >= len(siblings):
                raise DataSheetError(f"{sheet.code}: '{row.description}' refers to a missing row.")
            of = siblings[row.pct_of_row]
            amount = Decimal(0) if of.deleted else r2(of.amount * row.pct / HUNDRED)
        else:
            if row.quantity is None or row.rate is None:
                raise DataSheetError(f"{sheet.code}: '{row.description}' needs quantity and rate.")
            amount = r2(ENGINE_CONTEXT.multiply(row.quantity, row.rate))
        result = RowResult(index, row, Decimal(0) if deleted else amount, deleted)
        results.append(result)
        by_section[row.section].append(result)

    def total(section: str) -> Decimal:
        return sum((r.amount for r in by_section[section]), Decimal(0))

    a, b, c = total("A"), total("B"), total("C")
    base = a + b + c
    adds = tuple((ad, r2(base * ad.pct / HUNDRED)) for ad in sheet.additions)
    subtotal = base + sum((x for _, x in adds), Decimal(0))
    ohp = r2(subtotal * sheet.ohp_pct / HUNDRED)
    extras = sum((e.amount for e in sheet.extras), Decimal(0))
    grand = subtotal + ohp + extras
    unit_rate = ENGINE_CONTEXT.divide(grand, sheet.analysis_qty)
    adjustments = tuple((adj, adj.amount) for adj in sheet.adjustments)
    exact = unit_rate + sum((x for _, x in adjustments), Decimal(0))
    labour = c + sum((r.amount for r in by_section["B"] if r.row.is_labour), Decimal(0))
    # As printed: labour/unit to Rs 0.1, then 13.615 % of that to Rs 0.1, then the sum.
    tenth = Decimal("0.1")
    labour_unit = or_say(ENGINE_CONTEXT.divide(labour, sheet.analysis_qty), tenth)
    labour_ohp = or_say(labour_unit * sheet.ohp_pct / HUNDRED, tenth)
    return DataResult(
        rows=tuple(results),
        materials=a,
        machinery=b,
        labour=c,
        additions=adds,
        subtotal=subtotal,
        ohp=ohp,
        extras=extras,
        total=grand,
        rate_before_adjustments=unit_rate,
        adjustments=adjustments,
        rate_exact=exact,
        rate=or_say(exact, sheet.or_say_step),
        labour_per_unit=labour_unit,
        labour_per_unit_with_ohp=labour_unit + labour_ohp,
    )


def sor_item_rate(
    sor_rate: Decimal,
    lead: Decimal = Decimal(0),
    *,
    ohp_pct: Decimal = OHP_PCT,
    or_say_step: Decimal = Decimal(0),
) -> Decimal:
    """A non-data item taken from the SoR: rate + 13.615 % (+ lead, which already has it)."""
    exact = sor_rate + sor_rate * ohp_pct / HUNDRED + lead
    return or_say(exact, or_say_step) if or_say_step else exact


def round_up(value: Decimal, places: int) -> Decimal:
    """Excel ROUNDUP for positive values (seigniorage lines use it)."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_CEILING)
