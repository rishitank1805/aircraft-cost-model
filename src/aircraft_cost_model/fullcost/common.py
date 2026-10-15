"""Shared machinery for Part 4 components: flight time bases, typed input reading, allocation, status.

Time bases (from the saved Part 2 flight estimate, fuel accounting ``v2``):

- block hours        = block_time_min / 60       (off-block to on-block)
- airborne hours     = airborne_time_min / 60    (lift-off to touchdown; "engine flight hours" basis)
- engine running hrs = block hours               (Part 2 assumes all engines run during taxi; labelled estimate)
- flight cycles      = 1 per completed leg; engine cycles = 1 per engine per leg

Status of a component: ``failed_validation`` if inputs contradict each other or
fall outside their effective period; ``unavailable_price`` if an FX rate is
missing; ``missing_required_input`` if a required value is absent; otherwise
``calculated_benchmark`` when every input is a public benchmark / observed
public data, else ``calculated_assumption``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from aircraft_cost_model.costs.coverage import Assumption, ComponentResult, ComponentStatus, SourceType
from aircraft_cost_model.costs.currency import RateProvider, convert, plain, round_money
from aircraft_cost_model.costs.exceptions import ObservationUnavailableError
from aircraft_cost_model.fullcost.scenario import Scenario, ScenarioValue

BENCHMARK_SOURCES = {"public_financial_benchmark", "observed_public_data"}
ALLOCATION_BASES = ("block_hours", "flights")


@dataclass(frozen=True)
class FlightBasis:
    flight_estimate_id: int
    aircraft_code: str
    block_hours: Decimal
    airborne_hours: Decimal
    engine_running_hours: Decimal
    flight_cycles: Decimal
    engine_count: int | None
    payload_kg: Decimal
    pricing_date: date
    reporting_currency: str
    operational_validity: str

    def to_dict(self) -> dict[str, Any]:
        return {"block_hours": plain(self.block_hours), "airborne_hours": plain(self.airborne_hours),
                "engine_running_hours": plain(self.engine_running_hours), "flight_cycles": plain(self.flight_cycles),
                "engine_count": self.engine_count}


@dataclass
class InputReader:
    """Reads typed scenario values for one component and collects problems and provenance."""

    component: str
    scenario: Scenario
    basis: FlightBasis
    fx: RateProvider
    missing: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    fx_problems: list[str] = field(default_factory=list)
    breakdown: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    used_sources: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def get(self, path: str, unit_dimension: str, *, required: bool = True, positive: bool = False,
            nonnegative: bool = True) -> Decimal | None:
        """Value at ``path`` in reporting currency (money) or as-is (plain units).

        ``unit_dimension``: a money dimension such as ``block_hour``/``year``/``amount``, or a plain unit
        such as ``block_hour/year`` or ``ratio``.
        """
        item: ScenarioValue | None = self.scenario.value(path)
        if item is None:
            if required:
                self.missing.append(path)
            return None
        if item.is_money:
            if item.dimension != unit_dimension:
                self.fail(f"{path}: unit {item.unit} is not <CCY>/{unit_dimension}")
                return None
        elif item.unit != unit_dimension:
            self.fail(f"{path}: unit {item.unit} is not {unit_dimension}")
            return None
        if not item.covers(self.basis.pricing_date):
            self.fail(f"{path}: effective period {item.effective_from}..{item.effective_to} does not cover "
                      f"pricing date {self.basis.pricing_date}")
            return None
        if positive and item.value <= 0:
            self.fail(f"{path}: must be > 0")
            return None
        if nonnegative and item.value < 0:
            self.fail(f"{path}: must be >= 0")
            return None
        self.used_sources.add(item.source_type)
        self.assumptions.append(Assumption(path, f"{item.value:f}", item.unit, item.source_type,
                                           item.source_reference or item.notes))
        if item.reference_period:
            self.warnings.append(f"{path}: source reference period {item.reference_period} applied to "
                                 f"{self.basis.pricing_date} (no inflation adjustment)")
        value = item.value
        if item.is_money and item.currency != self.basis.reporting_currency:
            try:
                conversion = convert(value, item.currency, self.basis.reporting_currency, self.basis.pricing_date, self.fx)
            except ObservationUnavailableError as exc:
                self.fx_problems.append(f"{path}: {exc}")
                return None
            self.breakdown.extend({"input": path, **step} for step in conversion.steps)
            value = conversion.amount_out
        return value

    def allocate(self, annual_amount: Decimal | None, section_path: str, label: str) -> Decimal | None:
        """Allocate an annual amount to this flight by the section's explicit ``allocation_basis``."""
        basis = self.scenario.flag(f"{section_path}.allocation_basis")
        if basis is None:
            self.missing.append(f"{section_path}.allocation_basis")
            return None
        if basis not in ALLOCATION_BASES:
            self.fail(f"{section_path}.allocation_basis must be one of {ALLOCATION_BASES}")
            return None
        if basis == "block_hours":
            denominator = self.get("utilization.annual_aircraft_block_hours", "block_hour/year", positive=True)
            numerator, what = self.basis.block_hours, "flight block hours / annual aircraft block hours"
        else:
            denominator = self.get("utilization.annual_flights", "flight/year", positive=True)
            numerator, what = Decimal(1), "1 flight / annual flights"
        if annual_amount is None or denominator is None:
            return None
        share = numerator / denominator
        amount = annual_amount * share
        self.breakdown.append({"step": f"allocate {label}", "basis": basis, "formula": what,
                               "annual_amount": plain(annual_amount), "share": plain(share), "value": plain(amount)})
        return amount

    def result(self, amount: Decimal | None, method: str, *, extra_warnings: list[str] | None = None,
               notes: list[str] | None = None) -> ComponentResult:
        currency, day = self.basis.reporting_currency, self.basis.pricing_date
        warnings = self.warnings + (extra_warnings or [])
        base = dict(calculation_method=method, breakdown=self.breakdown, assumptions=self.assumptions)
        if self.failures:
            return ComponentResult(self.component, ComponentStatus.FAILED_VALIDATION, currency, day,
                                   warnings=warnings + self.failures, **base)
        if self.fx_problems:
            return ComponentResult(self.component, ComponentStatus.UNAVAILABLE_PRICE, currency, day,
                                   warnings=warnings + self.fx_problems, **base)
        if self.missing or amount is None:
            return ComponentResult(self.component, ComponentStatus.MISSING_REQUIRED_INPUT, currency, day,
                                   warnings=warnings, missing_inputs=sorted(set(self.missing)), **base)
        benchmark_only = bool(self.used_sources) and self.used_sources <= BENCHMARK_SOURCES
        status = ComponentStatus.CALCULATED_BENCHMARK if benchmark_only else ComponentStatus.CALCULATED_ASSUMPTION
        source = SourceType.PUBLIC_FINANCIAL_BENCHMARK if benchmark_only else SourceType.USER_ASSUMPTION
        rounded = round_money(amount)
        self.breakdown.append({"step": "rounding", "formula": "round half up to 0.01", "value": plain(rounded)})
        return ComponentResult(self.component, status, currency, day, rounded, source,
                               "; ".join(sorted({a.reference for a in self.assumptions if a.reference})) or None,
                               warnings=warnings + (notes or []), zero_by_tariff_rule=rounded == 0, **base)


def not_applicable(component: str, basis: FlightBasis, reason: str) -> ComponentResult:
    """A component that genuinely does not apply under the scenario (not unavailable)."""
    return ComponentResult(component, ComponentStatus.NOT_APPLICABLE, basis.reporting_currency, basis.pricing_date,
                           calculation_method="not applicable", breakdown=[{"reason": reason}],
                           warnings=[f"{component}: not applicable - {reason}"])


def failed(component: str, basis: FlightBasis, message: str) -> ComponentResult:
    return ComponentResult(component, ComponentStatus.FAILED_VALIDATION, basis.reporting_currency, basis.pricing_date,
                           calculation_method="validation", warnings=[f"{component}: {message}"])
