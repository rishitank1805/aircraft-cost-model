# Data dictionary

SQLite database: `database/aircraft_costs.db`. The schema is managed by
Alembic; the current revision is `0008_aircraft_specifications`. All
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

## Part 3 tables

Money, prices and rates use **`DecimalText`**: the exact decimal string
stored as VARCHAR(64) and read back as `Decimal`. Floats are rejected. SQL
comparisons on these columns are textual, so don't sort or filter them by
value in SQL.

### `fuel_price`

Unique on `(series_identifier, observation_period, observation_date)`; index
on `(series_identifier, observation_date)`.

| Column | Type | Required | Description |
|---|---|---|---|
| fuel_price_id | INTEGER PK | yes | |
| source_id | INTEGER FK | yes | → `data_source` (snapshot that supplied the current value) |
| series_identifier | VARCHAR(64) | yes | e.g. `EER_EPJK_PF4_RGC_DPG` |
| market_location | VARCHAR(100) | yes | `U.S. Gulf Coast, FOB` |
| product | VARCHAR(100) | yes | `Kerosene-type jet fuel` |
| observation_date | DATE | yes | Trading day the price refers to |
| observation_period | VARCHAR(20) | yes | `daily` = single trading-day assessment (not an average) |
| price | DecimalText | yes | > 0 |
| currency | VARCHAR(3) | yes | ISO 4217 (`USD`) |
| price_unit | VARCHAR(30) | yes | `USD/USgal` |
| retrieved_at | DATETIME | yes | UTC download time (separate from observation date) |
| created_at / updated_at | DATETIME | yes | `updated_at` changes only if the value changes |

### `exchange_rate`

Unique on `(base_currency, quote_currency, observation_date)`.

| Column | Type | Required | Description |
|---|---|---|---|
| exchange_rate_id | INTEGER PK | yes | |
| source_id | INTEGER FK | yes | → `data_source` |
| observation_date | DATE | yes | ECB publication date (TARGET business days) |
| base_currency | VARCHAR(3) | yes | `EUR` |
| quote_currency | VARCHAR(3) | yes | e.g. `USD` |
| rate | DecimalText | yes | units of quote currency per 1 base currency (USD per EUR) |
| series_key | VARCHAR(64) | yes | e.g. `EXR.D.USD.EUR.SP00.A` |
| retrieved_at | DATETIME | yes | UTC |
| created_at / updated_at | DATETIME | yes | |

### `navigation_rate`

Unique on `(charging_zone, valid_from)`. Superseded versions are kept. Holds
en-route and terminal rates (`charge_type`). Values come from git-ignored
local transcriptions.

| Column | Type | Required | Description |
|---|---|---|---|
| navigation_rate_id | INTEGER PK | yes | |
| source_id | INTEGER FK | yes | → `data_source` (reviewed CSV version) |
| charging_zone | VARCHAR(40) | yes | Project zone code (e.g. `GERMANY`), indexed |
| charging_zone_name | VARCHAR(100) | yes | Name as printed in the circular |
| valid_from / valid_to | DATE | yes / no | Validity interval (inclusive) |
| unit_rate | DecimalText | yes | Global unit rate t_i (national + administrative), EUR |
| national_unit_rate | DecimalText | no | National unit rate |
| currency | VARCHAR(3) | yes | `EUR` (CoA Art. 7) |
| source_reference | TEXT | yes | Document, section, URL, extraction method |
| verification_status | VARCHAR(40) | yes | `verified_against_source` or `pending_review` (pending rows are never priced) |
| charge_type | VARCHAR(20) | yes | `en_route` (default) or `terminal` (added in 0005) |
| service_unit_formula | VARCHAR(40) | yes | `sqrt_mtow_over_50` (en-route) or `mtow_over_50_pow_0_7` (terminal) |
| charged_movement | VARCHAR(20) | no | Terminal: `departure` or `arrival`, the movement the zone charges |

### `navigation_zone_aerodrome` (0005)

Unique on `(charging_zone, aerodrome_icao, valid_from)`; index on `aerodrome_icao`.

