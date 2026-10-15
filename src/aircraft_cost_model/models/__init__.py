"""SQLAlchemy ORM models for the master-data tables."""

from aircraft_cost_model.models.aircraft import AircraftType
from aircraft_cost_model.models.airport import Airport
from aircraft_cost_model.models.base import Base
from aircraft_cost_model.models.data_source import DataSource
from aircraft_cost_model.models.flight import FlightAssumption, FlightEstimate, FlightPhase, Route

__all__ = [
    "AircraftType",
    "Airport",
    "Base",
    "DataSource",
    "FlightAssumption",
    "FlightEstimate",
    "FlightPhase",
    "Route",
]
