"""M5: rate list, picking rates, abstract (charges, GST, rounding), validation, defaults."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration.conftest import add_org_member, csrf, login, register, requires_db
from tests.integration.test_estimates import Api, add_item, item, new_estimate, new_project

pytestmark = [pytest.mark.db, requires_db]

_NS = uuid.UUID("0b7b3e4c-4c1a-4f55-9a7e-2d1b9b8f3a10")
DEMO_SOURCE = str(uuid.uuid5(_NS, "demo-source-2026-27"))
CC_001 = str(uuid.uuid5(_NS, "CC-001"))
PLASTER = str(uuid.uuid5(_NS, "DEMO-PL-12"))


@pytest.fixture
def api(client: TestClient) -> Api:
    register(client)
    return Api(client)


def draft(api: Api) -> dict[str, Any]:
    est = new_estimate(api, new_project(api))
    return api.get(f"/versions/{est['draft_version_id']}")


def own_source(api: Api, **body: Any) -> dict[str, Any]:
    return api.post(
        "/rate-sources",
        {
            "state": "Telangana",
            "department": "R&B",
            "sor_name": "My SOR",
            "year": "2026-27",
            "effective_from": "2026-04-01",
            **body,
        },
        201,
    )


# ------------------------------------------------------------------ rates
def test_rate_list_search_and_demo_source_is_read_only(api: Api, make_client: Any) -> None:
    sources = api.get("/rate-sources")
    demo = next(s for s in sources if s["id"] == DEMO_SOURCE)
    assert demo["is_demo"] and demo["sor_name"] == "Demo Rates — Not Official SOR"
    assert (demo["can_edit"], demo["owned"], demo["item_count"]) == (False, False, 10)

    found = api.get("/rate-items?q=cement%20concrete")
    codes = [i["item_code"] for i in found["items"]]
    assert "CC-001" in codes
    cc = next(i for i in found["items"] if i["item_code"] == "CC-001")
    assert (cc["rate"], cc["unit"], cc["is_demo"]) == ("7500.00", "cum", True)
    assert cc["rate_display"] == "₹7,500.00"
    assert [i["item_code"] for i in api.get("/rate-items?q=CC-0")["items"]] == ["CC-001"]
    by_unit = api.get("/rate-items?unit=Sq.m")
    assert {i["item_code"] for i in by_unit["items"]} == {"DEMO-PL-12", "DEMO-PT-01"}
    assert api.get("/rate-items?q=%25")["total"] == 0  # LIKE wildcards are literal

    status, body = api.error("PATCH", f"/rate-items/{CC_001}", {"rate": "1"})
    assert (status, body["error_code"]) == (409, "RATE_SOURCE_READ_ONLY")
    status, body = api.error("POST", f"/rate-sources/{DEMO_SOURCE}/items",
                             {"item_code": "X", "description": "X", "unit": "cum", "rate": 1})  # fmt: skip
    assert status == 409

    mine = own_source(api)
    assert (mine["verification_status"], mine["can_edit"], mine["is_demo"]) == (
        "user_entered",
        True,
        False,
    )
    new = api.post(
        f"/rate-sources/{mine['id']}/items",
        {"item_code": "RB-12", "description": "Kerb stone painting", "unit": "Rmt", "rate": "45.5"},
        201,
    )
    assert (new["unit"], new["rate"], new["source_label"]) == ("rmt", "45.50", "My SOR 2026-27")
    status, body = api.error("POST", f"/rate-sources/{mine['id']}/items",
                             {"item_code": "RB-12", "description": "Dup", "unit": "rmt", "rate": 1})  # fmt: skip
    assert (status, body["error_code"]) == (409, "RATE_CODE_TAKEN")
    status, body = api.error("POST", f"/rate-sources/{mine['id']}/items",
                             {"item_code": "RB-13", "description": "X", "unit": "rmt", "rate": "1.005"})  # fmt: skip
    assert status == 400
    edited = api.patch(f"/rate-items/{new['id']}", {"rate": 50})
    assert edited["rate"] == "50.00"
    assert api.get(f"/rate-items?source_id={mine['id']}")["total"] == 1
    status, body = api.error("POST", "/rate-sources", {**mine, "year": "2026"})
    assert status == 400

    # Another workspace sees the demo rates but not this workspace's source.
    other = make_client()
    register(other, email="other@example.com")
    other_api = Api(other)
    assert [s["id"] for s in other_api.get("/rate-sources")] == [DEMO_SOURCE]
    assert other_api.get("/rate-items?q=kerb%20stone")["total"] == 0
    status, _ = other_api.error("PATCH", f"/rate-items/{new['id']}", {"rate": 1})
    assert status == 404


def test_only_workspace_admins_change_rates(
    api: Api, make_client: Any, db_session: Session
) -> None:
    org_id = api.get("/me")["organization"]["id"]
    add_org_member(db_session, org_id, "member@example.com")
    member = Api(login(make_client(), "member@example.com", "member pass 123"))
    assert member.get("/rate-items?q=concrete")["total"] >= 1
    status, body = member.error("POST", "/rate-sources", {
        "state": "TS", "department": "R&B", "sor_name": "X", "year": "2026-27",
        "effective_from": "2026-04-01"})  # fmt: skip
    assert (status, body["error_code"]) == (403, "FORBIDDEN")


# ------------------------------------------------------------ set rate
def test_set_rate_checks_unit_and_asks_before_overwriting(api: Api) -> None:
    v = draft(api)
    v = add_item(api, v, description="PCC", unit="Cum", quantity="10", rate="7000")
    pcc = item(v, "PCC")

    status, body = api.error("POST", f"/boq-items/{pcc['id']}/set-rate", {"rate_item_id": CC_001})
    assert (status, body["error_code"]) == (409, "RATE_OVERWRITE_REQUIRES_CONFIRMATION")
    assert body["details"] == {"current_rate": "7000.00", "new_rate": "7500.00"}

    v = api.post(
        f"/boq-items/{pcc['id']}/set-rate", {"rate_item_id": CC_001, "confirm_overwrite": True}
    )
    pcc = item(v, "PCC")
    assert (pcc["rate"], pcc["amount"], pcc["rate_source_type"]) == (
        "7500.00",
        "75000.00",
        "rate_database",
    )
    info = pcc["rate_info"]
    assert info["is_demo"] and info["item_code"] == "CC-001" and info["year"] == "2026-27"
    assert info["label"] == "CC-001 · Demo Rates — Not Official SOR 2026-27"
    # Picking another database rate needs no confirmation.
    api.post(f"/boq-items/{pcc['id']}/set-rate", {"rate_item_id": CC_001})

    v = add_item(api, v, description="Plaster", unit="Cum", quantity="2")
    status, body = api.error(
        "POST", f"/boq-items/{item(v, 'Plaster')['id']}/set-rate", {"rate_item_id": PLASTER}
    )
    assert (status, body["error_code"]) == (400, "UNIT_RATE_MISMATCH")
    assert body["details"] == {"item_unit": "cum", "rate_unit": "sqm"}

    v = add_item(api, v, description="Wall plaster", quantity="120.456")
    v = api.post(f"/boq-items/{item(v, 'Wall plaster')['id']}/set-rate", {"rate_item_id": PLASTER})
    wall = item(v, "Wall plaster")
    assert (wall["unit"], wall["quantity"], wall["amount"]) == ("sqm", "120.46", "39149.50")

    # Typing a rate by hand turns it back into a manual rate.
    v = api.patch(f"/boq-items/{pcc['id']}", {"rate": "7100"})
    assert item(v, "PCC")["rate_info"] is None
    assert item(v, "PCC")["rate_source_type"] == "manual"


def test_rate_in_use_cannot_be_deleted(api: Api) -> None:
    mine = own_source(api)
    rate = api.post(f"/rate-sources/{mine['id']}/items",
                    {"item_code": "A1", "description": "Excavation", "unit": "cum", "rate": 200},
                    201)  # fmt: skip
    v = draft(api)
    v = add_item(api, v, description="Excavation", unit="cum", quantity=5)
    api.post(f"/boq-items/{item(v, 'Excavation')['id']}/set-rate", {"rate_item_id": rate["id"]})
    status, body = api.error("DELETE", f"/rate-items/{rate['id']}")
    assert (status, body["error_code"]) == (409, "RATE_IN_USE")
    status, body = api.error("DELETE", f"/rate-sources/{mine['id']}")
    assert (status, body["error_code"]) == (409, "RATE_IN_USE")
    spare = own_source(api, sor_name="Spare")
    api.delete(f"/rate-sources/{spare['id']}")


# -------------------------------------------------------------- abstract
def brief_example(api: Api) -> dict[str, Any]:
    """Brief §12 sections: 2,50,000 + 4,50,000 + 15,50,000 + 3,25,000 = 25,75,000."""
    v = draft(api)
    vid = v["version"]["id"]
    first = v["sections"][0]
    api.patch(f"/sections/{first['id']}", {"title": "Earthwork"})
    for title in ("GSB", "CC Road", "Drainage"):
        v = api.post(f"/versions/{vid}/sections", {"title": title})
    amounts = dict(zip(("Earthwork", "GSB", "CC Road", "Drainage"),
                       ("250000", "450000", "1550000", "325000"), strict=True))  # fmt: skip
    for s in v["sections"]:
        v = add_item(api, v, section_id=s["id"], description=f"{s['title']} works",
                     unit="LS", quantity=1, rate=amounts[s["title"]])  # fmt: skip
    return v


def test_abstract_with_contingency_and_gst_to_the_paisa(api: Api) -> None:
    v = brief_example(api)
    vid = v["version"]["id"]
    a = api.get(f"/versions/{vid}/abstract")
    assert a["works_subtotal"] == "2575000.00"
    assert a["gst_config"]["applicable"] is False and a["gst_config"]["rate_pct"] is None
    assert a["charges"] == [] and a["rounding"] == "nearest_rupee"
    assert a["grand_total"] == "2575000.00" and a["can_edit"]

    a = api.post(f"/versions/{vid}/charges",
                 {"name": "Contingencies", "kind": "contingency", "percentage": "2.5"}, 201)  # fmt: skip
    assert a["charges"][0]["amount"] == "64375.00"
    assert a["charges"][0]["base_label"] == "works subtotal"

    status, body = api.error("PUT", f"/versions/{vid}/gst", {"applicable": True})
    assert (status, body["error_code"]) == (400, "GST_RATE_REQUIRED")
    a = api.c.put(f"/api/v1/versions/{vid}/gst", headers=csrf(api.c),
                  json={"applicable": True, "supply": "intra", "rate_pct": 18}).json()["data"]  # fmt: skip
    assert [(g["name"], g["rate_pct"], g["amount"]) for g in a["gst"]] == [
        ("CGST", "9", "237543.75"),
        ("SGST", "9", "237543.75"),
    ]
    assert a["subtotal_before_gst"] == "2639375.00"
    assert a["total_before_rounding"] == "3114462.50"
    # Nearest rupee (the default) rounds half up.
    assert (a["grand_total"], a["rounding_adjustment"]) == ("3114463.00", "0.50")
    a = api.c.put(f"/api/v1/versions/{vid}/rounding", headers=csrf(api.c),
                  json={"grand_total": "none"}).json()["data"]  # fmt: skip
    assert a["grand_total"] == "3114462.50"
    assert a["grand_total_display"] == "₹31,14,462.50"
    assert a["amount_in_words"] == (
        "Rupees Thirty One Lakh Fourteen Thousand Four Hundred Sixty Two and Fifty Paise Only"
    )
    assert api.get(f"/versions/{vid}")["totals"]["grand_total"] == "3114462.50"

    # Section-based charge, then disabling and reordering.
    road = next(s for s in a["sections"] if s["title"] == "CC Road")
    a = api.post(f"/versions/{vid}/charges", {"name": "Seigniorage", "kind": "seigniorage",
                 "percentage": 1, "base": "sections", "section_keys": [road["line_key"]]}, 201)  # fmt: skip
    seig = a["charges"][1]
    assert (seig["base_amount"], seig["amount"], seig["base_label"]) == (
        "1550000.00",
        "15500.00",
        "section 3",
    )
    status, _ = api.error("POST", f"/versions/{vid}/charges", {"name": "Bad", "percentage": 1,
                          "base": "sections", "section_keys": [str(uuid.uuid4())]})  # fmt: skip
    assert status == 400
    status, _ = api.error("POST", f"/versions/{vid}/charges",
                          {"name": "Both", "percentage": 1, "fixed_amount": 5})  # fmt: skip
    assert status == 400
    a = api.patch(f"/charges/{seig['id']}", {"enabled": False})
    assert a["charges"][1]["amount"] == "0.00" and a["grand_total"] == "3114462.50"
    a = api.patch(f"/charges/{seig['id']}", {"fixed_amount": "1000"})
    assert (a["charges"][1]["percentage"], a["charges"][1]["fixed_amount"]) == (None, "1000.00")
    ids = [c["id"] for c in a["charges"]]
    a = api.post(f"/versions/{vid}/charges/reorder", {"ids": ids[::-1]})
    assert [c["name"] for c in a["charges"]] == ["Seigniorage", "Contingencies"]
    a = api.delete(f"/charges/{seig['id']}")
    assert [c["name"] for c in a["charges"]] == ["Contingencies"]


def test_inclusive_and_inter_state_gst(api: Api) -> None:
    v = brief_example(api)
    vid = v["version"]["id"]
    put = lambda body: api.c.put(f"/api/v1/versions/{vid}/gst", json=body,  # noqa: E731
                                 headers=csrf(api.c)).json()["data"]  # fmt: skip
    a = put({"applicable": True, "supply": "inter", "rate_pct": 12, "base": "works_subtotal"})
    assert [(g["name"], g["amount"]) for g in a["gst"]] == [("IGST", "309000.00")]
    a = put({"applicable": True, "mode": "inclusive", "rate_pct": 18})
    assert all(g["included"] for g in a["gst"]) and a["gst_added"] == "0.00"
    assert a["grand_total"] == "2575000.00" and a["notes"]
    # Switching GST off clears the lines.
    a = put({"applicable": False})
    assert a["gst"] == [] and a["problem"] is None


def test_abstract_problem_is_reported_not_raised(api: Api, db_session: Session) -> None:
    v = brief_example(api)
    vid = v["version"]["id"]
    db_session.execute(
        text("UPDATE estimate_versions SET gst_config = '{\"applicable\": true}' WHERE id = :id"),
        {"id": vid},
    )
    db_session.commit()
    a = api.get(f"/versions/{vid}/abstract")
    assert a["problem"]["code"] == "GST_RATE_REQUIRED"
    assert a["grand_total"] == "2575000.00"
    report = api.get(f"/versions/{vid}/validation")
    assert "GST_INCONSISTENT" in {f["rule_id"] for f in report["findings"]}


def test_freeze_keeps_charges_and_grand_total(api: Api, db_session: Session) -> None:
    v = brief_example(api)
    vid = v["version"]["id"]
    api.post(f"/versions/{vid}/charges", {"name": "Contingencies", "kind": "contingency",
             "percentage": "2.5"}, 201)  # fmt: skip
    api.c.put(f"/api/v1/versions/{vid}/gst", headers=csrf(api.c),
              json={"applicable": True, "rate_pct": 18})  # fmt: skip
    new = api.post(f"/versions/{vid}/freeze", {"change_note": "Initial"})
    snap = db_session.scalar(
        text("SELECT totals_snapshot FROM estimate_versions WHERE id = :id"), {"id": vid}
    )
    assert snap["grand_total"] == "3114463.00"
    frozen = api.get(f"/versions/{vid}/abstract")
    assert frozen["can_edit"] is False and frozen["grand_total"] == "3114463.00"
    status, body = api.error("POST", f"/versions/{vid}/charges", {"name": "X", "percentage": 1})
    assert (status, body["error_code"]) == (409, "VERSION_FROZEN")
    status, _ = api.error("PATCH", f"/charges/{frozen['charges'][0]['id']}", {"enabled": False})
    assert status == 409

    nid = new["version"]["id"]
    nxt = api.get(f"/versions/{nid}/abstract")
    assert [c["name"] for c in nxt["charges"]] == ["Contingencies"]
    assert nxt["charges"][0]["line_key"] == frozen["charges"][0]["line_key"]
    assert nxt["gst_config"]["rate_pct"] == "18" and nxt["grand_total"] == "3114463.00"
    api.patch(f"/charges/{nxt['charges'][0]['id']}", {"percentage": 3})
    assert api.get(f"/versions/{vid}/abstract")["charges"][0]["percentage"] == "2.5"


# ------------------------------------------------------------ validation
def test_validation_passes_and_detects_problems(api: Api, db_session: Session) -> None:
    v = draft(api)
    vid = v["version"]["id"]
    report = api.get(f"/versions/{vid}/validation")
    assert report["status"] == "yellow"
    assert [f["rule_id"] for f in report["findings"]] == ["EMPTY_ESTIMATE"]

    v = add_item(api, v, description="PCC", unit="cum")
    pcc = item(v, "PCC")
    api.post(f"/boq-items/{pcc['id']}/measurements",
             {"nos": 1, "length": 10, "breadth": 2, "depth_height": "0.15"}, 201)  # fmt: skip
    api.patch(f"/boq-items/{pcc['id']}", {"rate": "7000"})
    report = api.get(f"/versions/{vid}/validation")
    assert (report["status"], report["message"], report["findings"]) == (
        "green",
        "Calculation checks passed",
        [],
    )

    api.post(
        f"/boq-items/{pcc['id']}/set-rate", {"rate_item_id": CC_001, "confirm_overwrite": True}
    )
    v = add_item(api, v, description="Kerb", unit="rmt", quantity=10)
    report = api.get(f"/versions/{vid}/validation")
    rules = {(f["rule_id"], f["severity"], f["sl_no"]) for f in report["findings"]}
    assert ("DEMO_RATE_USED", "yellow", "1.1") in rules
    assert ("RATE_MISSING", "red", "1.2") in rules
    assert report["status"] == "red"
    assert report["message"] == "1 error(s), 1 item(s) to review"

    # A row changed outside the app is caught by recalculation.
    db_session.execute(
        text("UPDATE boq_items SET amount = amount + 1 WHERE id = :id"), {"id": pcc["id"]}
    )
    db_session.execute(
        text("UPDATE estimate_items SET quantity = 99 WHERE boq_item_id = :id"), {"id": pcc["id"]}
    )
    db_session.commit()
    report = api.get(f"/versions/{vid}/validation")
    found = {f["rule_id"] for f in report["findings"] if f["sl_no"] == "1.1"}
    assert {"TOTAL_MISMATCH", "LINE_RECALC_MISMATCH"} <= found


def test_frozen_snapshot_mismatch_is_reported(api: Api, db_session: Session) -> None:
    v = draft(api)
    vid = v["version"]["id"]
    add_item(api, v, description="PCC", unit="cum", quantity=1, rate=100)
    api.post(f"/versions/{vid}/freeze", {"change_note": "V1"})
    assert api.get(f"/versions/{vid}/validation")["status"] == "green"
    db_session.execute(text("SET session_replication_role = replica"))
    db_session.execute(text("UPDATE boq_items SET amount = 5 WHERE version_id = :v"), {"v": vid})
    db_session.commit()
    report = api.get(f"/versions/{vid}/validation")
    assert {"ABSTRACT_MISMATCH", "TOTAL_MISMATCH"} <= {f["rule_id"] for f in report["findings"]}


# -------------------------------------------------------------- defaults
def test_workspace_defaults_apply_to_new_estimates(
    api: Api, make_client: Any, db_session: Session
) -> None:
    org_id = api.get("/me")["organization"]["id"]
    path = f"/organizations/{org_id}/settings/estimate-defaults"
    empty = api.get(path)
    assert empty["charges"] == [] and empty["gst"]["applicable"] is False and empty["can_edit"]

    body = {
        "gst": {"applicable": True, "supply": "intra", "rate_pct": "18"},
        "charges": [{"name": "Contingencies", "kind": "contingency", "percentage": "3"}],
        "rounding": "nearest_10",
    }
    saved = api.c.put(f"/api/v1{path}", json=body, headers=csrf(api.c)).json()["data"]
    assert saved["charges"][0]["percentage"] == "3" and saved["rounding"] == "nearest_10"
    bad = api.c.put(f"/api/v1{path}", json={**body, "gst": {"applicable": True}},
                    headers=csrf(api.c))  # fmt: skip
    assert bad.status_code == 400

    v = brief_example(api)
    a = api.get(f"/versions/{v['version']['id']}/abstract")
    assert [c["name"] for c in a["charges"]] == ["Contingencies"]
    assert a["gst_config"]["rate_pct"] == "18" and a["rounding"] == "nearest_10"
    # 25,75,000 + 3 % = 26,52,250; + 18 % GST = 31,29,655 → nearest 10.
    assert a["total_before_rounding"] == "3129655.00" and a["grand_total"] == "3129660.00"

    add_org_member(db_session, org_id, "member@example.com")
    member = Api(login(make_client(), "member@example.com", "member pass 123"))
    assert member.get(path)["can_edit"] is False
    status, _ = member.error("PUT", path, body)
    assert status == 403
    other = make_client()
    register(other, email="other@example.com")
    status, _ = Api(other).error("GET", path)
    assert status == 404
