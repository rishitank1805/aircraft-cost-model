"""Flight estimate orchestration and iterative fuel planning.

Pipeline: airport lookup -> great-circle / route distance -> aircraft and
limits -> kinematic profile -> taxi fuel -> iterative trip-fuel integration ->
loading checks -> :class:`FlightEstimateResult`.

Mass and fuel boundaries (``FUEL_ACCOUNTING_BASIS`` = "v2"):

    take-off mass = mass at brake release
    landing mass  = mass at touchdown
    trip fuel T   = fuel burned brake release -> touchdown = take-off mass - landing mass
    landing roll  = touchdown -> rest (ground idle), reported separately
    block fuel    = taxi_out + T + landing_roll + taxi_in

Iterative fuel planning (fixed point on trip fuel T):

    planned fuel F(T) = taxi_out + T + landing_roll + taxi_in + contingency(T) + alternate + final_reserve
    take-off mass     = ZFW + F(T) - taxi_out
    T_(k+1)           = integrated trip fuel at take-off mass(T_k)

``T_0`` is integrated at the lightest possible take-off mass (no trip fuel on
board), a lower bound, so iterates increase monotonically. Converged when
``|T_(k+1) - T_k| <= tolerance``; otherwise :class:`ConvergenceError`.

Results are model estimates for cost analysis, **not** dispatch fuel plans.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model import __version__
from aircraft_cost_model.config import JET_FUEL_DENSITY_KG_PER_L
from aircraft_cost_model.models import AircraftType, DataSource
from aircraft_cost_model.performance.airport_lookup import AirportInfo, get_airport
from aircraft_cost_model.performance.exceptions import (
    ConvergenceError,
    FuelFlowError,
    InputValidationError,
    UnsupportedAircraftError,
)
from aircraft_cost_model.performance.fuel import (
    INTEGRATION_METHOD,
    TripIntegration,
    ground_idle_fuel,
    integrate_trip,
)
from aircraft_cost_model.performance.mass import (
    STATUS_INFEASIBLE,
    AircraftLimits,
    LimitCheck,
    evaluate_limits,
    overall_status,
    require_nonnegative,
    zero_fuel_weight,
)
from aircraft_cost_model.performance.openap_adapter import AircraftPerformanceProvider, FlowState, ModelMetadata
from aircraft_cost_model.performance.profile import (
    CRUISE_ALTITUDE_STEP_FT,
    PHASE_APPROACH,
    PHASE_LANDING_ROLL,
    PHASE_TAKEOFF,
    PHASE_TAXI_IN,
    PHASE_TAXI_OUT,
    PROFILE_PHASES,
    FlightProfile,
    generate_profile,
    trajectory_states,
)
from aircraft_cost_model.performance.route import DISTANCE_METHOD, EARTH_MEAN_RADIUS_KM, RouteDistance, estimate_route_distance
from aircraft_cost_model.performance.units import KM_PER_NM, ft_to_m, m_to_ft

MODEL_NAME = "WRAP kinematic profile + OpenAP FuelFlow, time-step integration"

# v1 (estimates saved before migration 0003): trip fuel and landing mass ran to the end of the landing roll.
# v2: take-off mass at brake release, landing mass at touchdown, trip fuel = brake release -> touchdown,
#     landing-roll fuel and time reported separately.
FUEL_ACCOUNTING_BASIS = "v2"

# ICAO Annex 16 Vol. II reference LTO cycle: 26 min taxi/ground idle in total.
# Splitting it equally between taxi-out and taxi-in is a project assumption.
ICAO_LTO_TAXI_TOTAL_MIN = 26.0
DEFAULT_TAXI_OUT_MIN = ICAO_LTO_TAXI_TOTAL_MIN / 2
DEFAULT_TAXI_IN_MIN = ICAO_LTO_TAXI_TOTAL_MIN / 2
DEFAULT_TIME_STEP_S = 30.0
DEFAULT_TOLERANCE_KG = 1.0
DEFAULT_MAX_ITERATIONS = 25

SOURCE_USER = "user_input"
SOURCE_DEFAULT = "project_default"
SOURCE_OPENAP = "openap_model"
SOURCE_DATABASE = "database"
SOURCE_CONSTANT = "physical_constant"
SOURCE_MODEL = "modelling_assumption"

PHASE_METHODS = {
    PHASE_TAXI_OUT: "ICAO databank idle fuel flow (7% rated thrust) x engines; all engines assumed running",
    PHASE_TAKEOFF: "OpenAP FuelFlow.takeoff at full rated thrust during the roll; FuelFlow.enroute airborne",
    "climb": "OpenAP FuelFlow.enroute (clean-configuration drag polar)",
    "cruise": "OpenAP FuelFlow.enroute (clean-configuration drag polar)",
    "descent": "OpenAP FuelFlow.enroute (clean-configuration drag polar; thrust floored at OpenAP minimum)",
    PHASE_APPROACH: "OpenAP FuelFlow.enroute to touchdown (flap/gear drag not modelled)",
    PHASE_LANDING_ROLL: "ICAO databank idle fuel flow x engines, touchdown to rest (reverse thrust not modelled)",
    PHASE_TAXI_IN: "ICAO databank idle fuel flow (7% rated thrust) x engines; all engines assumed running",
}


@dataclass(frozen=True)
class FlightRequest:
    """User inputs for one flight estimate. ``None`` means "use the documented default"."""

    aircraft_code: str
    origin: str
    destination: str
    payload_kg: float
    cruise_altitude_ft: float | None = None
    taxi_out_min: float | None = None
    taxi_in_min: float | None = None
    route_factor: float = 1.0
    route_distance_nm: float | None = None
    fuel_density_kg_per_l: float | None = None
    contingency_pct_of_trip: float = 0.0
    alternate_fuel_kg: float = 0.0
    final_reserve_fuel_kg: float = 0.0
    time_step_s: float = DEFAULT_TIME_STEP_S
    tolerance_kg: float = DEFAULT_TOLERANCE_KG
    max_iterations: int = DEFAULT_MAX_ITERATIONS

    def validate(self) -> None:
        """Reject missing, negative or non-finite inputs."""
        if not self.aircraft_code or not self.aircraft_code.strip():
            raise InputValidationError("aircraft_code is required")
        require_nonnegative("payload_kg", self.payload_kg)
        for name in ("contingency_pct_of_trip", "alternate_fuel_kg", "final_reserve_fuel_kg"):
            require_nonnegative(name, getattr(self, name))
        for name in ("taxi_out_min", "taxi_in_min"):
            if getattr(self, name) is not None:
                require_nonnegative(name, getattr(self, name))
        for name in ("time_step_s", "tolerance_kg"):
            value = require_nonnegative(name, getattr(self, name))
            if value == 0:
                raise InputValidationError(f"{name} must be positive")
        if self.fuel_density_kg_per_l is not None:
            density = require_nonnegative("fuel_density_kg_per_l", self.fuel_density_kg_per_l)
            if density == 0:
                raise InputValidationError("fuel_density_kg_per_l must be positive")
        if self.cruise_altitude_ft is not None:
            require_nonnegative("cruise_altitude_ft", self.cruise_altitude_ft)
        if not isinstance(self.max_iterations, int) or self.max_iterations < 1:
            raise InputValidationError("max_iterations must be a positive integer")


@dataclass(frozen=True)
class Assumption:
    """A labelled input or modelling assumption."""

    name: str
    value: str
    unit: str | None
    source_type: str
    source_reference: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class PhaseSummary:
    """Per-phase totals (times relative to off-block)."""

    phase: str
    sequence_number: int
    start_time_s: float
    duration_s: float
    distance_nm: float | None
    start_altitude_ft: float
    end_altitude_ft: float
    start_mass_kg: float
    end_mass_kg: float
    fuel_burn_kg: float
    fuel_flow_method: str


@dataclass
class FlightEstimateResult:
    """Complete flight estimate: calculated values, assumptions, checks and provenance."""

    request: FlightRequest
    aircraft_type_id: int
    aircraft_code: str
    aircraft_description: str
    model: ModelMetadata
    origin: AirportInfo
    destination: AirportInfo
    route: RouteDistance
    profile: FlightProfile
    trip: TripIntegration
    taxi_out_min: float
    taxi_in_min: float
    taxi_out_fuel_kg: float
    taxi_in_fuel_kg: float
    contingency_fuel_kg: float
    alternate_fuel_kg: float
    final_reserve_fuel_kg: float
    planned_fuel_load_kg: float
    zero_fuel_weight_kg: float
    fuel_density_kg_per_l: float
    iterations: int
    iteration_history_kg: list[float]
    checks: list[LimitCheck]
    status: str
    assumptions: list[Assumption]
    warnings: list[str]
    phases: list[PhaseSummary]
    input_hash: str
    model_version: str
    model_name: str = MODEL_NAME

    # ---- derived quantities ----------------------------------------------------
    @property
    def trip_fuel_kg(self) -> float:
        return self.trip.trip_fuel_kg

    @property
    def taxi_fuel_kg(self) -> float:
        return self.taxi_out_fuel_kg + self.taxi_in_fuel_kg

    @property
    def landing_roll_fuel_kg(self) -> float:
        return self.trip.landing_roll_fuel_kg

    @property
    def block_fuel_kg(self) -> float:
        return self.taxi_out_fuel_kg + self.trip_fuel_kg + self.landing_roll_fuel_kg + self.taxi_in_fuel_kg

    @property
    def reserve_fuel_kg(self) -> float:
        return self.contingency_fuel_kg + self.alternate_fuel_kg + self.final_reserve_fuel_kg

    @property
    def takeoff_weight_kg(self) -> float:
        return self.trip.takeoff_mass_kg

    @property
    def ramp_weight_kg(self) -> float:
        return self.takeoff_weight_kg + self.taxi_out_fuel_kg

    @property
    def landing_weight_kg(self) -> float:
        """Mass at touchdown."""
        return self.trip.landing_mass_kg

    @property
    def block_in_weight_kg(self) -> float:
        return self.trip.end_of_landing_roll_mass_kg - self.taxi_in_fuel_kg

    @property
    def trip_time_min(self) -> float:
        """Brake release to touchdown."""
        return self.profile.trip_time_s / 60.0

    @property
    def landing_roll_time_min(self) -> float:
        return self.profile.landing_roll_s / 60.0

    @property
    def airborne_time_min(self) -> float:
        return self.profile.airborne_time_s / 60.0

    @property
    def block_time_min(self) -> float:
        return self.taxi_out_min + self.trip_time_min + self.landing_roll_time_min + self.taxi_in_min

    @property
    def fuel_per_nm_kg(self) -> float:
        """Airborne trip fuel per NM of estimated route distance."""
        return self.trip_fuel_kg / self.route.estimated_route_nm if self.route.estimated_route_nm > 0 else math.nan

    @property
    def fuel_per_block_hour_kg(self) -> float:
        """Block fuel per block hour."""
        hours = self.block_time_min / 60.0
        return self.block_fuel_kg / hours if hours > 0 else math.nan

    @property
    def is_feasible(self) -> bool:
        return self.status != STATUS_INFEASIBLE

    def phase(self, name: str) -> PhaseSummary:
        return next(p for p in self.phases if p.phase == name)

    def trajectory(self) -> list[dict[str, float | str]]:
        """Airborne states with mass (time relative to brake release)."""
        return trajectory_states(self.profile, self.trip.mass_trace_kg)


def _input_hash(request: FlightRequest, openap_version: str) -> str:
    payload = {"request": asdict(request), "openap": openap_version, "package": __version__, "model": MODEL_NAME}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def resolve_aircraft(session: Session, aircraft_code: str, provider: AircraftPerformanceProvider) -> tuple[AircraftType, ModelMetadata]:
    """Find the aircraft master row and confirm a complete performance model exists.

    Raises:
        UnsupportedAircraftError: Unknown aircraft, freighter without a validated model,
            or OpenAP type lacking kinematic/drag/engine data.
    """
    code = aircraft_code.strip().upper()
    row = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == code))
    if row is None:
        related = session.scalars(select(AircraftType.aircraft_code).where(AircraftType.icao_type_designator == code)).all()
        hint = f" Rows with ICAO designator {code}: {sorted(related)}." if related else ""
        raise UnsupportedAircraftError(f"Aircraft {code} is not in the aircraft_type table.{hint}")
    if not row.openap_supported:
        raise UnsupportedAircraftError(
            f"Aircraft {code} ({row.manufacturer} {row.model}) has no validated performance model "
            f"(OpenAP coverage: {row.openap_coverage}). Related passenger model "
            f"{row.openap_related_code or 'none'} is not substituted for a freighter."
        )
    meta = provider.get_model_metadata(code)
    if not meta.supported:
        raise UnsupportedAircraftError(
            f"Aircraft {code} has no complete OpenAP performance model: " + "; ".join(meta.unsupported_reasons)
        )
    return row, meta


def _round_down_to_step_ft(altitude_ft: float) -> float:
    return math.floor(altitude_ft / CRUISE_ALTITUDE_STEP_FT) * CRUISE_ALTITUDE_STEP_FT


def estimate_flight(
    session: Session, request: FlightRequest, provider: AircraftPerformanceProvider
) -> FlightEstimateResult:
    """Run the full pipeline. Infeasible loading returns a result with status ``infeasible``.

    Raises:
        InputValidationError, AirportLookupError, UnsupportedAircraftError,
        RouteTooShortError, FuelFlowError, ConvergenceError.
    """
    request.validate()
    warnings: list[str] = []
    assumptions: list[Assumption] = []

    def assume(name: str, value: Any, unit: str | None, source: str, ref: str | None = None, notes: str | None = None) -> None:
        assumptions.append(Assumption(name, str(value), unit, source, ref, notes))

    origin = get_airport(session, request.origin)
    destination = get_airport(session, request.destination)
    if origin.airport_id == destination.airport_id:
        raise InputValidationError("Origin and destination are the same airport")

    row, meta = resolve_aircraft(session, request.aircraft_code, provider)
    props = provider.get_aircraft_properties(meta.aircraft_code)
    params = provider.get_kinematic_parameters(meta.aircraft_code)
    source_row = session.get(DataSource, row.source_id)
    limits_source = (
        f"aircraft_type.source_id={row.source_id} ({source_row.source_name} {source_row.source_version})"
        if source_row else f"aircraft_type.source_id={row.source_id}"
    )
    if source_row is not None and source_row.source_name == "OpenAP" and source_row.source_version != meta.openap_version:
        warnings.append(
            f"Aircraft limits were ingested from OpenAP {source_row.source_version} but OpenAP "
            f"{meta.openap_version} is installed; re-run scripts/ingest_aircraft.py"
        )
    limits = AircraftLimits(
        oew_kg=row.oew_kg, mtow_kg=row.mtow_kg, mlw_kg=row.mlw_kg, mzfw_kg=row.mzfw_kg,
        max_payload_kg=row.max_payload_kg, fuel_capacity_l=row.fuel_capacity_l, source=limits_source,
    )
    for name, db_value, model_value in (
        ("oew_kg", row.oew_kg, props.oew_kg), ("mtow_kg", row.mtow_kg, props.mtow_kg),
        ("mlw_kg", row.mlw_kg, props.mlw_kg), ("fuel_capacity_l", row.fuel_capacity_l, props.fuel_capacity_l),
    ):
        if db_value is not None and model_value is not None and abs(db_value - model_value) > 1e-6:
            warnings.append(f"{name} differs between database ({db_value}) and installed OpenAP ({model_value})")

    # Route --------------------------------------------------------------------
    route = estimate_route_distance(
        origin.latitude, origin.longitude, destination.latitude, destination.longitude,
        route_factor=request.route_factor, user_route_distance_nm=request.route_distance_nm,
    )
    assume("distance_method", DISTANCE_METHOD, None, SOURCE_CONSTANT, "IUGG mean Earth radius R1",
           f"Earth radius {EARTH_MEAN_RADIUS_KM} km; spherical model")
    assume("route_distance_method", route.method, None,
           SOURCE_USER if route.method != "great_circle" else SOURCE_DEFAULT, None, route.description)
    if route.route_factor is not None:
        assume("route_factor", route.route_factor, "ratio", SOURCE_USER if request.route_factor != 1.0 else SOURCE_DEFAULT,
               None, "1.0 means no route extension is assumed")
    assume("wind", "none (ground speed = true airspeed)", None, SOURCE_MODEL, None,
           "Actual winds can materially change flight time and fuel burn")
    assume("atmosphere", "ISA, no temperature deviation", None, SOURCE_MODEL)

    # Elevations ----------------------------------------------------------------
    elevations: dict[str, float] = {}
    for label, airport in (("origin", origin), ("destination", destination)):
        if airport.elevation_ft is None:
            elevations[label] = 0.0
            warnings.append(f"{label} elevation unknown; 0 ft assumed")
            assume(f"{label}_elevation_ft", 0.0, "ft", SOURCE_MODEL, None, "elevation missing in airport data")
        else:
            elevations[label] = airport.elevation_ft
            assume(f"{label}_elevation_ft", airport.elevation_ft, "ft", SOURCE_DATABASE, "airport.elevation_ft")

    # Cruise altitude -------------------------------------------------------------
    ceiling_ft = m_to_ft(props.ceiling_m) if props.ceiling_m else None
    if request.cruise_altitude_ft is not None:
        cruise_ft = float(request.cruise_altitude_ft)
        if ceiling_ft is not None and cruise_ft > ceiling_ft:
            raise InputValidationError(
                f"Cruise altitude {cruise_ft:.0f} ft exceeds the OpenAP ceiling {ceiling_ft:.0f} ft for {meta.aircraft_code}"
            )
        assume("requested_cruise_altitude_ft", cruise_ft, "ft", SOURCE_USER)
    else:
        cruise_ft = _round_down_to_step_ft(m_to_ft(params.cruise_altitude_m) + CRUISE_ALTITUDE_STEP_FT / 2)
        if ceiling_ft is not None:
            cruise_ft = min(cruise_ft, _round_down_to_step_ft(ceiling_ft))
        assume("requested_cruise_altitude_ft", cruise_ft, "ft", SOURCE_OPENAP, params.source,
               "WRAP mean cruise altitude rounded to the nearest 1,000 ft")

    # Profile ---------------------------------------------------------------------
    profile = generate_profile(
        params, route.estimated_route_km * 1000.0, ft_to_m(cruise_ft),
        ft_to_m(elevations["origin"]), ft_to_m(elevations["destination"]), request.time_step_s,
    )
    warnings.extend(profile.warnings)
    assume("cruise_altitude_ft", m_to_ft(profile.cruise_altitude_m), "ft", SOURCE_MODEL, None,
           "altitude actually used (may be lower than requested on short routes)")
    assume("cruise_mach", params.cruise_mach, "Mach", SOURCE_OPENAP, params.source)
    assume("kinematic_parameters", params.source, None, SOURCE_OPENAP, None,
           "typical (mean) WRAP values; kinematics independent of mass")
    assume("time_step_s", request.time_step_s, "s", SOURCE_USER if request.time_step_s != DEFAULT_TIME_STEP_S else SOURCE_DEFAULT)
    assume("integration_method", INTEGRATION_METHOD, None, SOURCE_MODEL)
    assume("takeoff_thrust", "100% rated take-off thrust during the take-off roll (no derate)", None, SOURCE_MODEL,
           "ICAO LTO take-off mode is 100% rated thrust")
    assume("reverse_thrust", "not modelled; landing roll at ground idle", None, SOURCE_MODEL)

    # Taxi ------------------------------------------------------------------------
    taxi_out_min = request.taxi_out_min if request.taxi_out_min is not None else DEFAULT_TAXI_OUT_MIN
    taxi_in_min = request.taxi_in_min if request.taxi_in_min is not None else DEFAULT_TAXI_IN_MIN
    for name, value, given in (("taxi_out_min", taxi_out_min, request.taxi_out_min),
                               ("taxi_in_min", taxi_in_min, request.taxi_in_min)):
        if given is None:
            assume(name, value, "min", SOURCE_DEFAULT, "ICAO Annex 16 Vol. II reference LTO taxi/ground idle 26 min",
                   "26 min split equally (project assumption); not an observed airport-specific taxi time")
        else:
            assume(name, value, "min", SOURCE_USER)

    def fuel_flow(state: FlowState) -> float:
        return provider.get_fuel_flow(meta.aircraft_code, state)

    zfw = zero_fuel_weight(limits.oew_kg, request.payload_kg)
    assume("operating_empty_weight_kg", limits.oew_kg, "kg", SOURCE_DATABASE, limits_source,
           "OpenAP type-level OEW; not operator-specific")
    assume("payload_kg", request.payload_kg, "kg", SOURCE_USER)
    taxi_out_fuel = ground_idle_fuel(fuel_flow, taxi_out_min * 60.0, zfw, elevations["origin"])
    taxi_in_fuel = ground_idle_fuel(fuel_flow, taxi_in_min * 60.0, zfw, elevations["destination"])
    # Ground-idle fuel flow is mass-independent, so landing-roll fuel is fixed before iterating.
    landing_roll_fuel = ground_idle_fuel(fuel_flow, profile.landing_roll_s, zfw, elevations["destination"])
    assume("fuel_accounting_basis", FUEL_ACCOUNTING_BASIS, None, SOURCE_MODEL, None,
           "take-off mass at brake release; landing mass at touchdown; trip fuel = brake release to touchdown; "
           "landing-roll fuel separate; block fuel = taxi-out + trip + landing roll + taxi-in")
    assume("taxi_fuel_flow_kg_s", round((meta.idle_fuel_flow_kg_s_per_engine or 0) * (meta.engine_count or 0), 6),
           "kg/s", SOURCE_OPENAP, f"ICAO Engine Emissions Databank via OpenAP ({meta.engine_model})",
           "idle (7% rated thrust) fuel flow for all engines")

    # Fuel policy -----------------------------------------------------------------
    density = request.fuel_density_kg_per_l or JET_FUEL_DENSITY_KG_PER_L
    assume("fuel_density_kg_per_l", density, "kg/L",
           SOURCE_USER if request.fuel_density_kg_per_l else SOURCE_DEFAULT,
           None if request.fuel_density_kg_per_l else "OpenAP mass.py litre-to-kg factor",
           "generic jet fuel density used to convert fuel capacity (L) to mass; actual batches vary")
    pct = request.contingency_pct_of_trip
    reserves_fixed = request.alternate_fuel_kg + request.final_reserve_fuel_kg
    for name, value, unit in (("contingency_pct_of_trip", pct, "%"),
                              ("alternate_fuel_kg", request.alternate_fuel_kg, "kg"),
                              ("final_reserve_fuel_kg", request.final_reserve_fuel_kg, "kg")):
        assume(name, value, unit, SOURCE_USER if value else SOURCE_DEFAULT, None,
               "user-supplied planning quantity; no regulatory fuel policy is applied")
    if pct == 0 and reserves_fixed == 0:
        warnings.append("No contingency, alternate or final reserve fuel included; not a dispatch fuel plan")

    def planned_fuel(trip: float) -> float:
        return taxi_out_fuel + trip + landing_roll_fuel + taxi_in_fuel + trip * pct / 100.0 + reserves_fixed

    # Iteration -------------------------------------------------------------------
    trip_estimate = integrate_trip(
        profile, zfw + landing_roll_fuel + taxi_in_fuel + reserves_fixed, fuel_flow
    ).trip_fuel_kg
    history = [trip_estimate]
    integration: TripIntegration | None = None
    iterations = 0
    for iterations in range(1, request.max_iterations + 1):
        takeoff_mass = zfw + planned_fuel(trip_estimate) - taxi_out_fuel
        integration = integrate_trip(profile, takeoff_mass, fuel_flow)
        history.append(integration.trip_fuel_kg)
        converged = abs(integration.trip_fuel_kg - trip_estimate) <= request.tolerance_kg
        previous_estimate, trip_estimate = trip_estimate, integration.trip_fuel_kg
        if converged:
            break
    else:
        raise ConvergenceError(
            f"Fuel planning did not converge within {request.max_iterations} iterations "
            f"(tolerance {request.tolerance_kg} kg; trip fuel history {[round(h, 3) for h in history]})"
        )
    assert integration is not None
    if abs(integration.landing_roll_fuel_kg - landing_roll_fuel) > 1e-6:
        raise FuelFlowError("Landing-roll fuel from integration disagrees with ground-idle fuel flow")
    planned = planned_fuel(previous_estimate)
    assume("convergence_tolerance_kg", request.tolerance_kg, "kg",
           SOURCE_USER if request.tolerance_kg != DEFAULT_TOLERANCE_KG else SOURCE_DEFAULT, None,
           f"converged in {iterations} iterations; residual {history[-1] - history[-2]:+.3f} kg")

    checks = evaluate_limits(
        limits,
        payload_kg=request.payload_kg,
        zero_fuel_weight_kg=zfw,
        ramp_mass_kg=integration.takeoff_mass_kg + taxi_out_fuel,
        takeoff_mass_kg=integration.takeoff_mass_kg,
        landing_mass_kg=integration.landing_mass_kg,
        planned_fuel_kg=planned,
        fuel_density_kg_per_l=density,
        mass_trace_kg=[integration.takeoff_mass_kg + taxi_out_fuel, *integration.mass_trace_kg,
                       integration.end_of_landing_roll_mass_kg - taxi_in_fuel],
    )
    status = overall_status(checks)
    unverified = [c.name for c in checks if c.status == "not_performed"]
    if unverified and status != STATUS_INFEASIBLE:
        warnings.append(f"Flight not fully validated; checks not performed: {', '.join(unverified)}")

    phases = _phase_summaries(profile, integration, taxi_out_min, taxi_in_min, taxi_out_fuel, taxi_in_fuel,
                              elevations["origin"], elevations["destination"])

    return FlightEstimateResult(
        request=request,
        aircraft_type_id=row.aircraft_type_id,
        aircraft_code=row.aircraft_code,
        aircraft_description=f"{row.manufacturer or ''} {row.model or ''}".strip(),
        model=meta,
        origin=origin,
        destination=destination,
        route=route,
        profile=profile,
        trip=integration,
        taxi_out_min=taxi_out_min,
        taxi_in_min=taxi_in_min,
        taxi_out_fuel_kg=taxi_out_fuel,
        taxi_in_fuel_kg=taxi_in_fuel,
        contingency_fuel_kg=integration.trip_fuel_kg * pct / 100.0,
        alternate_fuel_kg=request.alternate_fuel_kg,
        final_reserve_fuel_kg=request.final_reserve_fuel_kg,
        planned_fuel_load_kg=planned,
        zero_fuel_weight_kg=zfw,
        fuel_density_kg_per_l=density,
        iterations=iterations,
        iteration_history_kg=history,
        checks=checks,
        status=status,
        assumptions=assumptions,
        warnings=warnings,
        phases=phases,
        input_hash=_input_hash(request, meta.openap_version),
        model_version=f"aircraft_cost_model {__version__}; openap {meta.openap_version}",
    )


def _phase_summaries(
    profile: FlightProfile,
    trip: TripIntegration,
    taxi_out_min: float,
    taxi_in_min: float,
    taxi_out_fuel: float,
    taxi_in_fuel: float,
    origin_ft: float,
    destination_ft: float,
) -> list[PhaseSummary]:
    taxi_out_s, taxi_in_s = taxi_out_min * 60.0, taxi_in_min * 60.0
    ramp = trip.takeoff_mass_kg + taxi_out_fuel
    summaries = [
        PhaseSummary(PHASE_TAXI_OUT, 1, 0.0, taxi_out_s, None, origin_ft, origin_ft, ramp, trip.takeoff_mass_kg,
                     taxi_out_fuel, PHASE_METHODS[PHASE_TAXI_OUT])
    ]
    for sequence, phase in enumerate(PROFILE_PHASES, start=2):
        items = [i for i in trip.intervals if i.interval.phase == phase]
        if items:
            first, last = items[0], items[-1]
            summaries.append(PhaseSummary(
                phase, sequence, taxi_out_s + first.interval.start_time_s,
                sum(i.interval.duration_s for i in items),
                sum(i.interval.distance_m for i in items) / 1000.0 / KM_PER_NM,
                m_to_ft(first.interval.start_altitude_m), m_to_ft(last.interval.end_altitude_m),
                first.start_mass_kg, last.end_mass_kg, sum(i.fuel_kg for i in items), PHASE_METHODS[phase],
            ))
        else:  # e.g. no cruise segment on a short route
            previous = summaries[-1]
            summaries.append(PhaseSummary(
                phase, sequence, previous.start_time_s + previous.duration_s, 0.0, 0.0,
                previous.end_altitude_ft, previous.end_altitude_ft, previous.end_mass_kg, previous.end_mass_kg,
                0.0, PHASE_METHODS[phase],
            ))
    end = summaries[-1]
    summaries.append(PhaseSummary(
        PHASE_TAXI_IN, len(PROFILE_PHASES) + 2, end.start_time_s + end.duration_s, taxi_in_s, None,
        destination_ft, destination_ft, trip.end_of_landing_roll_mass_kg,
        trip.end_of_landing_roll_mass_kg - taxi_in_fuel,
        taxi_in_fuel, PHASE_METHODS[PHASE_TAXI_IN],
    ))
    return summaries
