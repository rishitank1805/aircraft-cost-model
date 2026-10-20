"""Full operating cost estimate for a saved flight + saved variable-cost estimate + cost scenario.

Example::

    python scripts/calculate_full_costs.py --flight-estimate-id 2 --variable-cost-estimate-id 2 \\
        --scenario data/scenarios/example_owned_aircraft.json --save

Unavailable amounts print as N/A, never zero. Results are economic cost
estimates under the scenario's assumptions, not airline accounting expense.
Exit codes: 0 success, 1 error.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.fullcost.aggregate import TAXONOMY, Category
from aircraft_cost_model.fullcost.calculator import FullCostResult, calculate_full_costs
from aircraft_cost_model.fullcost.persistence import save_full_cost_estimate
from aircraft_cost_model.fullcost.scenario import ScenarioError, load_scenario
from aircraft_cost_model.logging_config import configure_logging

TITLES = {
    Category.DIRECT_VARIABLE: "DIRECT VARIABLE COSTS", Category.DIRECT_FIXED: "DIRECT FIXED COSTS",
    Category.INDIRECT: "INDIRECT COSTS", Category.NONCASH: "NONCASH COSTS", Category.FINANCING: "FINANCING COSTS",
}


def _money(value: Decimal | None, currency: str) -> str:
    return "N/A" if value is None else f"{value:,.2f} {currency}"


def render(result: FullCostResult) -> str:
    s, b, cur = result.summary, result.basis, result.basis.reporting_currency
    qualities = s.source_qualities()
    lines = [
        "FULL AIRCRAFT OPERATING COST ESTIMATE  (economic cost scenario - not airline accounting expense)", "",
        f"Flight estimate {result.flight_estimate_id} ({b.aircraft_code}), variable-cost estimate "
        f"{result.variable_cost_estimate_id}, pricing date {b.pricing_date}, currency {cur}",
        f"Scenario: {result.scenario.name} [ownership: {result.scenario.ownership_mode}; flight type: "
        f"{result.scenario.flight_type}; hash {result.scenario.content_hash[:12]}]",
        f"Time bases: block {b.block_hours:.4f} h, airborne {b.airborne_hours:.4f} h, cycles {b.flight_cycles}, "
        f"engines {b.engine_count}",
    ]
    for category in Category:
        lines += ["", TITLES[category]]
        for name in TAXONOMY[category]:
            c = s.components[name]
            lines.append(f"  {name:<24} {_money(c.amount, cur):>16}   {c.status.value:<28} {qualities[name].value}")
            detail = c.missing_inputs[:3] if c.missing_inputs else [w for w in c.warnings if "not applicable" in w
                                                                      or c.status.value == "failed_validation"][:2]
            for item in detail:
                lines.append(f"      - {item}")
        cs = s.category(category)
        complete = "complete" if cs.is_complete else f"incomplete (missing: {', '.join(cs.missing_components)})"
        lines.append(f"  {'Calculated subtotal':<24} {_money(cs.calculated_subtotal, cur):>16}   {complete}")
    coc, toc, total = s.coc, s.toc, s.total
    counts = s.coverage_counts()
    lines += [
        "", "SUMMARY (calculated subtotals add calculated components only)",
        f"  Calculated Direct Variable Subtotal : {_money(s.category(Category.DIRECT_VARIABLE).calculated_subtotal, cur)}",
        f"  Calculated Direct Fixed Subtotal    : {_money(s.category(Category.DIRECT_FIXED).calculated_subtotal, cur)}",
        f"  Calculated Indirect Subtotal        : {_money(s.category(Category.INDIRECT).calculated_subtotal, cur)}",
        f"  Calculated Cash Operating Subtotal  : {_money(coc[0], cur)}",
        f"  Calculated Total Operating Subtotal : {_money(toc[0], cur)}",
        f"  Calculated Total Cost Subtotal      : {_money(total[0], cur)}",
        "",
        f"  Complete COC          : {_money(coc[1], cur) if coc[1] is not None else 'unavailable'}",
        f"  Complete TOC          : {_money(toc[1], cur) if toc[1] is not None else 'unavailable'}",
        f"  Complete Total Costs  : {_money(total[1], cur) if total[1] is not None else 'unavailable'}",
        "",
        f"  A. Cost coverage       : {s.cost_coverage_status} ({counts['calculated']} calculated, "
        f"{counts['not_applicable']} not applicable, {counts['missing_required_input']} missing input, "
        f"{counts['unavailable']} unavailable, {counts['failed_validation']} failed validation)",
        f"  B. Operational validity: {s.operational_validity} (from the Part 2 flight estimate; unchanged by costing)",
        f"  C. Source quality      : {s.source_quality_summary}",
        f"  Input hash             : {result.input_hash[:16]}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flight-estimate-id", type=int, required=True)
    parser.add_argument("--variable-cost-estimate-id", type=int, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging("WARNING" if settings.log_level == "INFO" else settings.log_level)
    if not settings.database_path.is_file():
        print(f"Database not found: {settings.database_path}")
        return 1
    try:
        scenario = load_scenario(args.scenario)
    except (ScenarioError, OSError) as exc:
        print(f"ERROR (scenario): {exc}")
        return 1
    migrate_database(settings.database_url)
    engine = create_db_engine(settings.database_url)
    try:
        with Session(engine) as session:
            result = calculate_full_costs(session, args.flight_estimate_id, args.variable_cost_estimate_id, scenario)
    except CostCalculationError as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    print(render(result))
    if args.save:
        print(f"\nSaved as full_cost_estimate_id={save_full_cost_estimate(engine, result)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
