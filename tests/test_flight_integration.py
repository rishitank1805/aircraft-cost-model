"""End-to-end flight estimates with the installed OpenAP package (no network).

The end-to-end aircraft is the A320, a passenger aircraft directly supported by
OpenAP. These tests validate the pipeline; they are NOT cargo-aircraft results.
"""

from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aircraft_cost_model.models import FlightAssumption, FlightEstimate, FlightPhase, Route
from aircraft_cost_model.performance.exceptions import (
    ConvergenceError,
    InputValidationError,
    UnsupportedAircraftError,
)
from aircraft_cost_model.performance.mass import STATUS_INFEASIBLE, STATUS_LIMITS_UNVERIFIED
from aircraft_cost_model.performance.persistence import save_flight_estimate
from aircraft_cost_model.performance.planner import FlightRequest, estimate_flight
from aircraft_cost_model.performance.profile import ALL_PHASES, MODE_LANDING_ROLL, TRIP_PHASES

A320_FRA_CDG = FlightRequest("A320", "FRA", "CDG", payload_kg=10000)


def _estimate(engine, provider, request=A320_FRA_CDG):
    with Session(engine) as session:
        return estimate_flight(session, request, provider)


def test_supported_aircraft_excludes_freighters_and_synonyms(openap_provider):
    supported = openap_provider.get_supported_aircraft()
    assert "A320" in supported
    assert not {"B763", "A21N", "B77L", "B772"} & set(supported)  # missing WRAP/polar; no synonyms
    meta = openap_provider.get_model_metadata("A21N")
    assert not meta.supported and any("WRAP" in r for r in meta.unsupported_reasons)


def test_end_to_end_a320(flight_engine, openap_provider):
    r = _estimate(flight_engine, openap_provider)
    assert r.status == STATUS_LIMITS_UNVERIFIED  # MZFW / max payload unavailable -> not fully validated
    assert r.model.aircraft_code == "A320" and r.model.engine_model == "CFM56-5B4"
    assert r.model.openap_version == "2.6.2"
    assert 230 < r.route.great_circle_nm < 260
    assert r.trip_fuel_kg > 0 and r.taxi_fuel_kg > 0
    assert r.takeoff_weight_kg > r.landing_weight_kg > r.zero_fuel_weight_kg
    assert r.zero_fuel_weight_kg == pytest.approx(42600 + 10000)
    assert r.fuel_per_nm_kg == pytest.approx(r.trip_fuel_kg / r.route.estimated_route_nm)
    assert r.fuel_per_block_hour_kg == pytest.approx(r.block_fuel_kg / (r.block_time_min / 60))
    assert any("not a dispatch fuel plan" in w for w in r.warnings)


def test_durations_reconcile(flight_engine, openap_provider):
    r = _estimate(flight_engine, openap_provider)
    assert r.block_time_min == pytest.approx(r.taxi_out_min + r.trip_time_min + r.landing_roll_time_min + r.taxi_in_min)
    assert sum(p.duration_s for p in r.phases) / 60 == pytest.approx(r.block_time_min)
    profile = r.profile
    assert profile.trip_time_s == pytest.approx(profile.takeoff_roll_s + profile.airborne_time_s)
    assert r.landing_roll_time_min == pytest.approx(r.phase("landing_roll").duration_s / 60)
    assert [p.phase for p in r.phases] == list(ALL_PHASES)
    assert all(p.duration_s >= 0 for p in r.phases)
    for a, b in zip(r.phases, r.phases[1:]):
        assert b.start_time_s == pytest.approx(a.start_time_s + a.duration_s)


def test_fuel_and_mass_reconcile_without_double_counting(flight_engine, openap_provider):
    r = _estimate(flight_engine, openap_provider)
    trip = sum(p.fuel_burn_kg for p in r.phases if p.phase in TRIP_PHASES)
    assert trip == pytest.approx(r.trip_fuel_kg)
    assert sum(p.fuel_burn_kg for p in r.phases) == pytest.approx(r.block_fuel_kg)
    assert r.block_fuel_kg == pytest.approx(
        r.taxi_out_fuel_kg + r.trip_fuel_kg + r.landing_roll_fuel_kg + r.taxi_in_fuel_kg)
    assert r.ramp_weight_kg - r.taxi_out_fuel_kg == pytest.approx(r.takeoff_weight_kg)
    assert r.takeoff_weight_kg - r.trip_fuel_kg == pytest.approx(r.landing_weight_kg)
    for a, b in zip(r.phases, r.phases[1:]):
        assert b.start_mass_kg == pytest.approx(a.end_mass_kg)
        assert a.end_mass_kg <= a.start_mass_kg
    assert r.planned_fuel_load_kg == pytest.approx(r.ramp_weight_kg - r.zero_fuel_weight_kg)


