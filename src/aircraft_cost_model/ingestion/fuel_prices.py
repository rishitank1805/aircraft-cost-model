"""EIA U.S. Gulf Coast kerosene-type jet fuel spot price (series EER_EPJK_PF4_RGC_DPG).

Verified 2026-10-15:

- XLS download (no API key): ``https://www.eia.gov/dnav/pet/hist_xls/EER_EPJK_PF4_RGC_DPGd.xls``.
  Sheet ``Data 1``: row 2 ``Sourcekey | EER_EPJK_PF4_RGC_DPG``; row 3 header
  ``U.S. Gulf Coast Kerosene-Type Jet Fuel Spot Price FOB (Dollars per Gallon)``;
  then daily rows (Excel date, value). Coverage 1990-04-02 onwards.
- API v2 (``https://api.eia.gov/v2/petroleum/pri/spt/data/``) requires a free
  API key (``ACM_EIA_API_KEY``); without one it returns ``API_KEY_MISSING``.
- EIA content is U.S. government work in the public domain; EIA asks for
  attribution ("Source: U.S. Energy Information Administration").

This is a public spot-market benchmark (FOB U.S. Gulf Coast), not an airline
contract or into-plane price.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from aircraft_cost_model.config import EIA_API_V2_URL, EIA_JET_FUEL_SERIES, EIA_JET_FUEL_XLS_URL
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.database import SourceMetadata, register_data_source, upsert_rows
from aircraft_cost_model.ingestion.snapshots import RawSnapshot, download_snapshot, latest_snapshot
from aircraft_cost_model.models import FuelPrice
from aircraft_cost_model.validation.cost_validator import RowValidation, validate_observations

logger = logging.getLogger(__name__)

DESCRIPTION = "U.S. Gulf Coast Kerosene-Type Jet Fuel Spot Price FOB (Dollars per Gallon)"
UNIT_LABEL = "(Dollars per Gallon)"
PRICE_UNIT = "USD/USgal"
CURRENCY = "USD"
MARKET_LOCATION = "U.S. Gulf Coast, FOB"
PRODUCT = "Kerosene-type jet fuel"
PERIOD_DAILY = "daily"
XLS_PREFIX = f"eia_{EIA_JET_FUEL_SERIES}_daily"
API_PREFIX = f"eia_api_{EIA_JET_FUEL_SERIES}_daily"
LICENSE = ("U.S. government work, public domain. EIA requests attribution: 'Source: U.S. Energy Information "
           "Administration'. https://www.eia.gov/about/copyrights_reuse.php")


@dataclass
class ParsedFuelPrices:
    series_identifier: str
    description: str
    rows: list[dict[str, Any]]
    blank_observations: int = 0
    notes: list[str] = field(default_factory=list)


def download_eia_xls(raw_dir: Path, timeout: tuple[float, float], session=None) -> RawSnapshot:
    """Download the public XLS (no key) as an immutable snapshot."""
    return download_snapshot(EIA_JET_FUEL_XLS_URL, raw_dir, XLS_PREFIX, ".xls", timeout=timeout, session=session)


def download_eia_api(raw_dir: Path, api_key: str, start: str, timeout: tuple[float, float], session=None) -> RawSnapshot:
    """Download the series via API v2 (key required; the key is redacted from logs and metadata)."""
    params = {
        "api_key": api_key, "frequency": "daily", "data[0]": "value", "facets[series][]": EIA_JET_FUEL_SERIES,
        "start": start, "sort[0][column]": "period", "sort[0][direction]": "asc", "length": "5000",
    }
    return download_snapshot(EIA_API_V2_URL, raw_dir, API_PREFIX, ".json", timeout=timeout, session=session,
                             params=params, redact_params=("api_key",))


def latest_eia_snapshot(raw_dir: Path) -> RawSnapshot | None:
    return latest_snapshot(raw_dir, XLS_PREFIX, ".xls") or latest_snapshot(raw_dir, API_PREFIX, ".json")


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value)) if not isinstance(value, float) else Decimal(repr(value))
    except InvalidOperation:
        return None
    return number


def parse_eia_xls(path: Path) -> ParsedFuelPrices:
    """Parse the EIA XLS, checking series key and unit label (schema change -> :class:`SourceSchemaError`)."""
    import xlrd

    book = xlrd.open_workbook(str(path))
    if "Data 1" not in book.sheet_names():
        raise SourceSchemaError(f"{path.name}: sheet 'Data 1' not found ({book.sheet_names()})")
    sheet = book.sheet_by_name("Data 1")
    if sheet.nrows < 4 or sheet.cell_value(1, 0) != "Sourcekey":
        raise SourceSchemaError(f"{path.name}: unexpected header layout")
    series = str(sheet.cell_value(1, 1)).strip()
    header = str(sheet.cell_value(2, 1)).strip()
    if series != EIA_JET_FUEL_SERIES:
        raise SourceSchemaError(f"{path.name}: series {series!r}, expected {EIA_JET_FUEL_SERIES!r}")
    if UNIT_LABEL not in header:
        raise SourceSchemaError(f"{path.name}: unit label changed: {header!r}")
    rows, blanks = [], 0
    for r in range(3, sheet.nrows):
        date_cell, value_cell = sheet.cell(r, 0), sheet.cell(r, 1)
        if date_cell.ctype != xlrd.XL_CELL_DATE:
            raise SourceSchemaError(f"{path.name}: row {r + 1} has a non-date first column")
        obs = xlrd.xldate_as_datetime(date_cell.value, book.datemode).date()
        if value_cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
            blanks += 1
            continue
        price = _decimal(value_cell.value) if value_cell.ctype == xlrd.XL_CELL_NUMBER else None
        rows.append({"observation_date": obs, "price": price, "price_unit": PRICE_UNIT})
    return ParsedFuelPrices(series, header, rows, blanks)


def parse_eia_api_json(path: Path) -> ParsedFuelPrices:
    """Parse an API v2 JSON snapshot (``response.data`` with ``period``, ``value``, ``units``, ``series``)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "error" in payload:
        raise SourceSchemaError(f"EIA API error: {payload['error']}")
    data = payload.get("response", {}).get("data")
    if data is None:
        raise SourceSchemaError("EIA API response has no response.data")
    rows, blanks = [], 0
    for item in data:
        if item.get("series") != EIA_JET_FUEL_SERIES:
            raise SourceSchemaError(f"Unexpected series {item.get('series')!r}")
        if item.get("units") != "$/GAL":
            raise SourceSchemaError(f"Unexpected units {item.get('units')!r}")
        if item.get("value") in (None, ""):
            blanks += 1
            continue
        rows.append({"observation_date": date.fromisoformat(item["period"]), "price": _decimal(item["value"]),
                     "price_unit": PRICE_UNIT})
    total = int(payload.get("response", {}).get("total", len(data)))
    notes = [f"API returned {len(data)} of {total} rows"] if total > len(data) else []
    return ParsedFuelPrices(EIA_JET_FUEL_SERIES, DESCRIPTION, rows, blanks, notes)


