# AGENTS.md: instructions for AI coding sessions

## Objective
An open, reproducible model of cargo aircraft operating costs per flight
(aircraft type, origin, destination, date, payload, ULDs), producing COC, TOC,
total costs, RTNM and cost per RTNM from freely accessible public data.

## Roadmap
1. **Data foundation**: airports, aircraft master data, provenance, SQLite. **COMPLETED**
2. **Flight performance**: route distance, kinematic profile, block time, OpenAP fuel burn. **COMPLETED**
3. **Variable operating costs**: fuel, EUROCONTROL en-route and terminal navigation charges, airport tariffs, ground handling. **COMPLETED** (approved; commit `8001a93` on `feature/part-3-variable-costs`)
4. **Full operating costs**: maintenance, crew, insurance, leasing, depreciation, financing and
   indirect costs from cited benchmarks or explicit scenario assumptions; COC/TOC/Total.
   **COMPLETED** (commit `a920004` on `feature/part-4-full-operating-costs`)
5. **Analytics and validation**: unit metrics, scenario/sensitivity analysis, comparisons, BTS Form
   41 benchmarks, optional index adjustment, validation, reports. **COMMITTED** (`e794b21` on
   `feature/part-5-analytics-validation`, committed at the owner's request before Part 6).
6. **Aircraft Explorer & Learning Dashboard**: read-only FastAPI layer + React/TypeScript frontend,
   aircraft specification values with provenance (migration 0008). **IMPLEMENTED, uncommitted on
   `feature/part-6-aircraft-explorer`, awaiting owner review.** Do not start further phases without
   new owner instructions.

## Owner decisions in force (recorded after Part 3 approval)
1. **Germany 2025 terminal navigation:** rules and rate stay `pending_review` and are not
   priced. Do not assume the 2026 DFS rules also applied in 2025.
2. **Licensing:** treat the project as potentially commercial. Do not redistribute
   EUROCONTROL, DFS or Fraport data unless the applicable rights permit it. Obtain written
   permission before any commercial use that requires it.
3. **EUROCONTROL weight-factor rounding:** keep round half up, labelled as a *project
   interpretation, not an officially verified rule*, and keep reporting the truncation
   comparison.
4. **FRA night-time calculation structure:** keep it as implemented, subject to
   source-licensing review.
5. **Git:** do not push to GitHub. Leave all branches and remote settings unchanged
   (`origin` points to an empty GitHub repository; `main` tracks the non-existent
   `origin/main`).
6. **Part 4 requirement:** report cost-component coverage, the validity of the underlying
   flight-performance estimate, and source/assumption quality as **separate** dimensions.
7. **Preservation:** keep all Part 1–3 data, migrations (`0001`–`0008`), historical estimates
   (including `v1` flight estimates and the 4-component cost estimate #1) and source
   provenance. Back up the database before any migration.

### Recorded at Part 4 approval
8. **FAA benchmarks:** keep the published FAA Table 4-7 figures unchanged. Index adjustment only
   with a verified public index and documented original/target periods. Adjusted values are
   separate records (Part 5: crew/insurance proxies pending approval; maintenance unavailable).
9. **BTS Form 41** was the priority Part 5 benchmarking source, especially for all-cargo carriers
   (implemented in Part 5 for P-5.2 + T2).
10. **Illustrative scenario values** stay clearly labelled; real lease, insurance and acquisition
    values are not required.
11. **Source classification:** EIA jet fuel is a `public_market_benchmark`, never an observed
    airline expense.

## Stack
Python ≥ 3.11, pandas, NumPy, requests, SQLAlchemy 2 + SQLite, Alembic,
python-dotenv, OpenAP 2.6.x (pinned; the adapter depends on its data layout),
pytest. No Docker, cloud, web frameworks or dashboards unless approved.
Package: `src/aircraft_cost_model` (src layout). Install with `pip install -e ".[dev]"`.

## Conventions
- Type hints, docstrings, `pathlib.Path`. All paths come from `config.get_settings()`.
  Never hardcode absolute paths.
- Structured logging: `logger.info("event_name", extra={...})`; scripts call
  `configure_logging()`.
- Nothing may run on import (no downloads or database writes at module level).
- Keep the stages separate: ingestion (raw, unmodified) → processing (clean) →
  validation (check and report) → database (transactional upsert).
- Database writes happen in a single transaction per ingestion run, upserting
  on stable source keys. Never blind-append.
- Schema changes go through **Alembic migrations** in
  `src/aircraft_cost_model/migrations/versions/`. Make them additive, never
  recreate or empty existing tables, and back-fill new columns from existing
  data. Add a test. `tests/test_migrations.py` checks that the ORM and
  migrations match.
- Back up `database/aircraft_costs.db` before migrating it.
- Keep Part 2 concerns separate: pure maths (`route`, `profile`, `mass`,
  `fuel`), OpenAP calls only in `openap_adapter`/`atmosphere`, database access
  only in `airport_lookup`/`persistence`, orchestration in `planner`.
- Curated inputs live in version-controlled CSVs in `data/reference/`.
- Part 3: money uses `Decimal` end to end and `DecimalText` columns (never
  floats or SQLAlchemy `Numeric` on SQLite). Keep ingestion, tariff parsing,
  pricing logic (`costs/*`) and persistence separate.
- Every cost needs a pricing date. Select observations on or before it,
  within the staleness window. Never use future or latest-overall data, and
  never interpolate.
- Missing costs are `amount = None` with an explicit status, never 0.
  `ComponentResult` enforces this. Never label a partial subtotal as a total.
- Use parameterized SQL for any user-supplied value.

## Data provenance (mandatory)
- Preserve raw downloads byte for byte with timestamp, URL and SHA-256. Never
  overwrite a raw snapshot.
- Register every dataset version in `data_source`, including licence and notes.
- Verify licences. Do not assume public means unrestricted. Document them in
  `docs/data_sources.md`.
- Store values in documented units. Every unit conversion or derived value
  must be labelled (`field_provenance` → `"derived: <method>"`).

## Rules against invented data
- Never invent values, endpoints or sources. Unavailable means NULL, documented
  as a gap.
- Never present estimates or benchmarks as actual airline expenses. Label
  assumptions explicitly.
- Never silently substitute a passenger model for a freighter, or one aircraft
  type for another. OpenAP synonyms are never used; always pass
  `use_synonym=False` (`WRAP` defaults to `True`).
- Do not extract manufacturer document values (Airbus AC, Boeing ACAPS) unless
  their terms permit it. Currently they do not; see `docs/data_sources.md`.
- Unknown limits must be reported as `not_performed`, never as passed. Do not
  label an estimate fully validated when a check could not run.
- Flight estimates are not dispatch fuel plans. Do not invent a regulatory
  fuel policy.
- Every default must be recorded as a `flight_assumption` with its source.
- Do not invent unit rates, tariff amounts, noise or emission categories,
  zone distances, ULD counts or handling prices. Missing inputs give
  `missing_required_input`; missing data gives `unavailable_*`.
- Never price legacy `v1` flight estimates.
- Treat the project as potentially commercial when assessing licences.
  EUROCONTROL (non-commercial only), DFS and Fraport values stay in
  git-ignored `data/local/`. Never put them in code, docs or tests; use
  synthetic fixtures. Never bypass access controls (e.g. ADP's or EUR-Lex's
  bot challenges).
- Navigation charges need the certificated MTOW. The OpenAP type-level MTOW
  is allowed only as an explicit scenario (`calculated_assumption`).
- Record unresolved methodology interpretations as
  `unresolved_interpretation` assumptions; never present them as verified.
- Rates with `verification_status != verified_against_source` are never
  priced.
- Do not derive max payload from MZFW − OEW unless it is explicitly labelled as
  derived. Do not treat range as a fixed value.
- Do not assume an airport with an IATA code is suitable for cargo.

### Part 4 (full costs)
- Never invent maintenance or LLP reserve rates, crew pay, lease rates,
  insurance premiums, aircraft values or loan terms. Each Part 4 input comes
  from a scenario file value that carries a `source_type`. Illustrative
  values must be labelled `illustrative_assumption`, and a benchmark must cite
  its `source_reference`.
- Scenario values are decimal strings (floats are rejected) with explicit
  units and effective periods. Nothing is defaulted, including the staffing
  factor and the engine-hours basis.
- Prevent double counting with explicit flags (`covers`,
  `hourly_rate_includes_cycle_costs`, `includes_llp`, `includes_allowances`,
  lease `includes`, G&A `excludes_administration`) and ownership modes. A
  contradiction gives `failed_validation`, never a silent choice.
- `not_applicable` is not the same as unavailable. Only `not_applicable`
  components may be absent from a complete total.
- Reuse the saved Part 3 `cost_component` rows. Never recompute or alter
  historical Part 3 results. Reject a mismatched flight or variable-cost
  estimate, and reject v1 fuel accounting.
- Keep cost coverage, operational validity (Part 2 status, unchanged) and
  source quality as three separate dimensions.
- Results are economic costs, not accounting expense: LLP is an accrual,
  principal repayment is excluded, and FAA depreciation/rental fleet blends
  are not used.

### Part 5 (analytics)
- Analytics transform, compare and validate saved estimates. Never put cost formulas in
  `analytics/`; recalculate through the Part 3 fuel engine or the Part 4 calculator.
- Never mutate saved estimates, scenario files or saved scenario rows. Variants are new
  scenarios (new content hash); analytics runs are immutable and keyed by input hash.
- A partial subtotal divided by any denominator is a *partial* unit cost and must be labelled
  so. Complete unit costs need complete totals.
- RTNM needs an explicit revenue cargo payload. Never use the Part 2 modelled payload. For a
  passenger scenario only an explicitly labelled hypothetical cargo payload is accepted. Zero
  payload gives an undefined (not zero) cost per RTNM.
- Distance bases (`great_circle`, `modelled_route`, `actual_flown`) are explicit and never mixed.
- Benchmarks: never invent BTS observations or index values. Use only `ok`-quality BTS rows by
  default. Never divide fleet-level (type 999) expenses by a type denominator. Report
  `not_comparable` with reasons rather than a deviation. Never call a difference against a
  differently defined benchmark a model error.
- Index adjustments never modify the original benchmark. Categories without a verified index
  stay `unavailable`. The crew/insurance proxy indices are pending owner approval.
- BTS and BLS data are public domain (citation required). Do not bypass access controls: BLS
  bulk files returned 403 and are not used.

### Part 6 (explorer)
- The API opens SQLite read-only (`mode=ro`) and never writes; Flight Lab results are not saved.
- No performance or cost formulas in the frontend; the API reuses the Part 2-5 engines.
- Every displayed specification needs source, unit, source type, verification status and variant.
  Keep sources side by side; never merge or average them. Missing values stay missing.
- Never map a passenger-aircraft row (e.g. FAA ACD B744/B763/A332) to a freighter. Use a shared row
  only when it names the freighter (B77L "777-200LRF/LR"), flagged `shared_designator_row`.
- Values that contradict their own source are stored as `source_inconsistent` and never shown as
  verified.
- Do not scrape restricted manufacturer documents. Images only with a per-image licence and
  attribution.
- The explorer does not expose EUROCONTROL / DFS / Fraport tables or rate breakdowns (owner decision 2).
- Educational text must cite references and label general explanations as such.
- The design is inspired by EFW (colours and font from its public CSS) but uses no EFW assets and
  must not imply affiliation.

## Testing
- `pytest` must pass before claiming completion. Never claim results for tests
  that were not run.
- Tests use fixtures, `tmp_path` and temporary SQLite databases. They make no
  network calls and never touch `database/aircraft_costs.db`. Integration
  tests read the locally installed OpenAP package.
- Where a test compares timestamps, use a deliberately old value: timestamps
  have 1-second resolution, so a fast test can miss a spurious update.
- Add tests for new cleaning rules, validators and loaders.
- Frontend: `cd frontend && npm test` (Vitest) and `npm run typecheck`.
