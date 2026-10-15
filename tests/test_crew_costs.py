"""Crew salaries (role allocation) and allowances, kept separate."""

from __future__ import annotations

from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.fullcost.crew import crew_allowances, crew_salaries
from conftest import illustrative, scenario_from


def test_multiple_roles_with_on_costs(owned_scenario_data, basis, fx):
    r = crew_salaries(scenario_from(owned_scenario_data), basis, fx)
    # captain 200000*1.25*2/800 = 625; first officer 120000*1.25*2/800 = 375
    assert r.status == ComponentStatus.CALCULATED_ASSUMPTION and r.amount == Decimal("1000.00")
    assert [b["role"] for b in r.breakdown if "role" in b] == ["captain", "first_officer"]


def test_different_productive_hours_and_staffing_factor(owned_scenario_data, basis, fx):
    roles = owned_scenario_data["crew"]["salaries"]["roles"]
    roles[1]["annual_allocable_block_hours"] = illustrative("600", "block_hour/year")
    owned_scenario_data["crew"]["salaries"]["staffing_factor"] = illustrative("1.2", "ratio")
    r = crew_salaries(scenario_from(owned_scenario_data), basis, fx)
    assert r.amount == Decimal("1350.00")  # (625 + 500) * 1.2


def test_missing_staffing_data(owned_scenario_data, basis, fx):
    del owned_scenario_data["crew"]["salaries"]["staffing_factor"]
    r = crew_salaries(scenario_from(owned_scenario_data), basis, fx)
    assert r.status == ComponentStatus.MISSING_REQUIRED_INPUT and "crew.salaries.staffing_factor" in r.missing_inputs
    del owned_scenario_data["crew"]["salaries"]["roles"]
    assert crew_salaries(scenario_from(owned_scenario_data), basis, fx).amount is None


def test_allowances_per_duty_day_and_overnight(owned_scenario_data, basis, fx):
    assert crew_allowances(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("100.00")  # 50*2*1
    allowances = owned_scenario_data["crew"]["allowances"]
    allowances["accommodation_per_crew_member_per_night"] = illustrative("120", "EUR/night")
    allowances["nights"] = illustrative("1", "nights")
    allowances["other_flight_expenses"] = illustrative("30", "EUR/flight")
    assert crew_allowances(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("370.00")
    allowances["nights"] = illustrative("1", "days")  # nights are not duty days
    assert crew_allowances(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION


def test_salary_versus_allowance_separation(owned_scenario_data, basis, fx):
    owned_scenario_data["crew"]["salaries"]["includes_allowances"] = True
    assert crew_allowances(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION
    del owned_scenario_data["crew"]["allowances"]
    assert crew_allowances(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.NOT_APPLICABLE


def test_benchmark_rate_per_block_hour(owned_scenario_data, basis, fx):
    owned_scenario_data["crew"]["salaries"] = {"basis": "rate_per_block_hour", "includes_allowances": True,
                                               "rate_per_block_hour": {"value": "1378", "unit": "USD/block_hour",
                                                                       "source_type": "public_financial_benchmark",
                                                                       "source_reference": "FAA Table 4-7"}}
    r = crew_salaries(scenario_from(owned_scenario_data), basis, fx)
    assert r.status == ComponentStatus.CALCULATED_BENCHMARK and r.amount == Decimal("2204.80")  # 1378*2/1.25


def test_crew_productivity_is_not_aircraft_utilization(owned_scenario_data, basis, fx):
    before = crew_salaries(scenario_from(owned_scenario_data), basis, fx).amount
    owned_scenario_data["utilization"]["annual_aircraft_block_hours"] = illustrative("4500", "block_hour/year")
    assert crew_salaries(scenario_from(owned_scenario_data), basis, fx).amount == before
    del owned_scenario_data["crew"]["salaries"]["roles"][0]["annual_allocable_block_hours"]
    r = crew_salaries(scenario_from(owned_scenario_data), basis, fx)
    assert r.amount is None  # no fallback to aircraft utilization
    assert "crew.salaries.roles[0].annual_allocable_block_hours" in r.missing_inputs
