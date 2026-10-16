"""Scenario variations and sensitivity, recalculated through the Part 3 fuel engine and Part 4 calculator."""

from __future__ import annotations

import copy
import json
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import AnalyticsInputError
from aircraft_cost_model.analytics.metrics import DistanceBasis, DistanceInput, PayloadInput
from aircraft_cost_model.analytics.scenarios import BaseCase, Variation, base_from_saved, run_variation
from aircraft_cost_model.analytics.sensitivity import two_way, one_way
from aircraft_cost_model.costs.coverage import ComponentStatus
from conftest import SCENARIOS, scenario_from

D = Decimal
GC = DistanceInput(DistanceBasis.GREAT_CIRCLE)


@pytest.fixture
def base(analytics_db):
    engine, ids = analytics_db
    with Session(engine) as session:
        yield session, base_from_saved(session, ids["full"], GC), engine, ids


def amounts(result):
    return {n: c.amount for n, c in result.case.summary.components.items()}


def test_base_reproduces_saved_estimate(base):
    session, b, _, _ = base
    r = run_variation(session, b, ())
    assert r.status == "calculated"
    assert r.totals()["coc"] == D("3946.08") and r.totals()["toc"] == D("4844.31")
    assert r.totals()["total_costs"] == D("5443.13") and r.totals()["complete_coc"] is None
    assert amounts(r)["fuel"] == D("1788.05")


def test_fuel_price_change_through_part3_engine(base):
    session, b, _, _ = base
    r = run_variation(session, b, (Variation("fuel_price", "percent", D(10)),))
    changed = {n for n, a in amounts(r).items() if a != amounts(run_variation(session, b, ()))[n]}
    assert changed == {"fuel"} and amounts(r)["fuel"] == D("1966.86")  # 1788.0502... x 1.1
    fuel = r.case.summary.components["fuel"]
    assert fuel.status == ComponentStatus.CALCULATED_ASSUMPTION  # a varied price is not the observed benchmark
    assert r.case.summary.source_qualities()["fuel"].value == "mixed"
    assert r.modified[0].original_value == D("2.463") and r.modified[0].modified_value == D("2.7093")
    price = next(s for s in fuel.breakdown if s.get("step") == "price")
    block = next(s for s in fuel.breakdown if s.get("step") == "block fuel")
    assert price["value"] == "2.7093" and block["value"] == "2271.4893156832763"  # quantity unchanged


def test_fuel_burn_stress_test_is_labelled(base):
    session, b, _, _ = base
    r = run_variation(session, b, (Variation("fuel_burn", "percent", D(-10)),))
    assert amounts(r)["fuel"] == D("1609.25")
    assert any("not a physically validated simulation" in w for w in r.warnings)
    price = next(s for s in r.case.summary.components["fuel"].breakdown if s.get("step") == "price")
    assert price["value"] == "2.463"  # burn stress does not change the price


def test_maintenance_rate_change(base):
    session, b, _, _ = base
    r = run_variation(session, b, (Variation("airframe_maintenance_rate", "percent", D(20)),))
    assert amounts(r)["airframe_maintenance"] == D("531.15")  # 1.19764 x 360 + 100
    assert r.totals()["coc"] == D("3946.08") + D("71.86")


def test_utilization_changes_only_allocated_fixed_costs(base):
    session, b, _, _ = base
    before = amounts(run_variation(session, b, ()))
    after = amounts(run_variation(session, b, (Variation("annual_utilization", "percent", D(20)),)))
    changed = {n for n in before if before[n] != after[n]}
    assert changed == {"insurance", "general_administrative", "depreciation", "financing_interest"}
    for unchanged in ("fuel", "engine_llp", "crew_salaries", "administration"):
        assert before[unchanged] == after[unchanged]


def test_lease_and_financing_rate_changes(analytics_db, lease_scenario_data, owned_scenario_data):
    engine, ids = analytics_db
    with Session(engine) as session:
        lease = BaseCase(1, ids["variable"], scenario_from(lease_scenario_data), GC)
        r = run_variation(session, lease, (Variation("lease_payment", "percent", D(10)),))
        assert amounts(r)["operating_lease"] == D("1580.89")  # 330000 x 12 x 1.19764 / 3000
        owned = BaseCase(1, ids["variable"], scenario_from(owned_scenario_data), GC)
        r = run_variation(session, owned, (Variation("financing_interest_rate", "absolute", D("0.01")),))
        assert amounts(r)["financing_interest"] == D("718.59")  # 30M x 0.06 x 1.19764 / 3000
        bad = run_variation(session, owned, (Variation("lease_payment", "percent", D(10)),))
        assert bad.status == "calculation_error" and "does not apply" in bad.error


def test_payload_change_is_fixed_performance(base):
    session, b, _, _ = base
    b.payload = PayloadInput(D("5"), hypothetical_cargo=True, reference="test")
    r = run_variation(session, b, (Variation("revenue_cargo_payload", "value", D("8")),))
    assert r.metrics.traffic.revenue_tonnes == D("8")
    assert r.totals()["coc"] == D("3946.08")  # costs unchanged (passenger scenario has no cargo-sales input)
    assert any("fixed-performance" in w for w in r.warnings)
    too_heavy = run_variation(session, b, (Variation("revenue_cargo_payload", "value", D("12")),))
    assert too_heavy.status == "calculation_error" and "exceeds" in too_heavy.error