| Column | Type | Required | Description |
|---|---|---|---|
| navigation_zone_aerodrome_id | INTEGER PK | yes | |
| source_id | INTEGER FK | yes | → `data_source` |
| charging_zone | VARCHAR(40) | yes | Terminal charging zone, e.g. `FRANCE_TCZ1` |
| aerodrome_icao | VARCHAR(4) | yes | Aerodrome in the zone |
| valid_from / valid_to | DATE | yes / no | Membership validity |

### `airport_tariff`

Unique on `(airport_id, tariff_type, valid_from)`. Superseded versions are kept.

| Column | Type | Required | Description |
|---|---|---|---|
| airport_tariff_id | INTEGER PK | yes | |
| airport_id | INTEGER FK | yes | → `airport` (indexed) |
| source_id | INTEGER FK | yes | → `data_source` (transcription file version) |
| tariff_type | VARCHAR(40) | yes | `landing_takeoff` or `ground_handling` |
| valid_from / valid_to | DATE | yes / no | Validity interval |
| currency | VARCHAR(3) | yes | Tariff currency |
| calculation_method | VARCHAR(80) | yes | Rule implementation, e.g. `fra_movement_charges_2026`, `per_unit_handling` |
| parameters_json | TEXT | yes | Reviewed rates and bands (decimals as strings) |
| source_reference | TEXT | yes | Document title, URL, sections, pages |
| verification_status | VARCHAR(40) | yes | e.g. `transcribed_reviewed_local` |

### `variable_cost_estimate`

| Column | Type | Required | Description |
|---|---|---|---|
| variable_cost_estimate_id | INTEGER PK | yes | |
| flight_estimate_id | INTEGER FK | yes | → `flight_estimate` (v2 only), indexed |
| pricing_date | DATE | yes | Date used to select prices, rates and tariffs |
| reporting_currency | VARCHAR(3) | yes | ISO 4217 |
| calculated_subtotal | DecimalText | no | Sum of calculated components only; NULL if none was calculated. **Not a total** |
| complete_variable_cost | DecimalText | no | Set **only** when every applicable component is calculated with full scope; otherwise NULL |
| coverage_status | VARCHAR(30) | yes | `complete`, `partial` or `none` |
| components_calculated / components_applicable | INTEGER | yes | Component counts (not a share of cost) |
| calculation_version | VARCHAR(100) | yes | e.g. `variable_costs v1 (aircraft_cost_model 0.2.0)` |
| input_hash | VARCHAR(64) | yes | SHA-256 of the request and every selected observation, rate and amount (indexed) |
| created_at | DATETIME | yes | UTC |

### `cost_component`

Unique on `(variable_cost_estimate_id, component_name)`; cascades with its estimate.

| Column | Type | Required | Description |
|---|---|---|---|
| cost_component_id | INTEGER PK | yes | |
| variable_cost_estimate_id | INTEGER FK | yes | → `variable_cost_estimate` |
| component_name | VARCHAR(30) | yes | `fuel`, `navigation` (en-route), `terminal_navigation`, `landing`, `ground_handling`. Estimates saved before 0005 have four components, and their `navigation` is `partial_scope` |
| amount | DecimalText | no | NULL whenever not calculated (never 0 for missing) |
| currency | VARCHAR(3) | yes | Reporting currency |
| status | VARCHAR(40) | yes | See variable_cost_model.md §7 |
| source_type | VARCHAR(40) | yes | `public_tariff`, `public_market_benchmark`, `user_assumption`, `none` |
| partial_scope | BOOLEAN | yes | True if the component deliberately excludes part of the cost (e.g. terminal navigation charges) |
| source_id | INTEGER FK | no | → `data_source` of the price or tariff used |
| source_reference | TEXT | no | Human-readable source |
| pricing_observation_date | DATE | no | Observation date (fuel) or tariff/rate effective date |
| calculation_method | TEXT | no | Method description |
| breakdown_json | TEXT | yes | Every step and conversion, with values |
| assumptions_json | TEXT | yes | Labelled assumptions |
| warnings_json | TEXT | yes | Warnings, including missing inputs |

