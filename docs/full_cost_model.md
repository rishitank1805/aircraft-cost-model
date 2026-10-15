# Full operating cost model (Part 4)

Part 4 combines three inputs:

- a saved **Part 2 flight estimate** (the time bases);
- the saved **Part 3 variable-cost estimate** for that same flight (fuel,
  navigation, terminal navigation, landing, ground handling);
- a **cost scenario file** (maintenance, crew, insurance, ownership,
  financing and indirect assumptions).

From these it produces an estimate of the full cost of one flight.

> **Economic cost, not accounting expense.** The results are economic cost
> estimates under the scenario's assumptions. For example, an LLP reserve is
> treated as an accrual of future shop-visit cost, depreciation is spread
> evenly over the aircraft's useful life, and fixed annual costs are allocated
> per flight. An airline's accounting expense differs in timing (for example
> when maintenance events are expensed or capitalised), in classification
> (IFRS 16 puts leases on the balance sheet) and in scope (tax and
> one-off items). Nothing here is IFRS, US GAAP or a manufacturer's DOC method.

## 1. Running it

```bash
python scripts/calculate_full_costs.py --flight-estimate-id 2 --variable-cost-estimate-id 2 \
    --scenario data/scenarios/example_owned_aircraft.json --save
```

Before calculating, the tool checks the following. It exits with code 1 and
an error if any check fails.

- The variable-cost estimate must belong to the same flight estimate.
  Otherwise it raises `FullCostInputError`.
- The flight estimate must use fuel accounting **v2**. A v1 estimate is
  rejected.
- The scenario's `reporting_currency` must equal the variable-cost estimate's
  currency.
- If the scenario sets `pricing_date`, it must equal the variable-cost
  estimate's pricing date.

Two further rules apply to the inputs:

- **Part 3 results are reused, not recomputed.** Each Part 3 component is
  read from its saved `cost_component` row. The saved Part 4 component links
  to that row (`part3_cost_component_id`), so historical Part 3 amounts are
  reproduced exactly. A component absent from an older Part 3 estimate (for
  example terminal navigation in estimate 1) is reported as unavailable,
  never as zero.
- **Unsupported aircraft get no Part 4 costs.** If the aircraft has no
  supported performance model (the dedicated freighters A330-200F and B777F),
  every Part 4 component is `unsupported_aircraft`. No passenger substitute
  is used.

## 2. Time bases

| Basis | Value used | Used by |
|---|---|---|
| Block hours | `flight_estimate.block_time_min / 60` | airframe hourly rate, block-hour allocation, crew |
| Airborne hours | `airborne_time_min / 60` | engine hours (basis `airborne_hours`) |
| Engine running hours | block hours (an estimate: engines assumed running gate to gate) | engine hours (basis `engine_running_estimate`) |
| Flight cycles | 1 per flight | airframe cycle rate |
| Engine cycles | engine count × 1 | engine cycle rate, LLP |

## 3. Taxonomy

This taxonomy is the project's own reporting convention.

```text
Direct variable (DV) = fuel + airframe maintenance + engine maintenance + engine LLP
                       + en-route navigation + terminal navigation + landing
                       + ground handling + crew allowances
Direct fixed (DF)    = crew salaries + insurance + operating lease
Indirect             = administration + cargo sales + general & administrative
COC                  = DV + DF + Indirect
TOC                  = COC + depreciation          (noncash)
Total costs          = TOC + financing interest
```

Allocated annual costs (salaries, insurance, lease) are classed as *direct
fixed* because they are fixed per year and do not vary with the flight. The
allocation rule only spreads them across flights.

## 4. Statuses and completeness

Every component has a status:

- **calculated**: `calculated_public_tariff`, `calculated_benchmark` or
  `calculated_assumption`;
- **`not_applicable`**: excluded by ownership mode, by an inclusion flag, or
  by an explicit and reasoned non-applicability;
- **unavailable**: `missing_required_input`, `unavailable_*` or
  `unsupported_aircraft`;
- **`failed_validation`**: contradictory inputs, for example a double count,
  a wrong unit, or a value outside its effective period.

Aggregation follows these rules:

- **Calculated subtotals** add calculated components only. They are always
  labelled "calculated subtotal" and are never called totals.
- A **complete** category, COC, TOC or total exists only when every
  *applicable* component below it is calculated with full scope.
  `not_applicable` components do not block completeness. A category made up
  entirely of `not_applicable` components is complete at 0.00.
- A missing amount is **never** zero. Unavailable components have
  `amount = NULL` in the database and print as `N/A`.

## 5. Three independent dimensions

