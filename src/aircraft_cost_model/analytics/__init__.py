"""Part 5: analytics, scenario analysis, benchmarking and validation.

The analytics layer transforms, compares and validates estimates produced by
Parts 2-4. It contains no cost formulas of its own: whenever a scenario
changes a cost input, the affected components are recalculated through the
Part 3 fuel engine or the Part 4 full-cost calculator.

Every analytical result keeps three independent dimensions:

- **cost coverage**: complete / partial / missing_required_input / unsupported / calculation_error;
- **operational validity**: the Part 2 flight estimate's status, carried unchanged;
- **source quality**: observed public data, public market benchmark, public
  financial benchmark, modelled estimate, explicit user assumption or mixed.

A missing cost is never zero, and a partial subtotal divided by a denominator
is a *partial* unit cost.
"""

ANALYTICS_VERSION = "analytics v1"