## Part 4 tables (migration 0006)

Money and scenario values use `DecimalText` (exact decimal strings). Every
`amount`/subtotal column is NULL when not calculated, never 0 for missing.

### `cost_scenario`

Unique on `content_hash`; one row per distinct scenario content.

| Column | Type | Required | Description |
|---|---|---|---|
| scenario_id | INTEGER PK | yes | |
| name, description | VARCHAR(200), TEXT | name yes | From the scenario file |
| scenario_version | VARCHAR(40) | yes | Author's version label |
| ownership_mode | VARCHAR(30) | yes | `owned`, `operating_lease`, `custom` |
| flight_type | VARCHAR(20) | yes | `passenger`, `cargo` |
| reporting_currency | VARCHAR(3) | yes | ISO 4217 |
| pricing_date | DATE | no | Scenario pricing date, if given |
| source_quality_summary | VARCHAR(200) | yes | Dimension C at first use |
| source_path | VARCHAR(500) | no | File the scenario was loaded from |
| content_hash | VARCHAR(64) | yes | SHA-256 of the canonical JSON |
| content_json | TEXT | yes | Canonical JSON (exact reproduction) |
| created_at | DATETIME | yes | UTC |

### `cost_assumption`

Unique on `(scenario_id, parameter_name)`; cascades with its scenario.

| Column | Type | Required | Description |
|---|---|---|---|
| assumption_id | INTEGER PK | yes | |
| scenario_id | INTEGER FK | yes | → `cost_scenario` |
| component | VARCHAR(60) | yes | Top-level section, e.g. `maintenance` |
| parameter_name | VARCHAR(200) | yes | Value path, e.g. `crew.salaries.roles[0].annual_compensation` |
| value_decimal | DecimalText | yes | Exact value |
| unit | VARCHAR(40) | yes | e.g. `EUR/block_hour`, `ratio` |
| currency | VARCHAR(3) | no | For money units |
| effective_from / effective_to | DATE | no | Period the value is asserted to apply |
| reference_period | VARCHAR(100) | no | Period the source data describes |
| source_type | VARCHAR(40) | yes | `illustrative_assumption`, `user_assumption`, `public_financial_benchmark`, `observed_public_data` |
| source_reference, notes | TEXT | no | Citation and notes |

### `full_cost_estimate`

| Column | Type | Required | Description |
|---|---|---|---|
| full_cost_estimate_id | INTEGER PK | yes | |
| flight_estimate_id | INTEGER FK | yes | → `flight_estimate` |
| variable_cost_estimate_id | INTEGER FK | yes | → the exact Part 3 `variable_cost_estimate` used (same flight) |
| scenario_id | INTEGER FK | yes | → `cost_scenario` |
| pricing_date, reporting_currency | DATE, VARCHAR(3) | yes | From the Part 3 estimate |
| ownership_mode | VARCHAR(30) | yes | |
| direct_variable_subtotal, direct_fixed_subtotal, indirect_subtotal, noncash_subtotal, financing_subtotal | DecimalText | no | **Calculated subtotals** (calculated components only) |
| cash_operating_subtotal, total_operating_subtotal, total_cost_subtotal | DecimalText | no | Calculated COC / TOC / total subtotals |
| complete_coc, complete_toc, complete_total_costs | DecimalText | no | Set only when every applicable component below is calculated with full scope |
| cost_coverage_status | VARCHAR(30) | yes | Dimension A: `complete`, `incomplete`, `failed_validation` |
| operational_validity_status | VARCHAR(50) | yes | Dimension B: the Part 2 flight estimate's status, unchanged |
| source_quality_summary | VARCHAR(200) | yes | Dimension C |
| calculation_version | VARCHAR(100) | yes | e.g. `full_costs v1 (aircraft_cost_model …)` |
| input_hash | VARCHAR(64) | yes | SHA-256 of IDs, Part 3 input hash, scenario hash and all components (indexed) |
| created_at | DATETIME | yes | UTC |

### `full_cost_component`

