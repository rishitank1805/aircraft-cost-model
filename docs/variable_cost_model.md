# Variable cost model (Part 3)

This model prices five variable cost components for a saved Part 2 flight
estimate: **fuel**, **navigation** (EUROCONTROL en-route charges),
**terminal navigation**, **landing** (airport movement charges) and
**ground handling**. It uses public
benchmarks and published tariffs. **Results are estimates, not an airline's
actual costs**; missing components are never treated as zero.

Crew, maintenance, insurance, leasing, depreciation, financing, cash
operating costs (COC) and total operating costs (TOC) are out of scope
(Part 4).

## 1. Inputs and pricing date

```bash
python scripts/calculate_variable_costs.py --flight-estimate-id 2 --pricing-date 2025-01-15 --currency EUR --save
```

- **`flight_estimate_id`**: a saved Part 2 estimate. Only fuel accounting
  basis **`v2`** is priced. `v1` estimates raise
  `LegacyFuelAccountingError`; their fuel quantities are never reinterpreted.
- **`pricing_date`** (ISO 8601): selects the fuel prices, exchange rates and
  tariffs. It is independent of when the flight estimate was calculated.
- **`currency`**: reporting currency (ISO 4217).
- **Optional explicit inputs** (never invented by the tool):
  - charging-zone distances (`--nav-zone`);
  - certificated MTOW (`--certificated-mtow-kg`), or the explicit
    type-level scenario (`--type-level-mtow-scenario`);
  - airport tariff inputs (`--tariff-param`);
  - handling quantities (`--handling-param`);
  - user handling prices (`--handling-assumption`);
  - fuel density override;
  - staleness windows.

### Observation selection policy (`costs/pricing.py`)

For pricing date *D* and maximum staleness *S* (default 7 days for fuel and FX):

1. Only observations dated **on or before D** are eligible. Future data is
   never used.
2. The latest eligible observation is selected, with no interpolation. The
   overall latest observation is never used for a historical date.
3. If nothing is eligible, the status is `unavailable_price`
   (`no_observation_on_or_before`).
4. If *D − observation date > S*, the status is `unavailable_price`
   (`stale`). The stale candidate is reported but not used.
5. The selected observation date and the gap in days are recorded.

Retrieval timestamps (`retrieved_at`, `data_source.retrieved_at`) are kept
separate from observation and effective dates. EIA daily prices are single
trading-day spot assessments (`observation_period = daily`), not monthly
averages.

Tariffs and unit rates are selected by validity interval
(`valid_from ≤ D ≤ valid_to`). Overlapping versions are an error, and
versions from different dates are never combined.

## 2. Fuel cost

```text
litres          = block_fuel_kg / density_kg_per_l
US gallons      = litres / 3.785411784                     (exact)
cost (USD)      = US gallons x price (USD per US gallon)
cost (EUR)      = cost (USD) / (USD per 1 EUR)             (ECB quote direction)
```

- **Fuel quantity** is Part 2 **block fuel**: taxi-out + trip + landing roll
  + taxi-in.
