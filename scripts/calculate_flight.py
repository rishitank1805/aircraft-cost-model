"""Estimate route distance, flight/block time and fuel for one flight.

Example (from the repository root, after ``pip install -e .``)::

    python scripts/calculate_flight.py --aircraft A320 --origin FRA --destination CDG --payload-kg 10000 --save

Results are model estimates for cost analysis, not dispatch fuel plans.
Exit codes: 0 success, 1 input/model error, 2 infeasible loading.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy.orm import Session

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.logging_config import configure_logging
from aircraft_cost_model.performance.exceptions import FlightCalculationError
from aircraft_cost_model.performance.mass import CHECK_FAILED, CHECK_NOT_PERFORMED
from aircraft_cost_model.performance.openap_adapter import OpenAPPerformanceProvider
from aircraft_cost_model.performance.persistence import save_flight_estimate
from aircraft_cost_model.performance.planner import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_TIME_STEP_S,
    DEFAULT_TOLERANCE_KG,
    FlightEstimateResult,
    FlightRequest,
    estimate_flight,
)
from aircraft_cost_model.performance.units import m_to_ft

logger = logging.getLogger("calculate_flight")


def _minutes(value: float) -> str:
    hours, minutes = divmod(round(value), 60)
    return f"{value:6.1f} min ({hours}h{minutes:02d})"


def _assumed(user_value: float | None) -> str:
    return "  [assumption: default, half of ICAO LTO 26 min; not airport-specific]" if user_value is None else "  [user input]"


def render(result: FlightEstimateResult) -> str:
    """Human-readable report of a completed estimate."""
    r = result
    phase = r.phase
    lines = [
        "AIRCRAFT FLIGHT ESTIMATE  (model estimate - not a dispatch fuel plan)",
        "",
        "AIRCRAFT",
        f"  Type:                     {r.aircraft_code} ({r.aircraft_description})",
        f"  Performance model:        {r.model.describe()}",
        f"  Engine model:             {r.model.engine_model} x {r.model.engine_count}",
        f"  Payload:                  {r.request.payload_kg:,.0f} kg",
        "",
        "ROUTE",
        f"  Origin:                   {r.origin.label} ({r.origin.latitude:.4f}, {r.origin.longitude:.4f}, "
        f"{r.origin.elevation_ft if r.origin.elevation_ft is not None else 'n/a'} ft)",
        f"  Destination:              {r.destination.label} ({r.destination.latitude:.4f}, "
        f"{r.destination.longitude:.4f}, {r.destination.elevation_ft if r.destination.elevation_ft is not None else 'n/a'} ft)",
        f"  Great-circle distance:    {r.route.great_circle_nm:,.1f} NM ({r.route.great_circle_km:,.1f} km)",
        f"  Estimated route distance: {r.route.estimated_route_nm:,.1f} NM  [{r.route.description}]",
        f"  Cruise altitude:          {m_to_ft(r.profile.cruise_altitude_m):,.0f} ft",
        "",
        "FLIGHT TIME",
        f"  Taxi-out:                 {_minutes(r.taxi_out_min)}{_assumed(r.request.taxi_out_min)}",
        f"  Take-off (roll + initial climb): {_minutes(phase('takeoff').duration_s / 60)}",
        f"  Climb:                    {_minutes(phase('climb').duration_s / 60)}",
        f"  Cruise:                   {_minutes(phase('cruise').duration_s / 60)}",
        f"  Descent:                  {_minutes(phase('descent').duration_s / 60)}",
        f"  Approach:                 {_minutes(phase('approach').duration_s / 60)}",
        f"  Airborne (lift-off to touchdown): {_minutes(r.airborne_time_min)}",
        f"  Trip (brake release to touchdown): {_minutes(r.trip_time_min)}",
        f"  Landing roll:             {_minutes(r.landing_roll_time_min)}",
        f"  Taxi-in:                  {_minutes(r.taxi_in_min)}{_assumed(r.request.taxi_in_min)}",
        f"  Block time:               {_minutes(r.block_time_min)}",
        "",
        "AIRCRAFT MASS",
        f"  Zero fuel weight:         {r.zero_fuel_weight_kg:,.0f} kg",
        f"  Ramp weight:              {r.ramp_weight_kg:,.0f} kg",
        f"  Take-off weight (brake release): {r.takeoff_weight_kg:,.0f} kg",
        f"  Landing weight (touchdown):      {r.landing_weight_kg:,.0f} kg",
        f"  Block-in weight:          {r.block_in_weight_kg:,.0f} kg",
        "",
        "FUEL",
        f"  Taxi fuel:                {r.taxi_fuel_kg:,.0f} kg (out {r.taxi_out_fuel_kg:,.0f} / in {r.taxi_in_fuel_kg:,.0f})",
        f"  Trip fuel (brake release to touchdown = take-off - landing weight): {r.trip_fuel_kg:,.0f} kg",
    ]
    for p in r.phases[1:-2]:
        lines.append(f"    {p.phase:<22}  {p.fuel_burn_kg:>9,.1f} kg")
    lines += [
        f"  Landing roll fuel:        {r.landing_roll_fuel_kg:,.1f} kg",
        f"  Block fuel:               {r.block_fuel_kg:,.0f} kg (taxi-out + trip + landing roll + taxi-in)",
        f"  Reserves (user-supplied): {r.reserve_fuel_kg:,.0f} kg",
        f"  Planned fuel load:        {r.planned_fuel_load_kg:,.0f} kg",
        f"  Fuel per nautical mile:   {r.fuel_per_nm_kg:,.2f} kg/NM (trip fuel / estimated route distance)",
        f"  Fuel per block hour:      {r.fuel_per_block_hour_kg:,.0f} kg/h (block fuel / block time)",
        "",
        "LOADING CHECKS",
    ]
    for c in r.checks:
        detail = f"{c.value:,.0f} {c.comparison} {c.limit:,.0f} {c.unit}" if c.value is not None and c.limit is not None else ""
        lines.append(f"  {c.name:<30} {c.status:<14} {detail} {c.note}".rstrip())
    lines += ["", "MODEL INFORMATION", f"  OpenAP version:           {r.model.openap_version}",
              f"  Model:                    {r.model_name} ({r.model_version})",
              f"  Route assumption:         {r.route.description}",
              f"  Fuel density:             {r.fuel_density_kg_per_l} kg/L",
              f"  Planning iterations:      {r.iterations} (trip fuel history: "
              + ", ".join(f"{h:,.1f}" for h in r.iteration_history_kg) + " kg)",
              "  Assumptions:"]
    for a in r.assumptions:
        lines.append(f"    - {a.name} = {a.value}{(' ' + a.unit) if a.unit else ''} [{a.source_type}]"
                     + (f" - {a.notes}" if a.notes else ""))
    lines.append("  Warnings:")
    lines += [f"    - {w}" for w in r.warnings] or ["    (none)"]
    lines.append(f"  Calculation status:       {r.status}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aircraft", required=True, help="Aircraft code, e.g. A320 (see verify_database.py).")
    parser.add_argument("--origin", required=True, help="IATA, ICAO or OurAirports ident (prefix iata:/icao:/ident: to disambiguate).")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--payload-kg", type=float, required=True)
    parser.add_argument("--cruise-altitude-ft", type=float)
    parser.add_argument("--taxi-out-min", type=float, help="Default 13 (half of ICAO LTO 26 min taxi time).")
    parser.add_argument("--taxi-in-min", type=float, help="Default 13 (half of ICAO LTO 26 min taxi time).")
    distance = parser.add_mutually_exclusive_group()
    distance.add_argument("--route-factor", type=float, default=1.0, help="Multiplier >= 1 on great-circle distance.")
    distance.add_argument("--route-distance-nm", type=float, help="Explicit route distance (>= great-circle).")
    parser.add_argument("--fuel-density-kg-per-l", type=float, help="Default 0.8025 (OpenAP mass.py).")
    parser.add_argument("--contingency-pct", type=float, default=0.0, help="Contingency fuel as %% of trip fuel.")
    parser.add_argument("--alternate-fuel-kg", type=float, default=0.0)
    parser.add_argument("--final-reserve-fuel-kg", type=float, default=0.0)
    parser.add_argument("--time-step-s", type=float, default=DEFAULT_TIME_STEP_S)
    parser.add_argument("--tolerance-kg", type=float, default=DEFAULT_TOLERANCE_KG)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--save", action="store_true", help="Store the estimate in SQLite and write the trajectory CSV.")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging("WARNING" if settings.log_level == "INFO" else settings.log_level)
    if not settings.database_path.is_file():
        print(f"Database not found: {settings.database_path}. Run the ingestion scripts first.")
        return 1
    migrate_database(settings.database_url)
    engine = create_db_engine(settings.database_url)

    request = FlightRequest(
        aircraft_code=args.aircraft, origin=args.origin, destination=args.destination, payload_kg=args.payload_kg,
        cruise_altitude_ft=args.cruise_altitude_ft, taxi_out_min=args.taxi_out_min, taxi_in_min=args.taxi_in_min,
        route_factor=args.route_factor, route_distance_nm=args.route_distance_nm,
        fuel_density_kg_per_l=args.fuel_density_kg_per_l, contingency_pct_of_trip=args.contingency_pct,
        alternate_fuel_kg=args.alternate_fuel_kg, final_reserve_fuel_kg=args.final_reserve_fuel_kg,
        time_step_s=args.time_step_s, tolerance_kg=args.tolerance_kg, max_iterations=args.max_iterations,
    )
    try:
        with Session(engine) as session:
            result = estimate_flight(session, request, OpenAPPerformanceProvider())
    except FlightCalculationError as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1

    if not result.is_feasible:
        print("FLIGHT ESTIMATE INFEASIBLE - loading limits violated; no results are reported.\n")
        for check in result.checks:
            if check.status == CHECK_FAILED:
                print(f"  FAILED {check.name}: {check.value:,.0f} {check.unit} vs limit {check.limit:,.0f} {check.unit} "
                      f"({check.note})")
        not_done = [c.name for c in result.checks if c.status == CHECK_NOT_PERFORMED]
        if not_done:
            print(f"  Not checked (data unavailable): {', '.join(not_done)}")
        print("\nReduce payload, add fuel stops or choose a different aircraft. Nothing was saved.")
        return 2

    print(render(result))
    if args.save:
        estimate_id = save_flight_estimate(engine, result, settings.processed_flights_dir)
        print(f"\nSaved as flight_estimate_id={estimate_id} (trajectory CSV in {settings.processed_flights_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
