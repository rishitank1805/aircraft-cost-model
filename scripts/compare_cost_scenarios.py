"""Compare cost scenarios, routes or supported aircraft; or owned vs operating lease.

Examples::

    # several scenarios for one flight (owned vs lease gets the ownership report with --ownership)
    python scripts/compare_cost_scenarios.py --flight-estimate-id 2 --variable-cost-estimate-id 2 \\
        --scenario-files data/scenarios/example_owned_aircraft.json data/scenarios/example_operating_lease.json \\
        --distance-basis modelled_route --ownership
    # saved full-cost estimates (any flights)
    python scripts/compare_cost_scenarios.py --full-cost-estimate-ids 1 2 --distance-basis great_circle
    # aircraft x route cases resolved from saved estimates; unsupported freighters return an explicit row
    python scripts/compare_cost_scenarios.py --route-case A320:FRA:CDG --route-case B777F:FRA:CDG \\
        --pricing-date 2025-01-15 --scenario data/scenarios/example_owned_aircraft.json --distance-basis great_circle

Partial subtotals with different component coverage are flagged; the
``common_component_comparison`` uses only components calculated and
identically defined in every case and is never a complete operating cost.
Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import AnalyticsInputError, calculate_case, find_route_case, load_saved_case
from aircraft_cost_model.analytics.cli import open_database
from aircraft_cost_model.analytics.comparisons import compare_cases, ownership_comparison, ownership_table
from aircraft_cost_model.analytics.metrics import DistanceBasis, DistanceInput
from aircraft_cost_model.analytics.persistence import RunRecord, save_run
from aircraft_cost_model.analytics.reporting import (
    chart_comparison,
    chart_ownership,
    render_comparison,
    write_csv,
    write_json,
)
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.fullcost.scenario import load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flight-estimate-id", type=int)
    parser.add_argument("--variable-cost-estimate-id", type=int)
    parser.add_argument("--scenario-files", type=Path, nargs="+")
    parser.add_argument("--full-cost-estimate-ids", type=int, nargs="+")
    parser.add_argument("--route-case", action="append", default=[], help="AIRCRAFT:ORIGIN:DESTINATION")
    parser.add_argument("--pricing-date", type=date.fromisoformat)
    parser.add_argument("--currency", default=None, help="reporting currency for --route-case (required with it)")
    parser.add_argument("--scenario", type=Path, help="scenario for --route-case")
    parser.add_argument("--distance-basis", required=True, choices=[b.value for b in DistanceBasis
                                                                    if b != DistanceBasis.ACTUAL_FLOWN])
    parser.add_argument("--ownership", action="store_true", help="owned vs operating lease report (two scenarios)")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)
    distance = DistanceInput(DistanceBasis(args.distance_basis))
    try:
        engine = open_database()
        with Session(engine) as session:
            cases = []
            if args.scenario_files:
                if None in (args.flight_estimate_id, args.variable_cost_estimate_id):
                    raise AnalyticsInputError("--scenario-files needs --flight-estimate-id and --variable-cost-estimate-id")
                for path in args.scenario_files:
                    case, _ = calculate_case(session, args.flight_estimate_id, args.variable_cost_estimate_id,
                                             load_scenario(path), label=path.stem)
                    cases.append(case)
            for estimate_id in args.full_cost_estimate_ids or []:
                cases.append(load_saved_case(session, estimate_id))
            if args.route_case:
                if args.pricing_date is None or args.scenario is None or args.currency is None:
                    raise AnalyticsInputError("--route-case needs --pricing-date, --currency and --scenario")
                scenario = load_scenario(args.scenario)
                for spec in args.route_case:
                    aircraft, origin, destination = spec.split(":")
                    cases.append(find_route_case(session, aircraft, origin, destination, args.pricing_date,
                                                 args.currency, scenario))
            if args.ownership:
                if len(cases) != 2:
                    raise AnalyticsInputError("--ownership compares exactly two cases (owned, operating_lease)")
                owned, leased = sorted(cases, key=lambda c: c.ownership_mode != "owned")
                result = ownership_comparison(owned, leased, distance)
            else:
                result = compare_cases(cases, distance)
    except (CostCalculationError, ValueError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    print(render_comparison(result))
    if args.output_dir:
        name = result.analysis_type
        print(f"wrote {write_csv([r.values for r in result.rows], args.output_dir / f'{name}.csv')}")
        print(f"wrote {write_json(result.to_dict(), args.output_dir / f'{name}.json')}")
        if args.ownership:
            print(f"wrote {write_csv(ownership_table(result), args.output_dir / 'ownership_table.csv')}")
            print(f"wrote {chart_ownership(result, args.output_dir / 'owned_vs_leased.png')}")
        else:
            print(f"wrote {chart_comparison(result, args.output_dir / 'comparison.png')}")
    if args.save:
        costed = [c for c in cases if c.is_costed]
        outcome = save_run(engine, RunRecord(
            analysis_type=result.analysis_type, status="calculated",
            parameters={"cases": [[c.label, c.input_hash, c.origin, c.aircraft_code] for c in cases],
                        "distance": args.distance_basis},
            result=result.to_dict(),
            coverage_status="complete" if result.complete_totals_comparable else "partial",
            source_quality_summary="; ".join(sorted({c.summary.source_quality_summary for c in costed}))[:200],
            reporting_currency=result.currency, distance_basis=args.distance_basis, warnings=result.warnings))
        print(outcome.describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
