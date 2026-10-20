# Open Aircraft Operating Cost Model

An open, reproducible model for estimating the operating costs of cargo aircraft
on specific flights (for example an Airbus A330-200F from FRA to JFK), built in
Python from freely available public data.

The model will eventually estimate fuel, maintenance, LLP reserves, navigation
and landing charges, handling, crew, insurance, leasing, indirect costs,
depreciation and financing, and report:

- **Cash Operating Costs (COC)** = Direct Variable + Direct Fixed + Indirect Operating Costs
- **Total Operating Costs (TOC)** = COC + Non-Cash Operating Costs
- **Total Costs** = TOC + Financing Costs
- **RTNM** = Revenue Payload (t) × Distance (NM); **Cost per RTNM** = COC / RTNM

Estimates are never presented as actual airline expenses, and missing data is
never silently filled.

## Roadmap

| Part | Scope | Status |
|---|---|---|
| 1 | **Data foundation**: airports, aircraft master data, provenance, SQLite | ✅ Implemented |
| 2 | **Flight performance**: route distance, flight profile, block time, fuel burn via OpenAP | ✅ Implemented |
| 3 | **Variable operating costs**: fuel (EIA benchmark + ECB FX), EUROCONTROL en-route and terminal navigation charges, airport tariffs, ground handling, with explicit coverage | ✅ Implemented (8001a93) |
| 4 | **Full operating costs**: maintenance, crew, insurance, leasing, depreciation, financing and indirect costs from cited benchmarks or explicit scenario assumptions; COC / TOC / Total with three separate quality dimensions | ✅ Implemented (a920004) |
| 5 | **Analytics and validation**: unit metrics (block hour, NM, cycle, RTNM), scenario and sensitivity analysis, route/aircraft/ownership comparisons, BTS Form 41 benchmarks, optional index adjustment, validation, CSV/JSON/PNG reports | ✅ Implemented (e794b21) |
| 6 | **Aircraft Explorer & Learning Dashboard**: React/TypeScript web app over a read-only FastAPI layer - aircraft library and detail pages with sourced specifications, comparison, Cargo & P2F explorer, Flight Lab, Knowledge Hub, operating economics | ✅ Implemented (uncommitted, awaiting review) |

## Installation

Requires Python 3.11 or later (test suite run on 3.11.17 and 3.13.7 on macOS).

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install the package (editable) with test dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# 3. (Optional) local configuration
cp .env.example .env
```

## Usage

Run all commands from the repository root.

```bash
# Download, clean, validate and load OurAirports data
python scripts/ingest_airports.py
python scripts/ingest_airports.py --offline   # reuse the latest preserved raw snapshot

# Read OpenAP aircraft metadata + curated cargo coverage targets and load them
python scripts/ingest_aircraft.py

# Inspect the database
python scripts/verify_database.py
python scripts/verify_database.py --country DE --airport-type large_airport

# Estimate a flight (Part 2). Prints a full report; --save stores it in SQLite.
python scripts/calculate_flight.py --aircraft A320 --origin FRA --destination CDG --payload-kg 10000 --save
python scripts/calculate_flight.py --aircraft A332 --origin FRA --destination JFK --payload-kg 30000 \
    --cruise-altitude-ft 37000 --taxi-out-min 18 --taxi-in-min 9 --route-factor 1.05 \
    --contingency-pct 5 --final-reserve-fuel-kg 2500
