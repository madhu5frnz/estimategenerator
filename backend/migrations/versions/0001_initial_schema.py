"""Initial schema from the reviewed design (docs/design/03-database-schema.sql).

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0001_initial_schema.sql"


def upgrade() -> None:
    # exec_driver_sql: the file is plain SQL; SQLAlchemy must not parse ':name' as binds
    # (JSON defaults such as '{"applicable":false}' contain colons).
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    sql = SQL_FILE.read_text(encoding="utf-8")
    tables = re.findall(r"^CREATE TABLE (\w+)", sql, re.M)
    types = re.findall(r"^CREATE TYPE (\w+)", sql, re.M)
    functions = re.findall(r"^CREATE FUNCTION (\w+)", sql, re.M)
    bind = op.get_bind()
    for table in reversed(tables):
        bind.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    for function in functions:
        bind.exec_driver_sql(f'DROP FUNCTION IF EXISTS "{function}"() CASCADE')
    for type_name in types:
        bind.exec_driver_sql(f'DROP TYPE IF EXISTS "{type_name}"')
