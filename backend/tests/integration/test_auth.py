from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration.conftest import MemorySender, csrf, register, requires_db

pytestmark = [pytest.mark.db, requires_db]


def test_register_creates_workspace_free_plan_and_session(
    client: TestClient, mailbox: MemorySender
) -> None:
    me = register(client, email="  Mahesh@Example.COM ")
    assert me["user"]["email"] == "mahesh@example.com"
    assert me["user"]["email_verified"] is False
    assert me["organization"]["role"] == "owner"
    assert me["organization"]["is_personal"] is True
    assert me["subscription"]["plan_code"] == "free"
    assert me["subscription"]["limits"]["projects"] == 3
    for cookie in ("eai_access", "eai_refresh", "eai_csrf", "eai_session"):
        assert client.cookies.get(cookie), cookie
    assert mailbox.sent[-1].to == "mahesh@example.com"
    assert client.get("/api/v1/me").json()["data"]["user"]["full_name"] == "Mahesh"


def test_register_duplicate_email_case_insensitive(client: TestClient) -> None:
    register(client)
    other = client.post(
        "/api/v1/auth/register",
        json={"email": "MAHESH@example.com", "password": "another pass 1", "full_name": "X"},
    )
    assert other.status_code == 409
    assert other.json()["error_code"] == "EMAIL_TAKEN"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"email": "a@b.co", "password": "short", "full_name": "A"}, "WEAK_PASSWORD"),
        ({"email": "a@b.co", "password": "aaaaaaaaaa", "full_name": "A"}, "WEAK_PASSWORD"),
        (
            {"email": "not-an-email", "password": "good pass 123", "full_name": "A"},
            "VALIDATION_ERROR",
        ),
        ({"email": "a@b.co", "password": "good pass 123", "full_name": "  "}, "VALIDATION_ERROR"),
    ],
)
def test_register_validation(client: TestClient, body: dict[str, str], code: str) -> None:
    response = client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 400
    assert response.json()["error_code"] == code


def test_login_errors_do_not_reveal_which_part_is_wrong(make_client: Any) -> None:
    register(make_client())
    fresh = make_client()
    wrong_pw = fresh.post(
        "/api/v1/auth/login", json={"email": "mahesh@example.com", "password": "nope nope 1"}
    )
    unknown = fresh.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "nope nope 1"}
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["error_code"] == unknown.json()["error_code"] == "INVALID_CREDENTIALS"
    assert wrong_pw.json()["message"] == unknown.json()["message"]


def test_login_success_and_disabled_account(make_client: Any, db_session: Session) -> None:
    register(make_client())
    fresh = make_client()
    ok = fresh.post(
        "/api/v1/auth/login", json={"email": "mahesh@example.com", "password": "correct horse 42"}
    )
    assert ok.status_code == 200
    db_session.execute(text("UPDATE users SET is_active = false"))
    db_session.commit()
    blocked = make_client().post(
        "/api/v1/auth/login", json={"email": "mahesh@example.com", "password": "correct horse 42"}
    )
    assert blocked.json()["error_code"] == "ACCOUNT_DISABLED"
    # An existing session stops working too.
    assert fresh.get("/api/v1/me").status_code == 401


def test_unauthenticated_and_bad_tokens(make_client: Any) -> None:
    anon = make_client()
    assert anon.get("/api/v1/me").json()["error_code"] == "UNAUTHENTICATED"
    assert anon.get("/api/v1/projects").status_code == 401
    anon.cookies.set("eai_access", "garbage")
    assert anon.get("/api/v1/me").json()["error_code"] == "UNAUTHENTICATED"


