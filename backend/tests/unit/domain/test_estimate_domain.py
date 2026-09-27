from decimal import Decimal

import pytest

from app.domain.estimate.measurement import dimensions_calculation
from app.domain.estimate.totals import line_amount, measured_quantity, section_total, works_subtotal
from app.domain.quantity import CalculationError

D = Decimal


@pytest.mark.parametrize(
    ("qty", "rate", "expected"),
    [
        (D("825.000"), D("6450.00"), D("5321250.00")),
        (D("412.500"), D("1250.50"), D("515831.25")),
        (D("1.005"), D("1.00"), D("1.01")),  # half-up at the paisa
        (D("0.000"), D("100.00"), D("0.00")),
        (None, D("1.00"), None),
        (D("1.000"), None, None),
    ],
)
def test_line_amount(qty: Decimal | None, rate: Decimal | None, expected: Decimal | None) -> None:
    assert line_amount(qty, rate) == expected


def test_measured_quantity_with_deductions() -> None:
    lines = [(D("412.500"), False), (D("412.500"), False), (D("2.250"), True)]
    assert measured_quantity(lines, 3) == D("822.750")
    assert measured_quantity([], 3) == D("0.000")
    assert measured_quantity([(D("1"), True)], 2) == D("-1.00")


def test_section_and_works_totals() -> None:
    a = section_total([D("250000.00"), None, D("0.50")])
    assert (a.subtotal, a.item_count, a.priced_count) == (D("250000.50"), 3, 2)
    b = section_total([D("1550000.00")])
    assert works_subtotal([a, b]) == D("1800000.50")
    assert works_subtotal([]) == D("0.00")


def test_dimensions_volume_brief_example() -> None:
    r = dimensions_calculation(
        item_unit="cum", nos=D(1), length=D(100), breadth=D(2), depth_height=D(1),
        dimension_unit="m",
    )  # fmt: skip
    assert r.value == D("200.000")
    assert r.expression == "nos × L × B × D"
    assert r.substituted == "1 × 100 × 2 × 1"


@pytest.mark.parametrize(
    ("unit", "nos", "dims", "expected"),
    [
        ("sqm", D(1), (D(10), None, D(3)), D("30.00")),  # plaster: L and H
        ("rmt", D(1), (D(12), None, None), D("12.00")),
        ("nos", D(4), (None, None, None), D("4")),
        ("cum", D(4), (D(10), D("0.23"), D(3)), D("27.600")),  # 4 walls
    ],
)
def test_dimensions_by_unit(
    unit: str,
    nos: Decimal,
    dims: tuple[Decimal | None, Decimal | None, Decimal | None],
    expected: Decimal,
) -> None:
    r = dimensions_calculation(
        item_unit=unit, nos=nos, length=dims[0], breadth=dims[1], depth_height=dims[2],
        dimension_unit="m",
    )  # fmt: skip
    assert r.value == expected
    assert r.unit == unit


def test_dimensions_in_feet_converted_to_item_unit() -> None:
    r = dimensions_calculation(
        item_unit="sqm", nos=D(1), length=D(10), breadth=D(10), depth_height=None,
        dimension_unit="ft",
    )  # fmt: skip
    assert r.value == D("9.29")


@pytest.mark.parametrize(
    ("unit", "dims", "code"),
    [
        ("cum", (D(1), D(2), None), "DIMENSIONS_MISMATCH"),
        ("sqm", (D(1), D(2), D(3)), "DIMENSIONS_MISMATCH"),
        ("nos", (D(1), None, None), "DIMENSIONS_MISMATCH"),
        ("kg", (D(1), None, None), "MEASUREMENT_NOT_SUPPORTED"),
        ("ls", (None, None, None), "MEASUREMENT_NOT_SUPPORTED"),
    ],
)
def test_dimensions_errors(
    unit: str, dims: tuple[Decimal | None, Decimal | None, Decimal | None], code: str
) -> None:
    with pytest.raises(CalculationError) as exc:
        dimensions_calculation(
            item_unit=unit, nos=D(1), length=dims[0], breadth=dims[1], depth_height=dims[2],
            dimension_unit="m",
        )  # fmt: skip
    assert exc.value.code == code


def test_dimensions_need_a_unit() -> None:
    with pytest.raises(CalculationError) as exc:
        dimensions_calculation(
            item_unit="rmt", nos=D(1), length=D(5), breadth=None, depth_height=None,
            dimension_unit=None,
        )  # fmt: skip
    assert exc.value.code == "UNIT_REQUIRED"
