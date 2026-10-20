"""Touchdown-based mass/fuel boundaries for flight estimates.

Adds landing-roll time and fuel and a ``fuel_accounting_basis`` label. Rows
saved before this revision keep their values and are labelled ``v1`` (trip
fuel and landing mass measured to the end of the landing roll); new rows are
``v2`` (take-off mass at brake release, landing mass at touchdown, trip fuel
between them, landing roll separate). Additive only.

Revision ID: 0003_touchdown_fuel_boundaries
Revises: 0002_part2_flight_performance
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_touchdown_fuel_boundaries"
down_revision: str | None = "0002_part2_flight_performance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("flight_estimate", sa.Column("landing_roll_time_min", sa.Float()))
    op.add_column("flight_estimate", sa.Column("landing_roll_fuel_kg", sa.Float()))
    op.add_column(
        "flight_estimate",
        sa.Column("fuel_accounting_basis", sa.String(10), nullable=False, server_default="v1"),
    )


def downgrade() -> None:
    with op.batch_alter_table("flight_estimate") as batch:
        batch.drop_column("fuel_accounting_basis")
        batch.drop_column("landing_roll_fuel_kg")
        batch.drop_column("landing_roll_time_min")
