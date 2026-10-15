"""Shared pytest fixtures. Every test uses temporary files and databases; no network access."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine

from aircraft_cost_model.database import SourceMetadata, create_db_engine, create_schema
from aircraft_cost_model.processing.airport_cleaner import read_raw_airports

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_airports() -> pd.DataFrame:
    """Small airport fixture covering valid, invalid, duplicate and edge-case rows."""
    return read_raw_airports(FIXTURES / "airports_sample.csv")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """Fresh SQLite database in a temporary directory with the schema created."""
    db_engine = create_db_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    create_schema(db_engine)
    yield db_engine
    db_engine.dispose()


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
