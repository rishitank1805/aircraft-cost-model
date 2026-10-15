"""Validation checks for the cleaned airport dataset."""

from __future__ import annotations

import logging

from pandas.api.types import is_numeric_dtype

from aircraft_cost_model.processing.airport_cleaner import AirportCleaningResult, REJECTED_REASON_COLUMN
from aircraft_cost_model.validation.report import ValidationReport

logger = logging.getLogger(__name__)

IMPORTANT_FIELDS = (
    "airport_ident",
    "airport_name",
    "airport_type",
    "latitude",
    "longitude",
    "elevation_ft",
    "country_code",
    "region_code",
    "municipality",
    "scheduled_service",
    "icao_code",
    "iata_code",
    "gps_code",
)


def validate_airports(
    result: AirportCleaningResult,
    *,
    source_name: str,
    source_url: str,
    retrieved_at: str | None,
    source_version: str | None,
) -> ValidationReport:
    """Validate cleaned airports and build a report.

    Blocking errors: duplicate source ids, non-numeric or out-of-range
    coordinates, empty identifiers in the *cleaned* frame (any of these means
    cleaning failed). Missing optional fields and repeated IATA codes are
    reported as warnings only.
    """
    df = result.cleaned
    errors: list[str] = []
    warnings = list(result.warnings)

    if df["source_airport_id"].duplicated().any():
        errors.append(f"{int(df['source_airport_id'].duplicated().sum())} duplicate source_airport_id values")
    for column, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
        if not is_numeric_dtype(df[column]):
            errors.append(f"{column} is not numeric (dtype {df[column].dtype})")
            continue
        out_of_range = ~df[column].between(low, high).fillna(False)
        if out_of_range.any():
            errors.append(f"{int(out_of_range.sum())} {column} values outside [{low}, {high}]")
    empty_ident = df["airport_ident"].isna() | (df["airport_ident"].astype("string").str.strip() == "")
    if empty_ident.any():
        errors.append(f"{int(empty_ident.sum())} empty airport_ident values")

    iata = df["iata_code"].dropna()
    repeated_iata = iata[iata.duplicated(keep=False)]
    if not repeated_iata.empty:
        warnings.append(
            f"{repeated_iata.nunique()} IATA codes appear on more than one airport "
            f"(examples: {sorted(repeated_iata.unique())[:5]}); IATA is not treated as unique"
        )
    if not result.rejected.empty:
        counts = result.rejected[REJECTED_REASON_COLUMN].value_counts().to_dict()
        warnings.append(f"Rejected rows by reason: {counts}")

    missing = {c: int(df[c].isna().sum()) for c in IMPORTANT_FIELDS if c in df.columns}

    report = ValidationReport(
        dataset_name="airports",
        source_name=source_name,
        source_url=source_url,
        retrieved_at=retrieved_at,
        source_version=source_version,
        total_source_records=result.source_record_count,
        cleaned_records=len(df),
        rejected_records=len(result.rejected),
        duplicate_records=result.duplicate_count,
        missing_values_by_field=missing,
        errors=errors,
        warnings=warnings,
        statistics={
            "airports_by_type": {str(k): int(v) for k, v in df["airport_type"].value_counts(dropna=False).items()},
            "airports_by_country": {
                str(k): int(v) for k, v in df["country_code"].value_counts(dropna=False).items()
            },
            "rejected_by_reason": (
                result.rejected[REJECTED_REASON_COLUMN].value_counts().to_dict()
                if not result.rejected.empty
                else {}
            ),
            "airports_with_iata_code": int(df["iata_code"].notna().sum()),
            "airports_with_icao_code": int(df["icao_code"].notna().sum()),
            "airports_with_scheduled_service": int(df["scheduled_service"].fillna(False).sum()),
        },
    )
    logger.info(
        "airports_validated",
        extra={"passed": report.passed, "errors": len(errors), "warnings": len(warnings)},
    )
    return report

