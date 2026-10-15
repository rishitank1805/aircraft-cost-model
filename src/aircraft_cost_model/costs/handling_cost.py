"""Ground handling charges.

Only tariffs whose applicability is established are used:

- payer must be the aircraft operator (cargo terminal tariffs billed to
  shippers or forwarders are not aircraft operating costs);
- aircraft category must match (a cargo-only tariff is never applied to a
  passenger aircraft such as the A320; aircraft of unknown category match only
  ``any``);
- the movement (departure / arrival) must match;
- the chargeable quantity must be known (cargo tonnes and ULD counts are
  user inputs; they are never derived from payload mass).

``Handling cost = tariff rate x chargeable quantity`` per airport movement.
Exactly one applicable tariff per movement is required; combining several
service tariffs needs combination rules that are not defined, so it is
reported as ``unsupported_tariff_rule``. With no applicable public tariff the
result is ``unavailable_public_tariff`` unless the user supplies an explicit
handling price, reported as ``calculated_assumption``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from aircraft_cost_model.costs.coverage import (
    Assumption,
    ComponentName,
    ComponentResult,
    ComponentStatus,
    SourceType,
    combine_parts,
)
from aircraft_cost_model.costs.currency import RateProvider, convert, normalize_currency, round_money
from aircraft_cost_model.costs.exceptions import CostInputError, ObservationUnavailableError
from aircraft_cost_model.costs.landing_cost import AircraftFacts, AirportRef, TariffRecord

TARIFF_TYPE_HANDLING = "ground_handling"
METHOD_PER_UNIT = "per_unit_handling"
MOVEMENT_DEPARTURE = "departure"
MOVEMENT_ARRIVAL = "arrival"
UNITS = {"per_movement": None, "per_tonne_cargo": "cargo_tonnes", "per_uld": "uld_count"}


@dataclass(frozen=True)
class HandlingAssumption:
    """User-supplied handling price for one airport movement (scenario assumption, not observed data)."""

    amount: Decimal
    currency: str
    description: str = "user-supplied handling price per movement"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount < 0:
            raise CostInputError("Handling assumption amount must be a finite Decimal >= 0")
        normalize_currency(self.currency)


def aircraft_category(aircraft: AircraftFacts) -> str:
    if aircraft.is_freighter is True:
        return "cargo"
    if aircraft.is_freighter is False:
        return "passenger"
    return "unknown"


def _applicable(tariff: TariffRecord, aircraft: AircraftFacts, movement: str) -> tuple[bool, str]:
    p = tariff.parameters
    if tariff.calculation_method != METHOD_PER_UNIT:
        return False, f"rule {tariff.calculation_method} not implemented"
    if p.get("payer") != "aircraft_operator":
        return False, f"billed to {p.get('payer')}, not the aircraft operator"
    category = p.get("aircraft_category", "any")
    if category != "any" and category != aircraft_category(aircraft):
        return False, f"applies to {category} aircraft, not {aircraft_category(aircraft)}"
    if p.get("movement", "any") not in ("any", movement):
        return False, f"applies to {p.get('movement')} movements"
    if p.get("unit") not in UNITS:
        return False, f"unit {p.get('unit')} not supported"
    return True, ""


def calculate_handling_part(
    *,
    airport: AirportRef,
    aircraft: AircraftFacts,
    movement: str,
    pricing_date: date,
    tariffs: list[TariffRecord],
    context: dict[str, str],
    assumption: HandlingAssumption | None,
    reporting_currency: str,
    fx: RateProvider,
) -> ComponentResult:
    """Handling charge for one airport movement."""
    part = f"{airport.code} {movement}"
    base = {"part": part, "airport": airport.code, "movement": movement}
    name = ComponentName.GROUND_HANDLING.value
    applicable, rejected = [], []
    for tariff in tariffs:
        ok, reason = _applicable(tariff, aircraft, movement)
        (applicable if ok else rejected).append((tariff, reason))
    warnings = [f"{part}: tariff {t.parameters.get('service_category', t.tariff_type)} not applied ({r})"
                for t, r in rejected]

    def convert_amount(amount: Decimal, currency: str) -> tuple[Decimal, list[dict]] | ComponentResult:
        try:
            conversion = convert(amount, currency, reporting_currency, pricing_date, fx)
        except ObservationUnavailableError as exc:
            return ComponentResult(name, ComponentStatus.UNAVAILABLE_PRICE, reporting_currency, pricing_date,
                                   breakdown=[base], warnings=warnings + [f"{part}: exchange rate unavailable: {exc}"])
        return round_money(conversion.amount_out), conversion.steps

    if len(applicable) > 1:
        return ComponentResult(name, ComponentStatus.UNSUPPORTED_TARIFF_RULE, reporting_currency, pricing_date,
                               breakdown=[base], warnings=warnings + [
                                   f"{part}: {len(applicable)} applicable handling tariffs; combination rules undefined"])
    if applicable:
        tariff = applicable[0][0]
        p = tariff.parameters
        quantity_key = UNITS[p["unit"]]
        if quantity_key is None:
            quantity = Decimal(1)
        else:
            raw = context.get(quantity_key)
            if raw is None or raw == "":
                return ComponentResult(name, ComponentStatus.MISSING_REQUIRED_INPUT, reporting_currency, pricing_date,
                                       breakdown=[base], missing_inputs=[quantity_key],
                                       warnings=warnings + [f"{part}: chargeable quantity {quantity_key} not supplied"])
            try:
                quantity = Decimal(raw)
            except InvalidOperation:
                quantity = Decimal(-1)
            if not quantity.is_finite() or quantity < 0 or (quantity_key == "uld_count" and quantity != quantity.to_integral()):
                return ComponentResult(name, ComponentStatus.CALCULATION_ERROR, reporting_currency, pricing_date,
                                       breakdown=[base], warnings=warnings + [f"{part}: invalid {quantity_key} {raw!r}"])
        amount_src = Decimal(str(p["rate"])) * quantity
        converted = convert_amount(amount_src, tariff.currency)
        if isinstance(converted, ComponentResult):
            return converted
        amount, steps = converted
        breakdown = [{**base, "service_category": p.get("service_category"), "unit": p["unit"],
                      "quantity": str(quantity), "rate": str(p["rate"]), "currency": tariff.currency,
                      "amount_tariff_currency": str(amount_src)}] + steps
        return ComponentResult(name, ComponentStatus.CALCULATED_PUBLIC_TARIFF, reporting_currency, pricing_date,
                               amount, SourceType.PUBLIC_TARIFF, tariff.source_reference, tariff.source_id,
                               tariff.valid_from, "tariff rate x chargeable quantity", breakdown,
                               warnings=warnings, zero_by_tariff_rule=amount == 0)
    if assumption is not None:
        converted = convert_amount(assumption.amount, assumption.currency)
        if isinstance(converted, ComponentResult):
            return converted
        amount, steps = converted
        return ComponentResult(
            name, ComponentStatus.CALCULATED_ASSUMPTION, reporting_currency, pricing_date, amount,
            SourceType.USER_ASSUMPTION, "user-supplied scenario assumption", None, None,
            "user-supplied handling price", [{**base, "assumed_amount": str(assumption.amount),
                                              "currency": assumption.currency}] + steps,
            [Assumption(f"handling_price_{airport.code}_{movement}", str(assumption.amount), assumption.currency,
                        "user_assumption", assumption.description)],
            warnings + [f"{part}: handling priced from a user assumption, not observed public data"],
            zero_by_tariff_rule=amount == 0,
        )
    return ComponentResult(name, ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF, reporting_currency, pricing_date,
                           breakdown=[base], warnings=warnings + [
                               f"{part}: no applicable public ground handling tariff (handling contracts are private)"])


def calculate_handling_component(parts: list[ComponentResult], reporting_currency: str, pricing_date: date) -> ComponentResult:
    return combine_parts(ComponentName.GROUND_HANDLING.value, parts, reporting_currency, pricing_date,
                         "origin departure handling + destination arrival handling")
