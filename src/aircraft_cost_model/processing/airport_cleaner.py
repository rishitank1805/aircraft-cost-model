"""Clean and normalize the raw OurAirports ``airports.csv``.

The cleaner transforms values; it does not decide whether a dataset is
acceptable (that is the validator's job). Rows that cannot be used at all
(missing identifier, unusable coordinates, duplicate source id) are moved to a
separate *rejected* frame with an explicit reason instead of being silently
dropped. No missing value is replaced by an invented default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Source column -> cleaned column. Verified against the live CSV header
# (2026-10-15): id, ident, type, name, latitude_deg, longitude_deg, elevation_ft,
# continent, iso_country, iso_region, municipality, scheduled_service, icao_code,
# iata_code, gps_code, local_code, home_link, wikipedia_link, keywords.
COLUMN_MAPPING: dict[str, str] = {
    "id": "source_airport_id",
    "ident": "airport_ident",
    "type": "airport_type",
    "name": "airport_name",
    "latitude_deg": "latitude",
    "longitude_deg": "longitude",
    "elevation_ft": "elevation_ft",
    "continent": "continent",
    "iso_country": "country_code",
    "iso_region": "region_code",
    "municipality": "municipality",
    "scheduled_service": "scheduled_service",
    "icao_code": "icao_code",
    "iata_code": "iata_code",
    "gps_code": "gps_code",
    "local_code": "local_code",
    "home_link": "home_link",
    "wikipedia_link": "wikipedia_link",
    "keywords": "keywords",
}

REQUIRED_SOURCE_COLUMNS = ("id", "ident", "latitude_deg", "longitude_deg")

UPPERCASE_CODE_COLUMNS = (
    "airport_ident",
    "continent",
    "country_code",
    "region_code",
    "icao_code",
    "iata_code",
    "gps_code",
    "local_code",
)

SCHEDULED_SERVICE_MAP = {"yes": True, "no": False}

REJECTED_REASON_COLUMN = "rejection_reason"


@dataclass
class AirportCleaningResult:
    """Output of :func:`clean_airports`."""

    cleaned: pd.DataFrame
    rejected: pd.DataFrame
    source_record_count: int
    duplicate_count: int
    missing_source_columns: list[str] = field(default_factory=list)
    unmapped_source_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def read_raw_airports(path: Path) -> pd.DataFrame:
    """Read the raw CSV with every field as text and no NA inference.

    ``keep_default_na=False`` is essential: OurAirports uses ``NA`` as the
    continent code for North America, which pandas would otherwise turn into NaN.
    """
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8")


def _blank_to_na(series: pd.Series) -> pd.Series:
    """Strip whitespace and convert empty strings to missing values."""
    stripped = series.astype("string").str.strip()
    return stripped.mask(stripped == "", pd.NA)


def clean_airports(raw: pd.DataFrame) -> AirportCleaningResult:
    """Normalize a raw OurAirports frame.

    Steps: map known columns (unknown ones are retained unchanged), strip
    whitespace, uppercase aviation codes, coerce numeric fields, map
    ``scheduled_service`` to a nullable Boolean, reject duplicate source ids and
    rows with missing/invalid identifiers or coordinates.

    Args:
        raw: Frame as returned by :func:`read_raw_airports`.

    Returns:
        :class:`AirportCleaningResult` with cleaned and rejected rows.
    """
    missing_required = [c for c in REQUIRED_SOURCE_COLUMNS if c not in raw.columns]
    if missing_required:
        raise ValueError(f"Raw airport data is missing required columns: {missing_required}")

    missing_optional = [c for c in COLUMN_MAPPING if c not in raw.columns]
    unmapped = [c for c in raw.columns if c not in COLUMN_MAPPING]
    warnings: list[str] = []
    if missing_optional:
        warnings.append(f"Source columns not present (left NULL): {missing_optional}")
    if unmapped:
        warnings.append(f"Unmapped source columns retained as-is: {unmapped}")

    df = raw.rename(columns=COLUMN_MAPPING).copy()
    for column in COLUMN_MAPPING.values():
        if column not in df.columns:
            df[column] = pd.NA
    for column in df.columns:
        df[column] = _blank_to_na(df[column])

    for column in UPPERCASE_CODE_COLUMNS:
        df[column] = df[column].str.upper()
    df["airport_type"] = df["airport_type"].str.lower()

    raw_lat, raw_lon = df["latitude"], df["longitude"]
    df["latitude"] = pd.to_numeric(raw_lat, errors="coerce").astype("Float64")
    df["longitude"] = pd.to_numeric(raw_lon, errors="coerce").astype("Float64")
    elevation = pd.to_numeric(df["elevation_ft"], errors="coerce")
    bad_elevation = df["elevation_ft"].notna() & elevation.isna()
    if bad_elevation.any():
        warnings.append(f"{int(bad_elevation.sum())} non-numeric elevation values set to NULL")
    df["elevation_ft"] = elevation.astype("Float64")

    service = df["scheduled_service"].str.lower()
    unknown_service = service.notna() & ~service.isin(list(SCHEDULED_SERVICE_MAP))
    if unknown_service.any():
        warnings.append(
            f"{int(unknown_service.sum())} unrecognised scheduled_service values set to NULL"
        )
    df["scheduled_service"] = service.map(SCHEDULED_SERVICE_MAP).astype("boolean")

    source_id_numeric = pd.to_numeric(df["source_airport_id"], errors="coerce")

    reasons = pd.Series(pd.NA, index=df.index, dtype="string")

    def flag(mask: pd.Series, reason: str) -> None:
        nonlocal reasons
        reasons = reasons.mask(mask.fillna(False) & reasons.isna(), reason)

    flag(source_id_numeric.isna() | (source_id_numeric % 1 != 0), "invalid_source_airport_id")
    flag(df["airport_ident"].isna(), "missing_airport_ident")
    flag(raw_lat.isna() | raw_lon.isna(), "missing_coordinates")
    flag(df["latitude"].isna() | df["longitude"].isna(), "non_numeric_coordinates")
    flag(~df["latitude"].between(-90, 90), "latitude_out_of_range")
    flag(~df["longitude"].between(-180, 180), "longitude_out_of_range")

    duplicated = df["source_airport_id"].duplicated(keep="first") & df["source_airport_id"].notna()
    duplicate_count = int(duplicated.sum())
    flag(duplicated, "duplicate_source_airport_id")

    rejected_mask = reasons.notna()
    rejected = raw.loc[rejected_mask].copy()
    rejected[REJECTED_REASON_COLUMN] = reasons[rejected_mask]

    cleaned = df.loc[~rejected_mask].copy()
    cleaned["source_airport_id"] = source_id_numeric[~rejected_mask].astype("int64")
    ordered = list(COLUMN_MAPPING.values()) + [c for c in cleaned.columns if c not in COLUMN_MAPPING.values()]
    cleaned = cleaned[ordered].sort_values("source_airport_id").reset_index(drop=True)

    logger.info(
        "airports_cleaned",
        extra={
            "source_records": len(raw),
            "cleaned_records": len(cleaned),
            "rejected_records": int(rejected_mask.sum()),
            "duplicates": duplicate_count,
        },
    )
    return AirportCleaningResult(
        cleaned=cleaned,
        rejected=rejected.reset_index(drop=True),
        source_record_count=len(raw),
        duplicate_count=duplicate_count,
        missing_source_columns=missing_optional,
        unmapped_source_columns=unmapped,
        warnings=warnings,
    )


def save_cleaned_airports(result: AirportCleaningResult, output_dir: Path) -> dict[str, Path]:
    """Write cleaned and rejected airports as UTF-8 CSV files.

    CSV is used (rather than Parquet) to avoid adding pyarrow as a dependency;
    the cleaned file is fully reproducible from the preserved raw snapshot.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "cleaned": output_dir / "airports_clean.csv",
        "rejected": output_dir / "airports_rejected.csv",
    }
    result.cleaned.to_csv(paths["cleaned"], index=False)
    result.rejected.to_csv(paths["rejected"], index=False)
    logger.info("airports_saved", extra={k: str(v) for k, v in paths.items()})
    return paths
