"""Airframe, engine and LLP maintenance (time bases: 2.0 BH, 1.5 airborne h, 2 engines, 1 cycle)."""

from __future__ import annotations

from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.fullcost.maintenance import airframe_maintenance, engine_llp, engine_maintenance
from conftest import illustrative, scenario_from


def run(fn, data, basis, fx):
    return fn(scenario_from(data), basis, fx)


def test_hourly_and_cycle_airframe(owned_scenario_data, basis, fx):
    r = run(airframe_maintenance, owned_scenario_data, basis, fx)
    assert r.status == ComponentStatus.CALCULATED_ASSUMPTION and r.amount == Decimal("700.00")  # 2*300 + 1*100


def test_inclusive_hourly_rate_rejects_cycle_rate(owned_scenario_data, basis, fx):
    owned_scenario_data["maintenance"]["airframe"]["hourly_rate_includes_cycle_costs"] = True
    assert run(airframe_maintenance, owned_scenario_data, basis, fx).status == ComponentStatus.FAILED_VALIDATION
    del owned_scenario_data["maintenance"]["airframe"]["rate_per_flight_cycle"]
    assert run(airframe_maintenance, owned_scenario_data, basis, fx).amount == Decimal("600.00")


def test_engine_count_and_engine_hours_basis(owned_scenario_data, basis, fx):
    r = run(engine_maintenance, owned_scenario_data, basis, fx)
    assert r.amount == Decimal("450.00")  # 2 engines x 1.5 airborne h x 150
    owned_scenario_data["maintenance"]["engine"]["engine_hours_basis"] = "block_hours_proxy"
    proxy = run(engine_maintenance, owned_scenario_data, basis, fx)
    assert proxy.amount == Decimal("600.00") and any("proxy" in w for w in proxy.warnings)
    del owned_scenario_data["maintenance"]["engine"]["engine_hours_basis"]
    missing = run(engine_maintenance, owned_scenario_data, basis, fx)
    assert missing.status == ComponentStatus.MISSING_REQUIRED_INPUT  # never silently block hours
    assert "maintenance.engine.engine_hours_basis" in missing.missing_inputs


def test_engine_cycle_component_only_when_excluded(owned_scenario_data, basis, fx):
    engine = owned_scenario_data["maintenance"]["engine"]
    engine["hourly_rate_includes_cycle_costs"] = False
    assert run(engine_maintenance, owned_scenario_data, basis, fx).status == ComponentStatus.MISSING_REQUIRED_INPUT
    engine["rate_per_engine_cycle"] = illustrative("40", "EUR/engine_cycle")
    assert run(engine_maintenance, owned_scenario_data, basis, fx).amount == Decimal("530.00")  # 450 + 2*1*40


def test_llp_per_engine_cycle_is_accrual(owned_scenario_data, basis, fx):
    r = run(engine_llp, owned_scenario_data, basis, fx)
    assert r.amount == Decimal("200.00") and any("accrual" in w for w in r.warnings)


def test_double_counting_prevention(owned_scenario_data, basis, fx):
    owned_scenario_data["maintenance"]["engine"]["includes_llp"] = True
    assert run(engine_llp, owned_scenario_data, basis, fx).status == ComponentStatus.FAILED_VALIDATION
    del owned_scenario_data["maintenance"]["engine_llp"]
    assert run(engine_llp, owned_scenario_data, basis, fx).status == ComponentStatus.NOT_APPLICABLE
    owned_scenario_data["maintenance"]["airframe"]["covers"] = ["airframe", "engine", "engine_llp"]
    assert run(engine_maintenance, owned_scenario_data, basis, fx).status == ComponentStatus.FAILED_VALIDATION
    del owned_scenario_data["maintenance"]["engine"]
    assert run(engine_maintenance, owned_scenario_data, basis, fx).status == ComponentStatus.NOT_APPLICABLE
    assert run(engine_llp, owned_scenario_data, basis, fx).status == ComponentStatus.NOT_APPLICABLE


def test_missing_rate_and_wrong_unit(owned_scenario_data, basis, fx):
    del owned_scenario_data["maintenance"]["airframe"]["rate_per_block_hour"]
    r = run(airframe_maintenance, owned_scenario_data, basis, fx)
    assert r.status == ComponentStatus.MISSING_REQUIRED_INPUT and r.amount is None
    owned_scenario_data["maintenance"]["airframe"]["rate_per_block_hour"] = illustrative("300", "EUR/flight_cycle")
    assert run(airframe_maintenance, owned_scenario_data, basis, fx).status == ComponentStatus.FAILED_VALIDATION


def test_currency_conversion_and_effective_period(owned_scenario_data, basis, fx):
    owned_scenario_data["maintenance"]["airframe"]["rate_per_block_hour"] = illustrative("375", "USD/block_hour")
    assert run(airframe_maintenance, owned_scenario_data, basis, fx).amount == Decimal("700.00")  # 375/1.25 = 300
    owned_scenario_data["maintenance"]["airframe"]["rate_per_block_hour"] = illustrative(
        "300", "EUR/block_hour", effective_from="2026-01-01", effective_to="2026-12-31")
    r = run(airframe_maintenance, owned_scenario_data, basis, fx)
    assert r.status == ComponentStatus.FAILED_VALIDATION and any("effective period" in w for w in r.warnings)


def test_engine_hours_bases_are_distinct(owned_scenario_data, basis, fx):
    amounts = {}
    for name in ("airborne_hours", "engine_running_estimate", "block_hours_proxy"):
        owned_scenario_data["maintenance"]["engine"]["engine_hours_basis"] = name
        r = run(engine_maintenance, owned_scenario_data, basis, fx)
        amounts[name] = r.amount
        assert any(b.get("engine_hours_basis") == name or name in str(b) for b in r.breakdown)
    assert amounts["airborne_hours"] == Decimal("450.00")  # 1.5 airborne h, not block hours
    assert amounts["engine_running_estimate"] == amounts["block_hours_proxy"] == Decimal("600.00")
    owned_scenario_data["maintenance"]["engine"]["engine_hours_basis"] = "flight_hours"
    assert run(engine_maintenance, owned_scenario_data, basis, fx).status == ComponentStatus.FAILED_VALIDATION
