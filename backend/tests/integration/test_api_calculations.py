from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def post(client: TestClient, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    response = client.post(f"/api/v1{path}", json=body)
    return response.status_code, response.json()


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_request_id_is_echoed_or_generated(client: TestClient) -> None:
    given = client.get("/healthz", headers={"X-Request-ID": "abc12345-test"})
    assert given.headers["x-request-id"] == "abc12345-test"
    generated = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert generated.headers["x-request-id"] != "bad id with spaces"
    assert len(generated.headers["x-request-id"]) == 32


def test_system_info_reports_rules_provider_without_key(client: TestClient) -> None:
    body = client.get("/api/v1/system/info").json()
    assert body["success"] is True
    assert body["data"]["ai_provider"] in {"rules", "anthropic", "mock"}
    assert body["data"]["engine_version"]


def test_calculate_template_brief_example(client: TestClient) -> None:
    status, body = post(
        client,
        "/calculate",
        {
            "template_id": "road_layer",
            "parameters": {
                "length": {"value": "500", "unit": "m"},
                "width": {"value": 5.5, "unit": "m"},
                "thickness": {"value": "150", "unit": "mm"},
            },
        },
    )
    assert status == 200
    data = body["data"]
    assert data["value"] == "412.500"
    assert data["display"] == "412.500 Cum"
    assert data["substituted"] == "500 × 5.5 × 0.15"
    assert data["check"] == "Calculation check passed"
    assert body["meta"]["request_id"]


def test_calculate_missing_parameter_error_envelope(client: TestClient) -> None:
    status, body = post(
        client,
        "/calculate",
        {"template_id": "road_layer", "parameters": {"length": {"value": "500", "unit": "m"}}},
    )
    assert status == 400
    assert body["success"] is False
    assert body["error_code"] == "MISSING_PARAMETER"
    assert body["details"] == {"parameters": ["width", "thickness"]}
    assert body["request_id"]
    assert "Traceback" not in str(body)


def test_calculate_custom_expression(client: TestClient) -> None:
    status, body = post(
        client,
        "/calculate",
        {
            "expression": "pi * D^2 / 4 * L",
            "output_unit": "Cu.m",
            "parameters": {"D": {"value": "300", "unit": "mm"}, "L": {"value": "100", "unit": "m"}},
        },
    )
    assert status == 200
    assert body["data"]["value"] == "7.069"
    assert body["data"]["expression"] == "π × D² / 4 × L"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({}, "VALIDATION_ERROR"),
        ({"template_id": "road_layer", "expression": "L"}, "VALIDATION_ERROR"),
        ({"expression": "L * B"}, "VALIDATION_ERROR"),
        ({"template_id": "nope"}, "NOT_FOUND"),
        ({"expression": "__import__('os')", "output_unit": "cum"}, "FORMULA_INVALID"),
        ({"expression": "L", "output_unit": "furlong"}, "UNKNOWN_UNIT"),
    ],
)
def test_calculate_errors(client: TestClient, body: dict[str, Any], code: str) -> None:
    status, payload = post(client, "/calculate", body)
    assert status in (400, 404)
    assert payload["error_code"] == code


def test_list_templates_and_units(client: TestClient) -> None:
    templates = client.get("/api/v1/calculation-templates").json()["data"]
    road = next(t for t in templates if t["id"] == "road_layer")
    assert road["expression_display"] == "length × width × thickness"
    assert road["output_unit_display"] == "Cum"
    assert {p["canonical_unit"] for p in road["parameters"]} == {"m"}
    only_road = client.get("/api/v1/calculation-templates?category=road").json()["data"]
    assert {t["category"] for t in only_road} == {"road"}
    units = client.get("/api/v1/units").json()["data"]
    assert any(u["code"] == "cum" and u["is_canonical"] for u in units)


def test_convert(client: TestClient) -> None:
    status, body = post(
        client, "/units/convert", {"value": "1000", "from_unit": "sft", "to_unit": "sq.m"}
    )
    assert status == 200
    assert body["data"] == {
        "value": "92.90304000",
        "display": "92.90 Sq.m",
        "from_unit": "sqft",
        "to_unit": "sqm",
    }


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"value": "1", "from_unit": "m", "to_unit": "kg"}, "UNIT_MISMATCH"),
        ({"value": "abc", "from_unit": "m", "to_unit": "ft"}, "INVALID_INPUT"),
        ({"value": None, "from_unit": "m", "to_unit": "ft"}, "VALIDATION_ERROR"),
    ],
)
def test_convert_errors(client: TestClient, body: dict[str, Any], code: str) -> None:
    status, payload = post(client, "/units/convert", body)
    assert status == 400
    assert payload["error_code"] == code


def test_validate_expression(client: TestClient) -> None:
    status, body = post(client, "/calculate/validate-expression", {"expression": "L*(a+b)*t"})
    assert status == 200
    assert body["data"] == {
        "expression_display": "L × (a + b) × t",
        "parameters": ["L", "a", "b", "t"],
    }


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


def test_unhandled_error_hides_details(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import calculations

    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(calculations, "evaluate_template", boom)
    status, body = post(client, "/calculate", {"template_id": "road_layer", "parameters": {}})
    assert status == 500
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "secret" not in body["message"]


def test_readyz_reports_unavailable_services(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.db.session import get_engine

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:1/none")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["details"]["checks"] == {
            "database": "unavailable",
            "redis": "unavailable",
        }
    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()
