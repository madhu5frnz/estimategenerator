from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.conftest import add_org_member, csrf, login, register, requires_db

pytestmark = [pytest.mark.db, requires_db]
YEAR = datetime.now(UTC).year


# ------------------------------------------------------------------ helpers
class Api:
    def __init__(self, client: TestClient) -> None:
        self.c = client

    def _ok(self, response: Any, status: int = 200) -> dict[str, Any]:
        assert response.status_code == status, response.text
        return response.json()["data"]  # type: ignore[no-any-return]

    def get(self, path: str) -> dict[str, Any]:
        return self._ok(self.c.get(f"/api/v1{path}"))

    def post(self, path: str, body: Any = None, status: int = 200) -> dict[str, Any]:
        return self._ok(self.c.post(f"/api/v1{path}", json=body, headers=csrf(self.c)), status)

    def patch(self, path: str, body: Any) -> dict[str, Any]:
        return self._ok(self.c.patch(f"/api/v1{path}", json=body, headers=csrf(self.c)))

    def delete(self, path: str) -> dict[str, Any]:
        return self._ok(self.c.delete(f"/api/v1{path}", headers=csrf(self.c)))

    def error(self, method: str, path: str, body: Any = None) -> tuple[int, dict[str, Any]]:
        response = self.c.request(method, f"/api/v1{path}", json=body, headers=csrf(self.c))
        assert not response.json()["success"], response.text
        return response.status_code, response.json()


@pytest.fixture
def api(client: TestClient) -> Api:
    register(client)
    return Api(client)


def new_project(api: Api, name: str = "CC Road Miryalaguda") -> str:
    project = api.post("/projects", {"name": name, "project_type": "road"}, status=201)
    return str(project["id"])


def new_estimate(api: Api, project_id: str, **body: Any) -> dict[str, Any]:
    return api.post(
        f"/projects/{project_id}/estimates", {"title": "Detailed estimate", **body}, 201
    )


def first_section(version: dict[str, Any]) -> dict[str, Any]:
    return version["sections"][0]  # type: ignore[no-any-return]


def item(version: dict[str, Any], description: str) -> dict[str, Any]:
    for section in version["sections"]:
        for i in section["items"]:
            if i["description"] == description:
                return i  # type: ignore[no-any-return]
    raise AssertionError(f"no item {description!r}")


def add_item(api: Api, version: dict[str, Any], **body: Any) -> dict[str, Any]:
    section_id = body.pop("section_id", first_section(version)["id"])
    return api.post(
        f"/versions/{version['version']['id']}/boq-items", {"section_id": section_id, **body}, 201
    )


# -------------------------------------------------------------------- tests
def test_create_estimate_numbers_and_first_version(api: Api) -> None:
    pid = new_project(api)
    first = new_estimate(api, pid)
    second = new_estimate(api, pid, title="Revised estimate")
    assert first["estimate_number"] == f"EST-{YEAR}-0001"
    assert second["estimate_number"] == f"EST-{YEAR}-0002"
    assert first["draft_version_no"] == 1

    status, body = api.error(
        "POST", f"/projects/{pid}/estimates", {"title": "X", "estimate_number": f"EST-{YEAR}-0001"}
    )
    assert (status, body["error_code"]) == (409, "ESTIMATE_NUMBER_TAKEN")

    version = api.get(f"/versions/{first['draft_version_id']}")
    assert version["version"]["status"] == "draft"
    assert version["can_edit"] is True
    assert [s["title"] for s in version["sections"]] == ["General works"]
    assert version["totals"]["works_subtotal"] == "0.00"
    listed = api.get(f"/projects/{pid}/estimates")
    assert [e["title"] for e in listed] == ["Detailed estimate", "Revised estimate"]


