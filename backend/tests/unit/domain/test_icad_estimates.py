"""The I&CAD engine reproduces the department's own estimates (reference/ts-2026-27)."""

from decimal import Decimal as D

from app.domain.icad import general_abstract as ga
from app.domain.icad import seigniorage as sg
from app.domain.icad.lead import mechanical_lead
from app.domain.icad.rate_analysis import (
    DataSheet,
    PerUnitAdjustment,
    Row,
    compute,
    or_say,
    sor_item_rate,
)

# SoR 2026-27, COM-LDLFT-2, Zone III (see app/data/ts_icad_2026_27/basic_rates.json)
ZONE_III = {
    "1": {"earth_sand": "48.20", "aggregate_stone": "46.50"},
    "2": {"earth_sand": "67.50", "aggregate_stone": "65.10"},
    "3": {"earth_sand": "90.00", "aggregate_stone": "90.00"},
    "4": {"earth_sand": "109.30", "aggregate_stone": "109.30"},
    "5": {"earth_sand": "128.60", "aggregate_stone": "128.60"},
    "per_km_5_30": {"earth_sand": "19.30", "aggregate_stone": "19.30"},
    "per_km_beyond_30": {"earth_sand": "16.10", "aggregate_stone": "16.10"},
}


def test_lead_statement_of_the_ut_estimate() -> None:
    assert mechanical_lead(ZONE_III, "earth_sand", D(16)).amount == D("292.70")  # Musi sand
    assert mechanical_lead(ZONE_III, "aggregate_stone", D(25)).amount == D("468.10")  # metal
    assert mechanical_lead(ZONE_III, "earth_sand", D(5)).amount == D("80.40")  # gravel
    assert mechanical_lead(ZONE_III, "earth_sand", D("0.8")).amount == D("0.00")  # initial lead
    far = mechanical_lead(ZONE_III, "earth_sand", D(35))
    assert far.amount == D("128.60") - D("48.20") + 25 * D("19.30") + 5 * D("16.10")


def m15_40mm() -> DataSheet:
    """IRR-CCDW-2-3 as in the UT estimate's 'Datas - 2026-27' sheet (rows 47-114)."""
    A, B, C = "A", "B", "C"
    rows = [
        Row(A, "Cement for mix", "kg", D("3998.8"), D("5.1")),
        Row(A, "Cement for incidentals @ 3 kg / cum", "kg", D("46.14"), D("5.1")),
        Row(A, "Coarse aggregate 40-20 mm", "cum", D("6.921"), D(1107)),
        Row(A, "Coarse aggregate 20-10 mm", "cum", D("4.1526"), D(1230)),
        Row(A, "Coarse aggregate 10 mm below", "cum", D("2.7684"), D(945)),
        Row(A, "Fine aggregate", "cum", D("6.152"), D(777)),
        Row(A, "Super Plasticizer", "kg", D("15.9952"), D(78)),
        Row(A, "Use rate of shuttering for 40 uses", "sqm", D("15.38"), D("352.32")),
        Row(A, "Scaffolding @ 10 % of shuttering", "%", pct=D(10), pct_of_row=7),
        Row(A, "Sundries", "LS", D("0.5"), D(29)),
        Row(B, "Concrete mixer 300/200 ltr (diesel)", "Hour", D(8), D("67.2")),
        Row(B, "Fuel / Energy charges", "Hour", D(8), D("142.8")),
        Row(B, "5 hp pump (diesel)", "Hour", D("0.5"), D("10.7")),
        Row(B, "Fuel / Energy charges", "Hour", D("0.5"), D("142.8")),
        Row(B, "Water tanker 8000 ltr", "Hour", D(1), D("495.6")),
        Row(B, "Fuel / Energy charges", "Hour", D(1), D("539.6")),
        Row(B, "Needle vibrator 40 mm dia (petrol)", "Hour", D(8), D("7.3")),
        Row(B, "Fuel / Energy charges", "Hour", D(8), D("31.8")),
        Row(C, "Crew for Concrete mixer", "Hour", D(8), D("375.7")),
        Row(C, "Crew for Pump", "Hour", D("0.5"), D("187.2")),
        Row(C, "Crew for Water tanker", "Hour", D(1), D("293.5")),
        Row(C, "Crew for Needle vibrator", "Hour", D(8), D("270.4")),
        Row(C, "work inspector", "Day", D(1), D(845)),
        Row(C, "Mason Class-I", "Day", D(1), D(715)),
        Row(C, "mazdoor for batching materials", "Day", D(11), D(635)),
        Row(C, "mazdoor for loading mortar pans", "Day", D(4), D(635)),
        Row(C, "mazdoor for laying", "Day", D(3), D(635)),
        Row(C, "mazdoor for conveying concrete", "Day", D("15.38"), D(635)),
        Row(C, "mazdoor for cleaning/ washing/ curing", "Day", D(1), D(635)),
        Row(C, "Labour cost for shuttering", "sqm", D("15.38"), D("156.9")),
        Row(C, "Labour cost for scaffolding @ 10 %", "%", pct=D(10), pct_of_row=11),
    ]
    sand = mechanical_lead(ZONE_III, "earth_sand", D(16)).amount
    metal = mechanical_lead(ZONE_III, "aggregate_stone", D(25)).amount
    return DataSheet(
        code="IRR-CCDW-2-3",
        description="M-15, 40 mm, foundation filling",
        unit="cum",
        analysis_qty=D("15.38"),
        rows=rows,
        adjustments=[
            PerUnitAdjustment(
                "Correction for cement rate (present 5.10, SSR 5.10)", D(263), D(0), with_ohp=True
            ),
            PerUnitAdjustment("Conveyance charges for fine aggregate", D("0.4"), sand),
            PerUnitAdjustment("Conveyance charges for coarse aggregate", D("0.9"), metal),
        ],
    )


