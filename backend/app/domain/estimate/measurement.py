"""Turn a detailed-estimate line (No × L × B × D/H) into an engine calculation.

The item's unit decides how many dimensions are needed: a length item needs one, an area
item two and a volume item three. A count item uses No alone. Blank dimensions are simply
not used, so a plaster line can be entered as L and H, and a floor as L and B.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.quantity import CalculationError, CalculationResult, ParamInput
from app.domain.quantity.engine import evaluate_expression
from app.domain.units import Dimension, UnitRegistry, default_registry

DIMENSIONS_NEEDED = {
    Dimension.COUNT: 0,
    Dimension.LENGTH: 1,
    Dimension.AREA: 2,
    Dimension.VOLUME: 3,
}
DIMENSION_NAMES = ("L", "B", "D")


def dimensions_calculation(
    *,
    item_unit: str,
    nos: Decimal,
    length: Decimal | None,
    breadth: Decimal | None,
    depth_height: Decimal | None,
    dimension_unit: str | None,
    registry: UnitRegistry | None = None,
) -> CalculationResult:
    registry = registry or default_registry()
    unit = registry.get(item_unit)
    needed = DIMENSIONS_NEEDED.get(unit.dimension)
    if needed is None:
        raise CalculationError(
            "MEASUREMENT_NOT_SUPPORTED",
            f"Items measured in {unit.display_name} cannot use L × B × D lines. "
            "Use a formula line or enter the quantity directly.",
        )
    given = [
        (name, value)
        for name, value in zip(DIMENSION_NAMES, (length, breadth, depth_height), strict=True)
        if value is not None
    ]
    if len(given) != needed:
        what = {0: "only No.", 1: "one dimension (L)", 2: "two dimensions (e.g. L and B)",
                3: "three dimensions (L, B and D/H)"}[needed]  # fmt: skip
        raise CalculationError(
            "DIMENSIONS_MISMATCH",
            f"{unit.display_name} needs {what}; {len(given)} given.",
            {"needed": needed, "given": len(given)},
        )
    if given and not dimension_unit:
        raise CalculationError("UNIT_REQUIRED", "Choose the unit the dimensions are in.")
    inputs = {"nos": ParamInput(nos, None)}
    inputs.update({name: ParamInput(value, dimension_unit) for name, value in given})
    expression = " * ".join(["nos", *(name for name, _ in given)])
    return evaluate_expression(expression, inputs, unit.code, registry)
