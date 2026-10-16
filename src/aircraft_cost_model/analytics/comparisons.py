"""Route, aircraft, scenario and ownership comparisons.

Rules:

- Complete COC/TOC/Total are compared as complete only when every compared
  case has them. Otherwise only calculated (partial) subtotals are shown, with
  a coverage-mismatch warning when the cases include different components.
- ``common_component_comparison`` adds, for every case, only the components
  that are calculated (full scope) and *identically defined* in all cases
  (same component, same scope flags, same price series). It is never a complete
  operating cost.
- Unsupported aircraft appear as explicit unsupported rows; no passenger model
  is substituted.
- Different reporting currencies are not compared; different pricing dates
  are flagged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from aircraft_cost_model.analytics.cases import AnalyticsInputError, CostCase
from aircraft_cost_model.analytics.metrics import DistanceInput
from aircraft_cost_model.costs.currency import plain
from aircraft_cost_model.fullcost.aggregate import COMPONENT_CATEGORY, Category

GROUPS: dict[str, tuple[str, ...]] = {
    "fuel_cost": ("fuel",),
    "maintenance": ("airframe_maintenance", "engine_maintenance", "engine_llp"),
    "crew": ("crew_salaries", "crew_allowances"),
    "charges_and_handling": ("navigation", "terminal_navigation", "landing", "ground_handling"),
    "insurance": ("insurance",),
    "ownership": ("operating_lease", "depreciation", "financing_interest"),
    "indirect": ("administration", "cargo_sales", "general_administrative"),
}
COMMON_LABEL = "common_component_comparison"
OWNERSHIP_PATH_PREFIXES = ("operating_lease.", "depreciation.", "financing.")


@dataclass(frozen=True)
class GroupAmount:
    calculated: Decimal | None
    complete: Decimal | None
    missing: tuple[str, ...]
    not_applicable: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"calculated_subtotal": None if self.calculated is None else plain(self.calculated),
                "complete": None if self.complete is None else plain(self.complete),
                "missing": list(self.missing), "not_applicable": list(self.not_applicable)}


def group_amount(case: CostCase, names: tuple[str, ...]) -> GroupAmount:
    comps = case.summary.components
    calc = [comps[n].amount for n in names if comps[n].is_calculated]
    missing = tuple(n for n in names if comps[n].status.value != "not_applicable"
                    and (not comps[n].is_calculated or comps[n].partial_scope))
    na = tuple(n for n in names if comps[n].status.value == "not_applicable")
    subtotal = sum(calc, Decimal(0)) if calc else None
    complete = (subtotal if subtotal is not None else Decimal("0.00")) if not missing else None
    return GroupAmount(subtotal, complete, missing, na)


def component_signature(case: CostCase, name: str) -> tuple:
    """What a component *means* in this case; identical signatures are directly comparable."""
    comp = case.summary.components[name]
    scenario = case.scenario
    flag = scenario.flag if scenario is not None else (lambda _p: None)
    if name == "fuel":
        price = next((s for s in comp.breakdown if s.get("step") == "price"), {})
        return (name, price.get("series"), price.get("unit"), comp.partial_scope)
    if name in ("navigation", "terminal_navigation", "landing", "ground_handling"):
        return (name, comp.partial_scope, comp.source_type.value)
    if name == "airframe_maintenance":
        return (name, tuple(sorted(flag("maintenance.airframe.covers") or ())),
                flag("maintenance.airframe.hourly_rate_includes_cycle_costs"))
    if name == "engine_maintenance":
        return (name, flag("maintenance.engine.engine_hours_basis"), flag("maintenance.engine.includes_llp"),
                flag("maintenance.engine.hourly_rate_includes_cycle_costs"))
    if name == "crew_salaries":
        return (name, flag("crew.salaries.basis"), flag("crew.salaries.includes_allowances"))
    if name == "insurance":
        return (name, flag("insurance.basis"), "insurance" in (flag("operating_lease.includes") or ()))
    if name == "operating_lease":
        return (name, tuple(sorted(flag("operating_lease.includes") or ())))
    if name in ("administration", "general_administrative"):
        return (name, flag(f"indirect.{name}.scope"))
    if name == "cargo_sales":
        return (name, flag("indirect.cargo_sales.basis"))
    if name == "depreciation":
        return (name, flag("depreciation.method"))
    if name == "financing_interest":
        return (name, flag("financing.mode"))
    return (name,)


@dataclass
class ComparisonRow:
    case: CostCase
    values: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.values


@dataclass
class ComparisonResult:
    analysis_type: str
    rows: list[ComparisonRow]
    currency: str | None
    complete_totals_comparable: bool
    coverage_mismatch: dict[str, list[str]]
    pricing_dates: list[str]
    common_components: list[str]
    excluded_from_common: dict[str, str]
    common_subtotals: dict[str, Decimal | None]
    warnings: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"analysis_type": self.analysis_type, "currency": self.currency,
                "complete_totals_comparable": self.complete_totals_comparable,
                "coverage_mismatch": self.coverage_mismatch, "pricing_dates": self.pricing_dates,
                COMMON_LABEL: {"components": self.common_components, "excluded": self.excluded_from_common,
                               "subtotals": {k: (None if v is None else plain(v)) for k, v in self.common_subtotals.items()},
                               "label": "common-component subtotal (NOT a complete operating cost)"},
                "warnings": self.warnings, "explanation": self.explanation,
                "rows": [r.to_dict() for r in self.rows]}


def _row_values(case: CostCase, distance: DistanceInput) -> dict[str, Any]:
    if not case.is_costed:
        return {"label": case.label, "aircraft": case.aircraft_code, "status": case.origin,
                "cost_coverage": "unsupported" if case.origin == "unsupported" else "missing_required_input",
                "reason": "; ".join(case.warnings)}
    f, s = case.facts, case.summary
    distance_nm, _ = distance.resolve(f)
    values: dict[str, Any] = {
        "label": case.label, "aircraft": f.aircraft_code, "origin": f.origin, "destination": f.destination,
        "flight_estimate_id": f.flight_estimate_id, "variable_cost_estimate_id": case.variable_cost_estimate_id,
        "full_cost_estimate_id": case.full_cost_estimate_id, "scenario_id": case.scenario_id,
        "scenario": case.scenario.name if case.scenario else None,
        "scenario_hash": case.scenario_hash[:12] if case.scenario_hash else None,
        "ownership_mode": case.ownership_mode, "pricing_date": case.pricing_date.isoformat(),
        "currency": s.reporting_currency, "block_hours": plain(f.block_hours),
        "distance_nm": plain(distance_nm) if distance_nm is not None else None, "distance_basis": distance.basis.value,
        "block_fuel_kg": plain(f.block_fuel_kg), "status": case.origin,
    }
    for group, names in GROUPS.items():
        values[group] = group_amount(case, names).to_dict()
    for key, triple in (("coc", s.coc), ("toc", s.toc), ("total_costs", s.total)):
        values[key] = {"calculated_subtotal": None if triple[0] is None else plain(triple[0]),
                       "complete": None if triple[1] is None else plain(triple[1]), "missing": list(triple[2])}
    values.update(cost_coverage={"complete": "complete", "incomplete": "partial",
                                 "failed_validation": "calculation_error"}[s.cost_coverage_status],
                  operational_validity=s.operational_validity, source_quality=s.source_quality_summary)
    return values


def compare_cases(cases: list[CostCase], distance: DistanceInput, analysis_type: str = "comparison") -> ComparisonResult:
    if len(cases) < 2:
        raise AnalyticsInputError("a comparison needs at least two cases")
    costed = [c for c in cases if c.is_costed]
    currencies = sorted({c.summary.reporting_currency for c in costed})
    if len(currencies) > 1:
        raise AnalyticsInputError(f"cases use different reporting currencies {currencies}; not comparable")
    warnings: list[str] = []
    for c in cases:
        if not c.is_costed:
            warnings.append(f"{c.label}: {c.origin} - " + "; ".join(c.warnings))
    dates = sorted({c.pricing_date.isoformat() for c in costed})
    if len(dates) > 1:
        warnings.append(f"pricing dates differ ({', '.join(dates)}): price, tariff and FX differences are mixed with "
                        "operational differences")
    calculated_sets = {c.label: {n for n, r in c.summary.components.items() if r.is_calculated and not r.partial_scope}
                       for c in costed}
    union = set().union(*calculated_sets.values()) if calculated_sets else set()
    # A coverage gap is a component calculated in one case but applicable and unavailable in another. A component
    # that is not_applicable (e.g. lease vs depreciation across ownership modes) is a taxonomy difference instead.
    mismatch, applicability = {}, {}
    for c in costed:
        missing = sorted(n for n in union - calculated_sets[c.label] if c.summary.components[n].status.value != "not_applicable")
        na = sorted(n for n in union - calculated_sets[c.label] if c.summary.components[n].status.value == "not_applicable")
        if missing:
            mismatch[c.label] = missing
        if na:
            applicability[c.label] = na
    if mismatch:
        warnings.append("coverage mismatch: the partial subtotals include different components and are NOT directly "
                        f"comparable; see {COMMON_LABEL}")
    if applicability:
        warnings.append("applicability differs (not applicable by scenario convention, not missing): "
                        + "; ".join(f"{k}: {v}" for k, v in applicability.items()))
    by_scenario: dict[str, set[str]] = {}
    for c in costed:
        by_scenario.setdefault(c.scenario_hash or "", set()).add(c.facts.aircraft_code)
    shared = [sorted(types) for types in by_scenario.values() if len(types) > 1]
    if shared:
        warnings.append(f"the same cost scenario is applied to different aircraft types {shared}: its maintenance, crew "
                        "and ownership inputs are not aircraft-specific, so differences come from flight time, fuel and "
                        "allocation only")
    complete_ok = bool(costed) and all(c.summary.total[1] is not None for c in costed)
    if not complete_ok:
        warnings.append("complete COC/TOC/Total are unavailable for at least one case; only calculated subtotals "
                        "(partial) are shown")
    common, excluded = [], {}
    intersection = set.intersection(*calculated_sets.values()) if calculated_sets else set()
    for name in COMPONENT_CATEGORY:
        if name not in intersection:
            if name in union:
                excluded[name] = ("not applicable in some cases" if all(
                    c.summary.components[name].is_calculated or c.summary.components[name].status.value == "not_applicable"
                    for c in costed) else "not calculated (full scope) in every case")
            continue
        signatures = {component_signature(c, name) for c in costed}
        if len(signatures) > 1:
            excluded[name] = f"defined differently across cases: {sorted(map(str, signatures))}"
        else:
            common.append(name)
    common_subtotals = {c.label: (sum((c.summary.components[n].amount for n in common), Decimal(0)) if common else None)
                        for c in costed}
    return ComparisonResult(analysis_type, [ComparisonRow(c, _row_values(c, distance)) for c in cases],
                            currencies[0] if currencies else None, complete_ok, mismatch, dates, common, excluded,
                            common_subtotals, warnings)


OWNERSHIP_EXPLANATION = [
    "Project taxonomy (Part 4): the operating lease payment is a direct fixed cost inside COC; depreciation is a "
    "noncash cost added in TOC; financing interest is added only in Total Costs.",
    "An owned aircraft's capital cost therefore appears only in TOC and Total, while a leased aircraft's appears "
    "already in COC. COC and TOC differences between modes reflect this convention.",
    "This is an economic-cost comparison under the scenarios' assumptions, not an IFRS 16 or US GAAP comparison: a "
    "lessee's accounting would show right-of-use depreciation and lease interest instead of rent.",
    "Owned: lease not applicable. Operating lease: aircraft depreciation and acquisition financing are excluded "
    "(not applicable) under this convention; incompatible treatments are never combined.",
]


def scenario_differences(a: CostCase, b: CostCase) -> list[str]:
    """Scenario inputs that differ apart from ownership-specific sections."""
    def relevant(case: CostCase) -> dict[str, tuple[str, str]]:
        return {p: (plain(v.value), v.unit) for p, v in case.scenario.values.items()
                if not p.startswith(OWNERSHIP_PATH_PREFIXES)}
    ra, rb = relevant(a), relevant(b)
    diffs = [f"{p}: {ra.get(p)} vs {rb.get(p)}" for p in sorted(set(ra) | set(rb)) if ra.get(p) != rb.get(p)]
    for key in ("maintenance", "crew", "insurance", "indirect"):
        if json.dumps(a.scenario.raw.get(key), sort_keys=True, default=str) != json.dumps(
                b.scenario.raw.get(key), sort_keys=True, default=str) and not any(d.startswith(key) for d in diffs):
            diffs.append(f"{key}: flags or structure differ")
    return diffs


def ownership_comparison(owned: CostCase, leased: CostCase, distance: DistanceInput) -> ComparisonResult:
    for case, mode in ((owned, "owned"), (leased, "operating_lease")):
        if not case.is_costed:
            raise AnalyticsInputError(f"{case.label}: not costed ({case.origin})")
        if case.ownership_mode != mode:
            raise AnalyticsInputError(f"{case.label}: expected ownership mode {mode!r}, got {case.ownership_mode!r}")
    if owned.facts.flight_estimate_id != leased.facts.flight_estimate_id:
        raise AnalyticsInputError("ownership comparison needs the same flight estimate for both cases")
    result = compare_cases([owned, leased], distance, analysis_type="ownership_comparison")
    diffs = scenario_differences(owned, leased)
    if diffs:
        result.warnings.append("the scenarios differ beyond ownership inputs, so differences are not attributable to "
                               "ownership alone: " + "; ".join(diffs))
    result.explanation = list(OWNERSHIP_EXPLANATION)
    return result


def ownership_table(result: ComparisonResult) -> list[dict[str, Any]]:
    """Item-by-item owned vs leased table; not-applicable items are shown as n/a, never as zero."""
    owned, leased = (r.case for r in result.rows)
    items = [("maintenance", GROUPS["maintenance"]), ("crew", GROUPS["crew"]), ("insurance", ("insurance",)),
             ("lease_payment", ("operating_lease",)), ("depreciation", ("depreciation",)),
             ("financing_interest", ("financing_interest",))]
    table = []
    for item, names in items:
        a, b = group_amount(owned, names), group_amount(leased, names)

        def show(g: GroupAmount) -> str:
            if g.calculated is None:
                return "n/a (not applicable)" if not g.missing else "unavailable"
            return plain(g.calculated) + (" (partial)" if g.missing else "")
        diff = b.calculated - a.calculated if a.calculated is not None and b.calculated is not None else None
        table.append({"item": item, "owned": show(a), "operating_lease": show(b),
                      "difference_lease_minus_owned": None if diff is None else plain(diff)})
    for key, attr in (("COC (calculated subtotal)", "coc"), ("TOC (calculated subtotal)", "toc"),
                      ("Total costs (calculated subtotal)", "total")):
        a, b = getattr(owned.summary, attr), getattr(leased.summary, attr)
        same_cover = set(a[2]) == set(b[2])
        diff = b[0] - a[0] if a[0] is not None and b[0] is not None and same_cover else None
        table.append({"item": key, "owned": None if a[0] is None else plain(a[0]),
                      "operating_lease": None if b[0] is None else plain(b[0]),
                      "difference_lease_minus_owned": None if diff is None else plain(diff),
                      "note": "partial: excludes " + ", ".join(a[2]) if a[2] else "complete"})
    return table


__all__ = ["compare_cases", "ownership_comparison", "ownership_table", "group_amount", "GROUPS", "COMMON_LABEL",
           "Category"]
