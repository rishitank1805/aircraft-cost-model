"""Exception hierarchy for flight performance calculations."""

from __future__ import annotations


class FlightCalculationError(Exception):
    """Base class for all errors raised by the flight performance engine."""


class InputValidationError(FlightCalculationError, ValueError):
    """A user-supplied input is missing, malformed or physically impossible."""


class AirportLookupError(FlightCalculationError):
    """Base class for airport resolution failures."""


class AirportNotFoundError(AirportLookupError):
    """No airport matches the identifier."""


class AmbiguousAirportError(AirportLookupError):
    """More than one airport matches the identifier; none is selected."""


class InvalidAirportCoordinatesError(AirportLookupError):
    """The matched airport has missing or out-of-range coordinates."""


class InvalidCoordinatesError(FlightCalculationError, ValueError):
    """Coordinates passed to a distance calculation are invalid."""


class UnsupportedAircraftError(FlightCalculationError):
    """The aircraft has no validated performance model (e.g. freighters without an OpenAP model)."""


class RouteTooShortError(FlightCalculationError):
    """Climb and descent cannot fit within the route distance, even at the minimum cruise altitude."""


class FuelFlowError(FlightCalculationError):
    """The fuel-flow model returned a negative, NaN or infinite value."""


class ConvergenceError(FlightCalculationError):
    """Iterative fuel planning did not converge within the iteration limit."""
