"""Unit metrics: per block hour / NM / cycle / RTNM / ATNM, partial labels, payload and denominator rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.analytics.cases import AnalyticsInputError, CostCase, FlightFacts
from aircraft_cost_model.analytics.metrics import (
    DistanceBasis,
    DistanceInput,
    PayloadInput,
    unit_metrics,
)
from aircraft_cost_model.costs.coverage import ComponentResult, ComponentStatus, SourceType
from aircraft_cost_model.fullcost.aggregate import COMPONENT_CATEGORY, FullCostSummary

D = date(2025, 1, 15)
GC = DistanceInput(DistanceBasis.GREAT_CIRCLE)
ROUTE = DistanceInput(DistanceBasis.MODELLED_ROUTE)


def facts(block="2", gc="200", route="220", payload_kg="10000") -> FlightFacts:
    return FlightFacts(1, "A320", True, "FRA", "CDG", Decimal(block), Decimal("1.5"), Decimal(gc), Decimal(route),
                       "great_circle_x_factor", Decimal("2271.5"), Decimal(payload_kg), "calculated_limits_unverified", "v2")


def comp(name, amount=None, status=None, source=SourceType.PUBLIC_TARIFF, breakdown=None):
    if amount is None:
        return ComponentResult(name, status or ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF, "EUR", D)
    return ComponentResult(name, status or ComponentStatus.CALCULATED_PUBLIC_TARIFF, "EUR", D, Decimal(amount), source,
                           breakdown=breakdown or [])


def case(overrides=None, flight_type="cargo", f=None) -> CostCase:
    components = {n: comp(n, "10.00") for n in COMPONENT_CATEGORY}  # 17 x 10 = DV 90, DF 30, ind 30, nc 10, fin 10
    components.update(overrides or {})
    summary = FullCostSummary(components, "EUR", "calculated_limits_unverified")
    return CostCase("test", f or facts(), summary, D, "EUR", flight_type, "owned")


def test_cost_per_block_hour_nm_and_cycle_complete():
    r = unit_metrics(case(), GC)
    coc = r.metric("coc_per_block_hour")
    assert coc.metric_value == Decimal("75") and coc.label == "Calculated COC per block hour"  # 150 / 2
    assert r.metric("coc_per_block_hour", "complete_total").metric_value == Decimal("75")
    assert r.metric("coc_per_block_hour", "complete_total").label == "Complete COC per block hour"
    assert r.metric("total_costs_per_nautical_mile").metric_value == Decimal("0.85")  # 170 / 200
    assert r.metric("toc_per_flight_cycle").metric_value == Decimal("160")
    assert r.metric("direct_variable_per_block_hour").metric_unit == "EUR/block_hour"
    assert r.cost_coverage == "complete"


def test_distance_basis_is_explicit_and_never_mixed():
    assert unit_metrics(case(), ROUTE).metric("coc_per_nautical_mile").metric_value == Decimal(150) / Decimal(220)
    m = unit_metrics(case(), ROUTE).metric("coc_per_nautical_mile")
    assert m.denominator_basis.startswith("modelled_route")
    actual = DistanceInput(DistanceBasis.ACTUAL_FLOWN, Decimal("250"), "ADS-B track (example)")
    assert unit_metrics(case(), actual).metric("coc_per_nautical_mile").metric_value == Decimal("0.6")
    with pytest.raises(AnalyticsInputError, match="reference"):
        unit_metrics(case(), DistanceInput(DistanceBasis.ACTUAL_FLOWN, Decimal("250")))
    with pytest.raises(AnalyticsInputError, match="actual_flown"):
        unit_metrics(case(), DistanceInput(DistanceBasis.GREAT_CIRCLE, Decimal("250")))


def test_zero_distance_is_undefined():
    m = unit_metrics(case(), DistanceInput(DistanceBasis.ACTUAL_FLOWN, Decimal(0), "test")).metric("coc_per_nautical_mile")
    assert m.metric_status == "undefined" and m.metric_value is None


def test_invalid_block_hours_rejected():
    with pytest.raises(AnalyticsInputError, match="block hours"):
        unit_metrics(case(f=facts(block="0")), GC)


def test_rtnm_and_cost_per_rtnm():
    r = unit_metrics(case(), GC, PayloadInput(Decimal("8"), "user_assumption", "contract manifest"))
    assert r.traffic.rtnm == Decimal("1600")  # 8 t x 200 NM
    assert r.metric("coc_per_revenue_tonne_nm").metric_value == Decimal(150) / Decimal(1600)
    assert "8 t" in r.metric("coc_per_revenue_tonne_nm").payload_basis


def test_missing_payload_makes_rtnm_unavailable():
    r = unit_metrics(case(), GC)
    m = r.metric("coc_per_revenue_tonne_nm")
    assert r.traffic.rtnm is None and m.metric_value is None and m.metric_status == "unavailable"
    assert m.coverage_status == "missing_required_input"
    assert any("not revenue cargo" in w for w in r.warnings)


def test_zero_payload_is_undefined_not_zero_or_infinite():
    r = unit_metrics(case(), GC, PayloadInput(Decimal(0)))
    assert r.traffic.rtnm == 0
    m = r.metric("coc_per_revenue_tonne_nm")
    assert m.metric_status == "undefined" and m.metric_value is None


def test_payload_rules():
    with pytest.raises(AnalyticsInputError, match="hypothetical"):
        unit_metrics(case(flight_type="passenger"), GC, PayloadInput(Decimal("5")))
    r = unit_metrics(case(flight_type="passenger"), GC, PayloadInput(Decimal("5"), hypothetical_cargo=True))
    assert any("HYPOTHETICAL" in w for w in r.warnings) and "HYPOTHETICAL" in r.traffic.payload_basis
    with pytest.raises(AnalyticsInputError, match="exceeds"):
        unit_metrics(case(), GC, PayloadInput(Decimal("10.5")))  # modelled payload is 10 t
    with pytest.raises(AnalyticsInputError, match="negative"):
        unit_metrics(case(), GC, PayloadInput(Decimal("-1")))
    with pytest.raises(AnalyticsInputError, match="source_type"):
        unit_metrics(case(), GC, PayloadInput(Decimal("1"), "guess"))


def test_atnm_and_load_factor_are_not_rtnm():
    r = unit_metrics(case(), GC, PayloadInput(Decimal("6"), available_tonnes=Decimal("8"), available_reference="x"))
    assert r.traffic.atnm == Decimal("1600") and r.traffic.rtnm == Decimal("1200")
    assert r.traffic.load_factor == Decimal("0.75")
    assert r.metric("coc_per_available_tonne_nm").metric_value != r.metric("coc_per_revenue_tonne_nm").metric_value
    assert unit_metrics(case(), GC).metric("coc_per_available_tonne_nm").metric_value is None
    with pytest.raises(AnalyticsInputError, match="exceeds the stated available"):
        unit_metrics(case(), GC, PayloadInput(Decimal("9"), available_tonnes=Decimal("8")))


def test_partial_coverage_is_labelled_partial():
    r = unit_metrics(case({"landing": comp("landing")}), GC)
    partial = r.metric("coc_per_block_hour")
    assert partial.label == "Partial COC per block hour" and partial.coverage_status == "partial"
    assert partial.metric_value == Decimal("70") and partial.components_missing == ("landing",)
    complete = r.metric("coc_per_block_hour", "complete_total")
    assert complete.metric_value is None and complete.metric_status == "unavailable"
    assert any("missing landing" in w for w in complete.warnings)
    assert r.metric("direct_fixed_per_block_hour").coverage_status == "complete"  # unaffected category
    assert r.cost_coverage == "partial"


def test_failed_validation_is_calculation_error():
    failed = ComponentResult("insurance", ComponentStatus.FAILED_VALIDATION, "EUR", D, warnings=["overlap"])
    m = unit_metrics(case({"insurance": failed}), GC).metric("coc_per_block_hour")
    assert m.coverage_status == "calculation_error"


def test_currency_conversion_source_recorded():
    step = {"step": "USD -> EUR", "series_key": "EXR.D.USD.EUR.SP00.A", "rate": "1.03", "observation_date": "2025-01-15"}
    r = unit_metrics(case({"fuel": comp("fuel", "10.00", breakdown=[step])}), GC)
    assert "EXR.D.USD.EUR.SP00.A rate 1.03" in r.metric("coc_per_block_hour").fx_basis
    assert r.metric("indirect_per_block_hour").fx_basis.startswith("no currency conversion")


def test_unsupported_case_has_no_metrics():
    unsupported = CostCase("B777F FRA-JFK", None, None, None, None, None, None, origin="unsupported",
                           aircraft_code="B777F", warnings=["no supported model"])
    r = unit_metrics(unsupported, GC)
    assert r.metrics == [] and r.cost_coverage == "unsupported"


def test_exact_decimal_quotients_without_rounding():
    r = unit_metrics(case(f=facts(block="1.19764")), GC)
    value = r.metric("coc_per_block_hour").metric_value
    assert value == Decimal(150) / Decimal("1.19764") and len(str(value).replace(".", "")) > 20
