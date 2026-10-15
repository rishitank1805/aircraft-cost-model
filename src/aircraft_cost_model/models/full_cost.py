"""Part 4 tables: cost scenarios, their assumptions, full-cost estimates and components."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aircraft_cost_model.models.base import Base, utc_now
from aircraft_cost_model.models.types import DecimalText


class CostScenario(Base):
    """A scenario file's content, stored once per content hash (exact JSON kept for reproducibility)."""

    __tablename__ = "cost_scenario"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_cost_scenario_content_hash"),)

    scenario_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scenario_version: Mapped[str] = mapped_column(String(40), nullable=False)
    ownership_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    flight_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    pricing_date: Mapped[date | None] = mapped_column(Date)
    source_quality_summary: Mapped[str] = mapped_column(String(200), nullable=False)
    source_path: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    assumptions: Mapped[list["CostAssumption"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")


class CostAssumption(Base):
    """One typed scenario input with unit, currency, effective period and source classification."""

    __tablename__ = "cost_assumption"
    __table_args__ = (UniqueConstraint("scenario_id", "parameter_name", name="uq_cost_assumption_parameter"),)

    assumption_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("cost_scenario.scenario_id", ondelete="CASCADE"),
                                             nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(60), nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(200), nullable=False)
    value_decimal: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    reference_period: Mapped[str | None] = mapped_column(String(100))
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    scenario: Mapped[CostScenario] = relationship(back_populates="assumptions")


class FullCostEstimate(Base):
    """Full operating cost estimate: Part 3 components (linked, not copied as new results) + Part 4 components.

    ``*_subtotal`` columns add calculated components only. ``complete_*`` columns
    are set only when every applicable component below them is calculated.
    Cost coverage, operational validity and source quality are separate columns.
    """

    __tablename__ = "full_cost_estimate"

    full_cost_estimate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flight_estimate_id: Mapped[int] = mapped_column(ForeignKey("flight_estimate.flight_estimate_id"), nullable=False,
                                                    index=True)
    variable_cost_estimate_id: Mapped[int] = mapped_column(
        ForeignKey("variable_cost_estimate.variable_cost_estimate_id"), nullable=False, index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("cost_scenario.scenario_id"), nullable=False, index=True)
    pricing_date: Mapped[date] = mapped_column(Date, nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    ownership_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    direct_variable_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    direct_fixed_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    indirect_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    noncash_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    financing_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    cash_operating_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    total_operating_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    total_cost_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    complete_coc: Mapped[Decimal | None] = mapped_column(DecimalText)
    complete_toc: Mapped[Decimal | None] = mapped_column(DecimalText)
    complete_total_costs: Mapped[Decimal | None] = mapped_column(DecimalText)
    cost_coverage_status: Mapped[str] = mapped_column(String(30), nullable=False)
    operational_validity_status: Mapped[str] = mapped_column(String(50), nullable=False)
    source_quality_summary: Mapped[str] = mapped_column(String(200), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    components: Mapped[list["FullCostComponent"]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan", order_by="FullCostComponent.full_cost_component_id")


class FullCostComponent(Base):
    """One component of a full-cost estimate (NULL amount whenever not calculated)."""

    __tablename__ = "full_cost_component"
    __table_args__ = (UniqueConstraint("full_cost_estimate_id", "component_name", name="uq_full_cost_component_name"),)

    full_cost_component_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_cost_estimate_id: Mapped[int] = mapped_column(
        ForeignKey("full_cost_estimate.full_cost_estimate_id", ondelete="CASCADE"), nullable=False, index=True)
    component_name: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_quality: Mapped[str] = mapped_column(String(40), nullable=False)
    origin: Mapped[str] = mapped_column(String(40), nullable=False)
    part3_cost_component_id: Mapped[int | None] = mapped_column(ForeignKey("cost_component.cost_component_id"))
    source_reference: Mapped[str | None] = mapped_column(Text)
    calculation_method: Mapped[str | None] = mapped_column(Text)
    breakdown_json: Mapped[str] = mapped_column(Text, nullable=False)
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False)

    estimate: Mapped[FullCostEstimate] = relationship(back_populates="components")
