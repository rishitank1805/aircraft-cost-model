# Tariff methodology (Part 3)

**Licensing stance:** the project is treated as **potentially commercial**.
- EUROCONTROL permits reproduction of its content for non-commercial purposes
  only.
- Fraport and DFS state no reuse terms.

So their numeric rates and tariff values are **not** reproduced in this
repository, documentation or tests. They are transcribed into git-ignored
files under `data/local/` and used only locally. Examples below are
symbolic, or use clearly marked **synthetic** rates.

## 1. EUROCONTROL en-route charges

**Sources:**
- *Conditions of Application of the Route Charges System and Conditions of
  Payment*, Doc. 21.60.02 (November 2021), Arts. 3–7 (CoA);
- CRCO *Customer Guide to Charges* (April 2026), A.1.2;
- annual Information Circulars No. 2025/01 and 2026/01, Annex A, for the
  unit rates.

```text
Route charge = Σ_i r_i
r_i = t_i × N_i                    CoA Art. 3
N_i = d_i × p                      CoA Art. 4
d_i = (great-circle km in zone i − 20 km × (take-offs + landings in zone i)) / 100     CoA Art. 5
p   = √(MTOW_t / 50)               CoA Art. 6; Guide A.1.2.2
t_i = national + administrative unit rate, EUR                                        CoA Art. 7
```

### Methodology verification

| Item | Official text | Status in this project |
|---|---|---|
| Charging-zone treatment | d_i per charging zone, between the departure aerodrome or **entry point** and the arrival aerodrome or **exit point**, "based on the actual route flown as recorded by the Network Manager"; repeated for each zone overflown (CoA Art. 5.1; Guide A.1.2.1) | **Verified.** The route geometry is not available, so zone distances are explicit inputs (`--nav-zone ZONE:KM:TAKEOFFS:LANDINGS`). Without them the result is `unavailable_route_geometry` |
| 20 km deduction | "reduced by twenty (20) kilometres for each take-off from and for each landing in the charging zone" (Art. 5.3) | **Verified**, implemented. Chargeable km cannot fall below 0 |
| Circular flights | Special rule, Art. 5.2 | **Not supported**: origin and destination must differ |
| Distance-factor rounding | None stated (Art. 5; Guide A.1.2.1) | **Unresolved interpretation:** d_i is not rounded |
| Weight-factor basis | "certificated maximum take-off weight of the aircraft as shown in the Aircraft Flight Manual"; the highest if several; if unknown to EUROCONTROL, "the heaviest aircraft of the same type known to exist" (Art. 6) | **Verified.** An official-style calculation **requires the certificated MTOW** (`--certificated-mtow-kg`). OpenAP's type-level MTOW is allowed only as an explicit scenario (`--type-level-mtow-scenario`, status `calculated_assumption`). Otherwise `missing_required_input` |
| Weight-factor rounding | MTOW "taken to one decimal"; p "taken to two decimal places" (Art. 6; Guide: "the square root of the result taken to the second decimal") | **Unresolved interpretation:** no rounding direction is stated. Round half up is implemented; the **truncation** result is computed and shown alongside. Example: 78.0 t gives √1.56 = 1.2490, so p = 1.25 (half up) or 1.24 (truncated), a 0.8 % difference |
| Charge rounding | None stated | **Unresolved interpretation:** per-zone charges unrounded; total rounded once to cents, half up |
| Unit rate | Global rate = national + administrative, EUR (Art. 7); "applicable as from 1st January of each year"; monthly FX adjustment for non-EMU states (Guide A.1.2.3) | **Verified** for EMU zones (Germany, France, Belgium–Luxembourg, Netherlands; 2025 and 2026). Non-EMU monthly adjusted rates are not loaded |
| Rate end date | Not published | **Unresolved interpretation:** valid_to = 31 December, inferred from the annual cycle |

Every calculated navigation result carries these unresolved items as
`unresolved_interpretation` assumptions, and the CLI lists them.

**Synthetic example** (rates invented; Germany t = 100.00, France t = 80.00;
certificated MTOW 78,000 kg):

```text
p = 1.25 (truncated alternative 1.24)
Germany: 170 km, 1 take-off → d = 1.5 → 1.5 × 100.00 × 1.25 = 187.50
France:  290 km, 1 landing  → d = 2.7 → 2.7 ×  80.00 × 1.25 = 270.00
Total 457.50 (truncation alternative 453.84)
```

## 2. Terminal navigation charges

A separate component, `terminal_navigation`.

| | France | Germany |
|---|---|---|
| Billed by | EUROCONTROL CRCO | DFS directly |
| Rules | Information Circulars **LF 2025/01** and **LF 2026/01**, Annex Arts. 1, 3, 4 and Appendix 1 (aerodrome lists) | DFS *Air Navigation Services Terminal Charges* valid from **1 Jan 2026**, §§ 1–3 |
| Charged movement | "for each IFR flight departing from the aerodromes listed" (Art. 1); Guide A.2.2: "levied upon the departing flight only" | "Approach and departure … count as one flight. The counting unit is the departure." (§ 1.2) |
| Formula | R = t × N; N = (MTOW / 50)^0.70 "taken to two decimal places"; MTOW in tonnes to one decimal, "the one used for calculating the EUROCONTROL route charge" (Arts. 3–4) | R = t × p; p = (MTOW_t / 50)^0.7 to two decimals, AFM certificated MTOW (§ 3) |
| Zones | Zone 1: LFPG, LFPO. Zone 2: 52 aerodromes | One zone of 15 aerodromes incl. EDDF |
| Rates loaded (local) | 2025, 2026 (verified) | **2026 verified** (DFS notice). **2025 rate verified** from EUROCONTROL's *Terminal ANS unit rates applicable from 1 January 2025*, but the 2025 DFS rules notice is no longer published (404) and EUR-Lex (Reg. (EU) 2019/317) is not retrievable automatically. The 2025 row is therefore **`pending_review`** and **not priced** |
| Tax | – | Rate "subject to Value Added Tax, the rate being 19% at present". **VAT is not modelled**; amounts are net, with a warning |

