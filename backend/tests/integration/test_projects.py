from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration.conftest import add_org_member, csrf, login, register, requires_db

pytestmark = [pytest.mark.db, requires_db]

ROAD = {
    "name": "CC Road Miryalaguda",
    "project_type": "road",
    "district": "Nalgonda",
    "state": "Telangana",
    "estimated_value": "3097500.00",
    "client_department": "R&B",
    "reference_number": "RB/NLG/2026/14",
    "project_date": "2026-09-27",
}


def create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/api/v1/projects", json={**ROAD, **overrides}, headers=csrf(client))
    assert response.status_code == 201, response.text
    return response.json()["data"]  # type: ignore[no-any-return]


def test_create_get_update_delete_with_audit(client: TestClient, db_session: Session) -> None:
    register(client)
    project = create(client)
    assert project["my_role"] == "admin"
    assert project["estimated_value"] == "3097500.00"
    assert project["status"] == "draft"
    assert project["project_type_label"] == "Road"

    got = client.get(f"/api/v1/projects/{project['id']}").json()["data"]
    assert got["reference_number"] == "RB/NLG/2026/14"

    patched = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"name": "CC Road Miryalaguda (revised)", "status": "in_progress", "location": "  "},
        headers=csrf(client),
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["status"] == "in_progress"

    audit = db_session.execute(
        text(
            "SELECT action, field, old_value, new_value, actor_display FROM audit_logs"
            " WHERE project_id = :p ORDER BY id"
        ),
        {"p": project["id"]},
    ).all()
    assert audit[0].action == "create"
    updates = {row.field: (row.old_value, row.new_value) for row in audit if row.action == "update"}
    assert updates["name"] == ("CC Road Miryalaguda", "CC Road Miryalaguda (revised)")
    assert updates["status"] == ("draft", "in_progress")
    assert "location" not in updates  # blank stays None: no change recorded
    assert audit[0].actor_display == "Mahesh"

    deleted = client.delete(f"/api/v1/projects/{project['id']}", headers=csrf(client))
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 404


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"name": ""}, "name"),
        ({"project_type": "spaceport"}, "project_type"),
        ({"estimated_value": "-5"}, "estimated_value"),
        ({"estimated_value": "12.345"}, "estimated_value"),
        ({"project_date": "27-09-2026"}, "project_date"),
    ],
)
def test_create_validation(client: TestClient, body: dict[str, Any], field: str) -> None:
    register(client)
    response = client.post("/api/v1/projects", json={**ROAD, **body}, headers=csrf(client))
    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "VALIDATION_ERROR"
    assert field in {f["field"] for f in payload["details"]["fields"]}


def test_work_category_must_match_type(client: TestClient) -> None:
    register(client)
    categories = client.get("/api/v1/work-categories?project_type=building").json()["data"]
    assert categories and {c["project_type"] for c in categories} == {"building"}
    building_cat = categories[0]["id"]
    response = client.post(
        "/api/v1/projects", json={**ROAD, "work_category_id": building_cat}, headers=csrf(client)
    )
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    road_cat = client.get("/api/v1/work-categories?project_type=road").json()["data"][0]["id"]
    ok = client.post(
        "/api/v1/projects", json={**ROAD, "work_category_id": road_cat}, headers=csrf(client)
    )
    assert ok.status_code == 201
    # Changing the type without changing the category is rejected too.
    project_id = ok.json()["data"]["id"]
    changed = client.patch(
        f"/api/v1/projects/{project_id}", json={"project_type": "building"}, headers=csrf(client)
    )
    assert changed.json()["error_code"] == "VALIDATION_ERROR"


def test_project_types_listed(client: TestClient) -> None:
    types = client.get("/api/v1/project-types").json()["data"]
    assert {"code": "lift_irrigation", "label": "Lift Irrigation"} in types
    assert len(types) == 13


def test_free_plan_project_limit(client: TestClient) -> None:
    register(client)
    ids = [create(client, name=f"Project {i}")["id"] for i in range(3)]
    blocked = client.post("/api/v1/projects", json=ROAD, headers=csrf(client))
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "PLAN_LIMIT_REACHED"
    assert blocked.json()["details"] == {"limit": 3, "plan": "free"}
    client.delete(f"/api/v1/projects/{ids[0]}", headers=csrf(client))
    assert client.post("/api/v1/projects", json=ROAD, headers=csrf(client)).status_code == 201


