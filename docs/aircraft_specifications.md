# Aircraft specifications: sources, coverage and missing data (Part 6)

Table `aircraft_specification` (migration 0008) holds one row per aircraft × specification ×
source. Each row stores:
- the value in SI units, plus the original published value and unit;
- unit, source type and verification status;
- variant, condition and notes.

Sources are kept side by side, never merged. Load or refresh with
`python scripts/ingest_aircraft_specifications.py`; loading is insert-only, so a new source
version adds rows. The values already in `aircraft_type` (Part 1, OpenAP with per-field
provenance) are shown alongside.

## Sources (real database, 2026-10-16)

| Dataset | Values | Source type | Verification | Licence | What it provides |
|---|---:|---|---|---|---|
| OpenAP aircraft data (Part 1 raw snapshot) | 588 | open model data | `unverified_model_value` | GPL-3.0 (OpenAP data) | Fuselage length/width/height (**fuselage height is not overall height**), wing span/area/sweep/MAC, ceiling, nominal cruise range (no payload condition), MMO/VMO, seats, engine options |
| FAA Aircraft Characteristics Database (XLSX, last modified 2025-01-03) | 489 | published specification | `as_published` (13 `shared_designator_row`) | U.S. Government work (public domain) | Overall length, wingspan with/without winglets, tail height at OEW, wheelbase, main gear, MTOW, max allowable landing weight, approach speed, ADG/AAC/WTC |
| OpenAP `engines.csv` (ICAO Engine Emissions Databank values) | 128 | engine databank | `as_published` | GPL-3.0 (OpenAP); EEDB values | Rated thrust per engine, bypass ratio, pressure ratio, engine manufacturer (default engine only) |
| FAA Economic Values Tables 4-16/4-17 | 66 | documented classification | `as_published` | U.S. Government work | Narrowbody / widebody / regional jet (33 types) |
| Curated freighter facts (Airbus, Boeing, EFW pages, retrieved 2026-10-16) | 43 | published specification | `as_published` (1 `source_inconsistent`) | Facts with citation; page content (c) the publishers; only short attributed quotes | Freighter type, conversion provider, payloads, ranges with conditions, MZFW/MTOW/MLW (A321P2F WV011), A330-200F weights and dimensions, ULD positions, door, volume |

## Matching rules

- **OpenAP types** are matched to FAA ACD rows by ICAO type designator. The FAA row's model
  and BADA variant are recorded (e.g. A320 → "Airbus A320 (BADA model A320-231)").
- **Freighters** are matched to an FAA row only if the row names the freighter. B77L
  "Boeing 777-200LRF/LR" covers the 777F and is flagged `shared_designator_row`, because
  its weights are not separated by model. B744, B763 and A332 describe passenger models and
  are **not** used for the 747-400F, 767-300F or A330-200F.
- **Body class** is taken from FAA Tables 4-16/4-17 by BTS aircraft-type code. For
  freighters it is the documented class of the airframe type code (an airframe property),
  noted per row. Types without a table row (e.g. A319neo, A340-300, A380, 737 MAX 7/10,
  CRJ900, E170/E175) stay "not documented". The 61-99-seat regional-jet rows could not be
  extracted from the PDF and were not guessed.
- **Model series** in the Library is derived from the designation (e.g. "737-800" → "737")
  and is labelled as derived. No manufacturer "family" classification is claimed.
- **Inconsistent source values.** Airbus's A330-200F key figures list "Max take-off weight
  187.00 tonnes" together with a max ramp weight of 233.90 tonnes. Takeoff weight cannot
  exceed ramp weight, so the value is stored as `source_inconsistent` and never displayed
  as verified.

## Missing-data inventory (42 aircraft)

| Specification | Aircraft missing it | Why |
|---|---:|---|
| MZFW | 40 | Not in OpenAP or the FAA ACD; published only for the A330-200F (Airbus) and A321P2F (EFW) |
| Maximum structural payload | 39 | Published only for the A330-200F, 777F, 767-300F (Boeing/Airbus) and A321P2F (EFW) |
| Rated thrust / engine manufacturer | 10 | The 5 freighters (no engine data source), plus 5 OpenAP types whose default engine is not in `engines.csv` |
| Body class | 9 | Not in FAA Tables 4-16/4-17 (see above) |
| OEW | 5 | The 5 freighters (OpenAP OEW is for passenger types only) |
| Engine model/type/count, cruise Mach/speed, ceiling | 4-5 | Freighters: no permitted source |
| Overall length/height | 4 | B767-300F, B747-400F, A321P2F (no freighter-specific source); B3XM (not in FAA ACD) |
| Cargo door, volume, loading system, deck positions | 3-4 freighters | Published only for the A321P2F (EFW) and the A330-200F positions (Airbus) |
| Aircraft photographs | 42 | No licensed images bundled |
| Development history / context | 42 | Not sourced; only database-backed sentences are shown |

## Proposals for verified additional sources (not implemented: decisions for the owner)

| Missing field(s) | Proposed source | Licence / conditions | Additive approach |
|---|---|---|---|
| MZFW, MTOW, MLW per model incl. freighters (777F, 767-300F, 747-400F, A330-200F) | FAA Type Certificate Data Sheets (TCDS) via drs.faa.gov (likely A16WE for the 777, A1NM for the 767, A20WE for the 747 and A46NM for the A330 - identifiers to be confirmed on DRS) | U.S. Government work (public domain) | Download PDFs as raw snapshots; transcribe the weight tables per model and weight variant into a reviewed CSV; load as `published_specification` with TCDS revision and page; one row per weight variant (requires variant handling in the UI) |
| Freighter dimensions, door sizes, deck layouts, volumes | Manufacturer airport-planning documents (Airbus AC, Boeing ACAPS) | Reproduction requires written permission (recorded in Part 1) | Only with written permission; otherwise keep as missing |
| Aircraft photographs | Wikimedia Commons (per-image CC BY / CC BY-SA / public domain) | Per-image attribution; share-alike applies to the image only | Curated `aircraft_images.csv` (file URL, author, licence, licence URL); fetch via the Commons API with licence metadata; display the attribution under each image |
| Engine data for freighters | ICAO Engine Emissions Databank (EASA) for engines named in TCDS | EEDB terms (free use with citation) | After TCDS engine identification, look up the engine in the EEDB snapshot |
| 61-99-seat regional-jet classes | FAA Economic Values Table 4-17 (re-extract with OCR or manual transcription) | Public domain | Add rows to `aircraft_body_class_faa.csv` |
