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
| 2 | Aircraft performance and flight operations (distance, block time, fuel burn via OpenAP) | Not started |
| 3 | Variable operating costs (fuel prices, EUROCONTROL charges, airport tariffs) | Not started |
| 4 | Maintenance, fixed and financial costs from public benchmarks | Not started |
| 5 | Analytics, scenarios, sensitivity analysis and validation | Not started |

## Installation

Requires Python 3.11 or later (tested with 3.13 on macOS).

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
```

Both ingestion scripts are idempotent: re-running them updates changed rows and
leaves unchanged rows untouched. They never append duplicates.

Outputs:

| Location | Content |
|---|---|
| `data/raw/airports/airports_<UTC>_<sha12>.csv` + `.meta.json` | Unmodified download plus URL, timestamp, SHA-256, size, HTTP headers |
| `data/raw/aircraft/openap_aircraft_<version>_<sha12>.json` | Unmodified OpenAP aircraft records |
| `data/processed/airports/airports_clean.csv`, `airports_rejected.csv` | Cleaned rows; rejected rows with a `rejection_reason` |
| `data/processed/aircraft/aircraft_types.csv`, `cargo_aircraft_coverage.csv` | Aircraft master data; freighter coverage |
| `data/processed/*/*_validation_report.json` | Validation reports |
| `database/aircraft_costs.db` | SQLite database |

## Tests

```bash
pytest
```

Tests use small fixture files, temporary directories and temporary SQLite
databases. They need no internet access and never touch `database/aircraft_costs.db`.

## Documentation

- [docs/architecture.md](docs/architecture.md): components, data flow, design decisions
- [docs/data_dictionary.md](docs/data_dictionary.md): every table and column
- [docs/data_sources.md](docs/data_sources.md): sources, licences, limitations
- [AGENTS.md](AGENTS.md): rules for AI coding sessions

## Current limitations

- **No freighter performance data.** OpenAP 2.6.2 has no freighter models. The
  A330-200F, 767-300F, 747-400F and A321P2F are recorded with related OpenAP
  passenger models for reference only. The 777F (B77L) has no OpenAP model.
  All freighter weights and performance values are NULL.
- **MZFW and maximum payload are unavailable** from OpenAP for every type (NULL).
- **The OpenAP engine field is the default engine option only.** Other options
  are kept in the processed CSV.
- **`fuel_capacity_kg` and `cruise_speed_kt` are derived values.** They are labelled
  in `field_provenance`.
- **OpenAP's nominal cruise range is kept in the processed CSV only.** It is not a
  payload-independent range.
- **Airports missing from a newer OurAirports file are kept, not deleted.** The
  ingestion summary reports how many there are.
- **The schema is created with `create_all`.** Future schema changes need migrations
  (e.g. Alembic).
- **Not every airport suits cargo operations.** An airport with an IATA code may
  still be unsuitable, and this is not assessed yet.
