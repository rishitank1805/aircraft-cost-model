# Data sources

Licences were checked on 2026-10-15. Re-check them before redistributing any
data or derived database. Actual retrieval timestamps and checksums for each
load are recorded in the `data_source` table and in raw snapshot sidecar files.

## 1. OurAirports: airports

| Item | Detail |
|---|---|
| Official URL | https://ourairports.com/data/ (dataset: https://ourairports.com/data/airports.csv) |
| Actual download location | The URL redirects (HTTP 301) to `https://davidmegginson.github.io/ourairports-data/airports.csv`. The final URL is recorded on each download |
| Dataset | `airports.csv` (19 columns, verified against the live header: id, ident, type, name, latitude_deg, longitude_deg, elevation_ft, continent, iso_country, iso_region, municipality, scheduled_service, icao_code, iata_code, gps_code, local_code, home_link, wikipedia_link, keywords) |
| Access method | HTTPS GET with `requests` (connect 10 s / read 120 s timeouts, configurable) |
| Licence | **Public Domain.** "All data is released to the Public Domain, and comes with no guarantee of accuracy or fitness for use." (ourairports.com/data) |
| Update frequency | "The data is updated every night" (ourairports.com/data) |
| Data dictionary | https://ourairports.com/help/data-dictionary.html |
| Verified retrieval | 2026-10-15T13:40:05Z, 12,747,586 bytes, SHA-256 `536d6de0dfeed92d4bbe8fd7411ba6bc14c43251c2161f34b9fbfd50ee3f4113`, `Last-Modified: Thu, 15 Oct 2026 01:54:00 GMT`, 86,251 records |

**Limitations**

- The data is community-maintained and has no accuracy guarantee.
- `ident` is an OurAirports identifier. It is often, but not always, an ICAO
  code. Use the dedicated `icao_code` column, which was populated for 10,554 of
  86,251 airports in the verified snapshot.
- IATA codes are present for 9,054 airports and were unique in this snapshot.
  The schema does not enforce uniqueness.
- `scheduled_service` says nothing about cargo capability, runway length or
  operating hours.
- Elevation is missing for 14,968 airports and municipality for 4,770.
- The file changes nightly, so each load is tied to a checksum.

## 2. OpenAP: aircraft properties

| Item | Detail |
|---|---|
| Official URL | https://github.com/TUDelft-CNS-ATM/openap, documentation https://openap.dev/ |
| Dataset | `openap/data/aircraft/*.yml` inside the installed package, read via `openap.prop.available_aircraft()` / `openap.prop.aircraft()` |
| Access method | `pip install openap` (verified version **2.6.2**). There is no separate download endpoint |
| Licence | Package metadata: **GNU LGPL v3**. The bundled `openap/data/` directory contains a **GNU GPL v3** LICENSE file. Treat the aircraft data as GPL-3.0 when redistributing the database or derived files |
| Citation requested | Sun, J., Hoekstra, J.M., Ellerbroek, J. (2020). *OpenAP: An open-source aircraft performance model for air transportation studies and simulations.* Aerospace 7(8), 104 |
| Update frequency | Not documented. Changes come with package releases. Each load records the package version and a SHA-256 over all aircraft YAML files |
| Verified retrieval | 2026-10-15T13:40:02Z, 37 aircraft types, data SHA-256 `79a1353b91f9d6895273646e63757b065fafa4c41d3400423ad6331f1bfb3a8c` |

**Attributes actually available** (all 37 files): `mtow`, `mlw`, `oew` (kg);
`mfc` (maximum fuel capacity in **litres**: undocumented, but OpenAP's own
`mass.py` converts it with `mfc * 0.8025  # L->kg`, and values match published
litre capacities); `vmo` (kt); `mmo`; `ceiling` (m); `cruise.height` (m),
`cruise.mach`, `cruise.range` (km, nominal); `engine.type/number/default/options`;
plus geometry (wing, fuselage), drag polar and passenger counts, which are not
used.

**Not available:** MZFW, maximum payload, freighter variants, variant or
certification-specific weights.

**Limitations**

- Weights are generic, type-level values, not specific to an operator or a
  certification variant.
- `engine.default` is one of several engine options.
- Cruise range is a single nominal figure. It does not account for payload and
  fuel trade-offs.
- `openap/data/aircraft/_synonym.csv` maps unsupported types to *different*
  aircraft (e.g. `b77l → b77w`, i.e. 777-200LR/777F → 777-300ER;
  `md11 → b773`; `a306 → a332`). **This project does not use synonyms.**

### Cargo aircraft coverage (OpenAP 2.6.2)

| Target | ICAO designator | OpenAP model with that designator | Coverage |
|---|---|---|---|
| Airbus A330-200F | A332 | A332 = A330-200 passenger | related passenger variant only |
| Boeing 777F | B77L | none (synonym → B77W ignored) | no OpenAP model |
| Boeing 767-300F | B763 | B763 = 767-300 passenger | related passenger variant only |
| Boeing 747-400F | B744 | B744 = 747-400 passenger | related passenger variant only |
| Airbus A321P2F | A321 | A321 = A321 passenger | related passenger variant only |

No freighter values are copied from passenger models. Freighter weights and
performance need a documented public source or an explicitly labelled proxy
decision. That decision belongs to Part 2 and requires approval.

### OpenAP model data used by Part 2

