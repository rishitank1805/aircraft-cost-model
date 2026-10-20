"""``navigation_rate``: en-route and terminal navigation unit rates by charging zone (Part 3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from aircraft_cost_model.models.base import Base, TimestampMixin
from aircraft_cost_model.models.types import DecimalText


class NavigationRate(TimestampMixin, Base):
    """Unit rate of charge for one charging zone over a validity period.

    ``charge_type='en_route'``: ``unit_rate`` is the EUROCONTROL global unit rate
    (national + administrative) used in r_i = t_i x N_i (CoA Arts. 3 and 7).
    ``charge_type='terminal'``: terminal unit rate t in R = t x N for flights
    ``charged_movement`` (e.g. departing) from the zone's aerodromes.
    ``service_unit_formula`` names the weight formula. Only rows with
    ``verification_status='verified_against_source'`` are priced.
    Superseded versions are retained; selection is by ``valid_from``/``valid_to``.
    """

    __tablename__ = "navigation_rate"
    __table_args__ = (UniqueConstraint("charging_zone", "valid_from", name="uq_navigation_rate_zone_from"),)

    navigation_rate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False)
    charging_zone: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    charging_zone_name: Mapped[str] = mapped_column(String(100), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    unit_rate: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    national_unit_rate: Mapped[Decimal | None] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False)
    charge_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'en_route'"))
    service_unit_formula: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'sqrt_mtow_over_50'")
    )
    charged_movement: Mapped[str | None] = mapped_column(String(20))


class NavigationZoneAerodrome(TimestampMixin, Base):
    """Membership of an aerodrome (ICAO) in a terminal charging zone over a validity period."""

    __tablename__ = "navigation_zone_aerodrome"
    __table_args__ = (
        UniqueConstraint("charging_zone", "aerodrome_icao", "valid_from", name="uq_navigation_zone_aerodrome"),
    )

    navigation_zone_aerodrome_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False)
    charging_zone: Mapped[str] = mapped_column(String(40), nullable=False)
    aerodrome_icao: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
