"""Read aircraft metadata from the installed OpenAP package and define cargo coverage targets.

OpenAP (https://github.com/TUDelft-CNS-ATM/openap) ships one YAML file per
aircraft type in ``openap/data/aircraft/``. There is no separate download
endpoint; the installed package *is* the source. The raw records returned by
``openap.prop.aircraft`` are snapshotted unmodified to ``data/raw/aircraft/``.

Inspection of OpenAP 2.6.2 (2026-10-15) found, per aircraft file:
``mtow``, ``mlw``, ``oew`` (kg); ``mfc`` (maximum fuel capacity in *litres*,
as shown by OpenAP's own ``mass.py``: ``mfc * 0.8025  # L->kg``); ``vmo`` (kt);
``mmo``; ``ceiling`` (m); ``cruise.height`` (m), ``cruise.mach``,
``cruise.range`` (km, nominal); ``engine.type/number/default/options``.
No MZFW, maximum payload or freighter-specific files exist.

Synonyms (``openap/data/aircraft/_synonym.csv``) map unsupported types to
*different* aircraft (e.g. B77L -> B77W) and are deliberately not used.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenAPSnapshot:
    """Raw OpenAP aircraft records plus provenance."""

    records: dict[str, dict[str, Any]]
    openap_version: str
    data_checksum: str
    retrieved_at: datetime
    raw_path: Path | None = None


@dataclass(frozen=True)
class CargoAircraftTarget:
    """A freighter type the cost model must eventually support (one row of the curated CSV).

    ``icao_type_designator`` values are individual facts referenced from ICAO
    Doc 8643 (Aircraft Type Designators); ICAO does not distinguish freighters
    from passenger variants for most types. ``openap_related_code`` is set only
    when OpenAP has a model with the *same* ICAO designator (i.e. a related
    passenger variant) - it is recorded for coverage, never substituted.
    """

    aircraft_code: str
    manufacturer: str
    model: str
    variant: str
    icao_type_designator: str
    openap_related_code: str | None
    designator_reference: str
    notes: str


CARGO_TARGETS_SOURCE_NAME = "Project-curated cargo aircraft coverage list"
CARGO_TARGETS_REFERENCE_URL = "https://www.icao.int/publications/doc-8643-aircraft-type-designators"


def get_openap_version() -> str:
    """Installed OpenAP distribution version."""
    return metadata.version("openap")


def _openap_aircraft_files() -> list[Path]:
    import openap

    data_dir = Path(openap.__file__).resolve().parent / "data" / "aircraft"
    return sorted(data_dir.glob("*.yml"))


def openap_data_checksum() -> str:
    """SHA-256 over the names and bytes of all OpenAP aircraft YAML files.

    Identifies the exact aircraft data version even if the package version string
    stays the same.
    """
    digest = hashlib.sha256()
    for path in _openap_aircraft_files():
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def read_openap_aircraft() -> OpenAPSnapshot:
    """Read every aircraft record available in the installed OpenAP package.

    Uses ``openap.prop.available_aircraft(use_synonym=False)`` and
    ``openap.prop.aircraft(code)`` so only genuine OpenAP entries are returned.
    """
    from openap import prop

    records: dict[str, dict[str, Any]] = {}
    for code in prop.available_aircraft(use_synonym=False):
        record = prop.aircraft(code, use_synonym=False)
        record.pop("limits", None)  # compatibility duplicate added by OpenAP at load time
        records[code.upper()] = record
    snapshot = OpenAPSnapshot(
        records=records,
        openap_version=get_openap_version(),
        data_checksum=openap_data_checksum(),
        retrieved_at=datetime.now(timezone.utc).replace(microsecond=0),
    )
    logger.info(
        "openap_aircraft_read",
        extra={
            "count": len(records),
            "openap_version": snapshot.openap_version,
            "sha256": snapshot.data_checksum,
        },
    )
    return snapshot


def save_openap_snapshot(snapshot: OpenAPSnapshot, raw_dir: Path) -> OpenAPSnapshot:
    """Persist the raw OpenAP records as JSON (one file per OpenAP data version).

    If a snapshot for the same data checksum already exists it is reused and
    its original retrieval timestamp is kept.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"openap_aircraft_{snapshot.openap_version}_{snapshot.data_checksum[:12]}.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        logger.info("openap_snapshot_reused", extra={"path": path.name})
        return OpenAPSnapshot(
            records=snapshot.records,
            openap_version=snapshot.openap_version,
            data_checksum=snapshot.data_checksum,
            retrieved_at=datetime.fromisoformat(existing["retrieved_at"]),
            raw_path=path,
        )
    payload = {
        "source": "openap python package",
        "openap_version": snapshot.openap_version,
        "data_checksum_sha256": snapshot.data_checksum,
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "records": snapshot.records,
    }
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)
    logger.info("openap_snapshot_saved", extra={"path": path.name})
    return OpenAPSnapshot(**{**asdict(snapshot), "raw_path": path})


CARGO_TARGET_COLUMNS = (
    "aircraft_code",
    "manufacturer",
    "model",
    "variant",
    "icao_type_designator",
    "openap_related_code",
    "designator_reference",
    "notes",
)


def load_cargo_targets(path: Path) -> tuple[CargoAircraftTarget, ...]:
    """Read the version-controlled freighter target list (``data/reference/cargo_aircraft_targets.csv``).

    Raises:
        ValueError: If columns are missing, a required value is empty or a code is duplicated.
    """
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in CARGO_TARGET_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} is missing columns: {missing}")
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
    targets: list[CargoAircraftTarget] = []
    for number, row in enumerate(rows, start=2):
        for required in ("aircraft_code", "manufacturer", "model", "icao_type_designator"):
            if not row[required]:
                raise ValueError(f"{path.name} line {number}: empty {required}")
        targets.append(
            CargoAircraftTarget(
                aircraft_code=row["aircraft_code"],
                manufacturer=row["manufacturer"],
                model=row["model"],
                variant=row["variant"],
                icao_type_designator=row["icao_type_designator"],
                openap_related_code=row["openap_related_code"] or None,
                designator_reference=row["designator_reference"],
                notes=row["notes"],
            )
        )
    codes = [t.aircraft_code.upper() for t in targets]
    duplicates = sorted({c for c in codes if codes.count(c) > 1})
    if duplicates:
        raise ValueError(f"{path.name}: duplicate aircraft_code values {duplicates}")
    return tuple(targets)


def cargo_targets_checksum(path: Path) -> str:
    """SHA-256 of the curated CSV file (changes whenever the list is edited)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
