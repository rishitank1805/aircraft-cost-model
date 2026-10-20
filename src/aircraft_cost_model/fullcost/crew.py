"""Crew costs: salaries (direct fixed) and flight-specific allowances (direct variable), kept separate.

Salaries, ``crew.salaries.basis``:

- ``role_allocation``: for each role
  count x annual compensation x (1 + employer on-cost rate) x flight block hours
  / that role's annual allocable block hours per crew member, all x staffing factor.
  The staffing factor (reserve / relief crews) must be stated explicitly (1 = none).
  Annual allocable crew hours are per crew member and are not aircraft utilization.
- ``rate_per_block_hour``: block hours x crew cost per block hour (e.g. a public
  benchmark whose crew-cost definition is documented in its source).

Allowances (only when ``crew.salaries.includes_allowances`` is false):
per diem per crew member per duty day x crew count x duty days
+ accommodation per crew member per night x crew count x nights
+ other flight-specific crew expenses per flight. Duty days and nights are
explicit inputs; no overnight stay is assumed.
"""

from __future__ import annotations

from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentResult
from aircraft_cost_model.costs.currency import RateProvider, plain
from aircraft_cost_model.fullcost.common import FlightBasis, InputReader, failed, not_applicable
from aircraft_cost_model.fullcost.scenario import Scenario

SALARIES, ALLOWANCES = "crew_salaries", "crew_allowances"
SALARY_BASES = ("role_allocation", "rate_per_block_hour")


def crew_salaries(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    reader = InputReader(SALARIES, scenario, basis, fx)
    if scenario.section("crew", "salaries") is None:
        reader.missing.append("crew.salaries")
        return reader.result(None, "crew salaries")
    if scenario.flag("crew.salaries.includes_allowances") is None:
        reader.missing.append("crew.salaries.includes_allowances")
    method = scenario.flag("crew.salaries.basis")
    if method not in SALARY_BASES:
        reader.missing.append("crew.salaries.basis") if method is None else reader.fail(
            f"crew.salaries.basis must be one of {SALARY_BASES}")
        return reader.result(None, "crew salaries")
    if method == "rate_per_block_hour":
        rate = reader.get("crew.salaries.rate_per_block_hour", "block_hour")
        amount = None if rate is None else basis.block_hours * rate
        if amount is not None:
            reader.breakdown.append({"step": "crew cost per block hour",
                                     "formula": f"{plain(basis.block_hours)} BH x {plain(rate)}", "value": plain(amount)})
        return reader.result(amount, "block hours x crew cost per block hour")
    staffing = reader.get("crew.salaries.staffing_factor", "ratio", positive=True)
    roles = scenario.flag("crew.salaries.roles")
    if not isinstance(roles, list) or not roles:
        reader.missing.append("crew.salaries.roles")
        return reader.result(None, "crew salary allocation")
    total = Decimal(0)
    complete = staffing is not None
    names = []
    for index, role in enumerate(roles):
        prefix = f"crew.salaries.roles[{index}]"
        name = role.get("role") if isinstance(role, dict) else None
        if not name:
            reader.fail(f"{prefix}.role is required")
            continue
        names.append(name)
        count = reader.get(f"{prefix}.count", "count", positive=True)
        comp = reader.get(f"{prefix}.annual_compensation", "year", positive=True)
        oncost = reader.get(f"{prefix}.employer_on_cost_rate", "ratio")
        hours = reader.get(f"{prefix}.annual_allocable_block_hours", "block_hour/year", positive=True)
        if None in (count, comp, oncost, hours) or staffing is None:
            complete = False
            continue
        if count != count.to_integral():
            reader.fail(f"{prefix}.count must be a whole number")
            continue
        annual = count * comp * (1 + oncost)
        share = basis.block_hours / hours
        amount = annual * share * staffing
        total += amount
        reader.breakdown.append({"role": name, "count": plain(count), "annual_cost_incl_on_costs": plain(annual),
                                 "allocation": f"{plain(basis.block_hours)} BH / {plain(hours)} allocable BH",
                                 "staffing_factor": plain(staffing), "value": plain(amount)})
    if len(names) != len(set(names)):
        reader.fail("crew roles must be unique")
    return reader.result(total if complete else None,
                         "sum over roles: count x compensation x (1 + on-costs) x BH / allocable BH x staffing factor")


def crew_allowances(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    section = scenario.section("crew", "allowances")
    if scenario.flag("crew.salaries.includes_allowances") is True:
        if section is not None:
            return failed(ALLOWANCES, basis, "allowances supplied although crew salaries include them")
        return not_applicable(ALLOWANCES, basis, "included in crew salary costs")
    reader = InputReader(ALLOWANCES, scenario, basis, fx)
    if section is None:
        reader.missing.append("crew.allowances")
        return reader.result(None, "crew allowances")
    crew = reader.get("crew.allowances.crew_count", "count", positive=True)
    parts: list[Decimal] = []
    ok = crew is not None
    pairs = (("per_diem_per_crew_member_per_duty_day", "duty_day", "duty_days", "days"),
             ("accommodation_per_crew_member_per_night", "night", "nights", "nights"))
    for rate_key, rate_dim, qty_key, qty_unit in pairs:
        has_rate = scenario.value(f"crew.allowances.{rate_key}") is not None
        has_qty = scenario.value(f"crew.allowances.{qty_key}") is not None
        if not has_rate and not has_qty:
            continue
        rate = reader.get(f"crew.allowances.{rate_key}", rate_dim)
        qty = reader.get(f"crew.allowances.{qty_key}", qty_unit)
        if None in (rate, qty, crew):
            ok = False
            continue
        amount = rate * crew * qty
        parts.append(amount)
        reader.breakdown.append({"element": rate_key, "formula": f"{plain(rate)} x {plain(crew)} crew x {plain(qty)} {qty_key}",
                                 "value": plain(amount)})
    if scenario.value("crew.allowances.other_flight_expenses") is not None:
        other = reader.get("crew.allowances.other_flight_expenses", "flight")
        if other is None:
            ok = False
        else:
            parts.append(other)
            reader.breakdown.append({"element": "other flight-specific crew expenses", "value": plain(other)})
    if not parts and ok:
        reader.missing.append("crew.allowances (no allowance element supplied)")
    return reader.result(sum(parts, Decimal(0)) if ok and parts else None,
                         "per diem x crew x duty days + accommodation x crew x nights + other per-flight expenses")
