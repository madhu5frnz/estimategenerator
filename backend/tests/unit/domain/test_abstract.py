from decimal import Decimal

import pytest

from app.domain.estimate.abstract import (
    AbstractError,
    ChargeSpec,
    GstConfig,
    SectionAmount,
    compute_abstract,
)
from app.domain.money import amount_in_words

D = Decimal
# Brief §12 sections (the brief's printed subtotal ₹26,25,000 is an arithmetic slip; the
# sum is ₹25,75,000).
SECTIONS = [
    SectionAmount("s1", 1, "Earthwork", D("250000.00")),
    SectionAmount("s2", 2, "GSB", D("450000.00")),
    SectionAmount("s3", 3, "CC Road", D("1550000.00")),
    SectionAmount("s4", 4, "Drainage", D("325000.00")),
]


def test_works_subtotal_only() -> None:
    a = compute_abstract(SECTIONS)
    assert a.works_subtotal == D("2575000.00")
    assert a.grand_total == D("2575000.00")
    assert a.gst == () and a.charges == ()


def test_wireframe_example_contingency_then_intra_state_gst() -> None:
    a = compute_abstract(
        SECTIONS,
        [ChargeSpec("c1", "Contingencies", "contingency", percentage=D("2.5"))],
        GstConfig(applicable=True, supply="intra", rate_pct=D(18)),
    )
    assert a.charges[0].amount == D("64375.00")
    assert a.subtotal_before_gst == D("2639375.00")
    assert [(g.name, g.rate_pct, g.amount) for g in a.gst] == [
        ("CGST", D(9), D("237543.75")),
        ("SGST", D(9), D("237543.75")),
    ]
    assert a.grand_total == D("3114462.50")
    assert amount_in_words(a.grand_total) == (
        "Rupees Thirty One Lakh Fourteen Thousand Four Hundred Sixty Two and Fifty Paise Only"
    )


def test_inter_state_igst_on_works_subtotal() -> None:
    a = compute_abstract(
        SECTIONS,
        [ChargeSpec("c1", "Contingencies", "contingency", percentage=D(3))],
        GstConfig(applicable=True, supply="inter", rate_pct=D(12), base="works_subtotal"),
    )
    assert [(g.name, g.amount) for g in a.gst] == [("IGST", D("309000.00"))]
    assert a.grand_total == D("2575000.00") + D("77250.00") + D("309000.00")


def test_inclusive_gst_is_shown_not_added() -> None:
    a = compute_abstract(
        [SectionAmount("s", 1, "Works", D("118000.00"))],
        gst=GstConfig(applicable=True, mode="inclusive", rate_pct=D(18)),
    )
    assert [(g.name, g.amount, g.included) for g in a.gst] == [
        ("CGST", D("9000.00"), True),
        ("SGST", D("9000.00"), True),
    ]
    assert a.gst_added == D("0.00")
    assert a.grand_total == D("118000.00")
    assert a.notes


def test_charge_bases_order_fixed_and_disabled() -> None:
    a = compute_abstract(
        SECTIONS,
        [
            ChargeSpec("c1", "Contingencies", "contingency", percentage=D(3)),
            ChargeSpec("c2", "Work-charged establishment", "work_charged_establishment",
                       percentage=D(2), base="running_total"),
            ChargeSpec("c3", "Seigniorage", "seigniorage", percentage=D(1), base="sections",
                       section_keys=("s2", "s3")),
            ChargeSpec("c4", "Quality control", "other", fixed_amount=D("15000")),
            ChargeSpec("c5", "Labour cess", "labour_cess", percentage=D(1), enabled=False),
        ],
    )  # fmt: skip
    c1, c2, c3, c4, c5 = a.charges
    assert c1.amount == D("77250.00")
    assert (c2.base_amount, c2.amount) == (D("2652250.00"), D("53045.00"))
    assert (c3.base_label, c3.base_amount, c3.amount) == (
        "section 2, 3",
        D("2000000.00"),
        D("20000.00"),
    )
    assert (c4.base_label, c4.amount) == ("fixed amount", D("15000.00"))
    assert (c5.enabled, c5.amount) == (False, D("0.00"))
    assert a.grand_total == D("2575000.00") + D("77250.00") + D("53045.00") + D("20000.00") + D(
        "15000.00"
    )


def test_percentages_round_to_the_paisa_half_up() -> None:
    a = compute_abstract(
        [SectionAmount("s", 1, "Works", D("1000.05"))],
        [ChargeSpec("c", "Contingencies", "contingency", percentage=D("2.5"))],
    )
    assert a.charges[0].amount == D("25.00")  # 25.00125 → 25.00
    a = compute_abstract(
        [SectionAmount("s", 1, "Works", D("1000.30"))],
        [ChargeSpec("c", "Contingencies", "contingency", percentage=D("2.5"))],
    )
    assert a.charges[0].amount == D("25.01")  # 25.0075 → 25.01


@pytest.mark.parametrize(
    ("rounding", "grand", "adjustment"),
    [
        ("none", "3114462.50", "0.00"),
        ("nearest_rupee", "3114463.00", "0.50"),
        ("nearest_10", "3114460.00", "-2.50"),
        ("nearest_100", "3114500.00", "37.50"),
        ("nearest_1000", "3114000.00", "-462.50"),
    ],
)
def test_grand_total_rounding(rounding: str, grand: str, adjustment: str) -> None:
    a = compute_abstract(
        SECTIONS,
        [ChargeSpec("c1", "Contingencies", "contingency", percentage=D("2.5"))],
        GstConfig(applicable=True, rate_pct=D(18)),
        rounding,  # type: ignore[arg-type]
    )
    assert (a.grand_total, a.rounding_adjustment) == (D(grand), D(adjustment))


def test_errors() -> None:
    with pytest.raises(AbstractError) as exc:
        compute_abstract(SECTIONS, gst=GstConfig(applicable=True))
    assert exc.value.code == "GST_RATE_REQUIRED"
    with pytest.raises(AbstractError) as exc:
        compute_abstract(SECTIONS, [ChargeSpec("c", "X", "other")])
    assert exc.value.code == "CHARGE_INVALID"
    with pytest.raises(AbstractError):
        compute_abstract(
            SECTIONS, [ChargeSpec("c", "X", "other", percentage=D(1), fixed_amount=D(1))]
        )


def test_empty_sections_and_missing_section_keys() -> None:
    a = compute_abstract(
        [], [ChargeSpec("c", "Seigniorage", "seigniorage", percentage=D(1), base="sections",
                        section_keys=("gone",))]
    )  # fmt: skip
    assert (a.works_subtotal, a.charges[0].base_label, a.grand_total) == (
        D("0.00"),
        "no sections",
        D("0.00"),
    )
