# BTS Form 41 research, ingestion and benchmark methodology (Part 5)

Research was done on 2026-10-15 on the official site, https://www.transtats.bts.gov/
(Bureau of Transportation Statistics, Office of Airline Information). Every
statement below was checked against a TranStats page or against the
downloaded data.

## 1. Datasets and schedules

**Database "Air Carrier Financial Reports (Form 41 Financial Data)"**
- Who reports: large certificated U.S. carriers with annual operating
  revenue of $20 million or more. Some schedules also cover smaller carriers.
- Data run from 1990 to 2026. The financial formats changed in October 2006.

| Schedule | Content | Frequency | Level |
|---|---|---|---|
| **P-5.2** (table FMK) | Aircraft operating expenses: flying operations, direct maintenance, depreciation; airborne hours, aircraft days, fuel issued | quarterly | **carrier × aircraft type × configuration × reporting region** |
| P-5.1 (FMJ) | Aircraft operating expenses for large and medium regional carriers | quarterly/semiannual | carrier × aircraft type |
| P-6 (FME) | Operating expenses by objective grouping | quarterly | carrier (fleet) |
| P-7 (FKL) | Operating expenses by functional grouping | quarterly | carrier (fleet) |
| P-1.2 (FMI) | Profit and loss statement | quarterly | carrier |
| P-12(a) (FMH) | Fuel cost and gallons consumed | monthly | carrier |
| B-43 (GEH) | Airframe and engine inventory | annual | aircraft |

**Database "Air Carrier Summary Data (Form 41 and 298C)", table T2** (FIH)
- Quarterly traffic and capacity by carrier × aircraft type × configuration ×
  region × **service class**.
- Fields: ramp-to-ramp hours (630), airborne hours (650), revenue airborne
  hours (610), revenue departures performed (510), revenue aircraft miles
  (410), revenue ton-miles (240; freight 247; mail 249), available ton-miles
  (280), aircraft days (810) and fuel gallons (921).
- Data were available to June 2026 at verification.

**Answers to the research questions:**

| Question | Answer |
|---|---|
| 1. Operating expenses | P-5.2 by aircraft type; P-6/P-7 at carrier level (P-5.1 for regionals) |
| 2. Aircraft operating hours | P-5.2 Z6500 airborne hours (in thousands); T2 ramp-to-ramp (block) and airborne hours |
| 3. Departures / cycles | T2 revenue departures performed (510). Non-revenue departures are not in T2 |
| 4. Revenue cargo traffic | T2 freight and mail revenue ton-miles (247, 249); total RTM (240) includes passengers |
| 5. Aircraft-type level | P-5.2, T2 (and B-43 inventory) |
| 6. Passenger versus cargo | `AIRCRAFT_CONFIG`: 1 passenger, 2 freight, 3 combi, 9 unattributed. T2 service classes also distinguish scheduled all-cargo (G) and non-scheduled all-cargo (P) |
| 7. Carriers and periods | U.S. certificated carriers above the revenue threshold. Ingested: 2024Q1–2026Q2 (10 quarters) |
| 8. Mappable categories | See §4 |
| 9. Overlaps | Total flying operations includes fuel, crew, rentals and insurance. Total aircraft operating expense = flying operations + total flight-equipment maintenance + flight-equipment depreciation/amortisation (checked in the data: the residual is ≥ 0). Total maintenance includes applied burden (allocated overhead) |
| 10. Definition differences | See §5 |

## 2. Cargo-only carriers (verified in the 2024–2026 data)

Rows with freight configuration, quality `ok`:

| Carrier | Freight-configured types reported (BTS codes) | Quarters |
|---|---|---|
| FedEx (FX) | 757-200 (622), 767-300 (626), **777F (683)**, A300-600 (691), MD-11 (740), small aircraft under waiver code 110 | 2024Q1–2026Q2 |
| UPS (5X) | 757-200, 767-300, A300-600, MD-11, **747-400 (819)**, 747-8 (821) | 2024Q1–2026Q2 |
| Atlas Air (5Y) | 737-800, 767-300, 777-200, 747-400, 747-8 (also passenger-configured charters) | 2024Q1–2026Q2 |
| Kalitta Air (KAQ) | **777F (683)**, 747-400 (819) | 2024Q1–2026Q1 |
| ABX Air, Air Transport International | 767-200/-300 | 2024Q1–2026Q2 |
| Western Global (KD), Sky Lease Cargo (WI) | **747-400F (820)**, MD-11 | 2024Q1–2026Q2 |
| National Airlines (N8) | 747-400 | 2024Q1–2026Q2 |
| Amerijet (M6), Northern Air Cargo (NC) | 767-300 | various |
| Polar Air Cargo (PO) | 747-8 | 2024Q1–2025Q1 |

**Target freighters:**
- **777F (683):** FedEx and Kalitta.
- **767-300 in freight configuration (626/2):** 7 carriers. This includes
  converted aircraft.