def test_brief_example_measurements_rate_and_totals(api: Api, db_session: Session) -> None:
    est = new_estimate(api, new_project(api))
    v = api.get(f"/versions/{est['draft_version_id']}")
    v = add_item(api, v, description="PCC M30 for CC pavement", unit="Cum")
    pcc = item(v, "PCC M30 for CC pavement")
    assert pcc["sl_no"] == "1.1" and pcc["item_no_display"] == "1.1"
    assert pcc["quantity"] is None and pcc["amount"] is None

    line = {
        "nos": 1,
        "length": 500,
        "breadth": "5.5",
        "depth_height": "0.15",
        "dimension_unit": "m",
    }
    v = api.post(f"/boq-items/{pcc['id']}/measurements", {"description": "Ch 0-500", **line}, 201)
    v = api.post(
        f"/boq-items/{pcc['id']}/measurements", {"description": "Ch 500-1000", **line}, 201
    )
    pcc = item(v, "PCC M30 for CC pavement")
    assert pcc["quantity"] == "825.000"
    assert pcc["quantity_source"] == "measurements"
    calc = pcc["lines"][0]["calculation"]
    assert calc["substituted"] == "1 × 500 × 5.5 × 0.15"
    assert calc["result"] == "412.5"

    v = api.patch(f"/boq-items/{pcc['id']}", {"rate": "6450"})
    pcc = item(v, "PCC M30 for CC pavement")
    assert pcc["amount"] == "5321250.00"
    assert v["totals"]["works_subtotal"] == "5321250.00"
    assert v["totals"]["works_subtotal_display"] == "₹53,21,250.00"
    assert v["totals"]["amount_in_words"] == (
        "Rupees Fifty Three Lakh Twenty One Thousand Two Hundred Fifty Only"
    )

    # A deduction line subtracts, and the amount follows.
    v = api.post(
        f"/boq-items/{pcc['id']}/measurements",
        {"description": "Less culvert", "is_deduction": True, "nos": 1, "length": 3,
         "breadth": 5, "depth_height": "0.15", "dimension_unit": "m"},
        201,
    )  # fmt: skip
    pcc = item(v, "PCC M30 for CC pavement")
    assert pcc["quantity"] == "822.750"
    assert pcc["amount"] == "5306737.50"
    assert first_section(v)["subtotal"] == "5306737.50"

    # View Calculation for one line.
    line_id = pcc["lines"][0]["id"]
    detail = api.get(f"/measurements/{line_id}/calculation")
    assert detail["steps"][0]["text"] == "Formula: nos × L × B × D"

    # Editing a line recalculates the item; deleting all lines empties the quantity.
    v = api.patch(f"/measurements/{line_id}", {"length": 250})
    assert item(v, "PCC M30 for CC pavement")["quantity"] == "616.500"
    for line_ in item(v, "PCC M30 for CC pavement")["lines"]:
        v = api.delete(f"/measurements/{line_['id']}")
    pcc = item(v, "PCC M30 for CC pavement")
    assert (pcc["quantity"], pcc["amount"], pcc["quantity_source"]) == (None, None, "manual")

    actions = db_session.execute(
        text(
            "SELECT action, field, old_value, new_value FROM audit_logs"
            " WHERE entity_type = 'boq_item' AND entity_id = :i ORDER BY id"
        ),
        {"i": pcc["id"]},
    ).all()
    recalcs = [(a.old_value, a.new_value) for a in actions if a.action == "recalculate"]
    assert (None, "412.500") in recalcs and ("412.500", "825.000") in recalcs
    assert any(a.field == "rate" and a.new_value == "6450" for a in actions)


