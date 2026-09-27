from decimal import Decimal

import pytest

from app.domain.numeric import InvalidNumberError, plain, round_half_up, to_decimal


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.15, Decimal("0.15")),
        (5, Decimal(5)),
        ("1,23,456.50", Decimal("123456.50")),
        (" 42 ", Decimal(42)),
        (Decimal("1.1"), Decimal("1.1")),
    ],
)
def test_to_decimal_is_exact(raw: object, expected: Decimal) -> None:
    assert to_decimal(raw) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", [True, "", "abc", "NaN", "Infinity", float("inf"), None, [1]])
def test_to_decimal_rejects_non_numbers(raw: object) -> None:
    with pytest.raises(InvalidNumberError):
        to_decimal(raw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "places", "expected"),
    [
        ("2.345", 2, "2.35"),
        ("2.344", 2, "2.34"),
        ("-2.345", 2, "-2.35"),
        ("412.5", 3, "412.500"),
        ("0.5", 0, "1"),
    ],
)
def test_round_half_up(value: str, places: int, expected: str) -> None:
    assert str(round_half_up(Decimal(value), places)) == expected


def test_round_half_up_rejects_negative_places() -> None:
    with pytest.raises(ValueError):
        round_half_up(Decimal(1), -1)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.150", "0.15"), ("1E+3", "1000"), ("0", "0"), ("0.000", "0"), ("5.5", "5.5")],
)
def test_plain(value: str, expected: str) -> None:
    assert plain(Decimal(value)) == expected
