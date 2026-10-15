"""Exceptions for variable cost calculations."""

from __future__ import annotations


class CostCalculationError(Exception):
    """Base class for variable cost errors."""


class CostInputError(CostCalculationError, ValueError):
    """A user-supplied cost input is malformed or inconsistent."""


class LegacyFuelAccountingError(CostCalculationError):
    """The flight estimate uses the legacy v1 fuel accounting basis and is not reinterpreted."""


class FlightEstimateNotFoundError(CostCalculationError):
    """The requested flight estimate does not exist."""


class ObservationUnavailableError(CostCalculationError):
    """No acceptable price or rate observation exists for the pricing date."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class CurrencyMismatchError(CostCalculationError):
    """Amounts in different currencies were about to be added."""


class SourceSchemaError(CostCalculationError):
    """A source file no longer has the expected structure (schema change)."""
