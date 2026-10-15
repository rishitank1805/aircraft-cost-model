# Data dictionary

SQLite database: `database/aircraft_costs.db`. The schema is managed by
Alembic; the current revision is `0003_touchdown_fuel_boundaries`. All
timestamps are stored in UTC as timezone-naive `DATETIME`, because SQLite has
no timezone type. "Required" means `NOT NULL`.

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
| source_id | INTEGER FK | yes | | | → `data_source.source_id` of the snapshot that supplied the row's *current values*. Changes only when airport data changes |
| last_seen_source_id | INTEGER FK | no | | | → latest snapshot that still contained this airport. Rows missing from newer snapshots keep an older value and are **not deleted** (added in 0002, back-filled from `source_id`) |
| last_seen_at | DATETIME | no | UTC | | Retrieval time of `last_seen_source_id` |
| created_at | DATETIME | yes | UTC | | First insert |
| updated_at | DATETIME | yes | UTC | | Last real data change. Re-loads and new snapshots with identical data do not touch it, and neither does last-seen tracking |

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
| fuel_capacity_kg | FLOAT | no | kg | **derived** | `fuel_capacity_l × fuel_capacity_density_kg_per_l`. A model input, not a manufacturer-certified value. > 0 when present |
| fuel_capacity_density_kg_per_l | FLOAT | no | kg/L | assumption | Density used to derive `fuel_capacity_kg` (0.8025, from OpenAP `mass.py`). Added in 0002 and back-filled only where the Part 1 provenance label records 0.8025. Part 2 calculations use `fuel_capacity_l` with their own recorded density |
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

## `route` (Part 2)

Stable airport-pair reference data. Unique on `(origin_airport_id, destination_airport_id)`.

| Column | Type | Required | Unit | Description |
|---|---|---|---|---|
| route_id | INTEGER PK | yes | | Surrogate key |
| origin_airport_id | INTEGER FK | yes | | → `airport.airport_id` (indexed) |
| destination_airport_id | INTEGER FK | yes | | → `airport.airport_id` (indexed) |
| great_circle_distance_km | FLOAT | yes | km | Haversine distance between airport coordinates |
| great_circle_distance_nm | FLOAT | yes | NM | `km / 1.852` |
| distance_method | VARCHAR(200) | yes | | e.g. `haversine, spherical Earth, R = 6371.0088 km (IUGG mean radius)` |
| created_at / updated_at | DATETIME | yes | UTC | `updated_at` changes if airport coordinates change upstream |

## `flight_estimate` (Part 2)

One modelled flight. These are **estimates, not dispatch plans**. Only
feasible estimates are stored. Indexes: `aircraft_type_id`, `route_id`,
`(origin_airport_id, destination_airport_id)`, `input_hash`.

