"""Validation checks for the aircraft master table."""

from __future__ import annotations

import json
import logging

import pandas as pd

from aircraft_cost_model.validation.report import ValidationReport

logger = logging.getLogger(__name__)

PERFORMANCE_FIELDS = (
    "engine_type",
    "engine_count",
    "mtow_kg",
    "mlw_kg",
    "mzfw_kg",
    "oew_kg",
    "max_payload_kg",
    "fuel_capacity_l",
    "fuel_capacity_kg",
    "cruise_speed_kt",
)

# Fields that are only ever populated by a derivation/conversion and must be labelled.
DERIVED_FIELDS = ("fuel_capacity_kg", "cruise_speed_kt")


def _value(row: pd.Series, field: str) -> float | None:
    value = row.get(field)
    return None if value is None or pd.isna(value) else float(value)


def check_weight_relationships(row: pd.Series) -> list[str]:
    """Return warnings for implausible weight relationships.

    Only clearly inconsistent combinations are flagged (e.g. OEW above MTOW).
    Equalities are accepted because sources and certification variants differ in
    definitions; nothing here rejects a record.
    """
    code = row.get("aircraft_code")
    mtow, mlw, mzfw, oew = (_value(row, f) for f in ("mtow_kg", "mlw_kg", "mzfw_kg", "oew_kg"))
    payload = _value(row, "max_payload_kg")
    warnings: list[str] = []
    checks = (
        (oew, mtow, "oew_kg", "mtow_kg"),
        (mlw, mtow, "mlw_kg", "mtow_kg"),
        (oew, mlw, "oew_kg", "mlw_kg"),
        (mzfw, mlw, "mzfw_kg", "mlw_kg"),
        (oew, mzfw, "oew_kg", "mzfw_kg"),
        (payload, mtow, "max_payload_kg", "mtow_kg"),
    )
    for low, high, low_name, high_name in checks:
        if low is not None and high is not None and low > high:
            warnings.append(f"{code}: {low_name} ({low:g}) exceeds {high_name} ({high:g})")
    return warnings


def validate_aircraft(
    master: pd.DataFrame,
    *,
    total_source_records: int,
    source_name: str,
    source_url: str,
    retrieved_at: str | None,
    source_version: str | None,
    extra_warnings: list[str] | None = None,
) -> ValidationReport:
    """Validate the aircraft master table.

    Blocking errors: duplicate/empty ``aircraft_code``, non-positive MTOW, fuel
    capacity or engine count, and derived values without a provenance label.
    Weight relationship issues and missing attributes are warnings.
    """
    errors: list[str] = []
    warnings: list[str] = list(extra_warnings or [])

    codes = master["aircraft_code"]
    if codes.isna().any() or (codes.astype("string").str.strip() == "").any():
        errors.append("Empty aircraft_code values present")
    if codes.duplicated().any():
        errors.append(f"Duplicate aircraft_code values: {sorted(codes[codes.duplicated()].unique())}")
    if (codes != codes.str.upper()).any():
        errors.append("aircraft_code values are not normalized to uppercase")

    for field in ("mtow_kg", "fuel_capacity_l", "fuel_capacity_kg", "engine_count"):
        values = pd.to_numeric(master[field], errors="coerce")
        bad = master.loc[values.notna() & (values <= 0), "aircraft_code"]
        if not bad.empty:
            errors.append(f"Non-positive {field} for: {sorted(bad)}")

    for _, row in master.iterrows():
        warnings.extend(check_weight_relationships(row))
        provenance = json.loads(row["field_provenance"]) if isinstance(row["field_provenance"], str) else {}
        for field in DERIVED_FIELDS:
            if pd.notna(row[field]) and not str(provenance.get(field, "")).startswith("derived:"):
                errors.append(f"{row['aircraft_code']}: {field} populated without a 'derived:' provenance label")

    missing = {f: int(master[f].isna().sum()) for f in PERFORMANCE_FIELDS}
    for field, count in missing.items():
        if count == len(master):
            warnings.append(f"{field} is unavailable for all {count} records (left NULL)")

    report = ValidationReport(
        dataset_name="aircraft_types",
        source_name=source_name,
        source_url=source_url,
        retrieved_at=retrieved_at,
        source_version=source_version,
        total_source_records=total_source_records,
        cleaned_records=len(master),
        rejected_records=total_source_records - len(master),
        duplicate_records=int(codes.duplicated().sum()),
        missing_values_by_field=missing,
        errors=errors,
        warnings=warnings,
        statistics={
            "openap_supported": int(master["openap_supported"].astype(bool).sum()),
            "by_coverage": {str(k): int(v) for k, v in master["openap_coverage"].value_counts().items()},
            "by_manufacturer": {
                str(k): int(v) for k, v in master["manufacturer"].value_counts(dropna=False).items()
            },
        },
    )
    logger.info(
        "aircraft_validated",
        extra={"passed": report.passed, "errors": len(errors), "warnings": len(warnings)},
    )
    return report
