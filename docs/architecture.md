# Architecture (Parts 1–4: data foundation, flight performance, variable costs, full operating costs)

## Components

| Module | Responsibility |
|---|---|
| `config.py` | Project root detection, paths, dataset URLs, timeouts, `.env` overrides, directory creation |
| `logging_config.py` | Structured `event key=value` logging in UTC |
| `ingestion/airports.py` | Streams the OurAirports CSV to a temporary file, computes SHA-256, renames atomically, writes a metadata sidecar, deduplicates identical snapshots |
| `ingestion/aircraft.py` | Reads aircraft records from the installed OpenAP package (no synonyms), snapshots them, and defines the curated cargo targets |
| `processing/airport_cleaner.py` | Column mapping, whitespace and case normalization, type coercion, rejection of unusable rows with a reason |
| `processing/aircraft_cleaner.py` | Converts OpenAP records into master rows with per-field provenance; builds freighter coverage rows |
| `validation/*` | Checks cleaned data and produces `ValidationReport` (blocking errors and non-blocking warnings) |
| `models/*` | SQLAlchemy ORM tables `data_source`, `airport` and `aircraft_type` (`models/base.py` holds the shared declarative base) |
| `database.py` | Engine (foreign keys on), schema creation, transactional upserts |
| `migrations/` (Alembic) | Versioned schema: `0001_part1_baseline`, `0002_part2_flight_performance`, `0003_touchdown_fuel_boundaries`, `0004_part3_variable_costs`, `0005_terminal_navigation`, `0006_part4_full_costs` |
| `performance/*` | Part 2: airport lookup, route distance, OpenAP adapter, kinematic profile, mass checks, fuel integration, iterative planning, persistence (see [flight_performance.md](flight_performance.md)) |
| `costs/*` | Part 3: pricing-date policy, ECB currency conversion, fuel cost, EUROCONTROL route charges, airport movement-charge engine, ground handling, coverage and aggregation, persistence (see [variable_cost_model.md](variable_cost_model.md)) |
| `fullcost/*` | Part 4: scenario schema and validation (`scenario.py`), shared input reader and allocation (`common.py`), maintenance, crew, insurance, ownership/financing and indirect components, taxonomy aggregation with the three dimensions (`aggregate.py`), orchestration (`calculator.py`) and persistence (see [full_cost_model.md](full_cost_model.md)) |
| `data/scenarios/*.json` | Version-controlled cost scenarios: illustrative examples and a cited FAA benchmark scenario |
| `ingestion/snapshots.py` | Generic immutable snapshot downloader (temporary file, SHA-256, atomic rename, sidecar), used for OurAirports, EIA and ECB |
| `ingestion/fuel_prices.py`, `exchange_rates.py`, `airport_tariffs.py` | EIA XLS/API parsing, ECB CSV parsing, reviewed EUROCONTROL CSV and local airport tariff loading |
| `validation/cost_validator.py` | Observation and unit-rate validation (positivity, units, duplicates, overlapping validity) |
| `models/types.py` | `DecimalText`: exact decimal storage for money in SQLite |
| `data/reference/*.csv` | Version-controlled curated inputs and values-free source registers: freighter targets, manufacturer document references, navigation-rate sources, airport tariff sources, cost benchmark sources (`cost_benchmark_sources.csv`) |
| `data/local/` (git-ignored) | Locally transcribed rates and tariff values whose source terms do not permit (commercial) redistribution: EUROCONTROL/DFS navigation rates, Fraport tariff |
| `scripts/*` | Command-line orchestration and summaries (`ingest_*`, `verify_database`, `calculate_flight`, `calculate_variable_costs`, `calculate_full_costs`) |

## Data flow

```mermaid
flowchart LR
    subgraph Sources
        OA[OurAirports<br/>airports.csv]
        OP[OpenAP package<br/>data/aircraft/*.yml]
        CT[Curated cargo targets<br/>ingestion/aircraft.py]
    end
    subgraph Raw["data/raw (immutable)"]
        RA[airports_UTC_sha.csv<br/>+ .meta.json]
        RO[openap_aircraft_ver_sha.json]
    end
    subgraph Processing
        CA[airport_cleaner] --> VA[airport_validator]
        CC[aircraft_cleaner] --> VC[aircraft_validator]
    end
    subgraph Processed["data/processed"]
        PA[airports_clean.csv<br/>airports_rejected.csv<br/>report.json]
        PC[aircraft_types.csv<br/>cargo_aircraft_coverage.csv<br/>report.json]
    end
    subgraph DB["SQLite: database/aircraft_costs.db"]
        DS[(data_source)]
        AP[(airport)]
        AT[(aircraft_type)]
    end
    OA -- "requests, stream, temp file, atomic rename" --> RA --> CA
    OP -- "openap.prop" --> RO --> CC
    CT --> CC
    VA --> PA
    VC --> PC
    VA -- "upsert in one transaction<br/>(only if validation passed)" --> AP
    VC -- "upsert in one transaction" --> AT
    AP --> DS
    AT --> DS
```

