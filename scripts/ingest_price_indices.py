"""Load BLS index series (official API) and compute optional index adjustments of the FAA benchmarks.

Examples::

    python scripts/ingest_price_indices.py --start-year 2021 --end-year 2026
    python scripts/ingest_price_indices.py --offline --adjust-target-date 2025-01-15

The series come from ``data/reference/benchmark_index_mapping.csv`` (only
categories with an index). Originals are never modified; categories without a
verified index are recorded as ``unavailable``. Proxy indices are labelled
``proxy_pending_owner_approval``. Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cli import open_database, reference_path
from aircraft_cost_model.analytics.inflation import adjust_benchmarks, read_index_mapping, save_adjustments
from aircraft_cost_model.config import get_settings
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.ingestion.price_indices import download_series, load_index_observations, parse_series_json
from aircraft_cost_model.ingestion.snapshots import DownloadError, latest_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--offline", action="store_true", help="use the latest local BLS snapshot")
    parser.add_argument("--adjust-target-date", type=date.fromisoformat)
    parser.add_argument("--retrospective", action="store_true",
                        help="ignore the publication lag (explicit retrospective comparison)")
    args = parser.parse_args(argv)
    settings = get_settings()
    mapping = read_index_mapping(reference_path("benchmark_index_mapping.csv"))
    series = sorted({m.series_id for m in mapping.values() if m.series_id})
    titles = {m.series_id: m.title for m in mapping.values() if m.series_id}
    try:
        engine = open_database()
        if args.offline:
            snapshot = latest_snapshot(settings.raw_price_indices_dir, f"bls_{'_'.join(series)[:80]}", ".json")
            if snapshot is None:
                raise DownloadError("no local BLS snapshot (run without --offline)")
        else:
            if args.start_year is None or args.end_year is None:
                raise DownloadError("--start-year and --end-year are required when downloading")
            snapshot = download_series(series, args.start_year, args.end_year, settings.raw_price_indices_dir,
                                       settings.http_timeout)
        records, messages = parse_series_json(snapshot.path)
        inserted, existing = load_index_observations(engine, snapshot, records, titles)
        print(f"{snapshot.path.name}: {len(records)} observations ({inserted} inserted, {existing} already present)")
        for m in messages:
            print(f"  BLS: {m}")
        if args.adjust_target_date:
            with Session(engine) as session, session.begin():
                results = adjust_benchmarks(session, mapping, args.adjust_target_date,
                                            retrospective=args.retrospective)
                saved = save_adjustments(session, results)
                for obs, r in results:
                    if r.status == "adjusted":
                        print(f"  {obs.cost_category:<12} {obs.amount} {obs.currency}/BH ({obs.period_label}) x "
                              f"{r.target_index:.4f}/{r.base_index:.4f} = factor {r.factor:.6f} -> "
                              f"{r.adjusted_amount:.2f} [{r.index_series_id}; {r.suitability}; target {r.target_period}]")
                    else:
                        print(f"  {obs.cost_category:<12} UNAVAILABLE: {r.reason}")
            print(f"{saved} adjustment record(s) stored; original benchmark values unchanged")
    except (DownloadError, SourceSchemaError, OSError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
