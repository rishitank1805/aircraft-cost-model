"""Taxonomy aggregation, completeness and the three independent dimensions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.costs.coverage import ComponentResult, ComponentStatus, SourceType
from aircraft_cost_model.fullcost.aggregate import COMPONENT_CATEGORY, Category, FullCostSummary, SourceQuality

D = date(2025, 1, 15)


def calc(name, amount, source=SourceType.PUBLIC_TARIFF):
    status = ComponentStatus.CALCULATED_ASSUMPTION if source == SourceType.USER_ASSUMPTION else ComponentStatus.CALCULATED_PUBLIC_TARIFF
    return ComponentResult(name, status, "EUR", D, Decimal(amount), source)


def na(name):
    return ComponentResult(name, ComponentStatus.NOT_APPLICABLE, "EUR", D)


def missing(name):
    return ComponentResult(name, ComponentStatus.MISSING_REQUIRED_INPUT, "EUR", D, missing_inputs=[name])


def summary(overrides=None, validity="calculated_limits_unverified"):
    components = {n: calc(n, "10.00") for n in COMPONENT_CATEGORY}
    components.update(overrides or {})
    return FullCostSummary(components, "EUR", validity)


def test_complete_scenario_totals():
    s = summary()
    assert s.category(Category.DIRECT_VARIABLE).complete_amount == Decimal("90.00")  # 9 components
    assert s.category(Category.DIRECT_FIXED).complete_amount == Decimal("30.00")
    assert s.category(Category.INDIRECT).complete_amount == Decimal("30.00")
    assert s.coc[1] == Decimal("150.00") and s.toc[1] == Decimal("160.00") and s.total[1] == Decimal("170.00")
    assert s.cost_coverage_status == "complete"


def test_not_applicable_does_not_block_completeness():
    s = summary({"operating_lease": na("operating_lease"), "cargo_sales": na("cargo_sales"),
                 "financing_interest": na("financing_interest")})
    assert s.category(Category.DIRECT_FIXED).not_applicable_components == ("operating_lease",)
    assert s.category(Category.FINANCING).complete_amount == Decimal("0.00")  # wholly not applicable
    assert s.category(Category.FINANCING).calculated_subtotal is None
    assert s.total[1] == Decimal("140.00") and s.cost_coverage_status == "complete"


def test_missing_is_never_zero():
    s = summary({"landing": missing("landing"), "depreciation": missing("depreciation")})
    dv = s.category(Category.DIRECT_VARIABLE)
    assert dv.calculated_subtotal == Decimal("80.00") and dv.complete_amount is None
    assert dv.missing_components == ("landing",)
    assert s.coc == (Decimal("140.00"), None, ("landing",))
    assert s.toc[1] is None and s.toc[2] == ("landing", "depreciation")
    assert s.total[0] == Decimal("150.00") and s.total[1] is None
    assert s.cost_coverage_status == "incomplete"
    assert s.coverage_counts()["missing_required_input"] == 2


def test_partial_scope_blocks_completeness():
    partial = calc("ground_handling", "5.00")
    partial = ComponentResult("ground_handling", partial.status, "EUR", D, partial.amount, partial.source_type,
                              partial_scope=True)
    s = summary({"ground_handling": partial})
    assert s.category(Category.DIRECT_VARIABLE).calculated_subtotal == Decimal("85.00")
    assert s.coc[1] is None


def test_failed_validation_dominates_coverage():
    failed = ComponentResult("insurance", ComponentStatus.FAILED_VALIDATION, "EUR", D, warnings=["overlap"])
    assert summary({"insurance": failed}).cost_coverage_status == "failed_validation"


def test_dimensions_are_independent():
    for validity in ("calculated", "calculated_limits_unverified"):
        s = summary(validity=validity)
        assert s.cost_coverage_status == "complete" and s.operational_validity == validity
        assert s.source_quality_summary == SourceQuality.OBSERVED_PUBLIC_DATA.value
    assumed = summary({"insurance": calc("insurance", "1.00", SourceType.USER_ASSUMPTION)})
    assert assumed.cost_coverage_status == "complete"
    assert assumed.source_quality_summary == "mixed: explicit_user_assumption, observed_public_data"


def test_component_set_and_currency_enforced():
    components = {n: calc(n, "1.00") for n in COMPONENT_CATEGORY}
    del components["fuel"]
    with pytest.raises(ValueError, match="mismatch"):
        FullCostSummary(components, "EUR", "calculated")
    components["fuel"] = ComponentResult("fuel", ComponentStatus.CALCULATED_PUBLIC_TARIFF, "USD", D, Decimal(1),
                                         SourceType.PUBLIC_MARKET_BENCHMARK)
    with pytest.raises(ValueError, match="USD"):
        FullCostSummary(components, "EUR", "calculated")
