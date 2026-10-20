"""Part 1 baseline: data_source, airport and aircraft_type.

Reproduces the schema created by Part 1 (``Base.metadata.create_all`` at
commit 270bd2e). Existing Part 1 databases are *stamped* at this revision
after their schema has been verified, never recreated.

Revision ID: 0001_part1_baseline
Revises:
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001_part1_baseline"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_source",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("source_url", sa.String(500)),
        sa.Column("dataset_name", sa.String(200), nullable=False),
        sa.Column("license", sa.Text()),
        sa.Column("access_type", sa.String(100)),
        sa.Column("retrieved_at", sa.DateTime()),
        sa.Column("source_version", sa.String(200)),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.PrimaryKeyConstraint("source_id"),
        sa.UniqueConstraint("dataset_name", "checksum", name="uq_data_source_dataset_checksum"),
    )
    op.create_table(
        "aircraft_type",
        sa.Column("aircraft_type_id", sa.Integer(), nullable=False),
        sa.Column("aircraft_code", sa.String(32), nullable=False),
        sa.Column("icao_type_designator", sa.String(4)),
        sa.Column("manufacturer", sa.String(100)),
        sa.Column("model", sa.String(100)),
        sa.Column("variant", sa.String(100)),
        sa.Column("engine_type", sa.String(50)),
        sa.Column("engine_model", sa.String(100)),
        sa.Column("engine_count", sa.Integer()),
        sa.Column("mtow_kg", sa.Float()),
        sa.Column("mlw_kg", sa.Float()),
        sa.Column("mzfw_kg", sa.Float()),
        sa.Column("oew_kg", sa.Float()),
        sa.Column("max_payload_kg", sa.Float()),
        sa.Column("fuel_capacity_l", sa.Float()),
        sa.Column("fuel_capacity_kg", sa.Float()),
        sa.Column("cruise_mach", sa.Float()),
        sa.Column("cruise_altitude_m", sa.Float()),
        sa.Column("cruise_speed_kt", sa.Float()),
        sa.Column("openap_supported", sa.Boolean(), nullable=False),
        sa.Column("openap_coverage", sa.String(50)),
        sa.Column("openap_related_code", sa.String(8)),
        sa.Column("field_provenance", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("aircraft_type_id"),
        sa.UniqueConstraint("aircraft_code"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
    )
    op.create_index("ix_aircraft_type_icao_type_designator", "aircraft_type", ["icao_type_designator"])
    op.create_table(
        "airport",
        sa.Column("airport_id", sa.Integer(), nullable=False),
        sa.Column("source_airport_id", sa.Integer(), nullable=False),
        sa.Column("airport_ident", sa.String(16), nullable=False),
        sa.Column("airport_name", sa.String(255)),
        sa.Column("airport_type", sa.String(32)),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("elevation_ft", sa.Float()),
        sa.Column("continent", sa.String(2)),
        sa.Column("country_code", sa.String(2)),
        sa.Column("region_code", sa.String(16)),
        sa.Column("municipality", sa.String(255)),
        sa.Column("scheduled_service", sa.Boolean()),
        sa.Column("icao_code", sa.String(4)),
        sa.Column("gps_code", sa.String(16)),
        sa.Column("iata_code", sa.String(3)),
        sa.Column("local_code", sa.String(16)),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("airport_id"),
        sa.UniqueConstraint("source_airport_id"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"]),
    )
    for column in ("country_code", "gps_code", "icao_code", "iata_code", "airport_type"):
        op.create_index(f"ix_airport_{column}", "airport", [column])


def downgrade() -> None:
    op.drop_table("airport")
    op.drop_table("aircraft_type")
    op.drop_table("data_source")
