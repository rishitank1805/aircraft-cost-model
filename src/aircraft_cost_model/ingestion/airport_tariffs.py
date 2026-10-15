"""Reviewed tariff reference data: navigation unit rates and airport tariffs (local files).

En-route and terminal navigation unit rates and terminal charging-zone
aerodrome lists are transcribed from official documents (EUROCONTROL
circulars, DFS notice) into ``data/local/navigation_rates/`` (git-ignored):
EUROCONTROL permits reproduction only for non-commercial purposes and the
project is treated as potentially commercial, so the values are not
redistributed. ``data/reference/navigation_rate_sources.csv`` records the
documents, checksums and verification status without values.

Airport tariff parameters are transcribed from airport operators' published
charge documents into JSON files under ``data/local/airport_tariffs/``. That
directory is git-ignored: the documents' reuse terms are not stated, so the
transcribed values are used locally and not redistributed. Each file records
its source document, sections, checksum and review status, and is validated by
the rule implementation before loading.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.costs.landing_cost import RULES
from aircraft_cost_model.database import SourceMetadata, register_data_source, upsert_rows
from aircraft_cost_model.models import Airport, AirportTariff, NavigationRate, NavigationZoneAerodrome
from aircraft_cost_model.validation.cost_validator import RowValidation, validate_navigation_rate_rows

logger = logging.getLogger(__name__)

NAV_COLUMNS = ("charge_type", "charging_zone", "charging_zone_name", "valid_from", "valid_to", "national_unit_rate",
               "unit_rate", "currency", "service_unit_formula", "charged_movement", "source_document", "source_url",
               "source_section", "publication_date", "extraction_method", "verification_status", "notes")
ZONE_COLUMNS = ("charging_zone", "aerodrome_icao", "valid_from", "valid_to", "source_url")
NAV_RATES_FILE = "navigation_unit_rates.csv"
NAV_ZONES_FILE = "terminal_zone_aerodromes.csv"
EUROCONTROL_LICENSE = ("(c) EUROCONTROL. Reproduction authorised for non-commercial purposes provided the source is "
                       "acknowledged; commercial use requires written permission "
                       "(https://www.eurocontrol.int/info/privacy-and-website-terms-use).")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value) if value else None
    except InvalidOperation:
        return None


def read_navigation_rates(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in NAV_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SourceSchemaError(f"{path.name}: missing columns {missing}")
        return [{
            "charge_type": row["charge_type"].strip(),
            "service_unit_formula": row["service_unit_formula"].strip(),
            "charged_movement": row["charged_movement"].strip() or None,
            "charging_zone": row["charging_zone"].strip().upper(),
            "charging_zone_name": row["charging_zone_name"].strip(),
            "valid_from": date.fromisoformat(row["valid_from"]),
            "valid_to": date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
            "national_unit_rate": _decimal(row["national_unit_rate"]),
            "unit_rate": _decimal(row["unit_rate"]),
            "currency": row["currency"].strip().upper(),
            "source_reference": f"{row['source_document']}, {row['source_section']} ({row['source_url']}); "
                                f"extraction: {row['extraction_method']}"
                                + (f"; notes: {row['notes']}" if row.get("notes") else ""),
            "verification_status": row["verification_status"].strip(),
        } for row in reader]


def read_zone_aerodromes(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in ZONE_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SourceSchemaError(f"{path.name}: missing columns {missing}")
        rows = [{
            "charging_zone": row["charging_zone"].strip().upper(),
            "aerodrome_icao": row["aerodrome_icao"].strip().upper(),
            "valid_from": date.fromisoformat(row["valid_from"]),
            "valid_to": date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
        } for row in reader]
    for row in rows:
        if len(row["aerodrome_icao"]) != 4 or not row["aerodrome_icao"].isalpha():
            raise SourceSchemaError(f"{path.name}: invalid ICAO code {row['aerodrome_icao']!r}")
    return rows


def load_navigation_rates(engine: Engine, directory: Path) -> tuple[RowValidation, tuple[int, int], int]:
    """Load ``navigation_unit_rates.csv`` and ``terminal_zone_aerodromes.csv`` from ``directory``.

    Returns ``(validation, (inserted, updated), zone_rows)``.
    """
    rates_path, zones_path = directory / NAV_RATES_FILE, directory / NAV_ZONES_FILE
    if not rates_path.is_file():
        raise SourceSchemaError(f"{rates_path} not found (local, git-ignored file; see docs/cost_data_sources.md)")
    rows = read_navigation_rates(rates_path)
    validation = validate_navigation_rate_rows(rows)
    if not validation.passed:
        raise SourceSchemaError("; ".join(validation.errors))
    zones = read_zone_aerodromes(zones_path) if zones_path.is_file() else []
    terminal_zones = {r["charging_zone"] for r in validation.valid if r["charge_type"] == "terminal"}
    unknown = sorted({z["charging_zone"] for z in zones} - terminal_zones)
    if unknown:
        raise SourceSchemaError(f"Aerodrome list references zones without terminal rates: {unknown}")
    checksum = hashlib.sha256(rates_path.read_bytes() + (zones_path.read_bytes() if zones_path.is_file() else b"")).hexdigest()
    with Session(engine) as session, session.begin():
        source_id = register_data_source(session, SourceMetadata(
            source_name="EUROCONTROL CRCO / DFS (navigation unit rates)",
            source_url="https://www.eurocontrol.int/crco",
            dataset_name="navigation_unit_rates_local_transcription",
            license=EUROCONTROL_LICENSE + " DFS notice: reuse terms not stated.",
            access_type="Manual transcription of official PDFs into local, git-ignored CSV (data/local/navigation_rates/)",
            retrieved_at=datetime.now(timezone.utc).replace(microsecond=0),
            source_version=f"sha256:{checksum[:12]}",
            checksum=checksum,
            notes="En-route global unit rates and terminal unit rates; per-row document references in source_reference.",
        ))
        records = [{**r, "source_id": source_id} for r in validation.valid]
        counts = upsert_rows(session, NavigationRate, ("charging_zone", "valid_from"), records)
        upsert_rows(session, NavigationZoneAerodrome, ("charging_zone", "aerodrome_icao", "valid_from"),
                    [{**z, "source_id": source_id} for z in zones])
    return validation, counts, len(zones)


def read_tariff_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("airport_ident", "tariff_type", "valid_from", "currency", "calculation_method", "parameters",
                "source", "verification_status"):
        if key not in data:
            raise SourceSchemaError(f"{path.name}: missing {key!r}")
    rule = RULES.get(data["calculation_method"])
    if rule is None and data["tariff_type"] == "landing_takeoff":
        raise SourceSchemaError(f"{path.name}: no rule implementation for {data['calculation_method']!r}")
    if rule is not None:
        try:
            rule.validate_parameters(data["parameters"])
        except (ValueError, KeyError) as exc:
            raise SourceSchemaError(f"{path.name}: invalid parameters: {exc}") from exc
    return data


def load_airport_tariffs(engine: Engine, directory: Path) -> list[tuple[str, int, int]]:
    """Load every ``*.json`` tariff file in ``directory``; returns ``(file, inserted, updated)`` per file."""
    results = []
    for path in sorted(directory.glob("*.json")):
        data = read_tariff_file(path)
        source = data["source"]
        checksum = _sha256(path)
        with Session(engine) as session, session.begin():
            airport_id = session.scalar(select(Airport.airport_id).where(Airport.airport_ident == data["airport_ident"]))
            if airport_id is None:
                raise SourceSchemaError(f"{path.name}: airport {data['airport_ident']} not in airport table")
            source_id = register_data_source(session, SourceMetadata(
                source_name=source["publisher"],
                source_url=source["url"],
                dataset_name=f"airport_tariff_{data['airport_ident']}_{data['tariff_type']}",
                license=source.get("terms"),
                access_type="Manual transcription of official tariff document (local, not redistributed)",
                retrieved_at=datetime.fromisoformat(source["retrieved"]),
                source_version=f"{source['title']} valid from {data['valid_from']}",
                checksum=checksum,
                notes=f"Document sha256 {source.get('document_sha256')}; sections {source.get('sections')}; "
                      f"pages {source.get('pages')}; local file {path.name}",
            ))
            record = {
                "airport_id": airport_id, "tariff_type": data["tariff_type"],
                "valid_from": date.fromisoformat(data["valid_from"]),
                "valid_to": date.fromisoformat(data["valid_to"]) if data.get("valid_to") else None,
                "source_id": source_id, "currency": data["currency"].upper(),
                "calculation_method": data["calculation_method"],
                "parameters_json": json.dumps(data["parameters"], sort_keys=True),
                "source_reference": f"{source['title']} ({source['url']}), sections {source.get('sections')}, "
                                    f"pages {source.get('pages')}",
                "verification_status": data["verification_status"],
            }
            inserted, updated = upsert_rows(session, AirportTariff, ("airport_id", "tariff_type", "valid_from"), [record])
        results.append((path.name, inserted, updated))
    return results