| File / API | Content | Used for |
|---|---|---|
| `openap/data/wrap/*.txt` via `WRAP(code, use_synonym=False)` | WRAP kinematic parameters (Sun et al.), 17 types | Climb, cruise, descent and approach speeds and rates (default values) |
| `openap/data/dragpolar/*.yml` | Drag polars, 26 types | `FuelFlow.enroute` thrust |
| `openap/data/fuel/fuel_models.csv` | Fuel-flow coefficients: 14 type-specific + default | Fuel flow vs thrust |
| `openap/data/engine/engines.csv` | ICAO Aircraft Engine Emissions Databank values (max thrust, LTO fuel flows incl. `ff_idl`) | Take-off thrust; taxi and landing-roll idle fuel flow |

All of these files are inside the GPL-3.0 `openap/data/` directory. The
`_synonym.csv` files in `wrap/`, `dragpolar/` and `aircraft/` are **not used**.

## 3. Project-curated cargo aircraft targets

| Item | Detail |
|---|---|
| Location | `data/reference/cargo_aircraft_targets.csv` (version-controlled since Part 2; previously a Python constant) |
| Content | Five freighter types with manufacturer, model, variant, ICAO type designator and related OpenAP code. No numeric attributes |
| Access method | Manual curation. Version = SHA-256 of the CSV file (a new checksum creates a new `data_source` row) |
| Designator reference | ICAO Doc 8643, *Aircraft Type Designators*: https://www.icao.int/publications/doc-8643-aircraft-type-designators. B77L as the designator for the 777F is confirmed by public listings (e.g. https://en.wikipedia.org/wiki/List_of_aircraft_type_designators) |
| Licence | Project-authored. ICAO Doc 8643 is © ICAO and sold through the ICAO store, so only individual designators are cited and the ICAO database is **not** downloaded or redistributed |
| Limitations | The designators should be re-checked against the current ICAO Doc 8643 online lookup before relying on them operationally |

## 4. Manufacturer aircraft characteristics documents (investigated; values not extracted)

All five documents were downloaded on 2026-10-15 to
`data/raw/aircraft/manufacturer/`, which is git-ignored and not
redistributed. Their references are recorded in
`data/reference/freighter_specification_references.csv`: document number,
revision, section and page, SHA-256 and terms evidence.

| Freighter | Document | Section | Terms (verbatim evidence) |
|---|---|---|---|
| A330-200F | Airbus *A330 Aircraft Characteristics – Airport and Maintenance Planning*, Dec 01/25 ([PDF](https://www.aircraft.airbus.com/sites/g/files/jlcbta126/files/2025-12/AC_A330_20251201.pdf)) | 2-1-1, pages 12–13: MTW/MRW, MTOW, MLW, MZFW and estimated maximum payload for weight variants WV000/WV001/WV002; usable fuel | "It must not be reproduced in whole or in part without permission in writing from the owners of the copyright. Requests for reproduction of any data in this document … must be addressed to Airbus." |
| 777F | Boeing D6-58329-2 *777-200LR/-300ER/-Freighter Airplane Characteristics for Airport Planning*, Rev G, Dec 2024 ([PDF](https://www.boeing.com/content/dam/boeing/v2/airports/acaps/777-200LR-300ER-F_Rev_G.pdf)) | 2.1 General Characteristics | "Copyright © 2024 Boeing. All Rights Reserved." No reuse licence stated |
| 767-300F | Boeing D6-58328 *767 Airplane Characteristics for Airport Planning*, Rev K, Dec 2024 ([PDF](https://www.boeing.com/content/dam/boeing/v2/airports/acaps/767_REV_K.pdf)) | 2.1.5, page 2-6 | Same Boeing notice |
| 747-400F | Boeing D6-58326-1 *747-400 Airplane Characteristics for Airport Planning*, Rev F, Dec 2024 ([PDF](https://www.boeing.com/content/dam/boeing/v2/airports/acaps/747-400_Rev_F.pdf)) | 2.1.7–2.1.9 (by engine maker) | Same Boeing notice |
| A321P2F | Airbus *A321 Aircraft Characteristics*, 01-Jul-2026 ([PDF](https://mediaassets.airbus.com/pm_38_916_916230-7u6neg4lfg.pdf)) | **None.** The document has no freighter or P2F content (0 text matches) | Same Airbus notice. The conversion is by EFW; no public specification document was located |

**Decision.**
- Airbus explicitly requires written permission to reproduce any data.
- Boeing reserves all rights and grants no reuse licence.
- Under the project rule ("where licensing permits"), **no manufacturer values
  were extracted or stored**. Freighter MTOW, MLW, MZFW, OEW, payload and fuel
  capacity stay NULL.
- Written permission from Airbus and Boeing would allow these values to be
  added with the page references above.
- The documents also publish several weight variants per type (A330-200F) or
  per engine (747-400F). The master data would need a weight-variant concept
  to hold them correctly.

## 5. ICAO reference values used as defaults

| Value | Source | Use |
|---|---|---|
| LTO taxi/ground idle time 26 min; take-off mode 100 % thrust | ICAO Annex 16 Vol. II reference LTO cycle (also used by the ICAO Engine Emissions Databank) | Default taxi times (26 min split equally between taxi-out and taxi-in, a project assumption); take-off thrust assumption |
| Idle fuel flow `ff_idl` per engine (7 % rated thrust) | ICAO Engine Emissions Databank, as distributed in OpenAP `engines.csv` | Taxi and landing-roll fuel flow |
| Earth mean radius R1 = 6371.0088 km | IUGG | Haversine distance |

## Sources investigated but not used

- **ICAO Doc 8643 bulk data:** copyrighted, and terms for bulk reuse are unclear.
  Not ingested.
- **OpenAP synonyms:** not used, because they substitute different aircraft.

Cost data sources (fuel prices, exchange rates, navigation charges, airport
tariffs and Part 4 financial benchmarks) are documented in
[cost_data_sources.md](cost_data_sources.md). The Part 4 source register is
`data/reference/cost_benchmark_sources.csv`.
