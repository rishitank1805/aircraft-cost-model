# Benchmark index adjustment (Part 5)

```text
adjusted benchmark = original benchmark × target-period index ÷ base-period index
```

**Scope.** This is optional and only applies to published benchmark values
(the FAA Table 4-7 rates). **The original values are never modified.** Each
adjustment is a separate `benchmark_adjustment` record. It stores:
- the original value, currency and period;
- the index series and its source snapshot;
- the base and target periods and their mean index values;
- the factor and the adjusted value;
- the target date, the methodology, and a reason when unavailable.

## Index selection (`data/reference/benchmark_index_mapping.csv`)

| FAA category | Index | Status | Why |
|---|---|---|---|
| crew (1,378 USD/BH) | **CIU2014300000000I**: Employment Cost Index, total compensation, private industry, transportation and warehousing (NSA, quarterly, Dec 2005 = 100) | `proxy_pending_owner_approval` | Industry-wide labour cost; not pilot-specific. Pilot pay rose faster after the 2023 contract settlements |
| insurance (6 USD/BH) | **PCU524126524126**: PPI, direct property and casualty insurers (NSA, monthly) | `proxy_pending_owner_approval` | All property and casualty lines; not aviation-hull or liability specific |
| maintenance (954 USD/BH) | **none** | `unavailable` | The BLS API reported *PCU488190488190* (Other support activities for air transportation, which includes aircraft maintenance) as *non-existent* on 2026-10-15. No other aircraft-maintenance index was verified. A single CPI is not used |

**Verification:**
- The ECI series-ID **layout** was checked against
  https://www.bls.gov/help/hlpforma.htm: prefix, seasonal code, ownership,
  component, industry, occupation, subcell, periodicity.
- The **code meanings** (U = not seasonally adjusted, 2 = private industry,
  01 = total compensation, 4300 = transportation and warehousing, I = index)
  are taken from FRED's mirrored titles of this and related series. For
  example, CIU2024300000000I is "wages and salaries … transportation and
  warehousing".
- The BLS
  series-catalog pages could not be retrieved by script, and the BLS bulk
  files returned HTTP 403 (access denied); neither was bypassed.
- Values come from the official BLS Public Data API v2 (no key).
- BLS data are public domain.

## Periods

- **Base window.** The benchmark's own reporting period: FAA "YE June 2023"
  = July 2022 to June 2023. That is four ECI quarters (2022Q3–2023Q2) or 12
  PPI months. Every period must be present *and published by the target
  date*.
- **Target window.** The same number of consecutive periods, ending with the
  latest period *published* by the target date. Publication is approximated
  conservatively as period end + 45 days (quarterly ECI) or + 30 days
  (monthly PPI).
- **No future observations.** With `--retrospective` (an explicit user
  request) the lag is ignored, and the record is labelled RETROSPECTIVE.
- **Approximations:**
  - Each ECI quarterly value is treated as representative of its quarter
    (the ECI measures the pay period including the 12th of the quarter's
    last month).
  - PPI values are preliminary for four months. The count of preliminary
    values is recorded.
  - One source snapshot per series is used; snapshots are never mixed.

## Result for the 2025-01-15 pricing date (real database)

| Category | Original | Base window (mean) | Target window (mean) | Factor | Adjusted |
|---|---:|---|---|---:|---:|
| crew | 1,378 USD/BH | 2022-Q03..2023-Q02 (160.625) | 2023-Q04..2024-Q03 (173.85) | 1.082335 | **1,491.46 USD/BH** (proxy) |
| insurance | 6 USD/BH | 2022-M07..2023-M06 (164.5831) | 2023-M12..2024-M11 (183.3336) | 1.113927 | **6.68 USD/BH** (proxy) |
| maintenance | 954 USD/BH | — | — | — | **unavailable** (no verified index) |

**How adjusted values are used:**
- They are used only when a comparison explicitly asks for them
  (`BenchmarkSelection.use_adjusted_target_date`). The period check then
  reports the adjustment as a caveat.
- They are **not** written into any scenario: the FAA benchmark scenario
  keeps the published values.
- Whether proxy-adjusted values may be used at all is an owner decision.

```bash
python scripts/ingest_price_indices.py --start-year 2021 --end-year 2026 --adjust-target-date 2025-01-15
```
