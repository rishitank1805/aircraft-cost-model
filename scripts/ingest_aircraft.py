"""Read OpenAP aircraft metadata, add curated cargo coverage targets, validate and load into SQLite.

Usage (from the repository root, after ``pip install -e .``)::

    python scripts/ingest_aircraft.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from aircraft_cost_model.config import OPENAP_REPOSITORY_URL, get_settings
from aircraft_cost_model.database import SourceMetadata, create_db_engine, create_schema, load_aircraft_types
from aircraft_cost_model.ingestion.aircraft import (
    CARGO_AIRCRAFT_TARGETS,
    CARGO_TARGETS_REFERENCE_URL,
    CARGO_TARGETS_SOURCE_NAME,
    cargo_targets_checksum,
    read_openap_aircraft,
    save_openap_snapshot,
)
from aircraft_cost_model.logging_config import configure_logging
from aircraft_cost_model.processing.aircraft_cleaner import (
    build_cargo_target_rows,
    coverage_table,
    normalize_openap_aircraft,
    save_aircraft,
)
from aircraft_cost_model.validation.aircraft_validator import validate_aircraft

logger = logging.getLogger("ingest_aircraft")

OPENAP_LICENSE = (
    "OpenAP package: GNU LGPL v3 (package metadata). The bundled data directory "
    "(openap/data/) contains a GNU GPL v3 LICENSE file. Citation requested: Sun, Hoekstra & "
    "Ellerbroek (2020), 'OpenAP: An open-source aircraft performance model for air "
    "transportation studies and simulations', Aerospace 7(8):104."
)

OPENAP_NOTES = (
    "Read from the installed openap package via openap.prop (no synonyms). Units: mtow/mlw/oew kg; "
    "mfc litres; vmo kt; ceiling and cruise height m; cruise range km (nominal). Not provided: "
    "MZFW, maximum payload, freighter variants. Derived (labelled): fuel_capacity_kg, cruise_speed_kt."
)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    snapshot = save_openap_snapshot(read_openap_aircraft(), settings.raw_aircraft_dir)
    openap_rows = normalize_openap_aircraft(snapshot.records)
    cargo_rows, cargo_warnings = build_cargo_target_rows(CARGO_AIRCRAFT_TARGETS, set(snapshot.records))
    master = pd.concat([openap_rows, cargo_rows], ignore_index=True)

    report = validate_aircraft(
        master,
        total_source_records=len(snapshot.records) + len(CARGO_AIRCRAFT_TARGETS),
        source_name="OpenAP + project-curated cargo targets",
        source_url=OPENAP_REPOSITORY_URL,
        retrieved_at=snapshot.retrieved_at.isoformat(),
        source_version=f"openap {snapshot.openap_version}",
        extra_warnings=cargo_warnings,
    )
    paths = save_aircraft(master, cargo_rows, settings.processed_aircraft_dir)
    report_path = report.write_json(settings.processed_aircraft_dir / "aircraft_validation_report.json")
    if not report.passed:
        logger.error("aircraft_validation_failed", extra={"errors": "; ".join(report.errors)})
        print(f"Validation failed; nothing loaded. See {report_path}")
        return 1

    engine = create_db_engine(settings.database_url)
    create_schema(engine)
    openap_source = SourceMetadata(
        source_name="OpenAP",
        source_url=OPENAP_REPOSITORY_URL,
        dataset_name="openap_aircraft_properties",
        license=OPENAP_LICENSE,
        access_type="Python package (pip install openap)",
        retrieved_at=snapshot.retrieved_at,
        source_version=snapshot.openap_version,
        checksum=snapshot.data_checksum,
        notes=OPENAP_NOTES + (f" Raw snapshot: {snapshot.raw_path.name}." if snapshot.raw_path else ""),
    )
    cargo_source = SourceMetadata(
        source_name=CARGO_TARGETS_SOURCE_NAME,
        source_url=CARGO_TARGETS_REFERENCE_URL,
        dataset_name="cargo_aircraft_targets",
        license="Project-authored list. ICAO type designators are individual facts from ICAO Doc 8643 "
        "(ICAO copyright); the ICAO database itself is not redistributed.",
        access_type="Manual curation (src/aircraft_cost_model/ingestion/aircraft.py)",
        retrieved_at=datetime.now(timezone.utc).replace(microsecond=0),
        source_version=f"sha256:{cargo_targets_checksum()[:12]}",
        checksum=cargo_targets_checksum(),
        notes="Freighter types required by the cost model. Coverage only: no weights or performance "
        "values; related OpenAP passenger models are recorded, never substituted.",
    )
    openap_summary, cargo_summary = load_aircraft_types(
        engine, [(openap_rows, openap_source), (cargo_rows, cargo_source)]
    )

    print("\n=== Aircraft ingestion summary ===")
    print(f"OpenAP version           : {snapshot.openap_version} (data sha256 {snapshot.data_checksum[:12]})")
    print(f"Raw snapshot             : {snapshot.raw_path}")
    print(f"OpenAP aircraft types    : {len(openap_rows)}")
    print(f"Curated cargo targets    : {len(cargo_rows)}")
    for label, s in (("OpenAP", openap_summary), ("Cargo", cargo_summary)):
        print(f"{label:<7} inserted/updated/unchanged : {s.inserted} / {s.updated} / {s.unchanged} (source_id {s.source_id})")
    print("\nCargo aircraft coverage:")
    print(coverage_table(cargo_rows).drop(columns=["notes"]).to_string(index=False))
    print("\nMissing values by field:")
    for field, count in report.missing_values_by_field.items():
        print(f"  {field:<18} {count:>3} / {len(master)}")
    print(f"\nProcessed files   : {paths['master']}, {paths['cargo_coverage']}")
    print(f"Validation report : {report_path}")
    print(f"Warnings          : {len(report.warnings)}")
    for warning in report.warnings:
        print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
