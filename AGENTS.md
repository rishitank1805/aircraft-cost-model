# AGENTS.md: instructions for AI coding sessions

## Objective
An open, reproducible model of cargo aircraft operating costs per flight
(aircraft type, origin, destination, date, payload, ULDs), producing COC, TOC,
total costs, RTNM and cost per RTNM from freely accessible public data.

## Roadmap
1. **Data foundation**: airports, aircraft master data, provenance, SQLite. **COMPLETED**
2. **Flight performance**: route distance, kinematic profile, block time, OpenAP fuel burn. **COMPLETED**
3. **Variable operating costs**: fuel, EUROCONTROL route charges, airport tariffs, ground handling. **IMPLEMENTED, awaiting owner review (uncommitted on feature/part-3-variable-costs)**
4. Maintenance, fixed and financial costs from documented public benchmarks
5. Analytics, scenarios, sensitivity analysis, validation against public airline financials

**Do not start a later part without explicit approval from the project owner.**

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

## Testing
- `pytest` must pass before claiming completion. Never claim results for tests
  that were not run.
- Tests use fixtures, `tmp_path` and temporary SQLite databases. They make no
  network calls and never touch `database/aircraft_costs.db`. Integration
  tests read the locally installed OpenAP package.
- Where a test compares timestamps, use a deliberately old value: timestamps
  have 1-second resolution, so a fast test can miss a spurious update.
- Add tests for new cleaning rules, validators and loaders.
