from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import get_settings
from app.core.errors import AppError
from app.services import google_oauth


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://app.test/api/v1/auth/google/callback")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def use_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    real_client = httpx.Client

    def factory(**kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(record), **kwargs)

    monkeypatch.setattr(google_oauth.httpx, "Client", factory)
    return seen


def test_authorization_url_uses_pkce_and_state() -> None:
    request = google_oauth.build_authorization_request()
    query = parse_qs(urlparse(request.url).query)
    assert query["state"] == [request.state]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0] != request.code_verifier
    assert query["scope"] == ["openid email profile"]


def test_fetch_profile_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at"})
        assert request.headers["authorization"] == "Bearer at"
        return httpx.Response(
            200, json={"sub": "1", "email": "a@b.test", "email_verified": True, "name": "A"}
        )

    seen = use_transport(monkeypatch, handler)
    profile = google_oauth.fetch_profile("code", "verifier")
    assert (profile.subject, profile.email, profile.email_verified) == ("1", "a@b.test", True)
    assert b"code_verifier=verifier" in seen[0].content


@pytest.mark.parametrize(
    ("token_status", "info_status", "info_body"),
    [
        (400, 200, {}),
        (200, 401, {}),
        (200, 200, {"sub": "1"}),  # no email
    ],
)
def test_fetch_profile_failures(
    monkeypatch: pytest.MonkeyPatch, token_status: int, info_status: int, info_body: dict[str, Any]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(token_status, json={"access_token": "at"})
        return httpx.Response(info_status, json=info_body)

    use_transport(monkeypatch, handler)
    with pytest.raises(AppError) as exc:
        google_oauth.fetch_profile("code", "verifier")
    assert exc.value.error_code == "GOOGLE_LOGIN_FAILED"


def test_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    use_transport(monkeypatch, handler)
    with pytest.raises(AppError) as exc:
        google_oauth.fetch_profile("code", "verifier")
    assert exc.value.status_code == 502


def test_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID")
    get_settings.cache_clear()
    with pytest.raises(AppError) as exc:
        google_oauth.build_authorization_request()
    assert exc.value.error_code == "GOOGLE_LOGIN_NOT_CONFIGURED"


def test_production_requires_real_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings()
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("JWT_SIGNING_KEY", "short")
    with pytest.raises(ValidationError, match="JWT_SIGNING_KEY"):
        Settings()
    monkeypatch.setenv("JWT_SIGNING_KEY", "y" * 40)
    assert Settings().cookie_secure is True
