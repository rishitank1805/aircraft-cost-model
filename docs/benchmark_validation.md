# Validation framework and benchmark comparability (Part 5)

`python scripts/validate_cost_estimates.py --full-cost-estimate-id <id> [--output file.json] [--save]`

Each check is `pass`, `fail`, `warn` or `not_performed`. A check that cannot
run is never reported as passed. Exit code: 2 if any check fails.

## A. Arithmetic

| Check | Rule |
|---|---|
| Category subtotals | The sum of calculated components equals each stored subtotal (direct variable, direct fixed, indirect, noncash, financing) |
| COC/TOC/Total chain | COC = DV + DF + indirect; TOC = COC + noncash; Total = TOC + financing |
| Complete-total rule | Complete totals are withheld when any applicable component is uncalculated; otherwise they equal the subtotal |
| Money precision | Components are at 0.01 |
| Exact storage | Amounts are stored as SQLite *text* (exact decimals), never REAL |
| Fuel recheck | kg ÷ density ÷ 3.785411784 × price ÷ ECB rate, rounded half up = stored fuel (unit and currency conversion) |
| Reproducibility | Recalculating from the stored scenario gives identical component amounts and the same input hash (or reports a calculation-version change) |

## B. Operational

- Block hours > 0.
- Great-circle and modelled distance > 0.
- One cycle per leg.
- Supported aircraft.
- The Part 2 payload is reported as a *mass assumption, not revenue payload*.
- Operational validity is stored unchanged from Part 2.
- Fuel accounting is v2.
- `warn` when the Part 2 status is `calculated_limits_unverified`.

## C. Financial

- Coverage status recomputes to the stored value.
- No missing-as-zero: uncalculated components are NULL, and zero amounts
  appear only by tariff rule.
- Ownership-mode consistency:
  - owned → lease not applicable;
  - lease → depreciation and financing not applicable;
  - custom → at most two items, with a justification.
- No double counting:
  - maintenance `covers` and `includes_llp`;
  - crew `includes_allowances`;
  - lease includes insurance.
- The source-quality summary recomputes to the stored value.
- Part 3 and Part 4 pricing dates are equal.
- **Historical pricing rule:** no price, tariff or FX observation is dated
  after the pricing date.
- `warn` when the result depends on explicit or illustrative assumptions.

## D. External benchmarks

**Defaults:**
- BTS Form 41 for the mapped aircraft type and the quarter containing the
  pricing date;
- FAA Table 4-7 (see [bts_form41_methodology.md](bts_form41_methodology.md)).

**Benchmark metric** = Σ amounts / Σ matching denominators over the selected
rows. It is a ratio of totals, never an average of ratios.

**Comparability checks.** Any `fail` makes the comparison `not_comparable`
(no deviation is computed). Any `caveat` makes it `comparable_with_caveats`.

| Check | Fails when | Caveat when |
|---|---|---|
| model_metric | a model component is unavailable or not applicable | some mapped components are not applicable (included elsewhere) |
| model_source | the model input is an **illustrative assumption**, or **circular** (the model input is the same benchmark, e.g. FAA vs FAA) | the model input is FAA, which FAA derived from BTS (common origin) |
| category | there is no compatible benchmark category | always for BTS/FAA (accounting definitions differ; listed) |
| benchmark_data | no rows pass the quality filter | — |
| period | the benchmark is > 366 days from the pricing date and not index-adjusted | periods are not aligned but within a year, or an index adjustment is applied |
| denominator | the units differ (e.g. FAA per airborne hour) | — |
| aircraft_type | there is no verified mapping, or the selection does not match it | family or configuration match (not exact type); FAA class averages |
| operation_scope | passenger model versus freight rows (or the reverse) | — |
| traffic_definition | RTNM versus passenger-configured BTS RTM (which includes passengers) | — |
| fleet_level | — | published class averages (FAA) |
| geographic_scope | — | U.S. carriers versus a non-U.S. route |
| stage_length | — | model distance / benchmark average stage outside 0.5–2 |
| currency | no rate available | USD→EUR at the ECB period-average rate (BTS), or at the pricing-date rate (FAA) |

**Deviation (when not `not_comparable`):**

```text
absolute difference   = model metric − benchmark metric
percentage difference = (model − benchmark) / benchmark × 100    (benchmark > 0 only)
```

A deviation against a `comparable_with_caveats` benchmark is reported as a
**difference, not a model error**. Only a `comparable` benchmark (same
quantity, same definitions) would justify reading it as error. None of the
current public benchmarks qualifies for a European flight.

## Results for the A320 example (real database, saved estimate 1)

| Category | Result |
|---|---|
| Arithmetic | 13 pass |
| Operational | 7 pass; 1 warn (limits unverified) |
| Financial | 7 pass; 1 warn (illustrative assumptions) |
| External | 1 `comparable_with_caveats`; 8 `not_comparable` |

**The comparable-with-caveats check:** fuel per block hour against BTS A320
2025Q1 (1,492.97 versus 1,856.49 EUR/BH, −19.6 %).

**The 8 not-comparable checks:**
- crew, maintenance, insurance and depreciation against BTS and FAA:
  illustrative model inputs;
- FAA: also 565 days from the pricing date;
- lease: not applicable for an owned aircraft.

**FAA-benchmark scenario against BTS A320 2025Q1** (comparable with caveats;
FAA values are derived from BTS for YE June 2023):

| Item | FAA scenario | BTS | Difference |
|---|---:|---:|---:|
| Crew | 1,337.86 EUR/BH | 1,622.33 | −17.5 % |
| Maintenance | 926.21 | 1,135.66 | −18.4 % |
| Insurance | 5.83 | 9.31 | −37.4 % |

The FAA-adjusted comparisons of that scenario are refused as circular.
