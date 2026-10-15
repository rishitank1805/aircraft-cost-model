"""End-to-end Part 4: saved flight + saved Part 3 estimate + scenario -> full cost estimate (offline)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from aircraft_cost_model.costs.calculator import VariableCostRequest, calculate_variable_costs
from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.costs.persistence import save_variable_cost_estimate
from aircraft_cost_model.database import create_db_engine
from aircraft_cost_model.fullcost.aggregate import Category
from aircraft_cost_model.fullcost.calculator import FullCostInputError, calculate_full_costs
from aircraft_cost_model.fullcost.persistence import save_full_cost_estimate
from aircraft_cost_model.models import (
    AircraftType,
    CostAssumption,
    CostComponent,
    CostScenario,
    FlightEstimate,
    FullCostComponent,
    FullCostEstimate,
)
from conftest import scenario_from

PRICING = date(2025, 1, 15)


@pytest.fixture
def full_engine(cost_db):
    engine = create_db_engine(cost_db)
    with Session(engine) as session:
        result = calculate_variable_costs(session, VariableCostRequest(flight_estimate_id=1, pricing_date=PRICING))
    assert save_variable_cost_estimate(engine, result) == 1
    yield engine
    engine.dispose()


def run(engine, data, flight=1, variable=1):
    with Session(engine) as session:
        return calculate_full_costs(session, flight, variable, scenario_from(data))


def test_owned_end_to_end_preserves_part3(full_engine, owned_scenario_data):
    result = run(full_engine, owned_scenario_data)
    s = result.summary
    with Session(full_engine) as session:
        fuel_row = session.scalar(select(CostComponent).where(CostComponent.component_name == "fuel"))
        flight = session.get(FlightEstimate, 1)
    assert s.components["fuel"].amount == fuel_row.amount  # Part 3 result reused, not recomputed
    assert result.part3_row_ids["fuel"] == fuel_row.cost_component_id
    block_hours = Decimal(str(flight.block_time_min)) / 60
    assert s.components["airframe_maintenance"].amount == (block_hours * 300 + 100).quantize(Decimal("0.01"))
    assert s.components["operating_lease"].status == ComponentStatus.NOT_APPLICABLE
    assert s.components["cargo_sales"].status == ComponentStatus.NOT_APPLICABLE
    assert s.operational_validity == flight.calculation_status  # dimension B carried unchanged
    assert s.coc[1] is None and s.cost_coverage_status == "incomplete"  # navigation unavailable without zones
    assert "explicit_user_assumption" in s.source_quality_summary


def test_lease_excludes_depreciation_and_financing(full_engine, lease_scenario_data):
    s = run(full_engine, lease_scenario_data).summary
    assert s.components["operating_lease"].is_calculated
    assert s.components["depreciation"].status == ComponentStatus.NOT_APPLICABLE
    assert s.components["financing_interest"].status == ComponentStatus.NOT_APPLICABLE
    assert s.coc[0] == s.toc[0] == s.total[0]


def test_save_precision_links_and_reproducibility(full_engine, owned_scenario_data):
    first = run(full_engine, owned_scenario_data)
    second = run(full_engine, owned_scenario_data)
    assert first.input_hash == second.input_hash
    id1 = save_full_cost_estimate(full_engine, first)
    id2 = save_full_cost_estimate(full_engine, second)
    with Session(full_engine) as session:
        assert session.scalar(select(func.count()).select_from(CostScenario)) == 1  # stored once per content hash
        assert session.scalar(select(func.count()).select_from(CostAssumption)) == len(first.scenario.values)
        estimate = session.get(FullCostEstimate, id1)
        assert estimate.variable_cost_estimate_id == 1 and estimate.flight_estimate_id == 1
        assert estimate.complete_coc is None and estimate.cash_operating_subtotal == first.summary.coc[0]
        fuel = session.scalar(select(FullCostComponent).where(FullCostComponent.full_cost_estimate_id == id1,
                                                              FullCostComponent.component_name == "fuel"))
        assert fuel.origin == "part3_variable_cost_estimate" and fuel.part3_cost_component_id is not None
        unavailable = [c for c in estimate.components if not ComponentStatus(c.status).is_calculated]
        assert all(c.amount is None for c in unavailable)  # never stored as zero
        assert len(estimate.components) == 17 and id2 == id1 + 1
    with full_engine.connect() as conn:
        raw = conn.execute(text("SELECT amount FROM full_cost_component WHERE component_name='airframe_maintenance'"
                                " AND full_cost_estimate_id=:i"), {"i": id1}).scalar_one()
        assumption = conn.execute(text("SELECT value_decimal FROM cost_assumption WHERE parameter_name="
                                       "'crew.salaries.roles[0].annual_compensation'")).scalar_one()
    assert isinstance(raw, str) and raw == f"{first.summary.components['airframe_maintenance'].amount:f}"
    assert assumption == "200000"


def test_scenario_change_changes_hash(full_engine, owned_scenario_data):
    before = run(full_engine, owned_scenario_data).input_hash
    owned_scenario_data["maintenance"]["airframe"]["rate_per_block_hour"]["value"] = "301"
    assert run(full_engine, owned_scenario_data).input_hash != before


def test_mismatched_and_missing_estimates_rejected(full_engine, owned_scenario_data, openap_provider):
    from aircraft_cost_model.performance.persistence import save_flight_estimate
    from aircraft_cost_model.performance.planner import FlightRequest, estimate_flight

    with Session(full_engine) as session:
        other = estimate_flight(session, FlightRequest("A320", "FRA", "CDG", 8000), openap_provider)
    assert save_flight_estimate(full_engine, other) == 2
    with pytest.raises(FullCostInputError, match="belongs to flight_estimate 1"):
        run(full_engine, owned_scenario_data, flight=2, variable=1)
    with pytest.raises(FullCostInputError, match="does not exist"):
        run(full_engine, owned_scenario_data, flight=1, variable=99)
    with pytest.raises(FullCostInputError, match="does not exist"):
        run(full_engine, owned_scenario_data, flight=99, variable=1)


def test_currency_and_pricing_date_must_match(full_engine, owned_scenario_data):
    owned_scenario_data["pricing_date"] = "2025-02-01"
    with pytest.raises(FullCostInputError, match="pricing date"):
        run(full_engine, owned_scenario_data)
    owned_scenario_data.pop("pricing_date")
    owned_scenario_data["reporting_currency"] = "USD"
    with pytest.raises(FullCostInputError, match="currency"):
        run(full_engine, owned_scenario_data)


def test_legacy_v1_rejected(full_engine, owned_scenario_data):
    with Session(full_engine) as session, session.begin():
        session.get(FlightEstimate, 1).fuel_accounting_basis = "v1"
    with pytest.raises(FullCostInputError, match="v1"):
        run(full_engine, owned_scenario_data)


def test_unsupported_freighter_not_priced(full_engine, owned_scenario_data):
    with Session(full_engine) as session, session.begin():
        freighter = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == "B777F"))
        session.get(FlightEstimate, 1).aircraft_type_id = freighter.aircraft_type_id
    s = run(full_engine, owned_scenario_data).summary
    part4 = [c for n, c in s.components.items() if n not in ("fuel", "navigation", "terminal_navigation", "landing",
                                                               "ground_handling")]
    assert all(c.status == ComponentStatus.UNSUPPORTED_AIRCRAFT and c.amount is None for c in part4)


def test_part3_rows_unchanged_by_part4(full_engine, owned_scenario_data):
    with full_engine.connect() as conn:
        before = conn.execute(text("SELECT * FROM cost_component ORDER BY cost_component_id")).all()
    save_full_cost_estimate(full_engine, run(full_engine, owned_scenario_data))
    with full_engine.connect() as conn:
        assert conn.execute(text("SELECT * FROM cost_component ORDER BY cost_component_id")).all() == before


def test_cli_rejects_mismatch_and_prints_na(full_engine, owned_scenario_data, monkeypatch, capsys, tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("cfc", Path(__file__).parents[1] / "scripts" / "calculate_full_costs.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    scenario_file = tmp_path / "s.json"
    scenario_file.write_text(json.dumps(owned_scenario_data), encoding="utf-8")
    monkeypatch.setenv("ACM_DATABASE_PATH", full_engine.url.database)
    assert cli.main(["--flight-estimate-id", "1", "--variable-cost-estimate-id", "1", "--scenario", str(scenario_file)]) == 0
    out = capsys.readouterr().out
    assert "N/A" in out and "Complete COC          : unavailable" in out and "B. Operational validity" in out
    assert cli.main(["--flight-estimate-id", "2", "--variable-cost-estimate-id", "1", "--scenario", str(scenario_file)]) == 1


def test_source_classification_preserved(full_engine, owned_scenario_data):
    from aircraft_cost_model.costs.coverage import SourceType
    from aircraft_cost_model.fullcost.aggregate import SourceQuality

    result = run(full_engine, owned_scenario_data)
    s, qualities = result.summary, result.summary.source_qualities()
    fuel = s.components["fuel"]
    assert fuel.source_type == SourceType.PUBLIC_MARKET_BENCHMARK and fuel.status == ComponentStatus.CALCULATED_BENCHMARK
    assert qualities["fuel"] == SourceQuality.PUBLIC_MARKET_BENCHMARK  # never observed airline expense
    for name in ("airframe_maintenance", "crew_salaries", "insurance", "depreciation", "financing_interest"):
        assert s.components[name].source_type == SourceType.USER_ASSUMPTION
        assert qualities[name] == SourceQuality.EXPLICIT_USER_ASSUMPTION
        assert {a.source_type for a in s.components[name].assumptions} == {"illustrative_assumption"}
    assert "observed_public_data" not in s.source_quality_summary  # no tariff was priced for this flight
    estimate_id = save_full_cost_estimate(full_engine, result)
    with Session(full_engine) as session:
        rows = {c.component_name: c for c in session.get(FullCostEstimate, estimate_id).components}
        part3 = {c.component_name: c for c in session.scalars(select(CostComponent))}
    for name in ("fuel", "navigation", "terminal_navigation", "landing", "ground_handling"):
        assert (rows[name].source_type, rows[name].status, rows[name].amount) == (
            part3[name].source_type, part3[name].status, part3[name].amount)
    assert rows["fuel"].source_quality == "public_market_benchmark"
    assert json.loads(rows["crew_salaries"].assumptions_json)[0]["source_type"] == "illustrative_assumption"


def test_owned_subtotals_reconcile(full_engine, owned_scenario_data):
    s = run(full_engine, owned_scenario_data).summary
    amounts = {n: c.amount for n, c in s.components.items()}
    dv = ["fuel", "airframe_maintenance", "engine_maintenance", "engine_llp", "crew_allowances"]
    assert s.category(Category.DIRECT_VARIABLE).calculated_subtotal == sum(amounts[n] for n in dv)
    assert s.category(Category.DIRECT_FIXED).calculated_subtotal == amounts["crew_salaries"] + amounts["insurance"]
    assert s.category(Category.INDIRECT).calculated_subtotal == amounts["administration"] + amounts["general_administrative"]
    coc = sum(s.category(c).calculated_subtotal for c in (Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT))
    assert s.coc[0] == coc
    assert s.toc[0] == coc + amounts["depreciation"]
    assert s.total[0] == coc + amounts["depreciation"] + amounts["financing_interest"]
    unavailable = {n for n, a in amounts.items() if a is None} - {"operating_lease", "cargo_sales"}
    assert unavailable == set(s.coc[2]) == set(s.total[2])  # every unavailable component blocks completeness
    assert s.coc[1] is s.toc[1] is s.total[1] is None