def test_data_sheet_reproduces_the_ut_rate() -> None:
    r = compute(m15_40mm())
    assert (r.materials, r.machinery, r.labour) == (D("48017.36"), D("3104.75"), D("31601.63"))
    assert r.ohp == D("11262.84")
    assert r.rate_before_adjustments.quantize(D("0.01")) == D("6110.96")  # book: 6111.00
    assert [a for _, a in r.adjustments] == [D("0.00"), D("117.08"), D("421.29")]
    assert r.rate == D("6649.3")  # UT abstract item 3
    assert (r.labour_per_unit, r.labour_per_unit_with_ohp) == (D("2054.7"), D("2334.4"))  # book


def test_deleting_a_component_changes_the_rate() -> None:
    sheet = m15_40mm()
    full = compute(sheet).rate
    without_plasticiser = compute(DataSheet(**{**sheet.__dict__, "deleted_rows": frozenset({6})}))
    assert without_plasticiser.rate < full
    assert without_plasticiser.rows[6].deleted and without_plasticiser.rows[6].amount == 0


def test_sor_items_of_the_ut_estimate() -> None:
    # Dismantling: SoR 674 + 13.615 %, or say to 0.1 -> 765.8
    assert sor_item_rate(D(674), or_say_step=D("0.1")) == D("765.8")
    # RCC pipes (SoR page 647): 1402 + 13.615 % + lead 178.76 = 1771.6423 (kept exact)
    assert sor_item_rate(D(1402), D("178.76")) == D("1771.6423")
    assert or_say(D("136.89"), D("0.1")) == D("136.9")


UT_ITEMS = [
    ga.AbstractItem("1", "TBSC-U.I-01", "Dismantling stone masonry", D("24.84"), "Cum", D("765.8")),
    ga.AbstractItem("2", "IRR-CCDW-1-2", "Excavation for structures", D(103), "Cum", D("136.9")),
    ga.AbstractItem("3", "IRR-CCDW-2-3", "M-15 40 mm", D("27.16"), "Cum", D("6649.3")),
    ga.AbstractItem("4", "SoR p.647", "RCC S&S pipes", D(10), "RM", D("1771.6423")),
    ga.AbstractItem("5", "IRR-CCDW-6-1", "Laying and jointing pipes", D(4), "Joints", D("602.58")),
    ga.AbstractItem("6", "IRR-CCDW-2-9", "M-15 20 mm", D("76.95"), "Cum", D("6990.9")),
    ga.AbstractItem("7", "IRR-PMW-3-17", "Casing embankment", D("76.14"), "Cum", D("220.6")),
]