Unique on `(full_cost_estimate_id, component_name)`; cascades with its estimate.

| Column | Type | Required | Description |
|---|---|---|---|
| full_cost_component_id | INTEGER PK | yes | |
| full_cost_estimate_id | INTEGER FK | yes | → `full_cost_estimate` |
| component_name | VARCHAR(40) | yes | One of the 17 taxonomy components (full_cost_model.md §3) |
| category | VARCHAR(30) | yes | `direct_variable`, `direct_fixed`, `indirect`, `noncash`, `financing` |
| amount | DecimalText | no | NULL whenever not calculated |
| currency | VARCHAR(3) | yes | Reporting currency |
| status | VARCHAR(40) | yes | Component status, incl. `not_applicable` and `failed_validation` |
| source_type | VARCHAR(40) | yes | Component source type |
| source_quality | VARCHAR(40) | yes | Dimension C for the component |
| origin | VARCHAR(40) | yes | `part3_variable_cost_estimate` or `part4_scenario` |
| part3_cost_component_id | INTEGER FK | no | → the original Part 3 `cost_component` (Part 3 components only) |
| source_reference, calculation_method | TEXT | no | |
| breakdown_json, assumptions_json, warnings_json | TEXT | yes | Steps, inputs used, warnings and missing inputs |

## Part 5 tables (migration 0007)

Decimal values use `DecimalText` (exact decimal strings). NULL means
unavailable or undefined, never zero. Analytics runs are immutable; benchmark
and index observations are kept per source snapshot.

### `analytics_run`

Unique on `input_hash`. Saving the same request again returns the existing run.

| Column | Type | Required | Description |
|---|---|---|---|
| analytics_run_id | INTEGER PK | yes | |
| analysis_type | VARCHAR(40) | yes | `unit_metrics`, `sensitivity_1d`, `sensitivity_2d`, `comparison`, `ownership_comparison`, `validation` |
| status | VARCHAR(30) | yes | `calculated`, or the validation status `pass` / `warn` / `fail` |
| flight_estimate_id, variable_cost_estimate_id, full_cost_estimate_id | INTEGER FK | no | Source estimates |
| base_scenario_id | INTEGER FK | no | → `cost_scenario` (never modified) |
| pricing_date, reporting_currency | DATE, VARCHAR(3) | no | |
| distance_basis, payload_basis | VARCHAR(30), TEXT | no | e.g. `modelled_route`; "revenue cargo payload not provided" |
| coverage_status | VARCHAR(30) | yes | complete / partial / missing_required_input / unsupported / calculation_error |
| operational_validity | VARCHAR(50) | no | Part 2 status, unchanged |
| source_quality_summary | VARCHAR(200) | yes | |
| parameters_json | TEXT | yes | Canonical request (incl. the input hashes of the source estimates) |
| result_json | TEXT | yes | Canonical result (timestamps excluded); used for the reproducibility check |
| warnings_json | TEXT | yes | |
| calculation_version | VARCHAR(100) | yes | e.g. `analytics v1` |
| input_hash | VARCHAR(64) | yes | SHA-256 of type + parameters + version |
| created_at | DATETIME | yes | UTC |

### `unit_cost_metric`

| Column | Type | Required | Description |
|---|---|---|---|
| metric_id | INTEGER PK | yes | |
| analytics_run_id | INTEGER FK | yes | → `analytics_run` (cascade) |
| case_label, flight_estimate_id | VARCHAR(200), INTEGER FK | label yes | |
| metric_name, label | VARCHAR(60), VARCHAR(120) | yes | e.g. `coc_per_block_hour`, "Partial COC per block hour" |
| cost_basis, cost_measure | VARCHAR(30) | yes | basis (`direct_variable` … `total_costs`); `calculated_subtotal` or `complete_total` |
| numerator_amount, denominator_value, metric_value | DecimalText | no | Exact; NULL when unavailable or undefined |
| currency, denominator_unit, metric_unit | VARCHAR | yes | e.g. EUR, `block_hour`, `EUR/block_hour` |
| denominator_basis | TEXT | yes | e.g. distance basis and source |
| metric_status | VARCHAR(20) | yes | `calculated`, `unavailable`, `undefined` |
| coverage_status, operational_validity, source_quality | VARCHAR | yes | The three dimensions |
| pricing_date | DATE | yes | |
| fx_basis, payload_basis, calculation_method | TEXT | fx/method yes | |
| components_json, warnings_json | TEXT | yes | Included and missing components; warnings |

