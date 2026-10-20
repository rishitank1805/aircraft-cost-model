"""Additive loading of aircraft specification values with provenance (Part 6).

Sources (each value keeps its own source, unit, source type and verification status):

1. **OpenAP aircraft data** (already preserved as the Part 1 raw snapshot
   ``data/raw/aircraft/openap_aircraft_*.json``; GPL-3.0 data): fuselage and
   wing geometry, ceiling, nominal cruise range, seating, engine options,
   MMO/VMO. Source type ``open_model_data``: model parameters, *not*
   certified specifications. OpenAP's *fuselage* length/height are not the
   overall aircraft length/height and are stored under their own keys.
2. **OpenAP ``engines.csv``** (ICAO Aircraft Engine Emissions Databank values
   as distributed by OpenAP): rated thrust, bypass ratio and pressure ratio of
   each aircraft's default engine. Source type ``engine_databank``.
3. **FAA Aircraft Characteristics Database** (public domain, U.S.
   Government): overall length, wingspan, tail height at OEW, wheelbase, main
   gear width, MTOW, maximum allowable landing weight, approach speed, design
   group, wake category. Matched by ICAO type designator for the OpenAP types.
   Freighters are matched **only** where the FAA row explicitly includes the
   freighter (B77L "Boeing 777-200LRF/LR" for the 777F, flagged as a shared
   row); passenger rows are never used as freighter specifications.
4. **FAA Economic Values Tables 4-16/4-17** (public domain): documented
   narrowbody / widebody / regional-jet classification
   (``data/reference/aircraft_body_class_faa.csv``).
5. **Curated freighter facts** transcribed from manufacturer and
   conversion-provider web pages with URL and retrieval date
   (``data/reference/freighter_programs.csv``,
   ``data/reference/freighter_published_specs.csv``).

Values are stored in SI units (exact conversions: 1 ft = 0.3048 m,
1 lb = 0.45359237 kg, 1 in = 0.0254 m) with the original value and unit.
Loading is insert-only per (aircraft, specification, source): re-running
inserts nothing; a new source version adds rows and never overwrites.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from aircraft_cost_model.database import SourceMetadata, register_data_source
from aircraft_cost_model.ingestion.snapshots import RawSnapshot, download_snapshot, latest_snapshot
from aircraft_cost_model.models import AircraftSpecification, AircraftType, DataSource
from aircraft_cost_model.models.base import utc_now

logger = logging.getLogger(__name__)

FT = Decimal("0.3048")
LB = Decimal("0.45359237")
FAA_ACD_URL = "https://www.faa.gov/airports/engineering/aircraft_char_database/aircraft_data"
FAA_ACD_PAGE = "https://www.faa.gov/airports/engineering/aircraft_char_database"
FAA_LICENSE = "U.S. Government work (public domain); FAA Office of Airports, Aircraft Characteristics Database"
FREIGHTER_ROW_MAPPING = {
    # freighter code -> (FAA ICAO_Code, required text in Model_FAA proving the row includes the freighter)
    "B777F": ("B77L", "777-200LRF"),
}


@dataclass
class SpecRow:
    aircraft_code: str
    spec_key: str
    section: str
    value_decimal: Decimal | None = None
    value_text: str | None = None
    unit: str | None = None
    original_value: str | None = None
    original_unit: str | None = None
    source_type: str = "open_model_data"
    source_reference: str | None = None
    verification_status: str = "as_published"
    variant: str | None = None
    condition: str | None = None
    notes: str | None = None


def _dec(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "n/a"):
        return None
    try:
        return Decimal(text.replace(",", ""))
    except Exception:
        return None


def insert_specs(engine: Engine, source_id: int, rows: list[SpecRow]) -> tuple[int, int, list[str]]:
    """Insert rows for known aircraft codes; returns (inserted, already_present, unknown_codes)."""
    with Session(engine) as session, session.begin():
        ids = {code: i for i, code in session.execute(select(AircraftType.aircraft_type_id, AircraftType.aircraft_code))}
        before = session.query(AircraftSpecification).filter_by(source_id=source_id).count()
        unknown = sorted({r.aircraft_code for r in rows if r.aircraft_code not in ids})
        records = []
        for r in rows:
            if r.aircraft_code not in ids or (r.value_decimal is None and not r.value_text):
                continue
            records.append({
                "aircraft_type_id": ids[r.aircraft_code], "spec_key": r.spec_key, "section": r.section,
                "value_decimal": None if r.value_decimal is None else str(r.value_decimal), "value_text": r.value_text,
                "unit": r.unit, "original_value": r.original_value, "original_unit": r.original_unit,
                "source_id": source_id, "source_type": r.source_type, "source_reference": r.source_reference,
                "verification_status": r.verification_status, "variant": r.variant, "condition": r.condition,
                "notes": r.notes, "created_at": utc_now()})
        for start in range(0, len(records), 500):
            session.execute(sqlite_insert(AircraftSpecification.__table__).on_conflict_do_nothing(),
                            records[start:start + 500])
        after = session.query(AircraftSpecification).filter_by(source_id=source_id).count()
    return after - before, len(records) - (after - before), unknown


# ---------------------------------------------------------------------------
# 1. OpenAP aircraft data (preserved Part 1 snapshot)
# ---------------------------------------------------------------------------

OPENAP_FIELDS = (
    # key, section, path, unit, notes
    ("fuselage_length_m", "dimensions", ("fuselage", "length"), "m", "Fuselage length (OpenAP); not the overall aircraft length"),
    ("fuselage_width_m", "dimensions", ("fuselage", "width"), "m", "Fuselage width (OpenAP)"),
    ("fuselage_height_m", "dimensions", ("fuselage", "height"), "m",
     "Fuselage height (OpenAP); NOT the overall aircraft height (tail height)"),
    ("wingspan_m", "dimensions", ("wing", "span"), "m", "Wing span (OpenAP model parameter)"),
    ("wing_area_m2", "dimensions", ("wing", "area"), "m2", "Reference wing area (OpenAP)"),
    ("wing_sweep_deg", "dimensions", ("wing", "sweep"), "deg", "Wing sweep (OpenAP)"),
    ("wing_mac_m", "dimensions", ("wing", "mac"), "m", "Mean aerodynamic chord (OpenAP)"),
    ("ceiling_m", "performance", ("ceiling",), "m", "Maximum operating altitude (OpenAP)"),
    ("nominal_cruise_range_km", "performance", ("cruise", "range"), "km",
     "OpenAP nominal cruise range; payload and reserve conditions not stated - not a payload-range point"),
    ("mmo", "performance", ("mmo",), "Mach", "Maximum operating Mach number (OpenAP)"),
    ("vmo_kt", "performance", ("vmo",), "kt", "Maximum operating speed (OpenAP)"),
    ("max_seats", "capacity", ("pax", "max"), "seats", "Maximum passenger seats (OpenAP)"),
    ("typical_seats_high", "capacity", ("pax", "high"), "seats", "Typical high-density seating (OpenAP)"),
    ("typical_seats_low", "capacity", ("pax", "low"), "seats", "Typical low-density seating (OpenAP)"),
)


def openap_rows(records: dict[str, dict]) -> list[SpecRow]:
    rows: list[SpecRow] = []
    for code, rec in records.items():
        variant = rec.get("aircraft")
        for key, section, path, unit, notes in OPENAP_FIELDS:
            value: Any = rec
            for part in path:
                value = value.get(part) if isinstance(value, dict) else None
            number = _dec(value)
            if number is not None:
                rows.append(SpecRow(code, key, section, number, unit=unit, original_value=str(value),
                                    original_unit=unit, source_type="open_model_data",
                                    source_reference="OpenAP aircraft YAML (openap/data/aircraft)",
                                    verification_status="unverified_model_value", variant=variant, notes=notes))
        engine = rec.get("engine") or {}
        if engine.get("mount"):
            rows.append(SpecRow(code, "engine_mount", "engines", value_text=str(engine["mount"]),
                                source_type="open_model_data", verification_status="unverified_model_value",
                                variant=variant, notes="Engine mounting position (OpenAP)"))
        options = engine.get("options") or {}
        if options:
            text = ("; ".join(f"{k}: {v}" for k, v in sorted(options.items())) if isinstance(options, dict)
                    else "; ".join(str(o) for o in options))
            rows.append(SpecRow(code, "engine_options", "engines", value_text=text, source_type="open_model_data",
                                verification_status="unverified_model_value", variant=variant,
                                notes="Variant -> engine options listed by OpenAP"))
    return rows


def load_openap_specs(engine: Engine, raw_dir: Path) -> tuple[int, int, list[str]]:
    paths = sorted(raw_dir.glob("openap_aircraft_*.json"))
    if not paths:
        raise FileNotFoundError(f"no OpenAP snapshot in {raw_dir}")
    data = json.loads(paths[-1].read_text(encoding="utf-8"))
    with Session(engine) as session:
        source = session.scalar(select(DataSource).where(DataSource.dataset_name == "openap_aircraft_properties",
                                                         DataSource.checksum == data["data_checksum_sha256"]))
    if source is None:
        raise LookupError("the OpenAP snapshot is not registered in data_source (run ingest_aircraft.py first)")
    return insert_specs(engine, source.source_id, openap_rows(data["records"]))


# ---------------------------------------------------------------------------
# 2. OpenAP engines.csv (ICAO Engine Emissions Databank values)
# ---------------------------------------------------------------------------

def load_engine_specs(engine: Engine) -> tuple[int, int, list[str]]:
    import openap

    path = Path(openap.__file__).parent / "data" / "engine" / "engines.csv"
    content = path.read_bytes()
    table = pd.read_csv(path, dtype=str).set_index("name")
    with Session(engine) as session, session.begin():
        source_id = register_data_source(session, SourceMetadata(
            source_name="OpenAP (TU Delft) engine table, ICAO Aircraft Engine Emissions Databank values",
            source_url="https://github.com/TUDelft-CNS-ATM/openap", dataset_name="openap_engines_csv",
            license="OpenAP data GPL-3.0 (ICAO Engine Emissions Databank values)",
            access_type="installed openap package file openap/data/engine/engines.csv", retrieved_at=None,
            source_version=f"openap {openap.__version__}" if hasattr(openap, "__version__") else "openap 2.6.x",
            checksum=hashlib.sha256(content).hexdigest(), notes="per-engine rated output (max_thrust, N), bpr, pr"))
        aircraft = session.execute(select(AircraftType.aircraft_code, AircraftType.engine_model)
                                   .where(AircraftType.engine_model.is_not(None))).all()
    rows: list[SpecRow] = []
    for code, engine_model in aircraft:
        if engine_model not in table.index:
            continue
        r = table.loc[engine_model]
        variant = f"default engine {engine_model}"
        thrust = _dec(r.get("max_thrust"))
        if thrust is not None:
            rows.append(SpecRow(code, "rated_thrust_kn", "engines", thrust / 1000, unit="kN", original_value=str(r["max_thrust"]),
                                original_unit="N", source_type="engine_databank", verification_status="as_published",
                                source_reference="OpenAP engines.csv max_thrust (ICAO EEDB rated output)",
                                variant=variant, notes="Rated (sea-level static) thrust per engine"))
        for key, col, unit, note in (("bypass_ratio", "bpr", "ratio", "Bypass ratio"),
                                     ("overall_pressure_ratio", "pr", "ratio", "Overall pressure ratio")):
            value = _dec(r.get(col))
            if value is not None:
                rows.append(SpecRow(code, key, "engines", value, unit=unit, original_value=str(r[col]),
                                    original_unit=unit, source_type="engine_databank",
                                    verification_status="as_published", variant=variant, notes=note,
                                    source_reference=f"OpenAP engines.csv {col}"))
        if isinstance(r.get("manufacturer"), str):
            rows.append(SpecRow(code, "engine_manufacturer", "engines", value_text=r["manufacturer"],
                                source_type="engine_databank", verification_status="as_published", variant=variant))
    return insert_specs(engine, source_id, rows)


# ---------------------------------------------------------------------------
# 3. FAA Aircraft Characteristics Database
# ---------------------------------------------------------------------------

FAA_FIELDS = (
    # key, section, column, factor, unit, original unit, condition/notes
    ("length_m", "dimensions", "Length_ft", FT, "m", "ft", "Aircraft full length"),
    ("wingspan_m", "dimensions", "Wingspan_ft_without_winglets_sharklets", FT, "m", "ft", "Wingspan without winglets/sharklets"),
    ("wingspan_with_winglets_m", "dimensions", "Wingspan_ft_with_winglets_sharklets", FT, "m", "ft",
     "Wingspan with winglets/sharklets"),
    ("height_m", "dimensions", "Tail_Height_at_OEW_ft", FT, "m", "ft", "Tail height at operating empty weight"),
    ("wheelbase_m", "dimensions", "Wheelbase_ft", FT, "m", "ft", "Wheelbase"),
    ("main_gear_width_m", "dimensions", "Main_Gear_Width_ft", FT, "m", "ft", "Main gear width (outside to outside)"),
    ("mtow_kg", "weights", "MTOW_lb", LB, "kg", "lb", "Maximum takeoff gross weight"),
    ("mlw_kg", "weights", "MALW_lb", LB, "kg", "lb", "Maximum allowable landing weight"),
    ("approach_speed_kt", "performance", "Approach_Speed_knot", Decimal(1), "kt", "kt", "Approach speed"),
    ("engine_count", "engines", "Num_Engines", Decimal(1), "count", "count", "Number of engines"),
)
FAA_TEXT_FIELDS = (("adg", "classification", "ADG", "Airplane Design Group (FAA AC 150/5300-13B)"),
                   ("aac", "classification", "AAC", "Aircraft Approach Category"),
                   ("icao_wtc", "classification", "ICAO_WTC", "ICAO wake turbulence category"),
                   ("main_gear_config", "dimensions", "Main_Gear_Config", "Main gear configuration code"))


def download_faa_acd(raw_dir: Path, timeout: tuple[float, float] = (15.0, 120.0)) -> RawSnapshot:
    return download_snapshot(FAA_ACD_URL, raw_dir, "faa_acd", ".xlsx", timeout=timeout)


def latest_faa_acd(raw_dir: Path) -> RawSnapshot | None:
    return latest_snapshot(raw_dir, "faa_acd", ".xlsx")


def faa_rows(frame: pd.DataFrame, project: dict[str, str | None], freighters: dict[str, tuple[str, str]]
             ) -> list[SpecRow]:
    """``project``: aircraft_code -> ICAO designator for types matched directly (OpenAP-supported)."""
    by_icao = {r["ICAO_Code"]: r for r in frame.to_dict("records") if isinstance(r.get("ICAO_Code"), str)}
    targets: list[tuple[str, dict, str, str | None]] = []
    for code, icao in project.items():
        if icao and icao in by_icao:
            targets.append((code, by_icao[icao], "as_published", None))
    for code, (icao, must_contain) in freighters.items():
        row = by_icao.get(icao)
        if row is not None and must_contain in str(row.get("Model_FAA", "")):
            targets.append((code, row, "shared_designator_row",
                            f"FAA row '{row['Model_FAA']}' covers more than one model; values are not separated by "
                            "variant"))
    rows: list[SpecRow] = []
    for code, r, status, shared in targets:
        variant = f"{r.get('Model_FAA')} (BADA model {r.get('Model_BADA')})"
        reference = f"FAA Aircraft Characteristics Database, ICAO {r['ICAO_Code']}"
        for key, section, column, factor, unit, ounit, note in FAA_FIELDS:
            value = _dec(r.get(column))
            if value is None:
                continue
            rows.append(SpecRow(code, key, section, value * factor, unit=unit, original_value=str(r.get(column)),
                                original_unit=ounit, source_type="published_specification",
                                source_reference=reference, verification_status=status, variant=variant,
                                notes="; ".join(x for x in (note, shared) if x)))
        for key, section, column, note in FAA_TEXT_FIELDS:
            value = r.get(column)
            if isinstance(value, str) and value.strip():
                rows.append(SpecRow(code, key, section, value_text=value.strip(), source_type="published_specification",
                                    source_reference=reference, verification_status=status, variant=variant,
                                    notes="; ".join(x for x in (note, shared) if x)))
    return rows


def load_faa_acd(engine: Engine, snapshot: RawSnapshot) -> tuple[int, int, list[str]]:
    frame = pd.read_excel(snapshot.path, sheet_name="ACD_Data", dtype=str)
    with Session(engine) as session, session.begin():
        source_id = register_data_source(session, SourceMetadata(
            source_name="U.S. Federal Aviation Administration (FAA), Office of Airports", source_url=FAA_ACD_PAGE,
            dataset_name="faa_aircraft_characteristics_database", license=FAA_LICENSE,
            access_type="XLSX download (ACD_Data sheet)", retrieved_at=snapshot.retrieved_at,
            source_version=snapshot.last_modified or f"sha256:{snapshot.sha256[:12]}", checksum=snapshot.sha256,
            notes=f"raw file {snapshot.path.name}; values compiled by FAA from manufacturer manuals"))
        project = dict(session.execute(select(AircraftType.aircraft_code, AircraftType.icao_type_designator)
                                       .where(AircraftType.openap_supported.is_(True))).all())
    return insert_specs(engine, source_id, faa_rows(frame, project, FREIGHTER_ROW_MAPPING))


# ---------------------------------------------------------------------------
# 4/5. Curated reference files
# ---------------------------------------------------------------------------

def _register_reference(session: Session, path: Path, dataset: str, name: str, license_text: str, notes: str) -> int:
    return register_data_source(session, SourceMetadata(
        source_name=name, source_url=None, dataset_name=dataset, license=license_text,
        access_type=f"version-controlled transcription data/reference/{path.name}", retrieved_at=None,
        source_version=f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}",
        checksum=hashlib.sha256(path.read_bytes()).hexdigest(), notes=notes))


def load_body_class(engine: Engine, path: Path) -> tuple[int, int, list[str]]:
    with Session(engine) as session, session.begin():
        source_id = _register_reference(
            session, path, "faa_economic_values_tables_4_16_4_17",
            "FAA Economic Values for FAA Investment and Regulatory Decisions, Section 4, Tables 4-16 and 4-17",
            "U.S. Government work (public domain)",
            "https://www.faa.gov/regulations_policies/policy_guidance/benefit_cost/econ-value-section-4-op-costs.pdf")
    rows = []
    with path.open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            ref = f"FAA Economic Values Section 4, {r['faa_table']}, BTS code {r['bts_code']} ({r['faa_aircraft_type']})"
            rows.append(SpecRow(r["project_aircraft_code"], "body_class", "classification", value_text=r["body_class"],
                                source_type="documented_classification", source_reference=ref,
                                variant=r["faa_aircraft_type"], notes=r["notes"] or None))
            rows.append(SpecRow(r["project_aircraft_code"], "faa_aircraft_category", "classification",
                                value_text=f"passenger: {r['passenger_category']}; all-cargo: {r['all_cargo_category']}",
                                source_type="documented_classification", source_reference=ref,
                                variant=r["faa_aircraft_type"]))
    return insert_specs(engine, source_id, rows)


def load_freighter_reference(engine: Engine, programs: Path, specs: Path) -> tuple[int, int, list[str]]:
    with Session(engine) as session, session.begin():
        source_id = _register_reference(
            session, specs, "curated_freighter_published_specs",
            "Curated transcription of manufacturer and conversion-provider web pages (Airbus, Boeing, EFW)",
            "Facts transcribed with citation from publicly accessible pages; page content (c) the publishers; "
            "no text or images redistributed beyond short attributed quotes",
            f"also {programs.name} (sha256 {hashlib.sha256(programs.read_bytes()).hexdigest()[:12]})")
    rows: list[SpecRow] = []
    with programs.open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            ref = f"{r['source_publisher']}: {r['source_url']} (retrieved {r['retrieved']})"
            for key, value in (("freighter_type", r["freighter_type"]), ("conversion_provider", r["conversion_provider"]),
                               ("base_aircraft", r["base_aircraft"]), ("original_manufacturer", r["original_manufacturer"])):
                if value:
                    rows.append(SpecRow(r["aircraft_code"], key, "cargo", value_text=value,
                                        source_type="published_specification", source_reference=ref,
                                        notes=f"{r['statement']} {r['notes']}".strip()))
    with specs.open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            ref = f"{r['source_publisher']}: {r['source_url']} (retrieved {r['retrieved']})"
            rows.append(SpecRow(r["aircraft_code"], r["spec_key"], r["section"], _dec(r["value"]),
                                value_text=r["value_text"] or None, unit=r["unit"] or None,
                                original_value=r["original_value"] or None, original_unit=r["original_unit"] or None,
                                source_type="published_specification", source_reference=ref,
                                verification_status=r["verification_status"], variant=r["variant"] or None,
                                condition=r["condition"] or None, notes=r["notes"] or None))
    return insert_specs(engine, source_id, rows)