def test_list_search_filter_pagination(client: TestClient, db_session: Session) -> None:
    register(client)
    db_session.execute(
        text("UPDATE plans SET limits = limits || '{\"projects\": null}' WHERE code = 'free'")
    )
    db_session.commit()
    try:
        create(client, name="CC Road Miryalaguda")
        create(client, name="Minor canal lining D-12", project_type="canal", district="Suryapet")
        create(client, name="School building 100%", project_type="building")
        create(client, name="Drain works", project_type="drain", reference_number="DR_2026")

        def names(query: str) -> list[str]:
            body = client.get(f"/api/v1/projects{query}").json()
            return sorted(p["name"] for p in body["data"])

        assert names("?q=canal") == ["Minor canal lining D-12"]
        assert names("?q=suryapet") == ["Minor canal lining D-12"]
        assert names("?q=100%25") == ["School building 100%"]  # % is literal, not a wildcard
        assert names("?q=DR_") == ["Drain works"]
        assert names("?type=building") == ["School building 100%"]
        assert len(names("")) == 4

        page = client.get("/api/v1/projects?page=2&page_size=3").json()
        assert page["meta"]["total"] == 4
        assert len(page["data"]) == 1
        assert client.get("/api/v1/projects?page_size=500").status_code == 400
    finally:
        db_session.execute(
            text("UPDATE plans SET limits = limits || '{\"projects\": 3}' WHERE code = 'free'")
        )
        db_session.commit()


def test_other_organisations_cannot_see_or_touch_projects(make_client: Any) -> None:
    owner = make_client()
    register(owner, email="owner@example.com")
    project = create(owner)

    stranger = make_client()
    register(stranger, email="stranger@example.com")
    pid = project["id"]
    assert stranger.get(f"/api/v1/projects/{pid}").status_code == 404
    assert (
        stranger.patch(
            f"/api/v1/projects/{pid}", json={"name": "x"}, headers=csrf(stranger)
        ).status_code
        == 404
    )
    assert stranger.delete(f"/api/v1/projects/{pid}", headers=csrf(stranger)).status_code == 404
    assert stranger.get("/api/v1/projects").json()["data"] == []
    assert stranger.get("/api/v1/dashboard/summary").json()["data"]["total_projects"] == 0
    # The owner's project is untouched.
    assert owner.get(f"/api/v1/projects/{pid}").json()["data"]["name"] == ROAD["name"]


def test_project_roles_within_an_organisation(make_client: Any, db_session: Session) -> None:
    owner = make_client()
    me = register(owner, email="owner@example.com")
    org_id = me["organization"]["id"]
    visible = create(owner, name="Shared road")
    hidden = create(owner, name="Private road")

    member_id = add_org_member(db_session, org_id, "viewer@example.com")
    db_session.execute(
        text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, 'viewer')"),
        {"p": visible["id"], "u": member_id},
    )
    db_session.commit()
    member = login(make_client(), "viewer@example.com", "member pass 123")

    assert [p["name"] for p in member.get("/api/v1/projects").json()["data"]] == ["Shared road"]
    assert member.get(f"/api/v1/projects/{hidden['id']}").status_code == 404
    as_viewer = member.get(f"/api/v1/projects/{visible['id']}").json()["data"]
    assert as_viewer["my_role"] == "viewer"
    edit = member.patch(
        f"/api/v1/projects/{visible['id']}", json={"name": "x"}, headers=csrf(member)
    )
    assert edit.status_code == 403
    assert edit.json()["error_code"] == "FORBIDDEN"

    db_session.execute(
        text("UPDATE project_members SET role = 'professional' WHERE user_id = :u"),
        {"u": member_id},
    )
    db_session.commit()
    edit = member.patch(
        f"/api/v1/projects/{visible['id']}", json={"district": "Nalgonda"}, headers=csrf(member)
    )
    assert edit.status_code == 200
    delete = member.delete(f"/api/v1/projects/{visible['id']}", headers=csrf(member))
    assert delete.status_code == 403
    # Members cannot change workspace settings either.
    org_edit = member.patch(
        f"/api/v1/organizations/{org_id}", json={"name": "Mine"}, headers=csrf(member)
    )
    assert org_edit.status_code == 403


def test_removed_member_loses_access_immediately(make_client: Any, db_session: Session) -> None:
    owner = make_client()
    org_id = register(owner, email="owner@example.com")["organization"]["id"]
    member_id = add_org_member(db_session, org_id, "temp@example.com", role="admin")
    member = login(make_client(), "temp@example.com", "member pass 123")
    assert member.get("/api/v1/projects").status_code == 200
    db_session.execute(
        text("DELETE FROM organization_members WHERE user_id = :u"), {"u": member_id}
    )
    db_session.commit()
    assert member.get("/api/v1/projects").status_code == 401


def test_dashboard_summary(client: TestClient) -> None:
    register(client)
    create(client, name="A", estimated_value="1234567.00")
    b = create(client, name="B", estimated_value="1000000.50")
    client.patch(f"/api/v1/projects/{b['id']}", json={"status": "completed"}, headers=csrf(client))
    create(client, name="C", estimated_value=None)
    data = client.get("/api/v1/dashboard/summary").json()["data"]
    assert data["total_projects"] == 3
    assert data["draft_projects"] == 2
    assert data["completed_projects"] == 1
    assert data["total_estimated_value"] == "2234567.50"
    assert data["total_estimated_value_display"] == "₹22,34,567.50"
    assert data["recent_projects"][0]["name"] in {"B", "C"}
    assert data["subscription"]["plan_code"] == "free"
    assert data["usage"]["projects"] == 3
