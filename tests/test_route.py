"""Great-circle and route distance tests (no database, no network)."""

from __future__ import annotations

import math
import random

import pytest

from aircraft_cost_model.performance.exceptions import InputValidationError, InvalidCoordinatesError
from aircraft_cost_model.performance.route import (
    EARTH_MEAN_RADIUS_KM,
    METHOD_GREAT_CIRCLE,
    METHOD_GREAT_CIRCLE_FACTOR,
    METHOD_USER_SUPPLIED,
    estimate_route_distance,
    haversine_km,
)
from aircraft_cost_model.performance.units import KM_PER_NM, km_to_nm, nm_to_km

R = EARTH_MEAN_RADIUS_KM


@pytest.mark.parametrize(
    "points, expected_km",
    [
        (((0, 0), (0, 90)), math.pi / 2 * R),  # quarter of the equator
        (((90, 0), (-90, 0)), math.pi * R),  # pole to pole
        (((0, 0), (0, 180)), math.pi * R),  # antipodal on the equator
        (((10, 20), (11, 20)), math.pi / 180 * R),  # one degree along a meridian
        (((-33.9, 151.2), (-34.9, 151.2)), math.pi / 180 * R),  # southern hemisphere meridian
    ],
)
def test_known_great_circle_distances(points, expected_km):
    (lat1, lon1), (lat2, lon2) = points
    assert haversine_km(lat1, lon1, lat2, lon2) == pytest.approx(expected_km, rel=1e-12)


def test_matches_independent_spherical_law_of_cosines():
    rng = random.Random(42)
    for _ in range(200):
        lat1, lat2 = rng.uniform(-89, 89), rng.uniform(-89, 89)
        lon1, lon2 = rng.uniform(-180, 180), rng.uniform(-180, 180)
        p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
        cos_c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
        expected = R * math.acos(max(-1.0, min(1.0, cos_c)))
        assert haversine_km(lat1, lon1, lat2, lon2) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("lat", [0.0, 60.0, -45.0])
def test_international_date_line_takes_short_way(lat):
    across = haversine_km(lat, 179.5, lat, -179.5)
    same_side = haversine_km(lat, -0.5, lat, 0.5)
    assert across == pytest.approx(same_side, rel=1e-12)
    assert across < 200  # not the ~20,000 km long way round


def test_identical_coordinates_give_zero():
    assert haversine_km(50.0, 8.5, 50.0, 8.5) == 0.0


def test_very_short_distance_is_accurate():
    # 0.0001 degree of latitude ~ 11.1 m
    assert haversine_km(50.0, 8.5, 50.0001, 8.5) * 1000 == pytest.approx(math.pi / 180 * R * 0.1, rel=1e-6)


@pytest.mark.parametrize(
    "coords",
    [(91, 0, 0, 0), (0, 181, 0, 0), (0, 0, -90.5, 0), (float("nan"), 0, 0, 0), (None, 0, 0, 0), (0, float("inf"), 0, 0)],
)
def test_invalid_coordinates_raise(coords):
    with pytest.raises(InvalidCoordinatesError):
        haversine_km(*coords)


def test_unit_conversion():
    assert KM_PER_NM == 1.852
    assert km_to_nm(1852.0) == pytest.approx(1000.0)
    assert nm_to_km(km_to_nm(123.4)) == pytest.approx(123.4)
    route = estimate_route_distance(0, 0, 0, 1)
    assert route.great_circle_nm == pytest.approx(route.great_circle_km / 1.852)
    assert route.estimated_route_km == pytest.approx(route.great_circle_km)


def test_default_route_is_great_circle():
    route = estimate_route_distance(50.0, 8.5, 49.0, 2.5)
    assert route.method == METHOD_GREAT_CIRCLE
    assert route.route_factor == 1.0
    assert route.estimated_route_nm == route.great_circle_nm
    assert "not an actual flown route" in route.description


def test_route_factor_application():
    route = estimate_route_distance(50.0, 8.5, 49.0, 2.5, route_factor=1.05)
    assert route.method == METHOD_GREAT_CIRCLE_FACTOR
    assert route.estimated_route_nm == pytest.approx(route.great_circle_nm * 1.05)


def test_user_supplied_route_distance():
    gc = estimate_route_distance(50.0, 8.5, 49.0, 2.5).great_circle_nm
    route = estimate_route_distance(50.0, 8.5, 49.0, 2.5, user_route_distance_nm=gc + 20)
    assert route.method == METHOD_USER_SUPPLIED and route.estimated_route_nm == pytest.approx(gc + 20)


@pytest.mark.parametrize("kwargs", [{"route_factor": 0.9}, {"route_factor": float("nan")},
                                    {"user_route_distance_nm": 1.0},
                                    {"route_factor": 1.1, "user_route_distance_nm": 1000.0}])
def test_invalid_route_assumptions_rejected(kwargs):
    with pytest.raises(InputValidationError):
        estimate_route_distance(50.0, 8.5, 49.0, 2.5, **kwargs)