def test_mass_and_fuel_boundaries_are_consistent(flight_engine, openap_provider):
    """Regression: take-off mass (brake release) - landing mass (touchdown) == trip fuel exactly."""
    r = _estimate(flight_engine, openap_provider)
    assert r.takeoff_weight_kg - r.landing_weight_kg == pytest.approx(r.trip_fuel_kg, abs=1e-6)
    states = r.trajectory()
    assert states[0]["aircraft_mass_kg"] == r.takeoff_weight_kg and states[0]["time_s"] == 0.0
    touchdown = next(s for s in states if s["mode"] == MODE_LANDING_ROLL)
    assert touchdown["aircraft_mass_kg"] == pytest.approx(r.landing_weight_kg, abs=1e-9)
    assert touchdown["altitude_ft"] == pytest.approx(r.destination.elevation_ft)
    assert touchdown["time_s"] == pytest.approx(r.trip_time_min * 60)
    assert 0 < r.landing_roll_fuel_kg < 0.01 * r.trip_fuel_kg
    assert r.phase("landing_roll").fuel_burn_kg == pytest.approx(r.landing_roll_fuel_kg)
    assert r.phase("landing_roll").start_mass_kg == pytest.approx(r.landing_weight_kg)
    mlw = next(c for c in r.checks if c.name == "mlw")
    assert mlw.value == pytest.approx(r.landing_weight_kg)  # MLW checked at touchdown
    assert r.block_in_weight_kg == pytest.approx(r.landing_weight_kg - r.landing_roll_fuel_kg - r.taxi_in_fuel_kg)
    assert r.block_in_weight_kg == pytest.approx(r.zero_fuel_weight_kg + r.reserve_fuel_kg, abs=1.0)


def test_iterative_planning_converges_monotonically(flight_engine, openap_provider):
    r = _estimate(flight_engine, openap_provider, FlightRequest("A320", "FRA", "CDG", 10000, contingency_pct_of_trip=5,
                                                               final_reserve_fuel_kg=1100))
    history = r.iteration_history_kg
    assert all(b >= a - 1e-9 for a, b in zip(history, history[1:]))  # starts from a lower bound
    assert abs(history[-1] - history[-2]) <= 1.0
    assert r.contingency_fuel_kg == pytest.approx(0.05 * r.trip_fuel_kg)
    assert r.reserve_fuel_kg == pytest.approx(r.contingency_fuel_kg + 1100)
    assert r.landing_weight_kg - r.zero_fuel_weight_kg == pytest.approx(
        r.landing_roll_fuel_kg + r.taxi_in_fuel_kg + r.reserve_fuel_kg, abs=2.0)  # reserves on board at block-in


def test_iterative_planning_non_convergence(flight_engine, openap_provider):
    request = dataclasses.replace(A320_FRA_CDG, max_iterations=1, tolerance_kg=1e-9)
    with pytest.raises(ConvergenceError, match="did not converge"):
        _estimate(flight_engine, openap_provider, request)


def test_identical_inputs_give_identical_results(flight_engine, openap_provider):
    a, b = _estimate(flight_engine, openap_provider), _estimate(flight_engine, openap_provider)
    assert a.input_hash == b.input_hash
    assert a.trip_fuel_kg == b.trip_fuel_kg and a.block_time_min == b.block_time_min
    assert a.trajectory() == b.trajectory()


@pytest.mark.parametrize("code", ["A330-200F", "B777F", "B767-300F", "B747-400F", "A321P2F"])
def test_freighters_return_explicit_unsupported_error(flight_engine, openap_provider, code):
    with pytest.raises(UnsupportedAircraftError, match="not substituted"):
        _estimate(flight_engine, openap_provider, FlightRequest(code, "FRA", "JFK", 50000))


@pytest.mark.parametrize("code, missing", [("B763", "drag polar"), ("A21N", "WRAP")])
def test_openap_type_without_complete_model_is_unsupported(flight_engine, openap_provider, code, missing):
    with pytest.raises(UnsupportedAircraftError, match=missing):
        _estimate(flight_engine, openap_provider, FlightRequest(code, "FRA", "JFK", 20000))


def test_unknown_aircraft_and_designator_hint(flight_engine, openap_provider):
    with pytest.raises(UnsupportedAircraftError, match="B777F"):
        _estimate(flight_engine, openap_provider, FlightRequest("B77L", "FRA", "JFK", 20000))


