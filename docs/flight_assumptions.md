# Flight estimate assumptions

Every estimate stores the assumptions it used in `flight_assumption`, with a
`source_type` taken from this vocabulary:

| source_type | Meaning |
|---|---|
| `user_input` | Supplied on the command line or in `FlightRequest` |
| `project_default` | Documented default used because the user gave no value |
| `openap_model` | Value taken from OpenAP data (WRAP, ICAO databank via OpenAP, etc.) |
| `database` | Value read from the project database (airport or aircraft master data) |
| `physical_constant` | Definition or standard constant |
| `modelling_assumption` | Simplification built into the model |

## Assumptions and their effect

| Assumption | Default | Source / basis | Effect on results | Override |
|---|---|---|---|---|
| Distance method | Haversine, R = 6371.0088 km | IUGG mean radius | ≤ ~0.5 % vs ellipsoid | – |
| Route factor | 1.0 (great circle) | Project default: no route extension assumed | Real routes are longer, so fuel and time are understated | `--route-factor`, `--route-distance-nm` |
| Wind | None (GS = TAS) | Modelling assumption | Head/tailwinds change time and fuel materially | – (later enhancement) |
| Atmosphere | ISA, no ΔT | Modelling assumption | Hot days raise TAS and thrust demand | – |
| Cruise altitude | WRAP mean cruise altitude rounded to 1,000 ft, capped at OpenAP ceiling | OpenAP WRAP | Lower altitude → higher fuel flow | `--cruise-altitude-ft` |
| Short-route altitude reduction | 1,000 ft steps; floor at 1,500 ft above the origin / 1,000 ft above the destination | Modelling choice | Allows short routes; logged as a warning | – |
| Kinematics | WRAP mean speeds, rates and crossover altitudes; mass-independent | OpenAP WRAP | Typical, not optimised, profiles | – |
| Climb acceleration / descent deceleration | 0.5 / 0.2 m/s² | OpenAP `FlightGenerator` constants | Minor | – |
| Initial climb / final approach heights | 1,500 ft / 1,000 ft above the airport | OpenAP `FlightGenerator` | Phase boundaries | – |
| Take-off thrust | 100 % rated (no derate) | ICAO LTO take-off mode is 100 % | Slightly overstates take-off fuel | – |
| Drag | Clean configuration in all airborne phases | OpenAP `FuelFlow.enroute` | Understates approach fuel | – |
| Reverse thrust | Not modelled; landing roll at idle | Modelling assumption | Slightly understates landing-roll fuel | – |
| Mass/fuel boundaries (`fuel_accounting_basis`) | v2: take-off mass at brake release, landing mass at touchdown, trip fuel = brake release → touchdown, landing roll separate | Standard weight definitions; MLW applies at touchdown | Trip fuel excludes runway fuel after touchdown | – |
| Taxi times | 13 min out + 13 min in (**approved project default, labelled as an assumption** in every estimate and in CLI output) | ICAO Annex 16 Vol. II LTO taxi/idle 26 min, split equally (project assumption) | Taxi fuel ∝ time; not observed, not airport-specific | `--taxi-out-min`, `--taxi-in-min` |
| Taxi fuel flow | ICAO idle (7 % rated thrust) × all engines | ICAO Engine Emissions Databank via OpenAP | Single-engine taxi would reduce it | – |
| Fuel density | 0.8025 kg/L | OpenAP `mass.py` litre-to-kg factor | Converts fuel capacity (L) to kg for the capacity check only; actual batches vary | `--fuel-density-kg-per-l` |
| Contingency / alternate / final reserve | 0 / 0 / 0 kg | No regulatory policy implemented | Raises take-off mass and trip fuel when supplied | `--contingency-pct`, `--alternate-fuel-kg`, `--final-reserve-fuel-kg` |
| OEW and limits | OpenAP type-level values from `aircraft_type` | OpenAP via Part 1 ingestion | Not operator- or weight-variant-specific | – |
| Integration time step | 30 s (shortened at boundaries) | Project default | 30 s vs 5 s: 0.02 % on A320 FRA–CDG | `--time-step-s` |
| Integration method | Explicit midpoint (RK2) in mass | Modelling choice | Error < 1e-6 on analytic test | – |
| Convergence | 1 kg tolerance, at most 25 iterations | Project default | Residual ≤ 1 kg | `--tolerance-kg`, `--max-iterations` |
| Missing airport elevation | 0 ft with warning | Modelling assumption | Small | – |

## What is *not* assumed

- **No passenger model substitutes for a freighter.** OpenAP synonyms are
  never used.
- **No missing limit is treated as satisfied.** MZFW, maximum payload and
  maximum ramp weight are reported as `not_performed`, and the estimate status
  is then `calculated_limits_unverified`.
- **No estimated route is presented as a flown route.**
- **No result is presented as a dispatch fuel plan or an airline's actual
  fuel burn.**
