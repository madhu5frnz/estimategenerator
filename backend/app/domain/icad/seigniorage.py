"""Seigniorage statement: minor-mineral royalty on the materials an estimate consumes.

Each line is (item quantity) x (material per unit of item, e.g. 0.9 cum metal per cum of
M-15) x (seigniorage rate). Then:

    DMF  = 30 % of total seigniorage   (District Mineral Foundation)
    SMET =  2 % of total seigniorage   (State Mineral Exploration Trust)
    Permit fee = 80 % of the seigniorage on the chosen materials

Rates and percentages come from the estimate's settings (defaults from the department's
estimates, to be confirmed against the current G.O.). Line amounts use ROUNDUP to paise
and DMF / SMET are rounded to the rupee, as in the department's sheets.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.icad.rate_analysis import round_up

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class SeigniorageLine:
    item_label: str
    material: str  # key into the rates, e.g. "metal", "sand", "earth"
    item_quantity: Decimal
    factor: Decimal  # material per unit of the item
    rate: Decimal


@dataclass(frozen=True)
class SeigniorageSettings:
    dmf_pct: Decimal = Decimal(30)
    smet_pct: Decimal = Decimal(2)
    permit_fee_pct: Decimal = Decimal(80)
    permit_fee_materials: frozenset[str] = frozenset({"metal"})
    line_rounding: str = "roundup_paise"  # or "rupee"
    levy_rounding: str = "rupee"  # DMF / SMET


@dataclass(frozen=True)
class SeigniorageResult:
    lines: tuple[tuple[SeigniorageLine, Decimal, Decimal], ...]  # line, material qty, amount
    by_material: dict[str, Decimal]
    total: Decimal
    dmf: Decimal
    smet: Decimal
    permit_fee: Decimal


def _levy(value: Decimal, mode: str) -> Decimal:
    places = Decimal(1) if mode == "rupee" else Decimal("0.01")
    return value.quantize(places, rounding=ROUND_HALF_UP)


def compute(
    lines: Sequence[SeigniorageLine], settings: SeigniorageSettings | None = None
) -> SeigniorageResult:
    s = settings or SeigniorageSettings()
    out = []
    by_material: dict[str, Decimal] = {}
    for line in lines:
        qty = line.item_quantity * line.factor
        raw = qty * line.rate
        amount = (
            round_up(raw, 2)
            if s.line_rounding == "roundup_paise"
            else raw.quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
        out.append((line, qty, amount))
        by_material[line.material] = by_material.get(line.material, Decimal(0)) + amount
    total = sum((a for _, _, a in out), Decimal(0))
    permit_base = _sum(by_material, s.permit_fee_materials)
    return SeigniorageResult(
        lines=tuple(out),
        by_material=by_material,
        total=total,
        dmf=_levy(total * s.dmf_pct / HUNDRED, s.levy_rounding),
        smet=_levy(total * s.smet_pct / HUNDRED, s.levy_rounding),
        permit_fee=permit_base * s.permit_fee_pct / HUNDRED,
    )


def _sum(by_material: dict[str, Decimal], keys: Collection[str]) -> Decimal:
    if "*" in keys:
        return sum(by_material.values(), Decimal(0))
    return sum((v for k, v in by_material.items() if k in keys), Decimal(0))
