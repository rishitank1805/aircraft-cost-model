"""Load navigation unit rates (en-route and terminal) and terminal charging-zone aerodromes.

Reads the local, git-ignored transcriptions in data/local/navigation_rates/
(navigation_unit_rates.csv, terminal_zone_aerodromes.csv). See
data/reference/navigation_rate_sources.csv for the documents and their status.
"""

from __future__ import annotations

import sys

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.ingestion.airport_tariffs import load_navigation_rates
from aircraft_cost_model.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    migrate_database(settings.database_url)
    try:
        validation, (inserted, updated), zones = load_navigation_rates(
            create_db_engine(settings.database_url), settings.local_navigation_dir)
    except SourceSchemaError as exc:
        print(f"Navigation-rate ingestion failed: {exc}")
        return 1
    print("\n=== Navigation unit-rate ingestion summary ===")
    print(f"Directory           : {settings.local_navigation_dir} (local, not redistributed)")
    print(f"Rates               : {len(validation.valid)} valid, {len(validation.rejected)} rejected; "
          f"inserted {inserted}, updated {updated}")
    print(f"Zone aerodrome rows : {zones}")
    for row in validation.valid:
        print(f"  {row['charge_type']:<9} {row['charging_zone']:<20} {row['unit_rate']:>8} {row['currency']}  "
              f"{row['valid_from']} - {row['valid_to']}  [{row['verification_status']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
