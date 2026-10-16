"""Generate an analytical report (console text, CSV, JSON, PNG) for one saved full-cost estimate.

Example::

    python scripts/generate_cost_report.py --full-cost-estimate-id 1 --distance-basis modelled_route \\
        --ownership-scenario data/scenarios/example_operating_lease.json --output-dir data/output/reports/example

Contents: unit metrics; component, category and COC/TOC/Total charts; fuel
price, maintenance rate and utilization sensitivities (where the parameter
applies); optional owned-vs-leased and route/aircraft comparisons;
validation with external benchmark comparisons; ``manifest.json`` with the
SHA-256 of every file. Nothing is written to the database unless --save.
Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from aircraft_cost_model.analytics import ANALYTICS_VERSION
from aircraft_cost_model.analytics.cases import AnalyticsInputError, calculate_case, load_saved_case
from aircraft_cost_model.analytics.cli import (
    add_distance_payload_arguments,
    distance_from,
    open_database,
    payload_from,
    reference_path,
)
from aircraft_cost_model.analytics.comparisons import compare_cases, ownership_comparison, ownership_table
from aircraft_cost_model.analytics.metrics import unit_metrics
from aircraft_cost_model.analytics.reporting import (
    chart_benchmarks,
    chart_categories,
    chart_comparison,
    chart_component_breakdown,
    chart_ownership,
    chart_sensitivity,
    chart_totals,
    component_rows,
    render_comparison,
    render_sensitivity,
    render_unit_metrics,
    render_validation,
    write_csv,
    write_json,
)
from aircraft_cost_model.analytics.scenarios import base_from_saved, matching_paths
from aircraft_cost_model.analytics.sensitivity import one_way
from aircraft_cost_model.analytics.validation import validate_estimate
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.fullcost.scenario import load_scenario

SENSITIVITIES = (
    ("fuel_price", "percent", [Decimal(x) for x in ("-20", "-10", "0", "10", "20")]),
    ("airframe_maintenance_rate", "percent", [Decimal(x) for x in ("-20", "-10", "0", "10", "20")]),
    ("annual_utilization", "percent", [Decimal(x) for x in ("-20", "-10", "0", "10", "20")]),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full-cost-estimate-id", type=int, required=True)
    add_distance_payload_arguments(parser)
    parser.add_argument("--ownership-scenario", type=Path,
                        help="scenario with the other ownership mode, priced on the same flight for owned vs leased")
    parser.add_argument("--compare-full-cost-estimate-ids", type=int, nargs="*", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    out: Path = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    text: list[str] = []
    files: list[Path] = []
    try:
        engine = open_database()
        with Session(engine) as session:
            case = load_saved_case(session, args.full_cost_estimate_id)
            distance, payload = distance_from(args), payload_from(args)
            metrics = unit_metrics(case, distance, payload)
            text.append(render_unit_metrics(metrics))
            files += [write_json(metrics.to_dict(), out / "unit_metrics.json"),
                      write_csv([m.to_dict() for m in metrics.metrics], out / "unit_metrics.csv"),
                      write_csv(component_rows(case), out / "components.csv"),
                      chart_component_breakdown(case, out / "01_component_breakdown.png"),
                      chart_categories(case, out / "02_categories.png"),
                      chart_totals(case, out / "03_coc_toc_total.png")]
            base = base_from_saved(session, args.full_cost_estimate_id, distance, payload)
            for i, (parameter, change_type, levels) in enumerate(SENSITIVITIES, start=4):
                if parameter != "fuel_price" and not matching_paths(base.scenario, parameter):
                    text.append(f"\nSENSITIVITY {parameter}: not applicable to this scenario (input not present)")
                    continue
                result = one_way(session, base, parameter, change_type, levels)
                text.append("\n" + render_sensitivity(result))
                files += [write_csv([r.to_dict() for r in [result.base] + result.rows],
                                    out / f"sensitivity_{parameter}.csv"),
                          write_json(result.to_dict(), out / f"sensitivity_{parameter}.json"),
                          chart_sensitivity(result, out / f"{i:02d}_sensitivity_{parameter}.png")]
            if args.ownership_scenario:
                other, _ = calculate_case(session, case.facts.flight_estimate_id, case.variable_cost_estimate_id,
                                          load_scenario(args.ownership_scenario), label=args.ownership_scenario.stem)
                owned, leased = sorted([case, other], key=lambda c: c.ownership_mode != "owned")
                own = ownership_comparison(owned, leased, distance)
                text.append("\n" + render_comparison(own))
                files += [write_json(own.to_dict(), out / "ownership_comparison.json"),
                          write_csv(ownership_table(own), out / "ownership_table.csv"),
                          chart_ownership(own, out / "07_owned_vs_leased.png")]
            if args.compare_full_cost_estimate_ids:
                others = [load_saved_case(session, i) for i in args.compare_full_cost_estimate_ids]
                comparison = compare_cases([case] + others, distance)
                text.append("\n" + render_comparison(comparison))
                files += [write_json(comparison.to_dict(), out / "comparison.json"),
                          write_csv([r.values for r in comparison.rows], out / "comparison.csv"),
                          chart_comparison(comparison, out / "08_comparison.png")]
            validation = validate_estimate(session, args.full_cost_estimate_id,
                                           reference_path("bts_aircraft_type_mapping.csv"))
            text.append("\n" + render_validation(validation))
            files += [write_json(validation.to_dict(), out / "validation.json"),
                      write_csv([c.to_dict() for c in validation.checks], out / "validation_checks.csv"),
                      write_csv([b.to_dict() for b in validation.benchmark_comparisons],
                                out / "benchmark_comparisons.csv"),
                      chart_benchmarks(validation.benchmark_comparisons, out / "09_benchmark_comparison.png")]
    except (CostCalculationError, ValueError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    report = out / "report.txt"
    report.write_text("\n".join(text) + "\n", encoding="utf-8")
    files.append(report)
    manifest = {"analytics_version": ANALYTICS_VERSION, "full_cost_estimate_id": args.full_cost_estimate_id,
                "full_cost_input_hash": case.input_hash, "distance_basis": args.distance_basis,
                "payload": metrics.traffic.payload_basis,
                "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    write_json(manifest, out / "manifest.json")
    print("\n".join(text))
    print(f"\nWrote {len(files) + 1} files to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
