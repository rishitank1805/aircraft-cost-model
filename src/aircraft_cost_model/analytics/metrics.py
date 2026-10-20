"""Unit operating-cost metrics.

    cost per block hour      = cost amount / block hours            (Part 2 block time)
    cost per NM              = cost amount / distance (NM)          (explicit distance basis)
    cost per flight cycle    = cost amount / flight cycles          (1 for one completed leg)
    RTNM                     = revenue cargo payload (t) x revenue distance (NM)
    cost per RTNM            = cost amount / RTNM
    ATNM                     = available payload capacity (t) x distance (NM)
    load factor              = revenue payload / available payload

Rules:

- Every metric is computed twice per cost basis: from the **calculated
  subtotal** (labelled *partial* when components are missing) and from the
  **complete total** (unavailable unless every applicable component is
  calculated). A partial subtotal divided by a denominator is a partial
  unit cost.
- Distance basis is explicit: ``great_circle`` and ``modelled_route`` come
  from the Part 2 estimate; ``actual_flown`` must be supplied with a
  reference. Bases are never mixed.
- Revenue cargo payload is never taken from the Part 2 modelled payload. It
  must be supplied explicitly; for a passenger flight it is accepted only as
  an explicitly labelled hypothetical cargo scenario. Missing payload makes
  RTNM unavailable; zero payload makes cost/RTNM undefined (not 0, not infinite).
- Values are exact ``Decimal`` quotients; no intermediate rounding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from aircraft_cost_model.analytics.cases import AnalyticsInputError, CostCase, FlightFacts
from aircraft_cost_model.costs.currency import plain
from aircraft_cost_model.fullcost.aggregate import TAXONOMY, Category, FullCostSummary, SourceQuality, component_source_quality

PAYLOAD_SOURCE_TYPES = ("observed_public_data", "user_assumption", "illustrative_assumption")


class DistanceBasis(str, Enum):
    GREAT_CIRCLE = "great_circle"
    MODELLED_ROUTE = "modelled_route"
    ACTUAL_FLOWN = "actual_flown"


@dataclass(frozen=True)
class DistanceInput:
    basis: DistanceBasis
    actual_nm: Decimal | None = None
    reference: str | None = None

    def resolve(self, facts: FlightFacts) -> tuple[Decimal | None, str]:
        if self.basis == DistanceBasis.GREAT_CIRCLE:
            if self.actual_nm is not None:
                raise AnalyticsInputError("an actual distance may only be given with distance basis actual_flown")
            return facts.great_circle_nm, "great-circle distance from the Part 2 flight estimate (haversine)"
        if self.basis == DistanceBasis.MODELLED_ROUTE:
            if self.actual_nm is not None:
                raise AnalyticsInputError("an actual distance may only be given with distance basis actual_flown")
            return facts.modelled_route_nm, f"modelled route distance from Part 2 ({facts.route_distance_method})"
        if self.actual_nm is None or not self.reference:
            raise AnalyticsInputError("distance basis actual_flown requires an externally supplied distance and reference")
        return self.actual_nm, f"actual flown distance supplied externally ({self.reference})"


@dataclass(frozen=True)
class PayloadInput:
    """Explicit revenue cargo payload (and optional available capacity), in metric tonnes."""

    revenue_tonnes: Decimal | None
    source_type: str = "user_assumption"
    reference: str | None = None
    hypothetical_cargo: bool = False
    available_tonnes: Decimal | None = None
    available_reference: str | None = None

    def describe(self) -> str:
        if self.revenue_tonnes is None:
            return "revenue cargo payload not provided"
        label = "HYPOTHETICAL cargo scenario: " if self.hypothetical_cargo else ""
        return (f"{label}revenue cargo payload {plain(self.revenue_tonnes)} t ({self.source_type}"
                f"{'; ' + self.reference if self.reference else ''})")


NO_PAYLOAD = PayloadInput(None)


@dataclass
class TrafficMeasures:
    distance_nm: Decimal | None
    distance_basis: str
    distance_description: str
    revenue_tonnes: Decimal | None
    rtnm: Decimal | None
    available_tonnes: Decimal | None
    atnm: Decimal | None
    load_factor: Decimal | None
    payload_basis: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: (plain(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


COST_BASES: dict[str, tuple[Category, ...]] = {
    "direct_variable": (Category.DIRECT_VARIABLE,),
    "direct_fixed": (Category.DIRECT_FIXED,),
    "indirect": (Category.INDIRECT,),
    "coc": (Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT),
    "toc": (Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT, Category.NONCASH),
    "total_costs": tuple(Category),
}
COST_BASIS_LABELS = {"direct_variable": "direct variable cost", "direct_fixed": "direct fixed cost",
                     "indirect": "indirect cost", "coc": "COC", "toc": "TOC", "total_costs": "total costs"}
DENOMINATOR_LABELS = {"block_hour": "block hour", "nautical_mile": "NM", "flight_cycle": "flight cycle",
                      "revenue_tonne_nm": "RTNM", "available_tonne_nm": "ATNM"}


@dataclass
class CostAmount:
    """A cost numerator: calculated subtotal and complete total for one cost basis."""

    cost_basis: str
    calculated_subtotal: Decimal | None
    complete_total: Decimal | None
    included: tuple[str, ...]
    missing: tuple[str, ...]
    not_applicable: tuple[str, ...]
    source_quality: str
    failed: bool


def quality_of(summary: FullCostSummary, names: tuple[str, ...]) -> str:
    qualities = sorted({component_source_quality(summary.components[n]).value for n in names} - {SourceQuality.NONE.value})
    if not qualities:
        return SourceQuality.NONE.value
    return qualities[0] if len(qualities) == 1 else "mixed: " + ", ".join(qualities)


def cost_amount(summary: FullCostSummary, cost_basis: str) -> CostAmount:
    categories = COST_BASES[cost_basis]
    names = tuple(n for c in categories for n in TAXONOMY[c])
    subs = [summary.category(c) for c in categories]
    subtotals = [s.calculated_subtotal for s in subs if s.calculated_subtotal is not None]
    missing = tuple(m for s in subs for m in s.missing_components)
    calculated = sum(subtotals, Decimal(0)) if subtotals else None
    complete = sum((s.complete_amount for s in subs), Decimal(0)) if not missing else None
    included = tuple(n for n in names if summary.components[n].is_calculated)
    failed = any(summary.components[n].status.value == "failed_validation" for n in names)
    return CostAmount(cost_basis, calculated, complete, included, missing,
                      tuple(n for s in subs for n in s.not_applicable_components), quality_of(summary, included), failed)


def fx_basis(summary: FullCostSummary, names: tuple[str, ...]) -> str:
    conversions = sorted({f"ECB {step['series_key']} rate {step['rate']} ({step['observation_date']})"
                          for n in names for step in summary.components[n].breakdown
                          if isinstance(step, dict) and step.get("series_key")})
    return "; ".join(conversions) if conversions else "no currency conversion in the included components"


@dataclass
class UnitMetric:
    metric_name: str
    label: str
    cost_basis: str
    cost_measure: str  # calculated_subtotal | complete_total
    numerator_amount: Decimal | None
    currency: str
    denominator_value: Decimal | None
    denominator_unit: str
    denominator_basis: str
    metric_value: Decimal | None
    metric_unit: str
    metric_status: str  # calculated | unavailable | undefined
    coverage_status: str  # complete | partial | missing_required_input | unsupported | calculation_error
    operational_validity: str
    source_quality: str
    pricing_date: str
    fx_basis: str
    payload_basis: str | None
    components_included: tuple[str, ...]
    components_missing: tuple[str, ...]
    calculation_method: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = {}
        for k, v in self.__dict__.items():
            out[k] = plain(v) if isinstance(v, Decimal) else list(v) if isinstance(v, tuple) else v
        return out


@dataclass
class UnitMetricsResult:
    case_label: str
    facts: FlightFacts | None
    traffic: TrafficMeasures | None
    metrics: list[UnitMetric]
    cost_coverage: str
    operational_validity: str | None
    source_quality: str
    warnings: list[str] = field(default_factory=list)

    def metric(self, name: str, measure: str = "calculated_subtotal") -> UnitMetric:
        return next(m for m in self.metrics if m.metric_name == name and m.cost_measure == measure)

    def to_dict(self) -> dict[str, Any]:
        return {"case": self.case_label, "flight": self.facts.to_dict() if self.facts else None,
                "traffic": self.traffic.to_dict() if self.traffic else None, "cost_coverage": self.cost_coverage,
                "operational_validity": self.operational_validity, "source_quality": self.source_quality,
                "warnings": self.warnings, "metrics": [m.to_dict() for m in self.metrics]}


def traffic_measures(case: CostCase, distance: DistanceInput, payload: PayloadInput) -> TrafficMeasures:
    facts = case.facts
    distance_nm, description = distance.resolve(facts)
    warnings: list[str] = []
    if distance_nm is not None and distance_nm < 0:
        raise AnalyticsInputError("distance must not be negative")
    revenue = payload.revenue_tonnes
    if revenue is not None:
        if payload.source_type not in PAYLOAD_SOURCE_TYPES:
            raise AnalyticsInputError(f"payload source_type must be one of {PAYLOAD_SOURCE_TYPES}")
        if revenue < 0:
            raise AnalyticsInputError("revenue cargo payload must not be negative")
        if case.flight_type != "cargo" and not payload.hypothetical_cargo:
            raise AnalyticsInputError(
                f"the scenario flight type is {case.flight_type!r}: revenue cargo payload is accepted only as an "
                "explicitly labelled hypothetical cargo scenario (hypothetical_cargo=True)")
        modelled_t = facts.modelled_payload_kg / 1000
        if revenue > modelled_t:
            raise AnalyticsInputError(
                f"revenue cargo payload {plain(revenue)} t exceeds the {plain(modelled_t)} t payload used by the Part 2 "
                "performance estimate; rerun Part 2 with that payload")
        if payload.hypothetical_cargo:
            warnings.append("HYPOTHETICAL cargo scenario on a passenger aircraft estimate: it does not validate "
                            "cargo-aircraft performance, capacity or economics")
    else:
        warnings.append("revenue cargo payload not provided: RTNM and cost per RTNM are unavailable (the Part 2 "
                        "modelled payload is a mass assumption, not revenue cargo)")
    available = payload.available_tonnes
    if available is not None:
        if available <= 0:
            raise AnalyticsInputError("available payload capacity must be positive")
        if revenue is not None and revenue > available:
            raise AnalyticsInputError("revenue cargo payload exceeds the stated available payload capacity")
    rtnm = revenue * distance_nm if revenue is not None and distance_nm is not None else None
    atnm = available * distance_nm if available is not None and distance_nm is not None else None
    load_factor = revenue / available if revenue is not None and available is not None else None
    return TrafficMeasures(distance_nm, distance.basis.value, description, revenue, rtnm, available, atnm, load_factor,
                           payload.describe(), warnings)


def _metric(case: CostCase, amount: CostAmount, measure: str, denominator: Decimal | None, unit: str, basis: str,
            fx: str, payload_basis: str | None, missing_reason: str | None) -> UnitMetric:
    summary = case.summary
    numerator = amount.calculated_subtotal if measure == "calculated_subtotal" else amount.complete_total
    warnings: list[str] = []
    if amount.failed:
        coverage = "calculation_error"
    elif amount.complete_total is not None:
        coverage = "complete"
    elif amount.calculated_subtotal is None and not amount.missing:
        coverage = "complete"  # every component not applicable
    else:
        coverage = "partial" if amount.calculated_subtotal is not None else "missing_required_input"
    status, value = "calculated", None
    if numerator is None:
        status = "unavailable"
        if measure == "complete_total" and amount.missing:
            warnings.append(f"complete {COST_BASIS_LABELS[amount.cost_basis]} unavailable: missing "
                            f"{', '.join(amount.missing)}")
    elif denominator is None:
        status = "unavailable"
        if coverage != "calculation_error":
            coverage = "missing_required_input"
        warnings.append(missing_reason or f"{unit} denominator unavailable")
    elif denominator == 0:
        status = "undefined"
        warnings.append(f"{DENOMINATOR_LABELS[unit]} is zero: metric undefined (not zero, not infinite)")
    else:
        value = numerator / denominator
    partial_numerator = (measure == "calculated_subtotal" and amount.complete_total is None
                         and amount.calculated_subtotal is not None)
    qualifier = "Complete" if measure == "complete_total" else ("Partial" if partial_numerator else "Calculated")
    label = f"{qualifier} {COST_BASIS_LABELS[amount.cost_basis]} per {DENOMINATOR_LABELS[unit]}"
    if partial_numerator:
        warnings.append(f"partial: numerator excludes unavailable components ({', '.join(amount.missing)})")
    return UnitMetric(
        metric_name=f"{amount.cost_basis}_per_{unit}", label=label, cost_basis=amount.cost_basis, cost_measure=measure,
        numerator_amount=numerator, currency=summary.reporting_currency, denominator_value=denominator,
        denominator_unit=unit, denominator_basis=basis, metric_value=value,
        metric_unit=f"{summary.reporting_currency}/{unit}", metric_status=status, coverage_status=coverage,
        operational_validity=summary.operational_validity, source_quality=amount.source_quality,
        pricing_date=case.pricing_date.isoformat(), fx_basis=fx, payload_basis=payload_basis,
        components_included=amount.included, components_missing=amount.missing,
        calculation_method=f"{measure.replace('_', ' ')} / {DENOMINATOR_LABELS[unit]} (exact Decimal quotient)",
        warnings=warnings,
    )


def unit_metrics(case: CostCase, distance: DistanceInput, payload: PayloadInput = NO_PAYLOAD) -> UnitMetricsResult:
    """All unit metrics for one case. Unsupported or missing cases return no metrics with a reason."""
    if not case.is_costed:
        return UnitMetricsResult(case.label, None, None, [], "unsupported" if case.origin == "unsupported"
                                 else "missing_required_input", None, SourceQuality.NONE.value, list(case.warnings))
    facts, summary = case.facts, case.summary
    if facts.block_hours <= 0:
        raise AnalyticsInputError(f"flight_estimate {facts.flight_estimate_id}: block hours must be positive")
    traffic = traffic_measures(case, distance, payload)
    denominators = [
        ("block_hour", facts.block_hours, "Part 2 block time (off-block to on-block)", None),
        ("nautical_mile", traffic.distance_nm, f"{traffic.distance_basis}: {traffic.distance_description}", None),
        ("flight_cycle", facts.flight_cycles, "one completed leg (single Part 2 flight estimate) = 1 cycle", None),
        ("revenue_tonne_nm", traffic.rtnm, f"{traffic.payload_basis} x {traffic.distance_basis} distance",
         "RTNM unavailable: revenue cargo payload not provided"),
        ("available_tonne_nm", traffic.atnm, f"available capacity x {traffic.distance_basis} distance",
         "ATNM unavailable: available payload capacity not provided (never derived from MZFW - OEW)"),
    ]
    metrics: list[UnitMetric] = []
    for cost_basis in COST_BASES:
        amount = cost_amount(summary, cost_basis)
        fx = fx_basis(summary, amount.included)
        for unit, value, basis, reason in denominators:
            payload_basis = traffic.payload_basis if unit in ("revenue_tonne_nm", "available_tonne_nm") else None
            for measure in ("calculated_subtotal", "complete_total"):
                metrics.append(_metric(case, amount, measure, value, unit, basis, fx, payload_basis, reason))
    coverage = {"complete": "complete", "incomplete": "partial", "failed_validation": "calculation_error"}[
        summary.cost_coverage_status]
    return UnitMetricsResult(case.label, facts, traffic, metrics, coverage, summary.operational_validity,
                             summary.source_quality_summary, list(case.warnings) + traffic.warnings)