**Per flight:**
- **Origin departure:** charged under the origin zone's rule.
- **Destination arrival:** **zero by tariff rule** only when the verified
  rules of the destination's zone charge departures only (for example CDG,
  France zone 1).
- **Aerodromes outside any loaded zone:** `unavailable_public_tariff`. An
  unknown national rule is never treated as zero.

The rounding interpretations are the same as in §1. Example: (78.0 / 50)^0.7
= 1.3652, giving N = 1.37 (half up) or 1.36 (truncated).

**Synthetic example** (zone rate t = 300.00): 300.00 × 1.37 = 411.00
(truncated alternative 408.00). The arrival at a departure-only zone is 0.00.

## 3. Airport landing and take-off charges

### Engine

- Each `airport_tariff` row names a rule (`calculation_method`) and holds
  reviewed parameters (`parameters_json`) for a validity interval.
- The engine selects the **single** version in force on the pricing date.
  None gives `unavailable_public_tariff`; overlapping versions give
  `calculation_error`.
- It then asks the rule for missing inputs. Any missing input gives
  `missing_required_input`, and the inputs are listed.
- Otherwise it applies the rule and converts the currency.
- A flight is charged one take-off at the origin and one landing at the
  destination, each under that airport's own tariff.
- Parking, passenger, security, PRM and noise-surcharge charges are separate
  and not included.

### FRA rule `fra_movement_charges_2026` (Fraport, in force from 1 Aug 2026)

Values are local only. Structure, for non-ferry fixed-wing flights with
MTOM above the applicability threshold (section 1.2.3):

| Element (section) | Rule | Inputs |
|---|---|---|
| Passengers (1.2.4) | rate × passengers on board at take-off (take-off only) | `departing_passengers` |
| Freight / mail (1.2.4) | rate × started 100 kg on board, per landing and per take-off | `freight_mail_kg` |
| Noise (1.2.5–1.2.8) | fixed amount by noise category (separate landing and take-off tables), per movement | `noise_category_takeoff` / `_landing`, `noise_certification` |
| Night surcharge (1.2.8) | + category amount for night time 1 **or** night time 2 (local time windows in the tariff) | `movement_local_time` |
| NRI reduction (1.2.12) | Chapter 4 and higher, outside night time 2: noise charge reduced by a % depending on NRI category and MTOM band | `nri_category` |
| Emissions (1.2.13) | rate × emissions value (kg NOx-equivalent, ERLIG formula, three decimals), per landing and per take-off | `emission_value_kg_nox_eq` |

- **Weight basis:** the highest MTOM in the registration documents (1.2.2).
  The same MTOW rule as navigation applies: certificated value required, or
  an explicit type-level scenario (`calculated_assumption`).
- **The 1.2.3 mass-related charge applies only to ferry flights and
  helicopters**, not to normal commercial flights.
- **Not implemented** (`unsupported_tariff_rule`): ferry flights, minimum
  charges for light aircraft, and Chapter 3, marginal and non-certified
  surcharges (1.2.9–1.2.11).
- **Unresolved interpretation:** the NRI reduction is applied to the
  movement's whole 1.2.8 noise amount, including any night-time-1
  surcharge.
- **Rounding:** the emissions value is rounded to three decimals and freight
  uses started 100 kg, both as stated in the tariff; the movement total is
  rounded once to cents, which is a project choice.
- **No silent defaults:** noise category, NRI category, emissions value,
  passengers, freight and time are user inputs. The tariff's
  aircraft-to-category tables (1.2.6 landing, 1.2.7 take-off) are not copied
  into the project.

### CDG: deferred

Groupe ADP's tariff document is behind bot protection, which was **not
bypassed**. Status `unavailable_public_tariff` until a legitimately accessible
source is available.

## 4. Ground handling

`Handling cost = applicable tariff rate × chargeable quantity`, per airport
movement.

**Applicability (all required):**
- the payer is the aircraft operator;
- the aircraft category matches;
- the movement matches;
- the quantity is known (cargo tonnes and ULD counts are user inputs, never
  derived from payload);
- exactly one tariff applies.

**FRA central ground-handling infrastructure charges** (Fraport charges §2,
per turnaround) are **kept separate and not included**: no documented rule
allocates a per-turnaround infrastructure charge to a one-way flight.
Fraport's *List of Service Charges* gives service-hour rates, not a
per-flight price. With no applicable public tariff the result is
`unavailable_public_tariff`, unless an explicit
`--handling-assumption AIRPORT:AMOUNT:CURRENCY` is given
(`calculated_assumption`).
