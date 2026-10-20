"""Download (or reuse) BTS Form 41 P-5.2 + T2 snapshots and load benchmark observations; load FAA Table 4-7.

Examples::

    python scripts/ingest_bts_benchmarks.py --years 2024 2025        # download, snapshot, load
    python scripts/ingest_bts_benchmarks.py --years 2024 --offline   # reuse the latest local snapshots

Snapshots (ZIP, byte for byte) go to ``data/raw/bts/`` (git-ignored) with a
metadata sidecar. Loading is idempotent: observations are keyed by source
snapshot, so a revised download adds a new version and never overwrites one.
BTS data are public domain (citation required). Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.benchmarks import load_faa_benchmarks
from aircraft_cost_model.analytics.cli import open_database, reference_path
from aircraft_cost_model.config import get_settings
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.ingestion import bts_form41 as bts
from aircraft_cost_model.ingestion.snapshots import DownloadError
from aircraft_cost_model.processing.bts_form41 import build_records, read_lookup, read_zip_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", required=True)
    parser.add_argument("--offline", action="store_true", help="use the latest local snapshots; no network")
    args = parser.parse_args(argv)
    settings = get_settings()
    raw = settings.raw_bts_dir
    try:
        engine = open_database()
        lookup = (bts.latest_lookup_snapshot(raw, "L_AIRCRAFT_TYPE") if args.offline
                  else bts.download_lookup("L_AIRCRAFT_TYPE", raw, settings.http_timeout))
        if not args.offline:
            for name in bts.LOOKUPS[1:]:
                bts.download_lookup(name, raw, settings.http_timeout)
        if lookup is None:
            raise DownloadError("no local L_AIRCRAFT_TYPE snapshot (run without --offline)")
        types = read_lookup(lookup.path)
        for year in args.years:
            if args.offline:
                p52, t2 = bts.latest_table_snapshot(raw, "P52", year), bts.latest_table_snapshot(raw, "T2", year)
                if p52 is None or t2 is None:
                    raise DownloadError(f"no local snapshots for {year} (run without --offline)")
            else:
                p52 = bts.download_table("P52", year, raw)
                t2 = bts.download_table("T2", year, raw)
            parsed = build_records(read_zip_csv(p52.path, bts.TABLES["P52"].csv_name),
                                   read_zip_csv(t2.path, bts.TABLES["T2"].csv_name), types)
            inserted, existing = bts.load_bts_benchmarks(engine, p52, t2, year, parsed.records)
            statuses: dict[str, int] = {}
            for r in parsed.records:
                if r["cost_category"] == "aircraft_operating_total":
                    statuses[r["quality_status"]] = statuses.get(r["quality_status"], 0) + 1
            print(f"{year}: P-5.2 {p52.path.name} ({parsed.p52_rows} rows; {parsed.excluded_unattributed} unattributed "
                  f"fleet rows excluded), T2 {t2.path.name} ({parsed.t2_rows} rows); {inserted} observations inserted, "
                  f"{existing} already present; row quality {statuses}")
            for w in parsed.warnings:
                print(f"  ! {w}")
        with Session(engine) as session, session.begin():
            inserted, existing = load_faa_benchmarks(session, reference_path("faa_economic_values_table_4_7.csv"))
        print(f"FAA Table 4-7: {inserted} inserted, {existing} already present")
    except (DownloadError, SourceSchemaError, OSError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
