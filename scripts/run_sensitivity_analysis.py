"""One- or two-variable deterministic sensitivity analysis, recalculated through the Part 3/4 engines.

Examples::

    python scripts/run_sensitivity_analysis.py --full-cost-estimate-id 1 --distance-basis modelled_route \\
        --parameter fuel_price --percent-changes=-20,-10,0,10,20 --output data/output/fuel_sensitivity.csv
    python scripts/run_sensitivity_analysis.py --full-cost-estimate-id 1 --distance-basis modelled_route \\
        --parameter fuel_price --percent-changes=-10,0,10 \\
        --parameter2 annual_utilization --percent-changes2=-20,0,20 --output data/output/grid.csv

Levels are illustrative variation levels chosen by the user, not forecasts; a
grid is a set of deterministic scenario outcomes, not probabilities. Saved
estimates and scenario files are never modified. Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import AnalyticsInputError
from aircraft_cost_model.analytics.cli import (
    add_case_arguments,
    add_distance_payload_arguments,
    distance_from,
    open_database,
    payload_from,
)
from aircraft_cost_model.analytics.persistence import RunRecord, save_run
from aircraft_cost_model.analytics.reporting import chart_grid, chart_sensitivity, render_sensitivity, write_csv, write_json
from aircraft_cost_model.analytics.scenarios import PARAMETERS, BaseCase, base_from_saved, parse_levels
from aircraft_cost_model.analytics.sensitivity import one_way, two_way
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.fullcost.scenario import load_scenario


def _levels(args, suffix: str = "") -> tuple[str, list]:
    given = [(t, getattr(args, f"{t}_changes{suffix}" if t != "values" else f"values{suffix}"))
             for t in ("percent", "absolute", "values")]
    given = [(t, v) for t, v in given if v]
    if len(given) != 1:
        raise AnalyticsInputError(f"give exactly one of --percent-changes{suffix}, --absolute-changes{suffix}, "
                                  f"--values{suffix}")
    change_type, text = given[0]
    return ("value" if change_type == "values" else change_type), parse_levels(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_case_arguments(parser)
    add_distance_payload_arguments(parser)
    parser.add_argument("--parameter", required=True, choices=sorted(PARAMETERS))
    parser.add_argument("--percent-changes")
    parser.add_argument("--absolute-changes")
    parser.add_argument("--values")
    parser.add_argument("--parameter2", choices=sorted(PARAMETERS))
    parser.add_argument("--percent-changes2", dest="percent_changes2")
    parser.add_argument("--absolute-changes2", dest="absolute_changes2")
    parser.add_argument("--values2", dest="values2")
    parser.add_argument("--max-cells", type=int, default=100)
    parser.add_argument("--output", type=Path, help="CSV path (a JSON and a PNG chart are written next to it)")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)
    try:
        engine = open_database()
        with Session(engine) as session:
            if args.full_cost_estimate_id is not None:
                base = base_from_saved(session, args.full_cost_estimate_id, distance_from(args), payload_from(args))
            elif None not in (args.flight_estimate_id, args.variable_cost_estimate_id, args.scenario):
                base = BaseCase(args.flight_estimate_id, args.variable_cost_estimate_id, load_scenario(args.scenario),
                                distance_from(args), payload_from(args), label=args.scenario.name)
            else:
                raise AnalyticsInputError("give --full-cost-estimate-id or flight/variable/scenario")
            t1, l1 = _levels(args)
            if args.parameter2:
                t2, l2 = _levels(args, "2")
                result = two_way(session, base, (args.parameter, t1, l1), (args.parameter2, t2, l2), args.max_cells)
            else:
                result = one_way(session, base, args.parameter, t1, l1)
    except (CostCalculationError, ValueError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    print(render_sensitivity(result))
    if args.output:
        rows = [r.to_dict() for r in [result.base] + result.rows]
        print(f"wrote {write_csv(rows, args.output)}")
        print(f"wrote {write_json(result.to_dict(), args.output.with_suffix('.json'))}")
        chart = (chart_grid if args.parameter2 else chart_sensitivity)(result, args.output.with_suffix(".png"))
        print(f"wrote {chart}")
    if args.save:
        s = result.base.result.case.summary
        outcome = save_run(engine, RunRecord(
            analysis_type=result.analysis_type, status="calculated",
            parameters={"base_scenario_hash": base.scenario.content_hash, "flight": base.flight_estimate_id,
                        "variable": base.variable_cost_estimate_id, "full_cost_estimate_id": base.full_cost_estimate_id,
                        "levels": [r.label for r in result.rows], "distance": args.distance_basis,
                        "payload": str(args.revenue_payload_t)},
            result=result.to_dict(), coverage_status={"complete": "complete", "incomplete": "partial",
                                                      "failed_validation": "calculation_error"}[s.cost_coverage_status],
            source_quality_summary=s.source_quality_summary, operational_validity=s.operational_validity,
            flight_estimate_id=base.flight_estimate_id, variable_cost_estimate_id=base.variable_cost_estimate_id,
            full_cost_estimate_id=base.full_cost_estimate_id, base_scenario_id=base.base_scenario_id,
            pricing_date=result.base.result.case.pricing_date, reporting_currency=result.currency,
            distance_basis=args.distance_basis, warnings=[result.statement]),
            scenario_rows=result.rows)
        print(outcome.describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
