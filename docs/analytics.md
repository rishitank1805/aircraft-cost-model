# Analytics, scenario analysis, benchmarking and validation (Part 5)

Part 5 is a layer over the estimates produced by Parts 2–4. It **transforms,
compares and validates** them; it contains no cost formulas of its own.
Whenever an input changes, the affected components are recalculated:

- **fuel** through the Part 3 fuel engine (`calculate_fuel_cost`);
- **everything else** through the Part 4 calculator (`calculate_full_costs`).

Saved estimates, scenario files and saved scenario rows are never modified.

| Topic | Document |
|---|---|
| Unit metrics (per block hour, NM, cycle, RTNM, ATNM) | [unit_cost_metrics.md](unit_cost_metrics.md) |
| Scenario variations, sensitivity, grids, ownership and route comparisons | [scenario_analysis.md](scenario_analysis.md) |
| Validation framework and benchmark comparability | [benchmark_validation.md](benchmark_validation.md) |
| BTS Form 41 research and ingestion | [bts_form41_methodology.md](bts_form41_methodology.md) |
| Optional benchmark index adjustment | [inflation_adjustment.md](inflation_adjustment.md) |
| Console, CSV, JSON and PNG outputs | [reporting.md](reporting.md) |

## The three dimensions

Every analytical result keeps three dimensions, and none of them changes
another.

| Dimension | Values in analytics | Source |
|---|---|---|
| A. Cost coverage | `complete`, `partial`, `missing_required_input`, `unsupported`, `calculation_error` | From the components in the numerator (and the denominator's availability) |
| B. Operational validity | e.g. `calculated_limits_unverified` | The Part 2 flight estimate, carried unchanged; a complete cost scenario never improves it |
| C. Source quality | `observed_public_data`, `public_market_benchmark`, `public_financial_benchmark`, `modelled_estimate`, `explicit_user_assumption`, `mixed: …` | The components in the numerator |

**A partial cost divided by a denominator is a partial unit cost.** Every
metric is reported twice: once from the calculated subtotal (labelled
*Partial … per …* when components are missing) and once from the complete
total (*Complete … per …*). The complete version is unavailable unless every
applicable component is calculated.

## Status distinctions used throughout

- **Complete versus partial estimates**: as above.
- **Public benchmarks versus explicit user assumptions**: separated by source
  quality. Illustrative values remain labelled `illustrative_assumption` in
  every stored input.
- **Unsupported aircraft**: the five target freighters (A330-200F, 777F,
  767-300F, 747-400F, A321P2F) have no supported performance model. They
  return explicit `unsupported` cases; no passenger model is substituted.
- **Missing operational inputs** (e.g. revenue cargo payload) and **missing
  financial inputs** (e.g. lease payment): `missing_required_input`.
- **Not-applicable components** (e.g. lease for an owned aircraft):
  `not_applicable`. These are a taxonomy difference, not missing coverage.
- **A missing cost is never zero.** It is `None` in Python, NULL in SQLite,
  N/A in the console, an empty cell in CSV, `null` in JSON, and no bar in a
  chart.

## Architecture

```text
analytics/
    cases.py        CostCase and FlightFacts: load a saved estimate exactly as stored, recalculate one,
                    or return an explicit unsupported / missing-flight case
    metrics.py      unit metrics, distance and payload bases, RTNM/ATNM, partial labels
    scenarios.py    parameter registry, immutable scenario variations, Part 3 fuel recalculation
    sensitivity.py  one-variable sensitivity and bounded two-variable grids
    comparisons.py  route / aircraft / scenario comparison, common_component_comparison, owned vs leased
    benchmarks.py   FAA reference values, BTS benchmark aggregation, comparability checks, deviations
    inflation.py    index adjustment of benchmarks (originals never modified)
    validation.py   arithmetic, operational, financial and external checks
    reporting.py    console, CSV, JSON, PNG charts
    persistence.py  immutable analytics runs keyed by input hash
    cli.py          shared command-line arguments
ingestion/bts_form41.py, processing/bts_form41.py   BTS TranStats P-5.2 + T2 snapshots and records
ingestion/price_indices.py                          BLS API index observations
```

Scripts (each has `--help`, validates input, and exits non-zero on error):

| Script | Purpose |
|---|---|
| `calculate_unit_metrics.py` | Unit metrics for a saved or recalculated case |
| `run_sensitivity_analysis.py` | One-variable sensitivity, or a two-variable grid with `--parameter2` |
| `compare_cost_scenarios.py` | Scenario, route and aircraft comparisons; `--ownership` for owned vs leased |
| `generate_cost_report.py` | Full report folder with a SHA-256 manifest |
| `validate_cost_estimates.py` | Validation A–D |
| `ingest_bts_benchmarks.py` | BTS P-5.2 + T2 snapshots, plus the FAA Table 4-7 reference values |
| `ingest_price_indices.py` | BLS index series and optional benchmark adjustment |

## Reproducibility

- Every analytics run that is saved (`--save`) records:
  - the source flight, Part 3 and full-cost estimates;
  - the base scenario ID and hash;
  - the modified assumptions;
  - pricing date, currency, distance basis and payload basis;
  - the analytics calculation version (`analytics v1`);
  - an input hash, the source-quality summary, the coverage status and the
    warnings.
- **Runs are immutable.** The input hash is unique, so saving the same request
  again returns the existing run. It also compares the newly computed result
  with the stored one (ignoring timestamps) and reports
  *reproduced exactly* or *DIFFERS*.
- **Variant scenarios** are stored once per content hash in `cost_scenario`.
  The base scenario row is never changed.
- **Historical prices.** Fuel variations reuse the saved Part 3 price
  observation. They refuse to run if the fuel engine cannot reproduce the
  saved amount. The latest market price is never substituted.
- **Database identifiers** are looked up, never assumed. A fresh installation
  has different IDs.
- **Same inputs, same outputs.** Report files are byte-identical for
  identical inputs (see `manifest.json`).

## What Part 5 does not do

- It does not estimate freighter performance or costs.
- It does not invent revenue payloads, lease rates, BTS observations or index
  values.
- It does not present a partial subtotal as a complete cost.
- It does not forecast. Sensitivity levels are user-chosen, and grids are
  deterministic scenario outcomes, not probabilities.
