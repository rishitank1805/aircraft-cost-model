# Cost scenarios and assumptions (Part 4)

Every Part 4 input comes from a JSON **scenario file**. The tool supplies no
defaults: a missing value makes the dependent component
`missing_required_input`, which is never zero.

## File structure (schema version `1`)

```jsonc
{
  "schema_version": "1", "scenario_version": "1", "name": "...", "description": "...",
  "ownership_mode": "owned | operating_lease | custom",
  "flight_type": "passenger | cargo",
  "reporting_currency": "EUR",
  "pricing_date": "2025-01-15",          // optional; must equal the Part 3 estimate's
  "effective_from": "2025-01-01", "effective_to": "2025-12-31",
  "custom_treatment": {...},              // custom mode only
  "utilization": {"annual_aircraft_block_hours": V, "annual_flights": V},
  "maintenance": {"airframe": {...}, "engine": {...}, "engine_llp": {...}},
  "crew": {"salaries": {...}, "allowances": {...}},
  "insurance": {...}, "operating_lease": {...}, "depreciation": {...}, "financing": {...},
  "indirect": {"administration": {...}, "cargo_sales": {...}, "general_administrative": {...}}
}
```

Each value `V` is an object:

```json
{"value": "300.00", "unit": "EUR/block_hour", "source_type": "illustrative_assumption",
 "source_reference": null, "notes": "...", "effective_from": null, "effective_to": null, "reference_period": null}
```

The fields follow these rules:

- **`value`**: a decimal **string**. JSON numbers with a fraction or exponent
  (floats) are rejected, so no binary rounding enters money.
- **`unit`**: either `CCY/<dimension>` for money or a plain unit.
  - Money dimensions: `block_hour`, `flight_cycle`, `engine_flight_hour`,
    `engine_cycle`, `year`, `month`, `flight`, `duty_day`, `night`,
    `revenue_tonne`. A bare `CCY` means an amount.
  - Plain units: `block_hour/year`, `flight/year`, `ratio`, `years`, `count`,
    `days`, `nights`, `tonnes`, `per_year`, `payments/year`.
  - Each input has one expected dimension. A mismatch gives
    `failed_validation`.
  - Foreign currencies are converted to the reporting currency at the ECB
    rate for the pricing date. Rates more than 7 days stale are refused.
- **`source_type`**: one of
  - `illustrative_assumption`: for demonstration only;
  - `user_assumption`: the user's own figure;
  - `public_financial_benchmark`: requires `source_reference`;
  - `observed_public_data`: requires `source_reference`.
- **`effective_from` / `effective_to`**: the period in which the scenario
  author asserts the value applies. They default to the scenario's period.
  The pricing date must fall inside it, otherwise the result is
  `failed_validation`.
- **`reference_period`**: documents the period that the source data
  describes, for example "YE June 2023" for an FAA benchmark used in a 2025
  scenario. It does not have to match the effective period, and the gap is
  visible in the assumption record.

Allocation of annual costs: each section that holds annual amounts sets
`allocation_basis`.

- `block_hours`: annual × flight block hours / `utilization.annual_aircraft_block_hours`.
- `flights`: annual / `utilization.annual_flights`.

Every scenario value is stored in `cost_assumption`, with its unit,
currency, period and source. Each component's `assumptions_json` records the
values it used.

## Shipped scenarios (`data/scenarios/`)

| File | Mode | Values | Purpose |
|---|---|---|---|
| `example_owned_aircraft.json` | owned | all `illustrative_assumption` | Exercises every Part 4 component |
| `example_operating_lease.json` | operating_lease | all `illustrative_assumption` | Lease path: no depreciation or financing |
| `benchmark_faa_us_narrowbody_partial.json` | owned | `public_financial_benchmark` (FAA, cited per value) | Real public benchmarks where they exist; incomplete by design |

**The illustrative values are not airline costs, public benchmarks or
recommendations.** The task prohibits inventing maintenance, salary, lease,
insurance or aircraft-value figures and presenting them as data. These
values are labelled at every level (file description, value notes and
`source_type`), and results built on them report source quality
`explicit_user_assumption`.

## Public cost sources

The full register is in `data/reference/cost_benchmark_sources.csv`. For each
source it records the organisation, dataset, URL, publication date, effective
period, currency, units, licence, categories, limitations and verification
status.

| Source | Use |
|---|---|
| FAA *Economic Values*, Section 4 (2024 update), Table 4-7 | Used in the benchmark scenario: maintenance, crew and insurance per block hour. Depreciation and rentals are not used (fleet blends). |
| BTS Form 41 Schedule P-5.2 | Registered, not ingested (carrier accounting expense; needs T-2 block hours) |
| BLS OEWS 53-2011 | Registered, not used (wage only) |
| Lease rates, insurance premiums, aircraft values, LLP reserves | No reusable public source found (paywalled or contractual) |

All three US sources are US Government works. The EUROCONTROL, DFS and
Fraport restrictions recorded in Part 3 are unchanged; Part 4 adds no
restricted data.

## Deferred to Part 5 (owner decisions at Part 4 approval)

- **Inflation adjustment of benchmarks: deferred.** The FAA figures stay
  exactly as published (YE June 2023, USD). An optional adjustment will be
  added only with a verified public price index (for example a BLS CPI or PPI
  series, or Eurostat HICP), its licence recorded, and the original and
  target periods documented on every adjusted value. The adjusted value must
  never overwrite the original. Until then the benchmark scenario reports the
  gap between `reference_period` and the pricing date.
- **BTS Form 41 (Schedule P-5.2 with T-2 block hours): priority Part 5
  benchmarking source**, particularly for all-cargo carriers. It is not
  ingested in Part 4.
- **Real lease, insurance and acquisition values are not required.** Part 4
  is complete with clearly labelled illustrative values (`source_type:
  illustrative_assumption`, reported as `explicit_user_assumption`). Real
  operator inputs can be supplied later as `user_assumption` scenarios.
