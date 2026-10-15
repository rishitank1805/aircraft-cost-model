"""Common validation report structure shared by airport and aircraft validators."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ValidationReport:
    """Result of validating one cleaned dataset.

    ``errors`` are blocking: the dataset must not be loaded. ``warnings`` are
    informational (for example missing optional fields) and never block a load.
    """

    dataset_name: str
    source_name: str
    source_url: str
    retrieved_at: str | None
    source_version: str | None
    total_source_records: int
    cleaned_records: int
    rejected_records: int
    duplicate_records: int
    missing_values_by_field: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    statistics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True when there are no blocking errors."""
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation including the ``passed`` flag."""
        data = asdict(self)
        data["passed"] = self.passed
        return data

    def write_json(self, path: Path) -> Path:
        """Write the report as pretty-printed JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path
