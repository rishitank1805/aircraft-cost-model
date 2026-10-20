"""Database schema, idempotent loading and provenance tests (temporary SQLite only)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aircraft_cost_model.database import SourceMetadata, load_aircraft_types, load_airports
from aircraft_cost_model.models import AircraftType, Airport, DataSource
from aircraft_cost_model.processing.aircraft_cleaner import build_cargo_target_rows, normalize_openap_aircraft
from aircraft_cost_model.processing.airport_cleaner import clean_airports


def _count(engine, model) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def test_tables_and_indexes_created(engine):
    inspector = inspect(engine)
    assert {"airport", "aircraft_type", "data_source"} <= set(inspector.get_table_names())
    airport_indexes = {ix["name"] for ix in inspector.get_indexes("airport")}
    assert {"ix_airport_iata_code", "ix_airport_gps_code", "ix_airport_country_code",
            "ix_airport_airport_type"} <= airport_indexes
    iata_index = next(ix for ix in inspector.get_indexes("airport") if ix["name"] == "ix_airport_iata_code")
    assert not iata_index["unique"]
    fks = inspector.get_foreign_keys("airport")
    assert fks[0]["referred_table"] == "data_source"


def test_airport_ingestion_is_idempotent(engine, raw_airports, airport_source):
    cleaned = clean_airports(raw_airports).cleaned
    first = load_airports(engine, cleaned, airport_source)
    assert first.inserted == len(cleaned) == 6
    second = load_airports(engine, cleaned, airport_source)
    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 6)
    assert _count(engine, Airport) == 6
    assert _count(engine, DataSource) == 1


def test_new_snapshot_updates_only_changed_rows(engine, raw_airports, airport_source):
    cleaned = clean_airports(raw_airports).cleaned
    first = load_airports(engine, cleaned, airport_source)
    old_stamp = datetime(2020, 1, 1)  # make any spurious update visible despite 1 s timestamp resolution
    with engine.begin() as conn:
        conn.execute(Airport.__table__.update().values(updated_at=old_stamp))
    changed = cleaned.copy()
    changed.loc[changed["airport_ident"] == "EDDF", "airport_name"] = "Frankfurt Renamed"
    new_version = dataclasses.replace(
        airport_source, checksum="b" * 64, source_version="v2",
        retrieved_at=datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc),
    )
    summary = load_airports(engine, changed, new_version)
    assert (summary.inserted, summary.updated, summary.unchanged) == (0, 1, 5)
    with Session(engine) as session:
        for airport in session.scalars(select(Airport)):
            assert airport.last_seen_source_id == summary.source_id
            assert airport.last_seen_at == datetime(2026, 10, 16, 12, 0)
            if airport.iata_code == "FRA":
                assert airport.airport_name == "Frankfurt Renamed"
                assert airport.source_id == summary.source_id
                assert airport.updated_at > old_stamp
            else:  # unchanged data keeps its original source and updated_at
                assert airport.source_id == first.source_id
                assert airport.updated_at == old_stamp
    assert _count(engine, DataSource) == 2
    assert _count(engine, Airport) == 6


def test_airports_missing_upstream_are_preserved(engine, raw_airports, airport_source):
    cleaned = clean_airports(raw_airports).cleaned
    first = load_airports(engine, cleaned, airport_source)
    smaller = cleaned[cleaned["airport_ident"] != "XH02"]
    newer = dataclasses.replace(airport_source, checksum="c" * 64, source_version="v3")
    summary = load_airports(engine, smaller, newer)
    assert summary.in_database_not_in_source == 1
    assert _count(engine, Airport) == 6
    with Session(engine) as session:
        heliport = session.scalar(select(Airport).where(Airport.airport_ident == "XH02"))
        assert heliport.last_seen_source_id == first.source_id  # stale, not deleted


def test_missing_values_stored_as_null(engine, raw_airports, airport_source):
    load_airports(engine, clean_airports(raw_airports).cleaned, airport_source)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT iata_code, elevation_ft, scheduled_service FROM airport WHERE airport_ident = :i"),
            {"i": "XS07"},
        ).one()
    assert row.iata_code is None and row.elevation_ft is None and row.scheduled_service is None


def test_data_source_metadata_persisted(engine, raw_airports, airport_source):
    summary = load_airports(engine, clean_airports(raw_airports).cleaned, airport_source)
    with Session(engine) as session:
        source = session.get(DataSource, summary.source_id)
    assert source.source_name == "OurAirports"
    assert source.source_url == airport_source.source_url
    assert source.checksum == "a" * 64
    assert source.license == "Public Domain"
    assert source.retrieved_at.isoformat() == "2026-10-15T12:00:00"
    assert source.notes == "test fixture"


def test_failed_load_rolls_back_entire_transaction(engine, raw_airports, airport_source):
    cleaned = clean_airports(raw_airports).cleaned.copy()
    cleaned.loc[0, "airport_ident"] = None  # violates NOT NULL
    with pytest.raises(IntegrityError):
        load_airports(engine, cleaned, airport_source)
    assert _count(engine, Airport) == 0
    assert _count(engine, DataSource) == 0


def test_aircraft_ingestion_idempotent_with_sources(engine, openap_like_records, cargo_targets):
    openap_rows = normalize_openap_aircraft(openap_like_records)
    cargo_rows, _ = build_cargo_target_rows(cargo_targets, {"A332"})
    base = dict(source_url=None, license=None, access_type=None, retrieved_at=None, source_version=None)
    groups = [
        (openap_rows, SourceMetadata(source_name="OpenAP", dataset_name="openap", checksum="c" * 64, **base)),
        (cargo_rows, SourceMetadata(source_name="Curated", dataset_name="cargo", checksum="d" * 64, **base)),
    ]
    first = load_aircraft_types(engine, groups)
    assert [s.inserted for s in first] == [2, 5]
    second = load_aircraft_types(engine, groups)
    assert [s.inserted for s in second] == [0, 0]
    assert [s.unchanged for s in second] == [2, 5]
    assert _count(engine, AircraftType) == 7
    with Session(engine) as session:
        freighter = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == "B777F"))
        assert freighter.mtow_kg is None
        assert freighter.openap_supported is False
        a332 = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == "A332"))
        assert a332.mzfw_kg is None and a332.mtow_kg == 230000
        assert session.get(DataSource, a332.source_id).source_name == "OpenAP"
