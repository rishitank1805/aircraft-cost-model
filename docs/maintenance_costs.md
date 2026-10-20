# Maintenance costs (Part 4)

There are three components, kept separate so that each can be checked and
none is counted twice.

| Component | Formula | Rate unit |
|---|---|---|
| `airframe_maintenance` | block hours × rate per block hour + flight cycles × rate per flight cycle | `CCY/block_hour`, `CCY/flight_cycle` |
| `engine_maintenance` | engines × engine flight hours × rate per engine flight hour (+ engine cycles × rate per engine cycle) | `CCY/engine_flight_hour`, `CCY/engine_cycle` |
| `engine_llp` | engines × engine cycles × reserve per engine cycle | `CCY/engine_cycle` |

## Engine-hours basis (required, never implied)

`maintenance.engine.engine_hours_basis` must be set explicitly to one of the
following:

- `airborne_hours`: the Part 2 airborne time. This is closest to the usual
  "engine flight hour".
- `engine_running_estimate`: block hours, on the assumption that the engines
  run from gate to gate. This is an estimate.
- `block_hours_proxy`: block hours, labelled as a proxy, with a warning.

If the field is missing, the component is `missing_required_input`. Block
hours are never substituted silently.

## LLP is an economic accrual

Life-limited parts are replaced at certified cycle limits. A per-cycle
reserve spreads that future replacement cost over the cycles that consume
it. The result is an **economic accrual**, not a cash payment in the period:

- an airline expenses or capitalises LLP replacement when it actually
  happens;
- a lessor collects reserves under a contract.

The component's warnings say this.

## Double-counting controls

| Flag | Effect |
|---|---|
| `maintenance.airframe.covers` (must include `airframe`; may add `engine`, `engine_llp`) | A covered component becomes `not_applicable` ("included in the all-inclusive airframe maintenance rate"). If its section is supplied as well, it is `failed_validation`. |
| `maintenance.airframe.hourly_rate_includes_cycle_costs` / `maintenance.engine.hourly_rate_includes_cycle_costs` (required) | `true` together with a cycle rate gives `failed_validation`. `false` without a cycle rate gives `missing_required_input`. |
| `maintenance.engine.includes_llp` (required) | `true`: LLP is `not_applicable`, or `failed_validation` if an LLP reserve is also given. |
| Operating lease `includes: ["maintenance_reserves"]` | Rejected (`failed_validation`) when maintenance is also modelled. |

## Public sources

No public, reusable source for airframe, engine or LLP rates was found for a
specific aircraft and operator (see [cost_assumptions.md](cost_assumptions.md)
and `data/reference/cost_benchmark_sources.csv`).

FAA *Economic Values* Table 4-7 gives one **total** maintenance figure per
block hour: US Part 121 passenger narrowbody aircraft, year ending June 2023,
954 USD/BH. It can be used only as an all-inclusive airframe rate
(`covers: [airframe, engine, engine_llp]`), as in
`data/scenarios/benchmark_faa_us_narrowbody_partial.json`.

BTS Form 41 P-5.2 has airframe and engine labour and materials by aircraft
type. It is accounting expense, and it is registered but not ingested.
