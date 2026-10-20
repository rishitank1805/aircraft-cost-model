# Ownership, leasing, depreciation and financing (Part 4)

## Ownership modes (`ownership_mode`, required)

| Mode | Operating lease | Depreciation | Financing interest |
|---|---|---|---|
| `owned` | not applicable | applicable | applicable (or `mode: none` with a reason) |
| `operating_lease` | applicable | not applicable | not applicable |
| `custom` | per `custom_treatment.include_operating_lease` | per `include_depreciation` | per `include_financing` |

**`custom`** requires `custom_treatment` with all three booleans and a
non-empty `justification`. It may **never** include all three items (that
would double count the aircraft's capital cost).

Supplying a section for an excluded component gives `failed_validation`
rather than silently ignoring it.

## Operating lease (direct fixed)

```text
monthly_payment × 12 → annual, allocated by block hours or flights
```

`operating_lease.includes` ⊆ {`maintenance_reserves`, `insurance`,
`other_services`} records what the rent covers:

- `maintenance_reserves` together with any modelled maintenance component
  gives `failed_validation`;
- `insurance` together with an insurance section gives `failed_validation`.
  Without an insurance section, insurance is `not_applicable`.

No public lease-rate source was found; lease inputs must be user-supplied.

## Depreciation (noncash; in TOC, not COC)

Only `method: straight_line` is supported:

```text
annual = (depreciable_value - residual_value) / useful_life_years
```

The annual amount is then allocated.

The inputs are kept distinct: `acquisition_value` (recorded),
`depreciable_value`, `residual_value` and `useful_life_years`. Book value and
market value are different quantities and are not inferred.

A useful life ≤ 0, a negative residual value, or a residual value above the
depreciable value gives `failed_validation`.

FAA depreciation figures are fleet averages that mix owned and leased
aircraft, so they are **not** used.

## Financing interest (below TOC)

| `financing.mode` | Annual interest |
|---|---|
| `none` | not applicable; `reason` required |
| `annual_interest_expense` | given directly (`CCY/year`) |
| `principal_rate` | `outstanding_principal × annual_interest_rate` |
| `amortizing_loan` | interest paid in the loan year that contains the pricing date (annuity schedule from `principal`, `annual_interest_rate`, `term_years`, `payments_per_year`, `loan_start_date`) |

The annual interest is then allocated. **Principal repayment is not a cost.**
It is recorded in the breakdown (`principal_repaid_excluded`) and excluded
from the amount; the economic cost of the asset is captured by depreciation.
A pricing date before the loan starts or after it ends gives
`failed_validation`.

## Economic cost versus accounting

The lease cost here is rent per flight. Under IFRS 16, a lessee instead
records a right-of-use asset and interest. That is the same economic
substance with different timing and presentation, which is why the model
does not claim to be accounting expense. The same applies to depreciation
(the useful life and residual value are the scenario's own) and to financing
(interest only, allocated).
