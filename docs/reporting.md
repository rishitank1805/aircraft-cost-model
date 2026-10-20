# Reporting (Part 5)

Formats:
- **Console** text;
- **CSV**: nested fields are flattened as `a.b`; lists are joined with `; `;
  a missing value is an empty cell;
- **JSON**: decimals as exact strings; missing values as `null`;
- **PNG** charts: matplotlib, Agg backend, no GUI.

There is no web application and no PDF.

```bash
python scripts/generate_cost_report.py --full-cost-estimate-id 1 --distance-basis modelled_route \
    --ownership-scenario data/scenarios/example_operating_lease.json \
    --compare-full-cost-estimate-ids 2 3 --output-dir data/output/reports/a320_fra_cdg
```

`data/output/` is git-ignored: reports are regenerated from the database. The
report folder contains:

| File | Content |
|---|---|
| `report.txt` | Console text of every section |
| `unit_metrics.csv/.json`, `components.csv` | Metrics with all bases, coverage, quality and FX; components with status, source type, source quality and reference |
| `01_component_breakdown.png` | Component bars coloured by source quality. Unavailable components are listed as N/A with **no bar**; not-applicable ones as n/a |
| `02_categories.png`, `03_coc_toc_total.png` | Calculated subtotals. Hatched and labelled **PARTIAL** when incomplete; the title states *complete totals UNAVAILABLE* |
| `04–06_sensitivity_*.png` + CSV/JSON | Fuel price, airframe maintenance rate and utilisation (each only if the input exists in the scenario) |
| `07_owned_vs_leased.png`, `ownership_table.csv`, `ownership_comparison.json` | With `--ownership-scenario` |
| `08_comparison.png`, `comparison.csv/.json` | With `--compare-full-cost-estimate-ids`. Partial subtotal next to the `common_component_comparison`; mismatches noted |
| `09_benchmark_comparison.png`, `benchmark_comparisons.csv`, `validation.json`, `validation_checks.csv` | Validation A–D. Only comparable benchmarks are drawn; not-comparable ones are listed as text |
| `manifest.json` | Analytics version, input hash, distance and payload basis, and the SHA-256 of every file |

**Chart rules:**
- A partial subtotal is never drawn as a complete cost.
- Unavailable values are never drawn as zero.
- Assumptions and benchmarks are colour-coded.
- Currency and units are on the axis.
- The pricing date is in the title.
- Footnotes state missing components, operational validity and that the
  illustrative values are not airline costs.

**Reproducibility:**
- For identical inputs every file is byte-identical, so the manifests match.
  Two report runs are compared in the tests.
- Saved runs (`--save` on the individual scripts) are immutable and keyed by
  input hash; see [analytics.md](analytics.md).

**Example set generated on the real database (2026-10-15):**
`data/output/reports/a320_fra_cdg/` holds the 27 report files listed above.
Its `runs/` subfolder holds saved runs 1–8:
- unit metrics;
- three sensitivities and a fuel × utilisation grid;
- owned versus leased;
- the route and aircraft comparison including the B777F;
- validation.
