"""Scenario file schema and unit validation."""

from __future__ import annotations

import pytest

from aircraft_cost_model.fullcost.scenario import ScenarioError, load_scenario, parse_scenario
from conftest import SCENARIOS, illustrative, scenario_from


def test_shipped_scenarios_load():
    for path in SCENARIOS.glob("*.json"):
        scenario = load_scenario(path)
        assert scenario.ownership_mode in ("owned", "operating_lease", "custom")
        assert scenario.content_hash and scenario.values


def test_illustrative_values_are_labelled(owned_scenario_data):
    scenario = scenario_from(owned_scenario_data)
    assert {v.source_type for v in scenario.values.values()} == {"illustrative_assumption"}


def test_reproducible_hash(owned_scenario_data):
    assert scenario_from(owned_scenario_data).content_hash == scenario_from(owned_scenario_data).content_hash
    owned_scenario_data["utilization"]["annual_flights"]["value"] = "1501"
    assert scenario_from(owned_scenario_data).content_hash != parse_scenario(
        load_scenario(SCENARIOS / "example_owned_aircraft.json").raw).content_hash


@pytest.mark.parametrize("mutate, match", [
    (lambda d: d.update(ownership_mode="rented"), "ownership_mode"),
    (lambda d: d.update(ownership_mode="custom"), "custom_treatment"),
    (lambda d: d.pop("flight_type"), "flight_type"),
    (lambda d: d["utilization"]["annual_flights"].update(value=1500.0), "JSON float"),
    (lambda d: d["utilization"]["annual_flights"].update(unit="flights per year"), "unknown unit"),
    (lambda d: d["utilization"]["annual_flights"].update(unit="EUR/lightyear"), "dimension"),
    (lambda d: d["utilization"]["annual_flights"].update(source_type="guess"), "source_type"),
    (lambda d: d["utilization"]["annual_flights"].update(source_type="public_financial_benchmark"), "source_reference"),
    (lambda d: d.update(effective_to="2024-01-01"), "effective_to"),
])
def test_invalid_scenarios_rejected(owned_scenario_data, mutate, match):
    mutate(owned_scenario_data)
    with pytest.raises(ScenarioError, match=match):
        scenario_from(owned_scenario_data)


def test_money_units_parsed(owned_scenario_data):
    owned_scenario_data["utilization"]["annual_flights"] = illustrative("1500", "flight/year")
    scenario = scenario_from(owned_scenario_data)
    rate = scenario.value("maintenance.airframe.rate_per_block_hour")
    assert (rate.currency, rate.dimension, rate.is_money) == ("EUR", "block_hour", True)
    assert scenario.value("depreciation.acquisition_value").dimension == "amount"
    assert scenario.value("utilization.annual_flights").currency is None
