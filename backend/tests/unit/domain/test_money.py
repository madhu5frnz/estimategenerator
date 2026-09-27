import pytest

from app.domain.money import amount_in_words, format_indian, format_inr, integer_in_words


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1234567", "₹12,34,567.00"),
        ("3097500", "₹30,97,500.00"),
        ("100", "₹100.00"),
        ("1000", "₹1,000.00"),
        ("100000", "₹1,00,000.00"),
        ("123456789.456", "₹12,34,56,789.46"),
        ("0", "₹0.00"),
        ("-1500.5", "-₹1,500.50"),
    ],
)
def test_format_inr(value: str, expected: str) -> None:
    assert format_inr(value) == expected


def test_format_indian_places() -> None:
    assert format_indian("412.5", 3) == "412.500"
    assert format_indian("1234567.4", 0) == "12,34,567"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("3025000", "Rupees Thirty Lakh Twenty Five Thousand Only"),
        ("3097500", "Rupees Thirty Lakh Ninety Seven Thousand Five Hundred Only"),
        (
            "3114462.50",
            "Rupees Thirty One Lakh Fourteen Thousand Four Hundred Sixty Two and Fifty Paise Only",
        ),
        ("0", "Rupees Zero Only"),
        ("0.01", "Rupees Zero and One Paise Only"),
        ("1", "Rupees One Only"),
        ("15", "Rupees Fifteen Only"),
        ("100", "Rupees One Hundred Only"),
        ("101", "Rupees One Hundred One Only"),
        ("10000000", "Rupees One Crore Only"),
        (
            "999999999.99",
            "Rupees Ninety Nine Crore Ninety Nine Lakh Ninety Nine Thousand "
            "Nine Hundred Ninety Nine and Ninety Nine Paise Only",
        ),
        ("12000000000", "Rupees One Thousand Two Hundred Crore Only"),
        ("0.005", "Rupees Zero and One Paise Only"),
    ],
)
def test_amount_in_words(value: str, expected: str) -> None:
    assert amount_in_words(value) == expected


def test_negative_amount_in_words_rejected() -> None:
    with pytest.raises(ValueError):
        amount_in_words("-1")
    with pytest.raises(ValueError):
        integer_in_words(-1)
