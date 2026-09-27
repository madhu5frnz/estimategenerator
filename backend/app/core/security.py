"""Passwords, tokens and CSRF.

* Passwords: Argon2id.
* Access token: short-lived JWT (HS256, signed with JWT_SIGNING_KEY), in an HttpOnly cookie.
* Refresh token: opaque random string; only its SHA-256 is stored. Rotated on every use,
  and reuse of a rotated token revokes the whole token family (theft detection).
* Action tokens (email verification, password reset): signed JWTs bound to a fingerprint
  of the user's current state, so a reset link stops working once the password changes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher()
# Verified against when the email is unknown, so response time does not reveal accounts.
_DUMMY_HASH = _hasher.hash("not-a-real-password-used-for-timing")

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
_ALGORITHM = "HS256"


class TokenError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problem(password: str, email: str | None = None) -> str | None:
    """A human-readable reason the password is unacceptable, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if len(set(password)) < 4:
        return "Password is too simple."
    if email and password.lower() == email.lower():
        return "Password must not be your email address."
    return None


def now_utc() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- access token
@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    organization_id: uuid.UUID


def create_access_token(user_id: uuid.UUID, organization_id: uuid.UUID) -> str:
    settings = get_settings()
    issued = now_utc()
    payload = {
        "sub": str(user_id),
        "org": str(organization_id),
        "typ": "access",
        "iat": issued,
        "exp": issued + timedelta(seconds=settings.access_token_ttl_seconds),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token, get_settings().jwt_key, algorithms=[_ALGORITHM], options={"require": ["exp"]}
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("TOKEN_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("UNAUTHENTICATED") from exc
    if payload.get("typ") != "access":
        raise TokenError("UNAUTHENTICATED")
    try:
        return AccessClaims(uuid.UUID(payload["sub"]), uuid.UUID(payload["org"]))
    except (KeyError, ValueError) as exc:
        raise TokenError("UNAUTHENTICATED") from exc


# --------------------------------------------------------------- refresh token
def new_refresh_token() -> tuple[str, str]:
    """(raw token for the cookie, hash for the database)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# --------------------------------------------------------------- action tokens
def _fingerprint(value: str | None) -> str:
    key = get_settings().secret.encode()
    return hmac.new(key, (value or "").encode(), hashlib.sha256).hexdigest()[:24]


def create_action_token(
    purpose: str, user_id: uuid.UUID, bound_to: str | None, ttl: timedelta
) -> str:
    issued = now_utc()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": purpose,
        "fp": _fingerprint(bound_to),
        "iat": issued,
        "exp": issued + ttl,
    }
    return jwt.encode(payload, get_settings().secret, algorithm=_ALGORITHM)


def read_action_token(token: str, purpose: str) -> tuple[uuid.UUID, str]:
    """Returns (user_id, fingerprint). Check the fingerprint with :func:`fingerprint_matches`."""
    try:
        payload = jwt.decode(token, get_settings().secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("LINK_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("LINK_INVALID") from exc
    if payload.get("typ") != purpose:
        raise TokenError("LINK_INVALID")
    try:
        return uuid.UUID(payload["sub"]), str(payload["fp"])
    except (KeyError, ValueError) as exc:
        raise TokenError("LINK_INVALID") from exc


def fingerprint_matches(fingerprint: str, bound_to: str | None) -> bool:
    return hmac.compare_digest(fingerprint, _fingerprint(bound_to))


# ------------------------------------------------------------------------ CSRF
def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)
