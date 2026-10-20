"""``fuel_price``: public fuel-price benchmark observations (Part 3)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aircraft_cost_model.models.base import Base, TimestampMixin
from aircraft_cost_model.models.types import DecimalText


class FuelPrice(TimestampMixin, Base):
    """One observation of a published fuel-price series (e.g. EIA US Gulf Coast jet fuel spot, USD/gal).

    ``observation_period`` states what the value represents (``daily`` = one
    trading day's spot assessment). A benchmark, not an airline contract or
    into-plane price.
    """

    __tablename__ = "fuel_price"
    __table_args__ = (
        UniqueConstraint("series_identifier", "observation_period", "observation_date", name="uq_fuel_price_obs"),
        Index("ix_fuel_price_series_date", "series_identifier", "observation_date"),
    )

    fuel_price_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False)
    series_identifier: Mapped[str] = mapped_column(String(64), nullable=False)
    market_location: Mapped[str] = mapped_column(String(100), nullable=False)
    product: Mapped[str] = mapped_column(String(100), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    observation_period: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_unit: Mapped[str] = mapped_column(String(30), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
