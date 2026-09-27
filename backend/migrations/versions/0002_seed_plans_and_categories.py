"""Seed subscription plans and default work categories.

Prices are the brief's initial suggestions. Limits for Pro and Business follow the capped
proposal in docs/design/10-third-party-costs.md instead of "unlimited" AI use. All of
this is data: administrators change it without a deploy. ``null`` means no limit.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PLANS = [
    # code, name, price, limits, features, sort
    (
        "free", "Free", 0,
        {"ai_generations_per_period": 5, "projects": 3, "doc_pages_per_period": 0,
         "max_upload_mb": 10, "seats": 1},
        {"export_pdf": True, "export_xlsx": False, "export_docx": False,
         "rate_database": False, "team": False},
        0,
    ),
    (
        "starter", "Starter", 499,
        {"ai_generations_per_period": 50, "projects": 25, "doc_pages_per_period": 0,
         "max_upload_mb": 25, "seats": 1},
        {"export_pdf": True, "export_xlsx": True, "export_docx": False,
         "rate_database": False, "team": False},
        1,
    ),
    (
        "pro", "Pro", 999,
        {"ai_generations_per_period": 200, "projects": None, "doc_pages_per_period": 50,
         "max_upload_mb": 50, "seats": 1},
        {"export_pdf": True, "export_xlsx": True, "export_docx": True,
         "rate_database": True, "team": False},
        2,
    ),
    (
        "business", "Business", 2999,
        {"ai_generations_per_period": 750, "projects": None, "doc_pages_per_period": 200,
         "max_upload_mb": 100, "seats": 5},
        {"export_pdf": True, "export_xlsx": True, "export_docx": True,
         "rate_database": True, "team": True},
        3,
    ),
]  # fmt: skip

WORK_CATEGORIES = {
    "road": ["CC road", "BT road", "WBM road", "Road widening", "Road repairs"],
    "building": ["Residential building", "School building", "Office building",
                 "Compound wall", "Repairs and renovation"],
    "drain": ["Side drain", "Storm water drain", "Covered drain"],
    "culvert": ["Pipe culvert", "Box culvert", "Slab culvert"],
    "bridge": ["Minor bridge", "Major bridge", "Causeway"],
    "irrigation": ["Canal lining", "Distributary", "Field channels", "Check dam"],
    "canal": ["Main canal", "Branch canal", "Minor canal"],
    "tank": ["Tank restoration", "Bund strengthening", "Sluice repairs"],
    "lift_irrigation": ["Pump house", "Rising main", "Delivery cistern"],
    "water_supply": ["Pipeline", "Overhead tank", "Sump"],
    "sewerage": ["Sewer line", "Manholes", "Septic tank"],
    "electrical": ["Internal wiring", "Street lighting"],
    "other": ["General"],
}  # fmt: skip

# Fixed namespace so category ids are stable across environments.
_NS = uuid.UUID("6f1d8a3e-2b8f-4c1e-9d4a-1c2b3a4d5e6f")


def upgrade() -> None:
    bind = op.get_bind()
    for code, name, price, limits, features, sort in PLANS:
        bind.execute(
            sa.text(
                "INSERT INTO plans (code, name, price_inr_monthly, limits, features, sort_order)"
                " VALUES (:code, :name, :price, CAST(:limits AS jsonb),"
                " CAST(:features AS jsonb), :sort)"
            ),
            {
                "code": code,
                "name": name,
                "price": price,
                "limits": json.dumps(limits),
                "features": json.dumps(features),
                "sort": sort,
            },
        )
    for project_type, names in WORK_CATEGORIES.items():
        for name in names:
            bind.execute(
                sa.text(
                    "INSERT INTO work_categories (id, organization_id, project_type, name)"
                    " VALUES (:id, NULL, :type, :name)"
                ),
                {
                    "id": uuid.uuid5(_NS, f"{project_type}/{name}"),
                    "type": project_type,
                    "name": name,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM work_categories WHERE organization_id IS NULL"))
    bind.execute(sa.text("DELETE FROM plans WHERE code IN ('free','starter','pro','business')"))
