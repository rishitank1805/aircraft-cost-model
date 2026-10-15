"""``airport_tariff``: reviewed airport tariff parameters by validity period (Part 3)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aircraft_cost_model.models.base import Base, TimestampMixin


class AirportTariff(TimestampMixin, Base):
    """One tariff (e.g. FRA landing and take-off charges) valid over a date range.

    ``calculation_method`` names the rule implementation in
    :mod:`aircraft_cost_model.costs.landing_cost` / ``handling_cost``;
    ``parameters_json`` holds the reviewed rates and bands it needs (Decimal
    values encoded as strings). Superseded versions are retained.
    """

    __tablename__ = "airport_tariff"
    __table_args__ = (
        UniqueConstraint("airport_id", "tariff_type", "valid_from", name="uq_airport_tariff_version"),
    )

    airport_tariff_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    airport_id: Mapped[int] = mapped_column(ForeignKey("airport.airport_id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False)
    tariff_type: Mapped[str] = mapped_column(String(40), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    calculation_method: Mapped[str] = mapped_column(String(80), nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False)
