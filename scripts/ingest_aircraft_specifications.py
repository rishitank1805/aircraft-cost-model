"""Load aircraft specification values with provenance (OpenAP, ICAO EEDB via OpenAP, FAA ACD, FAA Table 4-16/4-17,
curated freighter facts).

Examples::

    python scripts/ingest_aircraft_specifications.py            # downloads the FAA ACD XLSX snapshot
    python scripts/ingest_aircraft_specifications.py --offline  # reuses the latest local FAA ACD snapshot

Insert-only: re-running inserts nothing; a new source version adds rows. No value is
invented: missing specifications have no row. Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import argparse
import sys

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.ingestion import aircraft_specs as specs
from aircraft_cost_model.ingestion.snapshots import DownloadError
from aircraft_cost_model.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="reuse the latest local FAA ACD snapshot")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging("WARNING")
    migrate_database(settings.database_url)
    engine = create_db_engine(settings.database_url)
    raw = settings.project_root / "data" / "raw" / "faa_acd"
    try:
        report = [("OpenAP aircraft data", specs.load_openap_specs(engine, settings.raw_aircraft_dir)),
                  ("OpenAP engines.csv (ICAO EEDB)", specs.load_engine_specs(engine))]
        snapshot = specs.latest_faa_acd(raw) if args.offline else specs.download_faa_acd(raw, settings.http_timeout)
        if snapshot is None:
            raise DownloadError("no local FAA ACD snapshot (run without --offline)")
        report.append((f"FAA ACD ({snapshot.path.name})", specs.load_faa_acd(engine, snapshot)))
        ref = settings.reference_dir
        report.append(("FAA Tables 4-16/4-17 body class", specs.load_body_class(engine, ref / "aircraft_body_class_faa.csv")))
        report.append(("Curated freighter facts", specs.load_freighter_reference(
            engine, ref / "freighter_programs.csv", ref / "freighter_published_specs.csv")))
    except (DownloadError, FileNotFoundError, LookupError, OSError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    for name, (inserted, existing, unknown) in report:
        print(f"{name}: {inserted} inserted, {existing} already present" + (f"; unknown codes {unknown}" if unknown else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
