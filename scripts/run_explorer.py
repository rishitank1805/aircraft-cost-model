"""Run the Aircraft Explorer: read-only API plus the built frontend.

Examples::

    cd frontend && npm install && npm run build && cd ..
    python scripts/run_explorer.py                 # http://127.0.0.1:8000
    python scripts/run_explorer.py --port 8001
    python scripts/run_explorer.py --reload        # restart on changes to src/ and data/reference/

For frontend development run the API with this script and ``npm run dev`` in
``frontend/`` (Vite proxies /api to port 8000). The database is opened read-only.
Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from aircraft_cost_model.api.app import create_app
from aircraft_cost_model.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true",
                        help="restart automatically when code, content JSON or reference CSVs change (development)")
    args = parser.parse_args(argv)
    if args.reload:
        settings = get_settings(create_directories=False)
        uvicorn.run("aircraft_cost_model.api.app:create_app", factory=True, host=args.host, port=args.port,
                    log_level="warning", reload=True,
                    reload_dirs=[str(settings.project_root / "src"), str(settings.reference_dir)],
                    reload_includes=["*.py", "*.json", "*.csv"])
        return 0
    try:
        app = create_app()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
