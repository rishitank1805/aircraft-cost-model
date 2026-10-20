"""Aircraft ownership costs: operating lease, depreciation, financing, and ownership-mode controls.

Ownership modes (economic-cost scenario conventions, **not** IFRS 16 / US GAAP accounting):

| Mode | Operating lease | Depreciation | Financing interest |
|---|---|---|---|
| ``owned`` | not_applicable | required | required (``financing.mode = none`` with a reason if debt-free) |
| ``operating_lease`` | required | not_applicable | not_applicable |
| ``custom`` | per ``custom_treatment`` | per ``custom_treatment`` | per ``custom_treatment`` |

Sections supplied for components the mode excludes are ``failed_validation``
(use ``custom`` with a justification instead). ``custom`` may never include
lease, depreciation and financing together, and needs a written justification
whenever more than one is included.

Formulas:

    Annual lease          = monthly lease payment x 12
    Annual depreciation   = (depreciable value - residual value) / useful life years   (straight line)
    Annual interest       = explicit annual interest expense
                          | outstanding principal x annual interest rate
                          | interest portion of an amortising loan in the loan year containing the pricing date
    Per flight            = annual amount allocated by the section's ``allocation_basis``

Principal repayment is never treated as an expense. A lease payment that
includes maintenance reserves while maintenance is modelled separately is
``failed_validation`` (double counting).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from aircraft_cost_model.costs.coverage import ComponentResult
from aircraft_cost_model.costs.currency import RateProvider, plain
from aircraft_cost_model.fullcost.common import FlightBasis, InputReader, failed, not_applicable
from aircraft_cost_model.fullcost.scenario import Scenario

LEASE, DEPRECIATION, FINANCING = "operating_lease", "depreciation", "financing_interest"
LEASE_INCLUDES = {"maintenance_reserves", "insurance", "other_services"}
FINANCING_MODES = ("none", "annual_interest_expense", "principal_rate", "amortizing_loan")


def included_components(scenario: Scenario) -> dict[str, bool | None]:
    """Which ownership components the mode includes (None = invalid custom treatment)."""
    if scenario.ownership_mode == "owned":
        return {LEASE: False, DEPRECIATION: True, FINANCING: True}
    if scenario.ownership_mode == "operating_lease":
        return {LEASE: True, DEPRECIATION: False, FINANCING: False}
    treatment = scenario.flag("custom_treatment") or {}
    return {LEASE: treatment.get("include_operating_lease"), DEPRECIATION: treatment.get("include_depreciation"),
            FINANCING: treatment.get("include_financing")}


def custom_treatment_problem(scenario: Scenario) -> str | None:
    if scenario.ownership_mode != "custom":
        return None
    flags = included_components(scenario)
    if any(v is None for v in flags.values()):
        return "custom_treatment must set include_operating_lease, include_depreciation and include_financing"
    if all(flags.values()):
        return "custom treatment may not include operating lease, depreciation and financing together"
    if sum(bool(v) for v in flags.values()) > 1 and not str((scenario.flag("custom_treatment") or {}).get("justification", "")).strip():
        return "custom treatment combining several ownership costs needs a written justification of non-overlap"
    return None


def _gate(component: str, section: str, scenario: Scenario, basis: FlightBasis) -> ComponentResult | None:
    """Apply the ownership mode; returns a terminal result or None to continue calculating."""
    problem = custom_treatment_problem(scenario)
    if problem:
        return failed(component, basis, problem)
    include = included_components(scenario)[component]
    if not include:
        if scenario.section(section) is not None:
            return failed(component, basis, f"'{section}' supplied but excluded by ownership mode "
                                            f"'{scenario.ownership_mode}' (use custom mode with a justification)")
        return not_applicable(component, basis, f"excluded by ownership mode '{scenario.ownership_mode}'")
    return None


def operating_lease(scenario: Scenario, basis: FlightBasis, fx: RateProvider, *, maintenance_modelled: bool) -> ComponentResult:
    gate = _gate(LEASE, "operating_lease", scenario, basis)
    if gate:
        return gate
    reader = InputReader(LEASE, scenario, basis, fx)
    if scenario.section("operating_lease") is None:
        reader.missing.append("operating_lease")
        return reader.result(None, "operating lease")
    includes = scenario.flag("operating_lease.includes")
    if not isinstance(includes, list):
        reader.missing.append("operating_lease.includes (list what the payment includes; [] for none)")
    elif not set(includes) <= LEASE_INCLUDES:
        reader.fail(f"operating_lease.includes must be a subset of {sorted(LEASE_INCLUDES)}")
    elif "maintenance_reserves" in includes and maintenance_modelled:
        reader.fail("lease payment includes maintenance reserves while maintenance is modelled separately "
                    "(double counting); use a payment excluding reserves")
    monthly = reader.get("operating_lease.monthly_payment", "month", positive=True)
    annual = None if monthly is None else monthly * 12
    if annual is not None:
        reader.breakdown.append({"step": "annual lease", "formula": f"{plain(monthly)} x 12", "value": plain(annual)})
    amount = reader.allocate(annual, "operating_lease", "annual lease")
    return reader.result(amount, "monthly payment x 12 allocated by explicit basis",
                         notes=[f"lease payment includes: {', '.join(includes) or 'nothing beyond aircraft rental'}"]
                         if isinstance(includes, list) else None)


def depreciation(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    gate = _gate(DEPRECIATION, "depreciation", scenario, basis)
    if gate:
        return gate
    reader = InputReader(DEPRECIATION, scenario, basis, fx)
    if scenario.section("depreciation") is None:
        reader.missing.append("depreciation")
        return reader.result(None, "straight-line depreciation")
    method = scenario.flag("depreciation.method")
    if method != "straight_line":
        reader.missing.append("depreciation.method") if method is None else reader.fail(
            "only depreciation.method 'straight_line' is supported")
    acquisition = reader.get("depreciation.acquisition_value", "amount", positive=True)
    depreciable = reader.get("depreciation.depreciable_value", "amount", positive=True)
    residual = reader.get("depreciation.residual_value", "amount")
    life = reader.get("depreciation.useful_life_years", "years", positive=True)
    annual = None
    if None not in (depreciable, residual, life):
        if residual > depreciable:
            reader.fail("residual value exceeds depreciable value")
        else:
            annual = (depreciable - residual) / life
            reader.breakdown.append({"step": "annual depreciation", "acquisition_value": plain(acquisition) if acquisition else None,
                                     "formula": f"({plain(depreciable)} - {plain(residual)}) / {plain(life)} years",
                                     "value": plain(annual)})
    amount = reader.allocate(annual, "depreciation", "annual depreciation")
    return reader.result(amount, "straight line (depreciable - residual) / useful life, allocated by explicit basis",
                         notes=["acquisition, depreciable, residual, book and market values are distinct inputs; "
                                "only depreciable and residual values drive the charge"])


def amortizing_interest(principal: Decimal, annual_rate: Decimal, term_years: int, payments_per_year: int,
                        start: date, pricing_date: date) -> tuple[Decimal, Decimal, list[dict]]:
    """Interest and principal repaid in the loan year containing ``pricing_date`` (annuity loan)."""
    if pricing_date < start:
        raise ValueError("pricing date is before the loan start")
    months = (pricing_date.year - start.year) * 12 + pricing_date.month - start.month - (pricing_date.day < start.day)
    year_index = months // 12
    if year_index >= term_years:
        raise ValueError("pricing date is after the loan term")
    n_total = term_years * payments_per_year
    i = annual_rate / payments_per_year
    payment = principal / n_total if i == 0 else principal * i / (1 - (1 + i) ** -n_total)
    balance = principal
    interest_year = principal_year = Decimal(0)
    for period in range(1, n_total + 1):
        interest = balance * i
        repaid = payment - interest
        if repaid < 0:
            raise ValueError("payment does not cover interest")
        balance -= repaid
        if (period - 1) // payments_per_year == year_index:
            interest_year += interest
            principal_year += repaid
    if abs(balance) > Decimal("0.01"):
        raise ValueError(f"amortisation schedule does not close (final balance {balance})")
    return interest_year, principal_year, [{"step": "annuity payment", "value": plain(payment)},
                                           {"step": "loan year", "index": year_index + 1}]


def financing(scenario: Scenario, basis: FlightBasis, fx: RateProvider) -> ComponentResult:
    gate = _gate(FINANCING, "financing", scenario, basis)
    if gate:
        return gate
    reader = InputReader(FINANCING, scenario, basis, fx)
    if scenario.section("financing") is None:
        reader.missing.append("financing")
        return reader.result(None, "financing interest")
    mode = scenario.flag("financing.mode")
    if mode not in FINANCING_MODES:
        reader.missing.append("financing.mode") if mode is None else reader.fail(f"financing.mode must be one of {FINANCING_MODES}")
        return reader.result(None, "financing interest")
    if mode == "none":
        reason = str(scenario.flag("financing.reason") or "").strip()
        if not reason:
            reader.missing.append("financing.reason")
            return reader.result(None, "financing interest")
        return not_applicable(FINANCING, basis, f"no acquisition financing: {reason}")
    annual = None
    if mode == "annual_interest_expense":
        annual = reader.get("financing.annual_interest_expense", "year")
    elif mode == "principal_rate":
        principal = reader.get("financing.outstanding_principal", "amount", positive=True)
        rate = reader.get("financing.annual_interest_rate", "ratio")
        if None not in (principal, rate):
            annual = principal * rate
            reader.breakdown.append({"step": "annual interest", "formula": f"{plain(principal)} x {plain(rate)}",
                                     "value": plain(annual)})
    else:
        principal = reader.get("financing.principal", "amount", positive=True)
        rate = reader.get("financing.annual_interest_rate", "ratio")
        term = reader.get("financing.term_years", "years", positive=True)
        per_year = reader.get("financing.payments_per_year", "payments/year", positive=True)
        start = scenario.flag("financing.loan_start_date")
        if start is None:
            reader.missing.append("financing.loan_start_date")
        if None not in (principal, rate, term, per_year, start):
            if term != term.to_integral() or per_year != per_year.to_integral():
                reader.fail("term_years and payments_per_year must be whole numbers")
            else:
                try:
                    interest, repaid, steps = amortizing_interest(principal, rate, int(term), int(per_year),
                                                                  date.fromisoformat(start), basis.pricing_date)
                except ValueError as exc:
                    reader.fail(f"amortizing loan: {exc}")
                else:
                    annual = interest
                    reader.breakdown.extend(steps)
                    reader.breakdown.append({"step": "loan year interest", "value": plain(interest),
                                             "principal_repaid_excluded": plain(repaid)})
    amount = reader.allocate(annual, "financing", "annual interest")
    return reader.result(amount, f"{mode}: annual interest allocated by explicit basis (principal repayment excluded)")
