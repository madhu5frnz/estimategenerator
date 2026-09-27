from decimal import Decimal
from typing import Any

import pytest

from app.domain import ENGINE_VERSION
from app.domain.quantity import (
    BUILTIN_TEMPLATES,
    CalculationError,
    CalculationTemplate,
    FormulaError,
    MissingParameterError,
    ParamInput,
    TemplateParameter,
    check_template,
    evaluate_expression,
    evaluate_template,
)
from app.domain.units import Dimension

TEMPLATES = {t.id: t for t in BUILTIN_TEMPLATES}


def inputs(**kw: tuple[Any, str | None]) -> dict[str, ParamInput]:
    return {k: ParamInput(v, u) for k, (v, u) in kw.items()}


def test_golden_cases(golden_quantities: list[dict[str, Any]]) -> None:
    assert golden_quantities
    for case in golden_quantities:
        template = TEMPLATES[case["template_id"]]
        result = evaluate_template(
            template, {k: ParamInput(v, u) for k, (v, u) in case["inputs"].items()}
        )
        expected = case["expected"]
        assert format(result.value, "f") == expected["value"], case["name"]
        assert result.unit == expected["unit"], case["name"]
        assert result.substituted == expected["substituted"], case["name"]


def test_brief_example_full_trace() -> None:
    result = evaluate_template(
        TEMPLATES["road_layer"],
        inputs(length=("500", "m"), width=("5.5", "m"), thickness=("150", "mm")),
    )
    assert result.value == Decimal("412.500")
    assert result.value_raw == Decimal("412.5")
    assert result.unit_display == "Cum"
    assert result.expression == "length × width × thickness"
    assert result.template_id == "road_layer"
    assert result.template_version == 1
    assert result.engine_version == ENGINE_VERSION
    assert [s.text for s in result.steps] == [
        "Formula: length × width × thickness",
        "length = 500 m",
        "width = 5.5 m",
        "thickness = 150 mm = 0.15 m",
        "Quantity = 500 × 5.5 × 0.15",
        "Quantity = 412.500 Cum",
    ]
    thickness = result.inputs[2]
    assert (thickness.unit, thickness.formula_unit) == ("mm", "m")
    assert thickness.formula_value == Decimal("0.15")
    assert thickness.source == "input"


def test_float_inputs_do_not_leak_binary_error() -> None:
    result = evaluate_template(
        TEMPLATES["road_layer"],
        inputs(length=(500, "m"), width=(5.5, "m"), thickness=(0.15, "m")),
    )
    assert result.value_raw == Decimal("412.5")


def test_template_default_is_marked() -> None:
    result = evaluate_template(
        TEMPLATES["volume_lbh"], inputs(L=("2", "m"), B=("3", "m"), H=("4", "m"))
    )
    n = next(i for i in result.inputs if i.name == "N")
    assert n.source == "template_default"
    assert "N = 1 (template default)" in [s.text for s in result.steps]
    assert result.value == Decimal("24.000")


def test_template_default_with_unit() -> None:
    result = evaluate_template(
        TEMPLATES["wall_masonry"], inputs(L=("10", "m"), H=("3", "m"), T=("0.2", "m"))
    )
    opening = next(i for i in result.inputs if i.name == "openings_area")
    assert (opening.value, opening.unit, opening.source) == (0, "sqm", "template_default")
    assert result.value == Decimal("6.000")


def test_missing_parameters_block_calculation() -> None:
    with pytest.raises(MissingParameterError) as exc:
        evaluate_template(TEMPLATES["road_layer"], inputs(length=("500", "m"), width=(None, "m")))
    assert exc.value.code == "MISSING_PARAMETER"
    assert exc.value.details == {"parameters": ["width", "thickness"]}
    assert "Layer width" in exc.value.message


def test_blank_string_counts_as_missing() -> None:
    with pytest.raises(MissingParameterError):
        evaluate_template(
            TEMPLATES["road_layer"],
            inputs(length=("500", "m"), width=("  ", "m"), thickness=("1", "m")),
        )


