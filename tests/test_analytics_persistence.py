"""Migration 0007, analytics persistence, idempotency, decimal precision and historical preservation."""

from __future__ import annotations

from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.metrics import DistanceBasis, DistanceInput, unit_metrics
from aircraft_cost_model.analytics.cases import load_saved_case
from aircraft_cost_model.analytics.persistence import RunRecord, run_hash, save_run
from aircraft_cost_model.analytics.scenarios import base_from_saved
from aircraft_cost_model.analytics.sensitivity import one_way
from aircraft_cost_model.database import _alembic_config, create_db_engine, current_revision, head_revision
from aircraft_cost_model.models import AnalyticsRun, CostScenario, ScenarioResult, UnitCostMetric

PART5_TABLES = {"analytics_run", "unit_cost_metric", "scenario_result", "benchmark_observation",
                "benchmark_comparison", "price_index_observation", "benchmark_adjustment"}
GC = DistanceInput(DistanceBasis.GREAT_CIRCLE)
HISTORICAL = ("flight_estimate", "flight_phase", "variable_cost_estimate", "cost_component", "cost_scenario",
              "cost_assumption", "full_cost_estimate", "full_cost_component", "data_source", "fuel_price",
              "exchange_rate")


def snapshot(engine, tables=HISTORICAL):
    with engine.connect() as conn:
        return {t: conn.execute(text(f"SELECT * FROM {t} ORDER BY 1")).all() for t in tables}


def test_0007_is_additive_and_reversible(analytics_db):
    engine, ids = analytics_db
    url = str(engine.url)
    assert current_revision(engine) == head_revision()
    assert PART5_TABLES <= set(inspect(engine).get_table_names())
    before = snapshot(engine)
    engine.dispose()
    command.downgrade(_alembic_config(url), "0006_part4_full_costs")
    engine = create_db_engine(url)
    assert not PART5_TABLES & set(inspect(engine).get_table_names())
    assert snapshot(engine) == before  # Part 1-4 rows untouched
    engine.dispose()
    command.upgrade(_alembic_config(url), "head")
    engine = create_db_engine(url)
    assert snapshot(engine) == before
    engine.dispose()


def test_foreign_keys(analytics_db):
    engine, _ = analytics_db
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("INSERT INTO analytics_run (analysis_type, status, full_cost_estimate_id, coverage_status, "
                          "source_quality_summary, parameters_json, result_json, warnings_json, calculation_version, "
                          "input_hash, created_at) VALUES ('x','x',999,'x','x','{}','{}','[]','v','h','2026-10-15')"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("INSERT INTO unit_cost_metric (analytics_run_id, case_label, metric_name, label, cost_basis, "
                          "cost_measure, currency, denominator_unit, denominator_basis, metric_unit, metric_status, "
                          "coverage_status, operational_validity, source_quality, pricing_date, fx_basis, "
                          "calculation_method, components_json, warnings_json) VALUES (999,'c','m','l','b','m','EUR',"
                          "'u','b','u','s','c','v','q','2025-01-15','f','m','{}','[]')"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("INSERT INTO benchmark_adjustment (benchmark_id, status, original_currency, original_period, "
                          "index_series_id, target_date, methodology, created_at) VALUES (999,'adjusted','USD','p','s',"
                          "'2025-01-15','m','2026-10-15')"))


def _metrics_record(case, result):
    return RunRecord(analysis_type="unit_metrics", status="calculated",
                     parameters={"case": case.input_hash, "distance": "great_circle"}, result=result.to_dict(),
                     coverage_status=result.cost_coverage, source_quality_summary=result.source_quality,
                     operational_validity=result.operational_validity, flight_estimate_id=case.facts.flight_estimate_id,
                     full_cost_estimate_id=case.full_cost_estimate_id, pricing_date=case.pricing_date,
                     reporting_currency="EUR", distance_basis="great_circle")


def test_unit_metric_run_is_idempotent_and_exact(analytics_db):
    engine, ids = analytics_db
    before = snapshot(engine)
    with Session(engine) as session:
        case = load_saved_case(session, ids["full"])
    result = unit_metrics(case, GC)
    record = _metrics_record(case, result)
    metrics = [(case.label, 1, m) for m in result.metrics]
    first = save_run(engine, record, metrics=metrics)
    again = save_run(engine, record, metrics=metrics)
    assert first.created and not again.created and again.reproduced and again.analytics_run_id == first.analytics_run_id
    record.result = {**record.result, "cost_coverage": "tampered"}
    assert save_run(engine, record).reproduced is False  # same inputs, different result is detected
    with Session(engine) as session:
        run = session.get(AnalyticsRun, first.analytics_run_id)
        assert run.input_hash == run_hash("unit_metrics", record.parameters)
        stored = session.scalar(select(UnitCostMetric).where(UnitCostMetric.metric_name == "coc_per_block_hour",
                                                             UnitCostMetric.cost_measure == "calculated_subtotal"))
        assert stored.metric_value == result.metric("coc_per_block_hour").metric_value  # exact quotient kept
        assert stored.label == "Partial COC per block hour"
        complete = session.scalar(select(UnitCostMetric).where(UnitCostMetric.metric_name == "coc_per_block_hour",
                                                               UnitCostMetric.cost_measure == "complete_total"))
        assert complete.metric_value is None and complete.metric_status == "unavailable"
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT metric_value, typeof(metric_value) FROM unit_cost_metric WHERE "
                                "metric_name='coc_per_block_hour' AND cost_measure='calculated_subtotal'")).one()
    assert raw[1] == "text" and Decimal(raw[0]) == result.metric("coc_per_block_hour").metric_value
    assert snapshot(engine) == before  # historical Part 1-4 rows unchanged


def test_sensitivity_run_stores_immutable_variant_scenarios(analytics_db):
    engine, ids = analytics_db
    with Session(engine) as session:
        base = base_from_saved(session, ids["full"], GC)
        result = one_way(session, base, "airframe_maintenance_rate", "percent", [Decimal(0), Decimal(10)])
    with Session(engine) as session:
        scenarios_before = session.scalars(select(CostScenario)).all()
        base_json = scenarios_before[0].content_json
    outcome = save_run(engine, RunRecord(
        analysis_type="sensitivity_1d", status="calculated",
        parameters={"base_scenario_hash": base.scenario.content_hash, "levels": ["0", "10"]}, result=result.to_dict(),
        coverage_status="partial", source_quality_summary="mixed", full_cost_estimate_id=ids["full"],
        base_scenario_id=base.base_scenario_id), scenario_rows=result.rows)
    with Session(engine) as session:
        rows = session.scalars(select(ScenarioResult).where(ScenarioResult.analytics_run_id == outcome.analytics_run_id)
                               .order_by(ScenarioResult.scenario_result_id)).all()
        identity, plus = rows
        assert identity.variant_scenario_id is None  # 0 % reproduces the base scenario: nothing new stored
        variant = session.get(CostScenario, plus.variant_scenario_id)
        assert variant.content_hash != base.scenario.content_hash and "+variation" in variant.scenario_version
        assert session.get(CostScenario, base.base_scenario_id).content_json == base_json  # base untouched
        assert plus.cash_operating_subtotal == Decimal("3946.08") + Decimal("35.93")
        assert plus.input_hash and plus.coverage_status == "partial"