- **747-400 freighters:** reported both as 819 with configuration 2 and as
  820.
- **A330-200F:** no freight-configured A330-200 rows were found.
- **A321P2F:** no verified BTS code exists (see
  `data/reference/bts_aircraft_type_mapping.csv`).

**Benchmark-only values for 2025** (aircraft operating expense, USD; no
model estimate exists for these aircraft):

| Aircraft (BTS) | Carriers | Op. expense / block hour | Fuel / BH | Maintenance (total) / BH | Pilots / BH | Op. expense / revenue tonne-NM | Avg stage (NM) |
|---|---|---:|---:|---:|---:|---:|---:|
| 777F (683/2) | FX, KAQ | 12,940 | 4,264 | 3,022 | 2,187 | 0.562 | 2,695 |
| 767-300 freight (626/2) | 5X, 5Y, 8C, ABX, FX, M6, NC | 6,984 | 2,193 | 1,548 | 1,470 | 0.738 | 943 |
| 747-400 freight (819/2) | 5X, 5Y, KAQ, N8 | 16,801 | 7,684 | 3,142 | 2,133 | 0.708 | 2,711 |
| 747-400F (820/2) | KD, WI | 11,572 | 4,713 | 1,600 | 1,380 | 0.546 | 3,242 |
| A320 passenger (694/1) | AA, B6, DL, F9, G4, GCA, NK, UA | 5,642 | 1,901 | 1,199 | 1,167 | not cargo (RTM includes passengers) | 801 |

"Aircraft operating expense" (account 70989) covers flying operations,
flight-equipment maintenance and depreciation only. It excludes ground
handling, landing fees, sales, general and administrative costs, and
interest. It is therefore **not** COC or TOC.

## 3. Ingestion (implemented for a documented subset)

**Access.**
- The TranStats Download page is an ASP.NET form without a bot challenge.
  `ingestion/bts_form41.py` makes the same requests a browser does: GET the
  form, then POST the year, all quarters and all fields.
- The returned ZIP is stored **byte for byte** in `data/raw/bts/`
  (git-ignored), with a metadata sidecar: URL, retrieval time, SHA-256 and
  size.
- Lookup tables come from TranStats' `Download_Lookup.asp`, using the exact
  identifiers shown on the form.

**Licence.** BTS states that its material is in the public domain and may be
reused without permission; citation is required. The data are U.S.
Government works.

**Subset ingested.**
- Tables: P-5.2 + T2.
- Years: 2024, 2025 and 2026 (to Q2), chosen to overlap the ECB rate history
  used for EUR conversion.
- Categories (each listing the exact P-5.2 accounts it sums, all required):

| Category | Accounts |
|---|---|
| `fuel` | 51451 |
| `pilots_and_copilots` | 51230 |
| `flight_crew_excluding_other_personnel` | 51230 + 51281 + 51360 + 51570 + 51680 |
| `maintenance_direct` | 52780 |
| `maintenance_total` | 52990 |
| `insurance` | 51551 |
| `rentals` | 51470 |
| `depreciation_airframe_engine` | 70751 + 70752 |
| `flying_operations_total` | 51990 |
| `aircraft_operating_total` | 70989 |

