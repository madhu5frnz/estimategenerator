"""Store the built-in calculation templates.

Stored calculations reference (template_id, template_version), so every template the
engine can use must exist as a row. Published template versions never change; a new
formula is a new version. Later migrations that add templates call the same sync, which
only inserts missing (id, version) pairs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

from app.domain.quantity.templates import template_rows

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for row in template_rows():
        bind.execute(
            sa.text(
                "INSERT INTO calculation_templates"
                " (id, version, name, category, expression, parameters, output_unit, description)"
                " VALUES (:id, :version, :name, :category, :expression,"
                " CAST(:parameters AS jsonb), :output_unit, :description)"
                " ON CONFLICT (id, version) DO NOTHING"
            ),
            {**row, "parameters": json.dumps(row["parameters"])},
        )


def downgrade() -> None:
    op.execute("DELETE FROM calculation_templates")
