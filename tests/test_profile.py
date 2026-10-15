"""Kinematic flight profile tests (pure maths; fixed A320 WRAP parameters)."""

from __future__ import annotations

import dataclasses

import pytest

from aircraft_cost_model.performance.exceptions import InputValidationError, RouteTooShortError
from aircraft_cost_model.performance.profile import (
    MODE_AIRBORNE,
    PHASE_LANDING_ROLL,
    PROFILE_PHASES,
    PHASE_CLIMB,
    PHASE_CRUISE,
    PHASE_DESCENT,
    generate_profile,
    trajectory_states,
)
from aircraft_cost_model.performance.units import ft_to_m, nm_to_km

FRA_FT, CDG_FT = 364.0, 392.0


def _profile(params, nm: float, cruise_ft: float = 36000.0, dt: float = 30.0):
    return generate_profile(params, nm_to_km(nm) * 1000, ft_to_m(cruise_ft), ft_to_m(FRA_FT), ft_to_m(CDG_FT), dt)


def test_states_are_chronological_and_contiguous(a320_params):
    p = _profile(a320_params, 1000)
    for a, b in zip(p.intervals, p.intervals[1:]):
        assert b.start_time_s == pytest.approx(a.end_time_s)
        assert b.start_distance_m == pytest.approx(a.end_distance_m)
        assert b.start_altitude_m == pytest.approx(a.end_altitude_m)  # altitude continuity
    assert p.intervals[0].start_time_s == 0.0
    assert all(i.duration_s > 0 for i in p.intervals)
    assert all(i.duration_s <= p.time_step_s + 1e-9 for i in p.intervals)


def test_phase_order_and_nonnegative_durations(a320_params):
    p = _profile(a320_params, 1000)
    order = [i.phase for i in p.intervals]
    assert [ph for k, ph in enumerate(order) if k == 0 or order[k - 1] != ph] == list(PROFILE_PHASES)
    assert order[-1] == PHASE_LANDING_ROLL
    for phase in PROFILE_PHASES:
        assert p.phase_duration_s(phase) >= 0


def test_altitude_transitions_valid(a320_params):
    p = _profile(a320_params, 1000)
    climb = [i for i in p.intervals if i.phase == PHASE_CLIMB]
    descent = [i for i in p.intervals if i.phase == PHASE_DESCENT]
    assert all(i.end_altitude_m >= i.start_altitude_m for i in climb)
    assert all(i.end_altitude_m <= i.start_altitude_m for i in descent)
    assert climb[-1].end_altitude_m == pytest.approx(ft_to_m(36000))
    assert all(i.start_altitude_m == i.end_altitude_m == ft_to_m(36000) for i in p.intervals if i.phase == PHASE_CRUISE)
    assert p.intervals[0].start_altitude_m == pytest.approx(ft_to_m(FRA_FT))
    assert p.intervals[-1].end_altitude_m == pytest.approx(ft_to_m(CDG_FT))


def test_positive_speed_when_airborne(a320_params):
    p = _profile(a320_params, 1000)
    assert all(i.start_tas_ms > 0 and i.end_tas_ms > 0 for i in p.intervals if i.mode == MODE_AIRBORNE)
    assert p.intervals[0].start_tas_ms == 0.0 and p.intervals[-1].end_tas_ms == pytest.approx(0.0)


@pytest.mark.parametrize("nm", [60, 250, 1000, 5000])
def test_distance_reconciles_exactly(a320_params, nm):
    p = _profile(a320_params, nm)
    assert p.intervals[-1].end_distance_m == pytest.approx(nm_to_km(nm) * 1000, rel=1e-9)
    assert sum(p.phase_distance_m(ph) for ph in PROFILE_PHASES) == pytest.approx(nm_to_km(nm) * 1000, rel=1e-9)
    assert p.trip_time_s == pytest.approx(p.takeoff_roll_s + p.airborne_time_s)  # brake release -> touchdown
    assert p.end_time_s == pytest.approx(p.trip_time_s + p.landing_roll_s)
    assert p.landing_roll_s == pytest.approx(p.phase_duration_s(PHASE_LANDING_ROLL))


def test_short_route_lowers_cruise_altitude(a320_params):
    p = _profile(a320_params, 60)
    assert p.cruise_altitude_m < ft_to_m(36000)
    assert p.cruise_altitude_m == pytest.approx(round(p.cruise_altitude_m / ft_to_m(1000)) * ft_to_m(1000))
    assert any("cruise altitude lowered" in w for w in p.warnings)
    assert p.phase_duration_s(PHASE_CRUISE) >= 0


def test_long_route_keeps_requested_altitude(a320_params):
    p = _profile(a320_params, 2000)
    assert p.cruise_altitude_m == pytest.approx(ft_to_m(36000)) and not p.warnings


def test_route_too_short_raises(a320_params):
    with pytest.raises(RouteTooShortError):
        _profile(a320_params, 3)


def test_invalid_inputs_rejected(a320_params):
    with pytest.raises(InputValidationError):
        _profile(a320_params, 500, cruise_ft=500)  # below minimum altitude
    with pytest.raises(InputValidationError):
        _profile(a320_params, 500, dt=0)
    with pytest.raises(InputValidationError):
        _profile(dataclasses.replace(a320_params, descent_vs_cas_ms=5.0), 500)


def test_trajectory_state_format(a320_params):
    p = _profile(a320_params, 300)
    states = trajectory_states(p, [70000.0 - k for k in range(len(p.intervals) + 1)])
    assert set(states[0]) >= {"time_s", "phase", "altitude_ft", "true_airspeed_kt", "vertical_speed_fpm",
                              "ground_speed_kt", "distance_nm", "aircraft_mass_kg"}
    assert all(s["ground_speed_kt"] == s["true_airspeed_kt"] for s in states)  # no-wind assumption
    assert [s["time_s"] for s in states] == sorted(s["time_s"] for s in states)
    assert states[-1]["distance_nm"] == pytest.approx(300)
    with pytest.raises(ValueError):
        trajectory_states(p, [1.0])
