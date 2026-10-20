"""Part 2: flight performance tables and Part 1 provenance improvements.

Additive only: new columns are added with ``ALTER TABLE ... ADD COLUMN`` and
back-filled from existing data; no Part 1 table is recreated or emptied.

- airport.last_seen_source_id / last_seen_at (back-filled from source_id)
- aircraft_type.fuel_capacity_density_kg_per_l (back-filled with 0.8025 only
  where the Part 1 provenance label records that density)
- new tables: route, flight_estimate, flight_phase, flight_assumption

Revision ID: 0002_part2_flight_performance
Revises: 0001_part1_baseline
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_part2_flight_performance"
down_revision: str | None = "0001_part1_baseline"
branch_labels = None
depends_on = None

# Density used by Part 1 (aircraft_cost_model.config.JET_FUEL_DENSITY_KG_PER_L at 270bd2e).
PART1_DENSITY_KG_PER_L = 0.8025


def upgrade() -> None:
    # SQLite supports ADD COLUMN with an inline REFERENCES clause when the default is NULL.
    op.execute(
        "ALTER TABLE airport ADD COLUMN last_seen_source_id INTEGER "
        "REFERENCES data_source (source_id)"
    )
    op.add_column("airport", sa.Column("last_seen_at", sa.DateTime()))
    op.create_index("ix_airport_last_seen_source_id", "airport", ["last_seen_source_id"])
    op.execute(
        "UPDATE airport SET last_seen_source_id = source_id, "
        "last_seen_at = (SELECT retrieved_at FROM data_source ds WHERE ds.source_id = airport.source_id)"
    )

    op.add_column("aircraft_type", sa.Column("fuel_capacity_density_kg_per_l", sa.Float()))
    op.get_bind().execute(
        sa.text(
            "UPDATE aircraft_type SET fuel_capacity_density_kg_per_l = :density "
            "WHERE fuel_capacity_kg IS NOT NULL AND field_provenance LIKE :label"
        ),
        {"density": PART1_DENSITY_KG_PER_L, "label": f"%{PART1_DENSITY_KG_PER_L} kg/L%"},
    )

    op.create_table(
        "route",
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("origin_airport_id", sa.Integer(), nullable=False),
        sa.Column("destination_airport_id", sa.Integer(), nullable=False),
        sa.Column("great_circle_distance_km", sa.Float(), nullable=False),
        sa.Column("great_circle_distance_nm", sa.Float(), nullable=False),
        sa.Column("distance_method", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("route_id"),
        sa.ForeignKeyConstraint(["origin_airport_id"], ["airport.airport_id"]),
        sa.ForeignKeyConstraint(["destination_airport_id"], ["airport.airport_id"]),
        sa.UniqueConstraint("origin_airport_id", "destination_airport_id", name="uq_route_origin_destination"),
    )
    op.create_index("ix_route_origin_airport_id", "route", ["origin_airport_id"])
    op.create_index("ix_route_destination_airport_id", "route", ["destination_airport_id"])

    op.create_table(
        "flight_estimate",
        sa.Column("flight_estimate_id", sa.Integer(), nullable=False),
        sa.Column("aircraft_type_id", sa.Integer(), nullable=False),
        sa.Column("origin_airport_id", sa.Integer(), nullable=False),
        sa.Column("destination_airport_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("payload_kg", sa.Float(), nullable=False),
        sa.Column("great_circle_distance_nm", sa.Float(), nullable=False),
        sa.Column("estimated_route_distance_nm", sa.Float(), nullable=False),
        sa.Column("route_distance_method", sa.String(50), nullable=False),
        sa.Column("route_factor", sa.Float()),
        sa.Column("cruise_altitude_ft", sa.Float(), nullable=False),
        sa.Column("taxi_out_min", sa.Float(), nullable=False),
        sa.Column("taxi_in_min", sa.Float(), nullable=False),
        sa.Column("airborne_time_min", sa.Float(), nullable=False),
        sa.Column("trip_time_min", sa.Float(), nullable=False),
        sa.Column("block_time_min", sa.Float(), nullable=False),
        sa.Column("zero_fuel_weight_kg", sa.Float(), nullable=False),
        sa.Column("ramp_weight_kg", sa.Float(), nullable=False),
        sa.Column("takeoff_weight_kg", sa.Float(), nullable=False),
        sa.Column("landing_weight_kg", sa.Float(), nullable=False),
        sa.Column("trip_fuel_kg", sa.Float(), nullable=False),
        sa.Column("taxi_out_fuel_kg", sa.Float(), nullable=False),
        sa.Column("taxi_in_fuel_kg", sa.Float(), nullable=False),
        sa.Column("taxi_fuel_kg", sa.Float(), nullable=False),
        sa.Column("block_fuel_kg", sa.Float(), nullable=False),
        sa.Column("reserve_fuel_kg", sa.Float(), nullable=False),
        sa.Column("planned_fuel_load_kg", sa.Float(), nullable=False),
        sa.Column("fuel_per_nm_kg", sa.Float(), nullable=False),
        sa.Column("fuel_per_block_hour_kg", sa.Float(), nullable=False),
        sa.Column("fuel_density_kg_per_l", sa.Float(), nullable=False),
        sa.Column("time_step_s", sa.Float(), nullable=False),
        sa.Column("planning_iterations", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("model_version", sa.String(200), nullable=False),
        sa.Column("performance_model_code", sa.String(8), nullable=False),
        sa.Column("engine_model", sa.String(100)),
        sa.Column("calculation_status", sa.String(50), nullable=False),
        sa.Column("limit_checks", sa.Text(), nullable=False),
        sa.Column("warnings", sa.Text()),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("trajectory_file", sa.String(500)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("flight_estimate_id"),
        sa.ForeignKeyConstraint(["aircraft_type_id"], ["aircraft_type.aircraft_type_id"]),
        sa.ForeignKeyConstraint(["origin_airport_id"], ["airport.airport_id"]),
        sa.ForeignKeyConstraint(["destination_airport_id"], ["airport.airport_id"]),
        sa.ForeignKeyConstraint(["route_id"], ["route.route_id"]),
    )
    op.create_index("ix_flight_estimate_aircraft_type_id", "flight_estimate", ["aircraft_type_id"])
    op.create_index("ix_flight_estimate_route_id", "flight_estimate", ["route_id"])
    op.create_index(
        "ix_flight_estimate_origin_destination", "flight_estimate", ["origin_airport_id", "destination_airport_id"]
    )
    op.create_index("ix_flight_estimate_input_hash", "flight_estimate", ["input_hash"])

    op.create_table(
        "flight_phase",
        sa.Column("flight_phase_id", sa.Integer(), nullable=False),
        sa.Column("flight_estimate_id", sa.Integer(), nullable=False),
        sa.Column("phase_name", sa.String(30), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("start_time_s", sa.Float(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("distance_nm", sa.Float()),
        sa.Column("start_altitude_ft", sa.Float(), nullable=False),
        sa.Column("end_altitude_ft", sa.Float(), nullable=False),
        sa.Column("start_mass_kg", sa.Float(), nullable=False),
        sa.Column("end_mass_kg", sa.Float(), nullable=False),
        sa.Column("fuel_burn_kg", sa.Float(), nullable=False),
        sa.Column("fuel_flow_method", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("flight_phase_id"),
        sa.ForeignKeyConstraint(
            ["flight_estimate_id"], ["flight_estimate.flight_estimate_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("flight_estimate_id", "sequence_number", name="uq_flight_phase_sequence"),
    )
    op.create_index("ix_flight_phase_flight_estimate_id", "flight_phase", ["flight_estimate_id"])

    op.create_table(
        "flight_assumption",
        sa.Column("assumption_id", sa.Integer(), nullable=False),
        sa.Column("flight_estimate_id", sa.Integer(), nullable=False),
        sa.Column("assumption_name", sa.String(100), nullable=False),
        sa.Column("assumption_value", sa.Text(), nullable=False),
        sa.Column("assumption_unit", sa.String(30)),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_reference", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.PrimaryKeyConstraint("assumption_id"),
        sa.ForeignKeyConstraint(
            ["flight_estimate_id"], ["flight_estimate.flight_estimate_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("flight_estimate_id", "assumption_name", name="uq_flight_assumption_name"),
    )
    op.create_index("ix_flight_assumption_flight_estimate_id", "flight_assumption", ["flight_estimate_id"])


def downgrade() -> None:
    op.drop_table("flight_assumption")
    op.drop_table("flight_phase")
    op.drop_table("flight_estimate")
    op.drop_table("route")
    op.drop_index("ix_airport_last_seen_source_id", table_name="airport")
    with op.batch_alter_table("airport") as batch:
        batch.drop_column("last_seen_at")
        batch.drop_column("last_seen_source_id")
    with op.batch_alter_table("aircraft_type") as batch:
        batch.drop_column("fuel_capacity_density_kg_per_l")
