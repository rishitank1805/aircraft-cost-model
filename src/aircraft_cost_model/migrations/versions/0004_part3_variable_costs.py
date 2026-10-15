"""Part 3: variable cost reference data and cost estimates.

Additive only. Monetary values and rates use a TEXT column holding the exact
decimal string (``models.types.DecimalText``) because SQLite has no decimal
type and SQLAlchemy ``Numeric`` would store binary floats.

Revision ID: 0004_part3_variable_costs
Revises: 0003_touchdown_fuel_boundaries
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_part3_variable_costs"
down_revision: str | None = "0003_touchdown_fuel_boundaries"
branch_labels = None
depends_on = None

DEC = sa.String(64)


def _timestamps() -> list[sa.Column]:
    return [sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "fuel_price",
        sa.Column("fuel_price_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("series_identifier", sa.String(64), nullable=False),
        sa.Column("market_location", sa.String(100), nullable=False),
        sa.Column("product", sa.String(100), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("observation_period", sa.String(20), nullable=False),
        sa.Column("price", DEC, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("price_unit", sa.String(30), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("fuel_price_id"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
        sa.UniqueConstraint("series_identifier", "observation_period", "observation_date", name="uq_fuel_price_obs"),
    )
    op.create_index("ix_fuel_price_series_date", "fuel_price", ["series_identifier", "observation_date"])

    op.create_table(
        "exchange_rate",
        sa.Column("exchange_rate_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("rate", DEC, nullable=False),
        sa.Column("series_key", sa.String(64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("exchange_rate_id"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
        sa.UniqueConstraint("base_currency", "quote_currency", "observation_date", name="uq_exchange_rate_obs"),
    )
    op.create_index("ix_exchange_rate_pair_date", "exchange_rate", ["base_currency", "quote_currency", "observation_date"])

    op.create_table(
        "navigation_rate",
        sa.Column("navigation_rate_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("charging_zone", sa.String(40), nullable=False),
        sa.Column("charging_zone_name", sa.String(100), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("unit_rate", DEC, nullable=False),
        sa.Column("national_unit_rate", DEC),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(40), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("navigation_rate_id"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
        sa.UniqueConstraint("charging_zone", "valid_from", name="uq_navigation_rate_zone_from"),
    )
    op.create_index("ix_navigation_rate_charging_zone", "navigation_rate", ["charging_zone"])

    op.create_table(
        "airport_tariff",
        sa.Column("airport_tariff_id", sa.Integer(), nullable=False),
        sa.Column("airport_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("tariff_type", sa.String(40), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("calculation_method", sa.String(80), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(40), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("airport_tariff_id"),
        sa.ForeignKeyConstraint(["airport_id"], ["airport.airport_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
        sa.UniqueConstraint("airport_id", "tariff_type", "valid_from", name="uq_airport_tariff_version"),
    )
    op.create_index("ix_airport_tariff_airport_id", "airport_tariff", ["airport_id"])

    op.create_table(
        "variable_cost_estimate",
        sa.Column("variable_cost_estimate_id", sa.Integer(), nullable=False),
        sa.Column("flight_estimate_id", sa.Integer(), nullable=False),
        sa.Column("pricing_date", sa.Date(), nullable=False),
        sa.Column("reporting_currency", sa.String(3), nullable=False),
        sa.Column("calculated_subtotal", DEC),
        sa.Column("complete_variable_cost", DEC),
        sa.Column("coverage_status", sa.String(30), nullable=False),
        sa.Column("components_calculated", sa.Integer(), nullable=False),
        sa.Column("components_applicable", sa.Integer(), nullable=False),
        sa.Column("calculation_version", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("variable_cost_estimate_id"),
        sa.ForeignKeyConstraint(["flight_estimate_id"], ["flight_estimate.flight_estimate_id"]),
    )
    op.create_index("ix_variable_cost_estimate_flight_estimate_id", "variable_cost_estimate", ["flight_estimate_id"])
    op.create_index("ix_variable_cost_estimate_input_hash", "variable_cost_estimate", ["input_hash"])

    op.create_table(
        "cost_component",
        sa.Column("cost_component_id", sa.Integer(), nullable=False),
        sa.Column("variable_cost_estimate_id", sa.Integer(), nullable=False),
        sa.Column("component_name", sa.String(30), nullable=False),
        sa.Column("amount", DEC),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("partial_scope", sa.Boolean(), nullable=False),
        sa.Column("source_id", sa.Integer()),
        sa.Column("source_reference", sa.Text()),
        sa.Column("pricing_observation_date", sa.Date()),
        sa.Column("calculation_method", sa.Text()),
        sa.Column("breakdown_json", sa.Text(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("cost_component_id"),
        sa.ForeignKeyConstraint(
            ["variable_cost_estimate_id"], ["variable_cost_estimate.variable_cost_estimate_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
        sa.UniqueConstraint("variable_cost_estimate_id", "component_name", name="uq_cost_component_name"),
    )
    op.create_index("ix_cost_component_variable_cost_estimate_id", "cost_component", ["variable_cost_estimate_id"])


def downgrade() -> None:
    for table in ("cost_component", "variable_cost_estimate", "airport_tariff", "navigation_rate",
                  "exchange_rate", "fuel_price"):
        op.drop_table(table)