def test_infeasible_loading_scenarios(flight_engine, openap_provider):
    fuel = _estimate(flight_engine, openap_provider, FlightRequest("A320", "FRA", "JFK", 10000))
    assert fuel.status == STATUS_INFEASIBLE
    assert {c.name for c in fuel.checks if c.status == "failed"} == {"fuel_capacity"}
    heavy = _estimate(flight_engine, openap_provider, FlightRequest("A320", "FRA", "CDG", 40000))
    assert heavy.status == STATUS_INFEASIBLE
    assert "mtow" in {c.name for c in heavy.checks if c.status == "failed"}
    with pytest.raises(ValueError, match="not saved"):
        save_flight_estimate(flight_engine, heavy)


@pytest.mark.parametrize("change", [{"payload_kg": -1}, {"origin": "CDG"}, {"cruise_altitude_ft": 60000},
                                    {"route_factor": 0.8}, {"time_step_s": 0}])
def test_invalid_requests_rejected(flight_engine, openap_provider, change):
    request = dataclasses.replace(A320_FRA_CDG, **change)
    with pytest.raises(InputValidationError):
        _estimate(flight_engine, openap_provider, request)


def test_persistence_of_estimate_phases_and_assumptions(flight_engine, openap_provider, tmp_path: Path):
    r = _estimate(flight_engine, openap_provider)
    first = save_flight_estimate(flight_engine, r, tmp_path / "flights")
    second = save_flight_estimate(flight_engine, _estimate(flight_engine, openap_provider), tmp_path / "flights")
    with Session(flight_engine) as session:
        estimate = session.get(FlightEstimate, first)
        assert estimate.trip_fuel_kg == pytest.approx(r.trip_fuel_kg)
        assert estimate.block_time_min == pytest.approx(r.block_time_min)
        assert estimate.calculation_status == r.status
        assert estimate.model_version == r.model_version and estimate.engine_model == "CFM56-5B4"
        assert estimate.fuel_accounting_basis == "v2"
        assert estimate.landing_roll_fuel_kg == pytest.approx(r.landing_roll_fuel_kg)
        assert estimate.takeoff_weight_kg - estimate.landing_weight_kg == pytest.approx(estimate.trip_fuel_kg)
        assert [p.phase_name for p in estimate.phases] == list(ALL_PHASES)
        assert sum(p.fuel_burn_kg for p in estimate.phases) == pytest.approx(estimate.block_fuel_kg)
        names = {a.assumption_name: a for a in estimate.assumptions}
        assert names["fuel_density_kg_per_l"].assumption_value == "0.8025"
        assert names["taxi_out_min"].source_type == "project_default"
        assert names["wind"].assumption_value.startswith("none")
        assert len(estimate.assumptions) == len(r.assumptions)
        assert {c["name"] for c in json.loads(estimate.limit_checks)} >= {"mtow", "mlw", "mzfw"}
        rows = list(csv.DictReader(open(estimate.trajectory_file, encoding="utf-8")))
        assert len(rows) == len(r.profile.intervals) + 1
        assert float(rows[-1]["aircraft_mass_kg"]) == pytest.approx(r.trip.end_of_landing_roll_mass_kg)
        assert session.get(FlightEstimate, second).input_hash == estimate.input_hash
        assert session.scalar(select(func.count()).select_from(Route)) == 1  # route reused
        assert session.scalar(select(func.count()).select_from(FlightPhase)) == 2 * len(ALL_PHASES)
        assert session.scalar(select(func.count()).select_from(FlightAssumption)) == 2 * len(r.assumptions)


def test_cli_end_to_end(flight_db, tmp_path, monkeypatch, capsys):
    from scripts_loader import load_script

    monkeypatch.setenv("ACM_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ACM_DATABASE_PATH", flight_db.removeprefix("sqlite:///"))
    cli = load_script("calculate_flight")
    assert cli.main(["--aircraft", "a320", "--origin", "FRA", "--destination", "CDG", "--payload-kg", "10000",
                     "--save"]) == 0
    out = capsys.readouterr().out
    assert "AIRCRAFT FLIGHT ESTIMATE" in out and "Calculation status:       calculated_limits_unverified" in out
    assert "Saved as flight_estimate_id=1" in out
    assert list((tmp_path / "data" / "processed" / "flights").glob("flight_estimate_1_*.csv"))
    assert cli.main(["--aircraft", "B777F", "--origin", "FRA", "--destination", "JFK", "--payload-kg", "50000"]) == 1
    assert "UnsupportedAircraftError" in capsys.readouterr().out
    assert cli.main(["--aircraft", "A320", "--origin", "FRA", "--destination", "JFK", "--payload-kg", "10000"]) == 2
    assert "INFEASIBLE" in capsys.readouterr().out
