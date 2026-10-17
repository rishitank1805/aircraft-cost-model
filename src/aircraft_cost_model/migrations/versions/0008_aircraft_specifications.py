"""Part 6: aircraft specification values with provenance.

Additive only; no existing table is altered.

Revision ID: 0008_aircraft_specifications
Revises: 0007_part5_analytics
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008_aircraft_specifications"
down_revision: str | None = "0007_part5_analytics"
branch_labels = None
depends_on = None

DEC = sa.String(64)


def upgrade() -> None:
    op.create_table(
        "aircraft_specification",
        sa.Column("specification_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("aircraft_type_id", sa.Integer(), nullable=False),
        sa.Column("spec_key", sa.String(60), nullable=False),
        sa.Column("section", sa.String(30), nullable=False),
        sa.Column("value_decimal", DEC, nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(30), nullable=True),
        sa.Column("original_value", sa.String(100), nullable=True),
        sa.Column("original_unit", sa.String(30), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(40), nullable=False),
        sa.Column("variant", sa.String(200), nullable=True),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["aircraft_type_id"], ["aircraft_type.aircraft_type_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
        sa.PrimaryKeyConstraint("specification_id"),
        sa.UniqueConstraint("aircraft_type_id", "spec_key", "source_id", name="uq_aircraft_specification"),
    )
    op.create_index(op.f("ix_aircraft_specification_aircraft_type_id"), "aircraft_specification", ["aircraft_type_id"])
    op.create_index(op.f("ix_aircraft_specification_source_id"), "aircraft_specification", ["source_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_aircraft_specification_source_id"), table_name="aircraft_specification")
    op.drop_index(op.f("ix_aircraft_specification_aircraft_type_id"), table_name="aircraft_specification")
    op.drop_table("aircraft_specification")