# Ambiguous codes are rejected; disambiguate with iata:, icao: or ident: (e.g. --origin ident:AGI)
```

Both ingestion scripts are idempotent: re-running them updates changed rows and
leaves unchanged rows untouched. They never append duplicates.

`calculate_flight.py` exit codes: 0 means success, 1 means an input or model
error (for example an unsupported freighter), and 2 means infeasible loading
(nothing is saved). Flight estimates are **model estimates for cost analysis,
not dispatch fuel plans.**

### Variable costs (Part 3)

```bash
python scripts/ingest_fuel_prices.py            # EIA jet fuel spot (XLS, no key); --offline / --api
python scripts/ingest_exchange_rates.py         # ECB reference rates (USD, GBP, CHF by default)
python scripts/ingest_navigation_rates.py       # en-route + terminal rates (data/local, git-ignored)
python scripts/ingest_airport_tariffs.py        # locally transcribed tariffs (data/local, git-ignored)
python scripts/calculate_variable_costs.py --flight-estimate-id 2 --pricing-date 2025-01-15 --currency EUR --save
python scripts/calculate_variable_costs.py --flight-estimate-id 2 --pricing-date 2025-01-15 \
    --nav-zone GERMANY:170:1:0 --nav-zone FRANCE:290:0:1 \
    --certificated-mtow-kg 78000     # explicit zone distances + AFM certificated MTOW (illustrative values)
# --type-level-mtow-scenario uses OpenAP's type MTOW instead, labelled as a scenario assumption
python scripts/verify_cost_database.py
```

Unavailable components print as `N/A`, never zero. The output reports a
**Calculated Component Subtotal** and a separate **Complete Variable Cost**,
which is shown only when every component is fully calculated. See
[docs/variable_cost_model.md](docs/variable_cost_model.md).

### Full operating costs (Part 4)

```bash
python scripts/calculate_full_costs.py --flight-estimate-id 2 --variable-cost-estimate-id 2 \
    --scenario data/scenarios/example_owned_aircraft.json --save
python scripts/calculate_full_costs.py --flight-estimate-id 2 --variable-cost-estimate-id 2 \
    --scenario data/scenarios/benchmark_faa_us_narrowbody_partial.json
```

Part 4 reads the saved Part 3 components and prices the rest from a JSON
scenario (see [docs/cost_assumptions.md](docs/cost_assumptions.md)). The
shipped `example_*` scenarios use **illustrative values that are not airline
costs**. The output reports:

- calculated subtotals for each category, COC, TOC and Total;
- separately, a **Complete COC / TOC / Total Costs**, shown only when every
  applicable component was calculated;
- three independent dimensions: **cost coverage**, **operational validity**
  (from Part 2) and **source quality**.

Results are economic cost estimates, not accounting expense. See
[docs/full_cost_model.md](docs/full_cost_model.md).

### Analytics and validation (Part 5)

```bash
python scripts/ingest_bts_benchmarks.py --years 2024 2025 2026          # BTS Form 41 P-5.2 + T2 (public domain)
python scripts/ingest_price_indices.py --start-year 2021 --end-year 2026 --adjust-target-date 2025-01-15
python scripts/calculate_unit_metrics.py --full-cost-estimate-id 1 --distance-basis modelled_route
python scripts/run_sensitivity_analysis.py --full-cost-estimate-id 1 --distance-basis modelled_route \
    --parameter fuel_price --percent-changes=-20,-10,0,10,20 --output data/output/fuel_sensitivity.csv
python scripts/compare_cost_scenarios.py --flight-estimate-id 2 --variable-cost-estimate-id 2 --distance-basis modelled_route \
    --scenario-files data/scenarios/example_owned_aircraft.json data/scenarios/example_operating_lease.json --ownership
python scripts/validate_cost_estimates.py --full-cost-estimate-id 1
python scripts/generate_cost_report.py --full-cost-estimate-id 1 --distance-basis modelled_route \
    --ownership-scenario data/scenarios/example_operating_lease.json --output-dir data/output/reports/example
