"""Read-only checks of Part 3 cost data: reference data coverage, sources and saved cost estimates."""

from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import inspect, text

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.database import create_db_engine, current_revision, head_revision

PART3_TABLES = ("fuel_price", "exchange_rate", "navigation_rate", "navigation_zone_aerodrome", "airport_tariff",
                "variable_cost_estimate", "cost_component")


def main(argv: list[str] | None = None) -> int:
    settings = get_settings(create_directories=False)
    if not settings.database_path.is_file():
        print(f"Database not found: {settings.database_path}")
        return 1
    engine = create_db_engine(settings.database_url)
    missing = set(PART3_TABLES) - set(inspect(engine).get_table_names())
    print(f"Alembic revision: {current_revision(engine)} (head {head_revision()})")
    if missing:
        print(f"Missing Part 3 tables: {sorted(missing)}; run an ingestion script to migrate.")
        return 1
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 70)
    with engine.connect() as conn:
        print("\n=== Fuel price series ===")
        print(pd.read_sql(text("SELECT series_identifier, observation_period, currency, price_unit, COUNT(*) AS n, "
                               "MIN(observation_date) AS first, MAX(observation_date) AS last FROM fuel_price "
                               "GROUP BY 1, 2, 3, 4"), conn).to_string(index=False))
        print("\n=== Exchange rates (quote per 1 EUR) ===")
        print(pd.read_sql(text("SELECT base_currency, quote_currency, COUNT(*) AS n, MIN(observation_date) AS first, "
                               "MAX(observation_date) AS last FROM exchange_rate GROUP BY 1, 2"), conn).to_string(index=False))
        print("\n=== Navigation unit rates (en-route and terminal) ===")
        print(pd.read_sql(text("SELECT charge_type, charging_zone, unit_rate, currency, service_unit_formula AS formula, "
                               "charged_movement, valid_from, valid_to, verification_status FROM navigation_rate "
                               "ORDER BY charge_type, charging_zone, valid_from"), conn).to_string(index=False))
        print(pd.read_sql(text("SELECT charging_zone, COUNT(*) AS aerodromes, MIN(valid_from) AS first, "
                               "MAX(valid_to) AS last FROM navigation_zone_aerodrome GROUP BY 1"), conn).to_string(index=False))
        print("\n=== Airport tariffs ===")
        tariffs = pd.read_sql(text("SELECT a.iata_code AS airport, t.tariff_type, t.calculation_method, t.valid_from, "
                                   "t.valid_to, t.currency, t.verification_status FROM airport_tariff t "
                                   "JOIN airport a USING (airport_id)"), conn)
        print(tariffs.to_string(index=False) if len(tariffs) else "(none loaded)")
        print("\n=== Saved variable cost estimates ===")
        print(pd.read_sql(text(
            "SELECT v.variable_cost_estimate_id AS id, v.flight_estimate_id AS flight, v.pricing_date, "
            "v.reporting_currency AS ccy, v.calculated_subtotal AS subtotal, "
            "COALESCE(v.complete_variable_cost, 'unavailable') AS complete_total, v.coverage_status, "
            "v.components_calculated || '/' || v.components_applicable AS calculated FROM variable_cost_estimate v "
            "ORDER BY v.variable_cost_estimate_id DESC LIMIT :n"), conn, params={"n": 10}).to_string(index=False))
        print("\n=== Components of the latest estimate ===")
        print(pd.read_sql(text(
            "SELECT component_name, COALESCE(amount, 'N/A') AS amount, currency, status, source_type, partial_scope, "
            "pricing_observation_date FROM cost_component WHERE variable_cost_estimate_id = "
            "(SELECT MAX(variable_cost_estimate_id) FROM variable_cost_estimate) ORDER BY cost_component_id"),
            conn).to_string(index=False))
        print("\n=== Part 3 data sources ===")
        print(pd.read_sql(text(
            "SELECT source_id, source_name, dataset_name, source_version, retrieved_at FROM data_source "
            "WHERE dataset_name LIKE 'eia_%' OR dataset_name LIKE 'ecb_%' OR dataset_name LIKE 'eurocontrol_%' OR dataset_name LIKE 'navigation_%' "
            "OR dataset_name LIKE 'airport_tariff_%' ORDER BY source_id"), conn).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