def test_manual_quantity_rules(api: Api) -> None:
    est = new_estimate(api, new_project(api))
    v = api.get(f"/versions/{est['draft_version_id']}")
    v = add_item(api, v, description="Kerb", unit="rmt", quantity="2000.456", rate="350.50")
    kerb = item(v, "Kerb")
    assert kerb["quantity"] == "2000.46"  # Rmt keeps 2 decimals
    assert kerb["amount"] == "701161.23"
    v = api.patch(f"/boq-items/{kerb['id']}", {"quantity": "1000"})
    assert item(v, "Kerb")["amount"] == "350500.00"

    for body, code in [
        ({"rate": "12.345"}, "VALIDATION_ERROR"),
        ({"quantity": "-1"}, "VALIDATION_ERROR"),
        ({"unit": "furlong"}, "UNKNOWN_UNIT"),
        ({"description": " "}, "VALIDATION_ERROR"),
    ]:
        status, err = api.error("PATCH", f"/boq-items/{kerb['id']}", body)
        assert (status, err["error_code"]) == (400, code), body

    v = api.post(
        f"/boq-items/{kerb['id']}/measurements",
        {"length": 10, "dimension_unit": "m", "description": "One side"},
        201,
    )
    status, err = api.error("PATCH", f"/boq-items/{kerb['id']}", {"quantity": "5"})
    assert (status, err["error_code"]) == (409, "QUANTITY_FROM_MEASUREMENTS")


def test_unit_change_recalculates_or_is_rejected(api: Api) -> None:
    est = new_estimate(api, new_project(api))
    v = api.get(f"/versions/{est['draft_version_id']}")
    v = add_item(api, v, description="Earthwork", unit="cum", rate="100")
    ew = item(v, "Earthwork")
    api.post(
        f"/boq-items/{ew['id']}/measurements",
        {"length": 100, "breadth": 2, "depth_height": 1, "dimension_unit": "m"},
        201,
    )
    v = api.patch(f"/boq-items/{ew['id']}", {"unit": "cft"})
    ew = item(v, "Earthwork")
    assert (ew["unit"], ew["quantity"]) == ("cuft", "7062.93")  # 200 cum in cft
    _, err = api.error("PATCH", f"/boq-items/{ew['id']}", {"unit": "sqm"})
    assert err["error_code"] == "DIMENSIONS_MISMATCH"
    assert item(api.get(f"/versions/{est['draft_version_id']}"), "Earthwork")["unit"] == "cuft"


def test_parameters_drive_formula_lines(api: Api) -> None:
    est = new_estimate(api, new_project(api))
    vid = est["draft_version_id"]
    api.post(
        f"/versions/{vid}/parameters",
        {"name": "road_length", "label": "Road length", "value": "500", "unit": "m"},
        201,
    )
    v = api.post(
        f"/versions/{vid}/parameters", {"name": "cc_width", "value": "5.5", "unit": "m"}, 201
    )
    assert [p["name"] for p in v["parameters"]] == ["cc_width", "road_length"]
    v = add_item(api, v, description="CC pavement", unit="cum", rate="6450")
    cc = item(v, "CC pavement")
    formula = {
        "mode": "formula",
        "template_id": "road_layer",
        "inputs": {
            "length": {"ref": "road_length"},
            "width": {"ref": "cc_width"},
            "thickness": {"value": "150", "unit": "mm"},
        },
    }
    v = api.post(f"/boq-items/{cc['id']}/measurements", formula, 201)
    cc = item(v, "CC pavement")
    assert cc["quantity"] == "412.500"
    assert cc["lines"][0]["calculation"]["inputs"]["length"]["ref"] == "road_length"
    assert {p["name"]: p["used_by"] for p in v["parameters"]} == {"cc_width": 1, "road_length": 1}

    road_length = next(p for p in v["parameters"] if p["name"] == "road_length")
    v = api.patch(f"/parameters/{road_length['id']}", {"value": "1", "unit": "km"})
    assert v["notice"] == "Recalculated 1 measurement line(s) in 1 item(s)."
    cc = item(v, "CC pavement")
    assert cc["quantity"] == "825.000"
    assert cc["amount"] == "5321250.00"
    assert "length = 1 km = 1000 m" in [s["text"] for s in cc["lines"][0]["calculation"]["steps"]]

    status, err = api.error("DELETE", f"/parameters/{road_length['id']}")
    assert (status, err["error_code"]) == (409, "PARAMETER_IN_USE")
    status, err = api.error("PATCH", f"/parameters/{road_length['id']}", {"value": None})
    assert (status, err["error_code"]) == (409, "PARAMETER_IN_USE")
    status, err = api.error("PATCH", f"/parameters/{road_length['id']}", {"unit": "sqm"})
    assert err["error_code"] == "UNIT_MISMATCH"

    unknown = {**formula, "inputs": {**formula["inputs"], "length": {"ref": "nope"}}}
    status, err = api.error("POST", f"/boq-items/{cc['id']}/measurements", unknown)
    assert err["error_code"] == "UNKNOWN_PARAMETER"
    api.post(
        f"/versions/{vid}/parameters", {"name": "gsb_thickness", "label": "GSB thickness"}, 201
    )
    missing = {**formula, "inputs": {**formula["inputs"], "thickness": {"ref": "gsb_thickness"}}}
    status, err = api.error("POST", f"/boq-items/{cc['id']}/measurements", missing)
    assert err["error_code"] == "MISSING_PARAMETER"
    status, err = api.error("POST", f"/versions/{vid}/parameters", {"name": "Road Length"})
    assert err["error_code"] == "VALIDATION_ERROR"
    status, err = api.error("POST", f"/versions/{vid}/parameters", {"name": "cc_width"})
    assert err["error_code"] == "PARAMETER_EXISTS"


