"""``aircraft_type`` table: aircraft master data."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aircraft_cost_model.models.base import Base, TimestampMixin


class AircraftType(TimestampMixin, Base):
    """One aircraft type or variant.

    Values are NULL when no free source provides them. ``field_provenance`` is a
    JSON object mapping each populated attribute to ``"source"`` or a
    ``"derived: <method>"`` description, so derived values and unit conversions
    are always labelled.
    """

    __tablename__ = "aircraft_type"

    aircraft_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aircraft_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    icao_type_designator: Mapped[str | None] = mapped_column(String(4), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    variant: Mapped[str | None] = mapped_column(String(100))
    engine_type: Mapped[str | None] = mapped_column(String(50))
    engine_model: Mapped[str | None] = mapped_column(String(100))
    engine_count: Mapped[int | None] = mapped_column(Integer)
    mtow_kg: Mapped[float | None] = mapped_column(Float)
    mlw_kg: Mapped[float | None] = mapped_column(Float)
    mzfw_kg: Mapped[float | None] = mapped_column(Float)
    oew_kg: Mapped[float | None] = mapped_column(Float)
    max_payload_kg: Mapped[float | None] = mapped_column(Float)
    fuel_capacity_l: Mapped[float | None] = mapped_column(Float)
    fuel_capacity_kg: Mapped[float | None] = mapped_column(Float)
    cruise_mach: Mapped[float | None] = mapped_column(Float)
    cruise_altitude_m: Mapped[float | None] = mapped_column(Float)
    cruise_speed_kt: Mapped[float | None] = mapped_column(Float)
    openap_supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    openap_coverage: Mapped[str | None] = mapped_column(String(50))
    openap_related_code: Mapped[str | None] = mapped_column(String(8))
    field_provenance: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False)
