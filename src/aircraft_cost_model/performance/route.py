"""Great-circle distance and estimated route distance.

Great-circle distance uses the haversine formula on a sphere with the IUGG
mean Earth radius R1 = 6371.0088 km. The spherical approximation differs from
ellipsoidal (geodesic) distance by up to about 0.5 %.

Estimated route distance is the great-circle distance multiplied by an
explicit route factor (default 1.0 = no route extension assumed), or a
user-supplied distance. It is never an actual flown or ATC route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aircraft_cost_model.performance.exceptions import InputValidationError, InvalidCoordinatesError
from aircraft_cost_model.performance.units import KM_PER_NM

EARTH_MEAN_RADIUS_KM = 6371.0088  # IUGG mean radius R1
DISTANCE_METHOD = "haversine, spherical Earth, R = 6371.0088 km (IUGG mean radius)"

METHOD_GREAT_CIRCLE = "great_circle"
METHOD_GREAT_CIRCLE_FACTOR = "great_circle_x_factor"
METHOD_USER_SUPPLIED = "user_supplied"


def _validate_coordinate(lat: float, lon: float) -> None:
    for name, value, limit in (("latitude", lat, 90.0), ("longitude", lon, 180.0)):
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise InvalidCoordinatesError(f"{name} must be a finite number, got {value!r}")
        if not -limit <= value <= limit:
            raise InvalidCoordinatesError(f"{name} {value} outside [-{limit}, {limit}]")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 coordinate pairs (degrees).

    Longitude differences are handled through the trigonometric terms, so
    routes across the International Date Line take the short way round.
    """
    _validate_coordinate(lat1, lon1)
    _validate_coordinate(lat2, lon2)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    a = min(1.0, max(0.0, a))  # guard rounding
    return 2 * EARTH_MEAN_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass(frozen=True)
class RouteDistance:
    """Great-circle and estimated route distance with the method used."""

    great_circle_km: float
    great_circle_nm: float
    estimated_route_nm: float
    method: str
    route_factor: float | None
    description: str

    @property
    def estimated_route_km(self) -> float:
        return self.estimated_route_nm * KM_PER_NM


def estimate_route_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    route_factor: float = 1.0,
    user_route_distance_nm: float | None = None,
) -> RouteDistance:
    """Compute great-circle distance and the estimated route distance.

    Args:
        route_factor: Multiplier >= 1.0 applied to the great-circle distance.
        user_route_distance_nm: Explicit route distance; must not be shorter
            than the great-circle distance. Cannot be combined with a factor != 1.

    Raises:
        InputValidationError: Invalid factor or distance.
        InvalidCoordinatesError: Invalid coordinates.
    """
    gc_km = haversine_km(lat1, lon1, lat2, lon2)
    gc_nm = gc_km / KM_PER_NM
    if route_factor is None or not math.isfinite(route_factor) or route_factor < 1.0:
        raise InputValidationError(f"route_factor must be a finite number >= 1.0, got {route_factor!r}")

    if user_route_distance_nm is not None:
        if route_factor != 1.0:
            raise InputValidationError("Specify either a route factor or a route distance, not both")
        if not math.isfinite(user_route_distance_nm) or user_route_distance_nm < gc_nm * (1 - 1e-9):
            raise InputValidationError(
                f"Route distance {user_route_distance_nm} NM is shorter than the great-circle distance "
                f"{gc_nm:.1f} NM"
            )
        return RouteDistance(
            gc_km, gc_nm, float(user_route_distance_nm), METHOD_USER_SUPPLIED, None,
            "User-supplied route distance (not verified against an actual flown route)",
        )
    if route_factor == 1.0:
        return RouteDistance(
            gc_km, gc_nm, gc_nm, METHOD_GREAT_CIRCLE, 1.0,
            "Great-circle distance; no route extension assumed (not an actual flown route)",
        )
    return RouteDistance(
        gc_km, gc_nm, gc_nm * route_factor, METHOD_GREAT_CIRCLE_FACTOR, float(route_factor),
        f"Great-circle distance x {route_factor} (user-supplied route factor; not an actual flown route)",
    )
