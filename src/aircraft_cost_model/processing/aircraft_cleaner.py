"""Normalize OpenAP aircraft records and curated cargo targets into one master table.

Rules:
- Values supplied by OpenAP are stored as-is in their documented units.
- Derived values (unit conversions, parsed names) are labelled per field in
  ``field_provenance`` with the method used.
- Attributes OpenAP does not provide (MZFW, maximum payload) stay NULL; maximum
  payload is *not* derived from MZFW - OEW.
- Freighter targets never inherit values from a related passenger model.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from aircraft_cost_model.config import JET_FUEL_DENSITY_KG_PER_L
from aircraft_cost_model.ingestion.aircraft import CargoAircraftTarget

logger = logging.getLogger(__name__)

KNOWN_MANUFACTURERS = ("Airbus", "Boeing", "Bombardier", "Cessna", "Embraer", "Gulfstream")

COVERAGE_OPENAP_MODEL = "openap_model"
COVERAGE_RELATED_PASSENGER_ONLY = "related_passenger_variant_only"
COVERAGE_NONE = "no_openap_model"

SOURCE = "source"

PROCESSED_COLUMNS = (
    "aircraft_code",
    "icao_type_designator",
    "manufacturer",
    "model",
    "variant",
    "engine_type",
    "engine_model",
    "engine_count",
    "mtow_kg",
    "mlw_kg",
    "mzfw_kg",
    "oew_kg",
    "max_payload_kg",
    "fuel_capacity_l",
    "fuel_capacity_kg",
    "cruise_mach",
    "cruise_altitude_m",
    "cruise_speed_kt",
    "openap_supported",
    "openap_coverage",
    "openap_related_code",
    "field_provenance",
    "notes",
    # Retained in the processed file only (not in the relational table):
    "vmo_kt",
    "mmo",
    "ceiling_m",
    "openap_nominal_cruise_range_km",
    "engine_options",
)


def split_manufacturer(name: str | None) -> tuple[str | None, str | None]:
    """Split an OpenAP aircraft name such as ``"Airbus A330-200"`` into manufacturer and model.

    Returns ``(None, name)`` when the leading word is not a known manufacturer,
    rather than guessing.
    """
    if not name:
        return None, None
    head, _, rest = name.strip().partition(" ")
    for manufacturer in KNOWN_MANUFACTURERS:
        if head.lower() == manufacturer.lower() and rest:
            return manufacturer, rest.strip()
    return None, name.strip()


def mach_to_tas_kt(mach: float, altitude_m: float) -> float:
    """True airspeed in knots for a Mach number at a pressure altitude in the ISA atmosphere."""
    from openap import aero

    return float(aero.mach2tas(mach, altitude_m) / aero.kts)


def _to_float(value: Any) -> float | None:
    """Return a float for numeric values, ``None`` for missing or non-numeric ones."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def normalize_openap_record(code: str, record: dict[str, Any]) -> dict[str, Any]:
    """Convert one raw OpenAP aircraft dict into a master-data row."""
    provenance: dict[str, str] = {}
    row: dict[str, Any] = {column: None for column in PROCESSED_COLUMNS}
    engine = record.get("engine") or {}
    cruise = record.get("cruise") or {}

    row["aircraft_code"] = code.strip().upper()
    row["icao_type_designator"] = code.strip().upper()
    provenance["icao_type_designator"] = "source: OpenAP file name (ICAO type designator)"

    manufacturer, model = split_manufacturer(record.get("aircraft"))
    row["manufacturer"], row["model"] = manufacturer, model
    if manufacturer:
        provenance["manufacturer"] = "derived: first word of OpenAP 'aircraft' name"
        provenance["model"] = "derived: OpenAP 'aircraft' name without manufacturer"
    else:
        provenance["model"] = "source: OpenAP 'aircraft' name"

    direct_fields = {
        "engine_type": engine.get("type"),
        "engine_model": engine.get("default"),
        "engine_count": engine.get("number"),
        "mtow_kg": record.get("mtow"),
        "mlw_kg": record.get("mlw"),
        "oew_kg": record.get("oew"),
        "fuel_capacity_l": record.get("mfc"),
        "cruise_mach": cruise.get("mach"),
        "cruise_altitude_m": cruise.get("height"),
        "vmo_kt": record.get("vmo"),
        "mmo": record.get("mmo"),
        "ceiling_m": record.get("ceiling"),
        "openap_nominal_cruise_range_km": cruise.get("range"),
    }
    numeric = {k for k in direct_fields if k not in ("engine_type", "engine_model")}
    for field, value in direct_fields.items():
        if field in numeric:
            value = _to_float(value)
        row[field] = value
        if value is not None:
            provenance[field] = SOURCE
    if row["engine_model"] is not None:
        provenance["engine_model"] = "source: OpenAP engine.default (one of several engine options)"
    if row["engine_count"] is not None:
        row["engine_count"] = int(row["engine_count"])

    options = engine.get("options")
    if options:
        row["engine_options"] = json.dumps(options, sort_keys=True)

    if row["fuel_capacity_l"] is not None:
        row["fuel_capacity_kg"] = round(row["fuel_capacity_l"] * JET_FUEL_DENSITY_KG_PER_L, 1)
        provenance["fuel_capacity_kg"] = (
            f"derived: fuel_capacity_l x {JET_FUEL_DENSITY_KG_PER_L} kg/L "
            "(jet fuel density used by OpenAP mass.py)"
        )
    if row["cruise_mach"] is not None and row["cruise_altitude_m"] is not None:
        row["cruise_speed_kt"] = round(mach_to_tas_kt(row["cruise_mach"], row["cruise_altitude_m"]), 1)
        provenance["cruise_speed_kt"] = (
            "derived: true airspeed from cruise_mach at cruise_altitude_m, ISA standard "
            "atmosphere (openap.aero.mach2tas)"
        )

    row["openap_supported"] = True
    row["openap_coverage"] = COVERAGE_OPENAP_MODEL
    row["field_provenance"] = json.dumps(provenance, sort_keys=True)
    row["notes"] = (
        "OpenAP aircraft model. Not available from OpenAP: MZFW, maximum payload, "
        "variant. Nominal cruise range is retained in the processed file only and is "
        "not a payload-independent range."
    )
    return row


