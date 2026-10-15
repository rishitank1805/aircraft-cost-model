"""Terminal navigation charges: rate type columns and terminal charging-zone aerodromes.

Additive only. Existing ``navigation_rate`` rows (EUROCONTROL en-route rates)
are back-filled by the server defaults ``charge_type='en_route'`` and
``service_unit_formula='sqrt_mtow_over_50'``.

Revision ID: 0005_terminal_navigation
Revises: 0004_part3_variable_costs
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005_terminal_navigation"
down_revision: str | None = "0004_part3_variable_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("navigation_rate", sa.Column("charge_type", sa.String(20), nullable=False,
                                               server_default=sa.text("'en_route'")))
    op.add_column("navigation_rate", sa.Column("service_unit_formula", sa.String(40), nullable=False,
                                               server_default=sa.text("'sqrt_mtow_over_50'")))
    op.add_column("navigation_rate", sa.Column("charged_movement", sa.String(20)))
    op.create_table(
        "navigation_zone_aerodrome",
        sa.Column("navigation_zone_aerodrome_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("charging_zone", sa.String(40), nullable=False),
        sa.Column("aerodrome_icao", sa.String(4), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("navigation_zone_aerodrome_id"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
        sa.UniqueConstraint("charging_zone", "aerodrome_icao", "valid_from", name="uq_navigation_zone_aerodrome"),
    )
    op.create_index("ix_navigation_zone_aerodrome_aerodrome_icao", "navigation_zone_aerodrome", ["aerodrome_icao"])


def downgrade() -> None:
    op.drop_table("navigation_zone_aerodrome")
    with op.batch_alter_table("navigation_rate") as batch:
        batch.drop_column("charged_movement")
        batch.drop_column("service_unit_formula")
        batch.drop_column("charge_type")