1. **Download.** The file is streamed to `.airports_<UTC>.csv.part` while its SHA-256
   is computed. A non-200 status, network error, empty body or truncation
   removes the temporary file and raises `DownloadError`. On success it is
   renamed to `airports_<UTC>_<sha12>.csv` and a `.meta.json` sidecar is written
   (source URL, final URL after redirects, timestamp, checksum, size, ETag,
   Last-Modified). If the content matches the newest snapshot, the duplicate is
   discarded and the existing snapshot is reused.
2. **Clean.** All fields are read as text with NA inference disabled (`NA` is
   the North America continent code and the Namibia country code). Fields are
   stripped, codes uppercased, coordinates and elevation coerced to numbers,
   and `scheduled_service` mapped to a nullable Boolean. Unusable rows go to a
   rejected file with a reason, and the first occurrence of a duplicate id is
   kept. All airport types are preserved, including heliports and closed
   airports.
3. **Validate.** The validator re-checks invariants (unique ids, coordinate
   ranges, numeric types, non-empty identifiers) and records missing values,
   counts by country and type, and warnings. Data is loaded only if there are
   no blocking errors.
4. **Load.** One transaction registers the `data_source` row (keyed by dataset
   name and checksum) and upserts records on stable keys (`source_airport_id`,
   `aircraft_code`) using SQLite `INSERT ... ON CONFLICT DO UPDATE ... WHERE <values differ>`.
   Unchanged rows are not rewritten, so `updated_at` reflects real changes. Any
   failure rolls back everything, including the source row.

## Why raw data is preserved

The raw download is the evidence for every number in the database. Keeping it
byte for byte, with its checksum and retrieval time, makes it possible to:

- reproduce or audit any cleaned output;
- re-clean old versions after fixing a cleaning bug;
- tell which upstream version a record came from (OurAirports changes nightly).

Raw files are never edited. Each new version is a new file.

## Why cleaning and validation are separate

The cleaner *transforms* data and decides which rows cannot be used at all.
The validator *checks* the result independently and decides whether the dataset
may be loaded. Keeping them separate:

- makes each one testable on its own;
- means a bug in the cleaner shows up in the validator instead of slipping through;
- lets the validator also run against data from other cleaners or sources later.

Missing optional fields are warnings, never grounds to reject a dataset.

## Schema migrations

The schema is managed with Alembic. Migrations live in the package
(`src/aircraft_cost_model/migrations`), so they work after installation and
from any working directory.

- `database.migrate_database(url)` runs at the start of every script.
  - An empty database gets all migrations.
  - A versioned database gets any pending migrations.
  - An **unversioned** Part 1 database is first compared with the schema the
    baseline migration would create: columns, types, nullability, indexes and
    unique and foreign keys. Only an exact match is *stamped* at
    `0001_part1_baseline` and then upgraded. A mismatch raises
    `SchemaVerificationError` and leaves the database untouched.
- Migrations are additive. `0002` adds columns with `ALTER TABLE … ADD COLUMN`
  and back-fills them from existing data; Part 1 tables are never recreated.
- The CLI equivalent is `alembic upgrade head`, run from the repository root.
- Tests check that the ORM models and the migrated schema match exactly
  (`alembic.autogenerate.compare_metadata`), and that the
  downgrade/upgrade round trip preserves Part 1 data.

On 2026-10-15 the live database was backed up to
`database/aircraft_costs.pre-part2-<UTC>.db` (git-ignored), verified, stamped
and upgraded. Its 86,251 airports, 42 aircraft types and data sources were
preserved.

## Why SQLite

- It needs no server: one file, part of the Python standard library, and works
  the same on macOS, Linux and Windows.
- It handles the current volumes easily (~86k airports, ~40 aircraft types).
- It enforces relational integrity (foreign keys, unique constraints) and
  supports transactions and `ON CONFLICT` upserts.
- SQLAlchemy keeps the code portable. Moving to PostgreSQL later mostly means
  replacing the SQLite-specific upsert (`sqlalchemy.dialects.sqlite.insert`)
  with the PostgreSQL equivalent.

