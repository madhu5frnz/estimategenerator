"""Stateless calculation and unit endpoints (standalone Quantity Calculator, S15).

Numbers are returned as strings so JavaScript never rounds them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from app.api.envelope import Envelope, ok
from app.core.errors import AppError
from app.domain.money import format_indian
from app.domain.numeric import InvalidNumberError
from app.domain.quantity import (
    BUILTIN_TEMPLATES,
    CalculationResult,
    CalculationTemplate,
    ParamInput,
    compile_expression,
    evaluate_expression,
    evaluate_template,
)
from app.domain.units import default_registry

router = APIRouter(tags=["calculations"])

NumberIn = Annotated[
    str | int | float | None, Field(description="Number; strings keep full precision")
]


# ----------------------------------------------------------------- schemas
class UnitOut(BaseModel):
    code: str
    display_name: str
    dimension: str
    is_canonical: bool
    decimal_places: int
    aliases: list[str]


class ConvertIn(BaseModel):
    value: NumberIn
    from_unit: str = Field(min_length=1, max_length=40)
    to_unit: str = Field(min_length=1, max_length=40)


class ConvertOut(BaseModel):
    value: str
    display: str
    from_unit: str
    to_unit: str


class TemplateParameterOut(BaseModel):
    name: str
    label: str
    dimension: str
    required: bool
    default: str | None
    canonical_unit: str | None


class TemplateOut(BaseModel):
    id: str
    version: int
    name: str
    category: str
    expression: str
    expression_display: str
    output_unit: str
    output_unit_display: str
    description: str
    parameters: list[TemplateParameterOut]


class ParamIn(BaseModel):
    value: NumberIn = None
    unit: str | None = Field(default=None, max_length=40)


class CalculateIn(BaseModel):
    template_id: str | None = Field(default=None, max_length=64)
    template_version: int | None = None
    expression: str | None = Field(default=None, max_length=500)
    output_unit: str | None = Field(default=None, max_length=40)
    parameters: dict[str, ParamIn] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def _one_source(self) -> CalculateIn:
        if (self.template_id is None) == (self.expression is None):
            raise ValueError("Provide either template_id or expression.")
        if self.expression is not None and not self.output_unit:
            raise ValueError("output_unit is required for a custom expression.")
        return self


class ResolvedInputOut(BaseModel):
    name: str
    label: str
    value: str
    unit: str | None
    formula_value: str
    formula_unit: str | None
    source: str


class StepOut(BaseModel):
    kind: str
    text: str


class CalculationOut(BaseModel):
    value: str
    value_raw: str
    display: str
    unit: str
    unit_display: str
    expression: str
    substituted: str
    inputs: list[ResolvedInputOut]
    steps: list[StepOut]
    template_id: str | None
    template_version: int | None
    engine_version: str
    check: str = Field(
        default="Calculation check passed",
        description="Arithmetic and unit checks only; not a confirmation of engineering "
        "correctness.",
    )


class ExpressionIn(BaseModel):
    expression: str = Field(max_length=500)


class ExpressionOut(BaseModel):
    expression_display: str
    parameters: list[str]


# ---------------------------------------------------------------- helpers
def _find_template(template_id: str, version: int | None) -> CalculationTemplate:
    matches = [t for t in BUILTIN_TEMPLATES if t.id == template_id]
    if version is not None:
        matches = [t for t in matches if t.version == version]
    if not matches:
        raise AppError("NOT_FOUND", f"Unknown calculation template '{template_id}'.", 404)
    return max(matches, key=lambda t: t.version)


def _template_out(t: CalculationTemplate) -> TemplateOut:
    registry = default_registry()
    return TemplateOut(
        id=t.id,
        version=t.version,
        name=t.name,
        category=t.category,
        expression=t.expression,
        expression_display=compile_expression(t.expression).render(),
        output_unit=t.output_unit,
        output_unit_display=registry.get(t.output_unit).display_name,
        description=t.description,
        parameters=[
            TemplateParameterOut(
                name=p.name,
                label=p.label,
                dimension=p.dimension.value,
                required=p.required,
                default=p.default,
                canonical_unit=(
                    None if p.dimension.value == "count" else registry.canonical(p.dimension).code
                ),
            )
            for p in t.parameters
        ],
    )


def _calculation_out(r: CalculationResult) -> CalculationOut:
    unit = default_registry().get(r.unit)
    return CalculationOut(
        value=format(r.value, "f"),
        value_raw=format(r.value_raw, "f"),
        display=f"{format_indian(r.value, unit.decimal_places)} {unit.display_name}",
        unit=r.unit,
        unit_display=r.unit_display,
        expression=r.expression,
        substituted=r.substituted,
        inputs=[
            ResolvedInputOut(
                name=i.name,
                label=i.label,
                value=format(i.value, "f"),
                unit=i.unit,
                formula_value=format(i.formula_value, "f"),
                formula_unit=i.formula_unit,
                source=i.source,
            )
            for i in r.inputs
        ],
        steps=[StepOut(kind=s.kind, text=s.text) for s in r.steps],
        template_id=r.template_id,
        template_version=r.template_version,
        engine_version=r.engine_version,
    )


# --------------------------------------------------------------- endpoints
@router.get("/units", response_model=Envelope[list[UnitOut]])
def list_units() -> Envelope[list[UnitOut]]:
    return ok(
        [
            UnitOut(
                code=u.code,
                display_name=u.display_name,
                dimension=u.dimension.value,
                is_canonical=u.is_canonical,
                decimal_places=u.decimal_places,
                aliases=list(u.aliases),
            )
            for u in default_registry().units
        ]
    )


@router.post("/units/convert", response_model=Envelope[ConvertOut])
def convert_units(body: ConvertIn) -> Envelope[ConvertOut]:
    if body.value is None:
        raise AppError("VALIDATION_ERROR", "value is required.")
    registry = default_registry()
    src, dst = registry.parse(body.from_unit), registry.parse(body.to_unit)
    try:
        value = registry.convert(body.value, src.code, dst.code)
    except InvalidNumberError as exc:
        raise AppError("INVALID_INPUT", str(exc)) from exc
    return ok(
        ConvertOut(
            value=format(value, "f"),
            display=f"{format_indian(value, dst.decimal_places)} {dst.display_name}",
            from_unit=src.code,
            to_unit=dst.code,
        )
    )


@router.get("/calculation-templates", response_model=Envelope[list[TemplateOut]])
def list_templates(category: str | None = None) -> Envelope[list[TemplateOut]]:
    latest: dict[str, CalculationTemplate] = {}
    for t in BUILTIN_TEMPLATES:
        if category and t.category != category:
            continue
        if t.id not in latest or t.version > latest[t.id].version:
            latest[t.id] = t
    return ok([_template_out(t) for t in latest.values()])


@router.post("/calculate", response_model=Envelope[CalculationOut])
def calculate(body: CalculateIn) -> Envelope[CalculationOut]:
    inputs = {k: ParamInput(v.value, v.unit) for k, v in body.parameters.items()}
    if body.template_id is not None:
        template = _find_template(body.template_id, body.template_version)
        result = evaluate_template(template, inputs)
    else:
        assert body.expression is not None and body.output_unit is not None
        output_unit = default_registry().parse(body.output_unit).code
        result = evaluate_expression(body.expression, inputs, output_unit)
    return ok(_calculation_out(result))


@router.post("/calculate/validate-expression", response_model=Envelope[ExpressionOut])
def validate_expression(body: ExpressionIn) -> Envelope[ExpressionOut]:
    compiled = compile_expression(body.expression)
    return ok(
        ExpressionOut(expression_display=compiled.render(), parameters=sorted(compiled.names))
    )
