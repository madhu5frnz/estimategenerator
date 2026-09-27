"""Estimate arithmetic: line amounts and totals. Pure functions on Decimal."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.domain.numeric import ENGINE_CONTEXT, round_half_up

AMOUNT_PLACES = 2


def line_amount(quantity: Decimal | None, rate: Decimal | None) -> Decimal | None:
    """Amount = Quantity × Rate, rounded to paise. None until both are known.

    The (already rounded) BOQ quantity is used, as in a printed estimate, so anyone
    re-multiplying the printed columns gets the printed amount.
    """
    if quantity is None or rate is None:
        return None
    return round_half_up(ENGINE_CONTEXT.multiply(quantity, rate), AMOUNT_PLACES)


def measured_quantity(lines: Iterable[tuple[Decimal, bool]], places: int) -> Decimal:
    """Sum of measurement lines; deduction lines subtract. Each line is already rounded."""
    total = Decimal(0)
    for quantity, is_deduction in lines:
        total = ENGINE_CONTEXT.subtract(total, quantity) if is_deduction else total + quantity
    return round_half_up(total, places)


@dataclass(frozen=True)
class SectionTotal:
    subtotal: Decimal
    item_count: int
    priced_count: int


def section_total(amounts: Iterable[Decimal | None]) -> SectionTotal:
    subtotal = Decimal("0.00")
    count = priced = 0
    for amount in amounts:
        count += 1
        if amount is not None:
            priced += 1
            subtotal += amount
    return SectionTotal(round_half_up(subtotal, AMOUNT_PLACES), count, priced)


def works_subtotal(sections: Iterable[SectionTotal]) -> Decimal:
    return round_half_up(sum((s.subtotal for s in sections), Decimal(0)), AMOUNT_PLACES)
