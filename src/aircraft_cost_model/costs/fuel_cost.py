"""Fuel cost from Part 2 block fuel and a public price benchmark.

    litres      = block_fuel_kg / density_kg_per_l
    US gallons  = litres / 3.785411784              (exact definition)
    barrels     = US gallons / 42                   (exact definition)
    cost_src    = quantity_in_price_unit x price    (price currency)
    cost_report = convert(cost_src)                 (ECB rates, see currency.py)

This is the economic cost of the fuel *consumed* valued at a public market
benchmark. It is not an airline's into-plane price, contract price, hedged
price, tax-inclusive price, or the cost of the actual uplift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from aircraft_cost_model.costs.coverage import Assumption, ComponentName, ComponentResult, ComponentStatus, SourceType
from aircraft_cost_model.costs.currency import RateProvider, convert, plain, round_money
from aircraft_cost_model.costs.exceptions import CostInputError, ObservationUnavailableError

US_GALLON_LITRES = Decimal("3.785411784")
US_GALLONS_PER_BARREL = Decimal("42")

# price_unit -> quantity unit of the price denominator
SUPPORTED_PRICE_UNITS = {"USgal", "L", "bbl", "kg", "t"}


@dataclass(frozen=True)
class FuelPriceObservation:
    """A selected benchmark observation (already checked against the pricing-date policy)."""

    series_identifier: str
    description: str
    observation_date: date
    observation_period: str
    price: Decimal
    currency: str
    price_unit: str  # e.g. "USD/USgal"
    gap_days: int
    source_id: int | None = None
    source_reference: str | None = None

    @property
    def quantity_unit(self) -> str:
        currency, _, unit = self.price_unit.partition("/")
        if currency != self.currency or unit not in SUPPORTED_PRICE_UNITS:
            raise CostInputError(f"Unsupported or inconsistent price unit {self.price_unit!r} for {self.currency}")
        return unit


def fuel_quantity(block_fuel_kg: Decimal, density_kg_per_l: Decimal, unit: str) -> tuple[Decimal, list[dict]]:
    """Convert kg of fuel to ``unit`` with every step recorded."""
    if block_fuel_kg < 0:
        raise CostInputError("Block fuel must not be negative")
    if density_kg_per_l <= 0:
        raise CostInputError("Fuel density must be positive")
    steps = [{"step": "block fuel", "value": plain(block_fuel_kg), "unit": "kg"}]
    if unit == "kg":
        return block_fuel_kg, steps
    if unit == "t":
        tonnes = block_fuel_kg / Decimal(1000)
        steps.append({"step": "kg -> t", "formula": "kg / 1000", "value": plain(tonnes), "unit": "t"})
        return tonnes, steps
    litres = block_fuel_kg / density_kg_per_l
    steps.append({"step": "kg -> L", "formula": f"kg / {density_kg_per_l} kg/L", "value": plain(litres), "unit": "L"})
    if unit == "L":
        return litres, steps
    gallons = litres / US_GALLON_LITRES
    steps.append({"step": "L -> US gal", "formula": f"L / {US_GALLON_LITRES}", "value": plain(gallons), "unit": "USgal"})
    if unit == "USgal":
        return gallons, steps
    if unit == "bbl":
        barrels = gallons / US_GALLONS_PER_BARREL
        steps.append({"step": "US gal -> bbl", "formula": "US gal / 42", "value": plain(barrels), "unit": "bbl"})
        return barrels, steps
    raise CostInputError(f"Unsupported fuel quantity unit {unit!r}")


def calculate_fuel_cost(
    *,
    block_fuel_kg: Decimal,
    density_kg_per_l: Decimal,
    density_source: str,
    price: FuelPriceObservation | None,
    price_unavailable_reason: str | None,
    reporting_currency: str,
    pricing_date: date,
    rates: RateProvider,
) -> ComponentResult:
    """Price block fuel at the benchmark and convert to the reporting currency."""
    name = ComponentName.FUEL.value
    assumptions = [
        Assumption("fuel_quantity_basis", "block fuel (taxi-out + trip + landing roll + taxi-in), Part 2 v2", None,
                   "model_estimate", "flight_estimate.block_fuel_kg"),
        Assumption("fuel_density_kg_per_l", str(density_kg_per_l), "kg/L", density_source),
    ]
    warnings = ["Fuel is valued at a public spot-market benchmark, not an airline contract, into-plane, "
                "hedged or tax-inclusive price, and not the actual uplift"]
    if price is None:
        return ComponentResult(name, ComponentStatus.UNAVAILABLE_PRICE, reporting_currency, pricing_date,
                               calculation_method="block fuel x benchmark price", assumptions=assumptions,
                               warnings=warnings + [price_unavailable_reason or "No benchmark price available"])
    quantity, steps = fuel_quantity(block_fuel_kg, density_kg_per_l, price.quantity_unit)
    cost_src = quantity * price.price
    steps.append({"step": "price", "series": price.series_identifier, "observation_date": price.observation_date.isoformat(),
                  "observation_period": price.observation_period, "gap_days": price.gap_days,
                  "value": plain(price.price), "unit": price.price_unit})
    steps.append({"step": "cost in price currency", "formula": f"quantity x price", "value": plain(cost_src),
                  "unit": price.currency})
    try:
        conversion = convert(cost_src, price.currency, reporting_currency, pricing_date, rates)
    except ObservationUnavailableError as exc:
        return ComponentResult(name, ComponentStatus.UNAVAILABLE_PRICE, reporting_currency, pricing_date,
                               calculation_method="block fuel x benchmark price", breakdown=steps,
                               assumptions=assumptions, warnings=warnings + [f"Exchange rate unavailable: {exc}"])
    steps.extend(conversion.steps)
    amount = round_money(conversion.amount_out)
    steps.append({"step": "rounding", "formula": "round half up to 0.01", "value": plain(amount), "unit": reporting_currency})
    if price.gap_days:
        warnings.append(f"Price observation dated {price.observation_date} ({price.gap_days} days before pricing date)")
    for quote in conversion.quotes:
        if quote.gap_days:
            warnings.append(f"ECB {quote.currency} rate dated {quote.observation_date} ({quote.gap_days} days before pricing date)")
    return ComponentResult(
        name, ComponentStatus.CALCULATED_BENCHMARK, reporting_currency, pricing_date, amount,
        SourceType.PUBLIC_MARKET_BENCHMARK, price.source_reference, price.source_id, price.observation_date,
        "block fuel (kg) -> price unit via stated density -> x benchmark price -> ECB conversion",
        steps, assumptions, warnings,
    )