| Column | Type | Required | Unit | Description |
|---|---|---|---|---|
| flight_estimate_id | INTEGER PK | yes | | Surrogate key |
| aircraft_type_id | INTEGER FK | yes | | → `aircraft_type` |
| origin_airport_id, destination_airport_id | INTEGER FK | yes | | → `airport` |
| route_id | INTEGER FK | yes | | → `route` |
| payload_kg | FLOAT | yes | kg | User input, ≥ 0 |
| great_circle_distance_nm | FLOAT | yes | NM | Copy at calculation time |
| estimated_route_distance_nm | FLOAT | yes | NM | Distance flown in the model |
| route_distance_method | VARCHAR(50) | yes | | `great_circle`, `great_circle_x_factor`, `user_supplied` |
| route_factor | FLOAT | no | ratio | NULL for a user-supplied distance |
| cruise_altitude_ft | FLOAT | yes | ft | Altitude actually used (may be below the requested altitude on short routes) |
| taxi_out_min, taxi_in_min | FLOAT | yes | min | User input or default (see flight_assumptions.md) |
| airborne_time_min | FLOAT | yes | min | Lift-off → touchdown |
| trip_time_min | FLOAT | yes | min | v2: brake release → touchdown (v1: → end of landing roll) |
| landing_roll_time_min | FLOAT | no | min | Touchdown → rest (NULL for v1 rows) |
| block_time_min | FLOAT | yes | min | v2: taxi-out + trip + landing roll + taxi-in |
| zero_fuel_weight_kg | FLOAT | yes | kg | OEW + payload |
| ramp_weight_kg, takeoff_weight_kg, landing_weight_kg | FLOAT | yes | kg | Ramp; brake release; v2 touchdown (v1: end of landing roll). See flight_performance.md §5–6 |
| trip_fuel_kg | FLOAT | yes | kg | v2: brake release → touchdown, equal to `takeoff_weight_kg − landing_weight_kg` (v1: → end of landing roll) |
| landing_roll_fuel_kg | FLOAT | no | kg | Touchdown → rest, ground idle (NULL for v1 rows) |
| taxi_out_fuel_kg, taxi_in_fuel_kg, taxi_fuel_kg | FLOAT | yes | kg | Ground idle fuel |
| block_fuel_kg | FLOAT | yes | kg | taxi-out + trip + landing roll + taxi-in (same total in v1 and v2) |
| reserve_fuel_kg | FLOAT | yes | kg | User-supplied contingency + alternate + final reserve |
| planned_fuel_load_kg | FLOAT | yes | kg | Fuel at ramp |
| fuel_per_nm_kg | FLOAT | yes | kg/NM | trip fuel / estimated route distance |
| fuel_per_block_hour_kg | FLOAT | yes | kg/h | block fuel / block hours |
| fuel_density_kg_per_l | FLOAT | yes | kg/L | Density used for the capacity check |
| time_step_s | FLOAT | yes | s | Maximum integration step |
| planning_iterations | INTEGER | yes | | Iterations to converge |
| model_name, model_version | VARCHAR | yes | | e.g. `aircraft_cost_model 0.2.0; openap 2.6.2` |
| performance_model_code | VARCHAR(8) | yes | | Exact OpenAP model used (no synonyms) |
| engine_model | VARCHAR(100) | no | | OpenAP default engine |
| calculation_status | VARCHAR(50) | yes | | `calculated` or `calculated_limits_unverified` |
| limit_checks | TEXT (JSON) | yes | | Every check: name, status (`passed`/`failed`/`not_performed`), value, limit, unit, note |
| warnings | TEXT (JSON) | no | | Warnings shown to the user |
| input_hash | VARCHAR(64) | yes | | SHA-256 of the normalized inputs and model versions (identical inputs give the same hash) |
| fuel_accounting_basis | VARCHAR(10) | yes | | `v2` = take-off mass at brake release, landing mass at touchdown, trip fuel between them, landing roll separate. `v1` = rows saved before migration 0003 (trip fuel and landing mass to end of landing roll; values kept unchanged) |
| trajectory_file | VARCHAR(500) | no | | CSV of per-step states (`time_s`, `phase`, `mode`, `altitude_ft`, `true_airspeed_kt`, `vertical_speed_fpm`, `ground_speed_kt`, `distance_nm`, `aircraft_mass_kg`) |
| created_at | DATETIME | yes | UTC | |

## `flight_phase` (Part 2)

Eight rows per v2 estimate, in this sequence: `taxi_out`, `takeoff`, `climb`,
`cruise`, `descent`, `approach`, `landing_roll`, `taxi_in`. (v1 rows have
seven, with the landing roll inside `approach_landing`.) Unique on
`(flight_estimate_id, sequence_number)`. Rows are deleted with their estimate
(`ON DELETE CASCADE`).

| Column | Type | Required | Unit | Description |
|---|---|---|---|---|
| flight_phase_id | INTEGER PK | yes | | |
| flight_estimate_id | INTEGER FK | yes | | → `flight_estimate` (indexed) |
| phase_name | VARCHAR(30) | yes | | See sequence above |
| sequence_number | INTEGER | yes | | 1–8 (1–7 for v1) |
| start_time_s | FLOAT | yes | s | Relative to off-block |
| duration_s | FLOAT | yes | s | ≥ 0; phase durations sum to block time |
| distance_nm | FLOAT | no | NM | NULL for taxi (taxi distance not modelled); airborne phases sum to route distance |
| start_altitude_ft, end_altitude_ft | FLOAT | yes | ft | Pressure altitude (ISA) |
| start_mass_kg, end_mass_kg | FLOAT | yes | kg | Continuous across phases |
| fuel_burn_kg | FLOAT | yes | kg | Phases sum to block fuel |
| fuel_flow_method | VARCHAR(200) | yes | | e.g. `OpenAP FuelFlow.enroute (clean-configuration drag polar)` |

## `flight_assumption` (Part 2)

Unique on `(flight_estimate_id, assumption_name)`. Cascades with its estimate.

| Column | Type | Required | Description |
|---|---|---|---|
| assumption_id | INTEGER PK | yes | |
| flight_estimate_id | INTEGER FK | yes | → `flight_estimate` (indexed) |
| assumption_name | VARCHAR(100) | yes | e.g. `taxi_out_min`, `fuel_density_kg_per_l`, `wind` |
| assumption_value | TEXT | yes | Value as text |
| assumption_unit | VARCHAR(30) | no | Unit, if any |
| source_type | VARCHAR(30) | yes | `user_input`, `project_default`, `openap_model`, `database`, `physical_constant`, `modelling_assumption` |
| source_reference | TEXT | no | Where the value comes from |
| notes | TEXT | no | Caveats |
