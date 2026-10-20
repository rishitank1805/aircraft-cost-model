"""Fuel cost unit conversions, benchmark pricing and FX (pure, offline)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.costs.currency import StaticRateProvider, round_money
from aircraft_cost_model.costs.exceptions import CostInputError
from aircraft_cost_model.costs.fuel_cost import (
    US_GALLON_LITRES,
    FuelPriceObservation,
    calculate_fuel_cost,
    fuel_quantity,
)

D = date(2025, 1, 15)
FX = StaticRateProvider({"USD": (Decimal("1.03"), D)})
PRICE = FuelPriceObservation("EER_EPJK_PF4_RGC_DPG", "test", D, "daily", Decimal("2.463"), "USD", "USD/USgal", 0)


def _cost(**kw):
    args = dict(block_fuel_kg=Decimal("2271.5"), density_kg_per_l=Decimal("0.8025"), density_source="test",
                price=PRICE, price_unavailable_reason=None, reporting_currency="EUR", pricing_date=D, rates=FX)
    args.update(kw)
    return calculate_fuel_cost(**args)


def test_kg_to_litres_to_us_gallons():
    gallons, steps = fuel_quantity(Decimal("802.5"), Decimal("0.8025"), "USgal")
    assert steps[1]["value"] == "1000"  # plain notation, not 1E+3  # 802.5 kg / 0.8025 kg/L = 1000 L exactly
    assert gallons == Decimal(1000) / US_GALLON_LITRES
    assert US_GALLON_LITRES == Decimal("3.785411784")
    litres, _ = fuel_quantity(Decimal("802.5"), Decimal("0.8025"), "L")
    assert litres == Decimal(1000)
    barrels, _ = fuel_quantity(Decimal("802.5"), Decimal("0.8025"), "bbl")
    assert barrels == gallons / 42
    assert fuel_quantity(Decimal("1500"), Decimal("0.8"), "t")[0] == Decimal("1.5")


def test_usd_per_gallon_to_eur_matches_hand_calculation():
    result = _cost()
    expected_usd = Decimal("2271.5") / Decimal("0.8025") / US_GALLON_LITRES * Decimal("2.463")
    assert result.status == ComponentStatus.CALCULATED_BENCHMARK
    assert result.amount == (expected_usd / Decimal("1.03")).quantize(Decimal("0.01"))
    assert result.amount == Decimal("1788.06")  # 2,271.5 kg exactly (the saved estimate holds 2,271.489... kg)
    assert result.currency == "EUR" and result.observation_date == D


def test_usd_reporting_needs_no_fx():
    assert _cost(reporting_currency="USD").amount == Decimal("1841.70")


def test_density_sensitivity():
    low, high = _cost(density_kg_per_l=Decimal("0.775")), _cost(density_kg_per_l=Decimal("0.84"))
    assert low.amount > _cost().amount > high.amount
    assert float(low.amount / high.amount) == pytest.approx(0.84 / 0.775, rel=1e-5)


def test_missing_price_is_unavailable_not_zero():
    result = _cost(price=None, price_unavailable_reason="no observation")
    assert result.status == ComponentStatus.UNAVAILABLE_PRICE and result.amount is None
    assert any("no observation" in w for w in result.warnings)


def test_missing_fx_is_unavailable():
    result = _cost(rates=StaticRateProvider({}))
    assert result.status == ComponentStatus.UNAVAILABLE_PRICE and result.amount is None


def test_invalid_inputs_rejected():
    with pytest.raises(CostInputError):
        _cost(density_kg_per_l=Decimal("0"))
    with pytest.raises(CostInputError):
        _cost(block_fuel_kg=Decimal("-1"))
    with pytest.raises(CostInputError):
        _cost(price=FuelPriceObservation("X", "x", D, "daily", Decimal("2"), "USD", "USD/tonne", 0))


def test_regression_stored_estimate_reconciles_without_intermediate_rounding():
    """A320 FRA-CDG estimate #2: exact stored inputs reproduce EUR 1,788.05; rounded intermediates do not."""
    block = Decimal(str(2271.4893156832763))  # flight_estimate.block_fuel_kg as stored (float, shortest repr)
    result = _cost(block_fuel_kg=block)
    assert result.amount == Decimal("1788.05")
    steps = {b.get("step"): b for b in result.breakdown}
    litres = Decimal(steps["kg -> L"]["value"])
    gallons = Decimal(steps["L -> US gal"]["value"])
    usd = Decimal(steps["cost in price currency"]["value"])
    eur = Decimal(steps["USD -> EUR"]["result"])
    # every reported step reconciles exactly with the previous one
    assert litres == block / Decimal("0.8025")
    assert gallons == litres / US_GALLON_LITRES
    assert usd == gallons * Decimal("2.463")
    assert eur == usd / Decimal("1.03")
    assert str(gallons).startswith("747.7432952") and str(usd).startswith("1841.6917361")
    # the rounded chain used in an earlier report (747.74 gal) gives a different cent value
    rounded_chain = round_money(Decimal("747.74") * Decimal("2.463") / Decimal("1.03"))
    assert rounded_chain == Decimal("1788.04") != result.amount
