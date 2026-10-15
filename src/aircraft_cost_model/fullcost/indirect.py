"""Indirect costs: administration, cargo sales, general and administrative (G&A) overhead.

``administration`` and ``general_administrative`` each declare a ``scope``
(free text) and a ``basis``:

    per_flight      : rate per flight
    per_block_hour  : block hours x rate
    annual          : annual aircraft-allocated amount, allocated by ``allocation_basis``

To prevent overlap, when both are supplied their scopes must differ and
``general_administrative.excludes_administration`` must be true.

``cargo_sales`` must state ``applicable`` explicitly. When applicable:

    per_revenue_tonne    : rate x revenue cargo tonnes (explicit input; never derived from payload)
    pct_of_cargo_revenue : rate x cargo revenue (explicit input; never invented)
    per_flight           : rate per flight
"""

from __future__ import annotations

from aircraft_cost_model.costs.coverage import ComponentResult
from aircraft_cost_model.costs.currency import RateProvider, plain
from aircraft_cost_model.fullcost.common import FlightBasis, InputReader, not_applicable
from aircraft_cost_model.fullcost.scenario import Scenario

ADMIN, CARGO_SALES, GA = "administration", "cargo_sales", "general_administrative"
OVERHEAD_BASES = ("per_flight", "per_block_hour", "annual")


def _overhead(component: str, section: str, scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    reader = InputReader(component, scenario, basis, fx)
    if scenario.section("indirect", section) is None:
        reader.missing.append(f"indirect.{section}")
        return reader.result(None, component)
    path = f"indirect.{section}"
    scope = str(scenario.flag(f"{path}.scope") or "").strip()
    if not scope:
        reader.missing.append(f"{path}.scope")
    if component == GA and scenario.section("indirect", "administration") is not None:
        admin_scope = str(scenario.flag("indirect.administration.scope") or "").strip()
        if scenario.flag(f"{path}.excludes_administration") is not True:
            reader.fail("general_administrative must set excludes_administration=true when administration is modelled")
        if scope and scope == admin_scope:
            reader.fail("administration and general_administrative have the same scope (overlap)")
    method = scenario.flag(f"{path}.basis")
    amount = None
    if method == "per_flight":
        amount = reader.get(f"{path}.rate", "flight")
    elif method == "per_block_hour":
        rate = reader.get(f"{path}.rate", "block_hour")
        amount = None if rate is None else basis.block_hours * rate
    elif method == "annual":
        amount = reader.allocate(reader.get(f"{path}.annual_amount", "year"), path, f"annual {component}")
    elif method is None:
        reader.missing.append(f"{path}.basis")
    else:
        reader.fail(f"{path}.basis must be one of {OVERHEAD_BASES}")
    return reader.result(amount, f"{method} ({scope})", notes=[f"scope: {scope}"] if scope else None)


def administration(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    return _overhead(ADMIN, "administration", scenario, basis, fx)


def general_administrative(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    return _overhead(GA, "general_administrative", scenario, basis, fx)


def cargo_sales(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    reader = InputReader(CARGO_SALES, scenario, basis, fx)
    path = "indirect.cargo_sales"
    if scenario.section("indirect", "cargo_sales") is None:
        reader.missing.append(path)
        return reader.result(None, "cargo sales")
    applicable = scenario.flag(f"{path}.applicable")
    if applicable is False:
        reason = str(scenario.flag(f"{path}.reason") or "").strip()
        if not reason:
            reader.missing.append(f"{path}.reason")
            return reader.result(None, "cargo sales")
        return not_applicable(CARGO_SALES, basis, reason)
    if applicable is not True:
        reader.missing.append(f"{path}.applicable")
        return reader.result(None, "cargo sales")
    method = scenario.flag(f"{path}.basis")
    amount = None
    if method == "per_revenue_tonne":
        rate = reader.get(f"{path}.rate", "revenue_tonne")
        tonnes = reader.get(f"{path}.revenue_cargo_tonnes", "tonnes")
        if None not in (rate, tonnes):
            amount = rate * tonnes
            reader.breakdown.append({"formula": f"{plain(rate)} x {plain(tonnes)} revenue t", "value": plain(amount)})
    elif method == "pct_of_cargo_revenue":
        rate = reader.get(f"{path}.rate", "ratio")
        revenue = reader.get(f"{path}.cargo_revenue", "amount")
        if None not in (rate, revenue):
            amount = rate * revenue
            reader.breakdown.append({"formula": f"{plain(rate)} x cargo revenue {plain(revenue)}", "value": plain(amount)})
    elif method == "per_flight":
        amount = reader.get(f"{path}.rate", "flight")
    elif method is None:
        reader.missing.append(f"{path}.basis")
    else:
        reader.fail(f"{path}.basis must be per_revenue_tonne, pct_of_cargo_revenue or per_flight")
    return reader.result(amount, f"cargo sales {method}")
