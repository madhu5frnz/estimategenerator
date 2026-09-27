"""Request dependencies: database session, authentication, CSRF and cookies."""

from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError
from app.core.security import TokenError, csrf_matches, decode_access_token
from app.db.session import get_db
from app.models import OrganizationMember, User
from app.services.accounts import ClientInfo, SessionTokens
from app.services.context import AuthContext

ACCESS_COOKIE = "eai_access"
REFRESH_COOKIE = "eai_refresh"
CSRF_COOKIE = "eai_csrf"
CSRF_HEADER = "x-csrf-token"
REFRESH_PATH = "/api/v1/auth"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

DB = Annotated[Session, Depends(get_db)]


def client_info(request: Request) -> ClientInfo:
    host = request.client.host if request.client else None
    try:
        ip = str(ipaddress.ip_address(host)) if host else None
    except ValueError:  # e.g. a unix socket or test client instead of an IP
        ip = None
    return ClientInfo(user_agent=request.headers.get("user-agent"), ip_address=ip)


def get_auth(request: Request, db: DB) -> AuthContext:
    token: str | None = None
    via_cookie = False
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    else:
        token = request.cookies.get(ACCESS_COOKIE)
        via_cookie = True
    if not token:
        raise AppError("UNAUTHENTICATED", "Please sign in.", 401)
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        message = "Your session has expired." if exc.code == "TOKEN_EXPIRED" else "Please sign in."
        raise AppError(exc.code, message, 401) from exc

    # Cookies are sent automatically by the browser, so cookie-authenticated writes must
    # also carry the CSRF token that only our own JavaScript can read.
    if (
        via_cookie
        and request.method not in SAFE_METHODS
        and not csrf_matches(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER))
    ):
        raise AppError("CSRF_FAILED", "Security check failed. Please reload the page.", 403)

    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise AppError("UNAUTHENTICATED", "Please sign in.", 401)
    role = db.scalar(
        select(OrganizationMember.role).where(
            OrganizationMember.organization_id == claims.organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if role is None:  # removed from the workspace since the token was issued
        raise AppError("UNAUTHENTICATED", "Please sign in.", 401)
    return AuthContext(user=user, organization_id=claims.organization_id, org_role=role)


Auth = Annotated[AuthContext, Depends(get_auth)]


def set_session_cookies(response: Response, tokens: SessionTokens) -> None:
    settings = get_settings()
    common = {"secure": settings.cookie_secure, "samesite": "lax", "domain": settings.cookie_domain}
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        max_age=settings.access_token_ttl_seconds,
        httponly=True,
        path="/",
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        path=REFRESH_PATH,
        **common,  # type: ignore[arg-type]
    )
    # Readable by our JavaScript so it can echo it in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE,
        tokens.csrf_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=False,
        path="/",
        **common,  # type: ignore[arg-type]
    )
    # Lets the Next.js server skip rendering app pages for signed-out visitors. It carries
    # no authority: every API call is still authenticated by the tokens above.
    response.set_cookie(
        "eai_session",
        "1",
        max_age=settings.refresh_token_ttl_days * 86400,
        path="/",
        **common,  # type: ignore[arg-type]
    )


def clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    for name, path in (
        (ACCESS_COOKIE, "/"),
        (REFRESH_COOKIE, REFRESH_PATH),
        (CSRF_COOKIE, "/"),
        ("eai_session", "/"),
    ):
        response.delete_cookie(name, path=path, domain=settings.cookie_domain)
