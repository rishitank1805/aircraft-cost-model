"""FastAPI application factory.

Run locally (see docs/explorer_app.md)::

    python scripts/run_explorer.py            # API + built frontend on http://127.0.0.1:8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aircraft_cost_model import __version__
from aircraft_cost_model.api.db import read_only_engine
from aircraft_cost_model.api.routers import aircraft, economics, flight, learn
from aircraft_cost_model.config import get_settings
from aircraft_cost_model.database import current_revision, head_revision


def create_app(database_path: Path | None = None, static_dir: Path | None = None) -> FastAPI:
    settings = get_settings(create_directories=False)
    path = database_path or settings.database_path
    if not path.is_file():
        raise FileNotFoundError(f"database not found: {path}")
    engine = read_only_engine(path)
    revision = current_revision(engine)
    if revision != head_revision():
        raise RuntimeError(f"database revision {revision} is not {head_revision()}; run the ingestion scripts "
                           "(which migrate) before starting the explorer")
    app = FastAPI(title="Aircraft Explorer API", version=__version__,
                  description="Read-only API over the Open Aircraft Operating Cost Model database.")
    app.state.engine = engine
    app.state.settings = settings
    app.state.database_path = path
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["*"])
    for router in (aircraft.router, learn.router, flight.router, economics.router):
        app.include_router(router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "database_revision": revision, "read_only": True, "version": __version__}

    static = static_dir or settings.project_root / "frontend" / "dist"
    if static.is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            root = static.resolve()
            candidate = (root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(root):  # no path traversal
                return FileResponse(candidate)
            return FileResponse(root / "index.html")
    return app
