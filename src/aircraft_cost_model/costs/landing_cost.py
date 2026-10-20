"""Airport landing and take-off (movement) charges.

A flight incurs movement charges at the origin (take-off) and destination
(landing) under each airport's own published tariff. The landing component is
calculated only when both parts are calculated; parts are never mixed with
fabricated values.

Each tariff record (``airport_tariff``) names a rule in :data:`RULES`; rules
declare the inputs they need and return ``missing_required_input`` instead of
assuming a noise class, emission value, passenger count or time of day.

Rule ``fra_movement_charges_2026`` - Fraport "Airport Charges according to
Art. 19b LuftVG", in force from 1 August 2026, section 1.2 (landing and
take-off charges) for non-ferry fixed-wing flights with MTOM > 66,000 kg:

- 1.2.4 passenger element: rate x passengers on board at take-off (take-off only)
- 1.2.4 freight/mail element: rate x started 100 kg on board (landing and take-off)
- 1.2.5-1.2.8 noise element: fixed amount per noise category (separate landing
  and take-off category tables) + night surcharge (night time 1: 22:00-22:59 and
  05:00-05:59; night time 2: 23:00-04:59, local time)
- 1.2.12 NRI reduction of the noise element for ICAO Chapter 4 and higher aircraft
  outside night time 2, by NRI category and MTOM band
- 1.2.13 emission element: rate x emission value (kg NOx-equivalent, ERLIG
  formula, three decimals) per landing and per take-off

Not implemented (``unsupported_tariff_rule``): ferry flights, MTOM <= 66 t
(minimum charges), Chapter 3 / marginal / non-certified surcharges
(1.2.9-1.2.11). The 1.2.3 mass-related charge applies only to ferry flights
> 66 t and helicopters, so it is not part of this rule. Parking, passenger,
security and noise-surcharge charges (1.3-1.6) are separate charges and are
not included here.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol

from aircraft_cost_model.costs.coverage import (
    Assumption,
    ComponentName,
    ComponentResult,
    ComponentStatus,
    SourceType,
    combine_parts,
)
from aircraft_cost_model.costs.currency import RateProvider, convert, plain, round_money
from aircraft_cost_model.costs.exceptions import ObservationUnavailableError

NIGHT_SURCHARGE_TABLES = {
    "night_time_1": "noise_night1_surcharge_by_category",
    "night_time_2": "noise_night2_surcharge_by_category",
}

MOVEMENT_TAKEOFF = "takeoff"
MOVEMENT_LANDING = "landing"
TARIFF_TYPE_MOVEMENT = "landing_takeoff"


@dataclass(frozen=True)
class AircraftFacts:
    aircraft_code: str
    icao_type_designator: str | None
    mtow_kg: Decimal | None
    mtow_source: str
    is_freighter: bool | None
    mtow_is_scenario: bool = False


@dataclass(frozen=True)
class AirportRef:
    airport_id: int
    code: str
    name: str | None


@dataclass(frozen=True)
class TariffRecord:
    airport_tariff_id: int | None
    airport_id: int
    tariff_type: str
    valid_from: date
    valid_to: date | None
    currency: str
    calculation_method: str
    parameters: dict[str, Any]
    source_id: int | None
    source_reference: str
    verification_status: str


class RuleNotApplicable(Exception):
    """The tariff exists but this implementation cannot apply it to the case (unsupported rule)."""


@dataclass
class RuleOutput:
    amount: Decimal
    breakdown: list[dict[str, Any]]
    assumptions: list[Assumption]
    warnings: list[str]


class TariffRule(Protocol):
    method: str

    def missing_inputs(self, movement: str, context: dict[str, str], aircraft: AircraftFacts,
                       params: dict[str, Any]) -> list[str]: ...

    def calculate(self, movement: str, context: dict[str, str], aircraft: AircraftFacts,
                  params: dict[str, Any]) -> RuleOutput: ...


def _dec(value: Any, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} is not a number: {value!r}") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name} must be a finite number >= 0")
    return number


def _local_time(value: str) -> time:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value.strip())
    if not match:
        raise ValueError(f"movement_local_time must be HH:MM, got {value!r}")
    return time(int(match.group(1)), int(match.group(2)))


def _in_window(t: time, start: str, end: str) -> bool:
    s, e = _local_time(start), _local_time(end)
    return s <= t <= e if s <= e else (t >= s or t <= e)


class FraMovementCharges2026:
    """Fraport section 1.2 rule (see module docstring)."""

    method = "fra_movement_charges_2026"
    NOISE_CERT_SUPPORTED = "chapter_4_or_higher"

    @staticmethod
    def validate_parameters(params: dict[str, Any]) -> None:
        """Raise ValueError if the reviewed parameter file is incomplete or malformed."""
        for key in ("passenger_rate_per_departing_passenger", "freight_mail_rate_per_started_100kg",
                    "emission_rate_per_kg_nox_eq", "applicability_min_mtom_kg_exclusive"):
            _dec(params[key], key)
        for table in ("noise_24h_by_category", "noise_night1_surcharge_by_category",
                      "noise_night2_surcharge_by_category"):
            categories = params[table]
            if sorted(categories, key=int) != [str(i) for i in range(1, 17)]:
                raise ValueError(f"{table} must define categories 1-16")
            for value in categories.values():
                _dec(value, table)
        for band in ("gt_34t_lt_136t", "ge_136t"):
            reductions = params["nri_reduction_pct"][band]
            if sorted(reductions) != sorted(f"R{i}" for i in range(1, 11)):
                raise ValueError(f"nri_reduction_pct.{band} must define R1-R10")
        for window in params["night_time_1"] + [params["night_time_2"]]:
            _local_time(window[0]), _local_time(window[1])

    def _night(self, t: time, params: dict[str, Any]) -> str | None:
        start, end = params["night_time_2"]
        if _in_window(t, start, end):
            return "night_time_2"
        if any(_in_window(t, s, e) for s, e in params["night_time_1"]):
            return "night_time_1"
        return None

    def missing_inputs(self, movement: str, context: dict[str, str], aircraft: AircraftFacts,
                       params: dict[str, Any]) -> list[str]:
        required = ["flight_type", "noise_certification", f"noise_category_{movement}", "movement_local_time",
                    "freight_mail_kg", "emission_value_kg_nox_eq"]
        if movement == MOVEMENT_TAKEOFF:
            required.append("departing_passengers")
        missing = [k for k in required if not context.get(k)]
        if aircraft.mtow_kg is None:
            missing.append("certificated MTOM")
        if not missing and context.get("noise_certification") == self.NOISE_CERT_SUPPORTED:
            t = _local_time(context["movement_local_time"])
            if self._night(t, params) != "night_time_2" and aircraft.mtow_kg and aircraft.mtow_kg > 34000 \
                    and not context.get("nri_category"):
                missing.append("nri_category")
        return missing

    def calculate(self, movement: str, context: dict[str, str], aircraft: AircraftFacts,
                  params: dict[str, Any]) -> RuleOutput:
        if context["flight_type"] != "commercial":
            raise RuleNotApplicable("Ferry/other flight types (section 1.2.3 mass-related charge) are not implemented")
        if aircraft.mtow_kg <= _dec(params["applicability_min_mtom_kg_exclusive"], "applicability"):
            raise RuleNotApplicable("MTOM <= 66,000 kg (minimum charges, 1.2.3) is not implemented")
        if context["noise_certification"] != self.NOISE_CERT_SUPPORTED:
            raise RuleNotApplicable("Only ICAO Chapter 4 and higher aircraft are implemented (1.2.9-1.2.11 surcharges not)")
        category = str(int(context[f"noise_category_{movement}"]))
        if category not in params["noise_24h_by_category"]:
            raise ValueError(f"noise category must be 1-16, got {category}")
        t = _local_time(context["movement_local_time"])
        night = self._night(t, params)
        breakdown: list[dict[str, Any]] = []
        assumptions = [Assumption(k, str(v), None, "user_input", "tariff context") for k, v in sorted(context.items())]
        assumptions.append(Assumption("mtom_kg", str(aircraft.mtow_kg), "kg", aircraft.mtow_source,
                                      "FRA 1.2.2: highest MTOM in the registration documents"))

        total = Decimal(0)
        if movement == MOVEMENT_TAKEOFF:
            pax = int(context["departing_passengers"])
            if pax < 0:
                raise ValueError("departing_passengers must be >= 0")
            amount = Decimal(pax) * _dec(params["passenger_rate_per_departing_passenger"], "pax rate")
            breakdown.append({"element": "1.2.4 passengers", "quantity": pax,
                              "rate": params["passenger_rate_per_departing_passenger"], "amount": plain(amount)})
            total += amount
        freight_kg = _dec(context["freight_mail_kg"], "freight_mail_kg")
        units = Decimal(math.ceil(freight_kg / Decimal(100)))
        amount = units * _dec(params["freight_mail_rate_per_started_100kg"], "freight rate")
        breakdown.append({"element": "1.2.4 freight/mail", "started_100kg": str(units),
                          "rate": params["freight_mail_rate_per_started_100kg"], "amount": plain(amount)})
        total += amount

        noise = _dec(params["noise_24h_by_category"][category], "noise")
        breakdown.append({"element": f"1.2.8 noise ({movement} table)", "category": category, "amount": plain(noise)})
        if night:
            surcharge = _dec(params[NIGHT_SURCHARGE_TABLES[night]][category], night)
            breakdown.append({"element": f"1.2.8 {night} surcharge", "category": category, "amount": plain(surcharge)})
            noise += surcharge
        if night != "night_time_2" and aircraft.mtow_kg > 34000:
            band = "ge_136t" if aircraft.mtow_kg >= 136000 else "gt_34t_lt_136t"
            pct = _dec(params["nri_reduction_pct"][band][context["nri_category"]], "nri pct")
            reduction = noise * pct / Decimal(100)
            breakdown.append({"element": "1.2.12 NRI reduction", "nri_category": context["nri_category"],
                              "band": band, "pct": str(pct), "amount": plain(-reduction)})
            noise -= reduction
            assumptions.append(Assumption("nri_reduction_base", "applied to the total 1.2.8 noise amount of the movement",
                                          None, "project_interpretation", "FRA 1.2.12"))
        total += noise

        emission_value = _dec(context["emission_value_kg_nox_eq"], "emission value").quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP)
        amount = emission_value * _dec(params["emission_rate_per_kg_nox_eq"], "emission rate")
        breakdown.append({"element": "1.2.13 emissions", "emission_value_kg_nox_eq": str(emission_value),
                          "rate": params["emission_rate_per_kg_nox_eq"], "amount": plain(amount)})
        total += amount
        return RuleOutput(total, breakdown, assumptions, [])


RULES: dict[str, TariffRule] = {FraMovementCharges2026.method: FraMovementCharges2026()}


class LandingTariffCalculator:
    """Calculates one airport's movement charge for one movement."""

    def __init__(self, rules: dict[str, TariffRule] | None = None) -> None:
        self.rules = RULES if rules is None else rules

    def calculate(
        self,
        airport: AirportRef,
        aircraft: AircraftFacts,
        movement: str,
        pricing_date: date,
        tariff_context: dict[str, str],
        tariffs: list[TariffRecord],
        reporting_currency: str,
        fx: RateProvider,
    ) -> ComponentResult:
        part = f"{airport.code} {movement}"
        base = {"part": part, "airport": airport.code, "movement": movement}

        def result(status: ComponentStatus, warning: str, missing: list[str] | None = None) -> ComponentResult:
            return ComponentResult(ComponentName.LANDING.value, status, reporting_currency, pricing_date,
                                   breakdown=[base], warnings=[f"{part}: {warning}"], missing_inputs=missing or [])

        if not tariffs:
            return result(ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF,
                          f"no reviewed public tariff in force on {pricing_date}")
        if len(tariffs) > 1:
            return result(ComponentStatus.CALCULATION_ERROR, "overlapping tariff versions in force")
        tariff = tariffs[0]
        rule = self.rules.get(tariff.calculation_method)
        if rule is None:
            return result(ComponentStatus.UNSUPPORTED_TARIFF_RULE, f"rule {tariff.calculation_method} not implemented")
        try:
            missing = rule.missing_inputs(movement, tariff_context, aircraft, tariff.parameters)
            if missing:
                return result(ComponentStatus.MISSING_REQUIRED_INPUT,
                              f"tariff requires inputs not available: {', '.join(missing)}", missing)
            output = rule.calculate(movement, tariff_context, aircraft, tariff.parameters)
        except RuleNotApplicable as exc:
            return result(ComponentStatus.UNSUPPORTED_TARIFF_RULE, str(exc))
        except (ValueError, KeyError) as exc:
            return result(ComponentStatus.CALCULATION_ERROR, f"invalid input or parameters: {exc}")
        breakdown = [{**base, "tariff_valid_from": tariff.valid_from.isoformat(), "currency": tariff.currency,
                      "verification_status": tariff.verification_status}] + output.breakdown
        try:
            conversion = convert(output.amount, tariff.currency, reporting_currency, pricing_date, fx)
        except ObservationUnavailableError as exc:
            return result(ComponentStatus.UNAVAILABLE_PRICE, f"exchange rate unavailable: {exc}")
        breakdown.extend(conversion.steps)
        amount = round_money(conversion.amount_out)
        warnings = list(output.warnings)
        if aircraft.mtow_is_scenario:
            warnings.append(f"{part}: scenario - MTOM thresholds use the OpenAP type-level MTOW")
        status = (ComponentStatus.CALCULATED_ASSUMPTION if aircraft.mtow_is_scenario
                  else ComponentStatus.CALCULATED_PUBLIC_TARIFF)
        return ComponentResult(
            ComponentName.LANDING.value, status, reporting_currency, pricing_date,
            amount, SourceType.PUBLIC_TARIFF, tariff.source_reference, tariff.source_id, tariff.valid_from,
            tariff.calculation_method, breakdown, output.assumptions, warnings,
            zero_by_tariff_rule=amount == 0,
        )


def calculate_landing_component(
    parts: list[ComponentResult], reporting_currency: str, pricing_date: date
) -> ComponentResult:
    """Origin take-off + destination landing; unavailable unless both are calculated."""
    return combine_parts(ComponentName.LANDING.value, parts, reporting_currency, pricing_date,
                         "sum of origin take-off and destination landing movement charges under each airport's tariff")


def parse_tariff_parameters(text: str) -> dict[str, Any]:
    return json.loads(text)
