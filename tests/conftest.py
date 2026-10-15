"""Shared pytest fixtures. Every test uses temporary files and databases; no network access."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine

from aircraft_cost_model.database import SourceMetadata, create_db_engine, migrate_database
from aircraft_cost_model.ingestion.aircraft import CargoAircraftTarget, load_cargo_targets
from aircraft_cost_model.processing.airport_cleaner import read_raw_airports

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def raw_airports() -> pd.DataFrame:
    """Small airport fixture covering valid, invalid, duplicate and edge-case rows."""
    return read_raw_airports(FIXTURES / "airports_sample.csv")


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """URL of a fresh temporary SQLite database migrated to the latest revision."""
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    migrate_database(url)
    return url


@pytest.fixture
def engine(database_url: str) -> Engine:
    """Engine for the migrated temporary database (never the production database)."""
    db_engine = create_db_engine(database_url)
    yield db_engine
    db_engine.dispose()


@pytest.fixture(scope="session")
def cargo_targets() -> tuple[CargoAircraftTarget, ...]:
    """The version-controlled freighter target list shipped with the repository."""
    return load_cargo_targets(REPO_ROOT / "data" / "reference" / "cargo_aircraft_targets.csv")


@pytest.fixture
def airport_source() -> SourceMetadata:
    return SourceMetadata(
        source_name="OurAirports",
        source_url="https://ourairports.com/data/airports.csv",
        dataset_name="ourairports_airports_csv",
        license="Public Domain",
        access_type="HTTP download (CSV)",
        retrieved_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        source_version="fixture",
        checksum="a" * 64,
        notes="test fixture",
    )


@pytest.fixture
def openap_like_records() -> dict[str, dict]:
    """Minimal records in the shape returned by ``openap.prop.aircraft``."""
    return {
        "A332": {
            "aircraft": "Airbus A330-200",
            "mtow": 230000,
            "mlw": 182000,
            "oew": 120200,
            "mfc": 139000,
            "vmo": 330,
            "mmo": 0.86,
            "ceiling": 12500,
            "cruise": {"height": 11000, "mach": 0.82, "range": 12500},
            "engine": {"type": "turbofan", "number": 2, "default": "Trent 772", "options": ["Trent 772"]},
        },
        "XYZ1": {
            "aircraft": "Unknownmaker Thing",
            "mtow": None,
            "cruise": {},
            "engine": {},
        },
    }


# ---------------------------------------------------------------------------
# Part 2 fixtures
# ---------------------------------------------------------------------------

from aircraft_cost_model.database import load_aircraft_types, load_airports  # noqa: E402
from aircraft_cost_model.ingestion.aircraft import read_openap_aircraft  # noqa: E402
from aircraft_cost_model.performance.openap_adapter import OpenAPPerformanceProvider  # noqa: E402
from aircraft_cost_model.performance.profile import KinematicParameters  # noqa: E402
from aircraft_cost_model.processing.aircraft_cleaner import (  # noqa: E402
    build_cargo_target_rows,
    normalize_openap_aircraft,
)
from aircraft_cost_model.processing.airport_cleaner import clean_airports  # noqa: E402


def _meta(name: str, dataset: str, checksum: str, version: str | None = None) -> SourceMetadata:
    return SourceMetadata(
        source_name=name, source_url=None, dataset_name=dataset, license=None, access_type="test fixture",
        retrieved_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc), source_version=version, checksum=checksum,
    )


@pytest.fixture(scope="session")
def flight_db_template(tmp_path_factory, cargo_targets) -> Path:
    """Migrated database with fixture airports (real OurAirports rows) and the installed OpenAP aircraft.

    Built once per session; tests get a private copy via ``flight_db``.
    """
    path = tmp_path_factory.mktemp("flight_template") / "flights.db"
    url = f"sqlite:///{path.as_posix()}"
    migrate_database(url)
    engine = create_db_engine(url)
    load_airports(engine, clean_airports(read_raw_airports(FIXTURES / "airports_routes.csv")).cleaned,
                  _meta("OurAirports", "ourairports_airports_csv", "f" * 64))
    snapshot = read_openap_aircraft()
    cargo_rows, _ = build_cargo_target_rows(cargo_targets, set(snapshot.records))
    load_aircraft_types(engine, [
        (normalize_openap_aircraft(snapshot.records),
         _meta("OpenAP", "openap_aircraft_properties", snapshot.data_checksum, snapshot.openap_version)),
        (cargo_rows, _meta("Curated", "cargo_aircraft_targets", "e" * 64)),
    ])
    engine.dispose()
    return path


@pytest.fixture
def flight_db(flight_db_template: Path, tmp_path: Path) -> str:
    """URL of a private copy of the flight test database."""
    import shutil

    target = tmp_path / "flights.db"
    shutil.copy(flight_db_template, target)
    return f"sqlite:///{target.as_posix()}"


@pytest.fixture
def flight_engine(flight_db: str) -> Engine:
    db_engine = create_db_engine(flight_db)
    yield db_engine
    db_engine.dispose()


@pytest.fixture(scope="session")
def openap_provider() -> OpenAPPerformanceProvider:
    return OpenAPPerformanceProvider()


@pytest.fixture
def a320_params() -> KinematicParameters:
    """A320 WRAP default values copied from OpenAP 2.6.2 data/wrap/a320.txt (SI units)."""
    return KinematicParameters(
        source="test fixture: OpenAP 2.6.2 WRAP A320 defaults",
        liftoff_speed_ms=85.3, takeoff_acceleration_ms2=1.93, initial_climb_vs_ms=12.59,
        climb_cas_ms=151.0, climb_cas_start_altitude_m=3700.0, climb_vs_pre_cas_ms=10.25,
        climb_vs_cas_ms=8.43, climb_vs_mach_ms=5.28, cruise_mach=0.78, cruise_altitude_m=10920.0,
        descent_mach=0.77, descent_cas_ms=144.0, descent_cas_end_altitude_m=5700.0,
        descent_vs_mach_ms=-5.76, descent_vs_cas_ms=-10.03, descent_vs_post_cas_ms=-6.08,
        approach_cas_ms=72.0, approach_vs_ms=-3.55, touchdown_speed_ms=69.4, landing_deceleration_ms2=-1.22,
    )
