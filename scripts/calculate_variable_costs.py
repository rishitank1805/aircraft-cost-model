"""Price the variable costs (fuel, navigation, landing, ground handling) of a saved flight estimate.

Example::

    python scripts/calculate_variable_costs.py --flight-estimate-id 2 --pricing-date 2025-01-15 --currency EUR --save

Optional explicit inputs (never invented by the tool):

    --nav-zone GERMANY:260:1:0 --nav-zone FRANCE:240:0:1     zone:great-circle km:take-offs:landings
    --certificated-mtow-kg 78000                              AFM certificated MTOW (route and terminal charges)
    --type-level-mtow-scenario                                 SCENARIO: use OpenAP type-level MTOW instead
    --tariff-param FRA:noise_category_takeoff=4               airport tariff inputs (repeatable)
    --handling-param FRA:uld_count=10                          handling chargeable quantities
    --handling-assumption FRA:850:EUR                          user-supplied handling price (scenario)

Unavailable amounts are shown as N/A. Exit codes: 0 success, 1 error.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from aircraft_cost_model.config import get_settings
from aircraft_cost_model.costs.calculator import VariableCostRequest, VariableCostResult, calculate_variable_costs
from aircraft_cost_model.costs.coverage import ComponentName, ComponentResult
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.costs.handling_cost import HandlingAssumption
from aircraft_cost_model.costs.navigation_cost import ZoneSegment
from aircraft_cost_model.costs.persistence import save_variable_cost_estimate
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.logging_config import configure_logging


def _money(value: Decimal | None, currency: str) -> str:
    return "N/A" if value is None else f"{value:,.2f} {currency}"


def _parse_zone(text: str) -> ZoneSegment:
    try:
        zone, km, takeoffs, landings = text.split(":")
        return ZoneSegment(zone.strip().upper(), Decimal(km), int(takeoffs), int(landings))
    except (ValueError, InvalidOperation) as exc:
        raise argparse.ArgumentTypeError(f"--nav-zone must be ZONE:KM:TAKEOFFS:LANDINGS, got {text!r}") from exc


def _parse_params(items: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in items:
        airport, _, pair = item.partition(":")
        key, sep, value = pair.partition("=")
        if not airport or not sep:
            raise argparse.ArgumentTypeError(f"expected AIRPORT:key=value, got {item!r}")
        out.setdefault(airport.strip().upper(), {})[key.strip()] = value.strip()
    return out


def _parse_assumptions(items: list[str]) -> dict[str, HandlingAssumption]:
    out = {}
    for item in items:
        try:
            airport, amount, currency = item.split(":")
            out[airport.strip().upper()] = HandlingAssumption(Decimal(amount), currency.strip().upper())
        except (ValueError, InvalidOperation) as exc:
            raise argparse.ArgumentTypeError(f"--handling-assumption must be AIRPORT:AMOUNT:CURRENCY, got {item!r}") from exc
    return out


def _section(component: ComponentResult, lines: list[str]) -> None:
    lines.append(f"  Status:                   {component.status.value}"
                 + ("  [partial scope]" if component.partial_scope else ""))
    if component.missing_inputs:
        lines.append(f"  Missing inputs:           {', '.join(component.missing_inputs)}")
    for warning in component.warnings:
        lines.append(f"  ! {warning}")


def render(result: VariableCostResult) -> str:
    s = result.summary
    cur = s.reporting_currency
    fuel, nav, terminal, landing, handling = (result.component(n) for n in
                                              (ComponentName.FUEL, ComponentName.NAVIGATION,
                                               ComponentName.TERMINAL_NAVIGATION, ComponentName.LANDING,
                                               ComponentName.GROUND_HANDLING))
    f = result.flight
    lines = ["VARIABLE AIRCRAFT OPERATING COST ESTIMATE  (public benchmarks/tariffs; not an airline's actual costs)", "",
             "FLIGHT",
             f"  Aircraft:                 {f.aircraft_code} ({f.aircraft_description})",
             f"  Origin:                   {f.origin.code} {f.origin.name}",
             f"  Destination:              {f.destination.code} {f.destination.name}",
             f"  Flight estimate ID:       {f.flight_estimate_id} (fuel accounting {f.fuel_accounting_basis})",
             f"  Pricing date:             {s.pricing_date.isoformat()}",
             f"  Reporting currency:       {cur}", "", "FUEL",
             f"  Block fuel:               {f.block_fuel_kg:,.1f} kg"]
    price = next((b for b in fuel.breakdown if b.get("step") == "price"), None)
    if price:
        lines += [f"  Fuel benchmark:           {price['series']} {price['value']} {price['unit']} ({price['observation_period']})",
                  f"  Price observation date:   {price['observation_date']} (gap {price['gap_days']} days)"]
        for b in fuel.breakdown:
            if b.get("step") in ("kg -> L", "L -> US gal", "cost in price currency") or (
                    " -> " in str(b.get("step", "")) and "operation" in b):
                lines.append(f"    {b['step']:<10} {b.get('formula') or b.get('operation')}: {b.get('value') or b.get('result')}")
    lines.append(f"  Fuel cost:                {_money(fuel.amount, cur)}")
    _section(fuel, lines)
    lines += ["", "NAVIGATION (EUROCONTROL en-route charges)"]
    zones = [b for b in nav.breakdown if "zone" in b]
    if zones:
        wf = nav.breakdown[0]
        lines.append(f"  Weight factor:            {wf.get('value')} = {wf.get('formula')}, MTOW {wf.get('mtow_t')} t "
                     f"(if truncated: {wf.get('alternative_if_truncated')})")
        for z in zones:
            lines.append(f"  {z['zone']:<20} d={z['distance_factor']} x t={z['unit_rate']} {z['rate_currency']}"
                         f" (valid from {z['rate_valid_from']}) = {Decimal(z['charge']):,.2f}")
    elif result.request.nav_segments:
        for seg in result.request.nav_segments:
            lines.append(f"  {seg.zone:<20} {seg.great_circle_km} km, take-offs {seg.takeoffs}, landings {seg.landings}"
                         " (supplied; not priced)")
    else:
        lines.append("  Charging zones:           none supplied")
    lines.append(f"  Navigation cost:          {_money(nav.amount, cur)}")
    _section(nav, lines)
    lines += ["", "TERMINAL NAVIGATION (approach/departure charges)"]
    for part in terminal.breakdown:
        inner = (part.get("breakdown") or [{}])[0]
        detail = ""
        if inner.get("zone"):
            detail = f"zone {inner['zone']} (charged on {inner.get('charged_movement')})"
            if inner.get("unit_rate"):
                detail += f", t={inner['unit_rate']} x N={inner.get('value')} (if truncated: {inner.get('alternative_if_truncated')})"
        lines.append(f"  {part.get('part') or '':<16} {part['status']:<28} "
                     f"{_money(Decimal(part['amount']) if part.get('amount') is not None else None, cur):>14}  {detail}")
    lines.append(f"  Terminal charge:          {_money(terminal.amount, cur)}")
    _section(terminal, lines)
    lines += ["", "LANDING (airport movement charges: origin take-off + destination landing)"]
    for part in landing.breakdown:
        lines.append(f"  {part.get('part') or '':<16} {part['status']:<28} {_money(Decimal(part['amount']) if part.get('amount') is not None else None, cur)}"
                     + (f"  tariff {part.get('calculation_method')} from {part.get('observation_date')}" if part.get('amount') is not None else ""))
    lines.append(f"  Landing charge:           {_money(landing.amount, cur)}")
    _section(landing, lines)
    lines += ["", "GROUND HANDLING"]
    for part in handling.breakdown:
        lines.append(f"  {part.get('part') or '':<16} {part['status']:<28} {_money(Decimal(part['amount']) if part.get('amount') is not None else None, cur)}")
    lines.append(f"  Handling cost:            {_money(handling.amount, cur)}")
    _section(handling, lines)
    lines += ["", "SUMMARY"]
    for component in s.components:
        lines.append(f"  {component.component:<17} {_money(component.amount, cur):>18}   {component.status.value}")
    counts = s.counts_by_category()
    lines += [
        "",
        f"  Calculated Component Subtotal: {_money(s.calculated_subtotal, cur)}"
        + ("  (sum of calculated components only - NOT total variable cost)" if not s.is_complete else ""),
        f"  Complete Variable Cost:        {_money(s.complete_variable_cost, cur) if s.is_complete else 'unavailable'}",
        f"  Coverage:                      {s.coverage_label()} ({s.coverage_status}); a count, not a share of cost",
        f"    public tariff {counts['public_tariff']}, public benchmark {counts['public_benchmark']}, "
        f"assumption {counts['assumption']}, unavailable {counts['unavailable']}, not applicable {counts['not_applicable']}",
        f"  Unresolved interpretations:    {', '.join(s.unresolved_interpretations) or 'none'}",
        f"  Input hash:                    {result.input_hash[:16]}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flight-estimate-id", type=int, required=True)
    parser.add_argument("--pricing-date", type=date.fromisoformat, required=True, help="ISO 8601, e.g. 2025-01-15")
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--fuel-density-kg-per-l", type=Decimal)
    parser.add_argument("--max-fuel-price-staleness-days", type=int, default=7)
    parser.add_argument("--max-fx-staleness-days", type=int, default=7)
    parser.add_argument("--nav-zone", action="append", default=[], type=_parse_zone)
    parser.add_argument("--certificated-mtow-kg", type=Decimal,
                        help="Highest certificated MTOW from the AFM; required for official-style navigation charges.")
    parser.add_argument("--type-level-mtow-scenario", action="store_true",
                        help="Scenario: use the OpenAP type-level MTOW when no certificated MTOW is given.")
    parser.add_argument("--tariff-param", action="append", default=[])
    parser.add_argument("--handling-param", action="append", default=[])
    parser.add_argument("--handling-assumption", action="append", default=[])
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging("WARNING" if settings.log_level == "INFO" else settings.log_level)
    if not settings.database_path.is_file():
        print(f"Database not found: {settings.database_path}")
        return 1
    migrate_database(settings.database_url)
    engine = create_db_engine(settings.database_url)
    try:
        request = VariableCostRequest(
            flight_estimate_id=args.flight_estimate_id, pricing_date=args.pricing_date, reporting_currency=args.currency,
            fuel_density_kg_per_l=args.fuel_density_kg_per_l,
            max_fuel_price_staleness_days=args.max_fuel_price_staleness_days,
            max_fx_staleness_days=args.max_fx_staleness_days, nav_segments=tuple(args.nav_zone),
            certificated_mtow_kg=args.certificated_mtow_kg,
            use_type_level_mtow_scenario=args.type_level_mtow_scenario,
            tariff_context=_parse_params(args.tariff_param),
            handling_context=_parse_params(args.handling_param),
            handling_assumptions=_parse_assumptions(args.handling_assumption),
        )
        with Session(engine) as session:
            result = calculate_variable_costs(session, request)
    except (CostCalculationError, argparse.ArgumentTypeError) as exc:
        print(f"ERROR ({type(exc).__name__}): {exc}")
        return 1
    print(render(result))
    if args.save:
        estimate_id = save_variable_cost_estimate(engine, result)
        print(f"\nSaved as variable_cost_estimate_id={estimate_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
