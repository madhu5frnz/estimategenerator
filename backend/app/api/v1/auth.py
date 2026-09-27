from __future__ import annotations

from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import (
    DB,
    REFRESH_COOKIE,
    Auth,
    clear_session_cookies,
    client_info,
    set_session_cookies,
)
from app.api.envelope import Envelope, ok
from app.api.v1.me import MeOut, build_me
from app.config import get_settings
from app.core.errors import AppError
from app.core.security import now_utc
from app.services import accounts, google_oauth
from app.services.email import EmailSender, get_email_sender

router = APIRouter(prefix="/auth", tags=["auth"])
Sender = Annotated[EmailSender, Depends(get_email_sender)]
OAUTH_COOKIE = "eai_oauth"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)
    full_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=2000)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=2000)
    password: str = Field(max_length=128)


class Message(BaseModel):
    message: str


@router.post("/register", response_model=Envelope[MeOut], status_code=201)
def register(
    body: RegisterIn, request: Request, response: Response, db: DB, sender: Sender
) -> Envelope[MeOut]:
    user = accounts.register(
        db, email=body.email, password=body.password, full_name=body.full_name, sender=sender
    )
    tokens = accounts.issue_session(db, user, client_info(request))
    db.commit()
    set_session_cookies(response, tokens)
    return ok(build_me(db, user, tokens.organization_id))


@router.post("/login", response_model=Envelope[MeOut])
def login(body: LoginIn, request: Request, response: Response, db: DB) -> Envelope[MeOut]:
    tokens = accounts.login(
        db, email=body.email, password=body.password, client=client_info(request)
    )
    set_session_cookies(response, tokens)
    return ok(build_me(db, tokens.user, tokens.organization_id))


@router.post("/refresh", response_model=Envelope[Message])
def refresh(request: Request, response: Response, db: DB) -> Envelope[Message]:
    try:
        tokens = accounts.refresh(
            db, raw_token=request.cookies.get(REFRESH_COOKIE), client=client_info(request)
        )
    except AppError:
        clear_session_cookies(response)
        raise
    set_session_cookies(response, tokens)
    return ok(Message(message="Session refreshed."))


@router.post("/logout", response_model=Envelope[Message])
def logout(request: Request, response: Response, db: DB) -> Envelope[Message]:
    accounts.logout(db, raw_token=request.cookies.get(REFRESH_COOKIE))
    clear_session_cookies(response)
    return ok(Message(message="Signed out."))


@router.post("/verify-email", response_model=Envelope[Message])
def verify_email(body: TokenIn, db: DB) -> Envelope[Message]:
    accounts.verify_email(db, token=body.token)
    return ok(Message(message="Email confirmed."))


@router.post("/resend-verification", response_model=Envelope[Message])
def resend_verification(auth: Auth, sender: Sender) -> Envelope[Message]:
    if auth.user.email_verified_at is None:
        accounts.send_verification_email(auth.user, sender)
    return ok(Message(message="If your email is not yet confirmed, a new link has been sent."))


@router.post("/forgot-password", response_model=Envelope[Message])
def forgot_password(body: ForgotIn, db: DB, sender: Sender) -> Envelope[Message]:
    accounts.request_password_reset(db, email=body.email, sender=sender)
    return ok(Message(message="If an account exists for this email, a reset link has been sent."))


@router.post("/reset-password", response_model=Envelope[Message])
def reset_password(body: ResetIn, db: DB) -> Envelope[Message]:
    accounts.reset_password(db, token=body.token, new_password=body.password)
    return ok(Message(message="Password updated. Please sign in."))


# ------------------------------------------------------------------ Google
@router.get("/google/start", include_in_schema=False)
def google_start() -> RedirectResponse:
    settings = get_settings()
    auth_request = google_oauth.build_authorization_request()
    response = RedirectResponse(auth_request.url, status_code=302)
    sealed = jwt.encode(
        {
            "state": auth_request.state,
            "verifier": auth_request.code_verifier,
            "exp": now_utc() + timedelta(minutes=10),
        },
        settings.secret,
        algorithm="HS256",
    )
    response.set_cookie(
        OAUTH_COOKIE, sealed, max_age=600, httponly=True, secure=settings.cookie_secure,
        samesite="lax", path="/api/v1/auth/google",
    )  # fmt: skip
    return response


@router.get("/google/callback", include_in_schema=False)
def google_callback(request: Request, db: DB, code: str = "", state: str = "") -> RedirectResponse:
    base = get_settings().app_base_url
    failure = RedirectResponse(f"{base}/login?error=google", status_code=302)
    failure.delete_cookie(OAUTH_COOKIE, path="/api/v1/auth/google")
    sealed = request.cookies.get(OAUTH_COOKIE)
    if not code or not state or not sealed:
        return failure
    try:
        saved = jwt.decode(sealed, get_settings().secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return failure
    if saved.get("state") != state:
        return failure
    try:
        profile = google_oauth.fetch_profile(code, str(saved.get("verifier", "")))
        tokens = accounts.login_with_google(db, profile, client_info(request))
    except AppError:
        return failure
    response = RedirectResponse(f"{base}/dashboard", status_code=302)
    response.delete_cookie(OAUTH_COOKIE, path="/api/v1/auth/google")
    set_session_cookies(response, tokens)
    return response
