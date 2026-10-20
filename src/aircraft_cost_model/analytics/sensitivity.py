"""One- and two-variable deterministic sensitivity analysis.

Each level is a full recalculation through :func:`run_variation` (Part 3 fuel
engine and/or Part 4 calculator); totals are never scaled directly.

Deltas against the base run:

- absolute change = varied value - base value (same currency/unit);
- percent change  = absolute change / base value x 100, computed only when
  the base value exists and is non-zero;
- totals are compared only when base and variant include the same calculated
  components; otherwise the delta is withheld and ``coverage_changed`` is set.

The levels are illustrative variation levels chosen by the user, not
forecasts; a two-variable grid is a set of deterministic scenario outcomes,
not a probability distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import product
from typing import Any

from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import AnalyticsInputError
from aircraft_cost_model.analytics.scenarios import BaseCase, Variation, VariationResult, run_variation
from aircraft_cost_model.costs.currency import plain
from aircraft_cost_model.fullcost.aggregate import TAXONOMY, Category

MAX_GRID_CELLS = 400
DEFAULT_GRID_CELLS = 100
SCENARIO_STATEMENT = ("Deterministic scenario outcomes for user-chosen input levels; not forecasts and not "
                      "probability estimates.")
TOTAL_KEYS = {"direct_variable": (Category.DIRECT_VARIABLE,),
              "coc": (Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT),
              "toc": (Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT, Category.NONCASH),
              "total_costs": tuple(Category)}
METRIC_KEYS = ("coc_per_block_hour", "coc_per_nautical_mile", "coc_per_revenue_tonne_nm")


@dataclass
class SensitivityRow:
    label: str
    variations: tuple[Variation, ...]
    result: VariationResult
    outputs: dict[str, Decimal | None]
    deltas: dict[str, tuple[Decimal | None, Decimal | None]]
    components_affected: list[str]
    coverage_changed: list[str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def s(v):
            return None if v is None else plain(v)
        s_ = self.result.case.summary if self.result.case else None
        return {"label": self.label, "variations": [v.to_dict() for v in self.variations],
                "status": self.result.status, "error": self.result.error,
                "outputs": {k: s(v) for k, v in self.outputs.items()},
                "delta_abs": {k: s(v[0]) for k, v in self.deltas.items()},
                "delta_pct": {k: s(v[1]) for k, v in self.deltas.items()},
                "components_affected": self.components_affected, "coverage_changed": self.coverage_changed,
                "cost_coverage": s_.cost_coverage_status if s_ else "calculation_error",
                "operational_validity": s_.operational_validity if s_ else None,
                "source_quality": s_.source_quality_summary if s_ else None,
                "modified": [m.to_dict() for m in self.result.modified], "notes": self.notes,
                "warnings": self.result.warnings}


@dataclass
class SensitivityResult:
    analysis_type: str  # sensitivity_1d | sensitivity_2d
    parameters: tuple[str, ...]
    base: SensitivityRow
    rows: list[SensitivityRow]
    currency: str
    statement: str = SCENARIO_STATEMENT

    def to_dict(self) -> dict[str, Any]:
        return {"analysis_type": self.analysis_type, "parameters": list(self.parameters), "currency": self.currency,
                "statement": self.statement, "base": self.base.to_dict(), "rows": [r.to_dict() for r in self.rows]}


def _included(result: VariationResult, categories: tuple[Category, ...]) -> frozenset[str]:
    comps = result.case.summary.components
    return frozenset(n for c in categories for n in TAXONOMY[c] if comps[n].is_calculated)


def _outputs(result: VariationResult) -> dict[str, Decimal | None]:
    if result.case is None:
        return {}
    out: dict[str, Decimal | None] = {"fuel": result.case.summary.components["fuel"].amount}
    out.update(result.totals())
    for key in METRIC_KEYS:
        out[key] = result.metrics.metric(key).metric_value if result.metrics else None
    return out


def _row(label: str, variations: tuple[Variation, ...], result: VariationResult, base: VariationResult | None
         ) -> SensitivityRow:
    outputs = _outputs(result)
    deltas: dict[str, tuple[Decimal | None, Decimal | None]] = {}
    affected: list[str] = []
    changed: list[str] = []
    notes: list[str] = []
    if base is not None and result.case is not None and base.case is not None:
        base_out = _outputs(base)
        b_comp, n_comp = base.component_amounts(), result.component_amounts()
        affected = sorted(n for n in n_comp if n_comp[n] != b_comp.get(n)
                          or result.case.summary.components[n].status != base.case.summary.components[n].status)
        for key, value in outputs.items():
            categories = TOTAL_KEYS.get(key.replace("complete_", ""))
            if categories is None and key in METRIC_KEYS:
                categories = TOTAL_KEYS["coc"]
            if categories is not None and _included(result, categories) != _included(base, categories):
                changed.append(key)
                deltas[key] = (None, None)
                continue
            b = base_out.get(key)
            if value is None or b is None:
                deltas[key] = (None, None)
                continue
            diff = value - b
            deltas[key] = (diff, diff / b * 100 if b != 0 else None)
            if b == 0:
                notes.append(f"{key}: base is zero, no percent change")
    return SensitivityRow(label, variations, result, outputs, deltas, affected, changed, notes)


def one_way(session: Session, base: BaseCase, parameter: str, change_type: str, levels: list[Decimal]
            ) -> SensitivityResult:
    """One variable at a time: one recalculation per level (identity levels reproduce the base)."""
    base_result = run_variation(session, base, (), label="base")
    if base_result.status != "calculated":
        raise AnalyticsInputError(f"base case cannot be calculated: {base_result.error}")
    base_row = _row("base", (), base_result, None)
    rows = []
    for level in levels:
        variation = Variation(parameter, change_type, level)
        result = run_variation(session, base, (variation,))
        rows.append(_row(variation.label(), (variation,), result, base_result))
    return SensitivityResult("sensitivity_1d", (parameter,), base_row, rows,
                             base_result.case.summary.reporting_currency)


def two_way(session: Session, base: BaseCase, first: tuple[str, str, list[Decimal]],
            second: tuple[str, str, list[Decimal]], max_cells: int = DEFAULT_GRID_CELLS) -> SensitivityResult:
    """A user-chosen grid of two parameters (bounded; no exhaustive search)."""
    (p1, t1, l1), (p2, t2, l2) = first, second
    if p1 == p2:
        raise AnalyticsInputError("a two-variable grid needs two different parameters")
    cells = len(l1) * len(l2)
    if cells > min(max_cells, MAX_GRID_CELLS):
        raise AnalyticsInputError(f"grid has {cells} cells; the limit is {min(max_cells, MAX_GRID_CELLS)}")
    base_result = run_variation(session, base, (), label="base")
    if base_result.status != "calculated":
        raise AnalyticsInputError(f"base case cannot be calculated: {base_result.error}")
    rows = []
    for a, b in product(l1, l2):
        variations = (Variation(p1, t1, a), Variation(p2, t2, b))
        result = run_variation(session, base, variations)
        rows.append(_row(" & ".join(v.label() for v in variations), variations, result, base_result))
    return SensitivityResult("sensitivity_2d", (p1, p2), _row("base", (), base_result, None), rows,
                             base_result.case.summary.reporting_currency)
