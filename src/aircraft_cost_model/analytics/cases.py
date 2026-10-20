"""Cost cases: one flight estimate + one cost summary, loaded from saved rows or recalculated.

A :class:`CostCase` is the unit every analytics function works on. It is built
in one of three ways:

- :func:`load_saved_case` reads a saved ``full_cost_estimate`` and its
  components exactly as stored (no recalculation);
- :func:`calculate_case` runs the Part 4 calculator for a flight estimate,
  a Part 3 variable-cost estimate and a scenario (optionally with Part 3
  overrides from the Part 3 engine);
- :func:`unsupported_case` describes an aircraft without a supported
  performance model. No costs are calculated and no substitute is used.

Database identifiers are looked up, never assumed: a fresh installation has
different IDs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.costs.coverage import Assumption, ComponentResult, ComponentStatus, SourceType
from aircraft_cost_model.costs.currency import RateProvider, to_decimal
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.fullcost.aggregate import FullCostSummary
from aircraft_cost_model.fullcost.calculator import FullCostResult, calculate_full_costs
from aircraft_cost_model.fullcost.scenario import Scenario, parse_scenario
from aircraft_cost_model.models import (
    AircraftType,
    Airport,
    CostComponent,
    CostScenario,
    FlightEstimate,
    FullCostEstimate,
    VariableCostEstimate,
)


class AnalyticsInputError(CostCalculationError, ValueError):
    """An analytics request refers to missing or inconsistent records or inputs."""


@dataclass(frozen=True)
class FlightFacts:
    """Physical facts of one saved Part 2 flight estimate (one completed leg)."""

    flight_estimate_id: int
    aircraft_code: str
    aircraft_supported: bool
    origin: str
    destination: str
    block_hours: Decimal
    airborne_hours: Decimal
    great_circle_nm: Decimal
    modelled_route_nm: Decimal
    route_distance_method: str
    block_fuel_kg: Decimal
    modelled_payload_kg: Decimal
    operational_validity: str
    fuel_accounting_basis: str
    flight_cycles: Decimal = Decimal(1)

    def to_dict(self) -> dict[str, Any]:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


@dataclass
class CostCase:
    """One costed flight (or an explicit unsupported/missing placeholder)."""

    label: str
    facts: FlightFacts | None
    summary: FullCostSummary | None
    pricing_date: date | None
    reporting_currency: str | None
    flight_type: str | None
    ownership_mode: str | None
    scenario: Scenario | None = None
    scenario_id: int | None = None
    full_cost_estimate_id: int | None = None
    variable_cost_estimate_id: int | None = None
    input_hash: str | None = None
    origin: str = "recalculated"  # saved | recalculated | unsupported | missing_flight_estimate
    aircraft_code: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_costed(self) -> bool:
        return self.summary is not None and self.facts is not None

    @property
    def scenario_hash(self) -> str | None:
        return self.scenario.content_hash if self.scenario else None


def _airport_code(airport: Airport) -> str:
    return airport.iata_code or airport.icao_code or airport.airport_ident


def flight_facts(session: Session, flight_estimate_id: int) -> FlightFacts:
    flight = session.get(FlightEstimate, flight_estimate_id)
    if flight is None:
        raise AnalyticsInputError(f"flight_estimate_id {flight_estimate_id} does not exist")
    aircraft = session.get(AircraftType, flight.aircraft_type_id)
    return FlightFacts(
        flight_estimate_id=flight.flight_estimate_id,
        aircraft_code=aircraft.aircraft_code,
        aircraft_supported=bool(aircraft.openap_supported),
        origin=_airport_code(session.get(Airport, flight.origin_airport_id)),
        destination=_airport_code(session.get(Airport, flight.destination_airport_id)),
        block_hours=to_decimal(flight.block_time_min) / 60,
        airborne_hours=to_decimal(flight.airborne_time_min) / 60,
        great_circle_nm=to_decimal(flight.great_circle_distance_nm),
        modelled_route_nm=to_decimal(flight.estimated_route_distance_nm),
        route_distance_method=flight.route_distance_method,
        block_fuel_kg=to_decimal(flight.block_fuel_kg),
        modelled_payload_kg=to_decimal(flight.payload_kg),
        operational_validity=flight.calculation_status,
        fuel_accounting_basis=flight.fuel_accounting_basis,
    )


def _assumptions(raw: str) -> list[Assumption]:
    return [Assumption(a.get("name"), a.get("value"), a.get("unit"), a.get("source_type", ""), a.get("reference"))
            for a in json.loads(raw or "[]")]


def summary_from_saved(session: Session, estimate: FullCostEstimate) -> FullCostSummary:
    """Rebuild the component results exactly as stored (amount, status, source type and inputs)."""
    components: dict[str, ComponentResult] = {}
    for row in estimate.components:
        status = ComponentStatus(row.status)
        partial = False
        if row.part3_cost_component_id is not None:
            part3 = session.get(CostComponent, row.part3_cost_component_id)
            partial = bool(part3.partial_scope) if part3 is not None else False
        components[row.component_name] = ComponentResult(
            row.component_name, status, row.currency, estimate.pricing_date, row.amount, SourceType(row.source_type),
            row.source_reference, calculation_method=row.calculation_method,
            breakdown=json.loads(row.breakdown_json), assumptions=_assumptions(row.assumptions_json),
            warnings=json.loads(row.warnings_json), partial_scope=partial,
            zero_by_tariff_rule=status.is_calculated and row.amount == 0,
        )
    return FullCostSummary(components, estimate.reporting_currency, estimate.operational_validity_status)


def load_saved_case(session: Session, full_cost_estimate_id: int, label: str | None = None) -> CostCase:
    estimate = session.get(FullCostEstimate, full_cost_estimate_id)
    if estimate is None:
        raise AnalyticsInputError(f"full_cost_estimate_id {full_cost_estimate_id} does not exist")
    scenario_row = session.get(CostScenario, estimate.scenario_id)
    scenario = parse_scenario(json.loads(scenario_row.content_json), source_path=scenario_row.source_path)
    facts = flight_facts(session, estimate.flight_estimate_id)
    return CostCase(
        label=label or f"full_cost_estimate {full_cost_estimate_id}",
        facts=facts, summary=summary_from_saved(session, estimate), pricing_date=estimate.pricing_date,
        reporting_currency=estimate.reporting_currency, flight_type=scenario.flight_type,
        ownership_mode=estimate.ownership_mode, scenario=scenario, scenario_id=estimate.scenario_id,
        full_cost_estimate_id=estimate.full_cost_estimate_id,
        variable_cost_estimate_id=estimate.variable_cost_estimate_id, input_hash=estimate.input_hash, origin="saved",
        aircraft_code=facts.aircraft_code,
    )


def case_from_result(result: FullCostResult, facts: FlightFacts, label: str, scenario_id: int | None = None) -> CostCase:
    return CostCase(
        label=label, facts=facts, summary=result.summary, pricing_date=result.basis.pricing_date,
        reporting_currency=result.basis.reporting_currency, flight_type=result.scenario.flight_type,
        ownership_mode=result.scenario.ownership_mode, scenario=result.scenario, scenario_id=scenario_id,
        variable_cost_estimate_id=result.variable_cost_estimate_id, input_hash=result.input_hash,
        origin="recalculated", aircraft_code=facts.aircraft_code,
    )


def calculate_case(session: Session, flight_estimate_id: int, variable_cost_estimate_id: int, scenario: Scenario,
                   label: str | None = None, fx: RateProvider | None = None,
                   part3_overrides: dict[str, ComponentResult] | None = None) -> tuple[CostCase, FullCostResult]:
    result = calculate_full_costs(session, flight_estimate_id, variable_cost_estimate_id, scenario, fx=fx,
                                  part3_overrides=part3_overrides)
    facts = flight_facts(session, flight_estimate_id)
    return case_from_result(result, facts, label or scenario.name), result


def unsupported_case(session: Session, aircraft_code: str, origin: str, destination: str) -> CostCase:
    aircraft = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == aircraft_code))
    reason = (f"{aircraft_code}: no supported flight-performance model; no costs are calculated and no passenger "
              "model is substituted" if aircraft is not None else f"{aircraft_code}: unknown aircraft type")
    return CostCase(label=f"{aircraft_code} {origin}-{destination}", facts=None, summary=None, pricing_date=None,
                    reporting_currency=None, flight_type=None, ownership_mode=None, origin="unsupported",
                    aircraft_code=aircraft_code, warnings=[reason])


def find_route_case(session: Session, aircraft_code: str, origin: str, destination: str, pricing_date: date,
                    currency: str, scenario: Scenario) -> CostCase:
    """Resolve aircraft + route to the latest v2 flight estimate with a Part 3 estimate on ``pricing_date``.

    Unsupported aircraft return an explicit unsupported case. A supported
    aircraft without a saved estimate returns ``missing_flight_estimate``;
    flights are never estimated implicitly here.
    """
    aircraft = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == aircraft_code))
    if aircraft is None or not aircraft.openap_supported:
        return unsupported_case(session, aircraft_code, origin, destination)
    origin_ids = [a.airport_id for a in session.scalars(select(Airport).where(
        (Airport.iata_code == origin) | (Airport.icao_code == origin) | (Airport.airport_ident == origin)))]
    destination_ids = [a.airport_id for a in session.scalars(select(Airport).where(
        (Airport.iata_code == destination) | (Airport.icao_code == destination) | (Airport.airport_ident == destination)))]
    flights = session.scalars(select(FlightEstimate).where(
        FlightEstimate.aircraft_type_id == aircraft.aircraft_type_id, FlightEstimate.origin_airport_id.in_(origin_ids),
        FlightEstimate.destination_airport_id.in_(destination_ids), FlightEstimate.fuel_accounting_basis == "v2",
    ).order_by(FlightEstimate.flight_estimate_id.desc())).all()
    for flight in flights:
        variable = session.scalar(select(VariableCostEstimate).where(
            VariableCostEstimate.flight_estimate_id == flight.flight_estimate_id,
            VariableCostEstimate.pricing_date == pricing_date, VariableCostEstimate.reporting_currency == currency,
        ).order_by(VariableCostEstimate.variable_cost_estimate_id.desc()))
        if variable is not None:
            case, _ = calculate_case(session, flight.flight_estimate_id, variable.variable_cost_estimate_id, scenario,
                                     label=f"{aircraft_code} {origin}-{destination}")
            return case
    return CostCase(label=f"{aircraft_code} {origin}-{destination}", facts=None, summary=None, pricing_date=pricing_date,
                    reporting_currency=currency, flight_type=scenario.flight_type, ownership_mode=scenario.ownership_mode,
                    origin="missing_flight_estimate", aircraft_code=aircraft_code,
                    warnings=[f"no saved v2 flight estimate with a {currency} variable-cost estimate on {pricing_date} "
                              f"for {aircraft_code} {origin}-{destination}; run calculate_flight.py and "
                              "calculate_variable_costs.py first"])
