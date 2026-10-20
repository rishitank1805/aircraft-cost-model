"""Project cost taxonomy, aggregation and the three independent quality dimensions.

Taxonomy (project reporting convention; not IFRS, US GAAP or a manufacturer standard):

    Direct variable = fuel + airframe maintenance + engine maintenance + engine LLP
                      + en-route navigation + terminal navigation + landing + ground handling
                      + crew allowances
    Direct fixed    = crew salaries + insurance + operating lease
    Indirect        = administration + cargo sales + general & administrative
    COC             = direct variable + direct fixed + indirect
    TOC             = COC + depreciation (noncash)
    Total costs     = TOC + financing

Rules:

- Category *calculated subtotals* add calculated components only and are
  never called totals.
- A *complete* category / COC / TOC / total exists only when every
  applicable component below it is calculated with full scope;
  ``not_applicable`` components do not block completeness.
- Dimension A (cost coverage), B (operational validity of the Part 2 flight
  estimate) and C (source quality of the monetary inputs) are reported
  separately; a financial calculation never changes B.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from aircraft_cost_model.costs.coverage import ComponentResult, ComponentStatus, SourceType


class Category(str, Enum):
    DIRECT_VARIABLE = "direct_variable"
    DIRECT_FIXED = "direct_fixed"
    INDIRECT = "indirect"
    NONCASH = "noncash"
    FINANCING = "financing"


TAXONOMY: dict[Category, tuple[str, ...]] = {
    Category.DIRECT_VARIABLE: ("fuel", "airframe_maintenance", "engine_maintenance", "engine_llp", "navigation",
                               "terminal_navigation", "landing", "ground_handling", "crew_allowances"),
    Category.DIRECT_FIXED: ("crew_salaries", "insurance", "operating_lease"),
    Category.INDIRECT: ("administration", "cargo_sales", "general_administrative"),
    Category.NONCASH: ("depreciation",),
    Category.FINANCING: ("financing_interest",),
}
COMPONENT_CATEGORY = {name: category for category, names in TAXONOMY.items() for name in names}


class SourceQuality(str, Enum):
    OBSERVED_PUBLIC_DATA = "observed_public_data"  # published tariffs/charges as levied
    PUBLIC_MARKET_BENCHMARK = "public_market_benchmark"  # e.g. EIA spot fuel price: a market index, not airline expense
    PUBLIC_FINANCIAL_BENCHMARK = "public_financial_benchmark"
    MODELLED_ESTIMATE = "modelled_estimate"
    EXPLICIT_USER_ASSUMPTION = "explicit_user_assumption"
    MIXED = "mixed"
    NONE = "none"


_VALUE_SOURCE_QUALITY = {
    "illustrative_assumption": SourceQuality.EXPLICIT_USER_ASSUMPTION,
    "user_assumption": SourceQuality.EXPLICIT_USER_ASSUMPTION,
    "public_financial_benchmark": SourceQuality.PUBLIC_FINANCIAL_BENCHMARK,
    "observed_public_data": SourceQuality.OBSERVED_PUBLIC_DATA,
}


def component_source_quality(result: ComponentResult) -> SourceQuality:
    """Quality of the *monetary* rates/prices behind a calculated component.

    Part 3 published tariffs count as observed public data (the charge as
    levied). Part 3 market prices (EIA jet-fuel spot benchmark) count as a
    public market benchmark: never as observed airline expense. Part 3
    scenario (assumption) results are mixed. Part 4 components derive quality
    from their scenario inputs. Modelled physical quantities (fuel burn, block
    time) are covered by operational validity, not here.
    """
    if not result.is_calculated:
        return SourceQuality.NONE
    if result.status == ComponentStatus.CALCULATED_ASSUMPTION and result.source_type in (
            SourceType.PUBLIC_TARIFF, SourceType.PUBLIC_MARKET_BENCHMARK):
        return SourceQuality.MIXED  # e.g. Part 3 navigation with a type-level MTOW scenario
    if result.source_type == SourceType.PUBLIC_TARIFF:
        return SourceQuality.OBSERVED_PUBLIC_DATA
    if result.source_type == SourceType.PUBLIC_MARKET_BENCHMARK:
        return SourceQuality.PUBLIC_MARKET_BENCHMARK
    qualities = {_VALUE_SOURCE_QUALITY[a.source_type] for a in result.assumptions if a.source_type in _VALUE_SOURCE_QUALITY}
    if not qualities:
        return SourceQuality.EXPLICIT_USER_ASSUMPTION if result.source_type == SourceType.USER_ASSUMPTION \
            else SourceQuality.MODELLED_ESTIMATE
    return qualities.pop() if len(qualities) == 1 else SourceQuality.MIXED


@dataclass(frozen=True)
class CategorySummary:
    category: Category
    calculated_subtotal: Decimal | None
    complete_amount: Decimal | None
    missing_components: tuple[str, ...]
    not_applicable_components: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return not self.missing_components


@dataclass
class FullCostSummary:
    """All components plus the three dimensions."""

    components: dict[str, ComponentResult]
    reporting_currency: str
    operational_validity: str

    def __post_init__(self) -> None:
        unknown = set(self.components) - set(COMPONENT_CATEGORY)
        missing = set(COMPONENT_CATEGORY) - set(self.components)
        if unknown or missing:
            raise ValueError(f"Component set mismatch: unknown {sorted(unknown)}, missing {sorted(missing)}")
        for name, result in self.components.items():
            if result.is_calculated and result.currency != self.reporting_currency:
                raise ValueError(f"{name} is in {result.currency}, expected {self.reporting_currency}")

    # Dimension A ---------------------------------------------------------------
    def category(self, category: Category) -> CategorySummary:
        results = [self.components[n] for n in TAXONOMY[category]]
        calculated = [r for r in results if r.is_calculated]
        blocking = tuple(r.component for r in results
                         if r.status != ComponentStatus.NOT_APPLICABLE and (not r.is_calculated or r.partial_scope))
        subtotal = sum((r.amount for r in calculated), Decimal(0)) if calculated else None
        complete = (subtotal if subtotal is not None else Decimal("0.00")) if not blocking else None
        return CategorySummary(category, subtotal, complete, blocking,
                               tuple(r.component for r in results if r.status == ComponentStatus.NOT_APPLICABLE))

    def _cumulative(self, categories: tuple[Category, ...]) -> tuple[Decimal | None, Decimal | None, tuple[str, ...]]:
        summaries = [self.category(c) for c in categories]
        subtotals = [s.calculated_subtotal for s in summaries if s.calculated_subtotal is not None]
        calculated = sum(subtotals, Decimal(0)) if subtotals else None
        missing = tuple(m for s in summaries for m in s.missing_components)
        complete = sum((s.complete_amount for s in summaries), Decimal(0)) if not missing else None
        return calculated, complete, missing

    @property
    def coc(self) -> tuple[Decimal | None, Decimal | None, tuple[str, ...]]:
        return self._cumulative((Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT))

    @property
    def toc(self) -> tuple[Decimal | None, Decimal | None, tuple[str, ...]]:
        return self._cumulative((Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT, Category.NONCASH))

    @property
    def total(self) -> tuple[Decimal | None, Decimal | None, tuple[str, ...]]:
        return self._cumulative(tuple(Category))

    @property
    def cost_coverage_status(self) -> str:
        statuses = {r.status for r in self.components.values()}
        if ComponentStatus.FAILED_VALIDATION in statuses:
            return "failed_validation"
        return "complete" if not self.total[2] else "incomplete"

    def coverage_counts(self) -> dict[str, int]:
        counts = {"calculated": 0, "not_applicable": 0, "missing_required_input": 0, "failed_validation": 0,
                  "unavailable": 0}
        for result in self.components.values():
            if result.is_calculated:
                counts["calculated"] += 1
            elif result.status == ComponentStatus.NOT_APPLICABLE:
                counts["not_applicable"] += 1
            elif result.status == ComponentStatus.MISSING_REQUIRED_INPUT:
                counts["missing_required_input"] += 1
            elif result.status == ComponentStatus.FAILED_VALIDATION:
                counts["failed_validation"] += 1
            else:
                counts["unavailable"] += 1
        return counts

    # Dimension C ---------------------------------------------------------------
    def source_qualities(self) -> dict[str, SourceQuality]:
        return {n: component_source_quality(r) for n, r in self.components.items()}

    @property
    def source_quality_summary(self) -> str:
        qualities = sorted({q.value for q in self.source_qualities().values() if q != SourceQuality.NONE})
        if not qualities:
            return SourceQuality.NONE.value
        return qualities[0] if len(qualities) == 1 else "mixed: " + ", ".join(qualities)

    def to_dict(self) -> dict[str, Any]:
        def money(value: Decimal | None) -> str | None:
            return None if value is None else f"{value:f}"
        return {
            "categories": {c.value: {"calculated_subtotal": money(s.calculated_subtotal), "complete": money(s.complete_amount),
                                     "missing": list(s.missing_components)} for c in Category for s in [self.category(c)]},
            "coc": [money(self.coc[0]), money(self.coc[1])], "toc": [money(self.toc[0]), money(self.toc[1])],
            "total": [money(self.total[0]), money(self.total[1])],
            "cost_coverage_status": self.cost_coverage_status, "operational_validity": self.operational_validity,
            "source_quality": self.source_quality_summary,
        }