- **Density** defaults to the value stored with the flight estimate (0.8025
  kg/L, OpenAP's litre-to-kg factor) and is recorded as an assumption. Actual
  fuel batches vary.
- **Price** is EIA series `EER_EPJK_PF4_RGC_DPG`, the U.S. Gulf Coast
  kerosene-type jet fuel spot price FOB, in **USD per US gallon**. It is a
  public market benchmark. It is not an into-plane price at FRA, a contract
  price, a hedged price or a tax-inclusive price, and not the cost of the
  actual uplift; tankering is not modelled.
- **Unit handling:** barrels (42 US gal), litres, kg and tonnes are supported
  explicitly. An unknown price unit is an error.

**Worked example** (A320 FRA→CDG, estimate #2, 2025-01-15). Every
intermediate is kept at full Decimal precision (28 significant digits) and
rounding happens **once**, at the end:

| Step | Exact value used |
|---|---|
| Block fuel (stored float, `Decimal(str(x))`) | 2271.4893156832763 kg |
| ÷ 0.8025 kg/L | 2830.516281225266417445482866 L |
| ÷ 3.785411784 L/US gal | 747.7432952444326245710981456 US gal |
| × 2.463 USD/US gal (EIA, 2025-01-15) | 1841.691736187037554318614733 USD |
| ÷ 1.03 USD per EUR (ECB publishes "1.03" for 2025-01-15) | 1788.050229307803450794771585 EUR |
| Round half up to cents | **1,788.05 EUR** |

**Reconciliation note.** An earlier report quoted "747.74 US gal × 2.463 =
1,841.69 USD". That is incorrect: 747.74 × 2.463 = 1,841.68, and
1,841.68 ÷ 1.03 = 1,788.04. The stored result (1,788.05) is correct because
nothing is rounded before the final step. Using the displayed block fuel of
2,271.5 kg instead of the stored 2,271.489… kg would give 1,788.06. A
regression test (`test_regression_stored_estimate_reconciles_without_intermediate_rounding`)
recomputes every breakdown step from the previous one and pins the result.

## 3. Exchange rates (ECB)

ECB euro reference rates are quoted as **units of X per 1 EUR** (series
`EXR.D.X.EUR.SP00.A`) and stored as `exchange_rate(base='EUR', quote='X', rate)`.

| Conversion | Operation |
|---|---|
| EUR → X | × rate(X) |
| X → EUR | ÷ rate(X) |
| X → Y | ÷ rate(X), then × rate(Y); both quotes recorded |

The ECB publishes no rate on weekends or TARGET holidays. The latest prior
rate within the staleness window is used, with its date and gap recorded.

## 4. Navigation charges

See [tariff_methodology.md](tariff_methodology.md) §§1–2.

- **En-route (`navigation`):**
  - With explicit zone distances: the EUROCONTROL formula × the verified unit
    rates in force.
  - Without zone distances: `unavailable_route_geometry`.
- **Terminal (`terminal_navigation`):** charged at the origin under its
  terminal zone's verified rules. The arrival is zero only where the
  destination zone charges departures only. An unknown zone is
  `unavailable_public_tariff`, and a `pending_review` rate is not priced.
- **MTOW rule (both):**
  - The **certificated MTOW** (`--certificated-mtow-kg`) is required for an
    official-style result (`calculated_public_tariff`).
  - The OpenAP type-level MTOW is used only with `--type-level-mtow-scenario`,
    giving `calculated_assumption`.
  - Otherwise the result is `missing_required_input`.
- **Unresolved interpretations** (rounding direction, unrounded distance
  factor, rate end dates) are attached to every calculated navigation result
  and listed by the CLI. The truncation alternative is computed and shown.

## 5. Landing charges

Each airport charges its own movements: **origin take-off + destination
landing**, each under that airport's tariff. The component is calculated only
when both parts are. A single calculated part is shown in the breakdown but
never added to the subtotal. See [tariff_methodology.md](tariff_methodology.md) §2.

## 6. Ground handling

Handling is priced only from a public tariff whose applicability is
established: payer, aircraft category and movement must all match, and the
chargeable quantity must be known. Otherwise the status is
`unavailable_public_tariff`.

A user-supplied price may be used as an explicit scenario
(`calculated_assumption`); it is never treated as observed data. See
[tariff_methodology.md](tariff_methodology.md) §3.

## 7. Statuses and source types

| Status | Meaning |
|---|---|
| `calculated_public_tariff` | Published tariff or unit rate applied |
| `calculated_benchmark` | Public market benchmark applied (fuel) |
| `calculated_assumption` | Priced from a user-supplied assumption |
| `missing_required_input` | Tariff exists but needs inputs not available (listed) |
| `unavailable_public_tariff` | No reviewed public tariff or rate in force for the date |
| `unavailable_route_geometry` | Charging-zone distances unknown |
| `unavailable_price` | No acceptable price or FX observation (none, or stale) |
| `unsupported_aircraft` | Aircraft has no validated performance model |
| `unsupported_tariff_rule` | Tariff exists but the case is not implemented (for example ferry flights at FRA) |
| `not_applicable` | Component does not apply |
| `calculation_error` | Invalid inputs or inconsistent tariff data |

Source types: `public_tariff`, `public_market_benchmark`, `user_assumption`,
`none`.

`ComponentResult` enforces these rules:
- a non-calculated component has **no amount** (NULL, displayed as N/A);
- a calculated component must have an amount;
- a zero amount is allowed only with `zero_by_tariff_rule`.

## 8. Aggregation and coverage

- **Components:** fuel, navigation (en-route), terminal navigation, landing
  and ground handling.
- **Calculated Component Subtotal** = the sum of calculated components only.
  It is never called a total.
- **Complete Variable Cost** exists only when every applicable component is
  calculated and none is flagged `partial_scope`. Components priced from
  assumptions count as calculated but are shown separately in the coverage
  categories.
- **Coverage** is reported as a count ("2 of 5 applicable components
  calculated") with a breakdown by category: public tariff, public benchmark,
  assumption, unavailable and not applicable. A component count says nothing
  about the share of monetary cost captured.
- **Unresolved interpretations** used by calculated components are listed
  with the summary.
- All calculated components must be in the reporting currency; mixing
  currencies raises `CurrencyMismatchError`.

## 9. Monetary precision

- All money, prices and rates are `decimal.Decimal`.
- Components are rounded once, to cents, half up; the subtotal is the exact
  sum of rounded components.
- SQLite has no decimal type, and SQLAlchemy `Numeric` would store binary
  floats. The `DecimalText` column type stores the exact decimal string and
  rejects floats. Tested: `0.10 + 0.20 == 0.30`, and stored values read back
  exactly.
- Part 2 fuel quantities are floats. They are converted with their shortest
  representation (`Decimal(str(x))`).

## 10. Provenance and persistence

`variable_cost_estimate` stores the pricing date, currency, subtotal, the
complete total (NULL unless complete), coverage, the calculation version and
an input hash. The hash covers the request and every selected observation,
rate and amount, so identical inputs and snapshots give identical hashes.

`cost_component` stores, per component:
- amount (or NULL), status and source type;
- `partial_scope`;
- the `data_source` id and reference, and the observation or effective date;
- the method;
- JSON breakdown, assumptions and warnings.

## 11. Example result (real database)

Flight estimate #2 (A320 FRA→CDG), pricing date 2025-01-15, EUR, no
optional inputs:

| Component | Amount | Status |
|---|---|---|
| Fuel | 1,788.05 EUR | `calculated_benchmark` |
| Navigation (en-route) | N/A | `unavailable_route_geometry` |
| Terminal navigation | N/A | `missing_required_input` (certificated MTOW). With it: FRA's 2025 terminal rate is `pending_review` → N/A |
| Landing | N/A | `unavailable_public_tariff` (FRA 2025 tariff no longer published; CDG deferred) |
| Ground handling | N/A | `unavailable_public_tariff` |
| **Calculated Component Subtotal** | **1,788.05 EUR** | partial, 1 of 5 |
| Complete Variable Cost | unavailable | |

Runs with explicit inputs (en-route zone distances, certificated MTOW, FRA
tariff inputs, later pricing dates) use the locally loaded official rates;
their amounts are not reproduced here (see the licensing stance in
[tariff_methodology.md](tariff_methodology.md)).

## 12. Limitations

- **Fuel benchmark:** U.S. Gulf Coast FOB, not a European into-plane price.
  It excludes into-plane fees, throughput charges (for example FRA tariff
  §2.5), taxes, contracts and hedging.
- **Navigation:**
  - Zone distances must be supplied, because the route recorded by the
    Network Manager isn't available.
  - Only 2025 and 2026 rates for four EMU zones are loaded. Non-EMU zones
    need monthly adjusted rates.
  - The certificated MTOW must be supplied; the type-level value is a
    scenario only.
  - Rounding direction and rate end dates are unresolved interpretations.
- **Terminal navigation:**
  - Only French (2025–2026) and German (2026) zones are loaded.
  - Germany 2025 is `pending_review`.
  - German VAT is not modelled.
- **Landing:**
  - FRA is implemented only for pricing dates from 1 August 2026, the only
    published version.
  - CDG is deferred: ADP's document sits behind bot protection.
  - FRA needs aircraft- and flight-specific inputs: noise category, NRI
    category, emissions value, passengers, freight and local time.
- **Ground handling:** no applicable public tariff was found for FRA or
  CDG.
- **Cargo aircraft:** freighters remain unsupported in Part 2, so no cargo
  flight can be priced yet.
