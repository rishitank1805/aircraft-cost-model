"""EUROCONTROL en-route charges and shared navigation-charge helpers.

Verified methodology (Conditions of Application of the Route Charges System,
Doc. 21.60.02, Nov 2021, Arts. 3-7; CRCO Customer Guide to Charges, April 2026,
A.1.2):

    r_i = t_i x N_i,  N_i = d_i x p,  route charge = sum over charging zones
    d_i = (great-circle km in zone i between aerodrome / entry / exit points of the
           actual route as recorded by the Network Manager, minus 20 km per
           take-off and per landing in the zone) / 100
    p   = sqrt(MTOW_t / 50), MTOW_t = highest certificated MTOW in the Aircraft
          Flight Manual, in metric tonnes "taken to one decimal"; p "taken to two
          decimal places"
    t_i = national + administrative unit rate, EUR, "applicable as from 1st
          January of each year" (monthly FX adjustment only for non-EMU states)

Unresolved interpretations (recorded on every result, not treated as verified):

- "taken to one decimal" / "taken to two decimal places" does not state a
  rounding direction; round half up is implemented and the truncation result
  is reported alongside;
- no rounding is stated for d_i; d_i is not rounded;
- no rounding is stated for r_i or the sum; the total is rounded once to cents;
- valid_to = 31 December is inferred from the annual cycle.

MTOW: an official-style calculation requires the certificated MTOW. The
OpenAP type-level MTOW is accepted only as an explicit scenario assumption
(status ``calculated_assumption``); otherwise ``missing_required_input``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from aircraft_cost_model.costs.coverage import Assumption, ComponentName, ComponentResult, ComponentStatus, SourceType
from aircraft_cost_model.costs.currency import RateProvider, convert, plain, round_money
from aircraft_cost_model.costs.exceptions import CostInputError, ObservationUnavailableError

TERMINAL_DEDUCTION_KM = Decimal(20)
METHOD = "EUROCONTROL CoA Arts. 3-7: sum over zones of t_i x d_i x p"
VERIFIED = "verified_against_source"

MTOW_CERTIFICATED = "certificated"
MTOW_TYPE_SCENARIO = "type_level_scenario"

FORMULA_SQRT = "sqrt_mtow_over_50"
FORMULA_POW_07 = "mtow_over_50_pow_0_7"
EXPONENT_07 = Decimal("0.7")

ROUNDING_INTERPRETATION = Assumption(
    "unresolved_interpretation_rounding",
    "'taken to one decimal' (MTOW t) and 'taken to two decimal places' (weight factor) implemented as round half "
    "up; the source states no rounding direction (truncation alternative reported in the breakdown)",
    None, "unresolved_interpretation", "CoA Art. 6; Customer Guide A.1.2.2; terminal rules (LF circular Art. 4, DFS 3)",
)
DISTANCE_INTERPRETATION = Assumption(
    "unresolved_interpretation_distance_rounding",
    "distance factor d_i not rounded; per-zone charges not rounded; total rounded once to cents half up "
    "(the CoA states no rounding for d_i or charges)",
    None, "unresolved_interpretation", "CoA Arts. 3-5",
)
VALIDITY_INTERPRETATION = Assumption(
    "unresolved_interpretation_rate_validity",
    "unit-rate validity ends 31 December (inferred from 'applicable as from 1st January of each year'; "
    "no end date is published)",
    None, "unresolved_interpretation", "Customer Guide A.1.2.3; Information Circulars",
)


@dataclass(frozen=True)
class MtowBasis:
    """The MTOW used for navigation weight factors and how it was obtained."""

    kg: Decimal | None
    basis: str | None
    description: str

    @classmethod
    def resolve(cls, certificated_kg: Decimal | None, type_level_kg: Decimal | None,
                allow_type_level_scenario: bool) -> "MtowBasis":
        if certificated_kg is not None:
            if certificated_kg <= 0:
                raise CostInputError("Certificated MTOW must be positive")
            return cls(certificated_kg, MTOW_CERTIFICATED, "user-supplied highest certificated MTOW (AFM)")
        if allow_type_level_scenario and type_level_kg is not None:
            return cls(type_level_kg, MTOW_TYPE_SCENARIO,
                       "SCENARIO: OpenAP type-level MTOW (aircraft_type.mtow_kg), not the certificated MTOW of a "
                       "specific aircraft")
        return cls(None, None, "certificated MTOW not supplied")

    @property
    def is_scenario(self) -> bool:
        return self.basis == MTOW_TYPE_SCENARIO

    def assumption(self) -> Assumption:
        return Assumption("mtow_for_weight_factor_kg", plain(self.kg) if self.kg is not None else "n/a", "kg",
                          "user_input" if self.basis == MTOW_CERTIFICATED else "scenario_assumption",
                          self.description)


@dataclass(frozen=True)
class WeightFactor:
    formula: str
    mtow_tonnes: Decimal
    value: Decimal
    alternative_truncated: Decimal

    def to_dict(self) -> dict[str, str]:
        return {"step": "weight factor", "formula": self.formula, "mtow_t": plain(self.mtow_tonnes),
                "value": plain(self.value), "alternative_if_truncated": plain(self.alternative_truncated)}


def weight_factor(mtow_kg: Decimal, formula: str = FORMULA_SQRT) -> WeightFactor:
    """Weight factor with round-half-up (implemented) and truncation (alternative) interpretations."""
    if mtow_kg <= 0:
        raise CostInputError("MTOW must be positive")
    tonnes = mtow_kg / Decimal(1000)
    results = []
    for mode in (ROUND_HALF_UP, ROUND_DOWN):
        t = tonnes.quantize(Decimal("0.1"), rounding=mode)
        ratio = t / Decimal(50)
        if formula == FORMULA_SQRT:
            raw = ratio.sqrt()
        elif formula == FORMULA_POW_07:
            raw = ratio ** EXPONENT_07
        else:
            raise CostInputError(f"Unknown service-unit formula {formula!r}")
        results.append((t, raw.quantize(Decimal("0.01"), rounding=mode)))
    (t_up, p_up), (_, p_down) = results
    label = "sqrt(MTOW_t / 50)" if formula == FORMULA_SQRT else "(MTOW_t / 50) ^ 0.7"
    return WeightFactor(label, t_up, p_up, p_down)


@dataclass(frozen=True)
class ZoneSegment:
    """Explicit charging-zone input for one flight."""

    zone: str
    great_circle_km: Decimal
    takeoffs: int
    landings: int

    def validate(self) -> None:
        if not self.zone:
            raise CostInputError("Charging zone is required")
        if self.great_circle_km < 0:
            raise CostInputError(f"{self.zone}: distance must not be negative")
        if self.takeoffs not in (0, 1) or self.landings not in (0, 1):
            raise CostInputError(f"{self.zone}: take-offs and landings per zone must be 0 or 1")


@dataclass(frozen=True)
class ZoneRate:
    zone: str
    zone_name: str
    unit_rate: Decimal
    currency: str
    valid_from: date
    valid_to: date | None
    source_id: int | None
    source_reference: str
    verification_status: str


def distance_factor(segment: ZoneSegment) -> tuple[Decimal, Decimal]:
    """Return ``(chargeable km, d_i)``; chargeable km cannot fall below zero."""
    deduction = TERMINAL_DEDUCTION_KM * (segment.takeoffs + segment.landings)
    km = max(segment.great_circle_km - deduction, Decimal(0))
    return km, km / Decimal(100)


def validate_segments(segments: list[ZoneSegment], great_circle_km: Decimal | None) -> None:
    """Consistency checks for one single-leg flight (circular flights, CoA Art. 5.2, are not supported)."""
    for segment in segments:
        segment.validate()
    zones = [s.zone for s in segments]
    if len(zones) != len(set(zones)):
        raise CostInputError("Each charging zone may appear once (sum re-entries into one distance)")
    if sum(s.takeoffs for s in segments) != 1 or sum(s.landings for s in segments) != 1:
        raise CostInputError("Exactly one take-off and one landing must be assigned to the charging zones")
    if great_circle_km is not None:
        total = sum((s.great_circle_km for s in segments), Decimal(0))
        if total < great_circle_km * Decimal("0.999"):
            raise CostInputError(
                f"Zone distances sum to {total} km, less than the airport-to-airport great circle {great_circle_km:.1f} km"
            )


def calculate_navigation_charge(
    *,
    segments: list[ZoneSegment],
    rates: dict[str, ZoneRate | None],
    mtow: MtowBasis,
    reporting_currency: str,
    pricing_date: date,
    fx: RateProvider,
    zone_distance_source: str = "user-supplied zone distances",
) -> ComponentResult:
    """En-route charges summed over charging zones; explicit unavailable statuses otherwise."""
    name = ComponentName.NAVIGATION.value
    warnings = ["En-route charges only; terminal navigation charges are the separate terminal_navigation component"]
    interpretations = [ROUNDING_INTERPRETATION, DISTANCE_INTERPRETATION, VALIDITY_INTERPRETATION]
    if not segments:
        return ComponentResult(
            name, ComponentStatus.UNAVAILABLE_ROUTE_GEOMETRY, reporting_currency, pricing_date,
            calculation_method=METHOD,
            warnings=warnings + ["Charging-zone distances are unknown (route as recorded by the Network Manager is "
                                 "not available); no charge is estimated"],
            missing_inputs=["charging-zone distances"],
        )
    if mtow.kg is None:
        return ComponentResult(name, ComponentStatus.MISSING_REQUIRED_INPUT, reporting_currency, pricing_date,
                               calculation_method=METHOD, warnings=warnings + [
                                   "Route charges use the highest certificated MTOW from the AFM; supply it "
                                   "(--certificated-mtow-kg) or opt into the type-level scenario"],
                               missing_inputs=["certificated MTOW"])
    missing = [s.zone for s in segments if rates.get(s.zone) is None]
    unverified = [s.zone for s in segments if rates.get(s.zone) is not None and rates[s.zone].verification_status != VERIFIED]
    if missing or unverified:
        notes = []
        if missing:
            notes.append(f"No unit rate in force on {pricing_date} for zone(s) {missing}")
        if unverified:
            notes.append(f"Unit rate for zone(s) {unverified} is pending review and is not priced")
        return ComponentResult(name, ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF, reporting_currency, pricing_date,
                               calculation_method=METHOD, warnings=warnings + notes,
                               missing_inputs=[f"unit rate {z}" for z in missing + unverified])
    wf = weight_factor(mtow.kg, FORMULA_SQRT)
    breakdown = [wf.to_dict()]
    total, total_alt = Decimal(0), Decimal(0)
    for segment in segments:
        rate = rates[segment.zone]
        km, d = distance_factor(segment)
        charge, charge_alt = rate.unit_rate * d * wf.value, rate.unit_rate * d * wf.alternative_truncated
        try:
            conv = convert(charge, rate.currency, reporting_currency, pricing_date, fx)
            conv_alt = convert(charge_alt, rate.currency, reporting_currency, pricing_date, fx)
        except ObservationUnavailableError as exc:
            return ComponentResult(name, ComponentStatus.UNAVAILABLE_PRICE, reporting_currency, pricing_date,
                                   calculation_method=METHOD, breakdown=breakdown,
                                   warnings=warnings + [f"Exchange rate unavailable: {exc}"])
        total += conv.amount_out
        total_alt += conv_alt.amount_out
        breakdown.append({
            "zone": segment.zone, "zone_name": rate.zone_name, "great_circle_km": plain(segment.great_circle_km),
            "takeoffs": segment.takeoffs, "landings": segment.landings, "chargeable_km": plain(km),
            "distance_factor": plain(d), "unit_rate": plain(rate.unit_rate), "rate_currency": rate.currency,
            "rate_valid_from": rate.valid_from.isoformat(), "rate_verification": rate.verification_status,
            "charge": plain(charge), "charge_reporting_currency": plain(conv.amount_out),
        })
        breakdown.extend(s for s in conv.steps if s.get("step") != "no conversion")
    amount = round_money(total)
    breakdown.append({"step": "rounding", "formula": "round half up to 0.01", "value": plain(amount),
                      "alternative_if_truncated": plain(round_money(total_alt))})
    status = ComponentStatus.CALCULATED_ASSUMPTION if mtow.is_scenario else ComponentStatus.CALCULATED_PUBLIC_TARIFF
    if mtow.is_scenario:
        warnings.append("Scenario: weight factor uses the OpenAP type-level MTOW, not a certificated MTOW")
    assumptions = [
        Assumption("zone_distances", zone_distance_source, "km", "user_input",
                   "CoA Art. 5 requires the route as recorded by the Network Manager"),
        mtow.assumption(), *interpretations,
    ]
    sources = sorted({rates[s.zone].source_reference for s in segments})
    return ComponentResult(
        name, status, reporting_currency, pricing_date, amount, SourceType.PUBLIC_TARIFF, "; ".join(sources),
        rates[segments[0].zone].source_id, rates[segments[0].zone].valid_from, METHOD, breakdown, assumptions,
        warnings, zero_by_tariff_rule=amount == 0,
    )