**Join.** P-5.2 (carrier entity × type × configuration × quarter) is matched
to the T2 row with the same keys and **service class Z** ("All Service, K +
V"). Summing service classes would double count, because K and V are
subtotals. The match is checked: T2 airborne hours must agree with P-5.2
airborne hours within max(10 h, 1 %).

**Unit conversions (exact).**
- Expenses: thousands of USD × 1000.
- P-5.2 hours: thousands × 1000.
- Ton-miles (short ton × statute mile) → tonne-NM: × 0.90718474 × 1609.344 / 1852 ≈ 0.78832.
- Statute miles → NM: × 1609.344 / 1852.

**Exclusions and quality flags:**
- **Excluded:** type 999 / configuration 9 rows (expenses not attributed to
  aircraft types). They are fleet-level and are never divided by a
  type-specific denominator.
- **Blank accounts** make that category unavailable (`missing_fields`). A
  blank is never zero. Example: 51240 "Other Flight Personnel" is blank for
  27 % of rows, so it is not part of the crew category.
- **Flags:**

| Flag | Meaning |
|---|---|
| `low_hours` | < 1,000 airborne hours. P-5.2 hours are published to ±5 h, and many rows are zero-activity placeholders |
| `no_traffic_match` | No T2 row matches. 645 of 715 such rows in 2024 have zero hours |
| `hours_mismatch` | T2 and P-5.2 airborne hours disagree |
| `region_mismatch` | The T2 and P-5.2 regions differ |
| `negative_amount` | Adjustments |
| `partial_quarter` | Fewer than three months reported |
| `missing_fields` | A required account is blank |

  Only `ok` rows are used by default.

**Idempotence and history.**
- Observations are keyed by source snapshot, so re-loading the same snapshot
  inserts nothing.
- A revised download is a new snapshot whose rows sit alongside the old ones.
  Benchmark selection uses the latest snapshot per period and never mixes
  snapshots.

**Real database (2026-10-15):**

| Year | Observations | P-5.2 rows | Unattributed rows excluded |
|---|---:|---:|---:|
| 2024 | 20,740 | 2,415 | 341 |
| 2025 | 20,560 | 2,400 | 344 |
| 2026 (Q1–Q2) | 10,780 | 1,247 | 169 |

- Loads are idempotent: re-running offline inserted 0 rows.

```bash
python scripts/ingest_bts_benchmarks.py --years 2024 2025 2026   # or --offline to reuse snapshots
```

Offline tests use real, unmodified excerpts in `tests/fixtures/bts/`.

## 4. Mapping to the project taxonomy

| Model metric | BTS category | Compatibility |
|---|---|---|
| fuel | `fuel` (51451) | Caveat: recorded expense (contract and into-plane prices, taxes, hedging) versus modelled block fuel at the EIA spot benchmark |
| crew salaries + allowances | `flight_crew_excluding_other_personnel` | Caveat: carrier-recorded pay, benefits, payroll taxes and personnel expenses, plus trainees |
| airframe + engine maintenance + LLP | `maintenance_total` (52990) | Caveat: recorded expense incl. applied burden; LLP accrual versus expense timing |
| insurance | `insurance` (51551) | Caveat |
| operating lease | `rentals` (51470) | Caveat: all rented flight equipment, incl. short-term |
| depreciation | `depreciation_airframe_engine` | Caveat: carrier lives/residuals; mixed owned/leased fleet |
| navigation, landing, handling, indirect, financing | not at aircraft-type level | **Not comparable**: P-6/P-7 are fleet-level and would need an allocation that is not independently justified |

## 5. Definition differences (why "comparable" is rare)

- **Accounting expense versus economic cost.** Carriers expense or
  capitalise maintenance under their own policies. Depreciation follows their
  own lives and residuals. LLP costs are expensed when replaced, not accrued
  per cycle.
- **Airborne versus block hours.** P-5.2 gives airborne hours; T2 gives
  ramp-to-ramp. The project uses each with the matching model denominator.
- **Statute miles and short tons** versus the project's NM and tonnes: these
  are converted explicitly.
- **RTM versus ATM.** For passenger-configured aircraft, BTS revenue
  ton-miles include passenger ton-miles. A comparison with the model's
  cargo-only RTNM is therefore refused.
- **Cargo-only versus mixed operations**: by configuration and carrier (some
  carriers fly both).
- **Domestic versus international**: by reporting region (D, A, L, P, I, S).
- **Calendar quarters.** These are calendar periods, not fiscal years.
- **Fleet averages.** Each benchmark averages all stage lengths flown by the
  type. Per-hour costs fall with longer stages, so the stage-length ratio is
  reported.
- **Geography.** These are U.S. carriers; the model's routes are European.

## 6. Example comparison (validation D)

**A320 FRA→CDG fuel per block hour against BTS A320 (694/1), 2025Q1:**
- Rows: 10 rows from AA, B6, DL, F9, G4, NK and UA. 7 rows were excluded
  (3 `low_hours`, 4 `no_traffic_match`).
- Benchmark: 1,953.67 USD/BH, converted at the mean of 63 ECB rates for
  2025Q1 (1.052341) = **1,856.49 EUR/BH**.
- Model: 1,788.05 EUR / 1.19764 BH = **1,492.97 EUR/BH**.
- Verdict: **comparable_with_caveats**.
- Difference: −363.52 EUR/BH (−19.6 %).
- Caveats: fuel definition, A320 family mapping, U.S. versus European
  geography, stage length 241.8 versus 829.0 NM (ratio 0.29), and FX
  conversion.

The difference is a *difference against a differently defined benchmark*,
not a measure of model error. All other comparisons for the illustrative
scenario are `not_comparable`, because their model inputs are illustrative
assumptions.

## 7. Limitations

- **Coverage.** Only U.S. carriers and only aircraft operating expense are
  covered. Ground, sales and administrative costs are only available
  fleet-wide.
- **Not ingested.** P-5.1, P-6/P-7, T-100 segment and B-43 data have not been
  loaded.
- **Pre-2024 years** need ECB rates from before 2024 for EUR conversion.
- **Rounding.** Hours are rounded to 10 h, so small rows are imprecise and
  are excluded.
- **Aircraft-type codes** group variants (e.g. 694 = A320-100/200). Freight
  configurations include converted aircraft. No A321P2F code is verified.
- **Single-carrier benchmarks** (e.g. the 777F: only FedEx and Kalitta)
  reflect those carriers' networks.
