"""Typed component statuses, component results and cost aggregation with coverage.

Rules enforced here:
- A component that was not calculated has ``amount = None`` (never 0.00).
- A calculated component must have an amount; zero is allowed only when a
  documented tariff rule yields zero (``zero_by_tariff_rule=True``).
- The subtotal is the sum of calculated components only and is never called a
  total. ``complete_variable_cost`` exists only when every applicable component
  is calculated and none is flagged ``partial_scope``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from aircraft_cost_model.costs.exceptions import CurrencyMismatchError


class ComponentName(str, Enum):
    FUEL = "fuel"
    NAVIGATION = "navigation"  # EUROCONTROL en-route charges
    TERMINAL_NAVIGATION = "terminal_navigation"
    LANDING = "landing"
    GROUND_HANDLING = "ground_handling"


REQUIRED_COMPONENTS = tuple(ComponentName)


class ComponentStatus(str, Enum):
    CALCULATED_PUBLIC_TARIFF = "calculated_public_tariff"
    CALCULATED_BENCHMARK = "calculated_benchmark"
    CALCULATED_ASSUMPTION = "calculated_assumption"
    MISSING_REQUIRED_INPUT = "missing_required_input"
    UNAVAILABLE_PUBLIC_TARIFF = "unavailable_public_tariff"
    UNAVAILABLE_ROUTE_GEOMETRY = "unavailable_route_geometry"
    UNAVAILABLE_PRICE = "unavailable_price"
    UNSUPPORTED_AIRCRAFT = "unsupported_aircraft"
    UNSUPPORTED_TARIFF_RULE = "unsupported_tariff_rule"
    NOT_APPLICABLE = "not_applicable"
    CALCULATION_ERROR = "calculation_error"

    @property
    def is_calculated(self) -> bool:
        return self in CALCULATED_STATUSES


CALCULATED_STATUSES = frozenset({
    ComponentStatus.CALCULATED_PUBLIC_TARIFF,
    ComponentStatus.CALCULATED_BENCHMARK,
    ComponentStatus.CALCULATED_ASSUMPTION,
})

# When sub-results (e.g. origin and destination airport) are combined, the
# component reports the first non-calculated status in this order.
STATUS_PRECEDENCE = (
    ComponentStatus.CALCULATION_ERROR,
    ComponentStatus.UNSUPPORTED_AIRCRAFT,
    ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF,
    ComponentStatus.UNAVAILABLE_ROUTE_GEOMETRY,
    ComponentStatus.UNSUPPORTED_TARIFF_RULE,
    ComponentStatus.MISSING_REQUIRED_INPUT,
    ComponentStatus.UNAVAILABLE_PRICE,
)


class SourceType(str, Enum):
    PUBLIC_TARIFF = "public_tariff"
    PUBLIC_MARKET_BENCHMARK = "public_market_benchmark"
    USER_ASSUMPTION = "user_assumption"
    NONE = "none"


@dataclass(frozen=True)
class Assumption:
    name: str
    value: str
    unit: str | None = None
    source_type: str = "user_input"
    reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "unit": self.unit, "source_type": self.source_type,
                "reference": self.reference}


@dataclass
class ComponentResult:
    """Result of one cost component (or one airport's part of a component)."""

    component: str
    status: ComponentStatus
    currency: str
    pricing_date: date
    amount: Decimal | None = None
    source_type: SourceType = SourceType.NONE
    source_reference: str | None = None
    source_id: int | None = None
    observation_date: date | None = None
    calculation_method: str | None = None
    breakdown: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    partial_scope: bool = False
    zero_by_tariff_rule: bool = False

    def __post_init__(self) -> None:
        if self.amount is not None and not isinstance(self.amount, Decimal):
            raise TypeError("amount must be a Decimal")
        if self.status.is_calculated:
            if self.amount is None:
                raise ValueError(f"{self.component}: calculated status requires an amount")
            if self.amount == 0 and not self.zero_by_tariff_rule:
                raise ValueError(f"{self.component}: zero amount requires zero_by_tariff_rule=True")
        elif self.amount is not None:
            raise ValueError(f"{self.component}: status {self.status.value} must not carry an amount")

    @property
    def is_calculated(self) -> bool:
        return self.status.is_calculated

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "amount": None if self.amount is None else str(self.amount),
            "currency": self.currency,
            "pricing_date": self.pricing_date.isoformat(),
            "status": self.status.value,
            "source_type": self.source_type.value,
            "source_reference": self.source_reference,
            "observation_date": self.observation_date.isoformat() if self.observation_date else None,
            "calculation_method": self.calculation_method,
            "partial_scope": self.partial_scope,
            "missing_inputs": self.missing_inputs,
            "breakdown": self.breakdown,
            "assumptions": [a.to_dict() for a in self.assumptions],
            "warnings": self.warnings,
        }


