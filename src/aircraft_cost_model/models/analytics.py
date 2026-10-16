"""Part 5 tables: analytics runs and their results, public benchmarks, price indices and adjustments.

Money, rates and index values use ``DecimalText``. An analytics run is
immutable and identified by its input hash (saving the same inputs again
returns the existing run). Benchmark observations and index observations are
kept per source snapshot, so a revised download never overwrites history.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aircraft_cost_model.models.base import Base, utc_now
from aircraft_cost_model.models.types import DecimalText


class AnalyticsRun(Base):
    """One reproducible analytics run (unit metrics, comparison, sensitivity, benchmark, validation)."""

    __tablename__ = "analytics_run"
    __table_args__ = (UniqueConstraint("input_hash", name="uq_analytics_run_input_hash"),)

    analytics_run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    flight_estimate_id: Mapped[int | None] = mapped_column(ForeignKey("flight_estimate.flight_estimate_id"), index=True)
    variable_cost_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("variable_cost_estimate.variable_cost_estimate_id"))
    full_cost_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("full_cost_estimate.full_cost_estimate_id"), index=True)
    base_scenario_id: Mapped[int | None] = mapped_column(ForeignKey("cost_scenario.scenario_id"))
    pricing_date: Mapped[date | None] = mapped_column(Date)
    reporting_currency: Mapped[str | None] = mapped_column(String(3))
    distance_basis: Mapped[str | None] = mapped_column(String(30))
    payload_basis: Mapped[str | None] = mapped_column(Text)
    coverage_status: Mapped[str] = mapped_column(String(30), nullable=False)
    operational_validity: Mapped[str | None] = mapped_column(String(50))
    source_quality_summary: Mapped[str] = mapped_column(String(200), nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    metrics: Mapped[list["UnitCostMetric"]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                                           order_by="UnitCostMetric.metric_id")
    scenario_results: Mapped[list["ScenarioResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ScenarioResult.scenario_result_id")
    benchmark_comparisons: Mapped[list["BenchmarkComparison"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="BenchmarkComparison.comparison_id")


class UnitCostMetric(Base):
    """One unit metric (numerator, denominator and value kept separately; NULL when unavailable/undefined)."""

    __tablename__ = "unit_cost_metric"

    metric_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analytics_run_id: Mapped[int] = mapped_column(ForeignKey("analytics_run.analytics_run_id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    case_label: Mapped[str] = mapped_column(String(200), nullable=False)
    flight_estimate_id: Mapped[int | None] = mapped_column(ForeignKey("flight_estimate.flight_estimate_id"))
    metric_name: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    cost_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    cost_measure: Mapped[str] = mapped_column(String(30), nullable=False)
    numerator_amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    denominator_value: Mapped[Decimal | None] = mapped_column(DecimalText)
    denominator_unit: Mapped[str] = mapped_column(String(30), nullable=False)
    denominator_basis: Mapped[str] = mapped_column(Text, nullable=False)
    metric_value: Mapped[Decimal | None] = mapped_column(DecimalText)
    metric_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    metric_status: Mapped[str] = mapped_column(String(20), nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(30), nullable=False)
    operational_validity: Mapped[str] = mapped_column(String(50), nullable=False)
    source_quality: Mapped[str] = mapped_column(String(200), nullable=False)
    pricing_date: Mapped[date] = mapped_column(Date, nullable=False)
    fx_basis: Mapped[str] = mapped_column(Text, nullable=False)
    payload_basis: Mapped[str | None] = mapped_column(Text)
    calculation_method: Mapped[str] = mapped_column(Text, nullable=False)
    components_json: Mapped[str] = mapped_column(Text, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped[AnalyticsRun] = relationship(back_populates="metrics")


class ScenarioResult(Base):
    """One recalculated scenario variation (or sensitivity level / grid cell)."""

    __tablename__ = "scenario_result"

    scenario_result_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analytics_run_id: Mapped[int] = mapped_column(ForeignKey("analytics_run.analytics_run_id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    variations_json: Mapped[str] = mapped_column(Text, nullable=False)
    modified_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    variant_scenario_id: Mapped[int | None] = mapped_column(ForeignKey("cost_scenario.scenario_id"))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    fuel_cost: Mapped[Decimal | None] = mapped_column(DecimalText)
    direct_variable_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    cash_operating_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    total_operating_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    total_cost_subtotal: Mapped[Decimal | None] = mapped_column(DecimalText)
    complete_coc: Mapped[Decimal | None] = mapped_column(DecimalText)
    complete_toc: Mapped[Decimal | None] = mapped_column(DecimalText)
    complete_total_costs: Mapped[Decimal | None] = mapped_column(DecimalText)
    components_json: Mapped[str] = mapped_column(Text, nullable=False)
    deltas_json: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(30), nullable=False)
    operational_validity: Mapped[str | None] = mapped_column(String(50))
    source_quality: Mapped[str | None] = mapped_column(String(200))
    calculated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped[AnalyticsRun] = relationship(back_populates="scenario_results")


class BenchmarkObservation(Base):
    """One public benchmark amount for one cost category with its compatible denominators.

    BTS rows are one carrier x aircraft type x configuration x reporting
    region x quarter (P-5.2 expenses joined to T2 traffic). FAA rows are
    published per-block-hour rates (``block_hours = 1``). Amounts are in the
    source currency (USD), never converted in storage.
    """

    __tablename__ = "benchmark_observation"
    __table_args__ = (UniqueConstraint(
        "source_id", "benchmark_source", "carrier_code", "aircraft_type_code", "aircraft_config", "region",
        "period_label", "cost_category", name="uq_benchmark_observation_key"),)

    benchmark_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False, index=True)
    traffic_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.source_id"))
    benchmark_source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_table: Mapped[str] = mapped_column(String(100), nullable=False)
    carrier_code: Mapped[str] = mapped_column(String(10), nullable=False)
    carrier_name: Mapped[str | None] = mapped_column(String(200))
    carrier_group: Mapped[str | None] = mapped_column(String(10))
    operation_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    aircraft_type_code: Mapped[str] = mapped_column(String(10), nullable=False)
    aircraft_type_description: Mapped[str | None] = mapped_column(String(200))
    aircraft_config: Mapped[str] = mapped_column(String(5), nullable=False)
    region: Mapped[str] = mapped_column(String(5), nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    cost_category: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    block_hours: Mapped[Decimal | None] = mapped_column(DecimalText)
    airborne_hours: Mapped[Decimal | None] = mapped_column(DecimalText)
    departures: Mapped[Decimal | None] = mapped_column(DecimalText)
    revenue_tonne_nm: Mapped[Decimal | None] = mapped_column(DecimalText)
    available_tonne_nm: Mapped[Decimal | None] = mapped_column(DecimalText)
    aircraft_miles_nm: Mapped[Decimal | None] = mapped_column(DecimalText)
    source_fields: Mapped[str] = mapped_column(Text, nullable=False)
    methodology: Mapped[str] = mapped_column(Text, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(30), nullable=False)
    quality_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class PriceIndexObservation(Base):
    """One published index value (e.g. BLS ECI or PPI) as retrieved in one source snapshot."""

    __tablename__ = "price_index_observation"
    __table_args__ = (UniqueConstraint("source_id", "series_id", "period", name="uq_price_index_observation"),)

    index_observation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False, index=True)
    series_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    series_title: Mapped[str | None] = mapped_column(String(300))
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    preliminary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    footnotes: Mapped[str | None] = mapped_column(Text)


class BenchmarkAdjustment(Base):
    """An index-adjusted copy of a benchmark value; the original observation is never modified."""

    __tablename__ = "benchmark_adjustment"
    __table_args__ = (UniqueConstraint("benchmark_id", "index_series_id", "target_date", "index_source_id",
                                       name="uq_benchmark_adjustment"),)

    adjustment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benchmark_id: Mapped[int] = mapped_column(ForeignKey("benchmark_observation.benchmark_id"), nullable=False,
                                              index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # adjusted | unavailable
    original_amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    original_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    original_period: Mapped[str] = mapped_column(String(40), nullable=False)
    index_series_id: Mapped[str] = mapped_column(String(40), nullable=False)
    index_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.source_id"))
    base_period: Mapped[str | None] = mapped_column(String(60))
    base_index: Mapped[Decimal | None] = mapped_column(DecimalText)
    target_period: Mapped[str | None] = mapped_column(String(60))
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_index: Mapped[Decimal | None] = mapped_column(DecimalText)
    factor: Mapped[Decimal | None] = mapped_column(DecimalText)
    adjusted_amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    methodology: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class BenchmarkComparison(Base):
    """A model metric against a benchmark metric with an explicit comparability verdict."""

    __tablename__ = "benchmark_comparison"

    comparison_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analytics_run_id: Mapped[int] = mapped_column(ForeignKey("analytics_run.analytics_run_id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    model_metric: Mapped[str] = mapped_column(String(80), nullable=False)
    model_value: Mapped[Decimal | None] = mapped_column(DecimalText)
    model_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    benchmark_metric: Mapped[str] = mapped_column(String(80), nullable=False)
    benchmark_value: Mapped[Decimal | None] = mapped_column(DecimalText)
    benchmark_value_converted: Mapped[Decimal | None] = mapped_column(DecimalText)
    benchmark_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    benchmark_selection_json: Mapped[str] = mapped_column(Text, nullable=False)
    comparability: Mapped[str] = mapped_column(String(30), nullable=False)
    checks_json: Mapped[str] = mapped_column(Text, nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    absolute_difference: Mapped[Decimal | None] = mapped_column(DecimalText)
    percentage_difference: Mapped[Decimal | None] = mapped_column(DecimalText)
    fx_basis: Mapped[str | None] = mapped_column(Text)

    run: Mapped[AnalyticsRun] = relationship(back_populates="benchmark_comparisons")
