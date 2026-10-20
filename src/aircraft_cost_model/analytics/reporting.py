"""Console, CSV, JSON and PNG reporting for analytics results.

Chart rules: partial subtotals are drawn hatched and labelled PARTIAL;
unavailable components are listed as N/A with no bar (never as zero);
not-applicable components are listed as n/a; bars are coloured by source
quality; currency, unit, pricing date and coverage are in every title or
footnote; not-comparable benchmarks are shown as text, not bars.
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from aircraft_cost_model.analytics.cases import CostCase  # noqa: E402
from aircraft_cost_model.analytics.comparisons import COMMON_LABEL, ComparisonResult, ownership_table  # noqa: E402
from aircraft_cost_model.analytics.metrics import UnitMetricsResult  # noqa: E402
from aircraft_cost_model.analytics.sensitivity import SensitivityResult  # noqa: E402
from aircraft_cost_model.analytics.validation import ValidationResult  # noqa: E402
from aircraft_cost_model.costs.currency import plain  # noqa: E402
from aircraft_cost_model.fullcost.aggregate import TAXONOMY, Category, component_source_quality  # noqa: E402

QUALITY_COLOURS = {"observed_public_data": "#2b8cbe", "public_market_benchmark": "#41ab5d",
                   "public_financial_benchmark": "#807dba", "explicit_user_assumption": "#fd8d3c",
                   "modelled_estimate": "#969696", "mixed": "#fdd0a2", "none": "#ffffff"}


def money(value: Decimal | None, currency: str = "", places: int = 2) -> str:
    if value is None:
        return "N/A"
    q = Decimal(1).scaleb(-places)
    return f"{value.quantize(q):,} {currency}".strip()


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def _flatten(row: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}."))
        elif isinstance(v, (list, tuple)):
            out[key] = "; ".join(json.dumps(x, default=str) if isinstance(x, dict) else str(x) for x in v)
        else:
            out[key] = v
    return out


def write_csv(rows: Iterable[dict[str, Any]], path: Path) -> Path:
    flat = [_flatten(r) for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for r in flat:
        columns += [k for k in r if k not in columns]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for r in flat:
            writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})
    return path


def write_json(data: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def component_rows(case: CostCase) -> list[dict[str, Any]]:
    rows = []
    for category in Category:
        for name in TAXONOMY[category]:
            c = case.summary.components[name]
            rows.append({"category": category.value, "component": name,
                         "amount": None if c.amount is None else plain(c.amount), "currency": c.currency,
                         "status": c.status.value, "source_type": c.source_type.value,
                         "source_quality": component_source_quality(c).value,
                         "source_reference": c.source_reference, "pricing_date": c.pricing_date.isoformat()})
    return rows


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------

def render_unit_metrics(result: UnitMetricsResult, cost_bases: tuple[str, ...] = ("direct_variable", "coc", "toc",
                                                                                     "total_costs")) -> str:
    if result.facts is None:
        return f"{result.case_label}: {result.cost_coverage} - " + "; ".join(result.warnings)
    f, t = result.facts, result.traffic
    lines = [f"UNIT COST METRICS - {result.case_label}",
             f"Flight estimate {f.flight_estimate_id}: {f.aircraft_code} {f.origin}-{f.destination}; block "
             f"{f.block_hours.quantize(Decimal('0.0001'))} h; distance {t.distance_basis} "
             f"{t.distance_nm.quantize(Decimal('0.01')) if t.distance_nm is not None else 'N/A'} NM; 1 cycle",
             f"Payload: {t.payload_basis}; RTNM {t.rtnm.quantize(Decimal('0.01')) if t.rtnm is not None else 'unavailable'}",
             "", f"{'Metric':<46} {'Value':>16}  {'Status':<11} {'Coverage':<22} Source quality"]
    for m in result.metrics:
        if m.cost_basis not in cost_bases:
            continue
        value = "N/A" if m.metric_value is None else f"{m.metric_value.quantize(Decimal('0.0001')):,}"
        lines.append(f"{m.label:<46} {value:>16}  {m.metric_status:<11} {m.coverage_status:<22} {m.source_quality}")
    lines += ["", "Values are exact quotients shown to 4 decimals; 'Partial' metrics exclude unavailable components.",
              f"A. Cost coverage: {result.cost_coverage}   B. Operational validity: {result.operational_validity}   "
              f"C. Source quality: {result.source_quality}"]
    lines += [f"  ! {w}" for w in result.warnings]
    return "\n".join(lines)


def render_sensitivity(result: SensitivityResult) -> str:
    lines = [f"SENSITIVITY ({result.analysis_type}): {', '.join(result.parameters)}  [{result.currency}]",
             result.statement, "",
             f"{'Variation':<44} {'Fuel':>10} {'DV subtotal':>12} {'COC subtotal':>13} {'dCOC':>10} {'dCOC %':>8} "
             f"{'COC/BH':>10}  Coverage / affected"]
    base = result.base.outputs
    lines.append(f"{'base':<44} {money(base.get('fuel')):>10} {money(base.get('direct_variable')):>12} "
                 f"{money(base.get('coc')):>13} {'':>10} {'':>8} {money(base.get('coc_per_block_hour')):>10}")
    for row in result.rows:
        o, d = row.outputs, row.deltas
        if row.result.status != "calculated":
            lines.append(f"{row.label:<44} ERROR: {row.result.error}")
            continue
        dabs, dpct = d.get("coc", (None, None))
        cov = row.result.case.summary.cost_coverage_status
        lines.append(f"{row.label:<44} {money(o.get('fuel')):>10} {money(o.get('direct_variable')):>12} "
                     f"{money(o.get('coc')):>13} {money(dabs):>10} {money(dpct):>8} "
                     f"{money(o.get('coc_per_block_hour')):>10}  {cov}; {', '.join(row.components_affected) or '-'}")
    lines.append("Subtotals are PARTIAL calculated subtotals unless the coverage is complete.")
    return "\n".join(lines)


def render_comparison(result: ComparisonResult) -> str:
    lines = [f"COMPARISON ({result.analysis_type}) [{result.currency}]", ""]
    for r in result.rows:
        v = r.values
        if "coc" not in v:
            lines.append(f"- {v['label']}: {v['cost_coverage'].upper()} ({v.get('reason')})")
            continue
        lines.append(f"- {v['label']}: {v['aircraft']} {v['origin']}-{v['destination']} flight {v['flight_estimate_id']}, "
                     f"scenario {v['scenario']} ({v['ownership_mode']}), pricing {v['pricing_date']}, block "
                     f"{Decimal(v['block_hours']).quantize(Decimal('0.0001'))} h")
        for key in ("fuel_cost", "maintenance", "crew", "charges_and_handling", "insurance", "ownership", "indirect"):
            g = v[key]
            amount = g["calculated_subtotal"] or "N/A"
            note = (" n/a" if g["not_applicable"] and not g["calculated_subtotal"] and not g["missing"] else
                    f" (partial; missing {g['missing']})" if g["missing"] and g["calculated_subtotal"] else
                    " (unavailable)" if g["missing"] else "")
            lines.append(f"    {key:<22} {amount:>12}{note}")
        for key in ("coc", "toc", "total_costs"):
            lines.append(f"    {key.upper():<22} calculated subtotal {v[key]['calculated_subtotal'] or 'N/A'}; complete "
                         f"{v[key]['complete'] or 'unavailable'}")
        lines.append(f"    coverage {v['cost_coverage']}; validity {v['operational_validity']}; quality {v['source_quality']}")
    lines += ["", f"{COMMON_LABEL} (NOT a complete operating cost): components {result.common_components}"]
    lines += [f"    {k}: {money(s)}" for k, s in result.common_subtotals.items()]
    lines += [f"    excluded {k}: {why}" for k, why in result.excluded_from_common.items()]
    lines += [f"  ! {w}" for w in result.warnings] + [f"  * {e}" for e in result.explanation]
    if result.analysis_type == "ownership_comparison":
        lines += ["", f"{'Item':<36} {'Owned':>22} {'Operating lease':>22} {'Lease - owned':>14}"]
        for row in ownership_table(result):
            lines.append(f"{row['item']:<36} {str(row['owned']):>22} {str(row['operating_lease']):>22} "
                         f"{str(row['difference_lease_minus_owned'] or '-'):>14}")
    return "\n".join(lines)


def render_validation(result: ValidationResult) -> str:
    lines = [f"VALIDATION of full_cost_estimate {result.full_cost_estimate_id}: {result.status.upper()}",
             f"Counts: {result.counts()}", ""]
    for c in result.checks:
        lines.append(f"[{c.status:<13}] {c.category:<11} {c.name:<36} {c.detail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _footer(fig, text: str) -> None:
    fig.text(0.01, 0.01, text, fontsize=7, ha="left", va="bottom", wrap=True)


def chart_component_breakdown(case: CostCase, path: Path) -> Path:
    s = case.summary
    names = [n for c in Category for n in TAXONOMY[c]]
    fig, ax = plt.subplots(figsize=(10, 7))
    for i, name in enumerate(names):
        c = s.components[name]
        q = component_source_quality(c).value
        if c.is_calculated:
            ax.barh(i, float(c.amount), color=QUALITY_COLOURS.get(q.split(":")[0], "#cccccc"), edgecolor="black")
            ax.text(float(c.amount), i, f" {money(c.amount)}", va="center", fontsize=8)
        else:
            label = "n/a (not applicable)" if c.status.value == "not_applicable" else f"N/A - {c.status.value}"
            ax.text(0, i, f" {label}", va="center", fontsize=8, color="#b30000" if label.startswith("N/A") else "gray")
    ax.set_yticks(range(len(names)), names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel(f"{s.reporting_currency} per flight")
    cov = "available components only (PARTIAL)" if s.cost_coverage_status != "complete" else "complete"
    ax.set_title(f"Cost components - {case.label}\n{cov}; pricing date {case.pricing_date}", fontsize=10)
    handles = [plt.Rectangle((0, 0), 1, 1, color=v) for k, v in QUALITY_COLOURS.items() if k != "none"]
    ax.legend(handles, [k for k in QUALITY_COLOURS if k != "none"], fontsize=7, loc="lower right",
              title="source quality", title_fontsize=7)
    _footer(fig, f"Operational validity: {s.operational_validity}. Unavailable components are not drawn and are not "
                 "zero. Illustrative assumptions are not airline costs.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _subtotal_bars(ax, labels, values, partial, currency):
    for i, (v, p) in enumerate(zip(values, partial)):
        if v is None:
            ax.text(i, 0, "N/A", ha="center", va="bottom", color="#b30000")
            continue
        ax.bar(i, float(v), color="#c6dbef" if p else "#2171b5", hatch="//" if p else None, edgecolor="black")
        ax.text(i, float(v), f"{money(v)}\n{'PARTIAL' if p else 'complete'}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(labels)), labels, fontsize=8)
    ax.set_ylabel(f"{currency} per flight")


def chart_categories(case: CostCase, path: Path) -> Path:
    s = case.summary
    cats = [Category.DIRECT_VARIABLE, Category.DIRECT_FIXED, Category.INDIRECT, Category.NONCASH, Category.FINANCING]
    subs = [s.category(c) for c in cats]
    fig, ax = plt.subplots(figsize=(9, 5))
    _subtotal_bars(ax, [c.value for c in cats], [x.calculated_subtotal for x in subs],
                   [not x.is_complete for x in subs], s.reporting_currency)
    ax.set_title(f"Cost categories (calculated subtotals) - {case.label}\npricing date {case.pricing_date}", fontsize=10)
    _footer(fig, "Hatched = PARTIAL (missing: " + "; ".join(f"{x.category.value}: {', '.join(x.missing_components)}"
                                                         for x in subs if x.missing_components) + ")")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def chart_totals(case: CostCase, path: Path) -> Path:
    s = case.summary
    triples = [s.coc, s.toc, s.total]
    fig, ax = plt.subplots(figsize=(8, 5))
    _subtotal_bars(ax, ["COC", "TOC", "Total costs"], [t[0] for t in triples], [t[1] is None for t in triples],
                   s.reporting_currency)
    ax.set_title(f"COC, TOC and Total costs - {case.label}\n" + ("complete totals" if s.total[1] is not None else
                 "calculated subtotals only: complete totals UNAVAILABLE"), fontsize=10)
    _footer(fig, f"Missing: {', '.join(s.total[2]) or 'none'}. COC = DV + DF + indirect; TOC = COC + depreciation; "
                 "Total = TOC + financing (project taxonomy).")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def chart_sensitivity(result: SensitivityResult, path: Path, keys: tuple[str, ...] = ("coc", "toc", "total_costs")
                      ) -> Path:
    fig, ax = plt.subplots(figsize=(9, 5))
    rows = [r for r in result.rows if r.result.status == "calculated"]
    xs = [float(r.variations[0].change) for r in rows]
    for key in keys:
        ys = [r.outputs.get(key) for r in rows]
        if all(y is not None for y in ys):
            ax.plot(xs, [float(y) for y in ys], marker="o", label=f"{key.upper()} (calculated subtotal)")
    v0 = rows[0].variations[0] if rows else None
    unit = {"percent": "% change", "absolute": "absolute change", "value": "value"}[v0.change_type] if v0 else ""
    ax.set_xlabel(f"{result.parameters[0]} ({unit})")
    ax.set_ylabel(f"{result.currency} per flight")
    ax.legend(fontsize=8)
    coverage = {r.result.case.summary.cost_coverage_status for r in rows}
    ax.set_title(f"Sensitivity: {result.parameters[0]}\n" + ("PARTIAL subtotals (incomplete coverage)"
                 if "incomplete" in coverage else "complete coverage"), fontsize=10)
    _footer(fig, result.statement + " Illustrative variation levels.")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def chart_grid(result: SensitivityResult, path: Path, key: str = "coc") -> Path:
    p1, p2 = result.parameters
    l1 = sorted({r.variations[0].change for r in result.rows})
    l2 = sorted({r.variations[1].change for r in result.rows})
    grid = [[None] * len(l2) for _ in l1]
    for r in result.rows:
        grid[l1.index(r.variations[0].change)][l2.index(r.variations[1].change)] = r.outputs.get(key)
    fig, ax = plt.subplots(figsize=(8, 6))
    data = [[float(v) if v is not None else float("nan") for v in row] for row in grid]
    im = ax.imshow(data, cmap="viridis", aspect="auto")
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            ax.text(j, i, money(v, places=0), ha="center", va="center", fontsize=7, color="white")
    ax.set_xticks(range(len(l2)), [plain(x) for x in l2])
    ax.set_yticks(range(len(l1)), [plain(x) for x in l1])
    ax.set_xlabel(p2)
    ax.set_ylabel(p1)
    fig.colorbar(im, label=f"{key.upper()} calculated subtotal ({result.currency})")
    ax.set_title(f"Two-variable scenario grid: {p1} x {p2}", fontsize=10)
    _footer(fig, result.statement)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def chart_ownership(result: ComparisonResult, path: Path) -> Path:
    table = ownership_table(result)
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, row in enumerate(table):
        for offset, key, colour in ((-0.2, "owned", "#6baed6"), (0.2, "operating_lease", "#fd8d3c")):
            value = row[key]
            try:
                number = float(str(value).split()[0])
            except (TypeError, ValueError):
                ax.text(i + offset, 0, str(value).split(" (")[0], rotation=90, fontsize=7, ha="center", va="bottom")
                continue
            ax.bar(i + offset, number, width=0.4, color=colour, edgecolor="black",
                   hatch="//" if "partial" in str(value) or "subtotal" in row["item"] else None)
    ax.set_xticks(range(len(table)), [r["item"].replace(" (calculated subtotal)", "*") for r in table], fontsize=7,
                  rotation=20)
    ax.legend(["owned", "operating lease"], fontsize=8)
    ax.set_ylabel(f"{result.currency} per flight")
    ax.set_title("Owned vs operating lease (project taxonomy, not IFRS 16)", fontsize=10)
    _footer(fig, "* calculated subtotals; hatched = partial. n/a = not applicable under the ownership mode (not zero).")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def chart_comparison(result: ComparisonResult, path: Path) -> Path:
    costed = [r for r in result.rows if "coc" in r.values]
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [r.values["label"] for r in costed]
    partial = [Decimal(r.values["coc"]["calculated_subtotal"]) if r.values["coc"]["calculated_subtotal"] else None
               for r in costed]
    common = [result.common_subtotals.get(label) for label in labels]
    for i, (p, c) in enumerate(zip(partial, common)):
        if p is not None:
            ax.bar(i - 0.2, float(p), width=0.4, color="#c6dbef", hatch="//", edgecolor="black")
        if c is not None:
            ax.bar(i + 0.2, float(c), width=0.4, color="#238b45", edgecolor="black")
    ax.set_xticks(range(len(labels)), labels, fontsize=7, rotation=15)
    ax.legend(["COC calculated subtotal (partial)", COMMON_LABEL], fontsize=8)
    ax.set_ylabel(f"{result.currency} per flight")
    unsupported = [r.values["label"] for r in result.rows if "coc" not in r.values]
    ax.set_title("Route / aircraft / scenario comparison" + (f"\nunsupported or missing: {unsupported}"
                                                             if unsupported else ""), fontsize=10)
    _footer(fig, ("COVERAGE MISMATCH - partial subtotals not directly comparable. " if result.coverage_mismatch else "")
            + f"{COMMON_LABEL}: {result.common_components}")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def chart_benchmarks(comparisons: list, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    shown = [c for c in comparisons if c.comparability != "not_comparable"]
    for i, c in enumerate(shown):
        ax.bar(i - 0.2, float(c.model_value), width=0.4, color="#fd8d3c", edgecolor="black")
        ax.bar(i + 0.2, float(c.benchmark_value_converted), width=0.4, color="#807dba", edgecolor="black")
        pct = f"{c.percentage_difference.quantize(Decimal('0.1'))}%" if c.percentage_difference is not None else "-"
        ax.text(i, max(float(c.model_value), float(c.benchmark_value_converted)), f"{c.comparability}\ndiff {pct}",
                ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(len(shown)), [f"{c.model_metric}\n{c.benchmark.selection.source}" for c in shown], fontsize=7)
    ax.set_xlim(-0.8, max(len(shown), 2) - 0.2)
    ax.legend(["model", "benchmark (converted)"], fontsize=8)
    ax.set_ylabel(shown[0].model_unit if shown else "")
    not_comp = [f"{c.model_metric} vs {c.benchmark.selection.source}" for c in comparisons
                if c.comparability == "not_comparable"]
    ax.set_title("External benchmark comparison (differences, not model error)", fontsize=10)
    _footer(fig, f"Not comparable (no bars): {len(not_comp)} - " + "; ".join(not_comp[:8]))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
