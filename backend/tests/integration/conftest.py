"""Fixtures for tests that need PostgreSQL (set TEST_DATABASE_URL to a disposable DB)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.email import Email

DB_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND = Path(__file__).resolve().parents[2]
requires_db = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

CLEANUP = [
    # Frozen estimate versions are protected by triggers; tests bypass them to reset.
    "SET session_replication_role = replica",
    "DELETE FROM usage_counters",
    "DELETE FROM calculations",
    "DELETE FROM estimate_items",
    "DELETE FROM boq_items",
    "DELETE FROM estimate_charges",
    "DELETE FROM estimate_sections",
    "DELETE FROM quantity_inputs",
    "DELETE FROM estimate_versions",
    "DELETE FROM estimates",
    "DELETE FROM ai_generations",
    "DELETE FROM project_members",
    "DELETE FROM projects",
    "DELETE FROM refresh_tokens",
    "DELETE FROM oauth_accounts",
    "DELETE FROM organization_members",
    "DELETE FROM subscriptions",
    "DELETE FROM audit_logs",
    "DELETE FROM work_categories WHERE organization_id IS NOT NULL",
    "DELETE FROM rate_items WHERE rate_source_id IN"
    " (SELECT id FROM rate_sources WHERE organization_id IS NOT NULL)",
    "DELETE FROM rate_sources WHERE organization_id IS NOT NULL",
    "DELETE FROM settings WHERE scope <> 'platform'",
    "DELETE FROM users",
    "DELETE FROM organizations",
    "SET session_replication_role = DEFAULT",
]


def alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", DB_URL or "")
    return cfg


@dataclass
class MemorySender:
    sent: list[Email] = field(default_factory=list)

    def send(self, email: Email) -> None:
        self.sent.append(email)

    def last_link(self, path: str) -> str:
        for email in reversed(self.sent):
            for word in email.body.split():
                if f"/{path}?token=" in word:
                    return word.split("token=", 1)[1]
        raise AssertionError(f"no {path} link sent")


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    if not DB_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    cfg = alembic_config()
    engine = create_engine(DB_URL)
    with engine.begin() as conn:  # leave no rows that would block a downgrade
        if conn.execute(text("SELECT to_regclass('public.users')")).scalar():
            for statement in CLEANUP:
                conn.execute(text(statement))
    engine.dispose()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield DB_URL


def _clean(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        for statement in CLEANUP:
            conn.execute(text(statement))
    engine.dispose()


@pytest.fixture
def db_url(migrated_db: str) -> Iterator[str]:
    _clean(migrated_db)
    yield migrated_db
    _clean(migrated_db)


@pytest.fixture
def mailbox() -> MemorySender:
    return MemorySender()


@pytest.fixture
def app_env(db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from app.config import get_settings
    from app.db.session import reset_engine_cache

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", db_url)
    for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    reset_engine_cache()
    yield
    get_settings.cache_clear()
    reset_engine_cache()


@pytest.fixture
def make_client(app_env: None, mailbox: MemorySender) -> Iterator[Any]:
    from app.main import create_app
    from app.services.email import get_email_sender

    clients: list[TestClient] = []

    def factory() -> TestClient:
        app = create_app()
        app.dependency_overrides[get_email_sender] = lambda: mailbox
        client = TestClient(app, raise_server_exceptions=False)
        clients.append(client)
        return client

    yield factory
    for c in clients:
        c.close()


@pytest.fixture
def client(make_client: Any) -> TestClient:
    return make_client()  # type: ignore[no-any-return]


@pytest.fixture
def db_session(db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with Session(engine) as session:
        yield session
    engine.dispose()


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("eai_csrf") or ""}


def register(
    client: TestClient,
    email: str = "mahesh@example.com",
    password: str = "correct horse 42",
    name: str = "Mahesh",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, "full_name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]  # type: ignore[no-any-return]


def add_org_member(db: Session, org_id: str, email: str, role: str = "member") -> uuid.UUID:
    """Create a user who belongs to an existing organisation (team accounts arrive in P3)."""
    from app.core.ids import new_id
    from app.core.security import hash_password

    user_id = new_id()
    db.execute(
        text(
            "INSERT INTO users (id, email, full_name, password_hash, email_verified_at)"
            " VALUES (:id, :email, :name, :hash, now())"
        ),
        {
            "id": user_id,
            "email": email,
            "name": email.split("@")[0],
            "hash": hash_password("member pass 123"),
        },
    )
    db.execute(
        text(
            "INSERT INTO organization_members (organization_id, user_id, role) VALUES (:o, :u, :r)"
        ),
        {"o": org_id, "u": user_id, "r": role},
    )
    db.commit()
    return user_id


def login(client: TestClient, email: str, password: str) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client