def test_base_and_saved_records_are_immutable(base):
    session, b, engine, ids = base
    raw_before = copy.deepcopy(b.scenario.raw)
    file_before = (SCENARIOS / "example_owned_aircraft.json").read_bytes()
    with engine.connect() as conn:
        rows_before = conn.execute(text("SELECT * FROM full_cost_component ORDER BY 1")).all()
        scen_before = conn.execute(text("SELECT * FROM cost_scenario ORDER BY 1")).all()
    for v in (Variation("fuel_price", "percent", D(20)), Variation("crew_compensation", "percent", D(-5)),
              Variation("useful_life", "absolute", D(5))):
        assert run_variation(session, b, (v,)).status == "calculated"
    assert b.scenario.raw == raw_before
    assert (SCENARIOS / "example_owned_aircraft.json").read_bytes() == file_before
    with engine.connect() as conn:
        assert conn.execute(text("SELECT * FROM full_cost_component ORDER BY 1")).all() == rows_before
        assert conn.execute(text("SELECT * FROM cost_scenario ORDER BY 1")).all() == scen_before


def test_variation_rules(base):
    session, b, _, _ = base
    with pytest.raises(AnalyticsInputError, match="unknown parameter"):
        Variation("acquisition_value", "percent", D(10))  # not exposed: does not drive any charge
    with pytest.raises(AnalyticsInputError, match="supports change types"):
        Variation("annual_utilization", "absolute", D(10))
    r = run_variation(session, b, (Variation("crew_compensation", "absolute", D(1000)),))
    assert r.status == "calculation_error" and "only percent" in r.error  # two roles
    with pytest.raises(AnalyticsInputError, match="only once"):
        run_variation(session, b, (Variation("fuel_price", "percent", D(1)), Variation("fuel_price", "percent", D(2))))


def test_reproducible_hashes(base):
    session, b, _, _ = base
    v = (Variation("fuel_price", "percent", D(10)),)
    first, second = run_variation(session, b, v), run_variation(session, b, v)
    assert first.input_hash == second.input_hash and first.to_dict()["totals"] == second.to_dict()["totals"]
    assert run_variation(session, b, (Variation("fuel_price", "percent", D(11)),)).input_hash != first.input_hash


def test_one_way_sensitivity(base):
    session, b, _, _ = base
    result = one_way(session, b, "fuel_price", "percent", [D(-10), D(0), D(10)])
    minus, zero, plus = result.rows
    assert zero.deltas["coc"] == (D("0.00"), D(0)) and zero.components_affected == []
    assert plus.deltas["coc"][0] == D("178.81") and plus.components_affected == ["fuel"]
    assert plus.deltas["coc"][1] == D("178.81") / D("3946.08") * 100
    assert plus.deltas["complete_coc"] == (None, None)  # complete total unavailable: no delta
    assert minus.outputs["coc_per_block_hour"] < zero.outputs["coc_per_block_hour"]
    assert "not forecasts" in result.statement


def test_sensitivity_withholds_deltas_when_coverage_changes(base):
    session, b, _, _ = base
    result = one_way(session, b, "residual_value", "value", [D("60000000")])  # residual > depreciable -> failed
    row = result.rows[0]
    assert row.result.case.summary.components["depreciation"].status == ComponentStatus.FAILED_VALIDATION
    assert "toc" in row.coverage_changed and row.deltas["toc"] == (None, None)
    assert row.deltas["coc"][0] == D("0.00")  # COC does not include depreciation


def test_two_way_grid(base):
    session, b, _, _ = base
    result = two_way(session, b, ("fuel_price", "percent", [D(0), D(10)]),
                     ("annual_utilization", "percent", [D(0), D(20)]))
    assert len(result.rows) == 4 and result.analysis_type == "sensitivity_2d"
    corner = next(r for r in result.rows if [v.change for v in r.variations] == [D(10), D(20)])
    assert corner.outputs["coc"] == D("3866.25") + D("178.81")
    assert "not probability estimates" in result.statement
    with pytest.raises(AnalyticsInputError, match="limit"):
        two_way(session, b, ("fuel_price", "percent", [D(i) for i in range(11)]),
                ("annual_utilization", "percent", [D(i) for i in range(11)]))
    with pytest.raises(AnalyticsInputError, match="two different"):
        two_way(session, b, ("fuel_price", "percent", [D(0)]), ("fuel_price", "percent", [D(1)]))


def test_sensitivity_serialises(base):
    session, b, _, _ = base
    data = one_way(session, b, "llp_reserve", "value", [D(150)]).to_dict()
    json.dumps(data)
    assert data["rows"][0]["outputs"]["coc"] == str(D("3946.08") + D("100.00"))  # 2 engines x 1 cycle x 50 more
