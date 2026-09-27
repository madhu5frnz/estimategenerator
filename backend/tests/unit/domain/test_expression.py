from decimal import Decimal

import pytest

from app.domain.quantity.expression import (
    FormulaError,
    Quantity,
    compile_expression,
)

LEN = (1, 0)


def q(value: str, exponents: tuple[int, int] = (0, 0)) -> Quantity:
    return Quantity(Decimal(value), exponents)


def ev(expr: str, **values: Quantity) -> Quantity:
    return compile_expression(expr).evaluate(values)


def test_brief_example_exact_decimal() -> None:
    result = ev("L * B * H", L=q("500", LEN), B=q("5.5", LEN), H=q("0.15", LEN))
    assert result == Quantity(Decimal("412.500"), (3, 0))


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("2 + 3 * 4", "14"),
        ("(2 + 3) * 4", "20"),
        ("2 ^ 3", "8"),
        ("2 ** 3", "8"),
        ("10 ÷ 4", "2.5"),
        ("3 × 4", "12"),
        ("7 − 2", "5"),
        ("-3 + 5", "2"),
        ("+3", "3"),
        ("min(3, 1, 2)", "1"),
        ("max(3, 1, 2)", "3"),
        ("abs(-4)", "4"),
        ("sqrt(16)", "4"),
        ("round(2.345, 2)", "2.35"),
        ("round(2.5)", "3"),
        ("ceil(2.1)", "3"),
        ("floor(2.9)", "2"),
        ("4 ^ 0.5", "2"),
        ("0.1 + 0.2", "0.3"),
    ],
)
def test_arithmetic(expr: str, expected: str) -> None:
    assert ev(expr).value == Decimal(expected)


def test_pi() -> None:
    assert str(ev("pi").value).startswith("3.14159265358979")


def test_dimensions_propagate() -> None:
    assert ev("L * L", L=q("2", LEN)).exponents == (2, 0)
    assert ev("L ^ 3", L=q("2", LEN)).exponents == (3, 0)
    assert ev("A / L", A=q("6", (2, 0)), L=q("2", LEN)).exponents == (1, 0)
    assert ev("sqrt(A)", A=q("9", (2, 0))).value == 3
    assert ev("ceil(L / S) + 1", L=q("10", LEN), S=q("3", LEN)).value == 5


@pytest.mark.parametrize(
    ("expr", "values"),
    [
        ("L + A", {"L": q("1", LEN), "A": q("1", (2, 0))}),
        ("min(L, A)", {"L": q("1", LEN), "A": q("1", (2, 0))}),
        ("sqrt(L)", {"L": q("4", LEN)}),
        ("L ^ 1.5", {"L": q("4", LEN)}),
        ("2 ^ L", {"L": q("2", LEN)}),
    ],
)
def test_dimension_errors(expr: str, values: dict[str, Quantity]) -> None:
    with pytest.raises(FormulaError) as exc:
        ev(expr, **values)
    assert exc.value.code == "UNIT_MISMATCH"


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hi')",
        "L.real",
        "L[0]",
        "lambda: 1",
        "open('x')",
        "sqrt",
        "sqrt(x=4)",
        "'abc'",
        "True",
        "1 if L else 2",
        "L < 2",
        "[1, 2]",
        "_secret * 2",
        "2 // 3",
        "2 % 3",
        "(",
        "",
        "   ",
        "x" * 501,
        "+".join(["1"] * 150),
        "exec('1')",
        "globals()",
    ],
)
def test_rejects_unsafe_or_invalid(expr: str) -> None:
    with pytest.raises(FormulaError) as exc:
        compile_expression(expr)
    assert exc.value.code == "FORMULA_INVALID"


@pytest.mark.parametrize(
    ("expr", "code"),
    [
        ("1 / 0", "DIVISION_BY_ZERO"),
        ("1 / (2 - 2)", "DIVISION_BY_ZERO"),
        ("0 ^ -1", "DIVISION_BY_ZERO"),
        ("2 ^ 11", "FORMULA_INVALID"),
        ("sqrt(-1)", "FORMULA_INVALID"),
        ("(-8) ^ 0.5", "FORMULA_INVALID"),
        ("round(1, 11)", "FORMULA_INVALID"),
        ("round(1, 0.5)", "FORMULA_INVALID"),
        ("round(1, 2, 3)", "FORMULA_INVALID"),
        ("min(1)", "FORMULA_INVALID"),
        ("abs(1, 2)", "FORMULA_INVALID"),
        ("unknown_name * 2", "UNKNOWN_PARAMETER"),
        ("((((((((10^10)^10)^10)^10)^10)^10)^10)^10)", "FORMULA_INVALID"),
    ],
)
def test_runtime_errors(expr: str, code: str) -> None:
    with pytest.raises(FormulaError) as exc:
        ev(expr)
    assert exc.value.code == code


def test_names_exclude_functions_and_constants() -> None:
    assert compile_expression("pi * D ^ 2 / 4 * L + max(a, b)").names == {"D", "L", "a", "b"}


@pytest.mark.parametrize(
    ("expr", "symbolic"),
    [
        ("length * width * thickness", "length × width × thickness"),
        ("pi * D^2 / 4 * L", "π × D² / 4 × L"),
        ("L * (a + b) * t", "L × (a + b) × t"),
        ("(L * H - o) * T", "(L × H - o) × T"),
        ("a - (b - c)", "a - (b - c)"),
        ("a - b - c", "a - b - c"),
        ("a / (b * c)", "a / (b × c)"),
        ("(a + b) ^ 4", "(a + b)^4"),
        ("a ^ (b + 1)", "a^(b + 1)"),
        ("-(a + b)", "-(a + b)"),
        ("-a", "-a"),
        ("+a", "a"),
        ("round(a * 2, 2)", "round(a × 2, 2)"),
        ("0.150 * a", "0.15 × a"),
    ],
)
def test_render_symbolic(expr: str, symbolic: str) -> None:
    assert compile_expression(expr).render() == symbolic


def test_render_substituted() -> None:
    compiled = compile_expression("length * width * thickness")
    text = compiled.render(
        {"length": Decimal("500"), "width": Decimal("5.5"), "thickness": Decimal("0.150")}
    )
    assert text == "500 × 5.5 × 0.15"
