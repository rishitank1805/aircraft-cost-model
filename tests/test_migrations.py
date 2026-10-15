"""Alembic migration tests (temporary SQLite databases only)."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from aircraft_cost_model.database import (
    BASELINE_REVISION,
    SchemaVerificationError,
    _alembic_config,
    create_db_engine,
    current_revision,
    head_revision,
    migrate_database,
)
from aircraft_cost_model.models import Base

PART2_TABLES = {"route", "flight_estimate", "flight_phase", "flight_assumption"}


def _url(tmp_path: Path, name: str = "m.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _legacy_part1_database(url: str) -> None:
    """A Part 1 database as created before Alembic: baseline schema + data, no alembic_version."""
    command.upgrade(_alembic_config(url), BASELINE_REVISION)
    engine = create_db_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text(
            "INSERT INTO data_source (source_id, source_name, dataset_name, checksum, retrieved_at) "
            "VALUES (1, 'OurAirports', 'ourairports_airports_csv', 'abc', '2026-10-15 13:40:05'), "
            "(2, 'OpenAP', 'openap_aircraft_properties', 'def', '2026-10-15 13:40:02')"
        ))
        conn.execute(text(
            "INSERT INTO airport (airport_id, source_airport_id, airport_ident, latitude, longitude, iata_code, "
            "source_id, created_at, updated_at) VALUES "
            "(1, 2212, 'EDDF', 50.03, 8.56, 'FRA', 1, '2026-10-15 13:40:11', '2026-10-15 13:40:11'), "
            "(2, 3622, 'KJFK', 40.64, -73.78, 'JFK', 1, '2026-10-15 13:40:11', '2026-10-15 13:40:11')"
        ))
        conn.execute(text(
            "INSERT INTO aircraft_type (aircraft_type_id, aircraft_code, fuel_capacity_l, fuel_capacity_kg, "
            "openap_supported, field_provenance, source_id, created_at, updated_at) VALUES "
            "(1, 'A320', 24210, 19428.5, 1, '{\"fuel_capacity_kg\": \"derived: fuel_capacity_l x 0.8025 kg/L\"}', 2, "
            "'2026-10-15', '2026-10-15'), "
            "(2, 'B777F', NULL, NULL, 0, '{}', 2, '2026-10-15', '2026-10-15')"
        ))
    engine.dispose()


def test_migration_creates_all_tables(tmp_path):
    url = _url(tmp_path)
    assert migrate_database(url)["action"] == "created"
    engine = create_db_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {"airport", "aircraft_type", "data_source", "alembic_version"} | PART2_TABLES <= tables
    assert current_revision(engine) == head_revision()
    engine.dispose()


def test_migration_is_idempotent(tmp_path):
    url = _url(tmp_path)
    migrate_database(url)
    assert migrate_database(url)["action"] == "up_to_date"


def test_orm_models_match_migrated_schema(tmp_path):
    url = _url(tmp_path)
    migrate_database(url)
    engine = create_db_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_legacy_part1_database_is_verified_stamped_and_preserved(tmp_path):
    url = _url(tmp_path)
    _legacy_part1_database(url)
    result = migrate_database(url)
    assert result["action"] == "verified_stamped_upgraded"
    engine = create_db_engine(url)
    with engine.connect() as conn:
        airports = conn.execute(text(
            "SELECT airport_ident, source_id, last_seen_source_id, last_seen_at, updated_at FROM airport ORDER BY 1"
        )).all()
        aircraft = dict(conn.execute(text(
            "SELECT aircraft_code, fuel_capacity_density_kg_per_l FROM aircraft_type")).all())
        assert conn.execute(text("SELECT COUNT(*) FROM data_source")).scalar_one() == 2
    assert [a.airport_ident for a in airports] == ["EDDF", "KJFK"]
    assert all(a.last_seen_source_id == a.source_id == 1 for a in airports)
    assert all(str(a.last_seen_at).startswith("2026-10-15 13:40:05") for a in airports)
    assert all(str(a.updated_at).startswith("2026-10-15 13:40:11") for a in airports)  # untouched
    assert aircraft == {"A320": 0.8025, "B777F": None}  # density only where provenance records it
    assert current_revision(engine) == head_revision()
    engine.dispose()


def test_mismatched_unversioned_database_is_not_stamped(tmp_path):
    url = _url(tmp_path)
    _legacy_part1_database(url)
    engine = create_db_engine(url)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE airport ADD COLUMN unexpected TEXT"))
    with pytest.raises(SchemaVerificationError, match="airport"):
        migrate_database(url)
    assert current_revision(engine) is None
    assert "route" not in inspect(engine).get_table_names()
    engine.dispose()


def test_downgrade_and_upgrade_preserve_part1_data(tmp_path):
    url = _url(tmp_path)
    _legacy_part1_database(url)
    migrate_database(url)
    command.downgrade(_alembic_config(url), BASELINE_REVISION)
    engine = create_db_engine(url)
    assert not PART2_TABLES & set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM airport")).scalar_one() == 2
    engine.dispose()
    migrate_database(url)
    engine = create_db_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM airport WHERE last_seen_source_id = 1")).scalar_one() == 2
    engine.dispose()


def test_estimates_saved_before_0003_are_labelled_v1(tmp_path):
    url = _url(tmp_path)
    _legacy_part1_database(url)
    migrate_database(url)
    command.downgrade(_alembic_config(url), "0002_part2_flight_performance")
    engine = create_db_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO route (route_id, origin_airport_id, destination_airport_id, great_circle_distance_km, "
            "great_circle_distance_nm, distance_method, created_at, updated_at) "
            "VALUES (1, 1, 2, 6189, 3342, 'haversine', '2026-10-15', '2026-10-15')"
        ))
        columns = [c["name"] for c in inspect(engine).get_columns("flight_estimate")
                   if c["name"] not in ("flight_estimate_id", "trajectory_file", "warnings", "route_factor",
                                        "engine_model")]
        values = {c: 1 for c in columns}
        values.update(aircraft_type_id=1, origin_airport_id=1, destination_airport_id=2, route_id=1,
                      trip_fuel_kg=1937.6, created_at="2026-10-15")
        conn.execute(text(f"INSERT INTO flight_estimate ({', '.join(values)}) VALUES "
                          f"({', '.join(':' + c for c in values)})"), values)
    engine.dispose()
    migrate_database(url)
    engine = create_db_engine(url)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT fuel_accounting_basis, landing_roll_fuel_kg, trip_fuel_kg FROM flight_estimate")).one()
    engine.dispose()
    assert row == ("v1", None, 1937.6)  # values kept, old boundary basis labelled


def test_foreign_keys_enforced_on_new_tables(engine):
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO flight_phase (flight_estimate_id, phase_name, sequence_number, start_time_s, "
                "duration_s, start_altitude_ft, end_altitude_ft, start_mass_kg, end_mass_kg, fuel_burn_kg, "
                "fuel_flow_method) VALUES (999, 'cruise', 1, 0, 1, 0, 0, 1, 1, 0, 'x')"
            ))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO route (origin_airport_id, destination_airport_id, great_circle_distance_km, "
                "great_circle_distance_nm, distance_method, created_at, updated_at) "
                "VALUES (998, 999, 1, 1, 'x', '2026-10-15', '2026-10-15')"
            ))
