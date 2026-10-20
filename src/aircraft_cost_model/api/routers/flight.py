"""Flight Performance Lab: runs the Part 2 engine for supported aircraft (results are not saved)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from aircraft_cost_model.api.db import get_session
from aircraft_cost_model.api.routers.aircraft import _provider
from aircraft_cost_model.models import AircraftType, Airport
from aircraft_cost_model.performance.exceptions import (
    AirportLookupError,
    InputValidationError,
    UnsupportedAircraftError,
)

router = APIRouter(tags=["flight"])
MAX_TRAJECTORY_POINTS = 300


class FlightIn(BaseModel):
    aircraft_code: str = Field(min_length=2, max_length=12)
    origin: str = Field(min_length=3, max_length=12)
    destination: str = Field(min_length=3, max_length=12)
    payload_kg: float = Field(ge=0, le=200_000)
    cruise_altitude_ft: float | None = Field(None, ge=10_000, le=45_000)


@router.get("/flight/aircraft")
def supported_aircraft(session: Session = Depends(get_session)) -> dict[str, Any]:
    provider = _provider()
    out = []
    for a in session.scalars(select(AircraftType).where(AircraftType.openap_supported.is_(True))
                             .order_by(AircraftType.aircraft_code)):
        meta = provider.get_model_metadata(a.aircraft_code)
        if meta.supported:
            out.append({"code": a.aircraft_code, "name": f"{a.manufacturer} {a.model}", "model": meta.describe()})
    return {"items": out, "note": "Only aircraft with a complete OpenAP model (climb profile, drag data and engine) are "
                                  "listed. Freighters aren't covered, and a passenger model is never used in their place."}


@router.get("/airports/search")
def airport_search(q: str = Query(..., min_length=2, max_length=40), session: Session = Depends(get_session)
                   ) -> dict[str, Any]:
    needle = q.strip().upper()
    rows = session.scalars(select(Airport).where(
        Airport.airport_type.in_(("large_airport", "medium_airport")),
        or_(Airport.iata_code == needle, Airport.icao_code == needle, Airport.airport_ident == needle,
            Airport.airport_name.ilike(f"%{q.strip()}%"), Airport.municipality.ilike(f"%{q.strip()}%")))
        .order_by(Airport.airport_type, Airport.airport_name).limit(15)).all()
    return {"items": [{"ident": a.airport_ident, "iata": a.iata_code, "icao": a.icao_code, "name": a.airport_name,
                       "city": a.municipality, "country": a.country_code, "type": a.airport_type} for a in rows]}


@router.post("/flight/estimate")
def estimate(body: FlightIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    from aircraft_cost_model.performance.planner import FlightRequest, estimate_flight

    request = FlightRequest(body.aircraft_code, f"ident:{body.origin}" if len(body.origin) > 3 else body.origin,
                            f"ident:{body.destination}" if len(body.destination) > 3 else body.destination,
                            body.payload_kg, cruise_altitude_ft=body.cruise_altitude_ft)
    try:
        r = estimate_flight(session, request, _provider())
    except UnsupportedAircraftError as exc:
        raise HTTPException(422, f"This aircraft can't be modelled: {exc}") from exc
    except (AirportLookupError, InputValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # model errors (route too short, convergence) are reported, not hidden
        raise HTTPException(422, f"The flight couldn't be calculated: {exc}") from exc
    trajectory = r.trajectory()
    step = max(1, len(trajectory) // MAX_TRAJECTORY_POINTS)
    return {
        "saved": False,
        "status": r.status, "feasible": r.is_feasible, "aircraft": r.aircraft_code, "aircraft_name": r.aircraft_description,
        "model": r.model.describe(),
        "origin": {"ident": r.origin.airport_ident, "iata": r.origin.iata_code, "name": r.origin.airport_name},
        "destination": {"ident": r.destination.airport_ident, "iata": r.destination.iata_code,
                        "name": r.destination.airport_name},
        "distance": {"great_circle_nm": r.route.great_circle_nm, "great_circle_km": r.route.great_circle_km,
                     "estimated_route_nm": r.route.estimated_route_nm, "method": r.route.method,
                     "description": r.route.description},
        "times_min": {"taxi_out": r.taxi_out_min, "airborne": r.airborne_time_min, "landing_roll": r.landing_roll_time_min,
                      "taxi_in": r.taxi_in_min, "trip": r.trip_time_min, "block": r.block_time_min},
        "fuel_kg": {"taxi_out": r.taxi_out_fuel_kg, "trip": r.trip_fuel_kg, "landing_roll": r.landing_roll_fuel_kg,
                    "taxi_in": r.taxi_in_fuel_kg, "block": r.block_fuel_kg, "reserve": r.reserve_fuel_kg,
                    "planned_load": r.planned_fuel_load_kg, "per_nm": r.fuel_per_nm_kg,
                    "per_block_hour": r.fuel_per_block_hour_kg},
        "mass_kg": {"zero_fuel": r.zero_fuel_weight_kg, "ramp": r.ramp_weight_kg, "takeoff": r.takeoff_weight_kg,
                    "landing": r.landing_weight_kg, "block_in": r.block_in_weight_kg},
        "phases": [p.__dict__ for p in r.phases],
        "checks": [c.__dict__ for c in r.checks],
        "assumptions": [a.__dict__ for a in r.assumptions],
        "warnings": r.warnings,
        "trajectory": trajectory[::step],
        "labels": ["This is a model estimate (OpenAP, standard atmosphere, no real weather or wind).",
                   "It isn't a fuel plan an airline could fly with, because no fuel reserves are included.",
                   "Where a certified limit isn't available, the check is shown as not checked, never as passed."],
    }
