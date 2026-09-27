from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration.conftest import add_org_member, login, register, requires_db
from tests.integration.test_estimates import Api

pytestmark = [pytest.mark.db, requires_db]

BRIEF = "Construction of 500 m long CC road, 5.5 m wide and 150 mm thick with 100 mm GSB."


@pytest.fixture
def api(client: TestClient) -> Api:
    register(client)
    return Api(client)


def project(api: Api) -> str:
    return str(
        api.post("/projects", {"name": "CC Road Miryalaguda", "project_type": "road"}, 201)["id"]
    )


def extract(api: Api, pid: str, description: str = BRIEF) -> dict[str, Any]:
    return api.post("/ai/extractions", {"project_id": pid, "text": description}, 201)


def comp(extraction: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in extraction["components"] if c["component_name"] == name)


def params(component: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in component["parameters"]}


GSB = "Granular sub-base (GSB)"


def test_rules_extraction_review_and_confirm(api: Api, db_session: Session) -> None:
    pid = project(api)
    ex = extract(api, pid)
    assert ex["provider"] == "rules"
    assert ex["status"] == "needs_input"
    cc = comp(ex, "CC pavement")
    assert cc["preview"]["value"] == "412.500"
    assert params(cc)["thickness"]["source_text"] == "150 mm thick"
    gsb = params(comp(ex, GSB))
    assert gsb["width"]["status"] == "missing"
    assert gsb["width"]["suggested_default"]["value"] == "5.5"
    assert [m["parameter"] for m in ex["missing_information"]] == ["width"]
    assert api.get(f"/ai/extractions/{ex['id']}")["id"] == ex["id"]

    # Missing width blocks the BOQ.
    status, err = api.error("POST", f"/ai/extractions/{ex['id']}/confirm", {})
    assert (status, err["error_code"]) == (400, "MISSING_PARAMETER")
    assert err["details"]["problems"][0]["parameter"] == "width"

    body = {
        "new_estimate_title": "CC road estimate",
        "components": [
            {"key": comp(ex, GSB)["key"], "parameters": {"width": {"accept_default": True}}}
        ],
    }
    done = api.post(f"/ai/extractions/{ex['id']}/confirm", body)
    assert done["items_created"] == 2
    version = api.get(f"/versions/{done['version_id']}")
    assert version["estimate"]["title"] == "CC road estimate"
    section = version["sections"][-1]
    assert section["title"] == "Works from description"
    qty = {i["description"]: (i["quantity"], i["unit"], i["provenance"]) for i in section["items"]}
    assert qty == {
        "CC pavement": ("412.500", "cum", "rule_extracted"),
        GSB: ("275.000", "cum", "rule_extracted"),
    }
    by_name = {p["name"]: p for p in version["parameters"]}
    assert by_name["road_length"]["used_by"] == 2  # one shared value for both layers
    assert by_name["road_length"]["provenance"] == "rule_extracted"
    assert by_name["road_length"]["source_text"] == "500 m long"
    assert by_name["layer_width_gsb"]["provenance"] == "default_accepted"
    assert by_name["layer_thickness_gsb"]["value"] == "100"
    assert by_name["layer_thickness_gsb"]["unit"] == "mm"

    accepted = db_session.execute(
        text("SELECT new_value FROM audit_logs WHERE action = 'accept_default'")
    ).scalar_one()
    assert accepted == {"name": "layer_width_gsb", "value": "5.5", "unit": "m"}
    # The rules parser is free: nothing counted against the AI quota.
    assert api.get("/me")["usage"]["ai_generations"] == 0

    status, err = api.error("POST", f"/ai/extractions/{ex['id']}/confirm", body)
    assert (status, err["error_code"]) == (409, "ALREADY_CONFIRMED")
    assert api.get(f"/ai/extractions/{ex['id']}")["result"]["version_id"] == done["version_id"]


