"""Persist variable cost estimates in one transaction."""

from __future__ import annotations

import json
import logging

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from aircraft_cost_model.costs.calculator import VariableCostResult
from aircraft_cost_model.models import CostComponent, VariableCostEstimate

logger = logging.getLogger(__name__)


def save_variable_cost_estimate(engine: Engine, result: VariableCostResult) -> int:
    """Store the estimate and every component (including unavailable ones). Returns its id.

    ``complete_variable_cost`` is stored only when the summary is complete;
    unavailable components are stored with ``amount = NULL``.
    """
    summary = result.summary
    with Session(engine) as session, session.begin():
        estimate = VariableCostEstimate(
            flight_estimate_id=result.flight.flight_estimate_id,
            pricing_date=summary.pricing_date,
            reporting_currency=summary.reporting_currency,
            calculated_subtotal=summary.calculated_subtotal,
            complete_variable_cost=summary.complete_variable_cost,
            coverage_status=summary.coverage_status,
            components_calculated=len(summary.calculated),
            components_applicable=len(summary.applicable),
            calculation_version=result.calculation_version,
            input_hash=result.input_hash,
        )
        estimate.components = [
            CostComponent(
                component_name=c.component,
                amount=c.amount,
                currency=c.currency,
                status=c.status.value,
                source_type=c.source_type.value,
                partial_scope=c.partial_scope,
                source_id=c.source_id,
                source_reference=c.source_reference,
                pricing_observation_date=c.observation_date,
                calculation_method=c.calculation_method,
                breakdown_json=json.dumps(c.breakdown, default=str),
                assumptions_json=json.dumps([a.to_dict() for a in c.assumptions]),
                warnings_json=json.dumps(c.warnings + ([f"missing inputs: {c.missing_inputs}"] if c.missing_inputs else [])),
            )
            for c in summary.components
        ]
        session.add(estimate)
        session.flush()
        estimate_id = estimate.variable_cost_estimate_id
    logger.info("variable_cost_estimate_saved", extra={"id": estimate_id, "coverage": summary.coverage_status})
    return estimate_id
