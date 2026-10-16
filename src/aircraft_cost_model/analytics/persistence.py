"""Persist analytics runs immutably; identical inputs return the existing run.

The run's ``input_hash`` covers the analysis type, every request parameter,
the input hashes of the underlying estimates (Part 3/4) and the analytics
version. Saving the same request again does not create a new row: the stored
``result_json`` is compared with the new result (timestamps excluded) and the
outcome is reported as a reproducibility check.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics import ANALYTICS_VERSION
from aircraft_cost_model.analytics.benchmarks import BenchmarkComparisonResult
from aircraft_cost_model.analytics.metrics import UnitMetric
from aircraft_cost_model.analytics.sensitivity import SensitivityRow
from aircraft_cost_model.costs.currency import plain
from aircraft_cost_model.fullcost.persistence import get_or_create_scenario
from aircraft_cost_model.models import AnalyticsRun, BenchmarkComparison, ScenarioResult, UnitCostMetric

VOLATILE_KEYS = {"calculated_at"}


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def canonical(value: Any) -> str:
    return json.dumps(_stable(value), sort_keys=True, default=str)


def run_hash(analysis_type: str, parameters: dict[str, Any]) -> str:
    return hashlib.sha256(canonical({"type": analysis_type, "parameters": parameters,
                                     "version": ANALYTICS_VERSION}).encode()).hexdigest()


@dataclass
class RunRecord:
    analysis_type: str
    status: str
    parameters: dict[str, Any]
    result: dict[str, Any]
    coverage_status: str
    source_quality_summary: str
    operational_validity: str | None = None
    flight_estimate_id: int | None = None
    variable_cost_estimate_id: int | None = None
    full_cost_estimate_id: int | None = None
    base_scenario_id: int | None = None
    pricing_date: date | None = None
    reporting_currency: str | None = None
    distance_basis: str | None = None
    payload_basis: str | None = None
    warnings: list[str] | None = None


@dataclass(frozen=True)
class SaveOutcome:
    analytics_run_id: int
    created: bool
    reproduced: bool | None  # None when newly created

    def describe(self) -> str:
        if self.created:
            return f"analytics_run_id={self.analytics_run_id} (created)"
        verdict = "reproduced exactly" if self.reproduced else "DIFFERS from stored result"
        return f"analytics_run_id={self.analytics_run_id} (existing run; result {verdict})"


def save_run(engine: Engine, record: RunRecord, metrics: list[tuple[str, int | None, UnitMetric]] = (),
             scenario_rows: list[SensitivityRow] = (), comparisons: list[BenchmarkComparisonResult] = ()) -> SaveOutcome:
    input_hash = run_hash(record.analysis_type, record.parameters)
    result_json = canonical(record.result)
    with Session(engine) as session, session.begin():
        existing = session.scalar(select(AnalyticsRun).where(AnalyticsRun.input_hash == input_hash))
        if existing is not None:
            return SaveOutcome(existing.analytics_run_id, False, existing.result_json == result_json)
        run = AnalyticsRun(
            analysis_type=record.analysis_type, status=record.status, flight_estimate_id=record.flight_estimate_id,
            variable_cost_estimate_id=record.variable_cost_estimate_id,
            full_cost_estimate_id=record.full_cost_estimate_id, base_scenario_id=record.base_scenario_id,
            pricing_date=record.pricing_date, reporting_currency=record.reporting_currency,
            distance_basis=record.distance_basis, payload_basis=record.payload_basis,
            coverage_status=record.coverage_status, operational_validity=record.operational_validity,
            source_quality_summary=record.source_quality_summary, parameters_json=canonical(record.parameters),
            result_json=result_json, warnings_json=json.dumps(record.warnings or []),
            calculation_version=ANALYTICS_VERSION, input_hash=input_hash)
        for label, flight_id, m in metrics:
            run.metrics.append(UnitCostMetric(
                case_label=label, flight_estimate_id=flight_id, metric_name=m.metric_name, label=m.label,
                cost_basis=m.cost_basis, cost_measure=m.cost_measure, numerator_amount=m.numerator_amount,
                currency=m.currency, denominator_value=m.denominator_value, denominator_unit=m.denominator_unit,
                denominator_basis=m.denominator_basis, metric_value=m.metric_value, metric_unit=m.metric_unit,
                metric_status=m.metric_status, coverage_status=m.coverage_status,
                operational_validity=m.operational_validity, source_quality=m.source_quality,
                pricing_date=date.fromisoformat(m.pricing_date), fx_basis=m.fx_basis, payload_basis=m.payload_basis,
                calculation_method=m.calculation_method,
                components_json=json.dumps({"included": list(m.components_included),
                                            "missing": list(m.components_missing)}),
                warnings_json=json.dumps(m.warnings)))
        for row in scenario_rows:
            r = row.result
            variant_id = None
            if (r.case is not None and r.case.scenario is not None
                    and r.case.scenario.content_hash != record.parameters.get("base_scenario_hash")):
                # immutable variant scenario row (stored once per content hash); the base is never modified
                variant_id = get_or_create_scenario(session, r.case.scenario,
                                                    r.case.summary.source_quality_summary).scenario_id
            totals = r.totals()
            s = r.case.summary if r.case else None
            run.scenario_results.append(ScenarioResult(
                label=row.label, variations_json=json.dumps([v.to_dict() for v in row.variations]),
                modified_values_json=json.dumps([m.to_dict() for m in r.modified]), variant_scenario_id=variant_id,
                status=r.status, fuel_cost=s.components["fuel"].amount if s else None,
                direct_variable_subtotal=totals.get("direct_variable"), cash_operating_subtotal=totals.get("coc"),
                total_operating_subtotal=totals.get("toc"), total_cost_subtotal=totals.get("total_costs"),
                complete_coc=totals.get("complete_coc"), complete_toc=totals.get("complete_toc"),
                complete_total_costs=totals.get("complete_total_costs"),
                components_json=json.dumps({n: {"amount": None if c.amount is None else plain(c.amount),
                                                "status": c.status.value} for n, c in (s.components.items() if s else [])}),
                deltas_json=json.dumps({k: [None if a is None else plain(a), None if p is None else plain(p)]
                                        for k, (a, p) in row.deltas.items()}),
                coverage_status=({"complete": "complete", "incomplete": "partial",
                                  "failed_validation": "calculation_error"}[s.cost_coverage_status]
                                 if s else "calculation_error"),
                operational_validity=s.operational_validity if s else None,
                source_quality=s.source_quality_summary if s else None, calculated_at=r.calculated_at,
                input_hash=r.input_hash, warnings_json=json.dumps(r.warnings + ([r.error] if r.error else []))))
        for c in comparisons:
            run.benchmark_comparisons.append(BenchmarkComparison(
                model_metric=c.model_metric, model_value=c.model_value, model_unit=c.model_unit,
                benchmark_metric=f"{c.benchmark.selection.source}:{c.benchmark.selection.cost_category}_per_"
                                 f"{c.benchmark.denominator}",
                benchmark_value=c.benchmark.value, benchmark_value_converted=c.benchmark_value_converted,
                benchmark_unit=c.benchmark_unit, benchmark_selection_json=canonical(c.benchmark.to_dict()),
                comparability=c.comparability, checks_json=json.dumps([x.to_dict() for x in c.checks]),
                reasons_json=json.dumps(c.reasons), absolute_difference=c.absolute_difference,
                percentage_difference=c.percentage_difference, fx_basis=c.fx_basis))
        session.add(run)
        session.flush()
        return SaveOutcome(run.analytics_run_id, True, None)