@pytest.mark.parametrize(
    ("params", "code"),
    [
        (
            {"length": ("500", "m"), "width": ("5.5", "m"), "thickness": ("150", None)},
            "UNIT_REQUIRED",
        ),
        (
            {"length": ("500", "m"), "width": ("5.5", "sqm"), "thickness": ("1", "m")},
            "UNIT_MISMATCH",
        ),
        (
            {"length": ("500", "m"), "width": ("5.5", "furlong"), "thickness": ("1", "m")},
            "UNKNOWN_UNIT",
        ),
        ({"length": ("-5", "m"), "width": ("5.5", "m"), "thickness": ("1", "m")}, "INVALID_INPUT"),
        ({"length": ("abc", "m"), "width": ("5.5", "m"), "thickness": ("1", "m")}, "INVALID_INPUT"),
        (
            {"length": ("1", "m"), "width": ("1", "m"), "thickness": ("1", "m"), "x": ("1", None)},
            "UNKNOWN_PARAMETER",
        ),
    ],
)
def test_input_errors(params: dict[str, tuple[str, str | None]], code: str) -> None:
    with pytest.raises(CalculationError) as exc:
        evaluate_template(TEMPLATES["road_layer"], inputs(**params))
    assert exc.value.code == code


def test_negative_net_result_is_returned_for_validation_to_flag() -> None:
    result = evaluate_template(
        TEMPLATES["plaster_area"],
        inputs(L=("2", "m"), H=("1", "m"), faces=("1", None), openings_area=("5", "sqm")),
    )
    assert result.value == Decimal("-3.00")


def test_non_canonical_output_unit() -> None:
    result = evaluate_template(
        TEMPLATES["kerb_length"], inputs(length=("1", "km"), sides=("2", None))
    )
    assert (result.value, result.unit) == (Decimal("2000.00"), "rmt")
    assert result.steps[-1].text == "Quantity = 2000.00 Rmt (= 2000 m)"


def test_count_parameter_accepts_count_units() -> None:
    result = evaluate_template(
        TEMPLATES["area_lb"], inputs(L=("2", "m"), B=("3", "m"), N=("4", "set"))
    )
    assert result.value == Decimal("24.00")


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES, ids=lambda t: t.id)
def test_builtin_templates_are_consistent(template: CalculationTemplate) -> None:
    check_template(template)


def test_template_ids_unique() -> None:
    keys = [(t.id, t.version) for t in BUILTIN_TEMPLATES]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    "template",
    [
        CalculationTemplate(
            "bad_names",
            1,
            "x",
            "t",
            "L * B",
            (TemplateParameter("L", "L", Dimension.LENGTH),),
            "sqm",
        ),
        CalculationTemplate(
            "bad_dims",
            1,
            "x",
            "t",
            "L * B",
            (
                TemplateParameter("L", "L", Dimension.LENGTH),
                TemplateParameter("B", "B", Dimension.LENGTH),
            ),
            "cum",
        ),
        CalculationTemplate(
            "bad_param_dim",
            1,
            "x",
            "t",
            "L",
            (TemplateParameter("L", "L", Dimension.LUMP_SUM),),
            "cum",
        ),
    ],
    ids=lambda t: t.id,
)
def test_check_template_rejects_inconsistent(template: CalculationTemplate) -> None:
    with pytest.raises(FormulaError) as exc:
        check_template(template)
    assert exc.value.code == "TEMPLATE_INVALID"


def test_custom_expression_infers_dimensions_from_units() -> None:
    result = evaluate_expression(
        "(L * H - door_w * door_h * doors) * T",
        inputs(
            L=("12", "ft"),
            H=("3", "m"),
            door_w=("1", "m"),
            door_h=("2.1", "m"),
            doors=("2", None),
            T=("230", "mm"),
        ),
        "cum",
    )
    # 12 ft = 3.6576 m → (3.6576 × 3 − 4.2) × 0.23 = 1.557744
    assert result.value == Decimal("1.558")
    assert result.template_id is None


def test_custom_expression_dimension_mismatch_with_output() -> None:
    with pytest.raises(FormulaError) as exc:
        evaluate_expression("L * B", inputs(L=("1", "m"), B=("1", "m")), "cum")
    assert exc.value.code == "UNIT_MISMATCH"
    assert "produces area" in exc.value.message


def test_custom_expression_rejects_lump_sum_units() -> None:
    with pytest.raises(CalculationError) as exc:
        evaluate_expression("a * 2", inputs(a=("1", "LS")), "cum")
    assert exc.value.code == "UNIT_MISMATCH"


def test_lump_sum_output_rejected() -> None:
    with pytest.raises(CalculationError):
        evaluate_expression("a", inputs(a=("1", None)), "ls")


def test_custom_expression_missing_value() -> None:
    with pytest.raises(MissingParameterError):
        evaluate_expression("L * B", inputs(L=("1", "m")), "sqm")
