"""Safe, dimension-aware formula evaluation on ``Decimal``.

Formulas are parsed with Python's ``ast`` module and evaluated by walking a whitelisted
subset of nodes. ``eval`` is never used. Only these constructs are accepted:

* numbers, named parameters, ``pi``
* ``+  -  *  /  ^`` (``**`` and the symbols ``×  ÷  −`` are also accepted) and parentheses
* functions ``min max round sqrt abs ceil floor``

Every value carries physical dimension exponents (length, mass), so ``L × B × H`` is
known to be a volume and ``L + B × H`` is rejected as adding a length to an area.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, DecimalException

from app.domain.numeric import ENGINE_CONTEXT, InvalidNumberError, plain, round_half_up, to_decimal

MAX_EXPRESSION_LENGTH = 500
MAX_NODES = 200
MAX_EXPONENT = 10
MAX_ROUND_PLACES = 10

PI = Decimal("3.141592653589793238462643383")
CONSTANTS: dict[str, Decimal] = {"pi": PI}
FUNCTIONS = frozenset({"min", "max", "round", "sqrt", "abs", "ceil", "floor"})

Exponents = tuple[int, int]  # (length, mass)
DIMENSIONLESS: Exponents = (0, 0)


class CalculationError(ValueError):
    """Base error for the quantity engine. ``code`` is the API ``error_code``."""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class FormulaError(CalculationError):
    pass


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    exponents: Exponents = DIMENSIONLESS


_PRECEDENCE: dict[type[ast.operator], int] = {
    ast.Add: 1,
    ast.Sub: 1,
    ast.Mult: 2,
    ast.Div: 2,
    ast.Pow: 4,
}
_UNARY_PRECEDENCE = 3
_SYMBOLS: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "×",
    ast.Div: "/",
    ast.Pow: "^",
}
_SUPERSCRIPTS = {"2": "²", "3": "³"}


def _normalise(source: str) -> str:
    return source.replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")


def _fail(message: str, **details: object) -> FormulaError:
    return FormulaError("FORMULA_INVALID", message, dict(details))


class CompiledExpression:
    """A parsed, validated formula. Create with :func:`compile_expression`."""

    def __init__(self, source: str, normalised: str, tree: ast.Expression) -> None:
        self.source = source
        self._normalised = normalised
        self._tree = tree
        name_nodes = sorted(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
                and node.id not in CONSTANTS
                and node.id not in FUNCTIONS
            ),
            key=lambda n: (n.lineno, n.col_offset),
        )
        # Parameter names in the order they first appear in the formula.
        self.ordered_names: tuple[str, ...] = tuple(dict.fromkeys(n.id for n in name_nodes))
        self.names: frozenset[str] = frozenset(self.ordered_names)

    # ------------------------------------------------------------ evaluation
    def evaluate(self, values: Mapping[str, Quantity]) -> Quantity:
        missing = sorted(self.names - values.keys())
        if missing:
            raise FormulaError(
                "UNKNOWN_PARAMETER",
                f"No value supplied for: {', '.join(missing)}.",
                {"parameters": missing},
            )
        try:
            result = self._eval(self._tree.body, values)
        except ZeroDivisionError as exc:  # includes decimal.DivisionByZero / DivisionUndefined
            raise FormulaError("DIVISION_BY_ZERO", "The formula divides by zero.") from exc
        except DecimalException as exc:  # Overflow, InvalidOperation
            raise _fail("The formula result is not a valid number.") from exc
        if not result.value.is_finite():
            raise _fail("The formula result is not a valid number.")
        return result

    def _eval(self, node: ast.expr, values: Mapping[str, Quantity]) -> Quantity:
        ctx = ENGINE_CONTEXT
        if isinstance(node, ast.Constant):
            return Quantity(self._literal(node))
        if isinstance(node, ast.Name):
            if node.id in CONSTANTS:
                return Quantity(CONSTANTS[node.id])
            return values[node.id]
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, values)
            if isinstance(node.op, ast.USub):
                return Quantity(ctx.minus(operand.value), operand.exponents)
            return operand
        if isinstance(node, ast.BinOp):
            left = self._eval(node.left, values)
            right = self._eval(node.right, values)
            return self._binop(node.op, left, right)
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)  # guaranteed by _validate
            args = [self._eval(arg, values) for arg in node.args]
            return self._call(node.func.id, args)
        raise _fail("Unsupported formula element.")  # unreachable after validation

    @staticmethod
    def _binop(op: ast.operator, left: Quantity, right: Quantity) -> Quantity:
        ctx = ENGINE_CONTEXT
        (ll, lm), (rl, rm) = left.exponents, right.exponents
        if isinstance(op, ast.Add | ast.Sub):
            if left.exponents != right.exponents:
                raise FormulaError(
                    "UNIT_MISMATCH",
                    "Cannot add or subtract values with different dimensions "
                    f"({_describe(left.exponents)} and {_describe(right.exponents)}).",
                )
            fn = ctx.add if isinstance(op, ast.Add) else ctx.subtract
            return Quantity(fn(left.value, right.value), left.exponents)
        if isinstance(op, ast.Mult):
            return Quantity(ctx.multiply(left.value, right.value), (ll + rl, lm + rm))
        if isinstance(op, ast.Div):
            if right.value == 0:
                raise FormulaError("DIVISION_BY_ZERO", "The formula divides by zero.")
            return Quantity(ctx.divide(left.value, right.value), (ll - rl, lm - rm))
        # Pow
        if right.exponents != DIMENSIONLESS:
            raise FormulaError("UNIT_MISMATCH", "An exponent must be a plain number.")
        exponent = right.value
        if abs(exponent) > MAX_EXPONENT:
            raise _fail(f"Exponents larger than {MAX_EXPONENT} are not allowed.")
        if left.exponents != DIMENSIONLESS:
            if exponent != exponent.to_integral_value():
                raise FormulaError(
                    "UNIT_MISMATCH", "A value with a unit can only be raised to a whole number."
                )
            n = int(exponent)
            return Quantity(ctx.power(left.value, n), (ll * n, lm * n))
        if left.value == 0 and exponent < 0:
            raise FormulaError("DIVISION_BY_ZERO", "The formula divides by zero.")
        if left.value < 0 and exponent != exponent.to_integral_value():
            raise _fail("A negative number cannot be raised to a fractional power.")
        return Quantity(ctx.power(left.value, exponent))

    @staticmethod
    def _call(name: str, args: list[Quantity]) -> Quantity:
        ctx = ENGINE_CONTEXT

        def arity(*allowed: int) -> None:
            if len(args) not in allowed:
                expected = " or ".join(str(n) for n in allowed)
                raise _fail(f"{name}() takes {expected} argument(s).")

        if name in ("min", "max"):
            if len(args) < 2:
                raise _fail(f"{name}() needs at least 2 arguments.")
            if len({a.exponents for a in args}) != 1:
                raise FormulaError(
                    "UNIT_MISMATCH", f"{name}() arguments must have the same dimension."
                )
            chooser: Callable[..., Quantity] = min if name == "min" else max
            return chooser(args, key=lambda a: a.value)
        if name == "abs":
            arity(1)
            return Quantity(ctx.abs(args[0].value), args[0].exponents)
        if name == "sqrt":
            arity(1)
            (el, em), value = args[0].exponents, args[0].value
            if el % 2 or em % 2:
                raise FormulaError("UNIT_MISMATCH", "sqrt() of this unit has no meaning.")
            if value < 0:
                raise _fail("sqrt() of a negative number.")
            return Quantity(ctx.sqrt(value), (el // 2, em // 2))
        if name in ("ceil", "floor"):
            arity(1)
            rounding = ROUND_CEILING if name == "ceil" else ROUND_FLOOR
            return Quantity(args[0].value.to_integral_value(rounding=rounding), args[0].exponents)
        # round
        arity(1, 2)
        places = 0
        if len(args) == 2:
            p = args[1]
            if p.exponents != DIMENSIONLESS or p.value != p.value.to_integral_value():
                raise _fail("round() places must be a whole number.")
            places = int(p.value)
            if not 0 <= places <= MAX_ROUND_PLACES:
                raise _fail(f"round() places must be between 0 and {MAX_ROUND_PLACES}.")
        return Quantity(round_half_up(args[0].value, places), args[0].exponents)

    def _literal(self, node: ast.Constant) -> Decimal:
        # Use the literal's source text so '0.15' is exactly Decimal('0.15').
        text = ast.get_source_segment(self._normalised, node)
        try:
            return to_decimal(text if text is not None else str(node.value))
        except InvalidNumberError as exc:
            raise _fail(f"Invalid number '{text}'.") from exc

    # -------------------------------------------------------------- rendering
    def render(self, values: Mapping[str, Decimal] | None = None) -> str:
        """Human-readable formula. With ``values``, parameters are replaced by numbers."""
        return self._render(self._tree.body, values)

    def _render(self, node: ast.expr, values: Mapping[str, Decimal] | None) -> str:
        if isinstance(node, ast.Constant):
            return plain(self._literal(node))
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return "π"
            if values is not None and node.id in values:
                return plain(values[node.id])
            return node.id
        if isinstance(node, ast.UnaryOp):
            inner = self._render(node.operand, values)
            if _precedence(node.operand) < _UNARY_PRECEDENCE:
                inner = f"({inner})"
            return f"-{inner}" if isinstance(node.op, ast.USub) else inner
        if isinstance(node, ast.BinOp):
            prec = _PRECEDENCE[type(node.op)]
            left = self._render(node.left, values)
            right = self._render(node.right, values)
            left_prec, right_prec = _precedence(node.left), _precedence(node.right)
            if isinstance(node.op, ast.Pow):
                if left_prec <= prec:
                    left = f"({left})"
                if isinstance(node.right, ast.Constant) and right in _SUPERSCRIPTS:
                    return f"{left}{_SUPERSCRIPTS[right]}"
                if right_prec < prec:
                    right = f"({right})"
                return f"{left}^{right}"
            if left_prec < prec:
                left = f"({left})"
            non_associative = isinstance(node.op, ast.Sub | ast.Div)
            if right_prec < prec or (non_associative and right_prec == prec):
                right = f"({right})"
            return f"{left} {_SYMBOLS[type(node.op)]} {right}"
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            args = ", ".join(self._render(a, values) for a in node.args)
            return f"{node.func.id}({args})"
        raise _fail("Unsupported formula element.")


def _precedence(node: ast.expr) -> int:
    if isinstance(node, ast.BinOp):
        return _PRECEDENCE[type(node.op)]
    if isinstance(node, ast.UnaryOp):
        return _UNARY_PRECEDENCE
    return 10  # atoms: numbers, names, calls


def _describe(exponents: Exponents) -> str:
    names = {
        (1, 0): "length",
        (2, 0): "area",
        (3, 0): "volume",
        (0, 1): "mass",
        (-1, 1): "mass per length",
        (0, 0): "plain number",
    }
    return names.get(exponents, f"L^{exponents[0]}·M^{exponents[1]}")


_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Call,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.UAdd,
    ast.USub,
)


def _validate(tree: ast.Expression) -> None:
    for count, node in enumerate(ast.walk(tree), start=1):
        if count > MAX_NODES:
            raise _fail("The formula is too long.")
        if not isinstance(node, _ALLOWED_NODES):
            raise _fail(f"'{type(node).__name__}' is not allowed in a formula.")
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, int | float)
        ):
            raise _fail("Only numbers are allowed as constants.")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise _fail(f"Invalid name '{node.id}'.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise _fail(
                    "Unknown function. Allowed: " + ", ".join(sorted(FUNCTIONS)) + ".",
                )
            if node.keywords:
                raise _fail("Named arguments are not allowed.")
    # A function name used as a plain value (e.g. 'sqrt * 2') is not valid.
    call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FUNCTIONS and id(node) not in call_funcs:
            raise _fail(f"'{node.id}' is a function and must be called, e.g. {node.id}(x).")


def compile_expression(source: str) -> CompiledExpression:
    if not source or not source.strip():
        raise _fail("The formula is empty.")
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise _fail(f"The formula is longer than {MAX_EXPRESSION_LENGTH} characters.")
    normalised = _normalise(source.strip())
    try:
        tree = ast.parse(normalised, mode="eval")
    except SyntaxError as exc:
        raise _fail("The formula could not be read. Check brackets and operators.") from exc
    _validate(tree)
    return CompiledExpression(source.strip(), normalised, tree)
