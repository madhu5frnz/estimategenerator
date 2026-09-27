"""Rules extractor + guardrails against the golden set (no network, no database)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.ai.postprocess import STATUS_CONFIRM, STATUS_MISSING, review
from app.ai.rules import extract
from app.ai.schemas import ExtractedComponent, ExtractedParameter, ExtractionResult
from app.ai.text import appears_in, normalise
from app.domain.numeric import to_decimal
from tests.conftest import FIXTURES

CASES = json.loads((FIXTURES / "golden" / "extraction" / "cases.json").read_text())["cases"]


def reviewed(text: str) -> dict[str, Any]:
    return review(extract(text), normalise(text), provider="rules")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_case(case: dict[str, Any]) -> None:
    out = reviewed(case["text"])
    assert out["project_type"] == case["project_type"]
    by_name = {c["component_name"]: c for c in out["components"]}
    assert set(by_name) == set(case["expected"])
    for name, params in case["expected"].items():
        got = {p["name"]: p for p in by_name[name]["parameters"]}
        assert set(got) >= set(params), name
        for pname, expected in params.items():
            p = got[pname]
            if expected is None:
                assert p["status"] == STATUS_MISSING, (name, pname, p)
                assert p["value"] is None
                assert p["question"]
            else:
                assert to_decimal(p["value"]) == to_decimal(expected[0]), (name, pname, p)
                assert p["unit"] == expected[1], (name, pname, p)
                assert p["status"] in ("ok", "template_default"), (name, pname, p)
    for name, params in case.get("suggested", {}).items():
        got = {p["name"]: p for p in by_name[name]["parameters"]}
        for pname, (value, unit) in params.items():
            suggestion = got[pname]["suggested_default"]
            assert suggestion and to_decimal(suggestion["value"]) == to_decimal(value)
            assert suggestion["unit"] == unit
            assert got[pname]["value"] is None  # offered, never applied
    assert sorted(c["description"] for c in out["custom_items"]) == sorted(
        case.get("custom_items", [])
    )
    for name, quantity in case.get("preview", {}).items():
        assert by_name[name]["preview"]["value"] == quantity


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_no_value_is_invented(case: dict[str, Any]) -> None:
    """False-fill guard: every extracted value is quoted from the text and contains it."""
    text = normalise(case["text"])
    for component in extract(case["text"]).components:
        for p in component.parameters:
            if p.value is None:
                continue
            assert p.source_text and appears_in(p.source_text, text), p
            digits = p.source_text.replace(",", "")
            number = str(p.value).rstrip("0").rstrip(".")
            from_digits = any(tok.startswith(number) for tok in digits.split())
            # Counts may be written in words ("both sides" = 2).
            from_words = p.source_text.lower() in {"both sides", "one side", "two sides"}
            assert from_digits or from_words, p


def test_normalise_digits_and_controls() -> None:
    assert normalise("౫౦౦\u0000 m  ५.५") == "500 m 5.5"
    assert appears_in("500  M long", "a 500 m long road")
    assert not appears_in("600 m long", "a 500 m long road")
    assert not appears_in("  ", "anything")


# ----------------------------------------------------------- guardrails
def llm_like(**component: Any) -> ExtractionResult:
    return ExtractionResult(project_type="road", components=[ExtractedComponent(**component)])


def test_unknown_template_becomes_item_without_quantity() -> None:
    out = review(llm_like(component_name="Bridge deck", template_id="bridge_magic", parameters=[]),
                 "bridge deck", provider="mock")  # fmt: skip
    assert out["components"] == []
    assert [c["description"] for c in out["custom_items"]] == ["Bridge deck"]
    assert "could not be matched" in out["warnings"][0]


def test_value_not_in_text_needs_confirmation() -> None:
    text = "CC road 500 m long, 5.5 m wide"
    result = llm_like(
        component_name="CC pavement", template_id="road_layer",
        parameters=[
            ExtractedParameter(name="length", value=500, unit="m", source_text="500 m long"),
            ExtractedParameter(name="width", value=5.5, unit="m", source_text="5.5 m wide"),
            # Invented: the text never says 200 mm.
            ExtractedParameter(name="thickness", value=200, unit="mm", source_text="200 mm thick"),
            ExtractedParameter(name="colour", value=1, unit=None, source_text="red"),
        ],
    )  # fmt: skip
    out = review(result, text, provider="mock")
    params = {p["name"]: p for p in out["components"][0]["parameters"]}
    assert params["length"]["status"] == "ok"
    assert params["thickness"]["status"] == STATUS_CONFIRM
    assert "could not be found" in params["thickness"]["note"]
    assert "Ignored unknown input 'colour'" in out["warnings"][0]


def test_wrong_or_missing_unit_needs_confirmation() -> None:
    text = "CC road 500 m long 5.5 m wide 150 thick"
    result = llm_like(
        component_name="CC pavement", template_id="road_layer",
        parameters=[
            ExtractedParameter(name="length", value=500, unit="sqm", source_text="500 m long"),
            ExtractedParameter(name="width", value=5.5, unit="m", source_text="5.5 m wide"),
            ExtractedParameter(name="thickness", value=150, unit=None, source_text="150 thick"),
        ],
    )  # fmt: skip
    params = {
        p["name"]: p for p in review(result, text, provider="mock")["components"][0]["parameters"]
    }
    assert params["length"]["status"] == STATUS_CONFIRM and params["length"]["unit"] is None
    assert params["thickness"]["status"] == STATUS_CONFIRM
    assert review(result, text, provider="mock")["components"][0]["preview"] is None


def test_extra_keys_from_a_model_are_ignored() -> None:
    raw = {
        "project_type": "road",
        "components": [{
            "component_name": "CC pavement", "template_id": "road_layer", "quantity": 999,
            "rate": 7500, "amount": 1, "parameters": [
                {"name": "length", "value": 10, "unit": "m", "source_text": "10 m", "quantity": 5}],
        }],
        "total": 123,
    }  # fmt: skip
    result = ExtractionResult.model_validate(raw)
    dumped = result.model_dump()
    assert "total" not in dumped
    assert "quantity" not in dumped["components"][0]
    assert "rate" not in dumped["components"][0]