def combine_parts(component: str, parts: list[ComponentResult], currency: str, pricing_date: date,
                  calculation_method: str) -> ComponentResult:
    """Combine per-airport parts into one component; any non-calculated part makes the component unavailable."""
    breakdown = [{"part": p.breakdown[0].get("part") if p.breakdown else None, **p.to_dict()} for p in parts]
    warnings = [w for p in parts for w in p.warnings]
    assumptions = [a for p in parts for a in p.assumptions]
    missing = [m for p in parts for m in p.missing_inputs]
    partial = any(p.partial_scope for p in parts)
    if all(p.is_calculated for p in parts):
        for p in parts:
            if p.currency != currency:
                raise CurrencyMismatchError(f"{component}: part in {p.currency}, expected {currency}")
        amount = sum((p.amount for p in parts), Decimal("0"))
        statuses = {p.status for p in parts}
        status = (ComponentStatus.CALCULATED_ASSUMPTION if ComponentStatus.CALCULATED_ASSUMPTION in statuses
                  else ComponentStatus.CALCULATED_BENCHMARK if ComponentStatus.CALCULATED_BENCHMARK in statuses
                  else ComponentStatus.CALCULATED_PUBLIC_TARIFF)
        source_types = {p.source_type for p in parts}
        source_type = SourceType.USER_ASSUMPTION if SourceType.USER_ASSUMPTION in source_types else next(iter(source_types))
        return ComponentResult(
            component, status, currency, pricing_date, amount, source_type,
            "; ".join(p.source_reference for p in parts if p.source_reference) or None,
            calculation_method=calculation_method, breakdown=breakdown, assumptions=assumptions,
            warnings=warnings, partial_scope=partial,
            zero_by_tariff_rule=amount == 0 and all(p.zero_by_tariff_rule or p.amount != 0 for p in parts),
        )
    status = next(s for s in STATUS_PRECEDENCE if any(p.status == s for p in parts))
    calculated = [p for p in parts if p.is_calculated]
    if calculated:
        warnings.append(
            f"{component}: {len(calculated)} of {len(parts)} parts calculated; the partial amount is shown in the "
            "breakdown only and is not counted"
        )
    return ComponentResult(component, status, currency, pricing_date, None, SourceType.NONE, None,
                           calculation_method=calculation_method, breakdown=breakdown, assumptions=assumptions,
                           warnings=warnings, missing_inputs=missing, partial_scope=partial)


@dataclass
class VariableCostSummary:
    """Aggregated variable cost components with explicit coverage."""

    pricing_date: date
    reporting_currency: str
    components: list[ComponentResult]

    def __post_init__(self) -> None:
        for c in self.components:
            if c.is_calculated and c.currency != self.reporting_currency:
                raise CurrencyMismatchError(
                    f"{c.component} is in {c.currency}; all calculated components must be in {self.reporting_currency}"
                )
        names = [c.component for c in self.components]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate components: {names}")

    @property
    def applicable(self) -> list[ComponentResult]:
        return [c for c in self.components if c.status != ComponentStatus.NOT_APPLICABLE]

    @property
    def calculated(self) -> list[ComponentResult]:
        return [c for c in self.components if c.is_calculated]

    @property
    def calculated_subtotal(self) -> Decimal | None:
        """Sum of calculated components only; ``None`` if nothing was calculated."""
        calculated = self.calculated
        return sum((c.amount for c in calculated), Decimal("0")) if calculated else None

    @property
    def is_complete(self) -> bool:
        applicable = self.applicable
        return bool(applicable) and all(c.is_calculated and not c.partial_scope for c in applicable)

    @property
    def complete_variable_cost(self) -> Decimal | None:
        return self.calculated_subtotal if self.is_complete else None

    @property
    def coverage_status(self) -> str:
        if self.is_complete:
            return "complete"
        return "partial" if self.calculated else "none"

    def counts_by_category(self) -> dict[str, int]:
        counts = {"public_tariff": 0, "public_benchmark": 0, "assumption": 0, "unavailable": 0, "not_applicable": 0}
        for c in self.components:
            if c.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF:
                counts["public_tariff"] += 1
            elif c.status == ComponentStatus.CALCULATED_BENCHMARK:
                counts["public_benchmark"] += 1
            elif c.status == ComponentStatus.CALCULATED_ASSUMPTION:
                counts["assumption"] += 1
            elif c.status == ComponentStatus.NOT_APPLICABLE:
                counts["not_applicable"] += 1
            else:
                counts["unavailable"] += 1
        return counts

    @property
    def unresolved_interpretations(self) -> list[str]:
        """Names of unresolved methodology interpretations used by calculated components."""
        return sorted({a.name for c in self.calculated for a in c.assumptions
                       if a.source_type == "unresolved_interpretation"})

    def coverage_label(self) -> str:
        """e.g. ``2 of 4 applicable components calculated`` (a count, not a share of cost)."""
        return f"{len(self.calculated)} of {len(self.applicable)} applicable components calculated"
