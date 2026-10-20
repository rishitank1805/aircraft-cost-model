# Unit operating-cost metrics (Part 5)

```text
cost per block hour   = cost amount / block hours                       [CCY/block_hour]
cost per NM           = cost amount / distance (NM)                     [CCY/nautical_mile]
cost per flight cycle = cost amount / flight cycles                     [CCY/flight_cycle]
RTNM                  = revenue cargo payload (t) x revenue distance (NM)
cost per RTNM         = cost amount / RTNM                              [CCY/revenue_tonne_nm]
ATNM                  = available payload capacity (t) x distance (NM)
cost per ATNM         = cost amount / ATNM                              [CCY/available_tonne_nm]
load factor           = revenue payload / available payload capacity
```

**Cost amounts.** Metrics are computed for six cost bases: direct variable,
direct fixed, indirect, COC, TOC and total costs. Each basis has two cost
measures:

- `calculated_subtotal`: the sum of calculated components. It is labelled
  **Partial** when applicable components are missing.
- `complete_total`: available only when every applicable component is
  calculated with full scope.

So the A320 example reports *Partial COC per block hour = 3,294.87 EUR*, and
*Complete COC per block hour* as unavailable, with the missing components
listed.

## Denominators

| Denominator | Value | Notes |
|---|---|---|
| Block hours | Part 2 `block_time_min / 60` (off-block to on-block) | Must be > 0, otherwise an error |
| Distance | Explicit `--distance-basis` | `great_circle`: Part 2 haversine distance. `modelled_route`: Part 2 estimated route distance (great-circle × route factor). `actual_flown`: an externally supplied distance and reference (e.g. a track). The bases are never mixed; the basis is stored with every metric. Zero distance makes the metric undefined. |
| Flight cycles | 1 | One saved Part 2 estimate is one completed leg. Multi-leg or incomplete records are not supported. |
| RTNM | Explicit revenue payload × the chosen distance | See below |
| ATNM | Explicit available capacity × the chosen distance | Capacity is never derived from MZFW − OEW (MZFW is unavailable in this project) |

## Revenue payload versus modelled payload

The Part 2 `payload_kg` is a *mass assumption* for the performance model. It
is **not** revenue cargo and is never used for RTNM.

**Revenue payload rules:**
- It must be supplied explicitly (`--revenue-payload-t`), with a source type
  (`observed_public_data`, `user_assumption` or `illustrative_assumption`) and
  a reference.
- If it is missing, RTNM and cost per RTNM are **unavailable**
  (`missing_required_input`).
- If it is zero, RTNM = 0 and cost per RTNM is **undefined**: neither zero
  nor infinite.
- It must not exceed the payload used by Part 2. A larger payload needs a
  Part 2 rerun.
- For a scenario with `flight_type: passenger` (the A320 example), a cargo
  payload is accepted only with `--hypothetical-cargo`. Every output is then
  labelled *HYPOTHETICAL cargo scenario*: it does not validate cargo-aircraft
  performance, capacity or economics. No cargo payload is invented for the
  A320 example.

**RTNM versus ATNM:**
- RTNM uses revenue cargo actually carried.
- ATNM uses available capacity.
- Cost per ATNM is always ≤ cost per RTNM when capacity ≥ payload.

## Precision, currency and provenance

- Values are exact `Decimal` quotients (28 significant digits) with no
  intermediate rounding. They are stored as exact decimal text. Console output
  shows 4 decimals and says so.
- Every metric records:
  - currency, pricing date and cost basis/measure;
  - the components included and missing;
  - coverage, operational validity and source quality;
  - distance basis and payload basis;
  - the FX basis: for example, *ECB EXR.D.USD.EUR.SP00.A rate 1.03
    (2025-01-15)* for the fuel conversion, or *no currency conversion*.

## Example: A320 FRA→CDG, saved full-cost estimate 1, illustrative owned scenario

| Item | Value |
|---|---|
| Block time | 71.859 min = 1.197644 h |
| Distances | great-circle 241.81 NM; modelled route 241.81 NM (this estimate's `route_distance_method` is `great_circle`, so the two coincide) |

| Metric | Value | Status |
|---|---|---|
| Partial COC per block hour | 3,294.8700 EUR | partial (navigation, terminal navigation, landing, handling missing) |
| Complete COC per block hour | unavailable | — |
| Partial COC per NM (modelled route) | 16.3190 EUR | partial |
| Partial COC per flight cycle | 3,946.0800 EUR | partial |
| Partial TOC / total costs per block hour | 4,044.8678 / 4,544.8663 EUR | partial |
| Cost per RTNM | unavailable | no revenue cargo payload (passenger scenario) |

Dimensions: A = partial; B = `calculated_limits_unverified`;
C = `mixed: explicit_user_assumption, public_market_benchmark`.

```bash
python scripts/calculate_unit_metrics.py --full-cost-estimate-id 1 --distance-basis modelled_route
```
