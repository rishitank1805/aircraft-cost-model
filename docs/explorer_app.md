# Aircraft Explorer & Learning Dashboard (Part 6)

An interactive learning platform over the project database. Its primary focus is aircraft
types, specifications, freighters and passenger-to-freighter (P2F) conversion, plus flight
performance. Operating-cost analytics are an advanced, secondary module.

## Run locally

```bash
# 1. Python side (once): install the package with the API dependencies and load specifications
pip install -e ".[dev]"                                 # adds fastapi, uvicorn, openpyxl, httpx
python scripts/ingest_aircraft_specifications.py        # migrates to 0008, loads OpenAP/FAA/curated specs (insert-only)

# 2. Frontend (once, and after frontend changes)
cd frontend && npm install && npm run build && cd ..

# 3. Start: read-only API + built frontend on http://127.0.0.1:8000
python scripts/run_explorer.py
```

For frontend development, run `python scripts/run_explorer.py` and `npm run dev` (in
`frontend/`) side by side. Vite proxies `/api` to port 8000. Open http://localhost:5173.

**Tests:**
- `pytest` runs all Python tests, including `tests/test_explorer_api.py` and
  `tests/test_aircraft_specifications.py`.
- `cd frontend && npm test` runs Vitest; `npm run typecheck` runs TypeScript.

## Architecture

```text
frontend/ (React 19 + TypeScript + Vite + Tailwind CSS 4 + Recharts + Lucide)
  src/pages/        Home, Library, AircraftDetail, Compare, Cargo, FlightLab, KnowledgeHub, Economics
  src/components/   Layout, SpecTable (values + provenance), GlossaryTerm (popover), Silhouette, ui badges
  src/diagrams/     schematic SVG teaching diagrams (dimensions, weights, turbofan, payload-range, phases, ULD, P2F)
        │  fetch /api/...
        ▼
src/aircraft_cost_model/api/ (FastAPI + Pydantic; SQLite opened read-only: mode=ro)
  specs.py          specification service: all values side by side, primary only for display, missing inventory
  routers/aircraft  /aircraft, /aircraft/{code}, /compare
  routers/learn     /glossary, /glossary/{slug}, /cargo         (content/*.json, version-controlled, referenced)
  routers/flight    /flight/aircraft, /airports/search, POST /flight/estimate  -> Part 2 estimate_flight (not saved)
  routers/economics /economics/estimates[/{id}[/sensitivity]], /economics/benchmarks -> Parts 4-5 analytics
        │
        ▼
database/aircraft_costs.db (migration 0008 adds aircraft_specification)
```

The API reuses the existing engines:
- **Part 2:** `estimate_flight` and the OpenAP provider;
- **Part 4:** `calculate_full_costs`, through the analytics cases;
- **Part 5:** `unit_metrics`, `one_way` and `benchmark_metric`.

The frontend contains **no** performance or cost formulas. It only formats and plots API values.

## Safety and data rules

- **Read-only.** The engine is opened with `?mode=ro`, so any write raises
  `attempt to write a readonly database` (this is tested). Flight Lab calculations are
  returned, not saved.
- **Static file serving** resolves paths and refuses anything outside `frontend/dist`
  (path traversal is tested).
- **CORS** allows only the Vite dev server. The launcher binds to 127.0.0.1 by default.
- **Every specification value** carries its source, unit, source type, verification status,
  variant or condition, original published value, and notes.
- **Missing values stay missing.** The detail page lists them per section.
- **Freighters never use passenger rows.** Passenger-aircraft rows are never mapped to
  freighters; a related passenger type is linked with an explicit warning.
- **Inconsistent values** (`source_inconsistent`) are struck through and never used as the
  displayed primary value. Example: the Airbus A330-200F page's "Max take-off weight
  187.00 t", which is below its own max ramp weight of 233.90 t.

## Features by section

| Section | What it shows |
|---|---|
| Home | Statistics, section entry points, three learning paths |
| Aircraft Library | 42 aircraft. Search and filters: manufacturer, model series (derived from the designation and labelled as such), role, freighter type, body type (FAA-documented), engines, flight-model support. Card and table views, key-specification coverage bar, schematic silhouette (no licensed photographs are bundled) |
| Aircraft Detail | A Overview (sourced sentences, role evidence, related types, flight-model status, BTS benchmark-only figures); B Dimensions (labelled diagram + all sources); C Weights (plain-language terms, a weight ladder on one scale, the OEW/payload/fuel diagram only when OEW, MZFW and MTOW exist, structural-vs-revenue payload warning); D Engines (turbofan explainer); E Performance (published specs separated from OpenAP model values); F Cargo (freighter facts and programme); G Sources & limitations (sources used, missing-data inventory, all values) |
| Compare | 2-3 aircraft. A row is like-for-like only with the same source, unit and condition; otherwise the incompatibility is stated. Charts are drawn only for like-for-like numeric rows |
| Cargo & P2F | 8 explainers (sourced or general explanation is labelled), a 7-step conversion guide with an interactive diagram, the 5 target freighters with classification, "not to be confused with", published facts and gaps |
| Flight Lab | 16 supported aircraft. Airport search, payload; results: timeline, fuel by phase, altitude and mass profile, block-time breakdown, mass at boundaries, limit checks ("not performed" where no certified limit exists), assumptions and warnings; phase explanations. Deep link: `?aircraft=A320&origin=FRA&destination=CDG&payload=10000&run=1` |
| Knowledge Hub | 22 topics with definition, why it matters, sourced example, related specifications, diagram, references and basis. Deep links `/learn#mzfw`; glossary popovers on detail pages |
| Operating Economics (advanced) | Saved estimates with partial/complete labels and N/A components, unit costs, fuel/maintenance/utilisation/crew sensitivity, FAA Table 4-7 (with proxy adjustments marked pending), BTS 777F benchmark-only figures |

See [design_system.md](design_system.md) for the visual design and
[aircraft_specifications.md](aircraft_specifications.md) for source coverage and the
missing-data inventory.

## Hosted deployment (Vercel)

The hosted explorer uses a **public copy** of the database: `database/explorer_public.db.gz`,
built from the live database by `python scripts/build_public_db.py`. The rows of the restricted
EUROCONTROL / DFS / Fraport tables (`navigation_rate`, `navigation_zone_aerodrome`,
`airport_tariff`) are removed (owner decision 2); their `data_source` metadata rows stay. The build
refuses to run if a saved cost component was priced from those rates. The live database and its
backups are never committed or uploaded (`.gitignore`, `.vercelignore`).

- Entrypoint: `vercel_app.py` (`[tool.vercel] entrypoint` in `pyproject.toml`).
- Build step: `scripts/vercel_build.py` restores the database and builds `frontend/dist`.
- After changing the live database, rebuild the public copy and commit the new `.gz`.
- Flight Lab results are computed per request and never saved; the database is opened read-only.
