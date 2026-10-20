"""Build the public explorer database for hosted deployments (e.g. Vercel).

Example (from the repository root)::

    python scripts/build_public_db.py

Writes ``database/explorer_public.db`` (git-ignored) and ``database/explorer_public.db.gz``
(committed; the hosted build restores it). The rows of the restricted EUROCONTROL / DFS / Fraport
rate tables are removed; the live database is only read.
Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import sys

from aircraft_cost_model.api.public_db import PublicDatabaseError, build_public_database
from aircraft_cost_model.config import get_settings
from aircraft_cost_model.logging_config import configure_logging


def main() -> int:
    configure_logging()
    settings = get_settings(create_directories=False)
    target = settings.database_path.parent / "explorer_public.db"
    try:
        result = build_public_database(settings.database_path, target)
    except (FileNotFoundError, PublicDatabaseError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Public database: {result.database_path} ({result.size_bytes / 1_048_576:.1f} MB)")
    print(f"Compressed copy: {result.compressed_path} ({result.compressed_path.stat().st_size / 1_048_576:.1f} MB)")
    print("Removed restricted rows: " + ", ".join(f"{t}={n}" for t, n in result.removed_rows.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
