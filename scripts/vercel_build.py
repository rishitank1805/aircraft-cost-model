"""Vercel build step: restore the public database and build the frontend.

Run by Vercel after the Python dependencies are installed (``[tool.vercel.scripts]`` in
pyproject.toml). Can also be run locally to reproduce the hosted layout.
Exit codes: 0 ok, non-zero on failure.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aircraft_cost_model.api.public_db import decompress_public_database  # noqa: E402


def main() -> int:
    compressed = ROOT / "database" / "explorer_public.db.gz"
    if not compressed.is_file():
        print(f"ERROR: {compressed} is missing; run scripts/build_public_db.py and commit it")
        return 1
    decompress_public_database(compressed, ROOT / "database" / "explorer_public.db")
    frontend = ROOT / "frontend"
    subprocess.run(["npm", "ci"], cwd=frontend, check=True)
    subprocess.run(["npm", "run", "build"], cwd=frontend, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
