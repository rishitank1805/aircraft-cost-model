"""Vercel entrypoint for the Aircraft Explorer (``[tool.vercel] entrypoint`` in pyproject.toml).

Serves the read-only API and the built frontend from the public database
(``database/explorer_public.db``, restored by ``scripts/vercel_build.py``), which excludes the
restricted EUROCONTROL / DFS / Fraport rate tables. Vercel imports this module to obtain ``app``,
so creating the app here is intentional; it only opens the database read-only.
Local use stays ``python scripts/run_explorer.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("ACM_PROJECT_ROOT", str(ROOT))
if str(ROOT / "src") not in sys.path:  # the project package may not be installed on Vercel
    sys.path.insert(0, str(ROOT / "src"))

from aircraft_cost_model.api.app import create_app  # noqa: E402

app: FastAPI = create_app(database_path=ROOT / "database" / "explorer_public.db",
                          static_dir=ROOT / "frontend" / "dist")
