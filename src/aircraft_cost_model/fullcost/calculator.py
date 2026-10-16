"""Full operating cost orchestration for a saved flight estimate + saved variable-cost estimate + scenario.

Part 3 results are **read from the saved** ``variable_cost_estimate`` /
``cost_component`` rows (never recomputed), so historical variable costs are
reproduced exactly. Part 4 components are calculated from the scenario.

Checks (each raises :class:`FullCostInputError`):
- the variable-cost estimate belongs to the same flight estimate;
- the flight estimate uses fuel accounting ``v2``;
- the scenario's reporting currency and pricing date (if given) match the
  variable-cost estimate.

Aircraft without a supported performance model (e.g. dedicated freighters)
get ``unsupported_aircraft`` for every Part 4 component; no passenger
substitute is used.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model import __version__
from aircraft_cost_model.costs.coverage import Assumption, ComponentResult, ComponentStatus, SourceType
from aircraft_cost_model.costs.currency import DatabaseRateProvider, RateProvider, to_decimal
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.fullcost import crew, indirect, insurance, maintenance, ownership
from aircraft_cost_model.fullcost.aggregate import FullCostSummary
from aircraft_cost_model.fullcost.common import FlightBasis
from aircraft_cost_model.fullcost.scenario import Scenario
from aircraft_cost_model.models import AircraftType, CostComponent, FlightEstimate, VariableCostEstimate

CALCULATION_VERSION = f"full_costs v1 (aircraft_cost_model {__version__})"
PART3_COMPONENTS = ("fuel", "navigation", "terminal_navigation", "landing", "ground_handling")


class FullCostInputError(CostCalculationError, ValueError):
    """Inconsistent inputs (mismatched estimates, currency, date or fuel accounting)."""


@dataclass
class FullCostResult:
    flight_estimate_id: int
    variable_cost_estimate_id: int
    scenario: Scenario
    basis: FlightBasis
    summary: FullCostSummary
    part3_row_ids: dict[str, int | None]
    input_hash: str
    calculation_version: str = CALCULATION_VERSION


def _part3_result(row: CostComponent | None, name: str, estimate: VariableCostEstimate) -> ComponentResult:
    if row is None:
        return ComponentResult(name, ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF, estimate.reporting_currency,
                               estimate.pricing_date, calculation_method="not present in the linked Part 3 estimate",
                               warnings=[f"{name}: variable_cost_estimate {estimate.variable_cost_estimate_id} "
                                         f"({estimate.calculation_version}) has no {name} component"])
    assumptions = [Assumption(a.get("name"), a.get("value"), a.get("unit"), a.get("source_type", ""), a.get("reference"))
                   for a in json.loads(row.assumptions_json)]
    status = ComponentStatus(row.status)
    return ComponentResult(
        name, status, row.currency, estimate.pricing_date, row.amount, SourceType(row.source_type),
        row.source_reference, row.source_id, row.pricing_observation_date,
        f"Part 3 result (cost_component {row.cost_component_id}): {row.calculation_method or ''}",
        json.loads(row.breakdown_json), assumptions, json.loads(row.warnings_json),
        partial_scope=row.partial_scope, zero_by_tariff_rule=status.is_calculated and row.amount == 0,
    )


def _maintenance_modelled(scenario: Scenario) -> bool:
    return any(scenario.section("maintenance", k) is not None for k in ("airframe", "engine", "engine_llp"))


def calculate_full_costs(session: Session, flight_estimate_id: int, variable_cost_estimate_id: int,
                         scenario: Scenario, fx: RateProvider | None = None,
                         part3_overrides: dict[str, ComponentResult] | None = None) -> FullCostResult:
    """Combine the saved Part 3 components with Part 4 components priced from ``scenario``.

    ``part3_overrides`` (Part 5 analytics only) replaces named Part 3
    components with results recalculated by the Part 3 engine, e.g. fuel at a
    varied price. Overrides enter the input hash; saved rows are never changed.
    """
    flight = session.get(FlightEstimate, flight_estimate_id)
    if flight is None:
        raise FullCostInputError(f"flight_estimate_id {flight_estimate_id} does not exist")
    variable = session.get(VariableCostEstimate, variable_cost_estimate_id)
    if variable is None:
        raise FullCostInputError(f"variable_cost_estimate_id {variable_cost_estimate_id} does not exist")
    if variable.flight_estimate_id != flight.flight_estimate_id:
        raise FullCostInputError(
            f"variable_cost_estimate {variable_cost_estimate_id} belongs to flight_estimate "
            f"{variable.flight_estimate_id}, not {flight_estimate_id}")
    if flight.fuel_accounting_basis != "v2":
        raise FullCostInputError(f"flight_estimate {flight_estimate_id} uses fuel accounting "
                                 f"{flight.fuel_accounting_basis!r}; only 'v2' is supported")
    if scenario.reporting_currency != variable.reporting_currency:
        raise FullCostInputError(f"scenario currency {scenario.reporting_currency} differs from the variable-cost "
                                 f"estimate's {variable.reporting_currency}")
    if scenario.pricing_date is not None and scenario.pricing_date != variable.pricing_date:
        raise FullCostInputError(f"scenario pricing date {scenario.pricing_date} differs from the variable-cost "
                                 f"estimate's {variable.pricing_date}")
    aircraft = session.get(AircraftType, flight.aircraft_type_id)
    basis = FlightBasis(
        flight_estimate_id=flight.flight_estimate_id, aircraft_code=aircraft.aircraft_code,
        block_hours=to_decimal(flight.block_time_min) / 60,
        airborne_hours=to_decimal(flight.airborne_time_min) / 60,
        engine_running_hours=to_decimal(flight.block_time_min) / 60,
        flight_cycles=Decimal(1), engine_count=aircraft.engine_count,
        payload_kg=to_decimal(flight.payload_kg), pricing_date=variable.pricing_date,
        reporting_currency=variable.reporting_currency, operational_validity=flight.calculation_status,
    )
    fx = fx or DatabaseRateProvider(session, max_staleness_days=7)

    rows = {c.component_name: c for c in session.scalars(
        select(CostComponent).where(CostComponent.variable_cost_estimate_id == variable.variable_cost_estimate_id))}
    components: dict[str, ComponentResult] = {n: _part3_result(rows.get(n), n, variable) for n in PART3_COMPONENTS}
    overrides = dict(part3_overrides or {})
    unknown = set(overrides) - set(PART3_COMPONENTS)
    if unknown:
        raise FullCostInputError(f"part3_overrides may only replace Part 3 components, not {sorted(unknown)}")
    for name, result in overrides.items():
        if result.currency != variable.reporting_currency or result.pricing_date != variable.pricing_date:
            raise FullCostInputError(f"override for {name} must use {variable.reporting_currency} and "
                                     f"{variable.pricing_date}")
    components.update(overrides)
    components.update({
        "airframe_maintenance": maintenance.airframe_maintenance(scenario, basis, fx),
        "engine_maintenance": maintenance.engine_maintenance(scenario, basis, fx),
        "engine_llp": maintenance.engine_llp(scenario, basis, fx),
        "crew_allowances": crew.crew_allowances(scenario, basis, fx),
        "crew_salaries": crew.crew_salaries(scenario, basis, fx),
        "insurance": insurance.insurance(scenario, basis, fx),
        "operating_lease": ownership.operating_lease(scenario, basis, fx,
                                                     maintenance_modelled=_maintenance_modelled(scenario)),
        "administration": indirect.administration(scenario, basis, fx),
        "cargo_sales": indirect.cargo_sales(scenario, basis, fx),
        "general_administrative": indirect.general_administrative(scenario, basis, fx),
        "depreciation": ownership.depreciation(scenario, basis, fx),
        "financing_interest": ownership.financing(scenario, basis, fx),
    })
    if not aircraft.openap_supported:  # no substitute passenger model for freighters (same rule as Part 3)
        for name in set(components) - set(PART3_COMPONENTS):
            components[name] = ComponentResult(
                name, ComponentStatus.UNSUPPORTED_AIRCRAFT, basis.reporting_currency, basis.pricing_date,
                warnings=[f"{aircraft.aircraft_code} has no supported performance model; time bases are not usable"])
    summary = FullCostSummary(components, basis.reporting_currency, basis.operational_validity)
    payload = {"flight": flight_estimate_id, "variable": variable_cost_estimate_id, "variable_hash": variable.input_hash,
               "scenario": scenario.content_hash, "version": CALCULATION_VERSION,
               **({"part3_overrides": sorted(overrides)} if overrides else {}),
               "components": {n: c.to_dict() for n, c in sorted(components.items())}}
    input_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return FullCostResult(flight_estimate_id, variable_cost_estimate_id, scenario, basis, summary,
                          {n: (rows[n].cost_component_id if n in rows and n not in overrides else None)
                           for n in PART3_COMPONENTS}, input_hash)
