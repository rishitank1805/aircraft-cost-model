"""ECB euro foreign exchange reference rates (dataset EXR, daily, SP00, average).

Verified 2026-10-15: ``https://data-api.ecb.europa.eu/service/data/EXR/D.<CCY>.EUR.SP00.A?format=csvdata``
returns CSV without an API key. Each row's ``CURRENCY`` per 1 ``CURRENCY_DENOM``
(EUR), e.g. ``US dollar/Euro ECB reference exchange rate`` 1.0304 = 1 EUR is
1.0304 USD. No observations on weekends and TARGET holidays.

ECB terms: free use provided the ECB is cited as the source; the reference
rates are published for information purposes only.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from aircraft_cost_model.config import ECB_EXR_API_URL
from aircraft_cost_model.costs.currency import normalize_currency
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.database import SourceMetadata, register_data_source, upsert_rows
from aircraft_cost_model.ingestion.snapshots import RawSnapshot, download_snapshot, latest_snapshot
from aircraft_cost_model.models import ExchangeRate
from aircraft_cost_model.validation.cost_validator import RowValidation, validate_observations

logger = logging.getLogger(__name__)

PREFIX = "ecb_exr_daily"
REQUIRED_COLUMNS = ("KEY", "FREQ", "CURRENCY", "CURRENCY_DENOM", "EXR_TYPE", "EXR_SUFFIX", "TIME_PERIOD",
                    "OBS_VALUE", "UNIT_MULT")
LICENSE = ("ECB: free use provided the ECB is cited as the source and information appears accurately; "
           "reference rates are for information purposes only. https://www.ecb.europa.eu/services/disclaimer/html/index.en.html")


@dataclass
class ParsedRates:
    rows: list[dict[str, Any]]
    skipped_missing: int = 0
    currencies: list[str] = field(default_factory=list)


def download_ecb_rates(raw_dir: Path, currencies: list[str], start: str, timeout: tuple[float, float],
                       session=None) -> RawSnapshot:
    codes = sorted({normalize_currency(c) for c in currencies} - {"EUR"})
    url = ECB_EXR_API_URL.format(currencies="+".join(codes))
    return download_snapshot(url, raw_dir, PREFIX, ".csv", timeout=timeout, session=session,
                             params={"format": "csvdata", "startPeriod": start})


def latest_ecb_snapshot(raw_dir: Path) -> RawSnapshot | None:
    return latest_snapshot(raw_dir, PREFIX, ".csv")


def parse_ecb_csv(path: Path) -> ParsedRates:
    """Parse ECB SDMX CSV; every row must be a daily EUR-denominated reference rate (SP00/A, UNIT_MULT 0)."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SourceSchemaError(f"{path.name}: missing columns {missing}")
        rows, skipped = [], 0
        for line in reader:
            if (line["FREQ"], line["CURRENCY_DENOM"], line["EXR_TYPE"], line["EXR_SUFFIX"], line["UNIT_MULT"]) != \
                    ("D", "EUR", "SP00", "A", "0"):
                raise SourceSchemaError(f"{path.name}: unexpected series {line['KEY']}")
            value = line["OBS_VALUE"].strip()
            if value in ("", "NaN"):
                skipped += 1
                continue
            try:
                rate = Decimal(value)
            except InvalidOperation:
                rate = None
            rows.append({"observation_date": date.fromisoformat(line["TIME_PERIOD"]), "base_currency": "EUR",
                         "quote_currency": normalize_currency(line["CURRENCY"]), "rate": rate, "series_key": line["KEY"]})
    return ParsedRates(rows, skipped, sorted({r["quote_currency"] for r in rows}))


def validate_rates(parsed: ParsedRates) -> RowValidation:
    result = validate_observations(parsed.rows, key_fields=("base_currency", "quote_currency", "observation_date"),
                                   value_field="rate")
    if parsed.skipped_missing:
        result.warnings.append(f"{parsed.skipped_missing} empty observations skipped (not interpolated)")
    return result


def load_exchange_rates(engine: Engine, parsed: ParsedRates, validation: RowValidation,
                        snapshot: RawSnapshot) -> tuple[int, int, int]:
    if not validation.passed:
        raise SourceSchemaError("; ".join(validation.errors))
    retrieved = snapshot.retrieved_at.replace(tzinfo=None)
    with Session(engine) as session, session.begin():
        source_id = register_data_source(session, SourceMetadata(
            source_name="European Central Bank (ECB)",
            source_url=snapshot.source_url,
            dataset_name="ecb_exr_daily_reference_rates",
            license=LICENSE,
            access_type="ECB Data Portal API (SDMX CSV)",
            retrieved_at=snapshot.retrieved_at,
            source_version=f"sha256:{snapshot.sha256[:12]}",
            checksum=snapshot.sha256,
            notes=f"EXR.D.<CCY>.EUR.SP00.A for {parsed.currencies}; quote = currency units per 1 EUR; "
                  f"raw file {snapshot.path.name}",
        ))
        records = [{**r, "source_id": source_id, "retrieved_at": retrieved} for r in validation.valid]
        inserted, updated = upsert_rows(session, ExchangeRate, ("base_currency", "quote_currency", "observation_date"),
                                        records, compare_exclude=("source_id", "retrieved_at"))
    unchanged = len(records) - inserted - updated
    logger.info("exchange_rates_loaded", extra={"inserted": inserted, "updated": updated, "unchanged": unchanged})
    return inserted, updated, unchanged
