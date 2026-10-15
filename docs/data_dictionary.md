# Data dictionary

SQLite database: `database/aircraft_costs.db`. All timestamps are stored in UTC
as timezone-naive `DATETIME`, because SQLite has no timezone type.
"Required" means `NOT NULL`.

## `data_source`

One row per retrieved version of a dataset. Unique on `(dataset_name, checksum)`:
re-ingesting identical content updates the existing row, and a new upstream
version gets a new row.

| Column | Type | Required | Unit | Source | Description / validation |
|---|---|---|---|---|---|
| source_id | INTEGER PK | yes | | generated | Surrogate key |
| source_name | VARCHAR(200) | yes | | ingestion script | Publisher, e.g. `OurAirports`, `OpenAP` |
| source_url | VARCHAR(500) | no | | ingestion script | Official URL that was requested |
| dataset_name | VARCHAR(200) | yes | | ingestion script | Stable dataset key, e.g. `ourairports_airports_csv`, `openap_aircraft_properties`, `cargo_aircraft_targets` |
| license | TEXT | no | | verified manually | Licence or terms, as verified (see data_sources.md) |
| access_type | VARCHAR(100) | no | | ingestion script | e.g. `HTTP download (CSV)`, `Python package`, `Manual curation` |
| retrieved_at | DATETIME | no | UTC | download / read time | When the data was retrieved |
| source_version | VARCHAR(200) | no | | HTTP `Last-Modified`, package version or checksum prefix | Human-readable version |
| checksum | VARCHAR(64) | yes | | computed | SHA-256 (hex) of the raw file, of the OpenAP aircraft data files, or of the curated list |
| notes | TEXT | no | | ingestion script | Raw snapshot filename, final URL, units, limitations |

## `airport`

Source: OurAirports `airports.csv`. Upsert key: `source_airport_id`.
Non-unique indexes: `iata_code`, `icao_code`, `gps_code`, `country_code`, `airport_type`.

| Column | Type | Required | Unit | Source field | Description / validation |
|---|---|---|---|---|---|
| airport_id | INTEGER PK | yes | | generated | Surrogate key |
| source_airport_id | INTEGER UNIQUE | yes | | `id` | OurAirports internal id. Must be an integer, unique (later duplicates rejected) |
| airport_ident | VARCHAR(16) | yes | | `ident` | OurAirports identifier, trimmed and uppercased. Rows with an empty value are rejected. **Not necessarily an ICAO code** |
| airport_name | VARCHAR(255) | no | | `name` | Trimmed |
| airport_type | VARCHAR(32) | no | | `type` | Lowercase: `large_airport`, `medium_airport`, `small_airport`, `heliport`, `seaplane_base`, `balloonport`, `closed`. All kept |
| latitude | FLOAT | yes | decimal degrees (WGS84) | `latitude_deg` | Numeric, in [-90, 90]. Otherwise the row is rejected |
| longitude | FLOAT | yes | decimal degrees (WGS84) | `longitude_deg` | Numeric, in [-180, 180]. Otherwise the row is rejected |
| elevation_ft | FLOAT | no | feet above MSL | `elevation_ft` | Numeric. Blank or non-numeric becomes NULL (warning) |
| continent | VARCHAR(2) | no | | `continent` | `AF AN AS EU NA OC SA`. `NA` = North America, never treated as missing |
| country_code | VARCHAR(2) | no | | `iso_country` | ISO 3166-1 alpha-2, uppercased (`NA` = Namibia) |
| region_code | VARCHAR(16) | no | | `iso_region` | ISO 3166-2 style region, uppercased |
| municipality | VARCHAR(255) | no | | `municipality` | Trimmed |
| scheduled_service | BOOLEAN | no | | `scheduled_service` | `yes` → true, `no` → false, anything else → NULL (warning). Does not imply cargo suitability |
| icao_code | VARCHAR(4) | no | | `icao_code` | Dedicated ICAO location indicator from the source, uppercased. NULL when absent; never inferred from `ident` or `gps_code` |
| gps_code | VARCHAR(16) | no | | `gps_code` | Uppercased |
| iata_code | VARCHAR(3) | no | | `iata_code` | Uppercased. NULL when absent. Not unique by design (duplicates reported as warnings) |
| local_code | VARCHAR(16) | no | | `local_code` | National code (e.g. FAA LID), uppercased |
| source_id | INTEGER FK | yes | | | → `data_source.source_id` of the snapshot that last updated the row |
| created_at | DATETIME | yes | UTC | | First insert |
| updated_at | DATETIME | yes | UTC | | Last real change (unchanged re-loads do not touch it) |

