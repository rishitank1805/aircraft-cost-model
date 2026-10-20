"""Time-step fuel integration along a flight profile.

For each profile interval of length dt (explicit midpoint / RK2 in mass):

    ff1   = fuel_flow(state_mid, m_start)            [kg/s]
    m_mid = m_start - ff1 * dt / 2
    ff2   = fuel_flow(state_mid, m_mid)
    burn  = ff2 * dt                                 [kg]
    m_end = m_start - burn

``state_mid`` uses the interval's mid-point altitude and speed, its constant
vertical speed and its acceleration. Every fuel-flow value is checked: a
negative, NaN or infinite result raises :class:`FuelFlowError`.

Fuel-flow modes per interval:
- take-off roll: full rated take-off thrust (``FuelFlow.takeoff``)
- airborne: ``FuelFlow.enroute`` (thrust from drag + climb + acceleration)
- landing roll and taxi: ICAO idle fuel flow (ground idle; no reverse thrust)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from aircraft_cost_model.performance.exceptions import FuelFlowError
from aircraft_cost_model.performance.openap_adapter import (
    MODE_AIRBORNE,
    MODE_GROUND_IDLE,
    MODE_TAKEOFF_ROLL,
    FlowState,
)
from aircraft_cost_model.performance.profile import (
    MODE_LANDING_ROLL,
    PHASE_LANDING_ROLL,
    FlightProfile,
    ProfileInterval,
)
from aircraft_cost_model.performance.profile import MODE_AIRBORNE as PROFILE_AIRBORNE
from aircraft_cost_model.performance.profile import MODE_TAKEOFF_ROLL as PROFILE_TAKEOFF_ROLL
from aircraft_cost_model.performance.units import m_to_ft, ms_to_fpm, ms_to_kt

FuelFlowFunction = Callable[[FlowState], float]

INTEGRATION_METHOD = "explicit midpoint (RK2) in mass, mid-interval kinematic state"

_MODE_MAP = {
    PROFILE_TAKEOFF_ROLL: MODE_TAKEOFF_ROLL,
    PROFILE_AIRBORNE: MODE_AIRBORNE,
    MODE_LANDING_ROLL: MODE_GROUND_IDLE,
}


@dataclass(frozen=True)
class IntervalFuel:
    """Fuel burned in one profile interval."""

    interval: ProfileInterval
    start_mass_kg: float
    end_mass_kg: float
    fuel_kg: float

    @property
    def fuel_flow_kg_s(self) -> float:
        return self.fuel_kg / self.interval.duration_s


@dataclass(frozen=True)
class TripIntegration:
    """Fuel integrated over the profile, split at touchdown.

    Boundaries: ``takeoff_mass_kg`` is the mass at brake release;
    ``landing_mass_kg`` is the mass at touchdown; ``trip_fuel_kg`` is the fuel
    burned between them, so ``takeoff_mass_kg - landing_mass_kg == trip_fuel_kg``.
    Landing-roll fuel (touchdown to rest) is reported separately.
    """

    intervals: list[IntervalFuel]
    takeoff_mass_kg: float

    @property
    def trip_intervals(self) -> list[IntervalFuel]:
        return [i for i in self.intervals if i.interval.phase != PHASE_LANDING_ROLL]

    @property
    def trip_fuel_kg(self) -> float:
        """Brake release to touchdown."""
        return sum(i.fuel_kg for i in self.trip_intervals)

    @property
    def landing_roll_fuel_kg(self) -> float:
        """Touchdown to rest."""
        return sum(i.fuel_kg for i in self.intervals if i.interval.phase == PHASE_LANDING_ROLL)

    @property
    def landing_mass_kg(self) -> float:
        """Mass at touchdown."""
        trip = self.trip_intervals
        return trip[-1].end_mass_kg if trip else self.takeoff_mass_kg

    @property
    def end_of_landing_roll_mass_kg(self) -> float:
        return self.intervals[-1].end_mass_kg if self.intervals else self.takeoff_mass_kg

    @property
    def mass_trace_kg(self) -> list[float]:
        return [self.takeoff_mass_kg] + [i.end_mass_kg for i in self.intervals]

    def phase_fuel_kg(self, phase: str) -> float:
        return sum(i.fuel_kg for i in self.intervals if i.interval.phase == phase)


def checked_fuel_flow(value: float, context: str) -> float:
    """Return ``value`` as float if finite and non-negative, else raise :class:`FuelFlowError`."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FuelFlowError(f"Fuel flow is not numeric ({value!r}) at {context}") from exc
    if not math.isfinite(number):
        raise FuelFlowError(f"Fuel flow is {number} at {context}")
    if number < 0:
        raise FuelFlowError(f"Fuel flow is negative ({number} kg/s) at {context}")
    return number


def _state(interval: ProfileInterval, mass_kg: float) -> FlowState:
    return FlowState(
        mode=_MODE_MAP[interval.mode],
        mass_kg=mass_kg,
        tas_kt=ms_to_kt(interval.mid_tas_ms),
        altitude_ft=m_to_ft(interval.mid_altitude_m),
        vertical_speed_fpm=ms_to_fpm(interval.vertical_speed_ms),
        acceleration_ms2=interval.acceleration_ms2,
    )


def integrate_trip(profile: FlightProfile, takeoff_mass_kg: float, fuel_flow: FuelFlowFunction) -> TripIntegration:
    """Integrate fuel burn over the profile starting at ``takeoff_mass_kg`` (mass at brake release).

    Raises:
        FuelFlowError: Invalid fuel-flow value or mass becoming non-positive.
    """
    if not math.isfinite(takeoff_mass_kg) or takeoff_mass_kg <= 0:
        raise FuelFlowError(f"Invalid take-off mass {takeoff_mass_kg}")
    phases = [i.phase for i in profile.intervals]
    if PHASE_LANDING_ROLL in phases and any(p != PHASE_LANDING_ROLL for p in phases[phases.index(PHASE_LANDING_ROLL):]):
        raise ValueError("Landing-roll intervals must come last; touchdown boundary would be ambiguous")
    mass = takeoff_mass_kg
    results: list[IntervalFuel] = []
    for index, interval in enumerate(profile.intervals):
        context = f"interval {index} ({interval.phase}, t={interval.start_time_s:.0f} s)"
        dt = interval.duration_s
        ff1 = checked_fuel_flow(fuel_flow(_state(interval, mass)), context)
        ff2 = checked_fuel_flow(fuel_flow(_state(interval, mass - 0.5 * ff1 * dt)), context)
        burn = ff2 * dt
        end_mass = mass - burn
        if end_mass <= 0:
            raise FuelFlowError(f"Aircraft mass became non-positive at {context}")
        results.append(IntervalFuel(interval, mass, end_mass, burn))
        mass = end_mass
    return TripIntegration(results, takeoff_mass_kg)


def ground_idle_fuel(fuel_flow: FuelFlowFunction, duration_s: float, mass_kg: float, altitude_ft: float) -> float:
    """Fuel (kg) for ``duration_s`` at ground idle (taxi). Fuel flow at idle is independent of mass."""
    if duration_s == 0:
        return 0.0
    rate = checked_fuel_flow(
        fuel_flow(FlowState(MODE_GROUND_IDLE, mass_kg, 0.0, altitude_ft)), f"ground idle ({duration_s:.0f} s)"
    )
    return rate * duration_s
