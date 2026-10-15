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
   **COMPLETED** (approved subject to final checks; committed on `feature/part-4-full-operating-costs`)
5. Analytics, scenarios, sensitivity analysis, validation against public airline financials.
   Carried over from the Part 4 review: BTS Form 41 (P-5.2 + T-2) is the priority benchmarking
   source, especially for all-cargo carriers; optional benchmark inflation adjustment only with a
   verified public index and documented original/target periods (originals never overwritten).

**Do not start a later part without explicit approval from the project owner.** Part 5 must not
start until the owner approves Part 4 and provides the Task 5 instructions.

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
7. **Preservation:** keep all Part 1–3 data, migrations (`0001`–`0006`), historical estimates
   (including `v1` flight estimates and the 4-component cost estimate #1) and source
   provenance. Back up the database before any migration.

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

## Testing
- `pytest` must pass before claiming completion. Never claim results for tests
  that were not run.
- Tests use fixtures, `tmp_path` and temporary SQLite databases. They make no
  network calls and never touch `database/aircraft_costs.db`. Integration
  tests read the locally installed OpenAP package.
- Where a test compares timestamps, use a deliberately old value: timestamps
  have 1-second resolution, so a fast test can miss a spurious update.
- Add tests for new cleaning rules, validators and loaders.
