"""Google sign-in (OpenID Connect authorization-code flow with PKCE).

The code is exchanged server-side with the client secret over TLS, and the profile is
read from Google's userinfo endpoint with the resulting access token.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.errors import AppError
from app.services.accounts import GoogleProfile

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass(frozen=True)
class AuthorizationRequest:
    url: str
    state: str
    code_verifier: str


def _require_config() -> None:
    if not get_settings().google_login_enabled:
        raise AppError("GOOGLE_LOGIN_NOT_CONFIGURED", "Google sign-in is not available.", 404)


def build_authorization_request() -> AuthorizationRequest:
    _require_config()
    settings = get_settings()
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    query = urlencode(
        {
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return AuthorizationRequest(url=f"{AUTH_URL}?{query}", state=state, code_verifier=verifier)


def fetch_profile(code: str, code_verifier: str) -> GoogleProfile:
    _require_config()
    settings = get_settings()
    assert settings.google_oauth_client_secret is not None
    try:
        with httpx.Client(timeout=10) as client:
            token_response = client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret.get_secret_value(),
                    "redirect_uri": settings.google_oauth_redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
            if token_response.status_code != 200:
                raise AppError("GOOGLE_LOGIN_FAILED", "Google sign-in failed. Please try again.")
            access_token = token_response.json().get("access_token")
            info = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            if info.status_code != 200:
                raise AppError("GOOGLE_LOGIN_FAILED", "Google sign-in failed. Please try again.")
            data = info.json()
    except httpx.HTTPError as exc:
        raise AppError(
            "GOOGLE_LOGIN_FAILED", "Could not reach Google. Please try again.", 502
        ) from exc
    if not data.get("sub") or not data.get("email"):
        raise AppError("GOOGLE_LOGIN_FAILED", "Google did not return an email address.")
    return GoogleProfile(
        subject=str(data["sub"]),
        email=str(data["email"]),
        email_verified=bool(data.get("email_verified")),
        name=str(data.get("name") or ""),
    )
