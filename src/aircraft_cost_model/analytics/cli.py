"""Shared command-line arguments and setup for the Part 5 scripts (no hidden defaults)."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import AnalyticsInputError, CostCase, calculate_case, load_saved_case
from aircraft_cost_model.analytics.metrics import DistanceBasis, DistanceInput, PayloadInput
from aircraft_cost_model.config import get_settings
from aircraft_cost_model.database import create_db_engine, migrate_database
from aircraft_cost_model.fullcost.scenario import load_scenario
from aircraft_cost_model.logging_config import configure_logging


def decimal_arg(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"not a decimal number: {text!r}") from exc
    if not value.is_finite():
        raise argparse.ArgumentTypeError("value must be finite")
    return value


def add_case_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("cost case (a saved full-cost estimate, or flight + Part 3 estimate + scenario)")
    group.add_argument("--full-cost-estimate-id", type=int)
    group.add_argument("--flight-estimate-id", type=int)
    group.add_argument("--variable-cost-estimate-id", type=int)
    group.add_argument("--scenario", type=Path, help="Part 4 scenario JSON")


def add_distance_payload_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--distance-basis", required=True, choices=[b.value for b in DistanceBasis],
                        help="great_circle / modelled_route (Part 2) or actual_flown (needs --actual-distance-nm)")
    parser.add_argument("--actual-distance-nm", type=decimal_arg)
    parser.add_argument("--distance-reference", help="source of an actual flown distance")
    parser.add_argument("--revenue-payload-t", type=decimal_arg,
                        help="explicit revenue cargo payload in tonnes (never taken from the Part 2 modelled payload)")
    parser.add_argument("--payload-source-type", default="user_assumption",
                        choices=["observed_public_data", "user_assumption", "illustrative_assumption"])
    parser.add_argument("--payload-reference")
    parser.add_argument("--hypothetical-cargo", action="store_true",
                        help="required to attach a cargo payload to a passenger-flight scenario (labelled hypothetical)")
    parser.add_argument("--available-payload-t", type=decimal_arg,
                        help="explicit available payload capacity in tonnes (for ATNM and load factor)")


def distance_from(args: argparse.Namespace) -> DistanceInput:
    return DistanceInput(DistanceBasis(args.distance_basis), args.actual_distance_nm, args.distance_reference)


def payload_from(args: argparse.Namespace) -> PayloadInput:
    return PayloadInput(args.revenue_payload_t, args.payload_source_type, args.payload_reference,
                        args.hypothetical_cargo, args.available_payload_t)


def open_database() -> Engine:
    settings = get_settings()
    configure_logging("WARNING" if settings.log_level == "INFO" else settings.log_level)
    if not settings.database_path.is_file():
        raise AnalyticsInputError(f"Database not found: {settings.database_path}")
    migrate_database(settings.database_url)
    return create_db_engine(settings.database_url)


def resolve_case(session: Session, args: argparse.Namespace) -> CostCase:
    if args.full_cost_estimate_id is not None:
        if args.flight_estimate_id or args.variable_cost_estimate_id or args.scenario:
            raise AnalyticsInputError("give either --full-cost-estimate-id or flight/variable/scenario, not both")
        return load_saved_case(session, args.full_cost_estimate_id)
    if None in (args.flight_estimate_id, args.variable_cost_estimate_id, args.scenario):
        raise AnalyticsInputError("give --full-cost-estimate-id, or all of --flight-estimate-id, "
                                  "--variable-cost-estimate-id and --scenario")
    case, _ = calculate_case(session, args.flight_estimate_id, args.variable_cost_estimate_id, load_scenario(args.scenario))
    return case


def reference_path(name: str) -> Path:
    return get_settings().reference_dir / name