def test_formula_lines_convert_or_use_custom_expressions(api: Api) -> None:
    est = new_estimate(api, new_project(api))
    v = api.get(f"/versions/{est['draft_version_id']}")
    v = add_item(api, v, description="GSB (cft)", unit="cft")
    gsb = item(v, "GSB (cft)")
    v = api.post(
        f"/boq-items/{gsb['id']}/measurements",
        {"mode": "formula", "template_id": "road_layer", "inputs": {
            "length": {"value": 10, "unit": "m"}, "width": {"value": 1, "unit": "m"},
            "thickness": {"value": 100, "unit": "mm"}}},
        201,
    )  # fmt: skip
    gsb = item(v, "GSB (cft)")
    assert gsb["quantity"] == "35.31"  # 1 cum
    assert "converted from Cum" in gsb["lines"][0]["calculation"]["steps"][-1]["text"]

    v = add_item(api, v, description="Wall", unit="cum")
    wall = item(v, "Wall")
    v = api.post(
        f"/boq-items/{wall['id']}/measurements",
        {"mode": "formula", "expression": "(L * H - door) * T", "inputs": {
            "L": {"value": 10, "unit": "m"}, "H": {"value": 3, "unit": "m"},
            "door": {"value": "2.1", "unit": "sqm"}, "T": {"value": 230, "unit": "mm"}}},
        201,
    )  # fmt: skip
    assert item(v, "Wall")["quantity"] == "6.417"
    _, err = api.error(
        "POST", f"/boq-items/{wall['id']}/measurements",
        {"mode": "formula", "expression": "L * H", "inputs": {"L": {"value": 1, "unit": "m"},
                                                               "H": {"value": 1, "unit": "m"}}},
    )  # fmt: skip
    assert err["error_code"] == "UNIT_MISMATCH"
    _, err = api.error("POST", f"/boq-items/{wall['id']}/measurements", {"mode": "formula"})
    assert err["error_code"] == "VALIDATION_ERROR"


