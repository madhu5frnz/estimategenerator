"""Each rule has a case that triggers it and the clean baseline shows it does not fire."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.domain.validation.rules import (
    PASSED_MESSAGE,
    ItemFacts,
    LineFacts,
    ParamFacts,
    VersionFacts,
    validate,
)

D = Decimal
TODAY = date(2026, 9, 27)


def line(**kw: object) -> LineFacts:
    base = dict(id="l1", quantity=D("412.500"), is_deduction=False, recomputed=D("412.500"),
                recompute_error=None, template_id="road_layer",
                canonical_inputs={"length": D(500), "width": D("5.5"), "thickness": D("0.15")})  # fmt: skip
    return LineFacts(**{**base, **kw})  # type: ignore[arg-type]


def item(**kw: object) -> ItemFacts:
    base = dict(id="i1", sl_no="1.1", description="PCC M30 for CC pavement", unit="cum",
                unit_places=3, quantity=D("412.500"), quantity_source="measurements",
                rate=D("6450.00"), amount=D("2660625.00"), rate_item_id=None, rate_unit=None,
                rate_verification=None, rate_effective_to=None, provenance="user_entered",
                lines=(line(),))  # fmt: skip
    return ItemFacts(**{**base, **kw})  # type: ignore[arg-type]


def facts(**kw: object) -> VersionFacts:
    base = dict(items=(item(),), params=(), gst_applicable=False, gst_rate=None, gst_mode="exclusive",
                works_subtotal=D("2660625.00"), snapshot_works_subtotal=None, today=TODAY)  # fmt: skip
    return VersionFacts(**{**base, **kw})  # type: ignore[arg-type]


def rules_of(f: VersionFacts) -> set[str]:
    return {x.rule_id for x in validate(f).findings}


def test_clean_estimate_passes_calculation_checks() -> None:
    report = validate(facts())
    assert report.status == "green"
    assert report.findings == ()
    assert report.message == PASSED_MESSAGE
    assert "confirmed" not in report.message.lower()


@pytest.mark.parametrize(
    ("changes", "rule", "severity"),
    [
        ({"items": ()}, "EMPTY_ESTIMATE", "yellow"),
        ({"items": (item(unit=None),)}, "UNIT_MISSING", "red"),
        (
            {"items": (item(quantity=None, quantity_source="manual", lines=(), amount=None),)},
            "QTY_MISSING",
            "yellow",
        ),
        (
            {
                "items": (
                    item(
                        quantity=D("-2.250"),
                        lines=(
                            line(quantity=D("2.250"), recomputed=D("2.250"), is_deduction=True),
                        ),
                        amount=D("-14512.50"),
                    ),
                )
            },
            "QTY_NEGATIVE",
            "red",
        ),
        (
            {
                "items": (
                    item(quantity=D("0.000"), quantity_source="manual", lines=(), amount=D("0.00")),
                )
            },
            "QTY_ZERO",
            "yellow",
        ),
        (
            {
                "items": (
                    item(
                        quantity=D("2000000"),
                        quantity_source="manual",
                        lines=(),
                        rate=D(1),
                        amount=D("2000000.00"),
                    ),
                )
            },
            "QTY_OUTLIER_HIGH",
            "yellow",
        ),
        ({"items": (item(rate=None, amount=None),)}, "RATE_MISSING", "red"),
        ({"items": (item(rate_unit="sqm"),)}, "UNIT_RATE_MISMATCH", "red"),
        ({"items": (item(rate_verification="demo"),)}, "DEMO_RATE_USED", "yellow"),
        ({"items": (item(rate_effective_to=date(2026, 3, 31)),)}, "RATE_EXPIRED", "yellow"),
        ({"items": (item(amount=D("2660000.00")),)}, "TOTAL_MISMATCH", "red"),
        (
            {"items": (item(quantity=D("500.000"), amount=D("3225000.00")),)},
            "TOTAL_MISMATCH",
            "red",
        ),
        (
            {"items": (item(lines=(line(recompute_error="Parameter 'x' has no value."),)),)},
            "FORMULA_ERROR",
            "red",
        ),
        ({"items": (item(lines=(line(recomputed=D("400.000")),)),)}, "LINE_RECALC_MISMATCH", "red"),
        (
            {"items": (item(lines=(line(canonical_inputs={"thickness": D("1.5")}),)),)},
            "INPUT_OUTLIER",
            "yellow",
        ),
        (
            {"items": (item(), item(id="i2", sl_no="1.2", description="PCC M30 for CC Pavement."))},
            "DUPLICATE_ITEM",
            "yellow",
        ),
        (
            {
                "items": (
                    item(rate_item_id="r1"),
                    item(id="i2", sl_no="1.2", description="Other", rate_item_id="r1"),
                )
            },
            "DUPLICATE_ITEM",
            "yellow",
        ),
        ({"items": (item(provenance="rule_extracted"),)}, "AI_REVIEW", "yellow"),
        (
            {"params": (ParamFacts("p1", "gsb_width", "GSB width", None, "user_entered", 1),)},
            "PARAM_MISSING",
            "red",
        ),
        (
            {"params": (ParamFacts("p1", "gsb_width", "GSB width", None, "user_entered", 0),)},
            "PARAM_MISSING",
            "yellow",
        ),
        (
            {
                "params": (
                    ParamFacts("p1", "gsb_width", "GSB width", D("5.5"), "default_accepted", 1),
                )
            },
            "DEFAULT_ACCEPTED",
            "yellow",
        ),
        ({"gst_applicable": True, "gst_rate": None}, "GST_INCONSISTENT", "red"),
        ({"gst_applicable": True, "gst_rate": D(40)}, "GST_INCONSISTENT", "red"),
        ({"gst_applicable": True, "gst_rate": D(15)}, "GST_UNUSUAL_RATE", "yellow"),
        ({"snapshot_works_subtotal": D("1.00")}, "ABSTRACT_MISMATCH", "red"),
    ],
)
def test_rule_fires(changes: dict[str, object], rule: str, severity: str) -> None:
    report = validate(replace(facts(), **changes))  # type: ignore[arg-type]
    matching = [f for f in report.findings if f.rule_id == rule]
    assert matching, [f.rule_id for f in report.findings]
    assert matching[0].severity == severity
    expected_status = "red" if any(f.severity == "red" for f in report.findings) else "yellow"
    assert report.status == expected_status


def test_negatives_do_not_fire() -> None:
    clean = facts(
        items=(
            item(rate_verification="user_entered", rate_effective_to=date(2027, 3, 31)),
            item(id="i2", sl_no="1.2", description="GSB", unit="cum", rate_item_id="r2", rate_unit="cum",
                 quantity=D("275.000"), rate=D("1800"), amount=D("495000.00"),
                 lines=(line(id="l2", quantity=D("275.000"), recomputed=D("275.000")),)),
        ),
        params=(ParamFacts("p1", "road_length", "Road length", D(500), "rule_extracted", 2),),
        gst_applicable=True, gst_rate=D(18), snapshot_works_subtotal=D("2660625.00"),
    )  # fmt: skip
    assert rules_of(clean) == set()


def test_findings_are_sorted_errors_first_and_carry_item_refs() -> None:
    report = validate(facts(items=(item(rate_verification="demo", unit=None),)))
    assert [f.severity for f in report.findings] == ["red", "yellow"]
    assert report.findings[0].sl_no == "1.1"
    assert report.findings[0].entity_type == "boq_item"
    assert report.message == "1 error(s), 1 item(s) to review"
