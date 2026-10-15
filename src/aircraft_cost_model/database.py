"""Database engine, schema creation and idempotent, transactional loading.

Schema creation uses ``Base.metadata.create_all`` for this initial version.
Future schema *changes* should be managed with migrations (e.g. Alembic)
rather than editing tables in place.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import Engine, create_engine, event, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from aircraft_cost_model.models import AircraftType, Airport, Base, DataSource
from aircraft_cost_model.models.base import utc_now

logger = logging.getLogger(__name__)

AIRPORT_DB_COLUMNS = (
    "source_airport_id",
    "airport_ident",
    "airport_name",
    "airport_type",
    "latitude",
    "longitude",
    "elevation_ft",
    "continent",
    "country_code",
    "region_code",
    "municipality",
    "scheduled_service",
    "icao_code",
    "gps_code",
    "iata_code",
    "local_code",
)

AIRCRAFT_DB_COLUMNS = (
    "aircraft_code",
    "icao_type_designator",
    "manufacturer",
    "model",
    "variant",
    "engine_type",
    "engine_model",
    "engine_count",
    "mtow_kg",
    "mlw_kg",
    "mzfw_kg",
    "oew_kg",
    "max_payload_kg",
    "fuel_capacity_l",
    "fuel_capacity_kg",
    "cruise_mach",
    "cruise_altitude_m",
    "cruise_speed_kt",
    "openap_supported",
    "openap_coverage",
    "openap_related_code",
    "field_provenance",
    "notes",
)


@dataclass(frozen=True)
class SourceMetadata:
    """Provenance details used to register a :class:`DataSource` row."""

    source_name: str
    source_url: str | None
    dataset_name: str
    license: str | None
    access_type: str | None
    retrieved_at: datetime | None
    source_version: str | None
    checksum: str
    notes: str | None = None


@dataclass(frozen=True)
class LoadSummary:
    """Counts produced by an upsert run."""

    source_id: int
    inserted: int
    updated: int
    unchanged: int
    in_database_not_in_source: int


def create_db_engine(database_url: str, echo: bool = False) -> Engine:
    """Create an engine; for SQLite, enforce foreign keys on every connection."""
    engine = create_engine(database_url, echo=echo, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_schema(engine: Engine) -> None:
    """Create all tables and indexes that do not yet exist."""
    Base.metadata.create_all(engine)
    logger.info("schema_ready", extra={"tables": ",".join(sorted(Base.metadata.tables))})


def _to_python(value: Any) -> Any:
    """Convert pandas/numpy scalars and missing markers to plain Python values."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def dataframe_to_records(df: pd.DataFrame, columns: Iterable[str]) -> list[dict[str, Any]]:
    """Select columns and convert rows to dicts with ``None`` for missing values."""
    subset = df[list(columns)].astype(object)
    return [{k: _to_python(v) for k, v in row.items()} for row in subset.to_dict(orient="records")]


def register_data_source(session: Session, meta: SourceMetadata) -> int:
    """Insert or update the data source identified by ``(dataset_name, checksum)``.

    Returns:
        The ``source_id`` of the registered source.
    """
    existing = session.scalar(
        select(DataSource).where(
            DataSource.dataset_name == meta.dataset_name, DataSource.checksum == meta.checksum
        )
    )
    values = {
        "source_name": meta.source_name,
        "source_url": meta.source_url,
        "license": meta.license,
        "access_type": meta.access_type,
        "retrieved_at": meta.retrieved_at.replace(tzinfo=None) if meta.retrieved_at else None,
        "source_version": meta.source_version,
        "notes": meta.notes,
    }
    if existing is None:
        existing = DataSource(dataset_name=meta.dataset_name, checksum=meta.checksum, **values)
        session.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)
    session.flush()
    logger.info(
        "data_source_registered",
        extra={"source_id": existing.source_id, "dataset": meta.dataset_name, "checksum": meta.checksum[:12]},
    )
    return existing.source_id


def _upsert(
    session: Session,
    model: type[Base],
    key_column: str,
    records: list[dict[str, Any]],
    batch_size: int = 1000,
) -> tuple[int, int]:
    """Upsert ``records`` on ``key_column``; rows whose values are unchanged are not touched.

    Returns:
        ``(inserted, updated)`` counts.
    """
    if not records:
        return 0, 0
    table = model.__table__
    key = table.c[key_column]
    existing_keys = set(session.scalars(select(key)))
    update_columns = [c for c in records[0] if c != key_column]

    stmt = sqlite_insert(table)
    stmt = stmt.on_conflict_do_update(
        index_elements=[key],
        set_={**{c: stmt.excluded[c] for c in update_columns}, "updated_at": utc_now()},
        # Only rewrite rows whose content actually changed (NULL-safe comparison).
        where=or_(*(table.c[c].is_not(stmt.excluded[c]) for c in update_columns)),
    )
    now = utc_now()
    affected = 0
    for start in range(0, len(records), batch_size):
        batch = [{**r, "created_at": now, "updated_at": now} for r in records[start : start + batch_size]]
        affected += session.execute(stmt, batch).rowcount
    inserted = sum(1 for r in records if r[key_column] not in existing_keys)
    return inserted, affected - inserted


def _count_missing_from_source(session: Session, model: type[Base], key_column: str, keys: set[Any]) -> int:
    column = model.__table__.c[key_column]
    total = session.scalar(select(func.count()).select_from(model)) or 0
    present = sum(1 for k in session.scalars(select(column)) if k in keys)
    return total - present


def load_airports(engine: Engine, cleaned: pd.DataFrame, source: SourceMetadata) -> LoadSummary:
    """Register the source and upsert airports in a single transaction.

    Airports that exist in the database but not in the current source are kept
    (not deleted) and counted, so history is not silently lost.
    """
    records = dataframe_to_records(cleaned, AIRPORT_DB_COLUMNS)
    with Session(engine) as session, session.begin():
        source_id = register_data_source(session, source)
        for record in records:
            record["source_id"] = source_id
        inserted, updated = _upsert(session, Airport, "source_airport_id", records)
        keys = {r["source_airport_id"] for r in records}
        orphaned = _count_missing_from_source(session, Airport, "source_airport_id", keys)
    summary = LoadSummary(source_id, inserted, updated, len(records) - inserted - updated, orphaned)
    logger.info("airports_loaded", extra=summary.__dict__)
    return summary


def load_aircraft_types(
    engine: Engine, groups: list[tuple[pd.DataFrame, SourceMetadata]]
) -> list[LoadSummary]:
    """Register each source and upsert its aircraft rows, all in one transaction.

    Args:
        groups: ``(rows, source)`` pairs; each group's rows reference its source.
    """
    summaries: list[LoadSummary] = []
    all_keys: set[str] = set()
    with Session(engine) as session, session.begin():
        for frame, source in groups:
            records = dataframe_to_records(frame, AIRCRAFT_DB_COLUMNS)
            source_id = register_data_source(session, source)
            for record in records:
                record["source_id"] = source_id
            inserted, updated = _upsert(session, AircraftType, "aircraft_code", records)
            all_keys |= {r["aircraft_code"] for r in records}
            summaries.append(
                LoadSummary(source_id, inserted, updated, len(records) - inserted - updated, 0)
            )
        orphaned = _count_missing_from_source(session, AircraftType, "aircraft_code", all_keys)
    if orphaned:
        logger.warning("aircraft_in_database_not_in_sources", extra={"count": orphaned})
    for summary in summaries:
        logger.info("aircraft_loaded", extra=summary.__dict__)
    return summaries
