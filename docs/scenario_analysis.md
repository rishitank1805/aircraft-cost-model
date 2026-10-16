# Scenario analysis, sensitivity and comparisons (Part 5)

## 1. Scenario variations

A variation changes one input and recalculates, through the existing
engines, every component that depends on it. Totals are never scaled
directly. The base is never modified:

- the scenario object and file are untouched;
- the variant is a new scenario with its own content hash, stored once in
  `cost_scenario` only when a run is saved;
- saved Part 3 and Part 4 rows are never changed.

| Parameter | Recalculated through | Change types |
|---|---|---|
| `fuel_price` | Part 3 fuel engine (the saved benchmark observation, price changed) | percent, absolute, value |
| `fuel_burn` | Part 3 fuel engine (block fuel × multiplier): **post-flight consumption stress test** | percent, value |
| `airframe_maintenance_rate`, `airframe_cycle_rate`, `engine_maintenance_rate`, `llp_reserve` | Part 4 maintenance | percent, absolute, value |
| `crew_compensation` | Part 4 crew (all roles, or the per-block-hour rate) | percent (absolute/value only with a single input) |
| `annual_block_hours`, `annual_flights` | Part 4 allocation denominators | percent, absolute, value |
| `annual_utilization` | both together (constant average block time per flight) | percent |
| `insurance_cost` | every insurance premium or rate input | percent (absolute/value only with a single input) |
| `lease_payment` | Part 4 operating lease | percent, absolute, value |
| `depreciable_value`, `residual_value`, `useful_life` | Part 4 depreciation | percent, absolute, value |
| `financing_interest_rate` | Part 4 financing (`principal_rate` / `amortizing_loan`) | percent, absolute, value |
| `administration_cost`, `cargo_sales_cost`, `ga_overhead` | Part 4 indirect | percent, absolute, value |
| `revenue_cargo_payload` | analytics payload (+ the cargo-sales tonnes input if present): **fixed-performance economic sensitivity** | percent, absolute, value |

**Not exposed: aircraft acquisition value.** Part 4 records it, but only the
depreciable and residual values drive depreciation. A change to it alone
would change nothing, so the model cannot "calculate it correctly" and it is
not offered.

**Parameter rules:**
- A parameter that is absent from the scenario is rejected. Example:
  `lease_payment` on an owned scenario → *does not apply*.
- A parameter mapping to several inputs accepts only percent changes. Example:
  `crew_compensation` with two roles.

Each variation result records:
- the base scenario (hash and ID);
- the modified parameter, input path, original value, new value, unit, the
  original source type, and the new `user_assumption` label;
- the calculation timestamp;
- all components, subtotals and complete totals;
- coverage, validity, source quality and warnings.

**Fuel price versus fuel burn:**
- **Fuel price** changes only the price per unit of fuel. The quantity is
  the Part 2 block fuel.
- **Fuel burn** scales the block fuel *after* the flight. Flight mass, fuel
  planning and feasibility are **not** re-evaluated, so this is a labelled
  stress test, not a physically validated simulation.
- **Rerunning Part 2** with different inputs is the physical alternative
  (`calculate_flight.py`).
- **Status change.** A varied fuel component becomes `calculated_assumption`
  (source quality `mixed`), because the price or quantity is no longer the
  observed benchmark.

**Utilisation:**
- Annual utilisation changes only the allocated fixed costs: insurance, lease,
  depreciation, financing and annual-amount overheads.
- It does not change fuel, distance, per-cycle LLP, per-flight charges or
  crew salaries. Crew salaries use crew productivity (allocable block hours
  per person), not aircraft utilisation.

## 2. One-variable sensitivity

- **Absolute change** = varied value − base value.
- **Percent change** = absolute change / base value × 100. It is computed only
  when the base exists and is non-zero.
- **Withheld deltas.** If a variation changes which components are calculated
  (e.g. a residual value above the depreciable value makes depreciation
  `failed_validation`), the deltas of the affected totals are withheld and
  `coverage_changed` lists them.

**Example (real database, A320 FRA→CDG, saved estimate 1, partial COC subtotal 3,946.08 EUR):**

| Variation (illustrative levels, not forecasts) | Fuel | COC subtotal | ΔCOC | ΔCOC % | Components affected |
|---|---:|---:|---:|---:|---|
| fuel_price −20 % | 1,430.44 | 3,588.47 | −357.61 | −9.06 | fuel |
| fuel_price +10 % | 1,966.86 | 4,124.89 | +178.81 | +4.53 | fuel |
| airframe_maintenance_rate +10 % | 1,788.05 | 3,982.01 | +35.93 | +0.91 | airframe_maintenance (1.19764 BH × 30 EUR) |
| annual_utilization −20 % | 1,788.05 | 4,065.85 | +119.77 | +3.04 | insurance, G&A, depreciation, financing |
| annual_utilization +20 % | 1,788.05 | 3,866.25 | −79.83 | −2.02 | insurance, G&A, depreciation, financing |

All subtotals are **partial**: navigation, terminal navigation, landing and
handling are unavailable.

## 3. Two-variable grid

