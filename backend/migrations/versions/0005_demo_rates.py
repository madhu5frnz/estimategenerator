"""Demo rate source for trying the app.

These rates are illustrative only. The source is marked ``verification_status = 'demo'``
and named "Demo Rates — Not Official SOR", so the app labels every use of them and
validation flags them. Real rates come from sources a workspace adds or imports.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_NS = uuid.UUID("0b7b3e4c-4c1a-4f55-9a7e-2d1b9b8f3a10")
SOURCE_ID = uuid.uuid5(_NS, "demo-source-2026-27")

ITEMS = [
    ("DEMO-EW-01", "Earthwork excavation in all soils, lead 50 m, lift 1.5 m", "cum", "245.00"),
    ("DEMO-GSB-01", "Providing and laying granular sub-base (GSB), compacted", "cum", "1850.00"),
    ("DEMO-WMM-01", "Providing and laying wet mix macadam (WMM), compacted", "cum", "2250.00"),
    ("DEMO-PCC-15", "Providing and laying plain cement concrete M15", "cum", "5950.00"),
    ("CC-001", "Providing and laying cement concrete", "cum", "7500.00"),
    ("DEMO-BW-01", "Brick masonry in cement mortar 1:6", "cum", "6850.00"),
    ("DEMO-PL-12", "12 mm thick cement plaster in CM 1:4", "sqm", "325.00"),
    ("DEMO-KB-01", "Precast concrete kerb, laid in line and level", "rmt", "380.00"),
    ("DEMO-RS-01", "Reinforcement steel Fe500, cut, bent and placed", "kg", "88.00"),
    ("DEMO-PT-01", "Painting two coats of acrylic emulsion over primer", "sqm", "125.00"),
]  # fmt: skip


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO rate_sources (id, organization_id, state, department, sor_name, year,"
            " effective_from, effective_to, verification_status, source_reference, notes)"
            " VALUES (:id, NULL, 'Telangana', 'Demo', 'Demo Rates — Not Official SOR', '2026-27',"
            " '2026-04-01', '2027-03-31', 'demo', NULL,"
            " 'Illustrative rates for trying EstimateAI. Not an official Schedule of Rates.')"
        ),
        {"id": SOURCE_ID},
    )
    for code, description, unit, rate in ITEMS:
        bind.execute(
            sa.text(
                "INSERT INTO rate_items (id, rate_source_id, item_code, description, unit_code,"
                " basic_rate, gst_pct, total_rate) VALUES (:id, :src, :code, :description, :unit,"
                " :rate, NULL, :rate)"
            ),
            {"id": uuid.uuid5(_NS, code), "src": SOURCE_ID, "code": code,
             "description": description, "unit": unit, "rate": rate},
        )  # fmt: skip


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM rate_sources WHERE id = :id"), {"id": SOURCE_ID})