def test_expired_and_forged_access_tokens(client: TestClient) -> None:
    me = register(client)
    from app.config import get_settings

    past = datetime.now(UTC) - timedelta(minutes=5)
    claims = {
        "sub": me["user"]["id"],
        "org": me["organization"]["id"],
        "typ": "access",
        "exp": past,
    }
    expired = jwt.encode(claims, get_settings().jwt_key, algorithm="HS256")
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.json()["error_code"] == "TOKEN_EXPIRED"

    claims["exp"] = datetime.now(UTC) + timedelta(minutes=5)
    forged = jwt.encode(claims, "attacker-key-" + "x" * 40, algorithm="HS256")
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.json()["error_code"] == "UNAUTHENTICATED"

    unsigned = jwt.encode(claims, "", algorithm="none") if hasattr(jwt, "encode") else ""
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {unsigned}"})
    assert response.status_code == 401


def test_csrf_required_for_cookie_writes(client: TestClient) -> None:
    register(client)
    blocked = client.patch("/api/v1/me", json={"full_name": "Changed"})
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "CSRF_FAILED"
    wrong = client.patch("/api/v1/me", json={"full_name": "Changed"}, headers={"X-CSRF-Token": "x"})
    assert wrong.status_code == 403
    allowed = client.patch("/api/v1/me", json={"full_name": "Changed"}, headers=csrf(client))
    assert allowed.status_code == 200
    assert allowed.json()["data"]["user"]["full_name"] == "Changed"


def test_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    register(client)
    first = client.cookies.get("eai_refresh")
    rotated = client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    second = client.cookies.get("eai_refresh")
    assert second and second != first

    # An attacker replays the stolen, already-rotated token.
    thief = TestClient(client.app, raise_server_exceptions=False)
    thief.cookies.set("eai_refresh", first or "", path="/api/v1/auth")
    replay = thief.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["error_code"] == "SESSION_REVOKED"

    # The whole family is revoked: the legitimate newer token no longer works either.
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_refresh_token(client: TestClient) -> None:
    register(client)
    token = client.cookies.get("eai_refresh")
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.cookies.get("eai_access") is None
    again = TestClient(client.app, raise_server_exceptions=False)
    again.cookies.set("eai_refresh", token or "", path="/api/v1/auth")
    assert again.post("/api/v1/auth/refresh").status_code == 401


def test_email_verification(client: TestClient, mailbox: MemorySender) -> None:
    register(client)
    token = mailbox.last_link("verify-email")
    bad = client.post("/api/v1/auth/verify-email", json={"token": token[:-3] + "abc"})
    assert bad.json()["error_code"] == "LINK_INVALID"
    good = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert good.status_code == 200
    assert client.get("/api/v1/me").json()["data"]["user"]["email_verified"] is True


def test_password_reset_flow(make_client: Any, mailbox: MemorySender) -> None:
    session = make_client()
    register(session)
    anon = make_client()

    before = len(mailbox.sent)
    unknown = anon.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert unknown.status_code == 200
    assert len(mailbox.sent) == before  # nothing sent, same response

    anon.post("/api/v1/auth/forgot-password", json={"email": "mahesh@example.com"})
    token = mailbox.last_link("reset-password")
    weak = anon.post("/api/v1/auth/reset-password", json={"token": token, "password": "123"})
    assert weak.json()["error_code"] == "WEAK_PASSWORD"
    done = anon.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "brand new pass 9"}
    )
    assert done.status_code == 200

    reused = anon.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "another pass 99"}
    )
    assert reused.json()["error_code"] == "LINK_INVALID"
    # Existing sessions were signed out.
    assert session.post("/api/v1/auth/refresh").status_code == 401
    old = anon.post(
        "/api/v1/auth/login", json={"email": "mahesh@example.com", "password": "correct horse 42"}
    )
    assert old.status_code == 401
    new = anon.post(
        "/api/v1/auth/login", json={"email": "mahesh@example.com", "password": "brand new pass 9"}
    )
    assert new.status_code == 200


def test_profile_validation(client: TestClient) -> None:
    register(client)
    bad = client.patch("/api/v1/me", json={"phone": "12ab"}, headers=csrf(client))
    assert bad.json()["error_code"] == "VALIDATION_ERROR"
    good = client.patch("/api/v1/me", json={"phone": "+91 98765 43210"}, headers=csrf(client))
    assert good.json()["data"]["user"]["phone"] == "+919876543210"