All schema changes go through Alembic migrations (see above).

## How the tables connect

```mermaid
erDiagram
    data_source ||--o{ airport : "source_id / last_seen_source_id"
    data_source ||--o{ aircraft_type : "source_id"
    airport ||--o{ route : "origin / destination"
    route ||--o{ flight_estimate : "route_id"
    airport ||--o{ flight_estimate : "origin / destination"
    aircraft_type ||--o{ flight_estimate : "aircraft_type_id"
    flight_estimate ||--|{ flight_phase : "8 phases (7 for v1 rows)"
    flight_estimate ||--o{ flight_assumption : "assumptions"
    flight_estimate ||--o{ variable_cost_estimate : "priced for a pricing date"
    variable_cost_estimate ||--|{ cost_component : "fuel, navigation, terminal, landing, handling"
    data_source ||--o{ fuel_price : "EIA snapshot"
    data_source ||--o{ exchange_rate : "ECB snapshot"
    data_source ||--o{ navigation_rate : "en-route and terminal rates"
    data_source ||--o{ navigation_zone_aerodrome : "terminal zone lists"
    data_source ||--o{ airport_tariff : "airport document"
    airport ||--o{ airport_tariff : "tariff versions"
    data_source ||--o{ cost_component : "price/tariff used"
    cost_scenario ||--o{ cost_assumption : "typed inputs"
    cost_scenario ||--o{ full_cost_estimate : "scenario used"
    flight_estimate ||--o{ full_cost_estimate : "time bases"
    variable_cost_estimate ||--o{ full_cost_estimate : "exact Part 3 result"
    full_cost_estimate ||--|{ full_cost_component : "17 components"
    cost_component ||--o{ full_cost_component : "part3_cost_component_id"
```

- `route` stores only stable airport-pair facts: the great-circle distance and
  its method. Scenario-specific route factors and distances belong to
  `flight_estimate`.
- `flight_estimate` stores inputs, results, the model name and version, the
  exact OpenAP model code and engine, the loading checks (JSON), warnings, a
  hash of the inputs and the path of the trajectory CSV. Per-time-step states
  are written to `data/processed/flights/flight_estimate_<id>_<hash>.csv`
  rather than the database.
- Part 3 `variable_cost_estimate` references `flight_estimate` (v2 only) and
  stores one `cost_component` per component. Every price, rate and tariff
  references its `data_source`. Reference tables keep all historical versions
  (by observation date or validity interval).
- Part 4 `full_cost_estimate` references the flight estimate, the exact
  variable-cost estimate and the `cost_scenario` (stored once per content
  hash). Its Part 3 components link to the original `cost_component` rows,
  so historical Part 3 results are reused rather than recomputed.

## Part 3 data flow

```mermaid
flowchart LR
    EIA[EIA XLS / API] --> SF[raw snapshot] --> PF[parse + validate] --> FP[(fuel_price)]
    ECB[ECB Data Portal CSV] --> SE[raw snapshot] --> PE[parse + validate] --> ER[(exchange_rate)]
    CIRC[EUROCONTROL / DFS PDFs] -->|manual transcription, local only| NCSV[local CSV] --> NR[(navigation_rate + zone aerodromes)]
    TAR[Airport tariff PDF] -->|manual transcription, local only| TJ[local JSON] --> AT[(airport_tariff)]
    FE[(flight_estimate v2)] --> CALC[calculate_variable_costs]
    FP --> CALC
    ER --> CALC
    NR --> CALC
    AT --> CALC
    CALC --> AGG[coverage + subtotal] --> VCE[(variable_cost_estimate + cost_component)]
```

## Part 4 data flow

```mermaid
flowchart LR
    SC[scenario JSON] --> PS[parse + validate: decimal strings, units, source types, periods] --> CALC4[calculate_full_costs]
    FE[(flight_estimate v2)] -->|block, airborne, engines, validity| CALC4
    VCE[(variable_cost_estimate + cost_component)] -->|saved Part 3 rows| CALC4
    ER[(exchange_rate)] --> CALC4
    CALC4 --> COMP[maintenance, crew, insurance, ownership, financing, indirect] --> AGG4[taxonomy: DV, DF, indirect, COC, TOC, total + 3 dimensions]
    AGG4 --> FCE[(cost_scenario, cost_assumption, full_cost_estimate, full_cost_component)]
```

## Part 2 data flow

See [flight_performance.md](flight_performance.md) for the full pipeline
diagram, equations and limitations.
