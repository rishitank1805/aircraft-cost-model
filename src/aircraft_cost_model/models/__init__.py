"""SQLAlchemy ORM models for the master-data tables."""

from aircraft_cost_model.models.aircraft import AircraftType
from aircraft_cost_model.models.airport import Airport
from aircraft_cost_model.models.base import Base
from aircraft_cost_model.models.data_source import DataSource
from aircraft_cost_model.models.flight import FlightAssumption, FlightEstimate, FlightPhase, Route
from aircraft_cost_model.models.fuel_price import FuelPrice
from aircraft_cost_model.models.exchange_rate import ExchangeRate
from aircraft_cost_model.models.navigation_rate import NavigationRate, NavigationZoneAerodrome
from aircraft_cost_model.models.airport_tariff import AirportTariff
from aircraft_cost_model.models.variable_cost import VariableCostEstimate
from aircraft_cost_model.models.cost_component import CostComponent
from aircraft_cost_model.models.full_cost import CostAssumption, CostScenario, FullCostComponent, FullCostEstimate

__all__ = [
    "AircraftType",
    "Airport",
    "AirportTariff",
    "CostAssumption",
    "CostComponent",
    "CostScenario",
    "ExchangeRate",
    "FuelPrice",
    "FullCostComponent",
    "FullCostEstimate",
    "NavigationRate",
    "NavigationZoneAerodrome",
    "VariableCostEstimate",
    "Base",
    "DataSource",
    "FlightAssumption",
    "FlightEstimate",
    "FlightPhase",
    "Route",
]