A user-chosen grid of two different parameters. It is bounded to 100 cells
by default (hard limit 400), so there is no exhaustive search. Each cell is a
full recalculation. These are **deterministic scenario outcomes, not
probability estimates.**

**Fuel price × annual utilisation**, COC calculated subtotal in EUR (partial):

| fuel price \ utilisation | −20 % | 0 % | +20 % |
|---|---:|---:|---:|
| −20 % | 3,708.24 | 3,588.47 | 3,508.64 |
| 0 % | 4,065.85 | 3,946.08 | 3,866.25 |
| +20 % | 4,423.46 | 4,303.69 | 4,223.86 |

**Payload grids** are fixed-performance economic sensitivities: Part 2 is
not rerun for the changed payload, and the output says so. A revenue payload
above the payload modelled by Part 2 is rejected.

```bash
python scripts/run_sensitivity_analysis.py --full-cost-estimate-id 1 --distance-basis modelled_route \
    --parameter fuel_price --percent-changes=-20,0,20 \
    --parameter2 annual_utilization --percent-changes2=-20,0,20 --output data/output/grid.csv --save
```

## 4. Route, aircraft and scenario comparisons

`compare_cost_scenarios.py` accepts three kinds of case:
- scenario files for one flight;
- saved full-cost estimates;
- `--route-case AIRCRAFT:ORIGIN:DESTINATION`. This resolves to the latest
  saved v2 flight with a Part 3 estimate on the pricing date. An unsupported
  aircraft gives an explicit *unsupported* row, and a missing estimate gives
  *missing_flight_estimate*. Flights are never estimated implicitly.

Each row shows:
- aircraft, route, flight, Part 3 and full-cost IDs, scenario and ownership;
- pricing date, block hours, distance (with basis) and block fuel;
- fuel, maintenance, crew, charges/handling, insurance, ownership and
  indirect group subtotals;
- COC, TOC and Total (calculated subtotal and complete);
- coverage, validity and quality.

**Rules:**
- **Complete totals** are compared as complete only if every case has them.
- **Coverage mismatch.** This is flagged when a component is calculated in
  one case and applicable but unavailable in another. Partial subtotals are
  then *not* directly comparable.
- **Not-applicable differences** (e.g. lease versus depreciation) are a
  taxonomy difference and are reported separately.
- **`common_component_comparison`** adds only components that are calculated
  (full scope) and *identically defined* in every case. "Identically defined"
  means the same scope flags (maintenance `covers`, engine-hours basis, crew
  `includes_allowances`, lease `includes`, overhead scopes) and the same fuel
  price series. It is never called a complete operating cost.
- **Pricing dates** that differ are flagged; **currencies** that differ are
  rejected.
- **Shared scenarios.** If the same scenario is applied to different aircraft
  types, a warning says its inputs are not aircraft-specific.

**Example (real database, owned illustrative scenario, 2025-01-15, all partial):**

| Case | Fuel | COC subtotal | Total subtotal |
|---|---:|---:|---:|
| A320 FRA→CDG (flight 2) | 1,788.05 | 3,946.08 | 5,443.13 |
| A320 CDG→FRA (flight 3) | 1,787.38 | 3,945.72 | 5,443.02 |
| A321 FRA→CDG (flight 4) | 1,972.92 | 4,128.34 | 5,623.61 |
| B777F FRA→CDG | unsupported: no performance model; no passenger substitute | — | — |

The A320 and A321 rows use the same illustrative A320 scenario. Their
difference therefore comes only from fuel, block time and allocation, and the
comparison warns about this.

## 5. Owned versus operating lease

`ownership_comparison` requires:
- the same flight estimate for both cases;
- modes `owned` and `operating_lease`.

It warns when the two scenarios differ in anything other than the ownership
sections (`operating_lease.`, `depreciation.`, `financing.`).

| Item (A320 FRA→CDG, EUR) | Owned | Operating lease | Lease − owned |
|---|---:|---:|---:|
| Maintenance | 880.16 | 880.16 | 0.00 |
| Crew | 698.82 | 698.82 | 0.00 |
| Insurance | 79.84 | 79.84 | 0.00 |
| Lease payment | n/a | 1,437.17 | — |
| Depreciation | 898.23 | n/a | — |
| Financing interest | 598.82 | n/a | — |
| COC (calculated subtotal) | 3,946.08 | 5,383.25 | 1,437.17 |
| TOC (calculated subtotal) | 4,844.31 | 5,383.25 | 538.94 |
| Total costs (calculated subtotal) | 5,443.13 | 5,383.25 | −59.88 |

**Why the totals differ.** Under the project taxonomy the lease payment is a
direct fixed cost inside COC. Depreciation enters only in TOC, and financing
interest only in Total costs. So an owned aircraft's capital cost appears
lower in the cost chain than a leased aircraft's. That is why COC differs by
the full lease while Total costs differ by only −59.88.

This is an economic-cost comparison under illustrative assumptions, **not an
IFRS 16 comparison**: a lessee's accounts would show right-of-use
depreciation and lease interest instead of rent. Not-applicable items are
shown as *n/a*, never as zero, and incompatible treatments are never
combined.
