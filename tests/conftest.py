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


# ---------------------------------------------------------------------------
# Part 3 fixtures (offline; real public-domain/ECB excerpts + synthetic tariffs)
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402
from decimal import Decimal  # noqa: E402

COST_FIXTURES = FIXTURES / "costs"


def synthetic_fra_parameters() -> dict:
    """SYNTHETIC parameters with the FRA rule's structure (not Fraport's values)."""
    return {
        "applicability_min_mtom_kg_exclusive": "66000",
        "passenger_rate_per_departing_passenger": "2.00",
        "freight_mail_rate_per_started_100kg": "0.10",
        "emission_rate_per_kg_nox_eq": "4.00",
        "noise_24h_by_category": {str(i): str(i * 10) for i in range(1, 17)},
        "noise_night1_surcharge_by_category": {str(i): str(i * 5) for i in range(1, 17)},
        "noise_night2_surcharge_by_category": {str(i): str(i * 20) for i in range(1, 17)},
        "night_time_1": [["22:00", "22:59"], ["05:00", "05:59"]],
        "night_time_2": ["23:00", "04:59"],
        "nri_reduction_pct": {
            "gt_34t_lt_136t": {f"R{i}": str(max(0, i - 4) * 2) for i in range(1, 11)},
            "ge_136t": {f"R{i}": str(max(0, i - 5) * 3) for i in range(1, 11)},
        },
    }


def write_synthetic_tariff(directory: Path, airport_ident: str = "EDDF", valid_from: str = "2025-01-01",
                           valid_to: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{airport_ident}_synthetic_{valid_from}.json"
    path.write_text(_json.dumps({
        "airport_ident": airport_ident, "tariff_type": "landing_takeoff", "valid_from": valid_from,
        "valid_to": valid_to, "currency": "EUR", "calculation_method": "fra_movement_charges_2026",
        "verification_status": "synthetic_test_fixture",
        "source": {"publisher": "TEST", "title": "synthetic test tariff", "url": "about:blank",
                   "retrieved": "2026-10-15T00:00:00", "terms": "test fixture"},
        "parameters": synthetic_fra_parameters(),
    }), encoding="utf-8")
    return path


FRA_CONTEXT = {
    "flight_type": "commercial", "noise_certification": "chapter_4_or_higher", "noise_category_takeoff": "4",
    "noise_category_landing": "4", "movement_local_time": "10:30", "nri_category": "R6",
    "departing_passengers": "150", "freight_mail_kg": "1250", "emission_value_kg_nox_eq": "10.1234",
}


def _snapshot(path: Path):
    from aircraft_cost_model.ingestion.snapshots import RawSnapshot, sha256_file

    return RawSnapshot(path=path, source_url=f"file://{path.name}", final_url=f"file://{path.name}",
                       retrieved_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc), sha256=sha256_file(path),
                       size_bytes=path.stat().st_size, http_status=200)


@pytest.fixture
def cost_db(flight_db: str, openap_provider) -> str:
    """Flight DB + a saved v2 A320 FRA->CDG estimate + fixture fuel prices, ECB rates and EUROCONTROL rates."""
    from aircraft_cost_model.ingestion import exchange_rates as er
    from aircraft_cost_model.ingestion import fuel_prices as fp
    from aircraft_cost_model.ingestion.airport_tariffs import load_navigation_rates
    from aircraft_cost_model.performance.persistence import save_flight_estimate
    from aircraft_cost_model.performance.planner import FlightRequest, estimate_flight
    from sqlalchemy.orm import Session

    engine = create_db_engine(flight_db)
    with Session(engine) as session:
        result = estimate_flight(session, FlightRequest("A320", "FRA", "CDG", 10000), openap_provider)
    assert save_flight_estimate(engine, result) == 1
    snap = _snapshot(COST_FIXTURES / "eia_jet_2025-01_excerpt.xls")
    parsed = fp.parse_snapshot(snap)
    fp.load_fuel_prices(engine, parsed, fp.validate_fuel_prices(parsed), snap)
    snap = _snapshot(COST_FIXTURES / "ecb_exr_2025-01_excerpt.csv")
    rates = er.parse_ecb_csv(snap.path)
    er.load_exchange_rates(engine, rates, er.validate_rates(rates), snap)
    load_navigation_rates(engine, COST_FIXTURES / "navigation")  # synthetic values
    engine.dispose()
    return flight_db