### `scenario_result`

| Column | Type | Required | Description |
|---|---|---|---|
| scenario_result_id | INTEGER PK | yes | |
| analytics_run_id | INTEGER FK | yes | → `analytics_run` (cascade) |
| label | VARCHAR(300) | yes | e.g. `fuel_price +10%` |
| variations_json, modified_values_json | TEXT | yes | Parameter, change type and value; for each modified input: path, original and new value, unit, original and new source type |
| variant_scenario_id | INTEGER FK | no | → `cost_scenario` row of the variant (new content hash; NULL when the base is reproduced) |
| status | VARCHAR(30) | yes | `calculated` / `calculation_error` |
| fuel_cost, direct_variable_subtotal, cash_operating_subtotal, total_operating_subtotal, total_cost_subtotal | DecimalText | no | Calculated subtotals |
| complete_coc, complete_toc, complete_total_costs | DecimalText | no | Only when complete |
| components_json, deltas_json | TEXT | yes | Component amounts and statuses; absolute and percent deltas versus the base (NULL when withheld) |
| coverage_status, operational_validity, source_quality | VARCHAR | coverage yes | |
| calculated_at | VARCHAR(40) | yes | UTC timestamp of the recalculation |
| input_hash, warnings_json | VARCHAR(64), TEXT | yes | |

### `benchmark_observation`

Unique on (source_id, benchmark_source, carrier_code, aircraft_type_code,
aircraft_config, region, period_label, cost_category).

| Column | Type | Required | Description |
|---|---|---|---|
| benchmark_id | INTEGER PK | yes | |
| source_id | INTEGER FK | yes | → `data_source` (P-5.2 snapshot, or the FAA reference CSV) |
| traffic_source_id | INTEGER FK | no | → `data_source` (T2 snapshot) |
| benchmark_source, source_table | VARCHAR | yes | `bts_form41_p52_t2` or `faa_econ_values_s4_t4_7` |
| carrier_code, carrier_name, carrier_group | VARCHAR | code yes | BTS unique carrier; FAA: `US_P121_PAX` |
| operation_scope | VARCHAR(40) | yes | `passenger_configuration`, `freight_configuration_all_cargo_carrier`, `freight_configuration_mixed_carrier`, `combi_configuration` |
| aircraft_type_code, aircraft_type_description, aircraft_config | VARCHAR | code/config yes | BTS codes (e.g. 694, config 1); FAA class `NB165K` |
| region | VARCHAR(5) | yes | BTS reporting region (D, A, L, P, I, S); FAA `US` |
| period_label, period_start, period_end | VARCHAR, DATE | yes | e.g. `2025Q1`; FAA `YE2023Q2` |
| cost_category | VARCHAR(40) | yes | See bts_form41_methodology.md §3 |
| amount | DecimalText | no | Source currency (USD); NULL when a required account is blank |
| currency | VARCHAR(3) | yes | |
| block_hours, airborne_hours, departures, revenue_tonne_nm, available_tonne_nm, aircraft_miles_nm | DecimalText | no | Converted denominators (FAA: block_hours = 1) |
| source_fields, methodology | TEXT | yes | Accounts summed; derivation |
| quality_status, quality_notes | VARCHAR, TEXT | status yes | `ok`, `low_hours`, `no_traffic_match`, `missing_fields`, `negative_amount`, `hours_mismatch`, `region_mismatch`, `partial_quarter` |
| created_at | DATETIME | yes | |

### `price_index_observation`

Unique on (source_id, series_id, period).

