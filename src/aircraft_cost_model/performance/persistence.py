"""Persist flight estimates (route, estimate, phases, assumptions) in one transaction.

Per-time-step trajectory samples are written to a CSV file under
``data/processed/flights/`` rather than the relational database; the file
path is stored on the estimate.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from aircraft_cost_model.models import FlightAssumption, FlightEstimate, FlightPhase, Route
from aircraft_cost_model.models.base import utc_now
from aircraft_cost_model.performance.mass import STATUS_INFEASIBLE
from aircraft_cost_model.performance.planner import FUEL_ACCOUNTING_BASIS, FlightEstimateResult
from aircraft_cost_model.performance.profile import trajectory_states
from aircraft_cost_model.performance.route import DISTANCE_METHOD
from aircraft_cost_model.performance.units import m_to_ft

logger = logging.getLogger(__name__)

TRAJECTORY_COLUMNS = (
    "time_s", "phase", "mode", "altitude_ft", "true_airspeed_kt", "vertical_speed_fpm",
    "ground_speed_kt", "distance_nm", "aircraft_mass_kg",
)


def upsert_route(session: Session, result: FlightEstimateResult) -> Route:
    """Get or create the route for the airport pair; refresh its distance if coordinates changed."""
    route = session.scalar(
        select(Route).where(
            Route.origin_airport_id == result.origin.airport_id,
            Route.destination_airport_id == result.destination.airport_id,
        )
    )
    if route is None:
        route = Route(
            origin_airport_id=result.origin.airport_id,
            destination_airport_id=result.destination.airport_id,
            great_circle_distance_km=result.route.great_circle_km,
            great_circle_distance_nm=result.route.great_circle_nm,
            distance_method=DISTANCE_METHOD,
        )
        session.add(route)
    elif abs(route.great_circle_distance_km - result.route.great_circle_km) > 1e-9:
        route.great_circle_distance_km = result.route.great_circle_km
        route.great_circle_distance_nm = result.route.great_circle_nm
        route.distance_method = DISTANCE_METHOD
        route.updated_at = utc_now()
    session.flush()
    return route


def write_trajectory_csv(result: FlightEstimateResult, path: Path) -> Path:
    """Write per-step airborne states (with mass) to CSV via a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.part")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRAJECTORY_COLUMNS)
        writer.writeheader()
        for state in trajectory_states(result.profile, result.trip.mass_trace_kg):
            writer.writerow({k: state[k] for k in TRAJECTORY_COLUMNS})
    tmp.replace(path)
    return path


def save_flight_estimate(engine: Engine, result: FlightEstimateResult, trajectory_dir: Path | None = None) -> int:
    """Store a feasible estimate with its phases and assumptions; returns ``flight_estimate_id``.

    Raises:
        ValueError: If the estimate is infeasible (infeasible results are not stored).
    """
    if result.status == STATUS_INFEASIBLE:
        raise ValueError("Infeasible flight estimates are not saved")
    written: Path | None = None
    try:
        with Session(engine) as session, session.begin():
            route = upsert_route(session, result)
            request = result.request
            estimate = FlightEstimate(
                aircraft_type_id=result.aircraft_type_id,
                origin_airport_id=result.origin.airport_id,
                destination_airport_id=result.destination.airport_id,
                route_id=route.route_id,
                payload_kg=request.payload_kg,
                great_circle_distance_nm=result.route.great_circle_nm,
                estimated_route_distance_nm=result.route.estimated_route_nm,
                route_distance_method=result.route.method,
                route_factor=result.route.route_factor,
                cruise_altitude_ft=m_to_ft(result.profile.cruise_altitude_m),
                taxi_out_min=result.taxi_out_min,
                taxi_in_min=result.taxi_in_min,
                airborne_time_min=result.airborne_time_min,
                trip_time_min=result.trip_time_min,
                landing_roll_time_min=result.landing_roll_time_min,
                block_time_min=result.block_time_min,
                zero_fuel_weight_kg=result.zero_fuel_weight_kg,
                ramp_weight_kg=result.ramp_weight_kg,
                takeoff_weight_kg=result.takeoff_weight_kg,
                landing_weight_kg=result.landing_weight_kg,
                trip_fuel_kg=result.trip_fuel_kg,
                taxi_out_fuel_kg=result.taxi_out_fuel_kg,
                taxi_in_fuel_kg=result.taxi_in_fuel_kg,
                taxi_fuel_kg=result.taxi_fuel_kg,
                landing_roll_fuel_kg=result.landing_roll_fuel_kg,
                block_fuel_kg=result.block_fuel_kg,
                reserve_fuel_kg=result.reserve_fuel_kg,
                planned_fuel_load_kg=result.planned_fuel_load_kg,
                fuel_per_nm_kg=result.fuel_per_nm_kg,
                fuel_per_block_hour_kg=result.fuel_per_block_hour_kg,
                fuel_density_kg_per_l=result.fuel_density_kg_per_l,
                time_step_s=request.time_step_s,
                planning_iterations=result.iterations,
                model_name=result.model_name,
                model_version=result.model_version,
                performance_model_code=result.model.aircraft_code,
                engine_model=result.model.engine_model,
                calculation_status=result.status,
                limit_checks=json.dumps([asdict(c) for c in result.checks]),
                warnings=json.dumps(result.warnings) if result.warnings else None,
                input_hash=result.input_hash,
                fuel_accounting_basis=FUEL_ACCOUNTING_BASIS,
            )
            estimate.phases = [
                FlightPhase(
                    phase_name=p.phase, sequence_number=p.sequence_number, start_time_s=p.start_time_s,
                    duration_s=p.duration_s, distance_nm=p.distance_nm, start_altitude_ft=p.start_altitude_ft,
                    end_altitude_ft=p.end_altitude_ft, start_mass_kg=p.start_mass_kg, end_mass_kg=p.end_mass_kg,
                    fuel_burn_kg=p.fuel_burn_kg, fuel_flow_method=p.fuel_flow_method,
                )
                for p in result.phases
            ]
            estimate.assumptions = [
                FlightAssumption(
                    assumption_name=a.name, assumption_value=a.value, assumption_unit=a.unit,
                    source_type=a.source_type, source_reference=a.source_reference, notes=a.notes,
                )
                for a in result.assumptions
            ]
            session.add(estimate)
            session.flush()
            if trajectory_dir is not None:
                written = write_trajectory_csv(
                    result, trajectory_dir / f"flight_estimate_{estimate.flight_estimate_id}_{result.input_hash[:12]}.csv"
                )
                estimate.trajectory_file = str(written)
            estimate_id = estimate.flight_estimate_id
    except Exception:
        if written is not None:
            written.unlink(missing_ok=True)
        raise
    logger.info("flight_estimate_saved", extra={"flight_estimate_id": estimate_id, "status": result.status})
    return estimate_id