def test_user_corrections_are_marked_and_components_can_be_skipped(api: Api) -> None:
    pid = project(api)
    ex = extract(
        api,
        pid,
        "Construction of 2 km CC road, 5.5 m wide, 150 mm thick, including earthwork, GSB and kerbs.",
    )
    cc, gsb, kerb = comp(ex, "CC pavement"), comp(ex, GSB), comp(ex, "Kerb")
    assert [c["description"] for c in ex["custom_items"]] == ["Earthwork / excavation"]
    body = {
        "components": [
            {"key": cc["key"], "parameters": {"width": {"value": "6", "unit": "m"}}},
            {"key": gsb["key"], "parameters": {"width": {"value": "6", "unit": "m"},
                                               "thickness": {"value": "100", "unit": "mm"}}},
            {"key": kerb["key"], "include": False},
        ],
    }  # fmt: skip
    done = api.post(f"/ai/extractions/{ex['id']}/confirm", body)
    assert done["items_created"] == 3  # CC, GSB, earthwork (kerb skipped)
    version = api.get(f"/versions/{done['version_id']}")
    items = {i["description"]: i for i in version["sections"][-1]["items"]}
    assert items["CC pavement"]["quantity"] == "1800.000"  # 2000 × 6 × 0.15
    assert items[GSB]["quantity"] == "1200.000"
    earthwork = items["Earthwork / excavation"]
    assert (earthwork["quantity"], earthwork["provenance"]) == (None, "ai_suggested")
    by_name = {p["name"]: p for p in version["parameters"]}
    assert by_name["layer_width"]["provenance"] == "user_entered"
    assert by_name["layer_width"]["used_by"] == 2  # same user value shared
    assert by_name["road_length"]["provenance"] == "rule_extracted"


def test_confirm_into_existing_estimate_and_validation(api: Api) -> None:
    pid = project(api)
    est = api.post(f"/projects/{pid}/estimates", {"title": "Main estimate"}, 201)
    ex = extract(
        api,
        pid,
        "Compound wall 120 m long, 2.1 m high, 230 mm thick brickwork with plastering on both sides",
    )
    for bad, reason in [
        ({"L": {"value": "-1", "unit": "m"}}, "Cannot be negative."),
        ({"L": {"value": "abc", "unit": "m"}}, "Not a number."),
        ({"L": {"value": "10", "unit": "kg"}}, "Needs a length unit."),
    ]:
        _, err = api.error(
            "POST", f"/ai/extractions/{ex['id']}/confirm",
            {"estimate_id": est["id"], "components": [{"key": "c1", "parameters": bad}]},
        )  # fmt: skip
        assert err["details"]["problems"][0]["reason"] == reason
    done = api.post(f"/ai/extractions/{ex['id']}/confirm", {"estimate_id": est["id"]})
    assert done["estimate_id"] == est["id"]
    version = api.get(f"/versions/{done['version_id']}")
    items = {i["description"]: i["quantity"] for i in version["sections"][-1]["items"]}
    assert items == {"Masonry wall": "57.960", "Plastering": "504.00"}  # 120×2.1×0.23; 120×2.1×2
    other = api.post("/projects", {"name": "Other", "project_type": "road"}, 201)
    ex2 = extract(api, str(other["id"]), BRIEF)
    _, err = api.error("POST", f"/ai/extractions/{ex2['id']}/confirm", {"estimate_id": est["id"]})
    assert err["error_code"] == "VALIDATION_ERROR"


