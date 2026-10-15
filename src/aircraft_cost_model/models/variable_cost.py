"""``variable_cost_estimate``: one priced set of variable cost components for a flight estimate."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aircraft_cost_model.models.base import Base, utc_now
from aircraft_cost_model.models.types import DecimalText


class VariableCostEstimate(Base):
    """Priced variable cost components for one flight estimate and pricing date.

    ``calculated_subtotal`` is the sum of calculated components only (never a
    complete total). ``complete_variable_cost`` is set **only** when every
    applicable component was calculated with full scope; otherwise NULL.
    """

    __tablename__ = "variable_cost_estimate"

    variable_cost_estimate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flight_estimate_id: Mapped[int] = mapped_column(
        ForeignKey("flight_estimate.flight_estimate_id"), nullable=False, index=True
    )
    pricing_date: Mapped[date] = mapped_column(Date, nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    calculated_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    complete_variable_cost: Mapped[Decimal | None] = mapped_column(DecimalText)
    coverage_status: Mapped[str] = mapped_column(String(30), nullable=False)
    components_calculated: Mapped[int] = mapped_column(Integer, nullable=False)
    components_applicable: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    components: Mapped[list["CostComponent"]] = relationship(  # noqa: F821
        back_populates="variable_cost_estimate", cascade="all, delete-orphan", order_by="CostComponent.cost_component_id"
    )
