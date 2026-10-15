"""Maintenance: airframe, engine and engine LLP as three separate components.

    Airframe = block hours x rate per block hour [+ flight cycles x rate per cycle]
    Engine   = engines x engine hours x rate per engine flight hour [+ engines x engine cycles x rate per engine cycle]
    LLP      = engines x engine cycles x LLP reserve per engine cycle   (economic accrual, not a cash payment)

Double-counting controls (scenario flags are mandatory, never defaulted):

- ``maintenance.airframe.covers`` lists what the airframe rate includes
  (``airframe`` and optionally ``engine`` / ``engine_llp`` for an all-inclusive
  rate). Included components become ``not_applicable``; supplying them as well
  is ``failed_validation``.
- ``maintenance.engine.includes_llp`` marks an engine rate that already
  includes LLP reserves (LLP becomes ``not_applicable``).
- ``hourly_rate_includes_cycle_costs``: when true a cycle rate must not be
  given; when false a cycle rate is required.
- ``maintenance.engine.engine_hours_basis`` must be chosen explicitly:
  ``airborne_hours`` (lift-off to touchdown), ``engine_running_estimate``
  (block time, Part 2 assumes all engines run while taxiing) or
  ``block_hours_proxy`` (explicitly labelled proxy).

This is a cost model, not a maintenance-planning or airworthiness system.
"""

from __future__ import annotations

from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentResult
from aircraft_cost_model.costs.currency import RateProvider, plain
from aircraft_cost_model.fullcost.common import FlightBasis, InputReader, failed, not_applicable
from aircraft_cost_model.fullcost.scenario import Scenario

AIRFRAME, ENGINE, LLP = "airframe_maintenance", "engine_maintenance", "engine_llp"
COVER_KEYS = {"airframe", "engine", "engine_llp"}
ENGINE_HOUR_BASES = ("airborne_hours", "engine_running_estimate", "block_hours_proxy")


def _cycle_part(reader: InputReader, section: str, cycles: Decimal, cycle_unit: str) -> Decimal | None:
    """Cycle-rate contribution honouring ``hourly_rate_includes_cycle_costs``."""
    flag = reader.scenario.flag(f"{section}.hourly_rate_includes_cycle_costs")
    rate_present = reader.scenario.value(f"{section}.rate_per_{cycle_unit}") is not None
    if flag is None:
        reader.missing.append(f"{section}.hourly_rate_includes_cycle_costs")
        return None
    if flag is True:
        if rate_present:
            reader.fail(f"{section}: a cycle rate is given although the hourly rate includes cycle costs")
        return Decimal(0)
    rate = reader.get(f"{section}.rate_per_{cycle_unit}", cycle_unit)
    if rate is None:
        return None
    amount = cycles * rate
    reader.breakdown.append({"step": f"{cycle_unit} part", "formula": f"{plain(cycles)} x {plain(rate)}",
                             "value": plain(amount)})
    return amount


def covers(scenario: Scenario) -> set[str] | None:
    value = scenario.flag("maintenance.airframe.covers")
    return set(value) if isinstance(value, list) else None


