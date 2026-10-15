"""Airport lookup tests against a temporary database with real OurAirports fixture rows."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from aircraft_cost_model.models import Airport
from aircraft_cost_model.performance.airport_lookup import _to_info, get_airport, normalize_airport_code
from aircraft_cost_model.performance.exceptions import (
    AirportNotFoundError,
    AmbiguousAirportError,
    InputValidationError,
    InvalidAirportCoordinatesError,
)


def test_iata_lookup_normalizes_input(flight_engine):
    with Session(flight_engine) as session:
        fra = get_airport(session, " fra ")
    assert fra.icao_code == "EDDF" and fra.matched_field == "iata_code"
    assert fra.latitude == pytest.approx(50.026706) and fra.longitude == pytest.approx(8.55835)


def test_icao_lookup(flight_engine):
    with Session(flight_engine) as session:
        jfk = get_airport(session, "KJFK")
    assert jfk.iata_code == "JFK"


def test_prefixed_lookup(flight_engine):
    with Session(flight_engine) as session:
        assert get_airport(session, "icao:lfpg").iata_code == "CDG"
        with pytest.raises(AirportNotFoundError):
            get_airport(session, "iata:EDDF")  # EDDF is not an IATA code


def test_unknown_airport(flight_engine):
    with Session(flight_engine) as session, pytest.raises(AirportNotFoundError):
        get_airport(session, "ZZZZ")


def test_ambiguous_airport_is_rejected_not_guessed(flight_engine):
    with Session(flight_engine) as session:
        with pytest.raises(AmbiguousAirportError, match="2 airports"):
            get_airport(session, "AGI")
        assert get_airport(session, "ident:AGI").airport_ident == "AGI"
        assert get_airport(session, "iata:AGI").airport_ident == "SMWA"


@pytest.mark.parametrize("bad", ["", "   ", None, "F", "FR A", "xyz:FRA", "FRA!"])
def test_invalid_identifiers_rejected(bad):
    with pytest.raises(InputValidationError):
        normalize_airport_code(bad)


def test_out_of_range_coordinates_rejected(flight_engine):
    with Session(flight_engine) as session, session.begin():
        source_id = session.get(Airport, 1).source_id
        session.add(Airport(source_airport_id=999999, airport_ident="XBAD", latitude=95.0, longitude=0.0,
                            source_id=source_id))
    with Session(flight_engine) as session, pytest.raises(InvalidAirportCoordinatesError):
        get_airport(session, "XBAD")


def test_missing_coordinates_rejected():
    # The schema forbids NULL coordinates; the guard still rejects them if an object lacks them.
    with pytest.raises(InvalidAirportCoordinatesError):
        _to_info(Airport(airport_id=1, airport_ident="XNUL", latitude=None, longitude=None), "airport_ident")
