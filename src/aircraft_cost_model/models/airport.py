"""``airport`` table: airport master data from OurAirports."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from aircraft_cost_model.models.base import Base, TimestampMixin


class Airport(TimestampMixin, Base):
    """One airport, heliport, seaplane base, balloonport or closed airfield.

    IATA codes are indexed but deliberately *not* unique: the source does not
    guarantee uniqueness and closed/historic airports may reuse codes.
    """

    __tablename__ = "airport"
    __table_args__ = (
        Index("ix_airport_iata_code", "iata_code"),
        Index("ix_airport_icao_code", "icao_code"),
        Index("ix_airport_gps_code", "gps_code"),
        Index("ix_airport_country_code", "country_code"),
        Index("ix_airport_airport_type", "airport_type"),
    )

    airport_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_airport_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    airport_ident: Mapped[str] = mapped_column(String(16), nullable=False)
    airport_name: Mapped[str | None] = mapped_column(String(255))
    airport_type: Mapped[str | None] = mapped_column(String(32))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_ft: Mapped[float | None] = mapped_column(Float)
    continent: Mapped[str | None] = mapped_column(String(2))
    country_code: Mapped[str | None] = mapped_column(String(2))
    region_code: Mapped[str | None] = mapped_column(String(16))
    municipality: Mapped[str | None] = mapped_column(String(255))
    scheduled_service: Mapped[bool | None] = mapped_column(Boolean)
    icao_code: Mapped[str | None] = mapped_column(String(4))
    gps_code: Mapped[str | None] = mapped_column(String(16))
    iata_code: Mapped[str | None] = mapped_column(String(3))
    local_code: Mapped[str | None] = mapped_column(String(16))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False)
