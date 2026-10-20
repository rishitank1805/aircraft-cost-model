"""Part 2 tables: routes, flight estimates, phase summaries and assumptions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aircraft_cost_model.models.base import Base, TimestampMixin, utc_now


class Route(TimestampMixin, Base):
    """Stable airport-pair reference data (great-circle distance only).

    Scenario-specific route factors and adjusted distances belong to
    :class:`FlightEstimate`, not here.
    """

    __tablename__ = "route"
    __table_args__ = (
        UniqueConstraint("origin_airport_id", "destination_airport_id", name="uq_route_origin_destination"),
    )

    route_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    origin_airport_id: Mapped[int] = mapped_column(ForeignKey("airport.airport_id"), nullable=False, index=True)
    destination_airport_id: Mapped[int] = mapped_column(
        ForeignKey("airport.airport_id"), nullable=False, index=True
    )
    great_circle_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    great_circle_distance_nm: Mapped[float] = mapped_column(Float, nullable=False)
    distance_method: Mapped[str] = mapped_column(String(200), nullable=False)


class FlightEstimate(Base):
    """One modelled flight (inputs, results and model provenance). Not a dispatch fuel plan.

    See ``fuel_accounting_basis`` for the mass/fuel boundaries used by each row.
    """

    __tablename__ = "flight_estimate"
    __table_args__ = (
        Index("ix_flight_estimate_aircraft_type_id", "aircraft_type_id"),
        Index("ix_flight_estimate_route_id", "route_id"),
        Index("ix_flight_estimate_origin_destination", "origin_airport_id", "destination_airport_id"),
        Index("ix_flight_estimate_input_hash", "input_hash"),
    )

    flight_estimate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aircraft_type_id: Mapped[int] = mapped_column(ForeignKey("aircraft_type.aircraft_type_id"), nullable=False)
    origin_airport_id: Mapped[int] = mapped_column(ForeignKey("airport.airport_id"), nullable=False)
    destination_airport_id: Mapped[int] = mapped_column(ForeignKey("airport.airport_id"), nullable=False)
    route_id: Mapped[int] = mapped_column(ForeignKey("route.route_id"), nullable=False)
    payload_kg: Mapped[float] = mapped_column(Float, nullable=False)
    great_circle_distance_nm: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_route_distance_nm: Mapped[float] = mapped_column(Float, nullable=False)
    route_distance_method: Mapped[str] = mapped_column(String(50), nullable=False)
    route_factor: Mapped[float | None] = mapped_column(Float)
    cruise_altitude_ft: Mapped[float] = mapped_column(Float, nullable=False)
    taxi_out_min: Mapped[float] = mapped_column(Float, nullable=False)
    taxi_in_min: Mapped[float] = mapped_column(Float, nullable=False)
    airborne_time_min: Mapped[float] = mapped_column(Float, nullable=False)
    trip_time_min: Mapped[float] = mapped_column(Float, nullable=False)
    landing_roll_time_min: Mapped[float | None] = mapped_column(Float)
    block_time_min: Mapped[float] = mapped_column(Float, nullable=False)
    zero_fuel_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    ramp_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    takeoff_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    landing_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    trip_fuel_kg: Mapped[float] = mapped_column(Float, nullable=False)
    taxi_out_fuel_kg: Mapped[float] = mapped_column(Float, nullable=False)
    taxi_in_fuel_kg: Mapped[float] = mapped_column(Float, nullable=False)
    taxi_fuel_kg: Mapped[float] = mapped_column(Float, nullable=False)
    landing_roll_fuel_kg: Mapped[float | None] = mapped_column(Float)
    block_fuel_kg: Mapped[float] = mapped_column(Float, nullable=False)
    reserve_fuel_kg: Mapped[float] = mapped_column(Float, nullable=False)
    planned_fuel_load_kg: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_per_nm_kg: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_per_block_hour_kg: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_density_kg_per_l: Mapped[float] = mapped_column(Float, nullable=False)
    time_step_s: Mapped[float] = mapped_column(Float, nullable=False)
    planning_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str] = mapped_column(String(200), nullable=False)
    performance_model_code: Mapped[str] = mapped_column(String(8), nullable=False)
    engine_model: Mapped[str | None] = mapped_column(String(100))
    calculation_status: Mapped[str] = mapped_column(String(50), nullable=False)
    limit_checks: Mapped[str] = mapped_column(Text, nullable=False)
    warnings: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # "v1": rows saved before migration 0003 (trip fuel and landing mass to end of landing roll).
    # "v2": take-off mass at brake release, landing mass at touchdown, trip fuel between them.
    fuel_accounting_basis: Mapped[str] = mapped_column(
        String(10), nullable=False, default="v2", server_default="v1"
    )
    trajectory_file: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    phases: Mapped[list["FlightPhase"]] = relationship(
        back_populates="flight_estimate", cascade="all, delete-orphan", order_by="FlightPhase.sequence_number"
    )
    assumptions: Mapped[list["FlightAssumption"]] = relationship(
        back_populates="flight_estimate", cascade="all, delete-orphan"
    )


class FlightPhase(Base):
    """Per-phase summary of a flight estimate."""

    __tablename__ = "flight_phase"
    __table_args__ = (
        UniqueConstraint("flight_estimate_id", "sequence_number", name="uq_flight_phase_sequence"),
    )

    flight_phase_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flight_estimate_id: Mapped[int] = mapped_column(
        ForeignKey("flight_estimate.flight_estimate_id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase_name: Mapped[str] = mapped_column(String(30), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    distance_nm: Mapped[float | None] = mapped_column(Float)
    start_altitude_ft: Mapped[float] = mapped_column(Float, nullable=False)
    end_altitude_ft: Mapped[float] = mapped_column(Float, nullable=False)
    start_mass_kg: Mapped[float] = mapped_column(Float, nullable=False)
    end_mass_kg: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_burn_kg: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_flow_method: Mapped[str] = mapped_column(String(200), nullable=False)

    flight_estimate: Mapped[FlightEstimate] = relationship(back_populates="phases")


class FlightAssumption(Base):
    """An input or modelling assumption that influenced a flight estimate."""

    __tablename__ = "flight_assumption"
    __table_args__ = (
        UniqueConstraint("flight_estimate_id", "assumption_name", name="uq_flight_assumption_name"),
    )

    assumption_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flight_estimate_id: Mapped[int] = mapped_column(
        ForeignKey("flight_estimate.flight_estimate_id", ondelete="CASCADE"), nullable=False, index=True
    )
    assumption_name: Mapped[str] = mapped_column(String(100), nullable=False)
    assumption_value: Mapped[str] = mapped_column(Text, nullable=False)
    assumption_unit: Mapped[str | None] = mapped_column(String(30))
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    flight_estimate: Mapped[FlightEstimate] = relationship(back_populates="assumptions")