def test_freeze_creates_next_draft_and_protects_history(api: Api, db_session: Session) -> None:
    est = new_estimate(api, new_project(api))
    v1 = api.get(f"/versions/{est['draft_version_id']}")
    v1 = add_item(api, v1, description="Earthwork", unit="cum", rate="250")
    ew = item(v1, "Earthwork")
    v1 = api.post(
        f"/boq-items/{ew['id']}/measurements",
        {"length": 100, "breadth": 2, "depth_height": 1, "dimension_unit": "m"},
        201,
    )
    before = api.get(f"/versions/{v1['version']['id']}")

    status, err = api.error("POST", f"/versions/{v1['version']['id']}/freeze", {"change_note": " "})
    assert err["error_code"] == "VALIDATION_ERROR"
    v2 = api.post(f"/versions/{v1['version']['id']}/freeze", {"change_note": "Initial estimate"})
    assert v2["version"]["version_no"] == 2 and v2["version"]["status"] == "draft"
    assert v2["notice"] == "V1 saved. You are now editing V2."
    assert v2["totals"] == before["totals"]
    ew2 = item(v2, "Earthwork")
    assert ew2["line_key"] == ew["line_key"] and ew2["id"] != ew["id"]
    assert ew2["lines"][0]["calculation"]["substituted"] == "1 × 100 × 2 × 1"

    # V1 is read-only through the API ...
    status, err = api.error("PATCH", f"/boq-items/{ew['id']}", {"rate": "300"})
    assert (status, err["error_code"]) == (409, "VERSION_FROZEN")
    assert err["details"]["draft_version_no"] == 2
    for method, path in [
        ("POST", f"/versions/{v1['version']['id']}/sections"),
        ("POST", f"/boq-items/{ew['id']}/measurements"),
        ("DELETE", f"/boq-items/{ew['id']}"),
        ("POST", f"/versions/{v1['version']['id']}/freeze"),
    ]:
        status, err = api.error(method, path, {"title": "x", "change_note": "x", "length": 1})
        assert err["error_code"] == "VERSION_FROZEN", path
    # ... and in the database.
    with pytest.raises(DBAPIError, match="VERSION_FROZEN"):
        db_session.execute(text("UPDATE boq_items SET rate = 1 WHERE id = :i"), {"i": ew["id"]})
    db_session.rollback()

    # Changing V2 leaves V1 exactly as it was.
    api.patch(f"/boq-items/{ew2['id']}", {"rate": "300"})
    reopened = api.get(f"/versions/{v1['version']['id']}")
    assert reopened["version"]["status"] == "frozen"
    assert reopened["version"]["change_note"] == "Initial estimate"
    assert reopened["version"]["frozen_by_name"] == "Mahesh"
    assert reopened["can_edit"] is False
    assert reopened["sections"] == before["sections"]
    assert reopened["totals"] == before["totals"]

    versions = api.get(f"/estimates/{est['id']}/versions")
    assert [(x["version_no"], x["status"], x["works_subtotal"]) for x in versions] == [
        (2, "draft", "60000.00"),
        (1, "frozen", "50000.00"),
    ]


def test_sections_duplicate_and_reorder(api: Api) -> None:
    est = new_estimate(api, new_project(api))
    vid = est["draft_version_id"]
    v = api.post(f"/versions/{vid}/sections", {"title": "GSB"})
    v = api.post(f"/versions/{vid}/sections", {"title": "CC pavement"})
    general, gsb, cc = (s["id"] for s in v["sections"])
    v = add_item(api, v, description="A", unit="nos", quantity=1, rate=10, section_id=general)
    v = add_item(api, v, description="B", unit="nos", quantity=2, rate=10, section_id=general)
    a = item(v, "A")
    api.post(f"/boq-items/{a['id']}/measurements", {"nos": 3}, 201)
    v = api.post(f"/boq-items/{a['id']}/duplicate")
    names = [i["description"] for i in v["sections"][0]["items"]]
    assert names == ["A", "A", "B"]
    copy = v["sections"][0]["items"][1]
    assert copy["quantity"] == "3" and len(copy["lines"]) == 1 and copy["line_key"] != a["line_key"]

    ids = [i["id"] for i in v["sections"][0]["items"]]
    v = api.post(f"/versions/{vid}/boq-items/reorder", {"section_id": general, "ids": ids[::-1]})
    assert [i["description"] for i in v["sections"][0]["items"]] == ["B", "A", "A"]
    assert [i["sl_no"] for i in v["sections"][0]["items"]] == ["1.1", "1.2", "1.3"]
    _, err = api.error(
        "POST", f"/versions/{vid}/boq-items/reorder", {"section_id": general, "ids": ids[:1]}
    )
    assert err["error_code"] == "VALIDATION_ERROR"

    v = api.patch(f"/boq-items/{ids[2]}", {"section_id": cc})  # move B
    assert [i["description"] for i in v["sections"][2]["items"]] == ["B"]
    v = api.post(f"/versions/{vid}/sections/reorder", {"ids": [cc, general, gsb]})
    assert [s["title"] for s in v["sections"]] == ["CC pavement", "General works", "GSB"]
    assert v["sections"][0]["items"][0]["sl_no"] == "1.1"
    v = api.patch(f"/sections/{gsb}", {"title": "Granular sub-base"})
    assert v["sections"][2]["title"] == "Granular sub-base"
    v = api.delete(f"/sections/{general}")
    assert [s["title"] for s in v["sections"]] == ["CC pavement", "Granular sub-base"]
    assert v["totals"]["works_subtotal"] == "20.00"


