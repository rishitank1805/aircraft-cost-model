"""Public explorer database: restricted rate rows are removed, the source stays untouched."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aircraft_cost_model.api.public_db import (
    PublicDatabaseError,
    build_public_database,
    decompress_public_database,
)


def _make_source(path: Path, *, priced_navigation: bool = False) -> Path:
    with sqlite3.connect(path) as db:
        db.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE data_source (source_id INTEGER PRIMARY KEY, source_name TEXT);
            CREATE TABLE navigation_rate (id INTEGER PRIMARY KEY, unit_rate TEXT);
            CREATE TABLE navigation_zone_aerodrome (id INTEGER PRIMARY KEY, icao TEXT);
            CREATE TABLE airport_tariff (id INTEGER PRIMARY KEY, amount TEXT);
            CREATE TABLE cost_component (id INTEGER PRIMARY KEY, component_name TEXT, amount TEXT);
            INSERT INTO data_source VALUES (1, 'Synthetic navigation source');
            INSERT INTO navigation_rate VALUES (1, '11.11'), (2, '22.22');
            INSERT INTO navigation_zone_aerodrome VALUES (1, 'XXXX');
            INSERT INTO airport_tariff VALUES (1, '33.33');
            INSERT INTO cost_component VALUES (1, 'fuel', '100.00');
        """)
        db.execute("INSERT INTO cost_component VALUES (2, 'navigation', ?)",
                   ("44.44" if priced_navigation else None,))
    return path


def _count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as db:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_restricted_rows_removed_and_source_unchanged(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "live.db")
    result = build_public_database(source, tmp_path / "out" / "public.db")

    assert result.removed_rows == {"navigation_rate": 2, "navigation_zone_aerodrome": 1, "airport_tariff": 1}
    for table in ("navigation_rate", "navigation_zone_aerodrome", "airport_tariff"):
        assert _count(result.database_path, table) == 0
    assert _count(result.database_path, "data_source") == 1  # provenance metadata kept
    assert _count(result.database_path, "cost_component") == 2
    assert _count(source, "navigation_rate") == 2  # live database only read
    with sqlite3.connect(result.database_path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert b"11.11" not in result.database_path.read_bytes()


def test_compressed_copy_round_trips(tmp_path: Path) -> None:
    result = build_public_database(_make_source(tmp_path / "live.db"), tmp_path / "public.db")
    restored = decompress_public_database(result.compressed_path, tmp_path / "restored.db")
    assert restored.read_bytes() == result.database_path.read_bytes()


def test_refuses_when_a_saved_component_was_priced_from_restricted_rates(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "live.db", priced_navigation=True)
    with pytest.raises(PublicDatabaseError, match="restricted rates"):
        build_public_database(source, tmp_path / "public.db")
    assert not (tmp_path / "public.db").exists()
    assert not (tmp_path / "public.db.part").exists()


def test_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_public_database(tmp_path / "missing.db", tmp_path / "public.db")