def test_organization_settings(client: TestClient, db_session: Session) -> None:
    me = register(client)
    org_id = me["organization"]["id"]
    bad = client.patch(
        f"/api/v1/organizations/{org_id}", json={"gstin": "123"}, headers=csrf(client)
    )
    assert bad.json()["error_code"] == "VALIDATION_ERROR"
    good = client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Sri Sai Constructions", "gstin": "36aabcu9603r1zm", "state_code": "TS"},
        headers=csrf(client),
    )
    assert good.status_code == 200
    assert good.json()["data"]["gstin"] == "36AABCU9603R1ZM"
    rows = db_session.execute(
        text(
            "SELECT field, old_value, new_value FROM audit_logs"
            " WHERE entity_type = 'organization' ORDER BY field"
        )
    ).all()
    assert [r.field for r in rows] == ["gstin", "name", "state_code"]
    other_org = "00000000-0000-0000-0000-000000000099"
    assert client.get(f"/api/v1/organizations/{other_org}").status_code == 404


# ------------------------------------------------------------------- Google
@pytest.fixture
def google(app_env: None, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from app.config import get_settings
    from app.services import google_oauth
    from app.services.accounts import GoogleProfile

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:3000/api/v1/auth/google/callback"
    )
    get_settings.cache_clear()
    profile: dict[str, Any] = {
        "value": GoogleProfile(
            subject="g-123", email="mahesh@example.com", email_verified=True, name="Mahesh G"
        )
    }
    monkeypatch.setattr(google_oauth, "fetch_profile", lambda code, verifier: profile["value"])
    return profile


def _google_login(client: TestClient, state_override: str | None = None) -> Any:
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert start.status_code == 302
    assert start.headers["location"].startswith("https://accounts.google.com/")
    state = start.headers["location"].split("state=")[1].split("&")[0]
    return client.get(
        f"/api/v1/auth/google/callback?code=abc&state={state_override or state}",
        follow_redirects=False,
    )


def test_google_disabled_by_default(client: TestClient) -> None:
    response = client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert response.json()["error_code"] == "GOOGLE_LOGIN_NOT_CONFIGURED"


def test_google_login_creates_verified_account(google: dict[str, Any], client: TestClient) -> None:
    response = _google_login(client)
    assert response.status_code == 302
    assert response.headers["location"].endswith("/dashboard")
    me = client.get("/api/v1/me").json()["data"]
    assert me["user"]["email_verified"] is True
    assert me["user"]["has_password"] is False
    # Signing in again reuses the same account.
    again = TestClient(client.app, raise_server_exceptions=False)
    _google_login(again)
    assert again.get("/api/v1/me").json()["data"]["user"]["id"] == me["user"]["id"]


def test_google_state_mismatch_rejected(google: dict[str, Any], client: TestClient) -> None:
    response = _google_login(client, state_override="forged")
    assert response.headers["location"].endswith("/login?error=google")
    assert client.cookies.get("eai_access") is None


def test_google_unverified_email_rejected(google: dict[str, Any], client: TestClient) -> None:
    from app.services.accounts import GoogleProfile

    google["value"] = GoogleProfile(
        subject="g-9", email="x@example.com", email_verified=False, name="X"
    )
    assert _google_login(client).headers["location"].endswith("/login?error=google")


def test_google_login_defeats_pre_registration_takeover(
    google: dict[str, Any], make_client: Any
) -> None:
    attacker = make_client()
    register(attacker, email="mahesh@example.com", password="attacker pass 1")  # never verified
    owner = make_client()
    _google_login(owner)
    assert owner.get("/api/v1/me").json()["data"]["user"]["has_password"] is False
    # The attacker's password and session no longer work.
    assert attacker.post("/api/v1/auth/refresh").status_code == 401
    retry = make_client().post(
        "/api/v1/auth/login", json={"email": "mahesh@example.com", "password": "attacker pass 1"}
    )
    assert retry.status_code == 401
