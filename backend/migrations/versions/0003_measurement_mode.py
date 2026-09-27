"""Measurement lines record how their quantity is calculated.

``dimensions``: No × L × B × D/H, using whichever dimensions the item's unit needs.
``formula``: a calculation template or custom formula, optionally referencing named
parameters of the version.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE estimate_items ADD COLUMN mode text NOT NULL DEFAULT 'dimensions'"
        " CHECK (mode IN ('dimensions', 'formula'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE estimate_items DROP COLUMN mode")
