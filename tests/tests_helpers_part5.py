"""Small synthetic cost cases for Part 5 tests that need no database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from aircraft_cost_model.analytics.cases import CostCase, FlightFacts
from aircraft_cost_model.costs.coverage import ComponentResult, ComponentStatus, SourceType
from aircraft_cost_model.fullcost.aggregate import COMPONENT_CATEGORY, FullCostSummary

D = date(2025, 1, 15)


def facts() -> FlightFacts:
    return FlightFacts(1, "A320", True, "FRA", "CDG", Decimal("2"), Decimal("1.5"), Decimal("200"), Decimal("220"),
                       "great_circle", Decimal("2000"), Decimal("10000"), "calculated_limits_unverified", "v2")


def _case(currency: str, label: str) -> CostCase:
    comps = {n: ComponentResult(n, ComponentStatus.CALCULATED_PUBLIC_TARIFF, currency, D, Decimal("10.00"),
                                SourceType.PUBLIC_TARIFF) for n in COMPONENT_CATEGORY}
    return CostCase(label, facts(), FullCostSummary(comps, currency, "calculated"), D, currency, "cargo", "owned")


def eur_case() -> CostCase:
    return _case("EUR", "eur")


def usd_case() -> CostCase:
    return _case("USD", "usd")
