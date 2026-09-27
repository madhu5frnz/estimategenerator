"""Deterministic quantity engine.

Takes a template (or a custom formula) and user-confirmed parameters with units, and
returns a traceable result: the formula, every input before and after unit conversion,
the substituted arithmetic, and the rounded quantity. The AI never reaches this module
with anything but parameters; it cannot supply a quantity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.domain import ENGINE_VERSION
from app.domain.numeric import InvalidNumberError, Number, plain, round_half_up, to_decimal
from app.domain.quantity.expression import (
    CalculationError,
    CompiledExpression,
    Exponents,
    FormulaError,
    Quantity,
    compile_expression,
)
from app.domain.quantity.templates import CalculationTemplate
from app.domain.units.registry import Dimension, Unit, UnitError, UnitRegistry, default_registry


class MissingParameterError(CalculationError):
    def __init__(self, missing: list[tuple[str, str]]) -> None:
        labels = ", ".join(label for _, label in missing)
        super().__init__(
            "MISSING_PARAMETER",
            f"Required value missing: {labels}.",
            {"parameters": [name for name, _ in missing]},
        )


@dataclass(frozen=True)
class ParamInput:
    value: Number | None
    unit: str | None = None


@dataclass(frozen=True)
class ResolvedInput:
    name: str
    label: str
    value: Decimal  # as entered
    unit: str | None  # unit code as entered (None for plain numbers / counts)
    formula_value: Decimal  # value used in the formula (canonical unit)
    formula_unit: str | None  # canonical unit code
    source: str  # 'input' | 'template_default'


@dataclass(frozen=True)
class CalculationStep:
    kind: str  # 'formula' | 'input' | 'substitution' | 'result'
    text: str


@dataclass(frozen=True)
class CalculationResult:
    value: Decimal  # rounded to the output unit's decimal places
    value_raw: Decimal  # unrounded, in the output unit
    unit: str
    unit_display: str
    expression: str  # symbolic: 'length × width × thickness'
    substituted: str  # '500 × 5.5 × 0.15'
    inputs: tuple[ResolvedInput, ...]
    steps: tuple[CalculationStep, ...]
    template_id: str | None
    template_version: int | None
    engine_version: str = ENGINE_VERSION


@dataclass(frozen=True)
class _Slot:
    name: str
    label: str
    dimension: Dimension | None  # None = infer from the unit (custom formulas)
    default: str | None


def _unit_label(registry: UnitRegistry, code: str | None) -> str:
    return registry.get(code).display_name if code else ""


def _format_with_unit(registry: UnitRegistry, value: Decimal, code: str | None) -> str:
    label = _unit_label(registry, code)
    return f"{plain(value)} {label}".rstrip()


def _formula_exponents(unit: Unit) -> Exponents:
    exponents = unit.dimension.exponents
    if exponents is None:
        raise CalculationError(
            "UNIT_MISMATCH", f"'{unit.display_name}' cannot be used inside a formula."
        )
    return exponents


def _resolve(
    slots: list[_Slot], inputs: Mapping[str, ParamInput], registry: UnitRegistry
) -> tuple[list[ResolvedInput], dict[str, Quantity]]:
    known = {s.name for s in slots}
    unknown = sorted(set(inputs) - known)
    if unknown:
        raise FormulaError(
            "UNKNOWN_PARAMETER",
            f"Unknown parameter(s): {', '.join(unknown)}.",
            {"parameters": unknown},
        )

    missing: list[tuple[str, str]] = []
    resolved: list[ResolvedInput] = []
    quantities: dict[str, Quantity] = {}
    for slot in slots:
        given = inputs.get(slot.name)
        source = "input"
        if (
            given is None
            or given.value is None
            or (isinstance(given.value, str) and not given.value.strip())
        ):
            if slot.default is None:
                missing.append((slot.name, slot.label))
                continue
            canonical_code = (
                None
                if slot.dimension in (None, Dimension.COUNT)
                else registry.canonical(slot.dimension).code
            )
            given = ParamInput(slot.default, canonical_code)
            source = "template_default"

        try:
            value = to_decimal(given.value)  # type: ignore[arg-type]
        except InvalidNumberError as exc:
            raise CalculationError(
                "INVALID_INPUT", f"{slot.label}: {exc}", {"parameter": slot.name}
            ) from exc
        if value < 0:
            raise CalculationError(
                "INVALID_INPUT",
                f"{slot.label} cannot be negative. Use a deduction line instead.",
                {"parameter": slot.name},
            )

        unit_code: str | None = None
        if given.unit is not None and given.unit.strip():
            try:
                unit = registry.parse(given.unit)
            except UnitError as exc:
                raise CalculationError(
                    exc.code, f"{slot.label}: {exc.message}", {"parameter": slot.name}
                ) from exc
            unit_code = unit.code
            if slot.dimension is not None and unit.dimension != slot.dimension:
                raise CalculationError(
                    "UNIT_MISMATCH",
                    f"{slot.label} needs a {slot.dimension.value} unit, not '{unit.display_name}'.",
                    {"parameter": slot.name},
                )
            exponents = _formula_exponents(unit)
            if unit.dimension is Dimension.COUNT:
                formula_value, formula_unit = value, None
            else:
                formula_value = registry.to_canonical(value, unit.code)
                formula_unit = registry.canonical(unit.dimension).code
        else:
            if slot.dimension not in (None, Dimension.COUNT):
                raise CalculationError(
                    "UNIT_REQUIRED",
                    f"{slot.label} needs a unit (e.g. m, mm, ft).",
                    {"parameter": slot.name},
                )
            exponents = (0, 0)
            formula_value, formula_unit = value, None

        resolved.append(
            ResolvedInput(
                slot.name, slot.label, value, unit_code, formula_value, formula_unit, source
            )
        )
        quantities[slot.name] = Quantity(formula_value, exponents)

    if missing:
        raise MissingParameterError(missing)
    return resolved, quantities


def _run(
    compiled: CompiledExpression,
    slots: list[_Slot],
    inputs: Mapping[str, ParamInput],
    output_unit: str,
    registry: UnitRegistry,
    template: CalculationTemplate | None,
) -> CalculationResult:
    out = registry.get(output_unit)
    out_exponents = _formula_exponents(out)
    resolved, quantities = _resolve(slots, inputs, registry)

    result = compiled.evaluate(quantities)
    if result.exponents != out_exponents:
        produced = Dimension.from_exponents(result.exponents)
        raise FormulaError(
            "UNIT_MISMATCH",
            f"The formula produces {produced.value if produced else 'an unsupported unit'}, "
            f"but the output unit {out.display_name} is {out.dimension.value}.",
        )

    raw = (
        result.value
        if out.dimension is Dimension.COUNT
        else registry.from_canonical(result.value, out.code)
    )
    rounded = round_half_up(raw, out.decimal_places)

    symbolic = compiled.render()
    substituted = compiled.render({r.name: r.formula_value for r in resolved})

    steps = [CalculationStep("formula", f"Formula: {symbolic}")]
    for r in resolved:
        text = f"{r.name} = {_format_with_unit(registry, r.value, r.unit)}"
        if r.unit and r.formula_unit and r.unit != r.formula_unit:
            text += f" = {_format_with_unit(registry, r.formula_value, r.formula_unit)}"
        if r.source == "template_default":
            text += " (template default)"
        steps.append(CalculationStep("input", text))
    steps.append(CalculationStep("substitution", f"Quantity = {substituted}"))
    conversion_note = ""
    if out.dimension is not Dimension.COUNT and not out.is_canonical:
        canonical = registry.canonical(out.dimension)
        conversion_note = f" (= {plain(result.value)} {canonical.display_name})"
    steps.append(
        CalculationStep(
            "result", f"Quantity = {format(rounded, 'f')} {out.display_name}{conversion_note}"
        )
    )

    return CalculationResult(
        value=rounded,
        value_raw=raw,
        unit=out.code,
        unit_display=out.display_name,
        expression=symbolic,
        substituted=substituted,
        inputs=tuple(resolved),
        steps=tuple(steps),
        template_id=template.id if template else None,
        template_version=template.version if template else None,
    )


def evaluate_template(
    template: CalculationTemplate,
    inputs: Mapping[str, ParamInput],
    registry: UnitRegistry | None = None,
) -> CalculationResult:
    registry = registry or default_registry()
    compiled = compile_expression(template.expression)
    slots = [_Slot(p.name, p.label, p.dimension, p.default) for p in template.parameters]
    return _run(compiled, slots, inputs, template.output_unit, registry, template)


def evaluate_expression(
    expression: str,
    inputs: Mapping[str, ParamInput],
    output_unit: str,
    registry: UnitRegistry | None = None,
) -> CalculationResult:
    """Custom formula: each parameter's dimension comes from the unit the user gives."""
    registry = registry or default_registry()
    compiled = compile_expression(expression)
    slots = [_Slot(name, name, None, None) for name in sorted(compiled.names)]
    return _run(compiled, slots, inputs, output_unit, registry, None)


def check_template(template: CalculationTemplate, registry: UnitRegistry | None = None) -> None:
    """Raise if a template is internally inconsistent (names or dimensions)."""
    registry = registry or default_registry()
    compiled = compile_expression(template.expression)
    declared = {p.name for p in template.parameters}
    if compiled.names != declared:
        raise FormulaError(
            "TEMPLATE_INVALID",
            f"Template '{template.id}' formula names {sorted(compiled.names)} do not match "
            f"its parameters {sorted(declared)}.",
        )
    probe: dict[str, Quantity] = {}
    for p in template.parameters:
        exponents = p.dimension.exponents
        if exponents is None:
            raise FormulaError(
                "TEMPLATE_INVALID", f"Parameter '{p.name}' has a non-formula dimension."
            )
        probe[p.name] = Quantity(Decimal(1), exponents)
    result = compiled.evaluate(probe)
    out_exponents = _formula_exponents(registry.get(template.output_unit))
    if result.exponents != out_exponents:
        raise FormulaError(
            "TEMPLATE_INVALID",
            f"Template '{template.id}' produces {result.exponents} but its output unit "
            f"'{template.output_unit}' needs {out_exponents}.",
        )
