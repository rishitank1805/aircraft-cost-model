"""Deterministic kinematic flight profile (no wind) built from WRAP parameters.

The airborne trajectory is a sequence of intervals. Within each interval the
vertical speed is constant and true airspeed changes linearly, so altitude is
exact and distance is the trapezoidal integral of speed. Interval length is
the configured time step, shortened where needed so that every segment
boundary (target altitude, target speed, phase change, route distance) is hit
exactly.

Segment logic follows OpenAP's ``FlightGenerator`` (``openap/gen.py``) with
WRAP default values:

- Take-off roll: constant acceleration from rest to lift-off speed.
- Initial climb to 1,500 ft above the origin; then climb with WRAP mean
  vertical rates for the pre-constant-CAS, constant-CAS and constant-Mach
  bands. Speed accelerates at 0.5 m/s2 (OpenAP's generator constant) until it
  reaches the CAS/Mach schedule, then follows it.
- Cruise: level flight at the schedule TAS (climb CAS / cruise Mach) for
  whatever distance remains.
- Descent with WRAP mean rates for the constant-Mach, constant-CAS and
  post-CAS bands to 1,000 ft above the destination; below the constant-CAS
  band speed decelerates at 0.2 m/s2 (OpenAP constant) to the approach CAS.
- Final approach at the WRAP approach CAS and vertical rate to touchdown,
  then a landing roll (its own phase) at WRAP braking deceleration to rest.

Accounting boundaries:
- trip (phases ``TRIP_PHASES``): brake release -> touchdown
- landing roll (``PHASE_LANDING_ROLL``): touchdown -> rest, always last

Simplifications: kinematics are independent of aircraft mass and use typical
(mean) WRAP values; no wind, so ground speed equals true airspeed; ISA
atmosphere; small instantaneous speed changes are allowed at phase boundaries
where WRAP parameters differ (e.g. cruise Mach vs descent Mach).

If climb and descent do not fit in the route distance, the cruise altitude is
lowered in 1,000 ft steps (with a warning) down to a minimum of 1,500 ft above
the origin / 1,000 ft above the destination; below that
:class:`RouteTooShortError` is raised.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from aircraft_cost_model.performance import atmosphere
from aircraft_cost_model.performance.exceptions import InputValidationError, RouteTooShortError
from aircraft_cost_model.performance.units import KM_PER_NM, ft_to_m, m_to_ft, ms_to_fpm, ms_to_kt

# Constants taken from OpenAP 2.6.2 FlightGenerator (openap/gen.py).
CLIMB_ACCELERATION_MS2 = 0.5
DESCENT_DECELERATION_MS2 = 0.2
INITIAL_CLIMB_HEIGHT_FT = 1500.0
FINAL_APPROACH_HEIGHT_FT = 1000.0
# Project modelling choice: cruise altitudes are whole thousands of feet.
CRUISE_ALTITUDE_STEP_FT = 1000.0

PHASE_TAXI_OUT = "taxi_out"
PHASE_TAKEOFF = "takeoff"
PHASE_CLIMB = "climb"
PHASE_CRUISE = "cruise"
PHASE_DESCENT = "descent"
PHASE_APPROACH = "approach"
PHASE_LANDING_ROLL = "landing_roll"
PHASE_TAXI_IN = "taxi_in"
# Brake release -> touchdown (take-off includes the take-off roll and initial climb).
TRIP_PHASES = (PHASE_TAKEOFF, PHASE_CLIMB, PHASE_CRUISE, PHASE_DESCENT, PHASE_APPROACH)
# Everything in the generated profile: trip phases, then the landing roll.
PROFILE_PHASES = (*TRIP_PHASES, PHASE_LANDING_ROLL)
ALL_PHASES = (PHASE_TAXI_OUT, *PROFILE_PHASES, PHASE_TAXI_IN)

MODE_TAKEOFF_ROLL = "takeoff_roll"
MODE_AIRBORNE = "airborne"
MODE_LANDING_ROLL = "landing_roll"

_EPS = 1e-9


@dataclass(frozen=True)
class KinematicParameters:
    """WRAP-derived kinematic parameters in SI units (m, m/s, m/s2)."""

    source: str
    liftoff_speed_ms: float
    takeoff_acceleration_ms2: float
    initial_climb_vs_ms: float
    climb_cas_ms: float
    climb_cas_start_altitude_m: float
    climb_vs_pre_cas_ms: float
    climb_vs_cas_ms: float
    climb_vs_mach_ms: float
    cruise_mach: float
    cruise_altitude_m: float
    descent_mach: float
    descent_cas_ms: float
    descent_cas_end_altitude_m: float
    descent_vs_mach_ms: float
    descent_vs_cas_ms: float
    descent_vs_post_cas_ms: float
    approach_cas_ms: float
    approach_vs_ms: float
    touchdown_speed_ms: float
    landing_deceleration_ms2: float

    def validate(self) -> None:
        """Check signs and finiteness so the generated profile is physically consistent."""
        positive = (
            "liftoff_speed_ms", "takeoff_acceleration_ms2", "initial_climb_vs_ms", "climb_cas_ms",
            "climb_vs_pre_cas_ms", "climb_vs_cas_ms", "climb_vs_mach_ms", "cruise_mach", "cruise_altitude_m",
            "descent_mach", "descent_cas_ms", "approach_cas_ms", "touchdown_speed_ms",
        )
        negative = (
            "descent_vs_mach_ms", "descent_vs_cas_ms", "descent_vs_post_cas_ms", "approach_vs_ms",
            "landing_deceleration_ms2",
        )
        for name in positive + negative:
            value = getattr(self, name)
            if not math.isfinite(value):
                raise InputValidationError(f"Kinematic parameter {name} is not finite")
        for name in positive:
            if getattr(self, name) <= 0:
                raise InputValidationError(f"Kinematic parameter {name} must be positive")
        for name in negative:
            if getattr(self, name) >= 0:
                raise InputValidationError(f"Kinematic parameter {name} must be negative")


@dataclass(frozen=True)
class ProfileInterval:
    """One integration interval with constant vertical speed and linear speed change."""

    phase: str
    mode: str
    start_time_s: float
    duration_s: float
    start_altitude_m: float
    end_altitude_m: float
    start_tas_ms: float
    end_tas_ms: float
    start_distance_m: float
    end_distance_m: float

    @property
    def end_time_s(self) -> float:
        return self.start_time_s + self.duration_s

    @property
    def vertical_speed_ms(self) -> float:
        return (self.end_altitude_m - self.start_altitude_m) / self.duration_s

    @property
    def acceleration_ms2(self) -> float:
        return (self.end_tas_ms - self.start_tas_ms) / self.duration_s

    @property
    def mid_altitude_m(self) -> float:
        return 0.5 * (self.start_altitude_m + self.end_altitude_m)

    @property
    def mid_tas_ms(self) -> float:
        return 0.5 * (self.start_tas_ms + self.end_tas_ms)

    @property
    def distance_m(self) -> float:
        return self.end_distance_m - self.start_distance_m


@dataclass
class FlightProfile:
    """Airborne profile from brake release to end of the landing roll."""

    intervals: list[ProfileInterval]
    cruise_altitude_m: float
    requested_cruise_altitude_m: float
    route_distance_m: float
    time_step_s: float
    parameters: KinematicParameters
    warnings: list[str] = field(default_factory=list)

    @property
    def trip_time_s(self) -> float:
        """Brake release to touchdown (take-off roll + airborne)."""
        return sum(i.duration_s for i in self.intervals if i.phase != PHASE_LANDING_ROLL)

    @property
    def end_time_s(self) -> float:
        """Brake release to end of landing roll."""
        return self.intervals[-1].end_time_s

    @property
    def takeoff_roll_s(self) -> float:
        return sum(i.duration_s for i in self.intervals if i.mode == MODE_TAKEOFF_ROLL)

    @property
    def landing_roll_s(self) -> float:
        return sum(i.duration_s for i in self.intervals if i.mode == MODE_LANDING_ROLL)

    @property
    def airborne_time_s(self) -> float:
        """Lift-off to touchdown."""
        return sum(i.duration_s for i in self.intervals if i.mode == MODE_AIRBORNE)

    def phase_duration_s(self, phase: str) -> float:
        return sum(i.duration_s for i in self.intervals if i.phase == phase)

    def phase_distance_m(self, phase: str) -> float:
        return sum(i.distance_m for i in self.intervals if i.phase == phase)


def _climb_side(p: KinematicParameters, origin_m: float, cruise_m: float, dt: float) -> list[ProfileInterval]:
    """Take-off roll, initial climb and climb to ``cruise_m`` starting at t=0, s=0."""
    out: list[ProfileInterval] = []
    t = s = 0.0
    h, v = origin_m, 0.0

    def add(phase: str, mode: str, step: float, h1: float, v1: float) -> None:
        nonlocal t, s, h, v
        ds = 0.5 * (v + v1) * step
        out.append(ProfileInterval(phase, mode, t, step, h, h1, v, v1, s, s + ds))
        t, s, h, v = t + step, s + ds, h1, v1

    while v < p.liftoff_speed_ms - _EPS:
        step = min(dt, (p.liftoff_speed_ms - v) / p.takeoff_acceleration_ms2)
        add(PHASE_TAKEOFF, MODE_TAKEOFF_ROLL, step, h, min(v + p.takeoff_acceleration_ms2 * step, p.liftoff_speed_ms))

    ic_end = origin_m + ft_to_m(INITIAL_CLIMB_HEIGHT_FT)
    crossover = atmosphere.crossover_altitude_m(p.climb_cas_ms, p.cruise_mach)
    boundaries = sorted(b for b in {ic_end, p.climb_cas_start_altitude_m, crossover, cruise_m} if b > origin_m)

    def vertical_speed(alt: float) -> float:
        if alt < ic_end - _EPS:
            return p.initial_climb_vs_ms
        if alt < p.climb_cas_start_altitude_m - _EPS:
            return p.climb_vs_pre_cas_ms
        if alt < crossover - _EPS:
            return p.climb_vs_cas_ms
        return p.climb_vs_mach_ms

    def target(alt: float) -> float:
        return atmosphere.schedule_tas(p.climb_cas_ms, p.cruise_mach, alt)

    while h < cruise_m - _EPS:
        boundary = min(b for b in boundaries if b > h + _EPS and b <= cruise_m + _EPS)
        vs = vertical_speed(h)
        step = min(dt, (boundary - h) / vs)
        if v < target(h) - 1e-6:
            step = min(step, max((target(h) - v) / CLIMB_ACCELERATION_MS2, 1e-3))
        h1 = boundary if abs(h + vs * step - boundary) < 1e-6 else h + vs * step
        goal = target(h1)
        v1 = min(v + CLIMB_ACCELERATION_MS2 * step, goal) if v < goal else goal
        add(PHASE_TAKEOFF if h < ic_end - _EPS else PHASE_CLIMB, MODE_AIRBORNE, step, h1, v1)
    return out


def _descent_side(p: KinematicParameters, cruise_m: float, dest_m: float, dt: float) -> list[ProfileInterval]:
    """Descent, final approach and landing roll from ``cruise_m``, starting at t=0, s=0."""
    out: list[ProfileInterval] = []
    t = s = 0.0
    h = cruise_m
    v = atmosphere.schedule_tas(p.descent_cas_ms, p.descent_mach, cruise_m)

    def add(phase: str, mode: str, step: float, h1: float, v1: float) -> None:
        nonlocal t, s, h, v
        ds = 0.5 * (v + v1) * step
        out.append(ProfileInterval(phase, mode, t, step, h, h1, v, v1, s, s + ds))
        t, s, h, v = t + step, s + ds, h1, v1

    fa_start = dest_m + ft_to_m(FINAL_APPROACH_HEIGHT_FT)
    crossover = atmosphere.crossover_altitude_m(p.descent_cas_ms, p.descent_mach)
    boundaries = sorted({b for b in (crossover, p.descent_cas_end_altitude_m, fa_start, dest_m) if b < cruise_m})

    def vertical_speed(alt: float) -> float:
        if alt > fa_start + _EPS:
            if alt > crossover + _EPS:
                return p.descent_vs_mach_ms
            if alt > p.descent_cas_end_altitude_m + _EPS:
                return p.descent_vs_cas_ms
            return p.descent_vs_post_cas_ms
        return p.approach_vs_ms

    def speed(alt_end: float, step: float) -> float:
        approach_tas = atmosphere.cas_to_tas(p.approach_cas_ms, alt_end)
        if alt_end > p.descent_cas_end_altitude_m + _EPS and alt_end >= fa_start - _EPS:
            return atmosphere.schedule_tas(p.descent_cas_ms, p.descent_mach, alt_end)
        if v > approach_tas:
            return max(v - DESCENT_DECELERATION_MS2 * step, approach_tas)
        return approach_tas

    while h > dest_m + _EPS:
        boundary = max(b for b in boundaries if b < h - _EPS)
        vs = vertical_speed(h)
        step = min(dt, (boundary - h) / vs)
        h1 = boundary if abs(h + vs * step - boundary) < 1e-6 else h + vs * step
        phase = PHASE_DESCENT if h > fa_start + _EPS else PHASE_APPROACH
        add(phase, MODE_AIRBORNE, step, h1, speed(h1, step))

    v = p.touchdown_speed_ms  # touchdown speed from WRAP
    decel = -p.landing_deceleration_ms2
    while v > _EPS:
        step = min(dt, v / decel)
        add(PHASE_LANDING_ROLL, MODE_LANDING_ROLL, step, dest_m, max(v - decel * step, 0.0))
    return out


def _cruise(
    p: KinematicParameters, cruise_m: float, distance_m: float, t0: float, s0: float, dt: float
) -> list[ProfileInterval]:
    out: list[ProfileInterval] = []
    v = atmosphere.schedule_tas(p.climb_cas_ms, p.cruise_mach, cruise_m)
    remaining, t, s = distance_m, t0, s0
    while remaining > 1e-6:
        step = min(dt, remaining / v)
        ds = v * step
        out.append(ProfileInterval(PHASE_CRUISE, MODE_AIRBORNE, t, step, cruise_m, cruise_m, v, v, s, s + ds))
        t, s, remaining = t + step, s + ds, remaining - ds
    return out


def _shift(intervals: list[ProfileInterval], dt: float, ds: float) -> list[ProfileInterval]:
    return [
        ProfileInterval(
            i.phase, i.mode, i.start_time_s + dt, i.duration_s, i.start_altitude_m, i.end_altitude_m,
            i.start_tas_ms, i.end_tas_ms, i.start_distance_m + ds, i.end_distance_m + ds,
        )
        for i in intervals
    ]


def generate_profile(
    parameters: KinematicParameters,
    route_distance_m: float,
    cruise_altitude_m: float,
    origin_elevation_m: float,
    destination_elevation_m: float,
    time_step_s: float = 30.0,
) -> FlightProfile:
    """Build a profile whose ground distance equals ``route_distance_m`` exactly.

    Raises:
        InputValidationError: Invalid distance, time step, altitude or parameters.
        RouteTooShortError: Even the minimum cruise altitude does not fit.
    """
    parameters.validate()
    for name, value in (("route_distance_m", route_distance_m), ("time_step_s", time_step_s)):
        if not math.isfinite(value) or value <= 0:
            raise InputValidationError(f"{name} must be positive, got {value}")
    step_m = ft_to_m(CRUISE_ALTITUDE_STEP_FT)
    minimum_m = max(
        origin_elevation_m + ft_to_m(INITIAL_CLIMB_HEIGHT_FT),
        destination_elevation_m + ft_to_m(FINAL_APPROACH_HEIGHT_FT),
    )
    minimum_m = math.ceil(minimum_m / step_m - 1e-9) * step_m
    if not math.isfinite(cruise_altitude_m) or cruise_altitude_m < minimum_m:
        raise InputValidationError(
            f"Cruise altitude {m_to_ft(cruise_altitude_m):.0f} ft is below the minimum "
            f"{m_to_ft(minimum_m):.0f} ft for these airports"
        )

    candidate = cruise_altitude_m
    while candidate >= minimum_m - 1e-6:
        climb = _climb_side(parameters, origin_elevation_m, candidate, time_step_s)
        descent = _descent_side(parameters, candidate, destination_elevation_m, time_step_s)
        fixed = climb[-1].end_distance_m + descent[-1].end_distance_m
        if fixed <= route_distance_m + 1e-6:
            cruise = _cruise(
                parameters, candidate, max(route_distance_m - fixed, 0.0),
                climb[-1].end_time_s, climb[-1].end_distance_m, time_step_s,
            )
            last = cruise[-1] if cruise else climb[-1]
            intervals = climb + cruise + _shift(descent, last.end_time_s, last.end_distance_m)
            warnings: list[str] = []
            if candidate < cruise_altitude_m - 1e-6:
                warnings.append(
                    f"Route too short to reach {m_to_ft(cruise_altitude_m):.0f} ft; cruise altitude lowered to "
                    f"{m_to_ft(candidate):.0f} ft"
                )
            return FlightProfile(
                intervals, candidate, cruise_altitude_m, route_distance_m, time_step_s, parameters, warnings
            )
        candidate = (math.ceil(candidate / step_m - 1e-9) - 1) * step_m
    raise RouteTooShortError(
        f"Route of {route_distance_m / 1000 / KM_PER_NM:.1f} NM is too short for the modelled climb and descent "
        f"even at the minimum cruise altitude {m_to_ft(minimum_m):.0f} ft"
    )


def trajectory_states(profile: FlightProfile, masses_kg: list[float] | None = None) -> list[dict[str, float | str]]:
    """Time-ordered states at interval boundaries (spec format; no wind, so ground speed = TAS).

    ``masses_kg`` must have ``len(intervals) + 1`` entries when given.
    """
    if masses_kg is not None and len(masses_kg) != len(profile.intervals) + 1:
        raise ValueError("masses_kg must have one entry per interval boundary")
    states: list[dict[str, float | str]] = []
    for index, interval in enumerate(profile.intervals):
        states.append(_state(interval, interval.start_time_s, interval.start_altitude_m, interval.start_tas_ms,
                             interval.start_distance_m, masses_kg[index] if masses_kg else math.nan))
    last = profile.intervals[-1]
    states.append(_state(last, last.end_time_s, last.end_altitude_m, last.end_tas_ms, last.end_distance_m,
                         masses_kg[-1] if masses_kg else math.nan))
    return states


def _state(interval: ProfileInterval, t: float, h: float, v: float, s: float, mass: float) -> dict[str, float | str]:
    return {
        "time_s": t,
        "phase": interval.phase,
        "mode": interval.mode,
        "altitude_ft": m_to_ft(h),
        "true_airspeed_kt": ms_to_kt(v),
        "vertical_speed_fpm": ms_to_fpm(interval.vertical_speed_ms),
        "ground_speed_kt": ms_to_kt(v),
        "distance_nm": s / 1000.0 / KM_PER_NM,
        "aircraft_mass_kg": mass,
    }
