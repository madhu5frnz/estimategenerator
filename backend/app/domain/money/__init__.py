"""Indian number formatting and amount in words (lakh / crore system)."""

from __future__ import annotations

from decimal import Decimal

from app.domain.numeric import Number, round_half_up, to_decimal

_ONES = [
    "Zero",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]
_TENS = ["_", "_", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _group_indian(digits: str) -> str:
    """'1234567' -> '12,34,567' (last three digits, then pairs)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join([*pairs, tail])


def format_indian(value: Number, places: int = 2) -> str:
    """Format with Indian digit grouping: 1234567.5 -> '12,34,567.50'."""
    amount = round_half_up(to_decimal(value), places)
    sign = "-" if amount < 0 else ""
    text = format(abs(amount), "f")
    whole, _, fraction = text.partition(".")
    grouped = _group_indian(whole)
    return f"{sign}{grouped}.{fraction}" if places else f"{sign}{grouped}"


def format_inr(value: Number, places: int = 2) -> str:
    """'₹12,34,567.00'; negative amounts as '-₹1,000.00'."""
    text = format_indian(value, places)
    return f"-₹{text[1:]}" if text.startswith("-") else f"₹{text}"


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def integer_in_words(n: int) -> str:
    """Indian system: 3025000 -> 'Thirty Lakh Twenty Five Thousand'."""
    if n < 0:
        raise ValueError("Negative amounts cannot be written in words.")
    if n == 0:
        return "Zero"
    crore, rest = divmod(n, 10_000_000)
    lakh, rest = divmod(rest, 100_000)
    thousand, rest = divmod(rest, 1_000)
    parts = []
    if crore:
        # Above 99 crore the crore count is itself written in the Indian system
        # (e.g. 'One Thousand Two Hundred Crore').
        parts.append(f"{integer_in_words(crore)} Crore")
    if lakh:
        parts.append(f"{_below_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_hundred(thousand)} Thousand")
    if rest:
        parts.append(_below_thousand(rest))
    return " ".join(parts)


def amount_in_words(value: Number) -> str:
    """'Rupees Thirty Lakh Twenty Five Thousand Only'; paise are included when present."""
    amount = round_half_up(to_decimal(value), 2)
    if amount < 0:
        raise ValueError("Negative amounts cannot be written in words.")
    rupees = int(amount)
    paise = int((amount - Decimal(rupees)) * 100)
    text = f"Rupees {integer_in_words(rupees)}"
    if paise:
        text += f" and {_below_hundred(paise)} Paise"
    return f"{text} Only"


__all__ = ["amount_in_words", "format_indian", "format_inr", "integer_in_words"]
