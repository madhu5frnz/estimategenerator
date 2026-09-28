"""I&CAD method end to end: the UT Km 8.388 estimate (reference/ts-2026-27) built through
the API reproduces the department's figures."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration.conftest import csrf, register, requires_db
from tests.integration.test_estimates import Api, add_item, item, new_estimate, new_project

pytestmark = [pytest.mark.db, requires_db]


@pytest.fixture
def api(client: TestClient) -> Api:
    register(client)
    return Api(client)


def book_id(db: Session, code: str) -> str:
    return str(
        db.scalar(
            text(
                "SELECT i.id FROM rate_items i JOIN rate_sources s ON s.id = i.rate_source_id"
                " WHERE s.sor_name = 'TS Standard Data (I&CAD) Zone III' AND i.item_code = :c"
            ),
            {"c": code},
        )
    )


def patch_(api: Api, path: str, body: Any) -> dict[str, Any]:
    return api.patch(path, body)


def ut_estimate(api: Api, db: Session) -> tuple[str, dict[str, Any]]:
    v = api.get(f"/versions/{new_estimate(api, new_project(api))['draft_version_id']}")
    vid = v["version"]["id"]
    s = api.get(f"/versions/{vid}/method-settings")
    assert s["config"]["zone"] == "III" and s["config"]["abstract"]["gst_pct"] == "18"
    api.patch(
        f"/versions/{vid}/method-settings",
        {"seigniorage": {"permit_fee_materials": ["metal", "earth"]}},
    )
    lead = [
        {
            "material": "Fine Aggregate/ Sand",
            "source": "Tahadakamalla (Musi)",
            "material_class": "earth_sand",
            "distance_km": 16,
        },
        {
            "material": "Coarse Aggregate",
            "source": "Appanapeta",
            "material_class": "aggregate_stone",
            "distance_km": 25,
        },
        {"material": "Gravel", "source": "Local", "material_class": "earth_sand", "distance_km": 5},
    ]
    for entry in lead:
        api.post(f"/versions/{vid}/lead-entries", entry, 201)

    specs = [
        ("Dismantling of stone masonry in CM", "cum", "24.84", None, "765.8"),
        ("Excavation for structures", "cum", "103", "IRR-CCDW-1-2", None),
        ("M-15 40 mm for foundation", "cum", "27.16", "IRR-CCDW-2-3", None),
        ("RCC S&S pipes 300 mm (SoR p.647)", "rmt", "10", None, "1771.64"),
        ("Laying and jointing 300 mm NP-3 pipes", "joint", "4", None, "602.58"),
        ("M-15 20 mm for walls", "cum", "76.95", "IRR-CCDW-2-9", None),
        ("Casing embankment", "cum", "76.14", None, "220.6"),
    ]
    for desc, unit, qty, code, rate in specs:
        v = add_item(api, v, description=desc, unit=unit, quantity=qty, rate=rate)
        if code:
            v = api.post(
                f"/boq-items/{item(v, desc)['id']}/set-rate", {"rate_item_id": book_id(db, code)}
            )
    return vid, v


def test_ut_estimate_through_the_api(api: Api, db_session: Session) -> None:
    vid, v = ut_estimate(api, db_session)

    lead = api.get(f"/versions/{vid}/lead-statement")
    assert [e["amount"] for e in lead["entries"]] == ["292.70", "468.10", "80.40"]
    assert lead["entries"][0]["working"] == "80.40 + 11 x 19.30"

    # Book rate for a sheet that could not be rebuilt: the printed rate, no data sheet.
    excavation = item(v, "Excavation for structures")
    assert excavation["rate"] == "136.90"
    assert api.get(f"/boq-items/{excavation['id']}/analysis")["has_analysis"] is False

    # IRR-CCDW-2-3: data sheet copied, then conveyance from the lead statement.
    m15 = item(v, "M-15 40 mm for foundation")
    sheet = api.get(f"/boq-items/{m15['id']}/analysis")
    assert sheet["has_analysis"] and sheet["analysis_qty"] == "15.38"
    # The book prints A = 48017.41 but its rows add to 48017.36, as in the UT sheet.
    assert (sheet["materials"], sheet["machinery"], sheet["labour"]) == (
        "48017.36",
        "3104.75",
        "31601.63",
    )
    assert sheet["rate_before_adjustments"] == "6110.96" and sheet["rate"] == "6111.0"
    assert (sheet["labour_per_unit"], sheet["labour_per_unit_with_ohp"]) == ("2054.7", "2334.4")
    sheet = api.post(f"/boq-items/{m15['id']}/analysis/auto-conveyance")
    assert [(a["quantity"], a["amount"]) for a in sheet["adjustments"]] == [
        ("0.4", "117.08"),
        ("0.9", "421.29"),
    ]
    assert sheet["rate"] == "6649.3"  # UT abstract item 3
    walls = item(api.get(f"/versions/{vid}"), "M-15 20 mm for walls")
    assert (
        api.post(f"/boq-items/{walls['id']}/analysis/auto-conveyance")["rate"] == "6990.9"
    )  # item 6

    # Seigniorage: suggested lines follow the items; UT used the unrounded detail quantity.
    seig = api.post(f"/versions/{vid}/seigniorage/suggest")
    assert [(x["material"], x["factor"]) for x in seig["lines"]] == [
        ("metal", "0.9"),
        ("sand", "0.4"),
        ("metal", "0.9"),
        ("sand", "0.4"),
        ("earth", "1"),
    ]
    for line in seig["lines"][:2]:
        seig = api.patch(
            f"/seigniorage-lines/{line['id']}",
            {"boq_item_line_key": None, "item_quantity": "27.162"},
        )
    assert (seig["total"], seig["dmf"], seig["smet"], seig["permit_fee"]) == (
        "15598.26",
        "4679",
        "312",
        "11145.97",
    )

    ga = api.get(f"/versions/{vid}/general-abstract")
    assert [i["amount"] for i in ga["items"]] == [
        "19022.47",
        "14100.70",
        "180594.99",
        "17716.40",
        "2410.32",
        "537949.76",
        "16796.48",
    ]
    assert [x["amount"] for x in ga["part_b"][:2]] == ["7885.91", "788.59"]
    assert ga["subtotal"] == "829000.85" and ga["gst"] == "149220.15"
    # UT prints Rs 9,78,221.03: its pipe rate carries 1771.6423 unrounded; rates here are
    # kept to the paisa (1771.64), which is 2.3 paise less on ECV.
    assert ga["total"] == "978221.00" and ga["total_in_lakhs"] == "9.78"
    assert ga["amount_in_words"].startswith("Rupees Nine Lakh Seventy Eight Thousand")


def test_editing_the_data_sheet_and_lead_reprices(api: Api, db_session: Session) -> None:
    vid, v = ut_estimate(api, db_session)
    m15 = item(v, "M-15 40 mm for foundation")
    api.post(f"/boq-items/{m15['id']}/analysis/auto-conveyance")
    sheet = api.get(f"/boq-items/{m15['id']}/analysis")
    plasticiser = next(r for r in sheet["rows"] if r["description"].startswith("Super Plasticizer"))
    sheet = api.patch(f"/boq-items/{m15['id']}/analysis", {"deleted_rows": [plasticiser["index"]]})
    assert sheet["rows"][plasticiser["index"]]["deleted"] and float(sheet["rate"]) < 6649.3
    after_delete = sheet["rate"]
    # Sand now 20 km: 4 km more x 19.30 x 0.4 cum = + 30.88 per cum
    sand = api.get(f"/versions/{vid}/lead-statement")["entries"][0]
    api.patch(f"/lead-entries/{sand['id']}", {"distance_km": 20})
    assert float(api.get(f"/boq-items/{m15['id']}/analysis")["rate"]) == pytest.approx(
        float(after_delete) + 30.88, abs=0.1
    )
    # The BOQ follows the data sheet.
    assert (
        item(api.get(f"/versions/{vid}"), "M-15 40 mm for foundation")["rate"]
        == api.get(f"/boq-items/{m15['id']}/analysis")["rate"] + "0"
    )
    # A lead used by a data sheet cannot be deleted; typing a rate drops the sheet.
    status, body = api.error("DELETE", f"/lead-entries/{sand['id']}")
    assert (status, body["error_code"]) == (409, "LEAD_IN_USE")
    api.patch(f"/boq-items/{m15['id']}", {"rate": "6500"})
    assert api.get(f"/boq-items/{m15['id']}/analysis")["has_analysis"] is False
    api.delete(f"/lead-entries/{sand['id']}")


def test_freeze_copies_the_method_data(api: Api, db_session: Session) -> None:
    vid, v = ut_estimate(api, db_session)
    m15 = item(v, "M-15 40 mm for foundation")
    api.post(f"/boq-items/{m15['id']}/analysis/auto-conveyance")
    api.post(f"/versions/{vid}/seigniorage/suggest")
    before = api.get(f"/versions/{vid}/general-abstract")["total"]
    new = api.post(f"/versions/{vid}/freeze", {"change_note": "UT estimate"})
    nid = new["version"]["id"]
    assert api.get(f"/versions/{nid}/general-abstract")["total"] == before
    assert len(api.get(f"/versions/{nid}/lead-statement")["entries"]) == 3
    assert len(api.get(f"/versions/{nid}/seigniorage")["lines"]) == 5
    assert api.get(f"/versions/{nid}/method-settings")["config"]["seigniorage"][
        "permit_fee_materials"
    ] == ["metal", "earth"]
    new_m15 = item(api.get(f"/versions/{nid}"), "M-15 40 mm for foundation")
    assert api.get(f"/boq-items/{new_m15['id']}/analysis")["rate"] == "6649.3"
    # The frozen version cannot change.
    sand = api.get(f"/versions/{vid}/lead-statement")["entries"][0]
    status, body = api.error("PATCH", f"/lead-entries/{sand['id']}", {"distance_km": 30})
    assert (status, body["error_code"]) == (409, "VERSION_FROZEN")
    assert api.get(f"/versions/{vid}/lead-statement")["can_edit"] is False


def test_settings_validation_and_book_in_rate_list(api: Api) -> None:
    v = api.get(f"/versions/{new_estimate(api, new_project(api))['draft_version_id']}")
    vid = v["version"]["id"]
    status, _ = api.error("PATCH", f"/versions/{vid}/method-settings", {"zone": "IV"})
    assert status == 400
    status, _ = api.error(
        "PATCH",
        f"/versions/{vid}/method-settings",
        {"abstract": {"lump_sums": [{"label": "", "amount": 1, "stage": "x"}]}},
    )
    assert status == 400
    s = api.patch(
        f"/versions/{vid}/method-settings",
        {
            "abstract": {
                "item_rounding": "rupee",
                "final": "round_up_1000_plus_unforeseen",
                "unforeseen": "2000",
                "lump_sums": [
                    {
                        "label": "Advertisement and stationery",
                        "amount": "5000",
                        "stage": "after_gst",
                    }
                ],
            }
        },
    )
    assert s["config"]["abstract"]["unforeseen"] == "2000"
    v = add_item(api, v, description="Work", unit="cum", quantity="10", rate="1000")
    ga = api.get(f"/versions/{vid}/general-abstract")
    # 10000 + cess 100 + NAC 10 = 10110; GST 1819.80; + 5000 = 16929.80 -> 17000 + 2000
    assert (ga["gst"], ga["after_gst"][0]["amount"], ga["total"]) == (
        "1819.80",
        "5000.00",
        "19000.00",
    )

    found = api.get("/rate-items?q=IRR-CCDW-2-3")["items"][0]
    assert (found["item_code"], found["rate"], found["labour_component"]) == (
        "IRR-CCDW-2-3",
        "6111.00",
        "2334.40",
    )
    assert (
        found["analysis_status"] == "verified"
        and found["verification_status"] == "imported_unverified"
    )
    assert api.post(
        "/rate-sources",
        {
            "state": "TS",
            "department": "x",
            "sor_name": "x",
            "year": "2026-27",
            "effective_from": "2026-04-01",
        },
        201,
    )
    status, _ = api.error("PATCH", f"/rate-items/{found['id']}", {"rate": 1})
    assert status == 409  # the imported book is read-only
    assert csrf(api.c)
