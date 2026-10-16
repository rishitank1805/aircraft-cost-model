"""Route / aircraft / scenario / ownership comparisons and the common-component comparison."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import AnalyticsInputError, calculate_case, find_route_case, load_saved_case
from aircraft_cost_model.analytics.comparisons import (
    COMMON_LABEL,
    compare_cases,
    ownership_comparison,
    ownership_table,
)
from aircraft_cost_model.analytics.metrics import DistanceBasis, DistanceInput
from aircraft_cost_model.costs.calculator import VariableCostRequest, calculate_variable_costs
from aircraft_cost_model.costs.persistence import save_variable_cost_estimate
from aircraft_cost_model.fullcost.scenario import load_scenario
from aircraft_cost_model.performance.persistence import save_flight_estimate
from aircraft_cost_model.performance.planner import FlightRequest, estimate_flight
from conftest import SCENARIOS, illustrative, scenario_from

GC = DistanceInput(DistanceBasis.GREAT_CIRCLE)
PRICING = date(2025, 1, 15)


def _add_flight(engine, provider, aircraft, origin, destination, pricing=PRICING):
    with Session(engine) as session:
        result = estimate_flight(session, FlightRequest(aircraft, origin, destination, 10000), provider)
    flight_id = save_flight_estimate(engine, result)
    with Session(engine) as session:
        variable = calculate_variable_costs(session, VariableCostRequest(flight_id, pricing))
    return flight_id, save_variable_cost_estimate(engine, variable)


@pytest.fixture
def multi(analytics_db, openap_provider):
    engine, ids = analytics_db
    ids["reverse"] = _add_flight(engine, openap_provider, "A320", "CDG", "FRA")
    ids["a321"] = _add_flight(engine, openap_provider, "A321", "FRA", "CDG")
    return engine, ids


def test_same_aircraft_different_routes(multi, owned_scenario_data):
    engine, ids = multi
    with Session(engine) as session:
        a = load_saved_case(session, ids["full"])
        b, _ = calculate_case(session, *ids["reverse"], scenario_from(owned_scenario_data), label="A320 CDG-FRA")
        result = compare_cases([a, b], GC)
    rows = [r.values for r in result.rows]
    assert [(r["origin"], r["destination"]) for r in rows] == [("FRA", "CDG"), ("CDG", "FRA")]
    assert all(r["coc"]["complete"] is None for r in rows) and not result.complete_totals_comparable
    for case in (a, b):
        assert result.common_subtotals[case.label] == sum(case.summary.components[n].amount
                                                          for n in result.common_components)
    assert "fuel" in result.common_components and result.pricing_dates == ["2025-01-15"]


def test_same_route_different_supported_aircraft_by_route_case(multi):
    engine, _ = multi
    scenario = load_scenario(SCENARIOS / "example_owned_aircraft.json")
    with Session(engine) as session:
        a320 = find_route_case(session, "A320", "FRA", "CDG", PRICING, "EUR", scenario)
        a321 = find_route_case(session, "A321", "FRA", "CDG", PRICING, "EUR", scenario)
        result = compare_cases([a320, a321], GC)
    assert {r.values["aircraft"] for r in result.rows} == {"A320", "A321"}
    fuels = [Decimal(r.values["fuel_cost"]["calculated_subtotal"]) for r in result.rows]
    assert fuels[0] != fuels[1]


def test_unsupported_freighter_and_missing_estimate(multi):
    engine, ids = multi
    scenario = load_scenario(SCENARIOS / "example_owned_aircraft.json")
    with Session(engine) as session:
        freighter = find_route_case(session, "B777F", "FRA", "CDG", PRICING, "EUR", scenario)
        missing = find_route_case(session, "A320", "FRA", "JFK", PRICING, "EUR", scenario)
        result = compare_cases([load_saved_case(session, ids["full"]), freighter, missing], GC)
    assert freighter.origin == "unsupported" and freighter.summary is None
    assert "no passenger model is substituted" in freighter.warnings[0]
    assert missing.origin == "missing_flight_estimate"
    statuses = [r.values["cost_coverage"] for r in result.rows]
    assert statuses == ["partial", "unsupported", "missing_required_input"]
    assert any("B777F" in w for w in result.warnings)


def test_owned_vs_leased(analytics_db, lease_scenario_data):
    engine, ids = analytics_db
    with Session(engine) as session:
        owned = load_saved_case(session, ids["full"])
        leased, _ = calculate_case(session, 1, ids["variable"], scenario_from(lease_scenario_data), label="lease")
        result = ownership_comparison(owned, leased, GC)
    assert not result.coverage_mismatch  # n/a items are a taxonomy difference, not missing coverage
    assert any("applicability differs" in w for w in result.warnings)
    assert not any("beyond ownership" in w for w in result.warnings)
    table = {r["item"]: r for r in ownership_table(result)}
    assert table["lease_payment"]["owned"].startswith("n/a") and table["lease_payment"]["operating_lease"] == "1437.17"
    assert table["depreciation"]["operating_lease"].startswith("n/a")
    assert table["COC (calculated subtotal)"]["difference_lease_minus_owned"] == "1437.17"
    assert table["maintenance"]["difference_lease_minus_owned"] == "0.00"
    assert any("IFRS 16" in e for e in result.explanation)
    assert set(result.common_components) >= {"fuel", "crew_salaries", "insurance"}
    assert "operating_lease" not in result.common_components
    assert result.excluded_from_common["depreciation"] == "not applicable in some cases"


def test_ownership_requires_matching_modes_and_flags_other_differences(analytics_db, lease_scenario_data):
    engine, ids = analytics_db
    lease_scenario_data["maintenance"]["airframe"]["rate_per_block_hour"] = illustrative("350", "EUR/block_hour")
    with Session(engine) as session:
        owned = load_saved_case(session, ids["full"])
        leased, _ = calculate_case(session, 1, ids["variable"], scenario_from(lease_scenario_data))
        result = ownership_comparison(owned, leased, GC)
        assert any("beyond ownership inputs" in w and "rate_per_block_hour" in w for w in result.warnings)
        with pytest.raises(AnalyticsInputError, match="expected ownership mode"):
            ownership_comparison(leased, owned, GC)


def test_common_component_excludes_differently_defined_components(analytics_db):
    engine, ids = analytics_db
    with Session(engine) as session:
        owned = load_saved_case(session, ids["full"])
        faa, _ = calculate_case(session, 1, ids["variable"],
                                load_scenario(SCENARIOS / "benchmark_faa_us_narrowbody_partial.json"))
        result = compare_cases([owned, faa], GC)
    assert "defined differently" in result.excluded_from_common["airframe_maintenance"]
    assert "airframe_maintenance" not in result.common_components
    assert COMMON_LABEL in result.to_dict()


def test_coverage_mismatch_is_flagged(analytics_db, owned_scenario_data):
    engine, ids = analytics_db
    without_insurance = dict(owned_scenario_data)
    without_insurance.pop("insurance")
    with Session(engine) as session:
        a = load_saved_case(session, ids["full"])
        b, _ = calculate_case(session, 1, ids["variable"], scenario_from(without_insurance), label="no insurance")
        result = compare_cases([a, b], GC)
    assert result.coverage_mismatch == {"no insurance": ["insurance"]}
    assert any("coverage mismatch" in w for w in result.warnings)
    assert "insurance" not in result.common_components


def test_pricing_date_mismatch_is_flagged(analytics_db, owned_scenario_data):
    engine, ids = analytics_db
    with Session(engine) as session:
        variable = calculate_variable_costs(session, VariableCostRequest(1, date(2025, 1, 16)))
    later = save_variable_cost_estimate(engine, variable)
    data = dict(owned_scenario_data, pricing_date="2025-01-16")
    with Session(engine) as session:
        a = load_saved_case(session, ids["full"])
        b, _ = calculate_case(session, 1, later, scenario_from(data), label="16 Jan")
        result = compare_cases([a, b], GC)
    assert result.pricing_dates == ["2025-01-15", "2025-01-16"]
    assert any("pricing dates differ" in w for w in result.warnings)


def test_currency_mismatch_and_single_case_rejected():
    from tests_helpers_part5 import usd_case, eur_case  # noqa: F401  (local helper module)

    with pytest.raises(AnalyticsInputError, match="currencies"):
        compare_cases([eur_case(), usd_case()], GC)
    with pytest.raises(AnalyticsInputError, match="at least two"):
        compare_cases([eur_case()], GC)


def test_shared_scenario_across_aircraft_is_flagged(multi):
    engine, _ = multi
    scenario = load_scenario(SCENARIOS / "example_owned_aircraft.json")
    with Session(engine) as session:
        result = compare_cases([find_route_case(session, "A320", "FRA", "CDG", PRICING, "EUR", scenario),
                                find_route_case(session, "A321", "FRA", "CDG", PRICING, "EUR", scenario)], GC)
    assert any("not aircraft-specific" in w for w in result.warnings)