def test_input_checks_and_access(make_client: Any, db_session: Session) -> None:
    owner = Api(make_client())
    me = register(owner.c, email="owner@example.com")
    pid = project(owner)
    status, err = owner.error("POST", "/ai/extractions", {"project_id": pid, "text": "   "})
    assert err["error_code"] == "VALIDATION_ERROR"
    status, err = owner.error("POST", "/ai/extractions", {"project_id": pid, "text": "x" * 4001})
    assert err["error_code"] == "INPUT_TOO_LONG"
    ex = extract(owner, pid)

    viewer_id = add_org_member(db_session, me["organization"]["id"], "viewer@example.com")
    db_session.execute(
        text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, 'viewer')"),
        {"p": pid, "u": viewer_id},
    )
    db_session.commit()
    viewer = Api(login(make_client(), "viewer@example.com", "member pass 123"))
    assert viewer.get(f"/ai/extractions/{ex['id']}")["id"] == ex["id"]
    status, _ = viewer.error("POST", "/ai/extractions", {"project_id": pid, "text": BRIEF})
    assert status == 403
    status, _ = viewer.error("POST", f"/ai/extractions/{ex['id']}/confirm", {})
    assert status in (400, 403)

    stranger = Api(make_client())
    register(stranger.c, email="stranger@example.com")
    assert stranger.error("GET", f"/ai/extractions/{ex['id']}")[0] == 404
    assert stranger.error("POST", "/ai/extractions", {"project_id": pid, "text": BRIEF})[0] == 404


# -------------------------------------------------------- metered provider
@pytest.fixture
def mock_provider(app_env: None, monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.ai import providers
    from app.config import get_settings

    monkeypatch.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    providers._provider.cache_clear()
    providers.MockProvider.responses.clear()
    yield providers.MockProvider
    providers.MockProvider.responses.clear()
    providers._provider.cache_clear()


def test_invented_value_must_be_confirmed(mock_provider: Any, client: TestClient) -> None:
    api = Api(client)
    register(client)
    pid = project(api)
    description = "CC road 500 m long and 5.5 m wide"
    mock_provider.register(description, {
        "project_type": "road",
        "components": [{"component_name": "CC pavement", "template_id": "road_layer", "parameters": [
            {"name": "length", "value": 500, "unit": "m", "source_text": "500 m long"},
            {"name": "width", "value": 5.5, "unit": "m", "source_text": "5.5 m wide"},
            {"name": "thickness", "value": 200, "unit": "mm", "source_text": "200 mm thick"},
        ]}],
        "missing_information": [], "custom_items": [], "assumptions": [],
    })  # fmt: skip
    ex = extract(api, pid, description)
    assert ex["provider"] == "mock"
    thickness = params(comp(ex, "CC pavement"))["thickness"]
    assert thickness["status"] == "needs_confirmation"
    _, err = api.error("POST", f"/ai/extractions/{ex['id']}/confirm", {})
    assert err["details"]["problems"][0]["reason"] == "Please confirm this value."
    body = {
        "components": [{"key": "c1", "parameters": {"thickness": {"value": "200", "unit": "mm"}}}]
    }
    done = api.post(f"/ai/extractions/{ex['id']}/confirm", body)
    version = api.get(f"/versions/{done['version_id']}")
    by_name = {p["name"]: p for p in version["parameters"]}
    assert by_name["layer_thickness"]["provenance"] == "user_entered"
    assert by_name["road_length"]["provenance"] == "ai_extracted"


def test_quota_cache_and_ledger(
    mock_provider: Any, client: TestClient, db_session: Session
) -> None:
    api = Api(client)
    register(client)
    pid = project(api)
    for n in range(5):
        extract(api, pid, f"CC road {100 + n} m long")
    assert api.get("/me")["usage"]["ai_generations"] == 5
    status, err = api.error(
        "POST", "/ai/extractions", {"project_id": pid, "text": "CC road 999 m long"}
    )
    assert (status, err["error_code"]) == (429, "QUOTA_EXCEEDED")
    # The same description again is served from the cache and costs nothing.
    cached = extract(api, pid, "CC road 100 m long")
    assert cached["served_from_cache"] is True
    assert api.get("/me")["usage"]["ai_generations"] == 5
    rows = db_session.execute(
        text("SELECT model, input_tokens, output_tokens, served_from_cache, status FROM ai_generations"
             " ORDER BY created_at")
    ).all()  # fmt: skip
    assert len(rows) == 6  # 5 generations + 1 cache hit; the refused request made no call
    assert rows[0].input_tokens == 1200 and rows[0].model == "mock"
    assert rows[-1].served_from_cache is True and rows[-1].input_tokens == 0