def parse_snapshot(snapshot: RawSnapshot) -> ParsedFuelPrices:
    return parse_eia_api_json(snapshot.path) if snapshot.path.suffix == ".json" else parse_eia_xls(snapshot.path)


def validate_fuel_prices(parsed: ParsedFuelPrices) -> RowValidation:
    result = validate_observations(parsed.rows, key_fields=("observation_date",), value_field="price",
                                   unit_field="price_unit", expected_unit=PRICE_UNIT)
    if parsed.blank_observations:
        result.warnings.append(f"{parsed.blank_observations} dates without a published value were skipped "
                               "(not interpolated)")
    return result


def source_metadata(snapshot: RawSnapshot) -> SourceMetadata:
    return SourceMetadata(
        source_name="U.S. Energy Information Administration (EIA)",
        source_url=snapshot.source_url,
        dataset_name=f"eia_{EIA_JET_FUEL_SERIES}_daily",
        license=LICENSE,
        access_type="HTTP download (XLS)" if snapshot.path.suffix == ".xls" else "EIA API v2 (JSON, API key)",
        retrieved_at=snapshot.retrieved_at,
        source_version=snapshot.last_modified or f"sha256:{snapshot.sha256[:12]}",
        checksum=snapshot.sha256,
        notes=f"Series {EIA_JET_FUEL_SERIES}: {DESCRIPTION}; daily spot assessments; raw file {snapshot.path.name}. "
              "Public market benchmark, not an airline contract or into-plane price.",
    )


def load_fuel_prices(engine: Engine, parsed: ParsedFuelPrices, validation: RowValidation,
                     snapshot: RawSnapshot) -> tuple[int, int, int]:
    """Register the source and upsert valid observations in one transaction. Returns (inserted, updated, unchanged)."""
    if not validation.passed:
        raise SourceSchemaError("; ".join(validation.errors))
    retrieved = snapshot.retrieved_at.replace(tzinfo=None)
    with Session(engine) as session, session.begin():
        source_id = register_data_source(session, source_metadata(snapshot))
        records = [{
            "series_identifier": parsed.series_identifier, "observation_period": PERIOD_DAILY,
            "observation_date": r["observation_date"], "source_id": source_id, "market_location": MARKET_LOCATION,
            "product": PRODUCT, "price": r["price"], "currency": CURRENCY, "price_unit": r["price_unit"],
            "retrieved_at": retrieved,
        } for r in validation.valid]
        inserted, updated = upsert_rows(session, FuelPrice,
                                        ("series_identifier", "observation_period", "observation_date"),
                                        records, compare_exclude=("source_id", "retrieved_at"))
    unchanged = len(records) - inserted - updated
    logger.info("fuel_prices_loaded", extra={"inserted": inserted, "updated": updated, "unchanged": unchanged})
    return inserted, updated, unchanged
