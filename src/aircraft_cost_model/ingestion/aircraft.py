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
    """A freighter type the cost model must eventually support.

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
    notes: str


CARGO_AIRCRAFT_TARGETS: tuple[CargoAircraftTarget, ...] = (
    CargoAircraftTarget(
        aircraft_code="A330-200F",
        manufacturer="Airbus",
        model="A330-200F",
        variant="production freighter",
        icao_type_designator="A332",
        openap_related_code="A332",
        notes="OpenAP A332 models the A330-200 passenger aircraft; its weights and "
        "performance are not applicable to the freighter without validation.",
    ),
    CargoAircraftTarget(
        aircraft_code="B777F",
        manufacturer="Boeing",
        model="777F",
        variant="production freighter",
        icao_type_designator="B77L",
        openap_related_code=None,
        notes="No OpenAP model for designator B77L. OpenAP's synonym table maps B77L "
        "to B77W (777-300ER), a different airframe; this project does not use it.",
    ),
    CargoAircraftTarget(
        aircraft_code="B767-300F",
        manufacturer="Boeing",
        model="767-300F",
        variant="production freighter",
        icao_type_designator="B763",
        openap_related_code="B763",
        notes="OpenAP B763 models the 767-300 passenger aircraft; not substituted.",
    ),
    CargoAircraftTarget(
        aircraft_code="B747-400F",
        manufacturer="Boeing",
        model="747-400F",
        variant="production freighter",
        icao_type_designator="B744",
        openap_related_code="B744",
        notes="OpenAP B744 models the 747-400 passenger aircraft; not substituted.",
    ),
    CargoAircraftTarget(
        aircraft_code="A321P2F",
        manufacturer="Airbus",
        model="A321P2F",
        variant="passenger-to-freighter conversion",
        icao_type_designator="A321",
        openap_related_code="A321",
        notes="Conversion of the A321 passenger aircraft. OpenAP A321 models the "
        "passenger aircraft; conversion changes OEW and payload limits; not substituted.",
    ),
)

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


def cargo_targets_checksum(targets: tuple[CargoAircraftTarget, ...] = CARGO_AIRCRAFT_TARGETS) -> str:
    """Checksum of the curated cargo target list (changes when the list is edited)."""
    payload = json.dumps([asdict(t) for t in targets], sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()