def test_ut_estimate_seigniorage_and_general_abstract() -> None:
    lines = [
        sg.SeigniorageLine("M15 bed", "metal", D("27.162"), D("0.9"), D(117)),
        sg.SeigniorageLine("M15 bed", "sand", D("27.162"), D("0.4"), D(40)),
        sg.SeigniorageLine("M-15 sup", "metal", D("76.95"), D("0.9"), D(117)),
        sg.SeigniorageLine("M-15 sup", "sand", D("76.95"), D("0.4"), D(40)),
        sg.SeigniorageLine("Earth", "earth", D("76.14"), D(1), D(39)),
    ]
    seig = sg.compute(
        lines, sg.SeigniorageSettings(permit_fee_materials=frozenset({"metal", "earth"}))
    )
    assert [a for _, _, a in seig.lines] == [
        D("2860.16"),
        D("434.60"),
        D("8102.84"),
        D("1231.20"),
        D("2969.46"),
    ]
    assert (seig.total, seig.dmf, seig.smet) == (D("15598.26"), D(4679), D(312))
    assert seig.permit_fee == D("11145.968")

    result = ga.compute(
        UT_ITEMS, seigniorage=seig.total, dmf=seig.dmf, smet=seig.smet, permit_fee=seig.permit_fee
    )
    assert result.ecv == D("788591.1420")
    assert [line.amount for line in result.part_b[:2]] == [D("7885.91"), D("788.59")]
    assert result.subtotal.quantize(D("0.01")) == D("829000.87")
    assert result.gst == D("149220.16")
    assert result.total.quantize(D("0.01")) == D("978221.03")  # UT: Rs 9.78 lakhs
    assert result.total_in_lakhs.quantize(D("0.01")) == D("9.78")


def test_slrb_estimate_rounding_conventions() -> None:
    items = [
        ga.AbstractItem(str(n), c, c, q, "Cum", r)
        for n, (c, q, r) in enumerate([
            ("IRR-CCDW-1-2", D("512.997"), D("136.9")), ("IRR-CCDW-2-3", D("66.475"), D(6698)),
            ("IRR-CCDW-2-9", D("41.465"), D(7042)), ("IRR-CCDW-2-22", D("120.024"), D(7826)),
            ("IRR-CCDW-2-1", D("4938.74"), D("82.4")), ("IRR-CCDW-2-10", D("6.676"), D(7876)),
            ("IRR-CCDW-2-25", D("72.375"), D(11609)), ("IRR-CCDW-2-9", D("4.5"), D("6729.7")),
        ], start=1)
    ]  # fmt: skip
    settings = ga.AbstractSettings(
        item_rounding="rupee",
        cess_rounding="none",
        nac_rounding="rupee",
        gst_rounding="none",
        final="round_up_1000_plus_unforeseen",
        unforeseen=D(2000),
    )
    result = ga.compute(
        items,
        seigniorage=D(39474),
        dmf=D(11842),
        smet=D(789),
        permit_fee=D("29633.6"),
        settings=settings,
    )
    assert result.ecv == D(3076801)
    assert result.part_b_total == D("115583.61")
    assert result.gst == D("574629.2298")
    assert result.total == D(3770000)  # SLRB: Rs 37.70 lakhs


def test_lead_edge_cases() -> None:
    import pytest

    from app.domain.icad.lead import LeadError

    with pytest.raises(LeadError):
        mechanical_lead(ZONE_III, "earth_sand", D(-1))
    with pytest.raises(LeadError):
        mechanical_lead(ZONE_III, "bitumen", D(3))
    assert mechanical_lead(ZONE_III, "earth_sand", D("3.2")).charged_km == 4  # part km -> next km
    far = mechanical_lead(ZONE_III, "earth_sand", D(35))
    assert far.working == "80.40 + 25 x 19.30 + 5 x 16.10"
    assert mechanical_lead(ZONE_III, "earth_sand", D(3), initial_km=0).amount == D("90.00")


def test_data_sheet_errors_and_additions() -> None:
    import pytest

    from app.domain.icad.rate_analysis import Addition, DataSheetError

    with pytest.raises(DataSheetError):
        compute(DataSheet("X", "x", "cum", D(0)))
    with pytest.raises(DataSheetError):
        compute(DataSheet("X", "x", "cum", D(1), rows=[Row("A", "no rate", "kg", D(1))]))
    with pytest.raises(DataSheetError):
        compute(
            DataSheet("X", "x", "cum", D(1), rows=[Row("A", "pct", "%", pct=D(10), pct_of_row=3)])
        )
    # Tunnel-style additions are inside the 13.615 % base.
    sheet = DataSheet(
        "X",
        "x",
        "cum",
        D(10),
        rows=[Row("A", "m", "cum", D(10), D(100))],
        additions=[Addition("Ventilation", D("4.5"))],
    )
    r = compute(sheet)
    assert r.subtotal == D("1045.00") and r.ohp == D("142.28")
    assert or_say(D("5.5"), D(0)) == D("5.5")


def test_seigniorage_rounding_to_rupee_and_all_materials() -> None:
    s = sg.SeigniorageSettings(
        line_rounding="rupee", levy_rounding="paise", permit_fee_materials=frozenset({"*"})
    )
    r = sg.compute([sg.SeigniorageLine("x", "metal", D("59.8275"), D(1), D(117))], s)
    assert r.total == D(7000) and r.dmf == D("2100.00") and r.permit_fee == D(5600)
