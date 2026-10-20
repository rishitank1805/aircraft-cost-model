"""Database engine, schema creation and idempotent, transactional loading.

The schema is managed with Alembic migrations (``aircraft_cost_model/migrations``).
:func:`migrate_database` brings any database to the latest revision; a
pre-Alembic Part 1 database is verified against the baseline revision and
stamped, never recreated. :func:`create_schema` (``create_all``) remains only
for throwaway databases.
"""

from __future__ import annotations

import logging
import math
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, func, inspect, or_, select, update
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
    "fuel_capacity_density_kg_per_l",
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
    """Create all tables directly from ORM metadata (throwaway databases only; use migrations otherwise)."""
    Base.metadata.create_all(engine)
    logger.info("schema_ready", extra={"tables": ",".join(sorted(Base.metadata.tables))})


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE_REVISION = "0001_part1_baseline"
PART1_TABLES = ("data_source", "airport", "aircraft_type")


class SchemaVerificationError(RuntimeError):
    """An unversioned database does not match the Part 1 baseline and cannot be stamped safely."""


def _alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logging"] = False
    return config


def head_revision() -> str:
    """Latest migration revision id."""
    return ScriptDirectory.from_config(_alembic_config("sqlite://")).get_current_head()


def current_revision(engine: Engine) -> str | None:
    """Revision recorded in the database's ``alembic_version`` table (None if unversioned)."""
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def describe_schema(engine: Engine, tables: Iterable[str]) -> dict[str, Any]:
    """Comparable description of tables: columns (type, nullability), indexes, unique and foreign keys."""
    inspector = inspect(engine)
    description: dict[str, Any] = {}
    for table in tables:
        if not inspector.has_table(table):
            description[table] = None
            continue
        description[table] = {
            "columns": {
                c["name"]: (str(c["type"]).upper(), bool(c["nullable"])) for c in inspector.get_columns(table)
            },
            "indexes": sorted((i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in inspector.get_indexes(table)),
            "unique": sorted(tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)),
            "foreign_keys": sorted(
                (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
                for f in inspector.get_foreign_keys(table)
            ),
        }
    return description


def expected_baseline_schema() -> dict[str, Any]:
    """Schema produced by the baseline migration, built in a temporary SQLite file."""
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{(Path(tmp) / 'baseline.db').as_posix()}"
        command.upgrade(_alembic_config(url), BASELINE_REVISION)
        engine = create_engine(url)
        try:
            return describe_schema(engine, PART1_TABLES)
        finally:
            engine.dispose()


def migrate_database(database_url: str) -> dict[str, str | None]:
    """Upgrade a database to the latest migration without recreating existing tables.

    - Empty database: all migrations are applied.
    - Versioned database: pending migrations are applied.
    - Unversioned database with Part 1 tables: the schema is compared with the
      baseline revision; only an exact match is stamped at the baseline, then
      upgraded. A mismatch raises :class:`SchemaVerificationError`.

    Returns:
        ``{"from": <revision or None>, "to": <head>, "action": ...}``
    """
    engine = create_db_engine(database_url)
    try:
        before = current_revision(engine)
        existing = set(inspect(engine).get_table_names())
        action = "upgraded"
        if before is None and existing & set(PART1_TABLES):
            actual = describe_schema(engine, PART1_TABLES)
            expected = expected_baseline_schema()
            if actual != expected:
                differences = [t for t in PART1_TABLES if actual.get(t) != expected.get(t)]
                raise SchemaVerificationError(
                    f"Unversioned database does not match the Part 1 baseline (tables differ: {differences}); "
                    "refusing to stamp."
                )
            command.stamp(_alembic_config(database_url), BASELINE_REVISION)
            logger.info("database_stamped", extra={"revision": BASELINE_REVISION})
            before = BASELINE_REVISION
            action = "verified_stamped_upgraded"
        elif before is None:
            action = "created"
        elif before == head_revision():
            action = "up_to_date"
    finally:
        engine.dispose()
    command.upgrade(_alembic_config(database_url), "head")
    head = head_revision()
    logger.info("database_migrated", extra={"from_revision": before, "to_revision": head, "action": action})
    return {"from": before, "to": head, "action": action}


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


def upsert_rows(
    session: Session,
    model: type[Base],
    key_columns: str | tuple[str, ...],
    records: list[dict[str, Any]],
    batch_size: int = 1000,
    compare_exclude: Iterable[str] = ("source_id",),
) -> tuple[int, int]:
    """Upsert ``records`` on a natural key; rows whose data values are unchanged are not touched.

    ``key_columns`` is one column name or a tuple for composite keys (there
    must be a matching unique constraint). Columns in ``compare_exclude`` are
    written on insert and on a real change but do not by themselves trigger an
    update, so a new source snapshot with identical data leaves ``updated_at``
    (and ``source_id``) unchanged.

    Returns:
        ``(inserted, updated)`` counts.
    """
    if not records:
        return 0, 0
    keys = (key_columns,) if isinstance(key_columns, str) else tuple(key_columns)
    table = model.__table__
    key_cols = [table.c[k] for k in keys]
    existing_keys = {tuple(row) for row in session.execute(select(*key_cols))}
    update_columns = [c for c in records[0] if c not in keys]
    compared = [c for c in update_columns if c not in set(compare_exclude)]

    stmt = sqlite_insert(table)
    stmt = stmt.on_conflict_do_update(
        index_elements=key_cols,
        set_={**{c: stmt.excluded[c] for c in update_columns}, "updated_at": utc_now()},
        # Only rewrite rows whose data actually changed (NULL-safe comparison).
        where=or_(*(table.c[c].is_not(stmt.excluded[c]) for c in compared)),
    )
    now = utc_now()
    affected = 0
    for start in range(0, len(records), batch_size):
        batch = [{**r, "created_at": now, "updated_at": now} for r in records[start : start + batch_size]]
        affected += session.execute(stmt, batch).rowcount
    key_type = {k: table.c[k].type for k in keys}
    inserted = sum(1 for r in records if tuple(_key_value(r[k], key_type[k]) for k in keys) not in existing_keys)
    return inserted, affected - inserted


def _key_value(value: Any, column_type: Any) -> Any:
    """Normalise a record's key value to what the database returns (e.g. date strings -> date)."""
    from datetime import date as _date

    if isinstance(value, str) and column_type.python_type is _date:
        return _date.fromisoformat(value)
    return value


def _upsert(
    session: Session,
    model: type[Base],
    key_column: str,
    records: list[dict[str, Any]],
    batch_size: int = 1000,
    compare_exclude: Iterable[str] = ("source_id",),
) -> tuple[int, int]:
    """Single-column-key upsert (see :func:`upsert_rows`)."""
    return upsert_rows(session, model, key_column, records, batch_size, compare_exclude)


def _count_missing_from_source(session: Session, model: type[Base], key_column: str, keys: set[Any]) -> int:
    column = model.__table__.c[key_column]
    total = session.scalar(select(func.count()).select_from(model)) or 0
    present = sum(1 for k in session.scalars(select(column)) if k in keys)
    return total - present


def _mark_airports_seen(
    session: Session, keys: list[int], source_id: int, seen_at: datetime | None, batch_size: int = 1000
) -> None:
    """Record that ``keys`` are present in snapshot ``source_id`` (does not touch ``updated_at``)."""
    for start in range(0, len(keys), batch_size):
        batch = keys[start : start + batch_size]
        session.execute(
            update(Airport)
            .where(Airport.source_airport_id.in_(batch))
            # Setting updated_at to itself suppresses the column's onupdate default:
            # being seen in a snapshot is not a data change.
            .values(last_seen_source_id=source_id, last_seen_at=seen_at, updated_at=Airport.updated_at)
            .execution_options(synchronize_session=False)
        )


def load_airports(engine: Engine, cleaned: pd.DataFrame, source: SourceMetadata) -> LoadSummary:
    """Register the source and upsert airports in a single transaction.

    ``source_id``/``updated_at`` change only for airports whose data changed;
    ``last_seen_source_id``/``last_seen_at`` are set for every airport in the
    snapshot. Airports missing from the snapshot are kept (not deleted) and
    counted, so history is not silently lost.
    """
    records = dataframe_to_records(cleaned, AIRPORT_DB_COLUMNS)
    seen_at = source.retrieved_at.replace(tzinfo=None) if source.retrieved_at else None
    with Session(engine) as session, session.begin():
        source_id = register_data_source(session, source)
        for record in records:
            record["source_id"] = source_id
        inserted, updated = _upsert(session, Airport, "source_airport_id", records)
        keys = [r["source_airport_id"] for r in records]
        _mark_airports_seen(session, keys, source_id, seen_at)
        orphaned = _count_missing_from_source(session, Airport, "source_airport_id", set(keys))
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
