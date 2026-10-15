# Cost data sources (Part 3)

Checked on 2026-10-15. Retrieval timestamps and checksums of each load are
stored in `data_source` and in the raw snapshot sidecars
(`data/raw/fuel_prices/`, `data/raw/exchange_rates/`).

## 1. EIA jet fuel spot price

| Item | Detail |
|---|---|
| Publisher | U.S. Energy Information Administration (https://www.eia.gov/petroleum/) |
| Series | `EER_EPJK_PF4_RGC_DPG`: U.S. Gulf Coast Kerosene-Type Jet Fuel Spot Price FOB (Dollars per Gallon) |
| Page | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=EER_EPJK_PF4_RGC_DPG&f=D |
| Access (default) | XLS download, **no API key**: https://www.eia.gov/dnav/pet/hist_xls/EER_EPJK_PF4_RGC_DPGd.xls (sheet `Data 1`; series key and unit label are checked on every parse) |
| Access (alternative) | API v2 `https://api.eia.gov/v2/petroleum/pri/spt/data/` needs a **free API key**; without one it returns `API_KEY_MISSING`. Set `ACM_EIA_API_KEY` and run `ingest_fuel_prices.py --api`. Parser tested with a fixture; not live-verified (no key) |
| Units | USD per U.S. gallon (stored as `USD/USgal`) |
| Frequency | Daily (trading days); no values on U.S. market holidays (e.g. 2025-01-09, 2025-01-20) |
| Coverage loaded | 1990-04-02 to 2026-10-06, 8,051 observations (2026-10-15 download, `Last-Modified: Wed, 07 Oct 2026`) |
| Licence | U.S. government work, **public domain**; EIA requests attribution ("Source: U.S. Energy Information Administration") |
| Commercial use | Public domain: no restriction |
| Limitations | U.S. Gulf Coast FOB spot benchmark. Not an airline contract price, a European into-plane price, or tax-, fee- or hedge-inclusive. Daily values are single trading-day assessments |

`xlrd` (BSD) was added to read the `.xls` file, which is the only key-free
machine-readable historical download.

## 2. ECB euro reference exchange rates

| Item | Detail |
|---|---|
| Publisher | European Central Bank, ECB Data Portal (https://data.ecb.europa.eu/) |
| Dataset | `EXR.D.<CCY>.EUR.SP00.A`: daily reference rates, *units of CCY per 1 EUR* (e.g. "US dollar/Euro" 1.0300 = 1 EUR is 1.03 USD) |
| Access | `https://data-api.ecb.europa.eu/service/data/EXR/D.USD+GBP+CHF.EUR.SP00.A?format=csvdata&startPeriod=2024-01-01` (no key) |
| Checks | `FREQ=D`, `CURRENCY_DENOM=EUR`, `EXR_TYPE=SP00`, `EXR_SUFFIX=A`, `UNIT_MULT=0` on every row; values parsed as exact decimals |
| Coverage loaded | USD, GBP, CHF from 2024-01-02 to 2026-10-15 (713 each); extend with `--currencies` and `--start` |
| Frequency | TARGET business days (no weekends or TARGET holidays) |
| Licence | Free use provided **the ECB is cited as the source** and information is reproduced accurately; reference rates are **for information purposes only** (https://www.ecb.europa.eu/services/disclaimer/html/index.en.html) |
| Commercial use | ECB terms allow free use with attribution (no non-commercial restriction) |
| Limitations | Reference rates, not transaction rates. EUROCONTROL's non-EMU monthly adjustments use Reuters rates, not ECB rates |

## 3. Navigation charges (EUROCONTROL en-route; EUROCONTROL / DFS terminal)

All numeric rates and terminal aerodrome lists are transcribed into
**git-ignored** `data/local/navigation_rates/` (`navigation_unit_rates.csv`,
`terminal_zone_aerodromes.csv`) and loaded with `ingest_navigation_rates.py`.
The repository keeps the values-free register
`data/reference/navigation_rate_sources.csv` (documents, checksums,
verification status).

| Source | URL | Used for | Verification |
|---|---|---|---|
| Conditions of Application, Doc. 21.60.02 (Nov 2021) | https://www.eurocontrol.int/sites/default/files/2021-10/doc-21-60-02-eurocontrol-conditions-application-november-2021-en.pdf | En-route methodology, Arts. 3–7 | Verified (rounding direction unresolved) |
| CRCO Customer Guide to Charges (April 2026) | https://www.eurocontrol.int/sites/default/files/2026-04/eurocontrol-customer-guide-to-charges.pdf | A.1.2 (en-route), A.2.2 (terminal: departing flight only) | Verified |
| Information Circular 2025/01 and 2026/01, Annex A | https://www.eurocontrol.int/sites/default/files/2024-12/circ-2025-01-eurocontrol-route-charges-system.pdf, https://www.eurocontrol.int/sites/default/files/2025-12/circ-2026-01-eurocontrol-route-charges-system.pdf | En-route global unit rates: Germany, France, Belgium–Luxembourg, Netherlands | Verified against source |
| Terminal charges in France, LF 2025/01 and LF 2026/01 | https://www.eurocontrol.int/sites/default/files/2024-12/lf-2025-01.pdf, https://www.eurocontrol.int/sites/default/files/2025-12/lf-2026-01.pdf | France terminal zones 1–2: rules, rates, aerodrome lists | Verified against source |
| EUROCONTROL, *Terminal ANS unit rates applicable from 1 January 2025* | https://www.eurocontrol.int/ServiceUnits/Dashboard/Downloads/Terminal%202025%20Unit%20Rates.pdf | Germany 2025 terminal rate and aerodrome list | Rate verified; Germany's 2025 rules **pending_review** (not priced) |
| DFS, *Air Navigation Services Terminal Charges* (from 1 Jan 2026) | https://www.dfs.de/homepage/de/unternehmen/rechtlicher-rahmen/flugsicherungsgebuehren/2026-apa-ifr.pdf | Germany 2026: counting unit departure, formula, rate (net of 19 % VAT) | Verified against source |
| DFS 2025 notice | analogous URL returns 404 | – | Not available |
| Regulation (EU) 2019/317 (EUR-Lex) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019R0317 | Would confirm the harmonised terminal formula for 2025 | Automated access returns an empty challenge (HTTP 202); not bypassed |

**Licence assessment (project treated as potentially commercial):**
- **EUROCONTROL:** "© EUROCONTROL"; reproduction is authorised for
  non-commercial purposes only, and commercial use needs written permission
  (https://www.eurocontrol.int/info/privacy-and-website-terms-use). Values
  are kept local and not redistributed.
- **DFS:** no reuse terms stated; values kept local.
- **Recommendation:** request written permission from EUROCONTROL (and DFS)
  before any commercial use or redistribution.

## 4. Airport tariffs

Register: `data/reference/airport_tariff_sources.csv` (version-controlled,
no tariff values).

| Airport | Document | Status | Terms |
|---|---|---|---|
| FRA | Fraport, *Airport Charges according to Art. 19b LuftVG*, valid from 1 Aug 2026 (sha256 `3487644d…`), sections 1.2.3–1.2.13 and 1.8 | Implemented. Values transcribed into the **git-ignored** `data/local/airport_tariffs/EDDF_landing_takeoff_2026-08-01.json` and loaded with `ingest_airport_tariffs.py` | © Fraport AG; no reuse licence stated, so **values are not redistributed** in the repository, docs or tests. The 2025 version is no longer published (the analogous URL returns 404) |
| CDG | Groupe ADP, *Tarifs des redevances aéroportuaires* (1 Apr 2024 – 31 Mar 2025) | **Deferred** until a legitimately accessible source exists. The official URL serves an Incapsula bot challenge, which was not bypassed. ART decision 2024-001 (https://www.autorite-transports.fr/wp-content/uploads/2024/02/decision-2024-001_vnc.pdf) confirms the structure but lacks the grid | Not reviewed |
| FRA | Fraport *List of Service Charges* (July 2026) | Not used for handling (service-hour rates, not per-flight) | © Fraport AG |

## 5. Not used

- **Paid fuel price assessments** (e.g. Platts, Argus): not free or openly
  licensed.
- **Airline handling or fuel contracts:** private.
- **Bypassing access controls:** never done.