```

Estimate IDs above are those of the reference database. Look up your own,
because a fresh installation has different IDs.

- **Partial labels.** A partial cost per block hour, NM or cycle is labelled
  *Partial*. Complete unit costs exist only when the complete total does.
- **RTNM** needs an explicitly supplied revenue cargo payload; the Part 2
  modelled payload is never used.
- **Recalculation.** Scenario variations go through the Part 3/4 engines and
  never overwrite saved estimates.
- **Benchmarks.** Comparisons report `comparable`, `comparable_with_caveats`
  or `not_comparable` with reasons; differences are not called model error.

See [docs/analytics.md](docs/analytics.md).

### Aircraft Explorer (Part 6)

```bash
python scripts/ingest_aircraft_specifications.py     # specification values with provenance (insert-only)
cd frontend && npm install && npm run build && cd ..
python scripts/run_explorer.py                       # http://127.0.0.1:8000 (read-only database)
```

The explorer lets you browse all aircraft in the database and open a detail page per
aircraft, with dimensions, weights, engines, performance, cargo, and sources and
limitations. It also offers aircraft comparison, freighters and P2F conversion, the
OpenAP-based Flight Lab, a glossary, the cost analytics.

- Every value shows its source, unit, source type and verification status.
- Missing values are shown as unavailable.
- Passenger specifications are never shown as freighter specifications.

See [docs/explorer_app.md](docs/explorer_app.md),
[docs/aircraft_specifications.md](docs/aircraft_specifications.md) and
[docs/design_system.md](docs/design_system.md).

### Database migrations

The schema is managed with Alembic, and every script brings the database up to
date automatically (`database.migrate_database`). A Part 1 database created
before Alembic is checked against the baseline schema before it is stamped;
it is never recreated. To migrate by hand, run from the repository root:

```bash
alembic upgrade head
alembic current
```

Outputs:

| Location | Content |
|---|---|
| `data/raw/airports/airports_<UTC>_<sha12>.csv` + `.meta.json` | Unmodified download plus URL, timestamp, SHA-256, size, HTTP headers |
| `data/raw/aircraft/openap_aircraft_<version>_<sha12>.json` | Unmodified OpenAP aircraft records |
| `data/processed/airports/airports_clean.csv`, `airports_rejected.csv` | Cleaned rows; rejected rows with a `rejection_reason` |
| `data/processed/aircraft/aircraft_types.csv`, `cargo_aircraft_coverage.csv` | Aircraft master data; freighter coverage |
| `data/processed/*/*_validation_report.json` | Validation reports |
| `data/processed/flights/flight_estimate_<id>_<hash>.csv` | Per-time-step trajectory of saved flight estimates |
| `data/reference/*.csv` | Version-controlled curated inputs and source registers (freighter targets, manufacturer documents, navigation, tariff and cost benchmark sources) |
| `data/scenarios/*.json` | Version-controlled Part 4 cost scenarios (illustrative examples and a cited FAA benchmark) |
| `data/raw/bts/`, `data/raw/price_indices/` | Raw BTS ZIP and BLS JSON snapshots (git-ignored) |
| `data/output/` | Generated Part 5 reports, CSV/JSON exports and charts (git-ignored) |
| `database/aircraft_costs.db` | SQLite database |

## Tests

```bash
pytest
```

Tests use small fixture files, temporary directories and temporary SQLite
databases. They need no internet access and never touch `database/aircraft_costs.db`.

## Documentation

- [docs/architecture.md](docs/architecture.md): components, data flow, migrations, design decisions
- [docs/flight_performance.md](docs/flight_performance.md): Part 2 pipeline, equations, coverage, limitations
- [docs/flight_assumptions.md](docs/flight_assumptions.md): every flight-estimate assumption and its effect
- [docs/variable_cost_model.md](docs/variable_cost_model.md): Part 3 methods, statuses, coverage, precision
- [docs/full_cost_model.md](docs/full_cost_model.md): Part 4 taxonomy, completeness, the three dimensions, worked example
- [docs/maintenance_costs.md](docs/maintenance_costs.md), [docs/crew_costs.md](docs/crew_costs.md), [docs/ownership_and_financing.md](docs/ownership_and_financing.md): Part 4 component methods
- [docs/cost_assumptions.md](docs/cost_assumptions.md): scenario file schema, shipped scenarios, public financial sources
- [docs/explorer_app.md](docs/explorer_app.md), [docs/aircraft_specifications.md](docs/aircraft_specifications.md), [docs/design_system.md](docs/design_system.md): Part 6 explorer, specification sources and missing-data inventory, design system
- [docs/analytics.md](docs/analytics.md): Part 5 overview, dimensions, scripts, reproducibility
- [docs/unit_cost_metrics.md](docs/unit_cost_metrics.md), [docs/scenario_analysis.md](docs/scenario_analysis.md), [docs/benchmark_validation.md](docs/benchmark_validation.md), [docs/bts_form41_methodology.md](docs/bts_form41_methodology.md), [docs/inflation_adjustment.md](docs/inflation_adjustment.md), [docs/reporting.md](docs/reporting.md): Part 5 methods
- [docs/tariff_methodology.md](docs/tariff_methodology.md): EUROCONTROL, FRA/CDG and handling tariff rules
- [docs/cost_data_sources.md](docs/cost_data_sources.md): EIA, ECB, EUROCONTROL and airport sources and licences
- [docs/data_dictionary.md](docs/data_dictionary.md): every table and column
- [docs/data_sources.md](docs/data_sources.md): sources, licences, limitations
- [AGENTS.md](AGENTS.md): rules for AI coding sessions

## Current limitations

- **The target freighters cannot be modelled yet.** OpenAP 2.6.2 has no
  freighter models, and the manufacturer documents (Airbus AC, Boeing ACAPS)
  do not permit data reuse without permission. Estimates for A330-200F, 777F,
  767-300F, 747-400F and A321P2F return an explicit `UnsupportedAircraftError`.
- **Only 16 OpenAP types support flight estimates.** These have a complete
  WRAP, drag-polar and engine model. The other 21 OpenAP types (for example
  A21N, B763 and B772) are rejected rather than mapped to a similar type.
- **MZFW, maximum payload and maximum ramp weight are unavailable.** So no
  estimate is fully validated; its status is `calculated_limits_unverified`.
- **No wind, ISA atmosphere and mean WRAP kinematics.** Clean-configuration
  drag; no reverse thrust or derate. Default taxi times are not
  airport-specific. Routes are great-circle distance × a factor, not flown
  routes. See [docs/flight_assumptions.md](docs/flight_assumptions.md).
- **No regulatory fuel policy.** Reserves are user-supplied and default to 0.
  The output is **not a dispatch fuel plan**.
- **Type-level OEW and limits from OpenAP.** They are not operator- or
  weight-variant-specific.
- **Not every airport suits cargo operations.** This is not assessed yet.
- **Variable costs are partial.**
  - Fuel uses a U.S. Gulf Coast spot benchmark.
  - En-route navigation needs explicit charging-zone distances and a
    certificated MTOW. Terminal charges are loaded for France (2025–2026)
    and Germany (2026); Germany 2025 is pending review.
  - Navigation and Fraport rates are local only (licensing).
  - Landing: FRA has a tariff only from 1 Aug 2026; CDG is unavailable.
  - Ground handling has no public tariff.
  - No estimate is "complete" yet. See [docs/variable_cost_model.md](docs/variable_cost_model.md) §12.
- **Full costs depend on scenario inputs.**
  - No reusable public source exists for lease rates, insurance premiums,
    aircraft values, LLP reserves or European crew pay. These must be
    supplied by the user.
  - The FAA benchmark is a US passenger-narrowbody average from YE June 2023.
    It is applied unadjusted and is not freighter-specific.
  - No complete COC exists for the example flight, because the Part 3
    components are incomplete.
- **Analytics inherit every gap above.**
  - Unit costs for the example are partial.
  - RTNM is unavailable without an explicit revenue cargo payload.
  - The target freighters remain unsupported; BTS gives benchmark-only values
    for them.
  - Public benchmarks are U.S. carrier accounting expense, so comparisons
    with European flights are at best `comparable_with_caveats`.
  - Index adjustment uses proxy indices pending owner approval; maintenance
    has no verified index.
- **Explorer specifications are partial.**
  - MZFW and maximum structural payload are missing for most aircraft.
  - Freighter dimensions and engine data are missing where no permitted source exists
    (proposals in [docs/aircraft_specifications.md](docs/aircraft_specifications.md)).
  - No licensed aircraft photographs are bundled.
