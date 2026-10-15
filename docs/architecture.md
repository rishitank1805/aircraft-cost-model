# Architecture (Part 1: data foundation)

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
| `scripts/*` | Command-line orchestration and summaries |

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

## Why SQLite

- It needs no server: one file, part of the Python standard library, and works
  the same on macOS, Linux and Windows.
- It handles the current volumes easily (~86k airports, ~40 aircraft types).
- It enforces relational integrity (foreign keys, unique constraints) and
  supports transactions and `ON CONFLICT` upserts.
- SQLAlchemy keeps the code portable. Moving to PostgreSQL later mostly means
  replacing the SQLite-specific upsert (`sqlalchemy.dialects.sqlite.insert`)
  with the PostgreSQL equivalent.

Schema creation currently uses `Base.metadata.create_all`, which only creates
missing tables. **Future schema changes must use migrations (e.g. Alembic).**

## How future tables will connect (Parts 2–5, not implemented)

```mermaid
erDiagram
    data_source ||--o{ airport : "provenance"
    data_source ||--o{ aircraft_type : "provenance"
    airport ||--o{ flight : "origin / destination (Part 2)"
    aircraft_type ||--o{ flight : "operated by (Part 2)"
    flight ||--o{ flight_cost_item : "cost lines (Parts 3-4)"
    data_source ||--o{ flight_cost_item : "benchmark / tariff source"
```

- A future `flight` (or `route`) table will reference `airport.airport_id` for
  origin and destination and `aircraft_type.aircraft_type_id` for the aircraft.
  It will also store distance, block time and fuel burn, computed with OpenAP
  using `aircraft_type.icao_type_designator` / `aircraft_code` and
  `openap_supported`.
- Cost tables (fuel price series, navigation unit rates, airport tariffs,
  maintenance benchmarks) will each reference `data_source`, so every cost line
  can be traced to its source or labelled assumption.
- Freighter rows (`openap_supported = false`) show which aircraft need a
  documented performance source or an explicitly labelled proxy decision before
  Part 2 can model them.