def test_roles_and_isolation(make_client: Any, db_session: Session) -> None:
    owner = Api(make_client())
    me = register(owner.c, email="owner@example.com")
    pid = new_project(owner)
    est = new_estimate(owner, pid)
    vid = est["draft_version_id"]
    v = add_item(owner, owner.get(f"/versions/{vid}"), description="X", unit="nos", quantity=1)
    x = item(v, "X")
    v = owner.post(f"/boq-items/{x['id']}/measurements", {"nos": 2}, 201)
    line_id = item(v, "X")["lines"][0]["id"]
    v = owner.post(f"/versions/{vid}/parameters", {"name": "p", "value": 1}, 201)
    param_id = v["parameters"][0]["id"]

    viewer_id = add_org_member(db_session, me["organization"]["id"], "viewer@example.com")
    db_session.execute(
        text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, 'viewer')"),
        {"p": pid, "u": viewer_id},
    )
    db_session.commit()
    viewer = Api(login(make_client(), "viewer@example.com", "member pass 123"))
    seen = viewer.get(f"/versions/{vid}")
    assert (seen["my_role"], seen["can_edit"]) == ("viewer", False)
    status, err = viewer.error("PATCH", f"/boq-items/{x['id']}", {"rate": "1"})
    assert (status, err["error_code"]) == (403, "FORBIDDEN")
    status, _ = viewer.error("POST", f"/projects/{pid}/estimates", {"title": "Mine"})
    assert status == 403

    stranger = Api(make_client())
    register(stranger.c, email="stranger@example.com")
    for method, path in [
        ("GET", f"/versions/{vid}"),
        ("GET", f"/estimates/{est['id']}"),
        ("GET", f"/projects/{pid}/estimates"),
        ("PATCH", f"/boq-items/{x['id']}"),
        ("PATCH", f"/measurements/{line_id}"),
        ("GET", f"/measurements/{line_id}/calculation"),
        ("PATCH", f"/parameters/{param_id}"),
        ("POST", f"/versions/{vid}/freeze"),
    ]:
        status, _ = stranger.error(method, path, {"change_note": "x", "rate": "1", "value": 2})
        assert status == 404, path
    assert stranger.get("/estimates") == []


def test_recent_estimates_on_dashboard(api: Api) -> None:
    pid = new_project(api)
    est = new_estimate(api, pid)
    v = api.get(f"/versions/{est['draft_version_id']}")
    add_item(api, v, description="Item", unit="nos", quantity=2, rate="1500.25")
    recent = api.get("/estimates")
    assert recent[0]["works_subtotal_display"] == "₹3,000.50"
    assert recent[0]["project_name"] == "CC Road Miryalaguda"
    dashboard = api.get("/dashboard/summary")
    assert dashboard["recent_estimates"][0]["estimate_number"] == est["estimate_number"]

    api.patch(f"/estimates/{est['id']}", {"title": "Final estimate", "prepared_by": "AE, R&B"})
    assert api.get(f"/estimates/{est['id']}")["title"] == "Final estimate"
    api.delete(f"/estimates/{est['id']}")
    assert api.get(f"/projects/{pid}/estimates") == []
