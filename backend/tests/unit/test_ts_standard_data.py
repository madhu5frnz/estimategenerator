"""The imported TS I&CAD Standard Data 2026-27 matches values printed in the book."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[2] / "app" / "data" / "ts_icad_2026_27"


@pytest.fixture(scope="module")
def items() -> dict[str, dict]:
    raw = json.loads((DATA / "items.json").read_text())
    return {i["code"]: i for i in raw["items"]}


@pytest.fixture(scope="module")
def sheets() -> dict[str, dict]:
    raw = json.loads((DATA / "datasheets.json").read_text())
    return {s["code"]: s for s in raw["datasheets"]}


def test_every_item_in_the_book_is_imported(items: dict[str, dict]) -> None:
    assert len(items) == 364
    assert sorted(i["sl"] for i in items.values()) == list(range(1, 365))
    assert all(i["rate"] for i in items.values() if not i["code"].startswith("SL-"))


@pytest.mark.parametrize(
    ("code", "unit", "rate", "labour"),
    [
        # Rates as printed in the "Work item rates" list (Zone III).
        ("IRR-DAW-1-1", "cum", "183.10", "44.50"),
        ("IRR-CCDW-1-2", "cum", "136.90", "36.50"),
        ("IRR-CCDW-2-3", "cum", "6111.00", "2334.40"),
        ("IRR-CCDW-6-1", "Joint", "547.80", "468.10"),
        ("IRR-TAW-2-1", "Kwhr", "37.00", "15.60"),
    ],
)
def test_known_rates(items: dict[str, dict], code: str, unit: str, rate: str, labour: str) -> None:
    item = items[code]
    assert (item["unit"], item["rate"], item["labour_component"]) == (unit, rate, labour)


def test_data_sheet_recomputes_to_the_printed_rate(sheets: dict[str, dict]) -> None:
    # IRR-CCDW-2-3, M-15 40 mm: A 48017.41 + B 3104.75 + C 31601.63, 13.615 %, per 15.38 cum.
    sheet = sheets["IRR-CCDW-2-3"]
    assert (sheet["analysis_qty"], sheet["analysis_unit"]) == ("15.38", "cum")
    assert sheet["totals"]["A"] == "48017.41"
    assert sheet["recomputed_rate"] == "6110.96"
    assert sheet["rate"] == "6111.00"
    assert sheet["problems"] == []


def test_most_data_sheets_verify(sheets: dict[str, dict]) -> None:
    verified = [s for s in sheets.values() if not s["problems"]]
    # Guards against a parser regression; complex gate/hoist sheets are flagged, not trusted.
    assert len(verified) >= 264
    for s in verified:
        diff = abs(Decimal(s["recomputed_rate"]) - Decimal(s["rate"].replace(",", "")))
        assert diff <= Decimal("0.06"), s["code"]


@pytest.fixture(scope="module")
def basic() -> dict:
    return json.loads((DATA / "basic_rates.json").read_text())  # type: ignore[no-any-return]


def test_sor_basic_rates(basic: dict) -> None:
    materials = {r["name"].split(" (")[0].split(" *")[0]: r for r in basic["materials"]}
    assert materials["Ordinary Portland Cement"]["rate"] == "5100.00"
    assert materials["Coarse aggregate 40-20 mm"]["rate"] == "1107.00"
    mixer = next(
        r for r in basic["hire_charges"]["III"] if r["name"].startswith("Concrete mixer 300")
    )
    # The same hire, fuel and crew rates appear in data sheet IRR-CCDW-2-3.
    assert (mixer["hire"], mixer["fuel"], mixer["crew"]) == ("67.20", "142.80", "375.70")
    mazdoor = next(
        r for r in basic["labour"] if "mazdoor" in r["name"].lower() and r["zone_3"] == "635"
    )
    assert (mazdoor["zone_1"], mazdoor["zone_2"]) == ("715", "675")


def test_zone_iii_lead_matches_the_ut_estimate(basic: dict) -> None:
    # UT Km 8.388 lead statement: sand 16 km -> 128.6 - 48.2 + 11 x 19.3 = 292.7
    lead = basic["lead"]["mechanical"]["III"]
    sand = {k: Decimal(v["earth_sand"]) for k, v in lead.items()}
    assert sand["5"] - sand["1"] + 11 * sand["per_km_5_30"] == Decimal("292.7")
    metal = {k: Decimal(v["aggregate_stone"]) for k, v in lead.items()}
    assert metal["5"] - metal["1"] + 20 * metal["per_km_5_30"] == Decimal("468.1")
