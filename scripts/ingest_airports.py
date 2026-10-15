"""Download, clean, validate and load OurAirports airport data into SQLite.

Usage (from the repository root, after ``pip install -e .``)::

    python scripts/ingest_airports.py            # download a fresh snapshot
    python scripts/ingest_airports.py --offline  # reuse the latest raw snapshot
"""

from __future__ import annotations

import argparse
import logging
import sys

from aircraft_cost_model.config import (
    OURAIRPORTS_DATA_DICTIONARY_URL,
    OURAIRPORTS_DATA_PAGE_URL,
    get_settings,
)
from aircraft_cost_model.database import SourceMetadata, create_db_engine, load_airports, migrate_database
from aircraft_cost_model.ingestion.airports import DownloadError, download_airports, latest_snapshot
from aircraft_cost_model.logging_config import configure_logging
from aircraft_cost_model.processing.airport_cleaner import clean_airports, read_raw_airports, save_cleaned_airports
from aircraft_cost_model.validation.airport_validator import validate_airports

logger = logging.getLogger("ingest_airports")

LICENSE_TEXT = (
    "Public Domain - 'All data is released to the Public Domain, and comes with no "
    "guarantee of accuracy or fitness for use.' (https://ourairports.com/data/, checked 2026-10-15)"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="Use the latest raw snapshot instead of downloading.")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)

    if args.offline:
        snapshot = latest_snapshot(settings.raw_airports_dir)
        if snapshot is None:
            logger.error("no_raw_snapshot", extra={"dir": str(settings.raw_airports_dir)})
            return 1
    else:
        try:
            snapshot = download_airports(settings.airports_url, settings.raw_airports_dir, settings.http_timeout)
        except DownloadError as exc:
            logger.error("airport_download_failed", extra={"error": str(exc)})
            print(f"Download failed: {exc}\nRe-run with --offline to use the latest preserved snapshot.")
            return 1

    raw = read_raw_airports(snapshot.path)
    result = clean_airports(raw)
    report = validate_airports(
        result,
        source_name="OurAirports",
        source_url=snapshot.source_url,
        retrieved_at=snapshot.retrieved_at.isoformat(),
        source_version=f"sha256:{snapshot.sha256[:12]}",
    )
    paths = save_cleaned_airports(result, settings.processed_airports_dir)
    report_path = report.write_json(settings.processed_airports_dir / "airports_validation_report.json")

    if not report.passed:
        logger.error("airport_validation_failed", extra={"errors": "; ".join(report.errors)})
        print(f"Validation failed; nothing loaded. See {report_path}")
        return 1

    migrate_database(settings.database_url)
    engine = create_db_engine(settings.database_url)
    summary = load_airports(
        engine,
        result.cleaned,
        SourceMetadata(
            source_name="OurAirports",
            source_url=snapshot.source_url,
            dataset_name="ourairports_airports_csv",
            license=LICENSE_TEXT,
            access_type="HTTP download (CSV)",
            retrieved_at=snapshot.retrieved_at,
            source_version=snapshot.last_modified or f"sha256:{snapshot.sha256[:12]}",
            checksum=snapshot.sha256,
            notes=(
                f"Raw file: {snapshot.path.name}; final URL after redirects: {snapshot.final_url}; "
                f"{snapshot.size_bytes} bytes. Updated nightly per {OURAIRPORTS_DATA_PAGE_URL}. "
                f"Data dictionary: {OURAIRPORTS_DATA_DICTIONARY_URL}"
            ),
        ),
    )

    by_type = report.statistics["airports_by_type"]
    print("\n=== Airport ingestion summary ===")
    print(f"Raw snapshot         : {snapshot.path.name} ({snapshot.size_bytes:,} bytes)")
    print(f"Retrieved at (UTC)   : {snapshot.retrieved_at.isoformat()}"
          f"{'  [reused existing snapshot]' if snapshot.reused_existing else ''}")
    print(f"SHA-256              : {snapshot.sha256}")
    print(f"Source records       : {report.total_source_records:,}")
    print(f"Cleaned records      : {report.cleaned_records:,}")
    print(f"Rejected records     : {report.rejected_records:,}")
    print(f"Duplicate source ids : {report.duplicate_records:,}")
    print(f"By type              : {', '.join(f'{k}={v:,}' for k, v in by_type.items())}")
    print(f"DB inserted/updated/unchanged : {summary.inserted:,} / {summary.updated:,} / {summary.unchanged:,}")
    print(f"In DB but not in this source  : {summary.in_database_not_in_source:,}")
    print(f"data_source id       : {summary.source_id}")
    print(f"Processed files      : {paths['cleaned']}, {paths['rejected']}")
    print(f"Validation report    : {report_path}")
    print(f"Warnings             : {len(report.warnings)}")
    for warning in report.warnings:
        print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
