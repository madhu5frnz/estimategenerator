"""Guardrails applied to every provider's output before anyone sees it.

The provider (rules, mock or LLM) only proposes. This module decides what is shown:

* ``template_id`` must be a known template; otherwise the component becomes a custom item
  with no quantity.
* Parameters must belong to the template; others are dropped with a warning.
* Units must parse and match the parameter's dimension.
* ``source_text`` must really occur in the user's text. A value that cannot be traced to
  the text is not trusted: it is shown as "needs confirmation".
* A required parameter without a value is missing and blocks the component until the
  user enters it or explicitly accepts a suggested default.
* Neutral template defaults (one instance, no deduction) are applied and labelled.
* When every value is present, the engine calculates a preview quantity.
"""

from __future__ import annotations

from typing import Any

from app.ai.schemas import ExtractionResult
from app.ai.text import appears_in
from app.domain.numeric import InvalidNumberError, plain, to_decimal
from app.domain.quantity import BUILTIN_TEMPLATES, CalculationError, ParamInput, evaluate_template
from app.domain.units import Dimension, UnitError, default_registry

TEMPLATES = {t.id: t for t in BUILTIN_TEMPLATES}

STATUS_OK = "ok"
STATUS_CONFIRM = "needs_confirmation"
STATUS_MISSING = "missing"
STATUS_DEFAULT = "template_default"


def _number(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return plain(to_decimal(value))
    except InvalidNumberError:
        return None


def review(result: ExtractionResult, text: str, *, provider: str) -> dict[str, Any]:
    registry = default_registry()
    warnings: list[str] = []
    components: list[dict[str, Any]] = []
    custom_items = [
        {
            "key": f"x{i}",
            "description": c.description,
            "source_text": c.source_text,
            "include": True,
        }
        for i, c in enumerate(result.custom_items, start=1)
    ]
    questions: dict[tuple[str, str], str] = {
        (m.component_name, m.parameter): m.question for m in result.missing_information
    }

    for index, comp in enumerate(result.components, start=1):
        template = TEMPLATES.get(comp.template_id)
        if template is None:
            warnings.append(
                f"'{comp.component_name}' could not be matched to a standard formula; it was "
                "added as an item without a quantity."
            )
            custom_items.append(
                {"key": f"x{len(custom_items) + 1}", "description": comp.component_name,
                 "source_text": None, "include": True}
            )  # fmt: skip
            continue

        given = {p.name: p for p in comp.parameters}
        for unknown in sorted(set(given) - {p.name for p in template.parameters}):
            warnings.append(f"Ignored unknown input '{unknown}' for {comp.component_name}.")

        params: list[dict[str, Any]] = []
        for tp in template.parameters:
            p = given.get(tp.name)
            entry: dict[str, Any] = {
                "name": tp.name,
                "label": tp.label,
                "dimension": tp.dimension.value,
                "required": tp.required,
                "value": None,
                "unit": None,
                "source_text": None,
                "status": STATUS_MISSING,
                "note": None,
                "suggested_default": None,
                "question": questions.get((comp.component_name, tp.name)),
            }
            if p is not None and p.suggested_default is not None:
                entry["suggested_default"] = {
                    "value": _number(p.suggested_default.value),
                    "unit": p.suggested_default.unit,
                    "reason": p.suggested_default.reason,
                }
            value = _number(p.value) if p is not None else None
            if value is not None and p is not None:
                entry["value"] = value
                entry["source_text"] = p.source_text
                entry["status"] = STATUS_OK
                unit = p.unit
                if tp.dimension is Dimension.COUNT:
                    entry["unit"] = None
                else:
                    try:
                        parsed = registry.parse(unit or "")
                        if parsed.dimension is not tp.dimension:
                            raise UnitError("UNIT_MISMATCH", "wrong dimension")
                        entry["unit"] = parsed.code
                    except UnitError:
                        entry["unit"] = None
                        entry["status"] = STATUS_CONFIRM
                        entry["note"] = (
                            f"Unit '{unit}' is not a {tp.dimension.value} unit; choose the unit."
                        )
                if entry["status"] == STATUS_OK and not (
                    p.source_text and appears_in(p.source_text, text)
                ):
                    entry["status"] = STATUS_CONFIRM
                    entry["note"] = (
                        "This value could not be found in your description; please confirm it."
                    )
            elif not tp.required:
                entry["value"] = tp.default
                entry["unit"] = (
                    None
                    if tp.dimension is Dimension.COUNT
                    else registry.canonical(tp.dimension).code
                )
                entry["status"] = STATUS_DEFAULT
                entry["note"] = "Standard value for this formula; change it if needed."
            if entry["status"] == STATUS_MISSING and not entry["question"]:
                entry["question"] = (
                    f"Please enter the {tp.label.lower()} for {comp.component_name}."
                )
            params.append(entry)

        component = {
            "key": f"c{index}",
            "component_name": comp.component_name,
            "template_id": template.id,
            "template_version": template.version,
            "template_name": template.name,
            "output_unit": template.output_unit,
            "output_unit_display": registry.get(template.output_unit).display_name,
            "include": True,
            "parameters": params,
            "preview": None,
        }
        component["preview"] = preview(component)
        components.append(component)

    missing = [
        {"component_key": c["key"], "component_name": c["component_name"], "parameter": p["name"],
         "label": p["label"], "question": p["question"]}
        for c in components
        for p in c["parameters"]
        if p["status"] == STATUS_MISSING
    ]  # fmt: skip
    component_names = {c["component_name"] for c in components}
    for m in result.missing_information:
        if m.component_name not in component_names:  # custom items / general questions
            missing.append(
                {
                    "component_key": None,
                    "component_name": m.component_name,
                    "parameter": m.parameter,
                    "label": m.parameter,
                    "question": m.question,
                }
            )

    return {
        "provider": provider,
        "project_type": result.project_type,
        "components": components,
        "custom_items": custom_items,
        "missing_information": missing,
        "assumptions": list(result.assumptions),
        "warnings": warnings,
    }


def preview(component: dict[str, Any]) -> dict[str, str] | None:
    """Engine quantity for a component whose values are all present (not yet confirmed)."""
    template = TEMPLATES.get(component["template_id"])
    if template is None:
        return None
    inputs = {}
    for p in component["parameters"]:
        if p["value"] is None:
            return None
        inputs[p["name"]] = ParamInput(p["value"], p["unit"])
    try:
        result = evaluate_template(template, inputs)
    except CalculationError:
        return None
    return {
        "value": format(result.value, "f"),
        "unit": result.unit,
        "unit_display": result.unit_display,
        "substituted": result.substituted,
    }
