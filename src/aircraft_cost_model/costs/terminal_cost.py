"""Terminal navigation (approach/departure) charges.

Verified sources:

- France (billed by EUROCONTROL): Information Circulars LF 2025/01 and LF
  2026/01 - charge levied "for each IFR flight departing" from the listed
  aerodromes; R = t x N; N = (MTOW/50)^0.70 "taken to two decimal places",
  MTOW in tonnes to one decimal, the same MTOW as for route charges.
- Germany (billed by DFS): DFS notice valid from 1 January 2026 - approach and
  departure count as one flight, "the counting unit is the departure";
  R = t x p, p = (MTOW/50)^0.7 to two decimals with the AFM certificated MTOW;
  the rate is subject to VAT (not modelled). The 2025 German rate is published
  by EUROCONTROL but the 2025 DFS rules notice is no longer available, so that
  row is ``pending_review`` and not priced.
- CRCO Customer Guide to Charges (April 2026) A.2.2: for EUROCONTROL-billed
  states "terminal charges are levied upon the departing flight only".

A flight has two parts: origin departure and destination arrival. A part is
zero only when the verified rules of that aerodrome's charging zone charge
the other movement only. An aerodrome without a loaded charging zone gives
``unavailable_public_tariff`` (the national rules are unknown), never zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from aircraft_cost_model.costs.coverage import (
    ComponentName,
    ComponentResult,
    ComponentStatus,
    SourceType,
    combine_parts,
)
from aircraft_cost_model.costs.currency import RateProvider, convert, plain, round_money
from aircraft_cost_model.costs.exceptions import ObservationUnavailableError
from aircraft_cost_model.costs.navigation_cost import (
    ROUNDING_INTERPRETATION,
    VALIDITY_INTERPRETATION,
    VERIFIED,
    MtowBasis,
    weight_factor,
)

MOVEMENT_DEPARTURE = "departure"
MOVEMENT_ARRIVAL = "arrival"
METHOD = "terminal charge R = t x (MTOW/50)^0.7, levied on the zone's charged movement"


@dataclass(frozen=True)
class TerminalZoneRate:
    zone: str
    zone_name: str
    unit_rate: Decimal
    currency: str
    valid_from: date
    valid_to: date | None
    service_unit_formula: str
    charged_movement: str
    verification_status: str
    source_id: int | None
    source_reference: str


def calculate_terminal_part(
    *,
    airport_code: str,
    aerodrome_icao: str | None,
    movement: str,
    zones: list[TerminalZoneRate],
    zone_memberships_without_rate: list[str],
    mtow: MtowBasis,
    reporting_currency: str,
    pricing_date: date,
    fx: RateProvider,
) -> ComponentResult:
    """Terminal charge for one movement at one aerodrome."""
    name = ComponentName.TERMINAL_NAVIGATION.value
    part = f"{airport_code} {movement}"
    base = {"part": part, "airport": airport_code, "aerodrome_icao": aerodrome_icao, "movement": movement}

    def unavailable(status: ComponentStatus, warning: str, missing: list[str] | None = None) -> ComponentResult:
        return ComponentResult(name, status, reporting_currency, pricing_date, breakdown=[base],
                               warnings=[f"{part}: {warning}"], missing_inputs=missing or [],
                               calculation_method=METHOD)

    if not aerodrome_icao:
        return unavailable(ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF, "aerodrome has no ICAO code")
    if zone_memberships_without_rate and not zones:
        return unavailable(ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF,
                           f"zone(s) {zone_memberships_without_rate} have no unit rate in force on {pricing_date}")
    if not zones:
        return unavailable(ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF,
                           f"{aerodrome_icao} is not in any loaded terminal charging zone for {pricing_date}; "
                           "national terminal charging rules unknown")
    if len(zones) > 1:
        return unavailable(ComponentStatus.CALCULATION_ERROR, f"aerodrome in several terminal zones {[z.zone for z in zones]}")
    zone = zones[0]
    if zone.verification_status != VERIFIED:
        return unavailable(ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF,
                           f"terminal rate for {zone.zone} ({zone.valid_from}) is {zone.verification_status} and is "
                           "not priced")
    rule = {**base, "zone": zone.zone, "charged_movement": zone.charged_movement,
            "rate_valid_from": zone.valid_from.isoformat(), "source": zone.source_reference}
    if movement != zone.charged_movement:
        return ComponentResult(
            name, ComponentStatus.CALCULATED_PUBLIC_TARIFF, reporting_currency, pricing_date, Decimal("0.00"),
            SourceType.PUBLIC_TARIFF, zone.source_reference, zone.source_id, zone.valid_from, METHOD,
            [{**rule, "note": f"{zone.zone} levies terminal charges on the {zone.charged_movement} only"}],
            [VALIDITY_INTERPRETATION], zero_by_tariff_rule=True,
        )
    if mtow.kg is None:
        return unavailable(ComponentStatus.MISSING_REQUIRED_INPUT,
                           "terminal charges use the certificated MTOW (same as route charges)", ["certificated MTOW"])
    wf = weight_factor(mtow.kg, zone.service_unit_formula)
    charge, charge_alt = zone.unit_rate * wf.value, zone.unit_rate * wf.alternative_truncated
    try:
        conv = convert(charge, zone.currency, reporting_currency, pricing_date, fx)
        conv_alt = convert(charge_alt, zone.currency, reporting_currency, pricing_date, fx)
    except ObservationUnavailableError as exc:
        return unavailable(ComponentStatus.UNAVAILABLE_PRICE, f"exchange rate unavailable: {exc}")
    amount = round_money(conv.amount_out)
    warnings = []
    if "VAT" in zone.source_reference:
        warnings.append(f"{part}: rate is net of VAT; VAT treatment is not modelled")
    if mtow.is_scenario:
        warnings.append(f"{part}: scenario - weight factor uses the OpenAP type-level MTOW")
    breakdown = [{**rule, **wf.to_dict(), "unit_rate": plain(zone.unit_rate), "currency": zone.currency,
                  "charge": plain(charge), "alternative_if_truncated": plain(round_money(conv_alt.amount_out))}]
    breakdown.extend(s for s in conv.steps if s.get("step") != "no conversion")
    status = ComponentStatus.CALCULATED_ASSUMPTION if mtow.is_scenario else ComponentStatus.CALCULATED_PUBLIC_TARIFF
    return ComponentResult(
        name, status, reporting_currency, pricing_date, amount, SourceType.PUBLIC_TARIFF, zone.source_reference,
        zone.source_id, zone.valid_from, METHOD, breakdown,
        [mtow.assumption(), ROUNDING_INTERPRETATION, VALIDITY_INTERPRETATION], warnings,
        zero_by_tariff_rule=amount == 0,
    )


def calculate_terminal_component(parts: list[ComponentResult], reporting_currency: str, pricing_date: date) -> ComponentResult:
    return combine_parts(ComponentName.TERMINAL_NAVIGATION.value, parts, reporting_currency, pricing_date,
                         "origin departure + destination arrival terminal charges under each zone's rules")

