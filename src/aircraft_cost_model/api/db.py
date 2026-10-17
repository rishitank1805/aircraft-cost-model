"""Read-only database access for the API."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from aircraft_cost_model.database import create_db_engine


def read_only_engine(database_path: Path) -> Engine:
    """SQLite opened with ``mode=ro``: any write attempt raises an error."""
    return create_db_engine(f"sqlite:///file:{database_path.resolve().as_posix()}?mode=ro&uri=true")


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
