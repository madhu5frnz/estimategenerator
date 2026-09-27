"""Centralised unit registry and conversion service.

No conversion factor appears anywhere else in the code base; every conversion goes through
``UnitRegistry``. Conversions are stored only as ``unit -> canonical unit`` pairs, and any
other pair is derived through the canonical unit, so the table can never hold two
inconsistent factors for the same pair.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache

from app.domain.numeric import ENGINE_CONTEXT, Number, to_decimal


class UnitError(ValueError):
    """Unknown unit, incompatible dimensions, or a missing conversion."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Dimension(StrEnum):
    LENGTH = "length"
    AREA = "area"
    VOLUME = "volume"
    MASS = "mass"
    LINEAR_DENSITY = "linear_density"  # kg/m, e.g. steel unit weight
    COUNT = "count"
    LUMP_SUM = "lump_sum"
    OTHER = "other"

    @property
    def exponents(self) -> tuple[int, int] | None:
        """Physical dimension as (length, mass) exponents; None = not usable in formulas.

        Counts are dimensionless multipliers.
        """
        return _EXPONENTS.get(self)

    @classmethod
    def from_exponents(cls, exponents: tuple[int, int]) -> Dimension | None:
        for dim, exp in _EXPONENTS.items():
            if exp == exponents and dim is not Dimension.COUNT:
                return dim
        return Dimension.COUNT if exponents == (0, 0) else None


_EXPONENTS: dict[Dimension, tuple[int, int]] = {
    Dimension.LENGTH: (1, 0),
    Dimension.AREA: (2, 0),
    Dimension.VOLUME: (3, 0),
    Dimension.MASS: (0, 1),
    Dimension.LINEAR_DENSITY: (-1, 1),
    Dimension.COUNT: (0, 0),
}


@dataclass(frozen=True)
class Unit:
    code: str
    display_name: str
    dimension: Dimension
    is_canonical: bool = False
    decimal_places: int = 3
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Conversion:
    """``to = from × factor + offset``. ``to_unit`` must be the dimension's canonical unit."""

    from_unit: str
    to_unit: str
    factor: Decimal | str
    offset: Decimal | str = "0"
    note: str = ""

    @property
    def factor_decimal(self) -> Decimal:
        return to_decimal(self.factor)

    @property
    def offset_decimal(self) -> Decimal:
        return to_decimal(self.offset)


def _compact(text: str) -> str:
    """Lower-case and drop spaces and dots: 'Cu. M' -> 'cum', 'sq.ft' -> 'sqft'."""
    return re.sub(r"[\s.]+", "", text.strip().lower())


class UnitRegistry:
    def __init__(self, units: Iterable[Unit], conversions: Iterable[Conversion]) -> None:
        self._units: dict[str, Unit] = {}
        for unit in units:
            if unit.code in self._units:
                raise UnitError("UNIT_CONFIG_INVALID", f"Duplicate unit code '{unit.code}'.")
            self._units[unit.code] = unit

        self._canonical: dict[Dimension, Unit] = {}
        for unit in self._units.values():
            if unit.is_canonical:
                if unit.dimension in self._canonical:
                    raise UnitError(
                        "UNIT_CONFIG_INVALID",
                        f"Dimension '{unit.dimension}' has more than one canonical unit.",
                    )
                self._canonical[unit.dimension] = unit

        self._to_canonical: dict[str, Conversion] = {}
        for conv in conversions:
            src, dst = self._units.get(conv.from_unit), self._units.get(conv.to_unit)
            if src is None or dst is None:
                raise UnitError(
                    "UNIT_CONFIG_INVALID",
                    f"Conversion {conv.from_unit}->{conv.to_unit} references an unknown unit.",
                )
            if not dst.is_canonical or dst.dimension != src.dimension:
                raise UnitError(
                    "UNIT_CONFIG_INVALID",
                    f"Conversion {conv.from_unit}->{conv.to_unit} must target the canonical "
                    f"unit of dimension '{src.dimension}'.",
                )
            if conv.factor_decimal <= 0:
                raise UnitError("UNIT_CONFIG_INVALID", "Conversion factor must be positive.")
            self._to_canonical[conv.from_unit] = conv

        self._lookup: dict[str, str] = {}
        for unit in self._units.values():
            for name in (unit.code, unit.display_name, *unit.aliases):
                for key in {name.strip().lower(), _compact(name)}:
                    existing = self._lookup.get(key)
                    if existing is not None and existing != unit.code:
                        raise UnitError(
                            "UNIT_CONFIG_INVALID",
                            f"Unit name '{name}' is ambiguous ({existing}, {unit.code}).",
                        )
                    self._lookup[key] = unit.code

    # ----------------------------------------------------------------- lookup
    @property
    def units(self) -> tuple[Unit, ...]:
        return tuple(self._units.values())

    def get(self, code: str) -> Unit:
        unit = self._units.get(code)
        if unit is None:
            raise UnitError("UNKNOWN_UNIT", f"Unknown unit '{code}'.")
        return unit

    def parse(self, text: str) -> Unit:
        """Resolve a code, display name or alias as users write it ('Cu.m', 'mtrs' …)."""
        raw = text.strip().lower()
        code = self._lookup.get(raw) or self._lookup.get(_compact(text))
        if code is None and raw.endswith("s"):
            code = self._lookup.get(_compact(raw[:-1]))  # plural: 'metres', 'mtrs'
        if code is None:
            raise UnitError("UNKNOWN_UNIT", f"Unknown unit '{text}'.")
        return self._units[code]

    def canonical(self, dimension: Dimension) -> Unit:
        unit = self._canonical.get(dimension)
        if unit is None:
            raise UnitError("UNIT_CONFIG_INVALID", f"No canonical unit for '{dimension}'.")
        return unit

    def factor_to_canonical(self, code: str) -> Conversion | None:
        """The stored conversion for a non-canonical unit (None for canonical units)."""
        unit = self.get(code)
        if unit.is_canonical:
            return None
        conv = self._to_canonical.get(code)
        if conv is None:
            raise UnitError(
                "CONVERSION_UNAVAILABLE",
                f"No conversion is defined from '{unit.display_name}' to "
                f"'{self.canonical(unit.dimension).display_name}'.",
            )
        return conv

    # ------------------------------------------------------------- conversion
    def to_canonical(self, value: Number, code: str) -> Decimal:
        amount = to_decimal(value)
        conv = self.factor_to_canonical(code)
        if conv is None:
            return amount
        ctx = ENGINE_CONTEXT
        return ctx.add(ctx.multiply(amount, conv.factor_decimal), conv.offset_decimal)

    def from_canonical(self, value: Number, code: str) -> Decimal:
        amount = to_decimal(value)
        conv = self.factor_to_canonical(code)
        if conv is None:
            return amount
        ctx = ENGINE_CONTEXT
        return ctx.divide(ctx.subtract(amount, conv.offset_decimal), conv.factor_decimal)

    def convert(self, value: Number, from_code: str, to_code: str) -> Decimal:
        src, dst = self.get(from_code), self.get(to_code)
        if src.dimension != dst.dimension:
            raise UnitError(
                "UNIT_MISMATCH",
                f"Cannot convert {src.display_name} ({src.dimension}) to "
                f"{dst.display_name} ({dst.dimension}).",
            )
        if src.code == dst.code:
            return to_decimal(value)
        return self.from_canonical(self.to_canonical(value, src.code), dst.code)


@lru_cache(maxsize=1)
def default_registry() -> UnitRegistry:
    from app.domain.units.seed import CONVERSIONS, UNITS

    return UnitRegistry(UNITS, CONVERSIONS)
