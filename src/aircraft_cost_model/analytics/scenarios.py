"""Reproducible scenario variations recalculated through the Part 3 and Part 4 engines.

A variation never edits a saved estimate, a scenario file or a saved
scenario row. It builds a modified *copy* of the base scenario (new content
hash) or a recalculated Part 3 fuel component, and runs the Part 4
calculator again.

Exposed parameters (only those the engines can recalculate correctly):

========================  ==============================================  ===========================
parameter                 recalculated through                            change types
========================  ==============================================  ===========================
fuel_price                Part 3 fuel engine (benchmark price changed)    percent, absolute, value
fuel_burn                 Part 3 fuel engine (block fuel x multiplier)    percent, value (multiplier)
airframe_maintenance_rate maintenance.airframe.rate_per_block_hour        percent, absolute, value
airframe_cycle_rate       maintenance.airframe.rate_per_flight_cycle      percent, absolute, value
engine_maintenance_rate   maintenance.engine.rate_per_engine_flight_hour  percent, absolute, value
llp_reserve               maintenance.engine_llp.reserve_per_engine_cycle percent, absolute, value
crew_compensation         crew salary roles / crew rate per block hour    percent (absolute/value if one input)
annual_block_hours        utilization.annual_aircraft_block_hours         percent, absolute, value
annual_flights            utilization.annual_flights                      percent, absolute, value
annual_utilization        both utilization inputs together                percent
insurance_cost            every insurance premium / rate input            percent (absolute/value if one input)
lease_payment             operating_lease.monthly_payment                 percent, absolute, value
depreciable_value         depreciation.depreciable_value                  percent, absolute, value
residual_value            depreciation.residual_value                     percent, absolute, value
useful_life               depreciation.useful_life_years                  percent, absolute, value
financing_interest_rate   financing.annual_interest_rate                  percent, absolute, value
administration_cost       indirect.administration.rate / annual_amount    percent, absolute, value
cargo_sales_cost          indirect.cargo_sales.rate                       percent, absolute, value
ga_overhead               indirect.general_administrative.*               percent, absolute, value
revenue_cargo_payload     analytics payload (+ cargo-sales tonnes input)  percent, absolute, value
========================  ==============================================  ===========================

The aircraft *acquisition value* is not exposed: Part 4 records it but only
the depreciable and residual values drive the depreciation charge, so a
change to it alone would change nothing. ``fuel_burn`` is a post-flight
consumption stress test, not a flight simulation: flight mass, fuel
planning and feasibility are not re-evaluated. Payload changes are a
fixed-performance economic sensitivity unless Part 2 is rerun.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics import ANALYTICS_VERSION
from aircraft_cost_model.analytics.cases import AnalyticsInputError, CostCase, calculate_case, flight_facts
from aircraft_cost_model.analytics.metrics import DistanceInput, PayloadInput, UnitMetricsResult, unit_metrics
from aircraft_cost_model.costs.coverage import Assumption, ComponentResult, ComponentStatus
from aircraft_cost_model.costs.currency import DatabaseRateProvider, plain, to_decimal
from aircraft_cost_model.costs.fuel_cost import FuelPriceObservation, calculate_fuel_cost
from aircraft_cost_model.costs import repository
from aircraft_cost_model.costs.exceptions import CostCalculationError
from aircraft_cost_model.fullcost.scenario import Scenario, ScenarioError, parse_scenario
from aircraft_cost_model.ingestion.fuel_prices import DESCRIPTION as EIA_DESCRIPTION
from aircraft_cost_model.models import CostComponent, FuelPrice, VariableCostEstimate

CHANGE_TYPES = ("percent", "absolute", "value")


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    description: str
    patterns: tuple[str, ...]  # regexes over scenario value paths
    change_types: tuple[str, ...] = CHANGE_TYPES
    engine: str = "part4_scenario"  # part4_scenario | part3_fuel | analytics_payload


PARAMETERS: dict[str, ParameterSpec] = {p.name: p for p in (
    ParameterSpec("fuel_price", "benchmark jet fuel price used by the Part 3 fuel engine", (), engine="part3_fuel"),
    ParameterSpec("fuel_burn", "post-flight consumption stress test: block fuel x multiplier (not a flight "
                  "simulation)", (), ("percent", "value"), engine="part3_fuel"),
    ParameterSpec("airframe_maintenance_rate", "airframe maintenance rate per block hour",
                  (r"maintenance\.airframe\.rate_per_block_hour",)),
    ParameterSpec("airframe_cycle_rate", "airframe maintenance rate per flight cycle",
                  (r"maintenance\.airframe\.rate_per_flight_cycle",)),
    ParameterSpec("engine_maintenance_rate", "engine maintenance rate per engine flight hour",
                  (r"maintenance\.engine\.rate_per_engine_flight_hour",)),
    ParameterSpec("llp_reserve", "LLP reserve per engine cycle", (r"maintenance\.engine_llp\.reserve_per_engine_cycle",)),
    ParameterSpec("crew_compensation", "crew annual compensation (all roles) or crew rate per block hour",
                  (r"crew\.salaries\.roles\[\d+\]\.annual_compensation", r"crew\.salaries\.rate_per_block_hour")),
    ParameterSpec("annual_block_hours", "annual aircraft block hours (allocation denominator)",
                  (r"utilization\.annual_aircraft_block_hours",)),
    ParameterSpec("annual_flights", "annual flights (allocation denominator)", (r"utilization\.annual_flights",)),
    ParameterSpec("annual_utilization", "annual block hours and annual flights changed together (constant average "
                  "block time per flight)", (r"utilization\.annual_aircraft_block_hours", r"utilization\.annual_flights"),
                  ("percent",)),
    ParameterSpec("insurance_cost", "insurance premiums, premium rates or rate per block hour",
                  (r"insurance\.coverages\[\d+\]\.annual_premium", r"insurance\.coverages\[\d+\]\.annual_premium_rate",
                   r"insurance\.rate_per_block_hour")),
    ParameterSpec("lease_payment", "operating lease monthly payment", (r"operating_lease\.monthly_payment",)),
    ParameterSpec("depreciable_value", "depreciable value (drives depreciation with residual value and life)",
                  (r"depreciation\.depreciable_value",)),
    ParameterSpec("residual_value", "residual value", (r"depreciation\.residual_value",)),
    ParameterSpec("useful_life", "useful life in years", (r"depreciation\.useful_life_years",)),
    ParameterSpec("financing_interest_rate", "annual financing interest rate", (r"financing\.annual_interest_rate",)),
    ParameterSpec("administration_cost", "administration rate or annual amount",
                  (r"indirect\.administration\.rate", r"indirect\.administration\.annual_amount")),
    ParameterSpec("cargo_sales_cost", "cargo sales rate", (r"indirect\.cargo_sales\.rate",)),
    ParameterSpec("ga_overhead", "general & administrative rate or annual amount",
                  (r"indirect\.general_administrative\.rate", r"indirect\.general_administrative\.annual_amount")),
    ParameterSpec("revenue_cargo_payload", "revenue cargo payload (fixed-performance economic sensitivity)",
                  (r"indirect\.cargo_sales\.revenue_cargo_tonnes",), engine="analytics_payload"),
)}

FIXED_PERFORMANCE_NOTE = ("fixed-performance economic sensitivity: the Part 2 flight performance (fuel burn, block "
                          "time, mass checks) is not rerun for the changed payload")
FUEL_BURN_NOTE = ("post-flight consumption stress test: block fuel is scaled after the flight; flight mass, fuel "
                  "planning and feasibility are not re-evaluated, so this is not a physically validated simulation")


@dataclass(frozen=True)
class Variation:
    parameter: str
    change_type: str
    change: Decimal

    def __post_init__(self) -> None:
        if self.parameter not in PARAMETERS:
            raise AnalyticsInputError(f"unknown parameter {self.parameter!r}; choose from {sorted(PARAMETERS)}")
        if self.change_type not in PARAMETERS[self.parameter].change_types:
            raise AnalyticsInputError(f"{self.parameter} supports change types {PARAMETERS[self.parameter].change_types}")
        if not isinstance(self.change, Decimal):
            raise TypeError("change must be a Decimal")

    @property
    def is_identity(self) -> bool:
        return self.change_type in ("percent", "absolute") and self.change == 0

    def apply(self, value: Decimal) -> Decimal:
        if self.change_type == "percent":
            return value * (1 + self.change / 100)
        if self.change_type == "absolute":
            return value + self.change
        return self.change

    def label(self) -> str:
        suffix = {"percent": "%", "absolute": " (absolute)", "value": " (value)"}[self.change_type]
        sign = "+" if self.change_type != "value" and self.change > 0 else ""
        return f"{self.parameter} {sign}{plain(self.change)}{suffix}"

    def to_dict(self) -> dict[str, str]:
        return {"parameter": self.parameter, "change_type": self.change_type, "change": plain(self.change)}


@dataclass(frozen=True)
class ModifiedValue:
    parameter: str
    path: str
    original_value: Decimal | None
    modified_value: Decimal | None
    unit: str
    original_source_type: str
    source_type: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {k: (plain(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


@dataclass
class BaseCase:
    """What a variation starts from: a flight, its Part 3 estimate, a scenario and analytics inputs."""

    flight_estimate_id: int
    variable_cost_estimate_id: int
    scenario: Scenario
    distance: DistanceInput
    payload: PayloadInput = field(default_factory=lambda: PayloadInput(None))
    base_scenario_id: int | None = None
    full_cost_estimate_id: int | None = None
    label: str = "base"


@dataclass
class VariationResult:
    label: str
    variations: tuple[Variation, ...]
    modified: list[ModifiedValue]
    case: CostCase | None
    metrics: UnitMetricsResult | None
    status: str  # calculated | calculation_error
    calculated_at: str
    input_hash: str
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def component_amounts(self) -> dict[str, Decimal | None]:
        return {n: c.amount for n, c in self.case.summary.components.items()} if self.case else {}

    def totals(self) -> dict[str, Decimal | None]:
        if self.case is None:
            return {}
        s = self.case.summary
        from aircraft_cost_model.fullcost.aggregate import Category
        return {"direct_variable": s.category(Category.DIRECT_VARIABLE).calculated_subtotal,
                "coc": s.coc[0], "toc": s.toc[0], "total_costs": s.total[0],
                "complete_coc": s.coc[1], "complete_toc": s.toc[1], "complete_total_costs": s.total[1]}

    def to_dict(self) -> dict[str, Any]:
        def money(v):
            return None if v is None else plain(v)
        s = self.case.summary if self.case else None
        return {
            "label": self.label, "variations": [v.to_dict() for v in self.variations],
            "modified": [m.to_dict() for m in self.modified], "status": self.status, "error": self.error,
            "calculated_at": self.calculated_at, "input_hash": self.input_hash,
            "components": {n: {"amount": money(c.amount), "status": c.status.value}
                           for n, c in (s.components.items() if s else [])},
            "totals": {k: money(v) for k, v in self.totals().items()},
            "cost_coverage": s.cost_coverage_status if s else "calculation_error",
            "operational_validity": s.operational_validity if s else None,
            "source_quality": s.source_quality_summary if s else None,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Part 3 fuel recalculation
# ---------------------------------------------------------------------------

def _fuel_inputs(session: Session, variable_cost_estimate_id: int) -> tuple[CostComponent, FuelPriceObservation, Decimal,
                                                                             Decimal, str]:
    row = session.scalar(select(CostComponent).where(CostComponent.variable_cost_estimate_id == variable_cost_estimate_id,
                                                     CostComponent.component_name == "fuel"))
    if row is None or not ComponentStatus(row.status).is_calculated:
        raise AnalyticsInputError(f"variable_cost_estimate {variable_cost_estimate_id} has no calculated fuel "
                                  "component; fuel variations need a priced base")
    steps = json.loads(row.breakdown_json)
    price_step = next(s for s in steps if s.get("step") == "price")
    block_fuel = Decimal(next(s for s in steps if s.get("step") == "block fuel")["value"])
    assumptions = json.loads(row.assumptions_json)
    density_a = next(a for a in assumptions if a["name"] == "fuel_density_kg_per_l")
    observation_date = datetime.strptime(price_step["observation_date"], "%Y-%m-%d").date()
    price_row = session.scalar(select(FuelPrice).where(FuelPrice.series_identifier == price_step["series"],
                                                       FuelPrice.observation_date == observation_date,
                                                       FuelPrice.observation_period == price_step["observation_period"]))
    if price_row is None or price_row.price != Decimal(price_step["value"]):
        raise AnalyticsInputError("the fuel price observation used by the saved Part 3 estimate is no longer in the "
                                  "database unchanged; the fuel component cannot be reproduced")
    observation = FuelPriceObservation(
        price_row.series_identifier, EIA_DESCRIPTION, price_row.observation_date, price_row.observation_period,
        price_row.price, price_row.currency, price_row.price_unit, int(price_step.get("gap_days") or 0),
        price_row.source_id, repository.source_label(session, price_row.source_id))
    return row, observation, block_fuel, Decimal(density_a["value"]), density_a["source_type"]


def recalculate_fuel(session: Session, variable_cost_estimate_id: int, variations: tuple[Variation, ...]
                     ) -> tuple[ComponentResult | None, list[ModifiedValue], list[str]]:
    """Recalculate fuel through the Part 3 engine; returns ``None`` when no fuel variation applies."""
    fuel_vars = [v for v in variations if PARAMETERS[v.parameter].engine == "part3_fuel"]
    if not fuel_vars:
        return None, [], []
    estimate = session.get(VariableCostEstimate, variable_cost_estimate_id)
    row, observation, block_fuel, density, density_source = _fuel_inputs(session, variable_cost_estimate_id)
    rates = DatabaseRateProvider(session, max_staleness_days=7)

    def price(obs: FuelPriceObservation, kg: Decimal) -> ComponentResult:
        return calculate_fuel_cost(block_fuel_kg=kg, density_kg_per_l=density, density_source=density_source, price=obs,
                                   price_unavailable_reason=None, reporting_currency=estimate.reporting_currency,
                                   pricing_date=estimate.pricing_date, rates=rates)

    base = price(observation, block_fuel)
    if base.amount != row.amount:
        raise AnalyticsInputError(f"Part 3 fuel engine reproduces {base.amount}, not the saved {row.amount}; "
                                  "refusing to vary an irreproducible base")
    modified: list[ModifiedValue] = []
    warnings: list[str] = []
    new_obs, new_kg = observation, block_fuel
    for v in fuel_vars:
        if v.is_identity:
            continue
        if v.parameter == "fuel_price":
            new_price = v.apply(observation.price)
            if new_price <= 0:
                raise AnalyticsInputError("varied fuel price must be positive")
            new_obs = replace(new_obs, price=new_price)
            modified.append(ModifiedValue(v.parameter, f"fuel_price[{observation.series_identifier}]", observation.price,
                                          new_price, observation.price_unit, "public_market_benchmark", "user_assumption",
                                          "illustrative variation level, not a price forecast"))
        else:
            multiplier = (1 + v.change / 100) if v.change_type == "percent" else v.change
            if multiplier <= 0:
                raise AnalyticsInputError("fuel burn multiplier must be positive")
            new_kg = block_fuel * multiplier
            modified.append(ModifiedValue(v.parameter, "flight_estimate.block_fuel_kg", block_fuel, new_kg, "kg",
                                          "modelled_estimate", "user_assumption", FUEL_BURN_NOTE))
            warnings.append(FUEL_BURN_NOTE)
    if not modified:
        return base, [], []
    result = price(new_obs, new_kg)
    if not result.is_calculated:
        return result, modified, warnings
    result = replace(
        result, status=ComponentStatus.CALCULATED_ASSUMPTION,
        calculation_method=f"Part 3 fuel engine with scenario variation: {result.calculation_method}",
        assumptions=result.assumptions + [Assumption(m.parameter, plain(m.modified_value), m.unit, "user_assumption",
                                                     m.note) for m in modified],
        warnings=result.warnings + ["scenario variation: the fuel price or quantity is not the observed benchmark"]
        + warnings,
    )
    return result, modified, warnings


# ---------------------------------------------------------------------------
# Part 4 scenario variation
# ---------------------------------------------------------------------------

_PATH_TOKEN = re.compile(r"([a-z_]+)(?:\[(\d+)\])?")


def _value_object(data: dict[str, Any], path: str) -> dict[str, Any]:
    node: Any = data
    for part in path.split("."):
        key, index = _PATH_TOKEN.fullmatch(part).groups()
        node = node[key]
        if index is not None:
            node = node[int(index)]
    return node


def matching_paths(scenario: Scenario, parameter: str) -> list[str]:
    patterns = [re.compile(p) for p in PARAMETERS[parameter].patterns]
    return sorted(p for p in scenario.values if any(r.fullmatch(p) for r in patterns))


def vary_scenario(scenario: Scenario, variations: tuple[Variation, ...]) -> tuple[Scenario, list[ModifiedValue]]:
    """Return a modified copy of ``scenario`` (the base object and its file are untouched)."""
    data = copy.deepcopy(scenario.raw)
    modified: list[ModifiedValue] = []
    for v in variations:
        spec = PARAMETERS[v.parameter]
        if spec.engine == "part3_fuel":
            continue
        paths = matching_paths(scenario, v.parameter)
        if not paths:
            if spec.engine == "analytics_payload":
                continue
            raise AnalyticsInputError(f"{v.parameter} does not apply to scenario {scenario.name!r}: none of "
                                      f"{list(spec.patterns)} is present")
        if len(paths) > 1 and v.change_type != "percent":
            raise AnalyticsInputError(f"{v.parameter} maps to {len(paths)} inputs ({paths}); only percent changes "
                                      "are unambiguous")
        if v.is_identity:
            continue
        for path in paths:
            original = scenario.values[path]
            new_value = v.apply(original.value)
            obj = _value_object(data, path)
            obj["value"] = plain(new_value)
            obj["source_type"] = "user_assumption"
            obj["notes"] = (f"Part 5 scenario variation ({v.label()}) of {plain(original.value)} {original.unit} "
                            f"[{original.source_type}]")
            modified.append(ModifiedValue(v.parameter, path, original.value, new_value, original.unit,
                                          original.source_type, "user_assumption",
                                          FIXED_PERFORMANCE_NOTE if spec.engine == "analytics_payload" else
                                          "illustrative variation level, not a forecast"))
    if not modified:
        return scenario, []
    data["scenario_version"] = f"{scenario.scenario_version}+variation"
    data["name"] = f"{scenario.name} [{', '.join(v.label() for v in variations)}]"
    try:
        return parse_scenario(data, source_path=None), modified
    except ScenarioError as exc:
        raise AnalyticsInputError(f"variation produces an invalid scenario: {exc}") from exc


def _vary_payload(payload: PayloadInput, variations: tuple[Variation, ...]) -> tuple[PayloadInput, list[ModifiedValue]]:
    out, modified = payload, []
    for v in variations:
        if v.parameter != "revenue_cargo_payload" or v.is_identity:
            continue
        if payload.revenue_tonnes is None and v.change_type != "value":
            raise AnalyticsInputError("revenue_cargo_payload percent/absolute changes need an explicit base payload")
        new = v.apply(payload.revenue_tonnes if payload.revenue_tonnes is not None else Decimal(0))
        out = replace(out, revenue_tonnes=new, source_type="user_assumption")
        modified.append(ModifiedValue(v.parameter, "analytics.revenue_cargo_payload", payload.revenue_tonnes, new,
                                      "tonnes", payload.source_type, "user_assumption", FIXED_PERFORMANCE_NOTE))
    return out, modified


def run_variation(session: Session, base: BaseCase, variations: tuple[Variation, ...], label: str | None = None
                  ) -> VariationResult:
    """Recalculate one variation (or the base when ``variations`` is empty) without saving anything."""
    params = [v.parameter for v in variations]
    if len(params) != len(set(params)):
        raise AnalyticsInputError("each parameter may appear only once in a variation")
    label = label or (", ".join(v.label() for v in variations) if variations else "base")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    warnings: list[str] = []
    try:
        fuel, fuel_mods, fuel_warn = recalculate_fuel(session, base.variable_cost_estimate_id, variations)
        scenario, scenario_mods = vary_scenario(base.scenario, variations)
        payload, payload_mods = _vary_payload(base.payload, variations)
        if payload_mods:
            warnings.append(FIXED_PERFORMANCE_NOTE)
        overrides = {"fuel": fuel} if fuel is not None and fuel_mods else None
        case, result = calculate_case(session, base.flight_estimate_id, base.variable_cost_estimate_id, scenario,
                                      label=label, part3_overrides=overrides)
        metrics = unit_metrics(case, base.distance, payload)
        modified = fuel_mods + scenario_mods + payload_mods
        warnings += fuel_warn
        status, error = "calculated", None
    except (AnalyticsInputError, CostCalculationError) as exc:
        case, metrics, modified, status, error = None, None, [], "calculation_error", str(exc)
        result = None
    payload_hash = {"base_scenario": base.scenario.content_hash, "flight": base.flight_estimate_id,
                    "variable": base.variable_cost_estimate_id, "variations": [v.to_dict() for v in variations],
                    "distance": [base.distance.basis.value, str(base.distance.actual_nm)],
                    "payload": [str(base.payload.revenue_tonnes), base.payload.hypothetical_cargo,
                                str(base.payload.available_tonnes)],
                    "result": result.input_hash if result else error, "version": ANALYTICS_VERSION}
    input_hash = hashlib.sha256(json.dumps(payload_hash, sort_keys=True, default=str).encode()).hexdigest()
    return VariationResult(label, tuple(variations), modified, case, metrics, status, now, input_hash,
                           warnings + (metrics.warnings if metrics else []), error)


def base_from_saved(session: Session, full_cost_estimate_id: int, distance: DistanceInput,
                    payload: PayloadInput | None = None) -> BaseCase:
    from aircraft_cost_model.analytics.cases import load_saved_case

    saved = load_saved_case(session, full_cost_estimate_id)
    flight_facts(session, saved.facts.flight_estimate_id)
    return BaseCase(saved.facts.flight_estimate_id, saved.variable_cost_estimate_id, saved.scenario, distance,
                    payload or PayloadInput(None), saved.scenario_id, full_cost_estimate_id,
                    label=f"full_cost_estimate {full_cost_estimate_id}")


def parse_levels(text: str) -> list[Decimal]:
    """Parse ``"-20,-10,0,10,20"`` into exact decimals (no floats)."""
    try:
        levels = [Decimal(part.strip()) for part in text.split(",") if part.strip()]
    except Exception as exc:  # decimal.InvalidOperation
        raise AnalyticsInputError(f"invalid level list {text!r}") from exc
    if not levels:
        raise AnalyticsInputError("at least one level is required")
    return levels


__all__ = ["PARAMETERS", "Variation", "BaseCase", "VariationResult", "ModifiedValue", "run_variation",
           "vary_scenario", "recalculate_fuel", "base_from_saved", "parse_levels", "to_decimal"]
