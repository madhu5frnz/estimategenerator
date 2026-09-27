"""Decimal helpers shared by the quantity engine and money formatting."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation

# All engine arithmetic runs in this context. 28 significant digits is far beyond any
# construction quantity, and traps turn silent NaN/Infinity results into exceptions.
ENGINE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_UP, Emax=999_999, Emin=-999_999)

Number = Decimal | int | float | str


class InvalidNumberError(ValueError):
    """Raised when a value cannot be read as a finite decimal number."""


def to_decimal(value: Number) -> Decimal:
    """Convert user or API input to ``Decimal`` without binary-float artefacts.

    Floats go through ``repr`` so ``0.15`` becomes ``Decimal("0.15")``, not
    ``Decimal("0.1499999999999999944488848768742172978818416595458984375")``.
    """
    if isinstance(value, bool):
        raise InvalidNumberError("Boolean is not a number.")
    try:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, float):
            result = Decimal(repr(value))
        elif isinstance(value, int):
            result = Decimal(value)
        elif isinstance(value, str):
            cleaned = value.strip().replace(",", "").replace("_", "")
            if not cleaned:
                raise InvalidNumberError("Empty value.")
            result = Decimal(cleaned)
        else:
            raise InvalidNumberError(f"Unsupported number type: {type(value).__name__}.")
    except InvalidOperation as exc:
        raise InvalidNumberError(f"Not a number: {value!r}.") from exc
    if not result.is_finite():
        raise InvalidNumberError(f"Not a finite number: {value!r}.")
    return result


def round_half_up(value: Decimal, places: int) -> Decimal:
    """Round like Indian estimate practice (0.5 rounds away from zero)."""
    if places < 0:
        raise ValueError("places must be >= 0")
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def plain(value: Decimal) -> str:
    """Shortest human-readable form without exponent: 0.150 -> '0.15', 1E+3 -> '1000'."""
    if value == 0:
        return "0"
    normalized = value.normalize()
    text = format(normalized, "f")
    return text
