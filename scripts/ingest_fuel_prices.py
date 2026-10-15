"""Ingest the EIA U.S. Gulf Coast jet fuel spot price series (EER_EPJK_PF4_RGC_DPG, USD per US gallon, daily).

Usage::

    python scripts/ingest_fuel_prices.py              # public XLS download (no API key)
    python scripts/ingest_fuel_prices.py --offline    # reprocess the latest preserved snapshot
    python scripts/ingest_fuel_prices.py --api --start 2024-01-01   # EIA API v2 (needs ACM_EIA_API_KEY)
"""

from __future__ import annotations

import argparse
import sys

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.ingestion import fuel_prices as fp
from aircraft_cost_model.ingestion.snapshots import DownloadError
from aircraft_cost_model.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Use the latest preserved raw snapshot.")
    mode.add_argument("--api", action="store_true", help="Use EIA API v2 (requires ACM_EIA_API_KEY).")
    parser.add_argument("--start", default="1990-01-01", help="API start date (ISO 8601).")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        if args.offline:
            snapshot = fp.latest_eia_snapshot(settings.raw_fuel_prices_dir)
            if snapshot is None:
                print(f"No preserved EIA snapshot in {settings.raw_fuel_prices_dir}")
                return 1
        elif args.api:
            if not settings.eia_api_key:
                print("ACM_EIA_API_KEY is not set (free key: https://www.eia.gov/opendata/register.php). "
                      "Run without --api to use the public XLS download.")
                return 1
            snapshot = fp.download_eia_api(settings.raw_fuel_prices_dir, settings.eia_api_key, args.start,
                                           settings.http_timeout)
        else:
            snapshot = fp.download_eia_xls(settings.raw_fuel_prices_dir, settings.http_timeout)
        parsed = fp.parse_snapshot(snapshot)
        validation = fp.validate_fuel_prices(parsed)
        migrate_database(settings.database_url)
        inserted, updated, unchanged = fp.load_fuel_prices(create_db_engine(settings.database_url), parsed,
                                                           validation, snapshot)
    except (DownloadError, SourceSchemaError) as exc:
        print(f"Fuel price ingestion failed: {exc}")
        return 1
    dates = [r["observation_date"] for r in validation.valid]
    print("\n=== Fuel price ingestion summary ===")
    print(f"Series            : {parsed.series_identifier} - {parsed.description}")
    print(f"Raw snapshot      : {snapshot.path.name} ({snapshot.size_bytes:,} bytes, sha256 {snapshot.sha256[:12]})"
          f"{'  [reused]' if snapshot.reused_existing else ''}")
    print(f"Retrieved (UTC)   : {snapshot.retrieved_at.isoformat()}")
    print(f"Observations      : {len(validation.valid):,} valid, {len(validation.rejected)} rejected, "
          f"{parsed.blank_observations} blank")
    print(f"Coverage          : {min(dates)} to {max(dates)}")
    print(f"DB inserted/updated/unchanged : {inserted:,} / {updated:,} / {unchanged:,}")
    for warning in validation.warnings + parsed.notes:
        print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
