"""Run read-only verification queries against the SQLite database.

Usage::

    python scripts/verify_database.py
    python scripts/verify_database.py --country DE --airport-type large_airport
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
from sqlalchemy import inspect, text

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.database import create_db_engine

PERFORMANCE_FIELDS = (
    "engine_type",
    "engine_count",
    "mtow_kg",
    "mlw_kg",
    "mzfw_kg",
    "oew_kg",
    "max_payload_kg",
    "fuel_capacity_kg",
    "cruise_speed_kt",
)


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--country", help="ISO country code filter for the example airports (e.g. DE).")
    parser.add_argument("--airport-type", default="large_airport", help="Airport type for the examples.")
    args = parser.parse_args(argv)

    settings = get_settings(create_directories=False)
    if not settings.database_path.is_file():
        print(f"Database not found: {settings.database_path}. Run the ingestion scripts first.")
        return 1
    engine = create_db_engine(settings.database_url)
    tables = set(inspect(engine).get_table_names())
    missing_tables = {"airport", "aircraft_type", "data_source"} - tables
    if missing_tables:
        print(f"Missing tables: {sorted(missing_tables)}")
        return 1

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.max_colwidth", 60)
    with engine.connect() as conn:
        _section("Record counts")
        for table in ("airport", "aircraft_type", "data_source"):
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()  # fixed identifiers
            print(f"{table:<14} {count:,}")

        _section("Airports by type")
        print(pd.read_sql(text(
            "SELECT airport_type, COUNT(*) AS n FROM airport GROUP BY airport_type ORDER BY n DESC"
        ), conn).to_string(index=False))

        _section(f"Ten example airports (type={args.airport_type}, country={args.country or 'any'})")
        params = {"airport_type": args.airport_type.lower(), "country": args.country.upper() if args.country else None}
        print(pd.read_sql(text(
            "SELECT airport_ident, icao_code, iata_code, airport_name, country_code, "
            "ROUND(latitude, 4) AS lat, ROUND(longitude, 4) AS lon, elevation_ft, scheduled_service "
            "FROM airport WHERE airport_type = :airport_type "
            "AND (:country IS NULL OR country_code = :country) "
            "ORDER BY iata_code IS NULL, source_airport_id LIMIT 10"
        ), conn, params=params).to_string(index=False))

        _section("Lookup check: FRA and JFK by IATA code")
        print(pd.read_sql(text(
            "SELECT iata_code, icao_code, airport_name, latitude, longitude FROM airport "
            "WHERE iata_code IN (:a, :b) ORDER BY iata_code"
        ), conn, params={"a": "FRA", "b": "JFK"}).to_string(index=False))

        _section("Available aircraft types")
        print(pd.read_sql(text(
            "SELECT aircraft_code, icao_type_designator AS icao, manufacturer, model, variant, engine_count AS eng, "
            "mtow_kg, oew_kg, fuel_capacity_l, cruise_speed_kt, openap_supported AS openap, openap_coverage "
            "FROM aircraft_type ORDER BY openap_supported DESC, aircraft_code"
        ), conn).to_string(index=False))

        _section("Missing aircraft performance fields (NULL count)")
        total = conn.execute(text("SELECT COUNT(*) FROM aircraft_type")).scalar_one()
        for field in PERFORMANCE_FIELDS:  # fixed identifiers, not user input
            nulls = conn.execute(text(f"SELECT COUNT(*) FROM aircraft_type WHERE {field} IS NULL")).scalar_one()
            print(f"{field:<18} {nulls:>3} / {total}")

        _section("Data sources")
        sources = pd.read_sql(text(
            "SELECT source_id, source_name, dataset_name, source_version, retrieved_at, "
            "SUBSTR(checksum, 1, 12) AS checksum12, access_type FROM data_source ORDER BY source_id"
        ), conn)
        print(sources.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
