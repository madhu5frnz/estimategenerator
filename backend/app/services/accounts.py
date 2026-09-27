"""Accounts and sessions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError
from app.core.ids import new_id
from app.core.security import (
    TokenError,
    create_access_token,
    create_action_token,
    fingerprint_matches,
    hash_password,
    hash_refresh_token,
    new_csrf_token,
    new_refresh_token,
    now_utc,
    password_problem,
    read_action_token,
    verify_password,
)
from app.models import (
    OAuthAccount,
    Organization,
    OrganizationMember,
    RefreshToken,
    Subscription,
    User,
)
from app.services import audit
from app.services.email import Email, EmailSender

VERIFY_TTL = timedelta(hours=48)
RESET_TTL = timedelta(hours=1)
FREE_PLAN = "free"


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    user: User
    organization_id: uuid.UUID


@dataclass(frozen=True)
class ClientInfo:
    user_agent: str | None = None
    ip_address: str | None = None


def normalise_email(email: str) -> str:
    return email.strip().lower()


# ------------------------------------------------------------------ creation
def _create_user_with_workspace(
    db: Session, *, email: str, full_name: str, password_hash: str | None, verified: bool
) -> User:
    now = now_utc()
    user = User(
        id=new_id(),
        email=email,
        full_name=full_name.strip(),
        password_hash=password_hash,
        email_verified_at=now if verified else None,
    )
    org = Organization(id=new_id(), name=f"{user.full_name}'s workspace", is_personal=True)
    db.add_all([user, org])
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    db.add(
        Subscription(
            id=new_id(),
            organization_id=org.id,
            plan_code=FREE_PLAN,
            status="active",
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
    )
    audit.record(
        db, actor=user, organization_id=org.id, entity_type="user", entity_id=user.id,
        action="register",
    )  # fmt: skip
    return user


def register(
    db: Session, *, email: str, password: str, full_name: str, sender: EmailSender
) -> User:
    email = normalise_email(email)
    problem = password_problem(password, email)
    if problem:
        raise AppError("WEAK_PASSWORD", problem, details={"field": "password"})
    if not full_name.strip():
        raise AppError(
            "VALIDATION_ERROR", "Please enter your name.", details={"field": "full_name"}
        )
    if db.scalar(select(User.id).where(User.email == email)):
        raise AppError(
            "EMAIL_TAKEN", "An account with this email already exists. Try signing in.", 409
        )
    try:
        user = _create_user_with_workspace(
            db, email=email, full_name=full_name, password_hash=hash_password(password),
            verified=False,
        )  # fmt: skip
        db.commit()
    except IntegrityError as exc:  # concurrent registration with the same email
        db.rollback()
        raise AppError("EMAIL_TAKEN", "An account with this email already exists.", 409) from exc
    send_verification_email(user, sender)
    return user


# ------------------------------------------------------------------ sessions
def default_organization_id(db: Session, user_id: uuid.UUID) -> uuid.UUID:
    row = db.execute(
        select(OrganizationMember.organization_id)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.is_personal.desc(), OrganizationMember.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise AppError("FORBIDDEN", "This account has no workspace.", 403)
    return row


def issue_session(
    db: Session,
    user: User,
    client: ClientInfo,
    *,
    family_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
) -> SessionTokens:
    settings = get_settings()
    org_id = organization_id or default_organization_id(db, user.id)
    raw, token_hash = new_refresh_token()
    db.add(
        RefreshToken(
            id=new_id(),
            user_id=user.id,
            token_hash=token_hash,
            family_id=family_id or new_id(),
            expires_at=now_utc() + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=(client.user_agent or "")[:300] or None,
            ip_address=client.ip_address,
        )
    )
    return SessionTokens(
        access_token=create_access_token(user.id, org_id),
        refresh_token=raw,
        csrf_token=new_csrf_token(),
        user=user,
        organization_id=org_id,
    )


def login(db: Session, *, email: str, password: str, client: ClientInfo) -> SessionTokens:
    user = db.scalar(select(User).where(User.email == normalise_email(email)))
    # verify_password always runs a hash comparison, even for unknown emails.
    valid = verify_password(password, user.password_hash if user else None)
    if user is None or not valid:
        raise AppError("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
    if not user.is_active:
        raise AppError("ACCOUNT_DISABLED", "This account has been disabled.", 403)
    user.last_login_at = now_utc()
    tokens = issue_session(db, user, client)
    db.commit()
    return tokens


def refresh(db: Session, *, raw_token: str | None, client: ClientInfo) -> SessionTokens:
    if not raw_token:
        raise AppError("UNAUTHENTICATED", "Please sign in.", 401)
    token = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        .with_for_update()
    )
    if token is None:
        raise AppError("UNAUTHENTICATED", "Please sign in.", 401)
    if token.revoked_at is not None:
        # A rotated token was presented again: assume theft and end every session in the
        # family, including the one the attacker may hold.
        _revoke_family(db, token.family_id)
        db.commit()
        raise AppError("SESSION_REVOKED", "Your session has ended. Please sign in again.", 401)
    if token.expires_at <= now_utc():
        raise AppError("UNAUTHENTICATED", "Your session has expired. Please sign in.", 401)
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise AppError("UNAUTHENTICATED", "Please sign in.", 401)
    token.revoked_at = now_utc()
    tokens = issue_session(db, user, client, family_id=token.family_id)
    db.commit()
    return tokens


def _revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now_utc())
    )


def logout(db: Session, *, raw_token: str | None) -> None:
    if not raw_token:
        return
    token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )
    if token is not None:
        _revoke_family(db, token.family_id)
        db.commit()


def revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now_utc())
    )


# ------------------------------------------------------- email verification
def send_verification_email(user: User, sender: EmailSender) -> None:
    token = create_action_token("verify_email", user.id, user.email, VERIFY_TTL)
    link = f"{get_settings().app_base_url}/verify-email?token={token}"
    sender.send(
        Email(
            to=user.email,
            subject="Confirm your email for EstimateAI",
            body=(
                f"Hello {user.full_name},\n\nPlease confirm your email address:\n{link}\n\n"
                "This link is valid for 48 hours. If you did not create an account, you can "
                "ignore this email."
            ),
        )
    )


def verify_email(db: Session, *, token: str) -> User:
    try:
        user_id, fingerprint = read_action_token(token, "verify_email")
    except TokenError as exc:
        raise AppError(exc.code, "This confirmation link is invalid or has expired.") from exc
    user = db.get(User, user_id)
    if user is None or not fingerprint_matches(fingerprint, user.email):
        raise AppError("LINK_INVALID", "This confirmation link is invalid or has expired.")
    if user.email_verified_at is None:
        user.email_verified_at = now_utc()
        db.commit()
    return user


# ------------------------------------------------------------ password reset
def request_password_reset(db: Session, *, email: str, sender: EmailSender) -> None:
    """Always succeeds from the caller's point of view (no account enumeration)."""
    user = db.scalar(select(User).where(User.email == normalise_email(email)))
    if user is None or not user.is_active:
        return
    token = create_action_token("reset_password", user.id, user.password_hash, RESET_TTL)
    link = f"{get_settings().app_base_url}/reset-password?token={token}"
    sender.send(
        Email(
            to=user.email,
            subject="Reset your EstimateAI password",
            body=(
                f"Hello {user.full_name},\n\nUse this link to set a new password:\n{link}\n\n"
                "The link is valid for 1 hour and can be used once. If you did not ask for "
                "this, you can ignore this email."
            ),
        )
    )


