"""Load locally transcribed airport tariff files (data/local/airport_tariffs/*.json, git-ignored).

The files hold values transcribed from airport operators' published charge
documents whose reuse terms are not stated; they are used locally and not
redistributed. See data/reference/airport_tariff_sources.csv for the status of
each airport.
"""

from __future__ import annotations

import sys

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.ingestion.airport_tariffs import load_airport_tariffs
from aircraft_cost_model.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    directory = settings.local_tariffs_dir
    if not any(directory.glob("*.json")):
        print(f"No tariff files in {directory}. Airport charges will be reported as unavailable_public_tariff.")
        return 0
    migrate_database(settings.database_url)
    try:
        results = load_airport_tariffs(create_db_engine(settings.database_url), directory)
    except SourceSchemaError as exc:
        print(f"Airport tariff ingestion failed: {exc}")
        return 1
    print("\n=== Airport tariff ingestion summary ===")
    for name, inserted, updated in results:
        print(f"  {name}: inserted {inserted}, updated {updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
