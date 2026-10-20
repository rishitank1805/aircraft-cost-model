"""Terminal navigation charges with SYNTHETIC rates (departure-only zones)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.costs.currency import StaticRateProvider, round_money
from aircraft_cost_model.costs.navigation_cost import MTOW_CERTIFICATED, MtowBasis
from aircraft_cost_model.costs.terminal_cost import (
    MOVEMENT_ARRIVAL,
    MOVEMENT_DEPARTURE,
    TerminalZoneRate,
    calculate_terminal_component,
    calculate_terminal_part,
)

D = date(2025, 1, 15)
FX = StaticRateProvider({"USD": (Decimal("1.03"), D)})
CERT = MtowBasis(Decimal("78000"), MTOW_CERTIFICATED, "test")
DE = TerminalZoneRate("GERMANY_TCZ", "Germany", Decimal("300.00"), "EUR", date(2025, 1, 1), date(2025, 12, 31),
                      "mtow_over_50_pow_0_7", "departure", "verified_against_source", 1, "SYNTHETIC; notes: subject to VAT")
FR = TerminalZoneRate("FRANCE_TCZ1", "France 1", Decimal("200.00"), "EUR", date(2025, 1, 1), date(2025, 12, 31),
                      "mtow_over_50_pow_0_7", "departure", "verified_against_source", 1, "SYNTHETIC")


def part(code="FRA", icao="EDDF", movement=MOVEMENT_DEPARTURE, zones=(DE,), without=(), mtow=CERT, currency="EUR"):
    return calculate_terminal_part(airport_code=code, aerodrome_icao=icao, movement=movement, zones=list(zones),
                                   zone_memberships_without_rate=list(without), mtow=mtow,
                                   reporting_currency=currency, pricing_date=D, fx=FX)


def test_departure_charge():
    r = part()
    assert r.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF
    assert r.amount == Decimal("411.00")  # 300.00 x 1.37 ((78.0/50)^0.7 = 1.3652)
    assert r.breakdown[0]["alternative_if_truncated"] == "408.00"  # N = 1.36
    assert any("VAT" in w for w in r.warnings)


def test_arrival_at_departure_only_zone_is_documented_zero():
    r = part("CDG", "LFPG", MOVEMENT_ARRIVAL, (FR,))
    assert r.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF and r.amount == Decimal("0.00")
    assert r.zero_by_tariff_rule and "departure only" in r.breakdown[0]["note"]


def test_unknown_zone_is_unavailable_not_zero():
    r = part("JFK", "KJFK", MOVEMENT_ARRIVAL, ())
    assert r.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF and r.amount is None
    assert part(icao=None).status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF
    assert part(zones=(), without=("GERMANY_TCZ",)).status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF


def test_pending_review_rate_not_priced():
    pending = TerminalZoneRate(**{**DE.__dict__, "verification_status": "pending_review"})
    r = part(zones=(pending,))
    assert r.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF and "pending_review" in r.warnings[0]


def test_mtow_rules():
    assert part(mtow=MtowBasis.resolve(None, Decimal("78000"), False)).status == ComponentStatus.MISSING_REQUIRED_INPUT
    scenario = part(mtow=MtowBasis.resolve(None, Decimal("78000"), True))
    assert scenario.status == ComponentStatus.CALCULATED_ASSUMPTION and scenario.amount == Decimal("411.00")


def test_component_combines_departure_and_arrival():
    combined = calculate_terminal_component([part(), part("CDG", "LFPG", MOVEMENT_ARRIVAL, (FR,))], "EUR", D)
    assert combined.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF and combined.amount == Decimal("411.00")
    unknown_destination = calculate_terminal_component([part(), part("JFK", "KJFK", MOVEMENT_ARRIVAL, ())], "EUR", D)
    assert unknown_destination.amount is None
    assert part(currency="USD").amount == round_money(Decimal("411.00") * Decimal("1.03"))
