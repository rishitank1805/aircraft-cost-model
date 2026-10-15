"""Download the OurAirports ``airports.csv`` file and preserve it unmodified.

Snapshots are stored as ``data/raw/airports/airports_<UTC>_<sha12>.csv`` plus a
``.meta.json`` sidecar by the generic :mod:`aircraft_cost_model.ingestion.snapshots`
downloader (temporary file, SHA-256, atomic rename, identical-content reuse).

Nothing here runs on import; call :func:`download_airports`.
"""

from __future__ import annotations

from pathlib import Path

import requests

from aircraft_cost_model.ingestion.snapshots import (
    DownloadError,
    RawSnapshot,
    download_snapshot,
    read_snapshot_metadata,
    sha256_file,
)
from aircraft_cost_model.ingestion.snapshots import latest_snapshot as _latest_snapshot

__all__ = [
    "DownloadError",
    "RawSnapshot",
    "download_airports",
    "latest_snapshot",
    "read_snapshot_metadata",
    "sha256_file",
]

PREFIX = "airports"
SUFFIX = ".csv"


def latest_snapshot(raw_dir: Path) -> RawSnapshot | None:
    """Most recent preserved airport snapshot, if any."""
    return _latest_snapshot(raw_dir, PREFIX, SUFFIX)


def download_airports(
    url: str,
    raw_dir: Path,
    timeout: tuple[float, float] = (10.0, 120.0),
    session: requests.Session | None = None,
) -> RawSnapshot:
    """Download the airport CSV into ``raw_dir`` as an immutable snapshot (see :func:`download_snapshot`)."""
    return download_snapshot(url, raw_dir, PREFIX, SUFFIX, timeout=timeout, session=session)
