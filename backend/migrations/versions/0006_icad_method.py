"""Telangana I&CAD estimate method: Standard Data 2026-27, analyses, leads, seigniorage.

* rate_items carry the labour component and the rate analysis (data sheet) of the book.
* A global rate source "TS I&CAD Standard Data 2026-27 (Zone III)" holds the book's 363
  priced items, marked imported_unverified: parsed from the published PDF and recomputed,
  but not a certified copy.
* item_analyses: the data sheet of one BOQ item in an estimate (editable copy).
* lead_entries: the estimate's lead statement.
* seigniorage_lines: the estimate's seigniorage statement.
* estimate_versions.method_config: zone, abstract and seigniorage settings.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op

from app.data.ts_icad import book_items

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_NS = uuid.UUID("5d0c5f7e-2b1a-4c61-9f0e-7a3c1e2d9b40")
SOURCE_ID = uuid.uuid5(_NS, "ts-icad-standard-data-2026-27-zone-iii")
FROZEN_TABLES = ("item_analyses", "lead_entries", "seigniorage_lines")


def upgrade() -> None:
    op.execute(
        "INSERT INTO units (code, display_name, dimension, is_canonical, decimal_places, aliases)"
        " VALUES ('joint', 'Joints', 'count', false, 0, '{joints}'),"
        " ('kwh', 'kWh', 'other', false, 2, '{kwhr,kilowatt hour}')"
    )
    op.add_column("rate_items", sa.Column("sl_no", sa.Integer()))
    op.add_column("rate_items", sa.Column("group_title", sa.Text()))
    op.add_column("rate_items", sa.Column("labour_component", sa.Numeric(14, 2)))
    op.add_column("rate_items", sa.Column("analysis", sa.dialects.postgresql.JSONB()))
    op.add_column(
        "rate_items",
        sa.Column("analysis_status", sa.Text(), nullable=False, server_default="none"),
    )
    op.add_column("rate_items", sa.Column("analysis_note", sa.Text()))
    op.create_check_constraint(
        "ck_rate_items_analysis_status",
        "rate_items",
        "analysis_status IN ('none','verified','rounded','unverified','user')",
    )
    op.add_column(
        "estimate_versions",
        sa.Column(
            "method_config",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.execute("""
    CREATE TABLE item_analyses (
      id               uuid PRIMARY KEY,
      organization_id  uuid NOT NULL REFERENCES organizations(id),
      version_id       uuid NOT NULL REFERENCES estimate_versions(id) ON DELETE CASCADE,
      boq_item_id      uuid NOT NULL UNIQUE REFERENCES boq_items(id) ON DELETE CASCADE,
      source_rate_item_id uuid REFERENCES rate_items(id) ON DELETE SET NULL,
      code             text NOT NULL,
      analysis         jsonb NOT NULL,
      status           text NOT NULL,
      created_at       timestamptz NOT NULL DEFAULT now(),
      updated_at       timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_item_analyses_version ON item_analyses(version_id);

    CREATE TABLE lead_entries (
      id               uuid PRIMARY KEY,
      organization_id  uuid NOT NULL REFERENCES organizations(id),
      version_id       uuid NOT NULL REFERENCES estimate_versions(id) ON DELETE CASCADE,
      line_key         uuid NOT NULL,
      sequence         integer NOT NULL,
      material         text NOT NULL,
      source           text,
      unit             text NOT NULL DEFAULT 'cum',
      material_class   text NOT NULL,
      distance_km      numeric(8,2),
      initial_km       integer NOT NULL DEFAULT 1,
      manual_amount    numeric(12,2),
      note             text,
      UNIQUE (version_id, line_key)
    );

    CREATE TABLE seigniorage_lines (
      id               uuid PRIMARY KEY,
      organization_id  uuid NOT NULL REFERENCES organizations(id),
      version_id       uuid NOT NULL REFERENCES estimate_versions(id) ON DELETE CASCADE,
      line_key         uuid NOT NULL,
      sequence         integer NOT NULL,
      label            text NOT NULL,
      material         text NOT NULL,
      boq_item_line_key uuid,
      item_quantity    numeric(18,4),
      factor           numeric(10,4) NOT NULL,
      rate             numeric(10,2) NOT NULL,
      UNIQUE (version_id, line_key)
    );
    """)
    for table in FROZEN_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_frozen BEFORE INSERT OR UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION forbid_frozen_version_change()"
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO rate_sources (id, organization_id, state, department, sor_name, year,"
            " effective_from, effective_to, verification_status, source_reference, notes)"
            " VALUES (:id, NULL, 'Telangana', 'I&CAD', 'TS Standard Data (I&CAD) Zone III',"
            " '2026-27', '2026-06-01', '2027-05-31', 'imported_unverified', :ref, :notes)"
        ),
        {
            "id": SOURCE_ID,
            "ref": "Proc.No.ENC(Admn)/Dy.ENC/EE(Tech)/DEE1/AEE1/Data-2026-27/Vol.-I Dt:29.06.2026",
            "notes": "Imported from the published Standard Data 2026-27 (Part-I). Rates exclude"
            " leads beyond the initial lead, area allowance, seigniorage and GST. Verify against"
            " the book before sanction.",
        },
    )
    rows = [
        {
            "id": uuid.uuid5(_NS, item["code"]),
            "src": SOURCE_ID,
            "code": item["code"],
            "description": item["description"],
            "unit": item["unit_code"],
            "rate": item["rate"],
            "sl": item["sl"],
            "grp": item["group"],
            "labour": item["labour_component"],
            "analysis": json.dumps(item["analysis"]) if item["analysis"] else None,
            "status": item["analysis_status"],
            "note": item["analysis_note"],
        }
        for item in book_items()
    ]
    bind.execute(
        sa.text(
            "INSERT INTO rate_items (id, rate_source_id, item_code, description, unit_code,"
            " basic_rate, gst_pct, total_rate, sl_no, group_title, labour_component, analysis,"
            " analysis_status, analysis_note) VALUES (:id, :src, :code, :description, :unit,"
            " :rate, NULL, :rate, :sl, :grp, :labour, CAST(:analysis AS jsonb), :status, :note)"
        ),
        rows,
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM rate_sources WHERE id = :id"), {"id": SOURCE_ID})
    for table in FROZEN_TABLES:
        op.execute(f"DROP TABLE {table}")
    op.drop_column("estimate_versions", "method_config")
    op.drop_constraint("ck_rate_items_analysis_status", "rate_items")
    for column in (
        "analysis_note",
        "analysis_status",
        "analysis",
        "labour_component",
        "group_title",
        "sl_no",
    ):
        op.drop_column("rate_items", column)
    op.execute("DELETE FROM units WHERE code IN ('joint', 'kwh')")
