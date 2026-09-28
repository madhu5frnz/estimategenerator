"""Lead (conveyance) charges from the SoR tables COM-LDLFT-1/2.

Mechanical conveyance: the table gives cumulative charges up to 1, 2, 3, 4 and 5 km,
then a rate per km up to 30 km and another beyond 30 km. The item rate already covers
the initial lead (1 km for most quarry materials), so the charge for a source at d km is

    table(min(d, 5)) - table(initial) + per_km_5_30 x (min(d, 30) - 5) + per_km_30 x (d - 30)

e.g. sand 16 km in Zone III: 128.6 - 48.2 + 11 x 19.3 = Rs 292.70 per cum.
Charges include 13.615 % and are added after overheads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

Table = Mapping[str, Mapping[str, str]]  # step -> class -> "rate"


class LeadError(ValueError):
    pass


@dataclass(frozen=True)
class LeadCharge:
    distance_km: Decimal  # as entered
    charged_km: Decimal  # whole km used for the table
    initial_km: int
    up_to_5: Decimal
    per_km_5_30: Decimal
    per_km_beyond_30: Decimal
    amount: Decimal  # per unit (cum or tonne)

    @property
    def working(self) -> str:
        parts = [f"{self.up_to_5}"]
        if self.charged_km > 5:
            n = min(self.charged_km, Decimal(30)) - 5
            parts.append(f"+ {n} x {self.per_km_5_30}")
        if self.charged_km > 30:
            parts.append(f"+ {self.charged_km - 30} x {self.per_km_beyond_30}")
        return " ".join(parts)


def mechanical_lead(
    table: Table, material_class: str, distance_km: Decimal, *, initial_km: int = 1
) -> LeadCharge:
    """Lead charge per unit for `distance_km` by trucks/tippers (initial lead deducted)."""
    if distance_km < 0:
        raise LeadError("Lead distance cannot be negative.")
    try:
        rate = {step: Decimal(row[material_class]) for step, row in table.items()}
    except KeyError as exc:
        raise LeadError(f"No lead rates for '{material_class}'.") from exc
    km = distance_km.quantize(Decimal(1), rounding=ROUND_CEILING)
    if km <= initial_km:
        return LeadCharge(
            distance_km,
            km,
            initial_km,
            Decimal(0),
            rate["per_km_5_30"],
            rate["per_km_beyond_30"],
            Decimal("0.00"),
        )
    initial = rate[str(initial_km)] if initial_km >= 1 else Decimal(0)
    up_to_5 = rate[str(min(int(km), 5))] - initial
    amount = up_to_5
    if km > 5:
        amount += (min(km, Decimal(30)) - 5) * rate["per_km_5_30"]
    if km > 30:
        amount += (km - 30) * rate["per_km_beyond_30"]
    return LeadCharge(
        distance_km,
        km,
        initial_km,
        up_to_5,
        rate["per_km_5_30"],
        rate["per_km_beyond_30"],
        amount.quantize(Decimal("0.01")),
    )
