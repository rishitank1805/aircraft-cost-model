"""Ingest ECB euro reference exchange rates (EXR, daily; quote = currency units per 1 EUR).

Usage::

    python scripts/ingest_exchange_rates.py                       # USD, GBP, CHF since 2024-01-01
    python scripts/ingest_exchange_rates.py --currencies USD,GBP --start 2020-01-01
    python scripts/ingest_exchange_rates.py --offline
"""

from __future__ import annotations

import argparse
import sys

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.costs.exceptions import CostInputError, SourceSchemaError
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.ingestion import exchange_rates as er
from aircraft_cost_model.ingestion.snapshots import DownloadError
from aircraft_cost_model.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--currencies", default="USD,GBP,CHF")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        if args.offline:
            snapshot = er.latest_ecb_snapshot(settings.raw_exchange_rates_dir)
            if snapshot is None:
                print(f"No preserved ECB snapshot in {settings.raw_exchange_rates_dir}")
                return 1
        else:
            snapshot = er.download_ecb_rates(settings.raw_exchange_rates_dir, args.currencies.split(","), args.start,
                                             settings.http_timeout)
        parsed = er.parse_ecb_csv(snapshot.path)
        validation = er.validate_rates(parsed)
        migrate_database(settings.database_url)
        inserted, updated, unchanged = er.load_exchange_rates(create_db_engine(settings.database_url), parsed,
                                                              validation, snapshot)
    except (DownloadError, SourceSchemaError, CostInputError) as exc:
        print(f"Exchange-rate ingestion failed: {exc}")
        return 1
    dates = [r["observation_date"] for r in validation.valid]
    print("\n=== ECB exchange-rate ingestion summary ===")
    print(f"Currencies        : {', '.join(parsed.currencies)} (units per 1 EUR)")
    print(f"Raw snapshot      : {snapshot.path.name} (sha256 {snapshot.sha256[:12]})"
          f"{'  [reused]' if snapshot.reused_existing else ''}")
    print(f"Observations      : {len(validation.valid):,} valid, {len(validation.rejected)} rejected")
    print(f"Coverage          : {min(dates)} to {max(dates)}")
    print(f"DB inserted/updated/unchanged : {inserted:,} / {updated:,} / {unchanged:,}")
    for warning in validation.warnings:
        print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