def normalize_openap_aircraft(records: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Normalize all OpenAP records into a DataFrame sorted by ``aircraft_code``."""
    rows = [normalize_openap_record(code, record) for code, record in records.items()]
    frame = pd.DataFrame(rows, columns=list(PROCESSED_COLUMNS))
    return frame.sort_values("aircraft_code").reset_index(drop=True)


def build_cargo_target_rows(
    targets: tuple[CargoAircraftTarget, ...] | list[CargoAircraftTarget],
    openap_codes: set[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Create master rows for freighter targets with performance fields left NULL.

    Returns:
        ``(frame, warnings)``. A target's related OpenAP code is cleared, with a
        warning, if that code is not present in the installed OpenAP data.
    """
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    for target in targets:
        related = target.openap_related_code
        if related and related.upper() not in openap_codes:
            warnings.append(f"{target.aircraft_code}: related OpenAP code {related} not found; cleared")
            related = None
        row: dict[str, Any] = {column: None for column in PROCESSED_COLUMNS}
        row.update(
            aircraft_code=target.aircraft_code.strip().upper(),
            icao_type_designator=target.icao_type_designator.strip().upper(),
            manufacturer=target.manufacturer,
            model=target.model,
            variant=target.variant,
            openap_supported=False,
            openap_coverage=COVERAGE_RELATED_PASSENGER_ONLY if related else COVERAGE_NONE,
            openap_related_code=related.upper() if related else None,
            notes=target.notes + " Performance and weight fields are NULL pending a documented public source.",
            field_provenance=json.dumps(
                {
                    "icao_type_designator": "source: ICAO Doc 8643 (curated, individual designator)",
                    "manufacturer": "source: project-curated list",
                    "model": "source: project-curated list",
                    "variant": "source: project-curated list",
                },
                sort_keys=True,
            ),
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=list(PROCESSED_COLUMNS)), warnings


def coverage_table(cargo_rows: pd.DataFrame) -> pd.DataFrame:
    """Compact cargo coverage summary for reporting."""
    return cargo_rows[
        ["aircraft_code", "icao_type_designator", "openap_supported", "openap_coverage", "openap_related_code", "notes"]
    ].reset_index(drop=True)


def save_aircraft(master: pd.DataFrame, cargo_rows: pd.DataFrame, output_dir: Path) -> dict[str, Path]:
    """Write the processed aircraft master table and cargo coverage as CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "master": output_dir / "aircraft_types.csv",
        "cargo_coverage": output_dir / "cargo_aircraft_coverage.csv",
    }
    master.to_csv(paths["master"], index=False)
    coverage_table(cargo_rows).to_csv(paths["cargo_coverage"], index=False)
    logger.info("aircraft_saved", extra={k: str(v) for k, v in paths.items()})
    return paths
