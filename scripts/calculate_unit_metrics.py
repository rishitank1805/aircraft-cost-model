"""Unit operating-cost metrics (per block hour, NM, flight cycle, RTNM, ATNM) for one cost case.

Examples::

    python scripts/calculate_unit_metrics.py --full-cost-estimate-id 1 --distance-basis modelled_route
    python scripts/calculate_unit_metrics.py --full-cost-estimate-id 1 --distance-basis great_circle \\
        --revenue-payload-t 8 --hypothetical-cargo --payload-reference "analyst test value" --output-format json

Partial subtotals give *partial* unit costs and are labelled so; complete
metrics are shown only when the complete total exists. RTNM needs an explicit
revenue cargo payload (never the Part 2 modelled payload). Exit codes: 0 ok, 1 error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cli import (
    add_case_arguments,
    add_distance_payload_arguments,
    distance_from,
    open_database,
    payload_from,
    resolve_case,
)
from aircraft_cost_model.analytics.metrics import unit_metrics
from aircraft_cost_model.analytics.persistence import RunRecord, save_run
from aircraft_cost_model.analytics.reporting import render_unit_metrics, write_csv, write_json
from aircraft_cost_model.costs.exceptions import CostCalculationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_case_arguments(parser)
    add_distance_payload_arguments(parser)
    parser.add_argument("--output-format", choices=["console", "json", "csv"], default="console")
    parser.add_argument("--output", type=Path, help="file for json/csv output (printed to stdout if omitted)")
    parser.add_argument("--save", action="store_true", help="store an immutable analytics_run with the metrics")
    args = parser.parse_args(argv)
    try:
        engine = open_database()
        with Session(engine) as session:
            case = resolve_case(session, args)
            result = unit_metrics(case, distance_from(args), payload_from(args))
    except (CostCalculationError, ValueError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    if args.output_format == "console":
        print(render_unit_metrics(result))
    elif args.output_format == "json":
        if args.output:
            print(f"wrote {write_json(result.to_dict(), args.output)}")
        else:
            import json
            print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        rows = [m.to_dict() for m in result.metrics]
        if not args.output:
            print("ERROR: --output is required for csv")
            return 1
        print(f"wrote {write_csv(rows, args.output)}")
    if args.save:
        facts = case.facts
        outcome = save_run(engine, RunRecord(
            analysis_type="unit_metrics", status="calculated",
            parameters={"case": case.input_hash, "full_cost_estimate_id": case.full_cost_estimate_id,
                        "scenario_hash": case.scenario_hash, "distance": args.distance_basis,
                        "actual_distance_nm": str(args.actual_distance_nm), "payload": result.traffic.payload_basis,
                        "available_payload_t": str(args.available_payload_t)},
            result=result.to_dict(), coverage_status=result.cost_coverage, source_quality_summary=result.source_quality,
            operational_validity=result.operational_validity, flight_estimate_id=facts.flight_estimate_id,
            variable_cost_estimate_id=case.variable_cost_estimate_id, full_cost_estimate_id=case.full_cost_estimate_id,
            base_scenario_id=case.scenario_id, pricing_date=case.pricing_date,
            reporting_currency=case.summary.reporting_currency, distance_basis=args.distance_basis,
            payload_basis=result.traffic.payload_basis, warnings=result.warnings),
            metrics=[(case.label, facts.flight_estimate_id, m) for m in result.metrics])
        print(outcome.describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