`home_link`, `wikipedia_link` and `keywords` are kept in
`data/processed/airports/airports_clean.csv` but not stored in the table.

## `aircraft_type`

Sources: OpenAP package (`openap_supported = true`) and the project-curated
cargo target list (`openap_supported = false`). Upsert key: `aircraft_code`.

**Provenance labels** (`field_provenance`, JSON): each populated attribute maps
to `"source"` (value as supplied), `"source: <detail>"`, or
`"derived: <method>"`. Validation fails if a derived field has no `derived:`
label.

| Column | Type | Required | Unit | Origin | Description / validation |
|---|---|---|---|---|---|
| aircraft_type_id | INTEGER PK | yes | | generated | Surrogate key |
| aircraft_code | VARCHAR(32) UNIQUE | yes | | OpenAP / curated | Normalized, uppercase project identifier. For OpenAP rows it equals the ICAO type designator (e.g. `A332`). For freighters it is a project label (e.g. `A330-200F`, `B777F`) because ICAO does not distinguish freighters. Must be unique and non-empty |
| icao_type_designator | VARCHAR(4) | no | | OpenAP filename / ICAO Doc 8643 | ICAO type designator. Not unique (A332 covers passenger and freighter) |
| manufacturer | VARCHAR(100) | no | | derived | Parsed from the OpenAP `aircraft` name for known manufacturers, otherwise NULL |
| model | VARCHAR(100) | no | | derived / curated | OpenAP name without the manufacturer |
| variant | VARCHAR(100) | no | | curated | `production freighter`, `passenger-to-freighter conversion`. NULL for OpenAP rows (not provided) |
| engine_type | VARCHAR(50) | no | | source `engine.type` | e.g. `turbofan` |
| engine_model | VARCHAR(100) | no | | source `engine.default` | Default engine option only |
| engine_count | INTEGER | no | engines | source `engine.number` | > 0 when present |
| mtow_kg | FLOAT | no | kg | source `mtow` | Maximum takeoff weight. > 0 when present |
| mlw_kg | FLOAT | no | kg | source `mlw` | Maximum landing weight |
| mzfw_kg | FLOAT | no | kg | — | Maximum zero fuel weight. **Not available from OpenAP; NULL for all rows** |
| oew_kg | FLOAT | no | kg | source `oew` | Operating empty weight (OpenAP's definition; may differ from operator OEW) |
| max_payload_kg | FLOAT | no | kg | — | **Not available; NULL.** Not derived from MZFW − OEW |
| fuel_capacity_l | FLOAT | no | litres | source `mfc` | Maximum fuel capacity as supplied. > 0 when present |
| fuel_capacity_kg | FLOAT | no | kg | **derived** | `fuel_capacity_l × 0.8025 kg/L` (density used in OpenAP `mass.py`). > 0 when present |
| cruise_mach | FLOAT | no | Mach | source `cruise.mach` | Nominal cruise Mach |
| cruise_altitude_m | FLOAT | no | m | source `cruise.height` | Nominal cruise altitude |
| cruise_speed_kt | FLOAT | no | kt (TAS) | **derived** | True airspeed of `cruise_mach` at `cruise_altitude_m` in the ISA standard atmosphere (`openap.aero.mach2tas`) |
| openap_supported | BOOLEAN | yes | | | True only when OpenAP has a model for exactly this aircraft |
| openap_coverage | VARCHAR(50) | no | | | `openap_model`, `related_passenger_variant_only`, `no_openap_model` |
| openap_related_code | VARCHAR(8) | no | | curated | OpenAP model with the same ICAO designator, for reference only. **Never substituted** |
| field_provenance | TEXT (JSON) | no | | generated | Per-field provenance (see above) |
| notes | TEXT | no | | | Coverage gaps and caveats |
| source_id | INTEGER FK | yes | | | → `data_source.source_id` |
| created_at / updated_at | DATETIME | yes | UTC | | As for `airport` |

**Weight plausibility checks** (warnings only, never rejections): OEW ≤ MTOW,
MLW ≤ MTOW, OEW ≤ MLW, MZFW ≤ MLW, OEW ≤ MZFW, max payload ≤ MTOW. Equal
values are accepted because definitions differ between sources.

Fields kept only in `data/processed/aircraft/aircraft_types.csv`: `vmo_kt`
(kt), `mmo` (Mach), `ceiling_m` (m), `openap_nominal_cruise_range_km` (km;
nominal only, **not** a payload-independent range), `engine_options` (JSON).