def reset_password(db: Session, *, token: str, new_password: str) -> None:
    try:
        user_id, fingerprint = read_action_token(token, "reset_password")
    except TokenError as exc:
        raise AppError(exc.code, "This reset link is invalid or has expired.") from exc
    user = db.get(User, user_id)
    if user is None or not fingerprint_matches(fingerprint, user.password_hash):
        raise AppError("LINK_INVALID", "This reset link is invalid or has already been used.")
    problem = password_problem(new_password, user.email)
    if problem:
        raise AppError("WEAK_PASSWORD", problem, details={"field": "password"})
    user.password_hash = hash_password(new_password)
    revoke_all_sessions(db, user.id)
    audit.record(
        db, actor=user, organization_id=None, entity_type="user", entity_id=user.id,
        action="password_reset",
    )  # fmt: skip
    db.commit()


# -------------------------------------------------------------- Google login
@dataclass(frozen=True)
class GoogleProfile:
    subject: str
    email: str
    email_verified: bool
    name: str


def login_with_google(db: Session, profile: GoogleProfile, client: ClientInfo) -> SessionTokens:
    if not profile.email_verified:
        raise AppError("GOOGLE_EMAIL_UNVERIFIED", "Your Google account email is not verified.", 403)
    email = normalise_email(profile.email)
    link = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == "google", OAuthAccount.provider_subject == profile.subject
        )
    )
    user: User | None
    if link is not None:
        user = db.get(User, link.user_id)
    else:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = _create_user_with_workspace(
                db, email=email, full_name=profile.name or email.split("@")[0],
                password_hash=None, verified=True,
            )  # fmt: skip
        elif user.email_verified_at is None:
            # Google has verified ownership of this address, but the existing account's
            # password was set by someone who never proved it (possible pre-registration
            # takeover). Drop that password and its sessions; the owner can set a new one.
            user.email_verified_at = now_utc()
            user.password_hash = None
            revoke_all_sessions(db, user.id)
        db.add(
            OAuthAccount(
                id=new_id(), user_id=user.id, provider="google", provider_subject=profile.subject
            )
        )
    if user is None or not user.is_active:
        raise AppError("ACCOUNT_DISABLED", "This account has been disabled.", 403)
    user.last_login_at = now_utc()
    tokens = issue_session(db, user, client)
    db.commit()
    return tokens
