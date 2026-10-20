"""Validate a saved full-cost estimate: arithmetic, operational, financial and external benchmark checks.

Example::

    python scripts/validate_cost_estimates.py --full-cost-estimate-id 1 --output data/output/validation.json

Checks that cannot run are reported as ``not_performed`` (never as passed).
External comparisons report comparable / comparable_with_caveats /
not_comparable with reasons; differences are not called model error.
Exit codes: 0 no failed check, 2 at least one failed check, 1 error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cli import open_database, reference_path
from aircraft_cost_model.analytics.persistence import RunRecord, save_run
from aircraft_cost_model.analytics.reporting import render_validation, write_csv, write_json
from aircraft_cost_model.analytics.validation import validate_estimate
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.models import FullCostEstimate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full-cost-estimate-id", type=int, required=True)
    parser.add_argument("--output", type=Path, help="JSON path (a CSV of checks is written next to it)")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)
    try:
        engine = open_database()
        with Session(engine) as session:
            result = validate_estimate(session, args.full_cost_estimate_id,
                                       reference_path("bts_aircraft_type_mapping.csv"))
            est = session.get(FullCostEstimate, args.full_cost_estimate_id)
            context = (est.flight_estimate_id, est.variable_cost_estimate_id, est.scenario_id, est.pricing_date,
                       est.reporting_currency, est.input_hash, est.operational_validity_status,
                       est.source_quality_summary, est.cost_coverage_status)
    except (CostCalculationError, ValueError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    print(render_validation(result))
    if args.output:
        print(f"wrote {write_json(result.to_dict(), args.output)}")
        print(f"wrote {write_csv([c.to_dict() for c in result.checks], args.output.with_suffix('.csv'))}")
    if args.save:
        flight, variable, scenario_id, pricing, currency, ihash, validity, quality, coverage = context
        outcome = save_run(engine, RunRecord(
            analysis_type="validation", status=result.status, parameters={"full_cost_estimate": ihash},
            result=result.to_dict(), coverage_status={"complete": "complete", "incomplete": "partial"}.get(
                coverage, "calculation_error"), source_quality_summary=quality, operational_validity=validity,
            flight_estimate_id=flight, variable_cost_estimate_id=variable,
            full_cost_estimate_id=args.full_cost_estimate_id, base_scenario_id=scenario_id, pricing_date=pricing,
            reporting_currency=currency), comparisons=result.benchmark_comparisons)
        print(outcome.describe())
    return 2 if result.status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
