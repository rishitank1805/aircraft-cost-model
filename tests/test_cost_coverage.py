"""Aggregation, coverage, statuses and Decimal arithmetic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.costs.coverage import ComponentResult, ComponentStatus, SourceType, VariableCostSummary
from aircraft_cost_model.costs.exceptions import CurrencyMismatchError

D = date(2025, 1, 15)


def comp(name, status, amount=None, currency="EUR", partial=False, zero=False):
    return ComponentResult(name, status, currency, D, None if amount is None else Decimal(amount),
                           SourceType.PUBLIC_TARIFF, partial_scope=partial, zero_by_tariff_rule=zero)


CALC = ComponentStatus.CALCULATED_PUBLIC_TARIFF


def test_all_components_calculated_complete():
    s = VariableCostSummary(D, "EUR", [comp("fuel", ComponentStatus.CALCULATED_BENCHMARK, "1788.05"),
                                       comp("navigation", CALC, "457.77"), comp("landing", CALC, "380.19"),
                                       comp("ground_handling", ComponentStatus.CALCULATED_ASSUMPTION, "900.00")])
    assert s.is_complete and s.coverage_status == "complete"
    assert s.complete_variable_cost == s.calculated_subtotal == Decimal("3526.01")


def test_one_unavailable_gives_partial_subtotal_only():
    s = VariableCostSummary(D, "EUR", [comp("fuel", ComponentStatus.CALCULATED_BENCHMARK, "1788.05"),
                                       comp("navigation", ComponentStatus.UNAVAILABLE_ROUTE_GEOMETRY),
                                       comp("landing", CALC, "380.19"), comp("ground_handling", CALC, "10.00")])
    assert s.calculated_subtotal == Decimal("2178.24")
    assert s.complete_variable_cost is None and s.coverage_status == "partial"
    assert s.coverage_label() == "3 of 4 applicable components calculated"


def test_multiple_unavailable_and_none_calculated():
    s = VariableCostSummary(D, "EUR", [comp("fuel", ComponentStatus.UNAVAILABLE_PRICE),
                                       comp("navigation", ComponentStatus.UNAVAILABLE_ROUTE_GEOMETRY)])
    assert s.calculated_subtotal is None and s.coverage_status == "none"
    assert s.counts_by_category()["unavailable"] == 2


def test_partial_scope_prevents_complete():
    s = VariableCostSummary(D, "EUR", [comp("fuel", CALC, "1"), comp("navigation", CALC, "2", partial=True)])
    assert not s.is_complete and s.complete_variable_cost is None


def test_genuine_zero_and_not_applicable():
    zero = comp("landing", CALC, "0", zero=True)
    s = VariableCostSummary(D, "EUR", [comp("fuel", CALC, "5"), zero, comp("ground_handling", ComponentStatus.NOT_APPLICABLE)])
    assert s.is_complete and s.calculated_subtotal == Decimal("5")
    assert s.counts_by_category()["not_applicable"] == 1
    with pytest.raises(ValueError, match="zero amount"):
        comp("landing", CALC, "0")


def test_missing_cost_cannot_be_zero_or_carry_amount():
    with pytest.raises(ValueError):
        comp("navigation", ComponentStatus.UNAVAILABLE_ROUTE_GEOMETRY, "0")
    with pytest.raises(ValueError):
        comp("fuel", CALC)
    with pytest.raises(TypeError):
        ComponentResult("fuel", CALC, "EUR", D, 1.5)  # float rejected


def test_currency_consistency():
    with pytest.raises(CurrencyMismatchError):
        VariableCostSummary(D, "EUR", [comp("fuel", CALC, "1", currency="USD")])


def test_decimal_arithmetic_exact():
    s = VariableCostSummary(D, "EUR", [comp("fuel", CALC, "0.10"), comp("landing", CALC, "0.20")])
    assert s.calculated_subtotal == Decimal("0.30")  # binary floats would give 0.30000000000000004
