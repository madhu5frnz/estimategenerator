"""Runs only when TEST_DATABASE_URL points at a disposable PostgreSQL 16 database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.domain.quantity import BUILTIN_TEMPLATES
from app.domain.units import default_registry
from tests.conftest import REPO_ROOT

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set"),
]
BACKEND = Path(__file__).resolve().parents[2]


def _config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", DB_URL or "")
    return cfg


def test_migration_sql_matches_design_document() -> None:
    migration = (BACKEND / "migrations" / "sql" / "0001_initial_schema.sql").read_text()
    design = (REPO_ROOT / "docs" / "design" / "03-database-schema.sql").read_text()
    assert migration == design


def test_upgrade_downgrade_upgrade() -> None:
    cfg = _config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(DB_URL or "")
    with engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name <> 'alembic_version'"
            )
        ).scalar_one()
        units = conn.execute(text("SELECT count(*) FROM units")).scalar_one()
        plans = conn.execute(text("SELECT count(*) FROM plans")).scalar_one()
        book = conn.execute(
            text(
                "SELECT count(*) AS n, count(*) FILTER (WHERE analysis_status = 'verified') AS ok"
                " FROM rate_items i JOIN rate_sources s ON s.id = i.rate_source_id"
                " WHERE s.sor_name = 'TS Standard Data (I&CAD) Zone III'"
            )
        ).one()
        unit_codes = set(conn.execute(text("SELECT code FROM units")).scalars())
        templates = {
            (row.id, row.version)
            for row in conn.execute(text("SELECT id, version FROM calculation_templates"))
        }
    assert tables == 40  # 37 reviewed + item_analyses, lead_entries, seigniorage_lines
    assert units == 22
    assert unit_codes == {u.code for u in default_registry().units}
    assert book.n == 363 and book.ok >= 266
    assert plans == 4
    assert templates == {(t.id, t.version) for t in BUILTIN_TEMPLATES}


def test_frozen_version_is_immutable() -> None:
    command.upgrade(_config(), "head")
    engine = create_engine(DB_URL or "")
    ids = {
        "user": "00000000-0000-0000-0000-000000000001",
        "org": "00000000-0000-0000-0000-000000000002",
        "project": "00000000-0000-0000-0000-000000000003",
        "estimate": "00000000-0000-0000-0000-000000000004",
        "version": "00000000-0000-0000-0000-000000000005",
    }
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, full_name) VALUES (:user, 'a@b.test', 'A')"), ids
        )
        conn.execute(text("INSERT INTO organizations (id, name) VALUES (:org, 'Org')"), ids)
        conn.execute(
            text(
                "INSERT INTO projects (id, organization_id, name, project_type, created_by) "
                "VALUES (:project, :org, 'P', 'road', :user)"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO estimates (id, organization_id, project_id, estimate_number, title,"
                " created_by) VALUES (:estimate, :org, :project, 'E-1', 'T', :user)"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO estimate_versions (id, organization_id, estimate_id, version_no,"
                " created_by) VALUES (:version, :org, :estimate, 1, :user)"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO estimate_sections (id, organization_id, version_id, line_key, title,"
                " sequence) VALUES (gen_random_uuid(), :org, :version, gen_random_uuid(), 'CC', 1)"
            ),
            ids,
        )
        conn.execute(text("UPDATE estimate_versions SET status = 'frozen'"))
    try:
        with pytest.raises(DBAPIError, match="VERSION_FROZEN"), engine.begin() as conn:
            conn.execute(text("UPDATE estimate_sections SET title = 'changed'"))
    finally:
        # Frozen rows cannot be deleted row by row, so rebuild the schema; other test
        # modules share this database and expect it at head.
        engine.dispose()
        command.downgrade(_config(), "base")
        command.upgrade(_config(), "head")
