import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.units import Conversion, Dimension, Unit, UnitError, UnitRegistry, default_registry
from app.domain.units.seed import CONVERSIONS, UNITS
from tests.conftest import REPO_ROOT

R = default_registry()


@pytest.mark.parametrize(
    ("value", "src", "dst", "expected"),
    [
        ("1", "ft", "m", "0.3048"),
        ("1", "sqft", "sqm", "0.09290304"),
        ("1", "cuft", "cum", "0.028316846592"),
        ("150", "mm", "m", "0.15"),
        ("2", "km", "m", "2000"),
        ("1", "ha", "sqm", "10000"),
        ("1", "mt", "qtl", "10"),
        ("1", "m", "ft", "3.280839895013123359580052493"),
        ("1000", "l", "cum", "1"),
        ("7", "m", "m", "7"),
    ],
)
def test_convert(value: str, src: str, dst: str, expected: str) -> None:
    assert R.convert(value, src, dst) == Decimal(expected)


def test_round_trip_is_stable() -> None:
    back = R.convert(R.convert("123.456", "cuft", "cum"), "cum", "cuft")
    assert back.quantize(Decimal("0.000000001")) == Decimal("123.456000000")


def test_convert_rejects_dimension_mismatch() -> None:
    with pytest.raises(UnitError) as exc:
        R.convert(1, "m", "sqm")
    assert exc.value.code == "UNIT_MISMATCH"


def test_convert_without_defined_conversion() -> None:
    with pytest.raises(UnitError) as exc:
        R.convert(1, "set", "nos")
    assert exc.value.code == "CONVERSION_UNAVAILABLE"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Cum", "cum"),
        ("cu.m", "cum"),
        ("Cu. M", "cum"),
        ("m3", "cum"),
        ("sq.ft", "sqft"),
        ("SFT", "sqft"),
        ("mtrs", "m"),
        ("metres", "m"),
        ("MT", "mt"),
        ("Nos", "nos"),
        ("kg/m", "kgpm"),
        ("Rmt", "rmt"),
        ("r.m", "rmt"),
        ("hectares", "ha"),
        ("mm", "mm"),
    ],
)
def test_parse_aliases(text: str, code: str) -> None:
    assert R.parse(text).code == code


def test_parse_unknown() -> None:
    with pytest.raises(UnitError) as exc:
        R.parse("furlong")
    assert exc.value.code == "UNKNOWN_UNIT"


def test_get_unknown() -> None:
    with pytest.raises(UnitError):
        R.get("nope")


def test_every_non_canonical_physical_unit_converts() -> None:
    for unit in R.units:
        if unit.dimension in (Dimension.COUNT, Dimension.LUMP_SUM, Dimension.OTHER):
            continue
        assert R.to_canonical(1, unit.code) > 0, unit.code


def test_dimension_exponent_mapping() -> None:
    assert Dimension.from_exponents((3, 0)) is Dimension.VOLUME
    assert Dimension.from_exponents((0, 0)) is Dimension.COUNT
    assert Dimension.from_exponents((5, 0)) is None
    assert Dimension.LUMP_SUM.exponents is None


def _registry(units: list[Unit], conversions: list[Conversion]) -> UnitRegistry:
    return UnitRegistry(units, conversions)


@pytest.mark.parametrize(
    ("units", "conversions"),
    [
        ([Unit("m", "m", Dimension.LENGTH, True), Unit("m", "m", Dimension.LENGTH)], []),
        ([Unit("m", "m", Dimension.LENGTH, True), Unit("x", "x", Dimension.LENGTH, True)], []),
        ([Unit("m", "m", Dimension.LENGTH, True)], [Conversion("ft", "m", "0.3")]),
        (
            [Unit("m", "m", Dimension.LENGTH, True), Unit("kg", "kg", Dimension.MASS, True)],
            [Conversion("kg", "m", "1")],
        ),
        (
            [Unit("m", "m", Dimension.LENGTH, True), Unit("ft", "ft", Dimension.LENGTH)],
            [Conversion("ft", "m", "0")],
        ),
        (
            [
                Unit("m", "m", Dimension.LENGTH, True, aliases=("x",)),
                Unit("kg", "kg", Dimension.MASS, True, aliases=("x",)),
            ],
            [],
        ),
    ],
    ids=[
        "duplicate-code",
        "two-canonicals",
        "unknown-unit",
        "wrong-target",
        "zero-factor",
        "ambiguous-alias",
    ],
)
def test_registry_rejects_bad_configuration(
    units: list[Unit], conversions: list[Conversion]
) -> None:
    with pytest.raises(UnitError) as exc:
        _registry(units, conversions)
    assert exc.value.code == "UNIT_CONFIG_INVALID"


def test_missing_canonical() -> None:
    reg = _registry([Unit("m", "m", Dimension.LENGTH, True)], [])
    with pytest.raises(UnitError):
        reg.canonical(Dimension.MASS)


def _sql_rows(sql: str, table: str) -> list[list[str]]:
    block = re.search(rf"INSERT INTO {table} \([^)]*\) VALUES(.*?);", sql, re.S)
    assert block, table
    rows = []
    for line in block.group(1).strip().splitlines():
        rows.append(re.findall(r"'((?:[^']|'')*)'|\b(true|false)\b|(\d+(?:\.\d+)?)", line))
    return [["".join(g) for g in row] for row in rows]


@pytest.mark.parametrize(
    "sql_path",
    [
        REPO_ROOT / "backend" / "migrations" / "sql" / "0001_initial_schema.sql",
        REPO_ROOT / "docs" / "design" / "03-database-schema.sql",
    ],
)
def test_python_seed_matches_sql_seed(sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    unit_rows = _sql_rows(sql, "units")
    assert {r[0] for r in unit_rows} == {u.code for u in UNITS}
    by_code = {u.code: u for u in UNITS}
    for code, display, dim, canonical, places, *_ in unit_rows:
        unit = by_code[code]
        assert (unit.display_name, unit.dimension.value) == (display, dim), code
        assert unit.is_canonical == (canonical == "true"), code
        assert unit.decimal_places == int(places), code
    conv_rows = _sql_rows(sql, "unit_conversions")
    assert {(r[0], r[1]): Decimal(r[2]) for r in conv_rows} == {
        (c.from_unit, c.to_unit): c.factor_decimal for c in CONVERSIONS
    }
