"""Part 4: cost scenarios, assumptions, full-cost estimates and components.

Additive only; no existing table is altered. Monetary columns use the exact
decimal-string type (``DecimalText``, VARCHAR(64)).

Revision ID: 0006_part4_full_costs
Revises: 0005_terminal_navigation
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006_part4_full_costs"
down_revision: str | None = "0005_terminal_navigation"
branch_labels = None
depends_on = None

DEC = sa.String(64)


def upgrade() -> None:
    op.create_table(
        "cost_scenario",
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("scenario_version", sa.String(40), nullable=False),
        sa.Column("ownership_mode", sa.String(30), nullable=False),
        sa.Column("flight_type", sa.String(20), nullable=False),
        sa.Column("reporting_currency", sa.String(3), nullable=False),
        sa.Column("pricing_date", sa.Date()),
        sa.Column("source_quality_summary", sa.String(200), nullable=False),
        sa.Column("source_path", sa.String(500)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("scenario_id"),
        sa.UniqueConstraint("content_hash", name="uq_cost_scenario_content_hash"),
    )
    op.create_table(
        "cost_assumption",
        sa.Column("assumption_id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(60), nullable=False),
        sa.Column("parameter_name", sa.String(200), nullable=False),
        sa.Column("value_decimal", DEC, nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(3)),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("reference_period", sa.String(100)),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.PrimaryKeyConstraint("assumption_id"),
        sa.ForeignKeyConstraint(["scenario_id"], ["cost_scenario.scenario_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("scenario_id", "parameter_name", name="uq_cost_assumption_parameter"),
    )
    op.create_index("ix_cost_assumption_scenario_id", "cost_assumption", ["scenario_id"])
    op.create_table(
        "full_cost_estimate",
        sa.Column("full_cost_estimate_id", sa.Integer(), nullable=False),
        sa.Column("flight_estimate_id", sa.Integer(), nullable=False),
        sa.Column("variable_cost_estimate_id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("pricing_date", sa.Date(), nullable=False),
        sa.Column("reporting_currency", sa.String(3), nullable=False),
        sa.Column("ownership_mode", sa.String(30), nullable=False),
        *[sa.Column(name, DEC) for name in (
            "direct_variable_subtotal", "direct_fixed_subtotal", "indirect_subtotal", "noncash_subtotal",
            "financing_subtotal", "cash_operating_subtotal", "total_operating_subtotal", "total_cost_subtotal",
            "complete_coc", "complete_toc", "complete_total_costs")],
        sa.Column("cost_coverage_status", sa.String(30), nullable=False),
        sa.Column("operational_validity_status", sa.String(50), nullable=False),
        sa.Column("source_quality_summary", sa.String(200), nullable=False),
        sa.Column("calculation_version", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("full_cost_estimate_id"),
        sa.ForeignKeyConstraint(["flight_estimate_id"], ["flight_estimate.flight_estimate_id"]),
        sa.ForeignKeyConstraint(["variable_cost_estimate_id"], ["variable_cost_estimate.variable_cost_estimate_id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["cost_scenario.scenario_id"]),
    )
    for column in ("flight_estimate_id", "variable_cost_estimate_id", "scenario_id", "input_hash"):
        op.create_index(f"ix_full_cost_estimate_{column}", "full_cost_estimate", [column])
    op.create_table(
        "full_cost_component",
        sa.Column("full_cost_component_id", sa.Integer(), nullable=False),
        sa.Column("full_cost_estimate_id", sa.Integer(), nullable=False),
        sa.Column("component_name", sa.String(40), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("amount", DEC),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_quality", sa.String(40), nullable=False),
        sa.Column("origin", sa.String(40), nullable=False),
        sa.Column("part3_cost_component_id", sa.Integer()),
        sa.Column("source_reference", sa.Text()),
        sa.Column("calculation_method", sa.Text()),
        sa.Column("breakdown_json", sa.Text(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("full_cost_component_id"),
        sa.ForeignKeyConstraint(["full_cost_estimate_id"], ["full_cost_estimate.full_cost_estimate_id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["part3_cost_component_id"], ["cost_component.cost_component_id"]),
        sa.UniqueConstraint("full_cost_estimate_id", "component_name", name="uq_full_cost_component_name"),
    )
    op.create_index("ix_full_cost_component_full_cost_estimate_id", "full_cost_component", ["full_cost_estimate_id"])


def downgrade() -> None:
    for table in ("full_cost_component", "full_cost_estimate", "cost_assumption", "cost_scenario"):
        op.drop_table(table)
