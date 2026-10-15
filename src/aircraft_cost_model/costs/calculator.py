"""Variable cost orchestration for a saved Part 2 flight estimate.

Steps: load the flight estimate -> reject legacy ``v1`` fuel accounting ->
resolve aircraft and airports -> fuel (block fuel x EIA benchmark, ECB FX) ->
navigation (EUROCONTROL zones, explicit distances only) -> landing (origin
take-off + destination landing tariffs) -> ground handling -> aggregation.

The pricing date is independent of when the flight estimate was calculated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aircraft_cost_model import __version__
from aircraft_cost_model.config import EIA_JET_FUEL_SERIES
from aircraft_cost_model.costs import repository
from aircraft_cost_model.costs.coverage import (
    ComponentName,
    ComponentResult,
    ComponentStatus,
    VariableCostSummary,
)
from aircraft_cost_model.costs.currency import DatabaseRateProvider, normalize_currency, to_decimal
from aircraft_cost_model.costs.exceptions import CostInputError, FlightEstimateNotFoundError, LegacyFuelAccountingError
from aircraft_cost_model.costs.fuel_cost import FuelPriceObservation, calculate_fuel_cost
from aircraft_cost_model.costs.handling_cost import (
    MOVEMENT_ARRIVAL,
    MOVEMENT_DEPARTURE,
    TARIFF_TYPE_HANDLING,
    HandlingAssumption,
    calculate_handling_component,
    calculate_handling_part,
)
from aircraft_cost_model.costs.landing_cost import (
    MOVEMENT_LANDING,
    MOVEMENT_TAKEOFF,
    TARIFF_TYPE_MOVEMENT,
    AircraftFacts,
    AirportRef,
    LandingTariffCalculator,
    TariffRecord,
    calculate_landing_component,
)
from aircraft_cost_model.costs.navigation_cost import (
    MtowBasis,
    ZoneRate,
    ZoneSegment,
    calculate_navigation_charge,
    validate_segments,
)
from aircraft_cost_model.costs.terminal_cost import (
    TerminalZoneRate,
    calculate_terminal_component,
    calculate_terminal_part,
)
from aircraft_cost_model.costs.terminal_cost import MOVEMENT_ARRIVAL as TERMINAL_ARRIVAL
from aircraft_cost_model.costs.terminal_cost import MOVEMENT_DEPARTURE as TERMINAL_DEPARTURE
from aircraft_cost_model.costs.pricing import select_observation
from aircraft_cost_model.ingestion.fuel_prices import DESCRIPTION as EIA_DESCRIPTION
from aircraft_cost_model.ingestion.fuel_prices import PERIOD_DAILY
from aircraft_cost_model.models import AircraftType, Airport, FlightEstimate

CALCULATION_VERSION = f"variable_costs v2 (aircraft_cost_model {__version__})"
SUPPORTED_FUEL_ACCOUNTING = "v2"


@dataclass(frozen=True)
class VariableCostRequest:
    flight_estimate_id: int
    pricing_date: date
    reporting_currency: str = "EUR"
    fuel_density_kg_per_l: Decimal | None = None
    fuel_series: str = EIA_JET_FUEL_SERIES
    max_fuel_price_staleness_days: int = 7
    max_fx_staleness_days: int = 7
    nav_segments: tuple[ZoneSegment, ...] = ()
    certificated_mtow_kg: Decimal | None = None
    use_type_level_mtow_scenario: bool = False
    tariff_context: dict[str, dict[str, str]] = field(default_factory=dict)
    handling_context: dict[str, dict[str, str]] = field(default_factory=dict)
    handling_assumptions: dict[str, HandlingAssumption] = field(default_factory=dict)

    def normalized(self) -> dict[str, Any]:
        def enc(value: Any) -> Any:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, date):
                return value.isoformat()
            if isinstance(value, dict):
                return {k: enc(v) for k, v in sorted(value.items())}
            if isinstance(value, (list, tuple)):
                return [enc(v) for v in value]
            return value
        return enc(asdict(self))


@dataclass
class FlightContext:
    flight_estimate_id: int
    aircraft_code: str
    aircraft_description: str
    origin: AirportRef
    destination: AirportRef
    block_fuel_kg: Decimal
    great_circle_km: Decimal
    fuel_accounting_basis: str


@dataclass
class VariableCostResult:
    request: VariableCostRequest
    flight: FlightContext
    summary: VariableCostSummary
    input_hash: str
    calculation_version: str = CALCULATION_VERSION

    def component(self, name: ComponentName) -> ComponentResult:
        return next(c for c in self.summary.components if c.component == name.value)


def _airport_ref(airport: Airport) -> AirportRef:
    return AirportRef(airport.airport_id, airport.iata_code or airport.airport_ident, airport.airport_name)


def _context_for(contexts: dict[str, dict[str, str]], airport: Airport) -> dict[str, str]:
    for key in (airport.iata_code, airport.icao_code, airport.airport_ident):
        if key and key.upper() in {k.upper() for k in contexts}:
            return next(v for k, v in contexts.items() if k.upper() == key.upper())
    return {}


def _tariff_records(session: Session, airport: Airport, tariff_type: str, pricing_date: date) -> list[TariffRecord]:
    return [
        TariffRecord(t.airport_tariff_id, t.airport_id, t.tariff_type, t.valid_from, t.valid_to, t.currency,
                     t.calculation_method, json.loads(t.parameters_json), t.source_id, t.source_reference,
                     t.verification_status)
        for t in repository.airport_tariffs_in_force(session, airport.airport_id, tariff_type, pricing_date)
    ]


def calculate_variable_costs(session: Session, request: VariableCostRequest) -> VariableCostResult:
    """Price fuel, navigation, landing and ground handling for a saved flight estimate.

    Raises:
        FlightEstimateNotFoundError, LegacyFuelAccountingError, CostInputError.
    """
    currency = normalize_currency(request.reporting_currency)
    estimate = session.get(FlightEstimate, request.flight_estimate_id)
    if estimate is None:
        raise FlightEstimateNotFoundError(f"flight_estimate_id {request.flight_estimate_id} does not exist")
    if estimate.fuel_accounting_basis != SUPPORTED_FUEL_ACCOUNTING:
        raise LegacyFuelAccountingError(
            f"flight_estimate_id {estimate.flight_estimate_id} uses fuel accounting basis "
            f"{estimate.fuel_accounting_basis!r}; only {SUPPORTED_FUEL_ACCOUNTING!r} is priced. Legacy estimates are not "
            "reinterpreted - recalculate the flight with scripts/calculate_flight.py to create a v2 estimate."
        )
    aircraft = session.get(AircraftType, estimate.aircraft_type_id)
    origin = session.get(Airport, estimate.origin_airport_id)
    destination = session.get(Airport, estimate.destination_airport_id)
    flight = FlightContext(
        estimate.flight_estimate_id, aircraft.aircraft_code, f"{aircraft.manufacturer or ''} {aircraft.model or ''}".strip(),
        _airport_ref(origin), _airport_ref(destination), to_decimal(estimate.block_fuel_kg),
        to_decimal(estimate.great_circle_distance_nm) * Decimal("1.852"), estimate.fuel_accounting_basis,
    )
    pricing_date = request.pricing_date
    fx = DatabaseRateProvider(session, request.max_fx_staleness_days)

    if not aircraft.openap_supported:
        components = [ComponentResult(n.value, ComponentStatus.UNSUPPORTED_AIRCRAFT, currency, pricing_date,
                                      warnings=[f"{aircraft.aircraft_code} has no validated performance model"])
                      for n in ComponentName]
        summary = VariableCostSummary(pricing_date, currency, components)
        return VariableCostResult(request, flight, summary, _hash(request, summary))

    # Fuel ---------------------------------------------------------------------
    if request.fuel_density_kg_per_l is not None:
        density, density_source = request.fuel_density_kg_per_l, "user_input"
    else:
        density = to_decimal(estimate.fuel_density_kg_per_l)
        density_source = "flight_estimate.fuel_density_kg_per_l (Part 2 default: OpenAP mass.py factor)"
    price_row = repository.latest_fuel_price_on_or_before(session, request.fuel_series, PERIOD_DAILY, pricing_date)
    selection = select_observation([(price_row.observation_date, price_row)] if price_row else [], pricing_date,
                                   request.max_fuel_price_staleness_days)
    price_obs, reason = None, None
    if selection.ok:
        row = selection.value
        price_obs = FuelPriceObservation(
            row.series_identifier, EIA_DESCRIPTION, row.observation_date, row.observation_period, row.price,
            row.currency, row.price_unit, selection.gap_days or 0, row.source_id,
            repository.source_label(session, row.source_id),
        )
    else:
        latest = f" (latest {selection.observation_date})" if selection.observation_date else ""
        reason = (f"No {request.fuel_series} price within {request.max_fuel_price_staleness_days} days on or before "
                  f"{pricing_date}{latest}: {selection.reason}")
    fuel = calculate_fuel_cost(block_fuel_kg=flight.block_fuel_kg, density_kg_per_l=density,
                               density_source=density_source, price=price_obs, price_unavailable_reason=reason,
                               reporting_currency=currency, pricing_date=pricing_date, rates=fx)

    # Navigation -----------------------------------------------------------------
    segments = list(request.nav_segments)
    if segments:
        validate_segments(segments, flight.great_circle_km)
    rates: dict[str, ZoneRate | None] = {}
    for segment in segments:
        versions = repository.navigation_rates_in_force(session, segment.zone, pricing_date)
        if len(versions) > 1:
            raise CostInputError(f"Overlapping unit-rate versions for {segment.zone} on {pricing_date}")
        v = versions[0] if versions else None
        rates[segment.zone] = None if v is None else ZoneRate(
            v.charging_zone, v.charging_zone_name, v.unit_rate, v.currency, v.valid_from, v.valid_to, v.source_id,
            v.source_reference, v.verification_status,
        )
    mtow = MtowBasis.resolve(request.certificated_mtow_kg,
                             to_decimal(aircraft.mtow_kg) if aircraft.mtow_kg is not None else None,
                             request.use_type_level_mtow_scenario)
    navigation = calculate_navigation_charge(segments=segments, rates=rates, mtow=mtow,
                                             reporting_currency=currency, pricing_date=pricing_date, fx=fx)

    # Terminal navigation -------------------------------------------------------------
    terminal_parts = [
        _terminal_part(session, airport, ref, movement, mtow, currency, pricing_date, fx)
        for airport, ref, movement in ((origin, flight.origin, TERMINAL_DEPARTURE),
                                       (destination, flight.destination, TERMINAL_ARRIVAL))
    ]
    terminal = calculate_terminal_component(terminal_parts, currency, pricing_date)

    # Landing ------------------------------------------------------------------------
    facts = AircraftFacts(aircraft.aircraft_code, aircraft.icao_type_designator, mtow.kg, mtow.description,
                          True if "freighter" in (aircraft.variant or "") else None, mtow.is_scenario)
    calculator = LandingTariffCalculator()
    landing_parts = [
        calculator.calculate(flight.origin, facts, MOVEMENT_TAKEOFF, pricing_date,
                             _context_for(request.tariff_context, origin),
                             _tariff_records(session, origin, TARIFF_TYPE_MOVEMENT, pricing_date), currency, fx),
        calculator.calculate(flight.destination, facts, MOVEMENT_LANDING, pricing_date,
                             _context_for(request.tariff_context, destination),
                             _tariff_records(session, destination, TARIFF_TYPE_MOVEMENT, pricing_date), currency, fx),
    ]
    landing = calculate_landing_component(landing_parts, currency, pricing_date)

    # Ground handling --------------------------------------------------------------------
    handling_parts = []
    for airport, ref, movement in ((origin, flight.origin, MOVEMENT_DEPARTURE),
                                   (destination, flight.destination, MOVEMENT_ARRIVAL)):
        assumption = next((v for k, v in request.handling_assumptions.items()
                           if k.upper() in {c.upper() for c in (airport.iata_code, airport.icao_code, airport.airport_ident) if c}),
                          None)
        handling_parts.append(calculate_handling_part(
            airport=ref, aircraft=facts, movement=movement, pricing_date=pricing_date,
            tariffs=_tariff_records(session, airport, TARIFF_TYPE_HANDLING, pricing_date),
            context=_context_for(request.handling_context, airport), assumption=assumption,
            reporting_currency=currency, fx=fx,
        ))
    handling = calculate_handling_component(handling_parts, currency, pricing_date)

    summary = VariableCostSummary(pricing_date, currency, [fuel, navigation, terminal, landing, handling])
    return VariableCostResult(request, flight, summary, _hash(request, summary))


def _terminal_part(session: Session, airport: Airport, ref: AirportRef, movement: str, mtow: MtowBasis,
                   currency: str, pricing_date: date, fx: DatabaseRateProvider) -> ComponentResult:
    icao = airport.icao_code
    zones, without_rate = [], []
    for zone in (repository.terminal_zones_for_aerodrome(session, icao, pricing_date) if icao else []):
        versions = repository.navigation_rates_in_force(session, zone, pricing_date, charge_type="terminal")
        if not versions:
            without_rate.append(zone)
        zones.extend(TerminalZoneRate(v.charging_zone, v.charging_zone_name, v.unit_rate, v.currency, v.valid_from,
                                      v.valid_to, v.service_unit_formula, v.charged_movement or "",
                                      v.verification_status, v.source_id, v.source_reference) for v in versions)
    return calculate_terminal_part(airport_code=ref.code, aerodrome_icao=icao, movement=movement, zones=zones,
                                   zone_memberships_without_rate=without_rate, mtow=mtow,
                                   reporting_currency=currency, pricing_date=pricing_date, fx=fx)


def _hash(request: VariableCostRequest, summary: VariableCostSummary) -> str:
    """Deterministic hash of the inputs and every selected observation, rate and amount."""
    payload = {"request": request.normalized(), "version": CALCULATION_VERSION,
               "components": [c.to_dict() for c in summary.components]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
