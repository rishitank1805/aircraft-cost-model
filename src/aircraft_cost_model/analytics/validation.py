"""Structured validation of a saved full-cost estimate.

A. Arithmetic   - component sums, category subtotals, COC/TOC/Total chain, complete-total rules,
                  2-decimal money, exact decimal storage, fuel unit and currency conversion recheck,
                  reproducibility (recalculation from the stored scenario).
B. Operational  - positive block hours and distance, one cycle per leg, supported aircraft,
                  payload basis, operational validity carried unchanged from Part 2.
C. Financial    - coverage status, no missing-as-zero, double-counting flags, ownership-mode
                  consistency, stored source-quality summary, historical pricing rules.
D. External     - benchmark comparisons with explicit comparability (see benchmarks.py).

Each check is ``pass``, ``fail``, ``warn`` or ``not_performed`` (never reported as
passed when it could not run).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.benchmarks import (
    BenchmarkComparisonResult,
    compare_with_benchmark,
    default_selections,
    read_aircraft_mapping,
)
from aircraft_cost_model.analytics.cases import load_saved_case
from aircraft_cost_model.costs.fuel_cost import US_GALLON_LITRES
from aircraft_cost_model.fullcost.aggregate import TAXONOMY, Category
from aircraft_cost_model.fullcost.calculator import calculate_full_costs
from aircraft_cost_model.models import CostComponent, FlightEstimate, FullCostEstimate, VariableCostEstimate

CENT = Decimal("0.01")


@dataclass(frozen=True)
class ValidationCheck:
    category: str  # arithmetic | operational | financial | external
    name: str
    status: str  # pass | fail | warn | not_performed
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"category": self.category, "name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class ValidationResult:
    full_cost_estimate_id: int
    checks: list[ValidationCheck]
    benchmark_comparisons: list[BenchmarkComparisonResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        statuses = {c.status for c in self.checks}
        return "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for c in self.checks:
            out.setdefault(c.category, {}).setdefault(c.status, 0)
            out[c.category][c.status] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"full_cost_estimate_id": self.full_cost_estimate_id, "status": self.status, "counts": self.counts(),
                "checks": [c.to_dict() for c in self.checks],
                "benchmark_comparisons": [b.to_dict() for b in self.benchmark_comparisons]}


def _chk(out: list[ValidationCheck], category: str, name: str, ok: bool | None, detail: str,
         warn_only: bool = False) -> None:
    status = "not_performed" if ok is None else ("pass" if ok else ("warn" if warn_only else "fail"))
    out.append(ValidationCheck(category, name, status, detail))


def _arithmetic(session: Session, est: FullCostEstimate, out: list[ValidationCheck]) -> None:
    comps = {c.component_name: c for c in est.components}
    subtotal_cols = {Category.DIRECT_VARIABLE: est.direct_variable_subtotal, Category.DIRECT_FIXED: est.direct_fixed_subtotal,
                     Category.INDIRECT: est.indirect_subtotal, Category.NONCASH: est.noncash_subtotal,
                     Category.FINANCING: est.financing_subtotal}
    sums: dict[Category, Decimal | None] = {}
    for category, stored in subtotal_cols.items():
        amounts = [comps[n].amount for n in TAXONOMY[category] if comps[n].amount is not None]
        sums[category] = sum(amounts, Decimal(0)) if amounts else None
        _chk(out, "arithmetic", f"{category.value}_subtotal", sums[category] == stored,
             f"sum of calculated components {sums[category]} vs stored {stored}")
    def add(*cats):
        vals = [sums[c] for c in cats if sums[c] is not None]
        return sum(vals, Decimal(0)) if vals else None
    chain = [("cash_operating_subtotal", est.cash_operating_subtotal,
              add(Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT)),
             ("total_operating_subtotal", est.total_operating_subtotal,
              add(Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT, Category.NONCASH)),
             ("total_cost_subtotal", est.total_cost_subtotal, add(*Category))]
    for name, stored, expected in chain:
        _chk(out, "arithmetic", name, stored == expected, f"COC/TOC/Total chain: expected {expected}, stored {stored}")
    blocking = [n for n, c in comps.items() if c.status != "not_applicable" and c.amount is None]
    _chk(out, "arithmetic", "complete_totals_rule",
         (est.complete_coc is None and est.complete_toc is None and est.complete_total_costs is None) if blocking
         else (est.complete_total_costs == est.total_cost_subtotal),
         f"complete totals {'withheld' if blocking else 'set'}; blocking components: {blocking or 'none'}")
    bad_scale = [n for n, c in comps.items() if c.amount is not None and c.amount != c.amount.quantize(CENT)]
    _chk(out, "arithmetic", "money_precision", not bad_scale, f"components not at 0.01: {bad_scale or 'none'}")
    raw = session.execute(text("SELECT component_name, amount, typeof(amount) FROM full_cost_component "
                               "WHERE full_cost_estimate_id = :i"), {"i": est.full_cost_estimate_id}).all()
    non_text = [r[0] for r in raw if r[1] is not None and r[2] != "text"]
    _chk(out, "arithmetic", "exact_decimal_storage", not non_text,
         f"amounts stored as exact decimal text; non-text: {non_text or 'none'}")
    # fuel unit and currency conversion recheck from the stored breakdown
    fuel = comps.get("fuel")
    if fuel is None or fuel.amount is None:
        _chk(out, "arithmetic", "fuel_conversion_recheck", None, "fuel not calculated")
    else:
        import json
        steps = {s.get("step"): s for s in json.loads(fuel.breakdown_json)}
        try:
            kg = Decimal(steps["block fuel"]["value"])
            density = Decimal(steps["kg -> L"]["formula"].split("/")[1].split()[0])
            litres = kg / density
            gallons = litres / US_GALLON_LITRES
            usd = gallons * Decimal(steps["price"]["value"])
            fx = next(s for k, s in steps.items() if k and "-> EUR" in k)
            eur = usd / Decimal(fx["rate"])
            ok = eur.quantize(CENT, ROUND_HALF_UP) == fuel.amount
            _chk(out, "arithmetic", "fuel_conversion_recheck", ok,
                 f"{kg} kg / {density} kg/L / {US_GALLON_LITRES} L/gal x {steps['price']['value']} "
                 f"{steps['price']['unit']} / {fx['rate']} USD/EUR = {eur.quantize(Decimal('0.0001'))} -> {fuel.amount}")
        except (KeyError, StopIteration, IndexError) as exc:
            _chk(out, "arithmetic", "fuel_conversion_recheck", None, f"breakdown incomplete ({exc})")
    # reproducibility from the stored scenario
    case = load_saved_case(session, est.full_cost_estimate_id)
    try:
        recalculated = calculate_full_costs(session, est.flight_estimate_id, est.variable_cost_estimate_id, case.scenario)
        same_amounts = all(recalculated.summary.components[n].amount == c.amount
                           and recalculated.summary.components[n].status.value == c.status for n, c in comps.items())
        same_hash = recalculated.input_hash == est.input_hash
        version_note = ("" if recalculated.calculation_version == est.calculation_version else
                        f"; calculation version changed {est.calculation_version} -> {recalculated.calculation_version}")
        _chk(out, "arithmetic", "reproducibility", same_amounts and (same_hash or bool(version_note)),
             f"recalculated from stored scenario: amounts {'identical' if same_amounts else 'DIFFER'}, input hash "
             f"{'identical' if same_hash else 'differs'}{version_note}")
    except Exception as exc:  # report, never hide
        _chk(out, "arithmetic", "reproducibility", False, f"recalculation failed: {exc}")


def _operational(session: Session, est: FullCostEstimate, out: list[ValidationCheck]) -> None:
    case = load_saved_case(session, est.full_cost_estimate_id)
    f = case.facts
    _chk(out, "operational", "block_hours_positive", f.block_hours > 0, f"block hours {f.block_hours}")
    _chk(out, "operational", "distance_positive", f.great_circle_nm > 0 and f.modelled_route_nm > 0,
         f"great-circle {f.great_circle_nm} NM, modelled route {f.modelled_route_nm} NM")
    _chk(out, "operational", "flight_cycles", f.flight_cycles == 1, "one completed leg = 1 flight cycle")
    _chk(out, "operational", "supported_aircraft", f.aircraft_supported, f"{f.aircraft_code} performance model supported")
    _chk(out, "operational", "payload_basis", f.modelled_payload_kg > 0,
         f"Part 2 modelled payload {f.modelled_payload_kg} kg (mass assumption; NOT revenue cargo payload)")
    flight = session.get(FlightEstimate, est.flight_estimate_id)
    _chk(out, "operational", "validity_carried_forward", est.operational_validity_status == flight.calculation_status,
         f"stored {est.operational_validity_status}; Part 2 {flight.calculation_status}")
    _chk(out, "operational", "fuel_accounting_v2", flight.fuel_accounting_basis == "v2",
         f"fuel accounting {flight.fuel_accounting_basis}")
    if flight.calculation_status != "calculated":
        out.append(ValidationCheck("operational", "flight_limits_verified", "warn",
                                   f"Part 2 status {flight.calculation_status}: some aircraft limits could not be "
                                   "verified; costs do not change this"))


def _financial(session: Session, est: FullCostEstimate, out: list[ValidationCheck]) -> None:
    case = load_saved_case(session, est.full_cost_estimate_id)
    s, sc = case.summary, case.scenario
    comps = s.components
    _chk(out, "financial", "coverage_status", s.cost_coverage_status == est.cost_coverage_status,
         f"recomputed {s.cost_coverage_status}, stored {est.cost_coverage_status}")
    zero_bad = [n for n, c in comps.items() if c.is_calculated and c.amount == 0 and not c.zero_by_tariff_rule]
    nonnull_bad = [n for n, c in comps.items() if not c.is_calculated and c.amount is not None]
    _chk(out, "financial", "no_missing_as_zero", not zero_bad and not nonnull_bad,
         f"uncalculated components are NULL; zero amounts only by tariff rule (violations: {zero_bad + nonnull_bad or 'none'})")
    mode = est.ownership_mode
    st = {n: comps[n].status.value for n in ("operating_lease", "depreciation", "financing_interest")}
    if mode == "owned":
        ok, detail = st["operating_lease"] == "not_applicable", f"owned: lease {st['operating_lease']}"
    elif mode == "operating_lease":
        ok = st["depreciation"] == st["financing_interest"] == "not_applicable"
        detail = f"operating lease: depreciation {st['depreciation']}, financing {st['financing_interest']}"
    else:
        flags = sc.flag("custom_treatment") or {}
        included = [k for k in ("include_operating_lease", "include_depreciation", "include_financing") if flags.get(k)]
        ok = len(included) < 3 and bool(str(flags.get("justification", "")).strip())
        detail = f"custom: included {included}; justification present: {bool(flags.get('justification'))}"
    _chk(out, "financial", "ownership_mode_consistency", ok, detail)
    covers = set(sc.flag("maintenance.airframe.covers") or ())
    dbl = []
    for name, flag in (("engine_maintenance", "engine"), ("engine_llp", "engine_llp")):
        if flag in covers and comps[name].is_calculated:
            dbl.append(name)
    if sc.flag("maintenance.engine.includes_llp") is True and comps["engine_llp"].is_calculated:
        dbl.append("engine_llp (in engine rate)")
    if sc.flag("crew.salaries.includes_allowances") is True and comps["crew_allowances"].is_calculated:
        dbl.append("crew_allowances")
    if "insurance" in (sc.flag("operating_lease.includes") or ()) and comps["insurance"].is_calculated:
        dbl.append("insurance (in lease)")
    _chk(out, "financial", "no_double_counting", not dbl, f"overlapping components: {dbl or 'none'}")
    _chk(out, "financial", "source_quality_summary", s.source_quality_summary == est.source_quality_summary,
         f"recomputed {s.source_quality_summary!r}, stored {est.source_quality_summary!r}")
    variable = session.get(VariableCostEstimate, est.variable_cost_estimate_id)
    _chk(out, "financial", "pricing_date_consistency", variable.pricing_date == est.pricing_date,
         f"Part 3 {variable.pricing_date}, full cost {est.pricing_date}")
    rows = session.scalars(select(CostComponent).where(
        CostComponent.variable_cost_estimate_id == est.variable_cost_estimate_id)).all()
    late = [r.component_name for r in rows if r.pricing_observation_date and r.pricing_observation_date > est.pricing_date]
    import json
    fx_late = []
    for r in rows:
        for step in json.loads(r.breakdown_json):
            if isinstance(step, dict) and step.get("series_key") and date.fromisoformat(step["observation_date"]) > est.pricing_date:
                fx_late.append(r.component_name)
    _chk(out, "financial", "historical_pricing_rule", not late and not fx_late,
         f"no price, tariff or FX observation after the pricing date (violations: {late + fx_late or 'none'})")
    if s.source_quality_summary.find("explicit_user_assumption") >= 0:
        out.append(ValidationCheck("financial", "assumption_disclosure", "warn",
                                   "result depends on explicit user/illustrative assumptions (see source quality)"))


def validate_estimate(session: Session, full_cost_estimate_id: int, aircraft_mapping_path: Path | None = None
                      ) -> ValidationResult:
    est = session.get(FullCostEstimate, full_cost_estimate_id)
    if est is None:
        from aircraft_cost_model.analytics.cases import AnalyticsInputError
        raise AnalyticsInputError(f"full_cost_estimate_id {full_cost_estimate_id} does not exist")
    checks: list[ValidationCheck] = []
    _arithmetic(session, est, checks)
    _operational(session, est, checks)
    _financial(session, est, checks)
    comparisons: list[BenchmarkComparisonResult] = []
    if aircraft_mapping_path is None or not aircraft_mapping_path.is_file():
        checks.append(ValidationCheck("external", "benchmark_comparisons", "not_performed",
                                      "aircraft-type mapping file not available"))
    else:
        case = load_saved_case(session, full_cost_estimate_id)
        mapping = read_aircraft_mapping(aircraft_mapping_path)
        for key, denominator, selection in default_selections(case, mapping):
            comparisons.append(compare_with_benchmark(session, case, key, denominator, selection, mapping))
        if not comparisons:
            checks.append(ValidationCheck("external", "benchmark_comparisons", "not_performed",
                                          "no benchmark selection applies to this aircraft"))
        for comp in comparisons:
            status = {"comparable": "pass", "comparable_with_caveats": "warn", "not_comparable": "not_performed"}[
                comp.comparability]
            detail = (f"{comp.comparability}: model {comp.model_value and comp.model_value.quantize(CENT)} vs "
                      f"benchmark {comp.benchmark_value_converted and comp.benchmark_value_converted.quantize(CENT)} "
                      f"{comp.model_unit}" + (f"; reasons: {comp.reasons}" if comp.reasons else ""))
            checks.append(ValidationCheck("external", f"{comp.model_metric} vs {comp.benchmark.selection.source}",
                                          status, detail))
    return ValidationResult(full_cost_estimate_id, checks, comparisons)
