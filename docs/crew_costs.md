# Crew costs (Part 4)

Crew costs are two separate components. They must not overlap.

## `crew_salaries` (direct fixed)

**Basis `role_allocation`** (`crew.salaries.roles[]`): for each role,

```text
count × annual_compensation × (1 + employer_on_cost_rate) × block hours / annual_allocable_block_hours
```

The sum over all roles is then multiplied by `crew.salaries.staffing_factor`.

- **`annual_compensation`** (`CCY/year`): salary and fixed pay for one person
  in the role.
- **`employer_on_cost_rate`** (`ratio`): employer social charges, pension,
  benefits and similar costs.
- **`annual_allocable_block_hours`** (`block_hour/year`): the block hours one
  person in the role produces in a year. This is productivity, not the
  aircraft's utilisation. Roles may differ.
- **`staffing_factor`** (`ratio`, required): reserve, training and leave
  cover beyond the operating crew. It is **never defaulted**. To apply no
  extra cover, set it to `1` explicitly.

**Basis `rate_per_block_hour`**: a single all-in crew cost per block hour,
for example FAA Table 4-7 at 1,378 USD/BH (US Part 121 narrowbody, year
ending June 2023).

## `crew_allowances` (direct variable)

```text
per_diem_per_crew_member_per_duty_day × crew_count × duty_days
+ accommodation_per_crew_member_per_night × crew_count × nights
+ other_flight_expenses (CCY/flight)
```

Rate and quantity always come as a pair. Duty days and nights are separate
units (`days` and `nights`) and cannot be swapped.

## No overlap

`crew.salaries.includes_allowances` is required.

- If it is `true`, `crew_allowances` is `not_applicable`. Supplying an
  allowances section anyway gives `failed_validation`.
- The FAA crew rate is treated as already including crew personnel expenses,
  so the benchmark scenario sets it to `true`.

## Public sources

BLS OEWS 53-2011 (airline pilots, copilots and flight engineers): the
national annual mean wage was 288,650 USD in May 2025, retrieved through the
official BLS API. It is registered but not used, because:

- it is a wage only, without on-costs or productivity;
- it covers all US pilots and does not separate captains from first
  officers;
- it is not cargo-specific and not European.

No public source was found for European crew pay or allowances. The example
scenarios' crew values are illustrative only.
