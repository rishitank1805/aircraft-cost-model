"""Part 2: aircraft flight performance, route modelling and fuel consumption.

Modules are separated by concern:

- pure calculations: :mod:`route`, :mod:`profile`, :mod:`mass`, :mod:`fuel`, :mod:`units`
- OpenAP integration: :mod:`openap_adapter`, :mod:`atmosphere`
- database access: :mod:`airport_lookup`, :mod:`persistence`
- orchestration: :mod:`planner`

Results are model estimates for cost analysis, not dispatch fuel plans.
"""
