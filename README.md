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
| 3 | **Variable operating costs**: fuel (EIA benchmark + ECB FX), EUROCONTROL en-route and terminal navigation charges, airport tariffs, ground handling, with explicit coverage | ✅ Implemented (awaiting review) |
| 4 | Maintenance, fixed and financial costs from public benchmarks | Not started |
| 5 | Analytics, scenarios, sensitivity analysis and validation | Not started |

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
| `data/reference/*.csv` | Version-controlled curated inputs (freighter targets, manufacturer document references) |
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