| Dimension | Values | Meaning |
|---|---|---|
| A. Cost coverage | `complete`, `incomplete`, `failed_validation` | Whether every applicable component was calculated |
| B. Operational validity | carried unchanged from Part 2, e.g. `calculated_limits_unverified` | Whether the flight itself was verified against aircraft limits |
| C. Source quality | `observed_public_data`, `public_market_benchmark`, `public_financial_benchmark`, `modelled_estimate`, `explicit_user_assumption`, `mixed: ...`, `none` | Where the monetary inputs come from |

No dimension changes another. A complete cost estimate built on illustrative
assumptions is `complete` + `explicit_user_assumption`. That is not the same
as `observed_public_data`, and neither one implies that the flight is
operationally valid.

How each component's source quality is classified:

| Origin | Component `source_type` | Source quality |
|---|---|---|
| Part 3 published tariff or charge (EUROCONTROL, DFS/DGAC, airport) | `public_tariff` | `observed_public_data`: the charge as levied |
| Part 3 fuel (EIA U.S. Gulf Coast jet-fuel spot price, converted at the ECB rate) | `public_market_benchmark` | `public_market_benchmark`: a market price index, **not** an observed airline fuel expense (which also includes contract differentials, into-plane fees and taxes) |
| Part 3 result that relies on a scenario input (e.g. a type-level MTOW) | `public_tariff` + assumption | `mixed` |
| Part 4, every input `public_financial_benchmark` (e.g. FAA) | `public_financial_benchmark` | `public_financial_benchmark`: an industry average, not this operator's expense |
| Part 4, any input `illustrative_assumption` or `user_assumption` | `user_assumption` | `explicit_user_assumption` |
| Part 4, inputs with different source types | | `mixed` |

Each Part 3 component keeps the `source_type`, status and source reference of
its saved Part 3 row. Each Part 4 component's `assumptions_json` keeps every
input's own `source_type`, so an `illustrative_assumption` remains visible as
illustrative.

## 6. Example: real database, A320 FRA→CDG (flight 2, Part 3 estimate 2, pricing 2025-01-15)

Time bases: 71.859 block minutes = 1.19764 h; 44.174 airborne minutes =
0.73623 h; 2 engines; 1 cycle.

| Component | Owned (illustrative) | Lease (illustrative) | FAA benchmark (partial) |
|---|---:|---:|---:|
| fuel (Part 3; EIA spot benchmark) | 1,788.05 | 1,788.05 | 1,788.05 |
| airframe maintenance | 459.29 | 459.29 | 1,109.27 (all-inclusive) |
| engine maintenance | 220.87 | 220.87 | n/a (included) |
| engine LLP | 200.00 | 200.00 | n/a (included) |
| en-route / terminal navigation, landing, handling | N/A | N/A | N/A |
| crew allowances | 100.00 | 100.00 | n/a (included) |
| crew salaries | 598.82 | 598.82 | 1,602.28 |
| insurance | 79.84 | 79.84 | 6.98 |
| operating lease | n/a | 1,437.17 | n/a |
| administration / G&A | 100.00 / 399.21 | 100.00 / 399.21 | missing |
| cargo sales | n/a (passenger) | n/a | missing |
| depreciation | 898.23 | n/a | missing |
| financing interest | 598.82 | n/a | missing |
| **Calculated COC subtotal** | 3,946.08 | 5,383.25 | 4,506.58 |
| **Complete COC** | unavailable | unavailable | unavailable |

All amounts are EUR. Hand checks:

- airframe: 1.19764 × 300 + 1 × 100 = 459.29;
- engine: 2 × 0.73623 × 150 = 220.87;
- insurance: 200,000 × 1.19764 / 3,000 = 79.84;
- lease: 300,000 × 12 × 1.19764 / 3,000 = 1,437.17;
- FAA airframe: 954 USD × 1.19764 / 1.0300 USD per EUR (ECB, 2025-01-15) = 1,109.27.

All three COC figures are *unavailable* because the Part 3 estimate has no
navigation zones, landing tariff or handling input for this flight. The
illustrative scenarios are **not** airline costs. They exist only to exercise
the engine.

## 7. Persistence

- **`cost_scenario`**: stores each scenario once per content hash, with its
  canonical JSON.
- **`cost_assumption`**: one row per scenario input.
- **`full_cost_estimate`**: one row per estimate, holding:
  - the links to the flight estimate, the variable-cost estimate and the
    scenario;
  - the calculated subtotals and the `complete_*` totals;
  - the three dimensions;
  - the input hash.
- **`full_cost_component`**: 17 rows per estimate.

Money is stored as exact decimal text. See [data_dictionary.md](data_dictionary.md).

Related documents:

- [maintenance_costs.md](maintenance_costs.md)
- [crew_costs.md](crew_costs.md)
- [ownership_and_financing.md](ownership_and_financing.md)
- [cost_assumptions.md](cost_assumptions.md)
