"""Build the public explorer database used for hosted deployments (e.g. Vercel).

The hosted explorer must not redistribute EUROCONTROL, DFS or Fraport values (owner decision 2).
The public copy is the live database with the rows of the restricted rate tables removed. Their
``data_source`` metadata rows (names, licences, checksums) stay so that provenance remains
traceable. No saved estimate prices a restricted rate (those components are ``unavailable_*``);
the build refuses to continue if any saved cost component still has an amount for them.
"""

from __future__ import annotations

import gzip
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Tables holding values transcribed from EUROCONTROL / DFS / Fraport documents.
RESTRICTED_TABLES: tuple[str, ...] = ("navigation_rate", "navigation_zone_aerodrome", "airport_tariff")
# Saved cost components priced from those tables. They must carry no amount in the public copy.
RESTRICTED_COMPONENTS: tuple[str, ...] = ("navigation", "terminal_navigation", "landing")


class PublicDatabaseError(RuntimeError):
    """The public database cannot be built without exposing restricted data."""


@dataclass(frozen=True)
class PublicDatabaseResult:
    database_path: Path
    compressed_path: Path | None
    removed_rows: dict[str, int]
    size_bytes: int


def build_public_database(source: Path, target: Path, *, compress: bool = True) -> PublicDatabaseResult:
    """Copy ``source`` to ``target`` without restricted rows, then optionally gzip it.

    The source database is only read. ``target`` (and ``target.gz``) are replaced.
    """
    if not source.is_file():
        raise FileNotFoundError(f"database not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)

    with sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as src, \
            sqlite3.connect(partial) as dst:
        src.backup(dst)
    try:
        removed = _strip_restricted(partial)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)

    compressed = None
    if compress:
        compressed = target.with_suffix(target.suffix + ".gz")
        with target.open("rb") as raw, gzip.open(compressed, "wb", compresslevel=9) as packed:
            shutil.copyfileobj(raw, packed)
    result = PublicDatabaseResult(target, compressed, removed, target.stat().st_size)
    logger.info("public_database_built", extra={"target": str(target), "removed_rows": removed,
                                                "size_bytes": result.size_bytes})
    return result


def _strip_restricted(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "cost_component" in tables:
            marks = ",".join("?" for _ in RESTRICTED_COMPONENTS)
            priced = connection.execute(
                f"SELECT COUNT(*) FROM cost_component WHERE component_name IN ({marks}) AND amount IS NOT NULL",
                RESTRICTED_COMPONENTS).fetchone()[0]
            if priced:
                raise PublicDatabaseError(f"{priced} saved cost component(s) priced from restricted rates; "
                                          "the public database would expose them")
        removed: dict[str, int] = {}
        with connection:
            for table in RESTRICTED_TABLES:
                if table in tables:
                    removed[table] = connection.execute(f"DELETE FROM {table}").rowcount
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise PublicDatabaseError(f"foreign key violations after removing restricted rows: {violations[:5]}")
        # Rollback journal (not WAL), so the file opens read-only on a read-only filesystem.
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("VACUUM")
    finally:
        connection.close()
    return removed


def decompress_public_database(compressed: Path, target: Path) -> Path:
    """Restore the database from its gzip copy (used by the hosted build step)."""
    partial = target.with_suffix(target.suffix + ".part")
    with gzip.open(compressed, "rb") as packed, partial.open("wb") as raw:
        shutil.copyfileobj(packed, raw)
    partial.replace(target)
    return target
