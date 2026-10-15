"""Insurance allocation, insured-value scenarios and coverage overlap."""

from __future__ import annotations

from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.fullcost.insurance import insurance
from conftest import illustrative, scenario_from


def test_annual_premium_allocation(owned_scenario_data, basis, fx):
    r = insurance(scenario_from(owned_scenario_data), basis, fx)
    assert r.amount == Decimal("133.33")  # 200000 * 2 / 3000
    owned_scenario_data["insurance"]["allocation_basis"] = "flights"
    assert insurance(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("133.33")  # 200000 / 1500


def test_insured_value_scenario_and_separate_coverages(owned_scenario_data, basis, fx):
    owned_scenario_data["insurance"]["coverages"] = [
        {"name": "hull", "insured_value": illustrative("40000000", "EUR"), "annual_premium_rate": illustrative("0.002", "ratio")},
        {"name": "liability", "annual_premium": illustrative("70000", "EUR/year")},
    ]
    assert insurance(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("100.00")  # (80000+70000)*2/3000


def test_inclusive_plus_separate_coverage_rejected(owned_scenario_data, basis, fx):
    owned_scenario_data["insurance"]["coverages"].append({"name": "war_risk", "annual_premium": illustrative("1000", "EUR/year")})
    assert insurance(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION


def test_missing_annual_utilization(owned_scenario_data, basis, fx):
    del owned_scenario_data["utilization"]["annual_aircraft_block_hours"]
    r = insurance(scenario_from(owned_scenario_data), basis, fx)
    assert r.status == ComponentStatus.MISSING_REQUIRED_INPUT
    assert "utilization.annual_aircraft_block_hours" in r.missing_inputs


def test_insurance_included_in_lease(lease_scenario_data, basis, fx):
    lease_scenario_data["operating_lease"]["includes"] = ["insurance"]
    assert insurance(scenario_from(lease_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION
    del lease_scenario_data["insurance"]
    assert insurance(scenario_from(lease_scenario_data), basis, fx).status == ComponentStatus.NOT_APPLICABLE