def airframe_maintenance(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    reader = InputReader(AIRFRAME, scenario, basis, fx)
    if scenario.section("maintenance", "airframe") is None:
        reader.missing.append("maintenance.airframe")
        return reader.result(None, "airframe maintenance")
    cov = covers(scenario)
    if cov is None:
        reader.missing.append("maintenance.airframe.covers")
    elif "airframe" not in cov or not cov <= COVER_KEYS:
        reader.fail(f"maintenance.airframe.covers must include 'airframe' and only {sorted(COVER_KEYS)}")
    rate = reader.get("maintenance.airframe.rate_per_block_hour", "block_hour")
    hourly = None if rate is None else basis.block_hours * rate
    if hourly is not None:
        reader.breakdown.append({"step": "block-hour part", "formula": f"{plain(basis.block_hours)} BH x {plain(rate)}",
                                 "value": plain(hourly)})
    cycle = _cycle_part(reader, "maintenance.airframe", basis.flight_cycles, "flight_cycle")
    amount = None if hourly is None or cycle is None else hourly + cycle
    included = sorted((cov or set()) - {"airframe"})
    return reader.result(amount, "block hours x hourly rate [+ cycles x cycle rate]",
                         notes=[f"rate also covers: {', '.join(included)}"] if included else None)


def engine_maintenance(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    cov = covers(scenario) or set()
    section = scenario.section("maintenance", "engine")
    if "engine" in cov:
        if section is not None:
            return failed(ENGINE, basis, "engine maintenance supplied although the airframe rate covers engines")
        return not_applicable(ENGINE, basis, "included in the all-inclusive airframe maintenance rate")
    reader = InputReader(ENGINE, scenario, basis, fx)
    if section is None:
        reader.missing.append("maintenance.engine")
        return reader.result(None, "engine maintenance")
    if basis.engine_count is None:
        reader.missing.append("aircraft engine count")
    hours_basis = scenario.flag("maintenance.engine.engine_hours_basis")
    hours = None
    if hours_basis is None:
        reader.missing.append("maintenance.engine.engine_hours_basis")
    elif hours_basis not in ENGINE_HOUR_BASES:
        reader.fail(f"maintenance.engine.engine_hours_basis must be one of {ENGINE_HOUR_BASES}")
    else:
        hours = {"airborne_hours": basis.airborne_hours, "engine_running_estimate": basis.engine_running_hours,
                 "block_hours_proxy": basis.block_hours}[hours_basis]
        if hours_basis == "block_hours_proxy":
            reader.warnings.append("engine hours use block hours as an explicitly selected proxy")
        if hours_basis == "engine_running_estimate":
            reader.warnings.append("engine running time = block time (Part 2 assumes all engines run during taxi)")
    if scenario.flag("maintenance.engine.includes_llp") is None:
        reader.missing.append("maintenance.engine.includes_llp")
    rate = reader.get("maintenance.engine.rate_per_engine_flight_hour", "engine_flight_hour")
    hourly = None
    if None not in (rate, hours, basis.engine_count):
        hourly = Decimal(basis.engine_count) * hours * rate
        reader.breakdown.append({"step": "engine-hour part", "engine_hours_basis": hours_basis,
                                 "formula": f"{basis.engine_count} engines x {plain(hours)} h x {plain(rate)}",
                                 "value": plain(hourly)})
    engine_cycles = Decimal(basis.engine_count or 0) * basis.flight_cycles
    cycle = _cycle_part(reader, "maintenance.engine", engine_cycles, "engine_cycle")
    amount = None if hourly is None or cycle is None else hourly + cycle
    return reader.result(amount, "engines x engine hours x rate [+ engine cycles x cycle rate]")


def engine_llp(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    cov = covers(scenario) or set()
    section = scenario.section("maintenance", "engine_llp")
    included_by = ("the all-inclusive airframe maintenance rate" if "engine_llp" in cov
                   else "the engine maintenance rate" if scenario.flag("maintenance.engine.includes_llp") is True
                   else None)
    if included_by:
        if section is not None:
            return failed(LLP, basis, f"LLP reserve supplied although {included_by} includes LLP")
        return not_applicable(LLP, basis, f"included in {included_by}")
    reader = InputReader(LLP, scenario, basis, fx)
    if section is None:
        reader.missing.append("maintenance.engine_llp")
        return reader.result(None, "engine LLP reserve")
    if basis.engine_count is None:
        reader.missing.append("aircraft engine count")
    rate = reader.get("maintenance.engine_llp.reserve_per_engine_cycle", "engine_cycle")
    amount = None
    if rate is not None and basis.engine_count is not None:
        engine_cycles = Decimal(basis.engine_count) * basis.flight_cycles
        amount = engine_cycles * rate
        reader.breakdown.append({"step": "LLP accrual", "formula": f"{plain(engine_cycles)} engine cycles x {plain(rate)}",
                                 "value": plain(amount)})
    return reader.result(amount, "engines x engine cycles x LLP reserve per engine cycle",
                         notes=["LLP cost is a modelled economic accrual, not a cash payment on the flight date"])
