"""``cost_component``: one priced (or explicitly unavailable) cost component."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aircraft_cost_model.models.base import Base
from aircraft_cost_model.models.types import DecimalText
from aircraft_cost_model.models.variable_cost import VariableCostEstimate


class CostComponent(Base):
    """Fuel, navigation, landing or ground handling result.

    ``amount`` is NULL whenever the component was not calculated; a zero amount
    is stored only when a documented tariff rule yields zero.
    """

    __tablename__ = "cost_component"
    __table_args__ = (
        UniqueConstraint("variable_cost_estimate_id", "component_name", name="uq_cost_component_name"),
    )

    cost_component_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variable_cost_estimate_id: Mapped[int] = mapped_column(
        ForeignKey("variable_cost_estimate.variable_cost_estimate_id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_name: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    partial_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.source_id"))
    source_reference: Mapped[str | None] = mapped_column(Text)
    pricing_observation_date: Mapped[date | None] = mapped_column(Date)
    calculation_method: Mapped[str | None] = mapped_column(Text)
    breakdown_json: Mapped[str] = mapped_column(Text, nullable=False)
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False)

    variable_cost_estimate: Mapped[VariableCostEstimate] = relationship(back_populates="components")
