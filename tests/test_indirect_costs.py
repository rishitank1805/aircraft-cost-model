"""Administration, cargo sales and G&A overhead."""

from __future__ import annotations

from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.fullcost.indirect import administration, cargo_sales, general_administrative
from conftest import illustrative, scenario_from


def test_per_flight_administration_and_annual_overhead(owned_scenario_data, basis, fx):
    assert administration(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("100.00")
    assert general_administrative(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("666.67")  # 1M*2/3000
    owned_scenario_data["indirect"]["administration"] = {"scope": "ops admin", "basis": "per_block_hour",
                                                         "rate": illustrative("40", "EUR/block_hour")}
    assert administration(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("80.00")


def test_cargo_sales_per_tonne_and_revenue_share(owned_scenario_data, basis, fx):
    sales = {"applicable": True, "basis": "per_revenue_tonne", "rate": illustrative("25", "EUR/revenue_tonne"),
             "revenue_cargo_tonnes": illustrative("8.5", "tonnes")}
    owned_scenario_data["indirect"]["cargo_sales"] = sales
    assert cargo_sales(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("212.50")
    del sales["revenue_cargo_tonnes"]  # never derived from payload
    assert cargo_sales(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.MISSING_REQUIRED_INPUT
    owned_scenario_data["indirect"]["cargo_sales"] = {"applicable": True, "basis": "pct_of_cargo_revenue",
                                                     "rate": illustrative("0.05", "ratio"),
                                                     "cargo_revenue": illustrative("20000", "EUR")}
    assert cargo_sales(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("1000.00")


def test_passenger_cargo_applicability(owned_scenario_data, basis, fx):
    assert cargo_sales(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.NOT_APPLICABLE
    owned_scenario_data["indirect"]["cargo_sales"] = {"applicable": False}
    assert cargo_sales(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.MISSING_REQUIRED_INPUT
    del owned_scenario_data["indirect"]["cargo_sales"]
    assert cargo_sales(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.MISSING_REQUIRED_INPUT


def test_ga_overlap_prevention(owned_scenario_data, basis, fx):
    ga = owned_scenario_data["indirect"]["general_administrative"]
    ga["excludes_administration"] = False
    assert general_administrative(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION
    ga["excludes_administration"] = True
    ga["scope"] = owned_scenario_data["indirect"]["administration"]["scope"]
    assert general_administrative(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION


def test_allocation_denominators_explicit(owned_scenario_data, basis, fx):
    ga = owned_scenario_data["indirect"]["general_administrative"]
    del ga["allocation_basis"]
    r = general_administrative(scenario_from(owned_scenario_data), basis, fx)
    assert r.amount is None and "indirect.general_administrative.allocation_basis" in r.missing_inputs
    ga["allocation_basis"] = "flights"
    del owned_scenario_data["utilization"]["annual_flights"]
    r = general_administrative(scenario_from(owned_scenario_data), basis, fx)
    assert r.amount is None and r.missing_inputs == ["utilization.annual_flights"]  # no block-hour fallback
    ga["allocation_basis"] = "revenue"
    assert general_administrative(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION
