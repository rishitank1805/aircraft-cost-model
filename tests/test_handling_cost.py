"""Ground handling applicability, quantities and explicit assumptions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.costs.currency import StaticRateProvider
from aircraft_cost_model.costs.exceptions import CostInputError
from aircraft_cost_model.costs.handling_cost import HandlingAssumption, calculate_handling_part
from aircraft_cost_model.costs.landing_cost import AircraftFacts, AirportRef, TariffRecord

D = date(2025, 1, 15)
FX = StaticRateProvider({"USD": (Decimal("1.03"), D)})
FRA = AirportRef(1, "FRA", "Frankfurt")
A320 = AircraftFacts("A320", "A320", Decimal("78000"), "test", None)
B777F = AircraftFacts("B777F", "B77L", Decimal("347800"), "test", True)


def handling_tariff(**params):
    base = {"service_category": "ramp_handling", "payer": "aircraft_operator", "aircraft_category": "any",
            "movement": "any", "unit": "per_movement", "rate": "500.00"}
    base.update(params)
    return TariffRecord(5, 1, "ground_handling", date(2025, 1, 1), None, "EUR", "per_unit_handling", base, 3,
                        "SYNTHETIC", "synthetic_test_fixture")


def calc(tariffs, aircraft=A320, context=None, assumption=None):
    return calculate_handling_part(airport=FRA, aircraft=aircraft, movement="departure", pricing_date=D,
                                   tariffs=tariffs, context=context or {}, assumption=assumption,
                                   reporting_currency="EUR", fx=FX)


def test_public_tariff_calculation():
    r = calc([handling_tariff()])
    assert r.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF and r.amount == Decimal("500.00")
    uld = calc([handling_tariff(unit="per_uld", rate="35.50")], context={"uld_count": "12"})
    assert uld.amount == Decimal("426.00")


def test_missing_tariff_is_unavailable():
    r = calc([])
    assert r.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF and r.amount is None


def test_invalid_or_missing_chargeable_quantity():
    t = [handling_tariff(unit="per_tonne_cargo", rate="80")]
    assert calc(t).status == ComponentStatus.MISSING_REQUIRED_INPUT  # cargo tonnes never derived from payload
    assert calc(t, context={"cargo_tonnes": "-3"}).status == ComponentStatus.CALCULATION_ERROR
    assert calc([handling_tariff(unit="per_uld")], context={"uld_count": "2.5"}).status == ComponentStatus.CALCULATION_ERROR


def test_cargo_tariff_not_applied_to_passenger_aircraft():
    cargo_only = handling_tariff(aircraft_category="cargo")
    r = calc([cargo_only])
    assert r.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF
    assert any("applies to cargo aircraft" in w for w in r.warnings)
    assert calc([cargo_only], aircraft=B777F).status == ComponentStatus.CALCULATED_PUBLIC_TARIFF


def test_shipper_billed_terminal_tariff_not_an_operator_cost():
    r = calc([handling_tariff(service_category="cargo_terminal_handling", payer="shipper_or_forwarder")])
    assert r.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF


def test_multiple_applicable_tariffs_not_combined():
    r = calc([handling_tariff(), handling_tariff(service_category="towing")])
    assert r.status == ComponentStatus.UNSUPPORTED_TARIFF_RULE and r.amount is None


def test_explicit_assumption_labelled():
    r = calc([], assumption=HandlingAssumption(Decimal("900"), "USD"))
    assert r.status == ComponentStatus.CALCULATED_ASSUMPTION
    assert r.amount == (Decimal("900") / Decimal("1.03")).quantize(Decimal("0.01"))
    assert any("user assumption" in w for w in r.warnings)
    with pytest.raises(CostInputError):
        HandlingAssumption(Decimal("-1"), "EUR")
