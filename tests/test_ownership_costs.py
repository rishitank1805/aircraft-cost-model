"""Operating lease, depreciation, financing and ownership-mode double-counting controls."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.fullcost.ownership import amortizing_interest, depreciation, financing, operating_lease
from conftest import illustrative, scenario_from


def lease(data, basis, fx, maintenance=True):
    return operating_lease(scenario_from(data), basis, fx, maintenance_modelled=maintenance)


def test_monthly_to_annual_and_per_flight_allocation(lease_scenario_data, basis, fx):
    r = lease(lease_scenario_data, basis, fx)
    assert r.amount == Decimal("2400.00")  # 300000*12*2/3000
    lease_scenario_data["operating_lease"]["allocation_basis"] = "flights"
    assert lease(lease_scenario_data, basis, fx).amount == Decimal("2400.00")  # 3.6M / 1500


def test_maintenance_reserves_in_lease(lease_scenario_data, basis, fx):
    lease_scenario_data["operating_lease"]["includes"] = ["maintenance_reserves"]
    assert lease(lease_scenario_data, basis, fx).status == ComponentStatus.FAILED_VALIDATION
    assert lease(lease_scenario_data, basis, fx, maintenance=False).status == ComponentStatus.CALCULATED_ASSUMPTION


def test_ownership_mode_exclusions(owned_scenario_data, lease_scenario_data, basis, fx):
    assert lease(owned_scenario_data, basis, fx).status == ComponentStatus.NOT_APPLICABLE
    for fn in (depreciation, financing):
        assert fn(scenario_from(lease_scenario_data), basis, fx).status == ComponentStatus.NOT_APPLICABLE
    lease_scenario_data["depreciation"] = owned_scenario_data["depreciation"]
    assert depreciation(scenario_from(lease_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION


def test_straight_line_depreciation(owned_scenario_data, basis, fx):
    r = depreciation(scenario_from(owned_scenario_data), basis, fx)
    assert r.amount == Decimal("1500.00")  # (50M - 5M)/20 = 2.25M; *2/3000


@pytest.mark.parametrize("key, value, unit", [("useful_life_years", "0", "years"), ("residual_value", "60000000", "EUR"),
                                              ("residual_value", "-1", "EUR")])
def test_invalid_depreciation_inputs(owned_scenario_data, basis, fx, key, value, unit):
    owned_scenario_data["depreciation"][key] = illustrative(value, unit)
    assert depreciation(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.FAILED_VALIDATION


def test_financing_modes(owned_scenario_data, basis, fx):
    assert financing(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("1000.00")  # 30M*5%*2/3000
    owned_scenario_data["financing"] = {"mode": "annual_interest_expense", "allocation_basis": "block_hours",
                                        "annual_interest_expense": illustrative("600000", "EUR/year")}
    assert financing(scenario_from(owned_scenario_data), basis, fx).amount == Decimal("400.00")
    owned_scenario_data["financing"] = {"mode": "none"}
    assert financing(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.MISSING_REQUIRED_INPUT
    owned_scenario_data["financing"]["reason"] = "aircraft purchased with equity"
    assert financing(scenario_from(owned_scenario_data), basis, fx).status == ComponentStatus.NOT_APPLICABLE


def test_amortizing_loan_excludes_principal():
    interest, repaid, _ = amortizing_interest(Decimal("1200"), Decimal("0.12"), 1, 12, date(2025, 1, 1), date(2025, 6, 1))
    assert repaid == pytest.approx(Decimal("1200"), abs=Decimal("0.01"))
    assert interest == pytest.approx(Decimal("79.42"), abs=Decimal("0.01"))  # 12 x 106.62 - 1200
    zero, _, _ = amortizing_interest(Decimal("1000"), Decimal("0"), 2, 4, date(2024, 1, 1), date(2025, 2, 1))
    assert zero == 0
    with pytest.raises(ValueError):
        amortizing_interest(Decimal("1000"), Decimal("0.05"), 1, 12, date(2025, 1, 1), date(2024, 12, 31))
    with pytest.raises(ValueError):
        amortizing_interest(Decimal("1000"), Decimal("0.05"), 1, 12, date(2023, 1, 1), date(2025, 1, 1))


def test_amortizing_mode_in_scenario(owned_scenario_data, basis, fx):
    owned_scenario_data["financing"] = {
        "mode": "amortizing_loan", "allocation_basis": "flights", "loan_start_date": "2024-07-01",
        "principal": illustrative("30000000", "EUR"), "annual_interest_rate": illustrative("0.05", "ratio"),
        "term_years": illustrative("12", "years"), "payments_per_year": illustrative("12", "payments/year")}
    r = financing(scenario_from(owned_scenario_data), basis, fx)
    assert r.status == ComponentStatus.CALCULATED_ASSUMPTION
    year = next(b for b in r.breakdown if b.get("step") == "loan year interest")
    assert Decimal(year["principal_repaid_excluded"]) > 0  # recorded, not expensed
    assert r.amount < Decimal(30000000 * 0.05 / 1500 + 1)


def test_custom_mode_controls(owned_scenario_data, basis, fx):
    data = dict(owned_scenario_data, ownership_mode="custom",
                custom_treatment={"include_operating_lease": True, "include_depreciation": True,
                                  "include_financing": True, "justification": "x"},
                operating_lease={"allocation_basis": "block_hours", "includes": [],
                                 "monthly_payment": illustrative("1000", "EUR/month")})
    for fn in (depreciation, financing):
        assert fn(scenario_from(data), basis, fx).status == ComponentStatus.FAILED_VALIDATION  # all three never
    data["custom_treatment"] = {"include_operating_lease": True, "include_depreciation": True, "include_financing": False}
    assert depreciation(scenario_from(data), basis, fx).status == ComponentStatus.FAILED_VALIDATION  # needs justification
    data["custom_treatment"]["justification"] = "depreciation of operator-owned cabin modifications on a leased airframe"
    assert depreciation(scenario_from(data), basis, fx).status == ComponentStatus.CALCULATED_ASSUMPTION
    assert financing(scenario_from(data), basis, fx).status == ComponentStatus.FAILED_VALIDATION  # section present, excluded
