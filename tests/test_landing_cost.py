"""Airport movement-charge engine with a SYNTHETIC tariff (structure of the FRA rule, not its values)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.costs.currency import StaticRateProvider
from aircraft_cost_model.costs.landing_cost import (
    MOVEMENT_LANDING,
    MOVEMENT_TAKEOFF,
    AircraftFacts,
    AirportRef,
    FraMovementCharges2026,
    LandingTariffCalculator,
    TariffRecord,
    calculate_landing_component,
)
from conftest import FRA_CONTEXT, synthetic_fra_parameters

D = date(2025, 6, 1)
FX = StaticRateProvider({"USD": (Decimal("1.10"), D)})
A320 = AircraftFacts("A320", "A320", Decimal("78000"), "test", None)
FRA = AirportRef(1, "FRA", "Frankfurt")
CDG = AirportRef(2, "CDG", "Paris CDG")


def tariff(valid_from=date(2025, 1, 1), valid_to=None, method="fra_movement_charges_2026"):
    return TariffRecord(1, 1, "landing_takeoff", valid_from, valid_to, "EUR", method, synthetic_fra_parameters(), 9,
                        "synthetic", "synthetic_test_fixture")


def calc(context=FRA_CONTEXT, tariffs=None, aircraft=A320, movement=MOVEMENT_TAKEOFF, currency="EUR"):
    return LandingTariffCalculator().calculate(FRA, aircraft, movement, D, dict(context),
                                               [tariff()] if tariffs is None else tariffs, currency, FX)


def test_synthetic_parameters_validate():
    FraMovementCharges2026.validate_parameters(synthetic_fra_parameters())


def test_takeoff_charge_elements():
    r = calc()
    # pax 150 x 2.00 = 300; freight ceil(1250/100)=13 x 0.10 = 1.30; noise cat 4 = 40 less R6 (4%) = 38.40;
    # emissions 10.123 (3 dp) x 4.00 = 40.492  -> 380.192 -> 380.19
    assert r.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF
    assert r.amount == Decimal("380.19")
    elements = {b.get("element"): b for b in r.breakdown}
    assert elements["1.2.4 freight/mail"]["started_100kg"] == "13"
    assert elements["1.2.13 emissions"]["emission_value_kg_nox_eq"] == "10.123"


def test_landing_has_no_passenger_element():
    r = calc(movement=MOVEMENT_LANDING)
    assert not any(b.get("element") == "1.2.4 passengers" for b in r.breakdown)
    assert r.amount == Decimal("80.19")


def test_night_surcharges_and_nri_only_outside_night2():
    night1 = calc({**FRA_CONTEXT, "movement_local_time": "22:15"})
    night2 = calc({**FRA_CONTEXT, "movement_local_time": "23:30"})
    assert any("night_time_1" in str(b.get("element")) for b in night1.breakdown)
    assert any("NRI" in str(b.get("element")) for b in night1.breakdown)
    assert any("night_time_2" in str(b.get("element")) for b in night2.breakdown)
    assert not any("NRI" in str(b.get("element")) for b in night2.breakdown)
    # night 2: noise 40 + 80 surcharge, no reduction
    assert night2.amount == Decimal("300") + Decimal("1.30") + Decimal("120") + Decimal("40.492").quantize(Decimal("0.01"))


def test_missing_noise_classification_is_reported_not_assumed():
    context = {k: v for k, v in FRA_CONTEXT.items() if k != "noise_category_takeoff"}
    r = calc(context)
    assert r.status == ComponentStatus.MISSING_REQUIRED_INPUT and r.amount is None
    assert "noise_category_takeoff" in r.missing_inputs
    nri = calc({k: v for k, v in FRA_CONTEXT.items() if k != "nri_category"})
    assert nri.missing_inputs == ["nri_category"]


def test_effective_date_and_missing_tariff():
    assert calc(tariffs=[]).status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF
    assert calc(tariffs=[tariff(), tariff(date(2025, 3, 1))]).status == ComponentStatus.CALCULATION_ERROR
    assert calc(tariffs=[tariff(method="unknown_rule")]).status == ComponentStatus.UNSUPPORTED_TARIFF_RULE


def test_weight_basis_and_unsupported_cases():
    small = AircraftFacts("E190", "E190", Decimal("50300"), "test", None)
    assert calc(aircraft=small).status == ComponentStatus.UNSUPPORTED_TARIFF_RULE  # minimum charges not implemented
    assert calc({**FRA_CONTEXT, "flight_type": "ferry"}).status == ComponentStatus.UNSUPPORTED_TARIFF_RULE
    assert calc({**FRA_CONTEXT, "noise_certification": "chapter_3"}).status == ComponentStatus.UNSUPPORTED_TARIFF_RULE
    no_mtow = AircraftFacts("A320", "A320", None, "test", None)
    assert "certificated MTOM" in calc(aircraft=no_mtow).missing_inputs


def test_currency_conversion_and_rounding():
    usd = calc(currency="USD")
    assert usd.amount == (Decimal("380.192") * Decimal("1.10")).quantize(Decimal("0.01"))


def test_component_requires_both_airports_no_double_counting():
    origin = calc()
    destination = LandingTariffCalculator().calculate(CDG, A320, MOVEMENT_LANDING, D, {}, [], "EUR", FX)
    combined = calculate_landing_component([origin, destination], "EUR", D)
    assert combined.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF and combined.amount is None
    both = calculate_landing_component([origin, calc(movement=MOVEMENT_LANDING)], "EUR", D)
    assert both.amount == origin.amount + Decimal("80.19")  # each movement charged once
