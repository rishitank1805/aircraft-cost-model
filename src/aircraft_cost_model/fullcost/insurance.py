"""Aircraft insurance (direct fixed).

``insurance.basis``:

- ``annual``: coverages listed explicitly, each either an annual premium or an
  insured value x annual premium rate (both explicit; no universal percentage).
  An ``inclusive`` coverage (all risks in one premium) cannot be combined with
  further coverages. The annual total is allocated by ``allocation_basis``
  (block hours / annual aircraft block hours, or 1 / annual flights).
- ``rate_per_block_hour``: block hours x insurance cost per block hour (benchmark).

If the operating lease payment includes insurance, insurance is
``not_applicable`` (included) and supplying it as well is ``failed_validation``.
"""

from __future__ import annotations

from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentResult
from aircraft_cost_model.costs.currency import RateProvider, plain
from aircraft_cost_model.fullcost.common import FlightBasis, InputReader, failed, not_applicable
from aircraft_cost_model.fullcost.scenario import Scenario

INSURANCE = "insurance"


def lease_includes(scenario: Scenario, item: str) -> bool:
    included = scenario.flag("operating_lease.includes")
    return scenario.ownership_mode in ("operating_lease", "custom") and isinstance(included, list) and item in included


def insurance(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    section = scenario.section("insurance")
    if lease_includes(scenario, "insurance"):
        if section is not None:
            return failed(INSURANCE, basis, "insurance supplied although the lease payment includes insurance")
        return not_applicable(INSURANCE, basis, "included in the operating lease payment")
    reader = InputReader(INSURANCE, scenario, basis, fx)
    if section is None:
        reader.missing.append("insurance")
        return reader.result(None, "insurance")
    method = scenario.flag("insurance.basis")
    if method == "rate_per_block_hour":
        rate = reader.get("insurance.rate_per_block_hour", "block_hour")
        amount = None if rate is None else basis.block_hours * rate
        return reader.result(amount, "block hours x insurance cost per block hour")
    if method != "annual":
        reader.missing.append("insurance.basis") if method is None else reader.fail(
            "insurance.basis must be 'annual' or 'rate_per_block_hour'")
        return reader.result(None, "insurance")
    coverages = scenario.flag("insurance.coverages")
    if not isinstance(coverages, list) or not coverages:
        reader.missing.append("insurance.coverages")
        return reader.result(None, "insurance")
    names = [c.get("name") for c in coverages if isinstance(c, dict)]
    if len(names) != len(coverages) or not all(names) or len(set(names)) != len(names):
        reader.fail("each insurance coverage needs a unique name")
    if any(c.get("inclusive") for c in coverages if isinstance(c, dict)) and len(coverages) > 1:
        reader.fail("an inclusive coverage cannot be combined with separate coverages (double counting)")
    annual = Decimal(0)
    complete = True
    for index, coverage in enumerate(coverages):
        prefix = f"insurance.coverages[{index}]"
        if scenario.value(f"{prefix}.annual_premium") is not None:
            if scenario.value(f"{prefix}.insured_value") is not None:
                reader.fail(f"{prefix}: give an annual premium or insured value x rate, not both")
            premium = reader.get(f"{prefix}.annual_premium", "year")
            method_text = "annual premium"
        else:
            value = reader.get(f"{prefix}.insured_value", "amount", positive=True)
            rate = reader.get(f"{prefix}.annual_premium_rate", "ratio")
            premium = None if None in (value, rate) else value * rate
            method_text = "insured value x annual premium rate"
        if premium is None:
            complete = False
            continue
        annual += premium
        reader.breakdown.append({"coverage": coverage.get("name"), "method": method_text, "annual": plain(premium)})
    amount = reader.allocate(annual if complete else None, "insurance", "annual insurance")
    return reader.result(amount, "annual insurance (sum of coverages) allocated by explicit basis",
                         notes=[f"coverage scope: {', '.join(str(n) for n in names)}"])
