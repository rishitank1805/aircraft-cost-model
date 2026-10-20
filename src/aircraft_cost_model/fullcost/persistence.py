"""Persist scenarios and full-cost estimates in one transaction."""

from __future__ import annotations

import json

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from aircraft_cost_model.fullcost.aggregate import COMPONENT_CATEGORY, Category
from aircraft_cost_model.fullcost.calculator import PART3_COMPONENTS, FullCostResult
from aircraft_cost_model.fullcost.scenario import Scenario
from aircraft_cost_model.models import CostAssumption, CostScenario, FullCostComponent, FullCostEstimate


def get_or_create_scenario(session: Session, scenario: Scenario, source_quality_summary: str) -> CostScenario:
    """Store the scenario once per content hash, with every typed assumption."""
    existing = session.scalar(select(CostScenario).where(CostScenario.content_hash == scenario.content_hash))
    if existing is not None:
        return existing
    row = CostScenario(
        name=scenario.name, description=scenario.description, scenario_version=scenario.scenario_version,
        ownership_mode=scenario.ownership_mode, flight_type=scenario.flight_type,
        reporting_currency=scenario.reporting_currency, pricing_date=scenario.pricing_date,
        source_quality_summary=source_quality_summary, source_path=scenario.source_path,
        content_hash=scenario.content_hash, content_json=scenario.canonical_json,
    )
    row.assumptions = [
        CostAssumption(component=path.split(".")[0], parameter_name=path, value_decimal=v.value, unit=v.unit,
                       currency=v.currency, effective_from=v.effective_from, effective_to=v.effective_to,
                       reference_period=v.reference_period, source_type=v.source_type,
                       source_reference=v.source_reference, notes=v.notes)
        for path, v in sorted(scenario.values.items())
    ]
    session.add(row)
    session.flush()
    return row


def save_full_cost_estimate(engine: Engine, result: FullCostResult) -> int:
    summary = result.summary
    qualities = summary.source_qualities()
    with Session(engine) as session, session.begin():
        scenario_row = get_or_create_scenario(session, result.scenario, summary.source_quality_summary)
        coc, toc, total = summary.coc, summary.toc, summary.total
        estimate = FullCostEstimate(
            flight_estimate_id=result.flight_estimate_id, variable_cost_estimate_id=result.variable_cost_estimate_id,
            scenario_id=scenario_row.scenario_id, pricing_date=result.basis.pricing_date,
            reporting_currency=result.basis.reporting_currency, ownership_mode=result.scenario.ownership_mode,
            direct_variable_subtotal=summary.category(Category.DIRECT_VARIABLE).calculated_subtotal,
            direct_fixed_subtotal=summary.category(Category.DIRECT_FIXED).calculated_subtotal,
            indirect_subtotal=summary.category(Category.INDIRECT).calculated_subtotal,
            noncash_subtotal=summary.category(Category.NONCASH).calculated_subtotal,
            financing_subtotal=summary.category(Category.FINANCING).calculated_subtotal,
            cash_operating_subtotal=coc[0], total_operating_subtotal=toc[0], total_cost_subtotal=total[0],
            complete_coc=coc[1], complete_toc=toc[1], complete_total_costs=total[1],
            cost_coverage_status=summary.cost_coverage_status,
            operational_validity_status=summary.operational_validity,
            source_quality_summary=summary.source_quality_summary,
            calculation_version=result.calculation_version, input_hash=result.input_hash,
        )
        estimate.components = [
            FullCostComponent(
                component_name=name, category=COMPONENT_CATEGORY[name].value, amount=c.amount, currency=c.currency,
                status=c.status.value, source_type=c.source_type.value, source_quality=qualities[name].value,
                origin="part3_variable_cost_estimate" if name in PART3_COMPONENTS else "part4_scenario",
                part3_cost_component_id=result.part3_row_ids.get(name), source_reference=c.source_reference,
                calculation_method=c.calculation_method, breakdown_json=json.dumps(c.breakdown, default=str),
                assumptions_json=json.dumps([a.to_dict() for a in c.assumptions]),
                warnings_json=json.dumps(c.warnings + ([f"missing inputs: {c.missing_inputs}"] if c.missing_inputs else [])),
            )
            for name, c in summary.components.items()
        ]
        session.add(estimate)
        session.flush()
        return estimate.full_cost_estimate_id