| Column | Type | Required | Description |
|---|---|---|---|
| index_observation_id | INTEGER PK | yes | |
| source_id | INTEGER FK | yes | → `data_source` (BLS API snapshot) |
| series_id, series_title | VARCHAR | id yes | e.g. `CIU2014300000000I` |
| period, period_start, period_end | VARCHAR(10), DATE | yes | e.g. `2024-Q03`, `2024-M11` |
| value | DecimalText | yes | As published |
| preliminary | BOOLEAN | yes | BLS footnote `P` |
| footnotes | TEXT | no | |

### `benchmark_adjustment`

| Column | Type | Required | Description |
|---|---|---|---|
| adjustment_id | INTEGER PK | yes | |
| benchmark_id | INTEGER FK | yes | → `benchmark_observation` (never modified) |
| status | VARCHAR(20) | yes | `adjusted` / `unavailable` |
| original_amount, original_currency, original_period | | currency/period yes | |
| index_series_id, index_source_id | VARCHAR, INTEGER FK | series yes | Empty series and NULL source when no verified index exists |
| base_period, base_index, target_period, target_index, factor, adjusted_amount | VARCHAR / DecimalText | no | adjusted = original × factor; factor = target / base |
| target_date | DATE | yes | |
| methodology, reason | TEXT | methodology yes | Windows, publication-lag rule, suitability label, reason when unavailable |
| created_at | DATETIME | yes | |

### `benchmark_comparison`

| Column | Type | Required | Description |
|---|---|---|---|
| comparison_id | INTEGER PK | yes | |
| analytics_run_id | INTEGER FK | yes | → `analytics_run` (cascade) |
| model_metric, model_value, model_unit | | metric/unit yes | e.g. `fuel_per_block_hour`, EUR/block_hour |
| benchmark_metric, benchmark_value, benchmark_value_converted, benchmark_unit | | metric/unit yes | Original currency value and converted value |
| benchmark_selection_json | TEXT | yes | Selection, rows used and excluded, carriers, periods, stage length, adjustment |
| comparability | VARCHAR(30) | yes | `comparable`, `comparable_with_caveats`, `not_comparable` |
| checks_json, reasons_json | TEXT | yes | Every check with its result; failure reasons |
| absolute_difference, percentage_difference | DecimalText | no | NULL when not comparable (percent also NULL when the benchmark is 0) |
| fx_basis | TEXT | no | |

## Part 6 table (migration 0008)

### `aircraft_specification`

One value of one specification for one aircraft type from one source. Unique on
(aircraft_type_id, spec_key, source_id). Insert-only: a new source version adds rows.

| Column | Type | Required | Description |
|---|---|---|---|
| specification_id | INTEGER PK | yes | |
| aircraft_type_id | INTEGER FK | yes | → `aircraft_type` |
| spec_key | VARCHAR(60) | yes | e.g. `length_m`, `mtow_kg`, `rated_thrust_kn`, `body_class`, `main_deck_cargo_door` |
| section | VARCHAR(30) | yes | dimensions, weights, engines, performance, capacity, classification, cargo |
| value_decimal | DecimalText | no | Value in SI units (exact; e.g. lb × 0.45359237) |
| value_text | TEXT | no | Text values (classifications, cargo descriptions) |
| unit | VARCHAR(30) | no | m, m2, m3, kg, L, kN, kt, km, NM, Mach, deg, ratio, count, seats |
| original_value, original_unit | VARCHAR | no | As published (e.g. `171961` `lb`) |
| source_id | INTEGER FK | yes | → `data_source` |
| source_type | VARCHAR(40) | yes | `published_specification`, `open_model_data`, `engine_databank`, `documented_classification` |
| source_reference | TEXT | no | Row / table / URL and retrieval date |
| verification_status | VARCHAR(40) | yes | `as_published`, `shared_designator_row`, `source_inconsistent`, `unverified_model_value` |
| variant | VARCHAR(200) | no | Model / weight variant / engine the value applies to |
| condition | TEXT | no | e.g. "with a 107-tonne payload", "payload condition not stated" |
| notes | TEXT | no | Definitions and caveats (e.g. fuselage height is not overall height) |
| created_at | DATETIME | yes | |
