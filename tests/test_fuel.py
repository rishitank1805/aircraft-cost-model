"""Fuel-flow integration tests with synthetic fuel-flow models (analytic answers)."""

from __future__ import annotations

import math

import pytest

from aircraft_cost_model.performance.exceptions import FuelFlowError
from aircraft_cost_model.performance.fuel import checked_fuel_flow, ground_idle_fuel, integrate_trip
from aircraft_cost_model.performance.openap_adapter import MODE_AIRBORNE, MODE_GROUND_IDLE, MODE_TAKEOFF_ROLL
from aircraft_cost_model.performance.profile import PHASE_LANDING_ROLL, TRIP_PHASES, generate_profile
from aircraft_cost_model.performance.units import ft_to_m, nm_to_km


@pytest.fixture
def profile(a320_params):
    return generate_profile(a320_params, nm_to_km(500) * 1000, ft_to_m(36000), 100.0, 100.0, 30.0)


def test_constant_fuel_flow_unit_conversion(profile):
    """1 kg/s must give exactly as many kilograms as seconds, split at touchdown."""
    trip = integrate_trip(profile, 60000.0, lambda state: 1.0)
    assert trip.trip_fuel_kg == pytest.approx(profile.trip_time_s, rel=1e-12)
    assert trip.landing_roll_fuel_kg == pytest.approx(profile.landing_roll_s, rel=1e-12)
    assert trip.landing_mass_kg == pytest.approx(60000.0 - profile.trip_time_s)
    assert trip.end_of_landing_roll_mass_kg == pytest.approx(60000.0 - profile.end_time_s)


def test_time_step_integration_matches_analytic_solution(profile):
    """ff = c * m gives m(T) = m0 * exp(-c T); RK2 must match closely."""
    c, m0 = 2e-5, 60000.0
    trip = integrate_trip(profile, m0, lambda state: c * state.mass_kg)
    analytic = m0 * (1 - math.exp(-c * profile.end_time_s))
    assert trip.trip_fuel_kg + trip.landing_roll_fuel_kg == pytest.approx(analytic, rel=1e-6)


def test_fuel_positive_and_mass_strictly_decreasing(profile):
    trip = integrate_trip(profile, 60000.0, lambda state: 0.5 + 1e-6 * state.mass_kg)
    assert trip.trip_fuel_kg > 0
    trace = trip.mass_trace_kg
    assert all(b < a for a, b in zip(trace, trace[1:]))
    assert trip.intervals[0].start_mass_kg == 60000.0
    for a, b in zip(trip.intervals, trip.intervals[1:]):
        assert b.start_mass_kg == a.end_mass_kg


def test_modes_passed_to_fuel_flow(profile):
    seen = set()

    def flow(state):
        seen.add(state.mode)
        return 1.0

    integrate_trip(profile, 60000.0, flow)
    assert seen == {MODE_TAKEOFF_ROLL, MODE_AIRBORNE, MODE_GROUND_IDLE}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, "abc"])
def test_invalid_fuel_flow_rejected(profile, bad):
    with pytest.raises(FuelFlowError):
        integrate_trip(profile, 60000.0, lambda state: bad)
    with pytest.raises(FuelFlowError):
        checked_fuel_flow(bad, "test")


def test_mass_exhaustion_rejected(profile):
    with pytest.raises(FuelFlowError, match="non-positive"):
        integrate_trip(profile, 100.0, lambda state: 10.0)


def test_phase_fuel_reconciles_without_double_counting(profile):
    trip = integrate_trip(profile, 60000.0, lambda state: 0.8)
    assert sum(trip.phase_fuel_kg(p) for p in TRIP_PHASES) == pytest.approx(trip.trip_fuel_kg, rel=1e-12)
    assert trip.phase_fuel_kg(PHASE_LANDING_ROLL) == pytest.approx(trip.landing_roll_fuel_kg, rel=1e-12)
    assert sum(i.fuel_kg for i in trip.intervals) == pytest.approx(trip.trip_fuel_kg + trip.landing_roll_fuel_kg)


def test_takeoff_minus_landing_mass_equals_trip_fuel(profile):
    """Regression: landing mass is at touchdown, so the landing roll is not part of trip fuel."""
    trip = integrate_trip(profile, 60000.0, lambda state: 0.3 + 1e-5 * state.mass_kg)
    assert trip.takeoff_mass_kg - trip.landing_mass_kg == pytest.approx(trip.trip_fuel_kg, abs=1e-9)
    first_roll = next(i for i in trip.intervals if i.interval.phase == PHASE_LANDING_ROLL)
    assert trip.landing_mass_kg == first_roll.start_mass_kg  # mass at touchdown
    assert trip.landing_roll_fuel_kg > 0
    assert trip.landing_mass_kg - trip.end_of_landing_roll_mass_kg == pytest.approx(trip.landing_roll_fuel_kg)


def test_landing_roll_must_be_last(profile):
    import dataclasses

    shuffled = dataclasses.replace(profile, intervals=[profile.intervals[-1], *profile.intervals[:-1]])
    with pytest.raises(ValueError, match="must come last"):
        integrate_trip(shuffled, 60000.0, lambda state: 1.0)


def test_ground_idle_fuel():
    assert ground_idle_fuel(lambda s: 0.2, 600.0, 50000.0, 0.0) == pytest.approx(120.0)
    assert ground_idle_fuel(lambda s: 0.2, 0.0, 50000.0, 0.0) == 0.0
    with pytest.raises(FuelFlowError):
        ground_idle_fuel(lambda s: -1.0, 60.0, 50000.0, 0.0)
