"""EUROCONTROL route charges (CoA Arts. 3-7) with SYNTHETIC unit rates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.costs.coverage import ComponentStatus
from aircraft_cost_model.costs.currency import StaticRateProvider, round_money
from aircraft_cost_model.costs.exceptions import CostInputError
from aircraft_cost_model.costs.navigation_cost import (
    FORMULA_POW_07,
    MTOW_CERTIFICATED,
    MTOW_TYPE_SCENARIO,
    MtowBasis,
    ZoneRate,
    ZoneSegment,
    calculate_navigation_charge,
    distance_factor,
    validate_segments,
    weight_factor,
)

D = date(2025, 1, 15)
SYN = "SYNTHETIC"
RATES = {
    "GERMANY": ZoneRate("GERMANY", "Germany", Decimal("100.00"), "EUR", date(2025, 1, 1), date(2025, 12, 31), 1, SYN, "verified_against_source"),
    "FRANCE": ZoneRate("FRANCE", "France", Decimal("80.00"), "EUR", date(2025, 1, 1), date(2025, 12, 31), 1, SYN, "verified_against_source"),
}
SEGMENTS = [ZoneSegment("GERMANY", Decimal("170"), 1, 0), ZoneSegment("FRANCE", Decimal("290"), 0, 1)]
CERT = MtowBasis(Decimal("78000"), MTOW_CERTIFICATED, "test certificated")


def _charge(**kw):
    args = dict(segments=SEGMENTS, rates=RATES, mtow=CERT, reporting_currency="EUR", pricing_date=D,
                fx=StaticRateProvider({"USD": (Decimal("1.03"), D)}))
    args.update(kw)
    return calculate_navigation_charge(**args)


@pytest.mark.parametrize("mtow_kg, tonnes, p, p_truncated", [
    ("78000", "78.0", "1.25", "1.24"),       # sqrt(1.56) = 1.2490: interpretations differ
    ("50000", "50.0", "1.00", "1.00"),
    ("347450", "347.5", "2.64", "2.63"),     # 347.45 t -> 347.5 (half up) or 347.4 (truncated)
    ("5700", "5.7", "0.34", "0.33"),
])
def test_weight_factor_both_interpretations(mtow_kg, tonnes, p, p_truncated):
    wf = weight_factor(Decimal(mtow_kg))
    assert (wf.mtow_tonnes, wf.value, wf.alternative_truncated) == (Decimal(tonnes), Decimal(p), Decimal(p_truncated))


def test_terminal_weight_formula_power_07():
    wf = weight_factor(Decimal("78000"), FORMULA_POW_07)
    assert wf.value == Decimal("1.37")  # 1.56 ** 0.7 = 1.3652 -> 1.37 half up
    assert wf.alternative_truncated == Decimal("1.36")


def test_distance_factor_deducts_20km_per_takeoff_and_landing_unrounded():
    assert distance_factor(ZoneSegment("X", Decimal("170"), 1, 0)) == (Decimal(150), Decimal("1.5"))
    assert distance_factor(ZoneSegment("X", Decimal("300.37"), 1, 1)) == (Decimal("260.37"), Decimal("2.6037"))
    assert distance_factor(ZoneSegment("X", Decimal("15"), 1, 0))[0] == 0


def test_multiple_zones_certificated_mtow():
    result = _charge()
    assert result.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF and not result.partial_scope
    assert result.amount == Decimal("457.50")  # 1.5*100*1.25 + 2.7*80*1.25
    rounding = result.breakdown[-1]
    assert rounding["alternative_if_truncated"] == "453.84"  # p = 1.24
    names = {a.name for a in result.assumptions}
    assert {"unresolved_interpretation_rounding", "unresolved_interpretation_distance_rounding",
            "unresolved_interpretation_rate_validity"} <= names
    assert _charge(reporting_currency="USD").amount == round_money(Decimal("457.50") * Decimal("1.03"))  # 471.225 -> 471.23 half up


def test_mtow_required_for_official_calculation():
    missing = _charge(mtow=MtowBasis.resolve(None, Decimal("78000"), False))
    assert missing.status == ComponentStatus.MISSING_REQUIRED_INPUT and "certificated MTOW" in missing.missing_inputs
    scenario = _charge(mtow=MtowBasis.resolve(None, Decimal("78000"), True))
    assert scenario.status == ComponentStatus.CALCULATED_ASSUMPTION and scenario.amount == Decimal("457.50")
    assert any("Scenario" in w for w in scenario.warnings)
    assert MtowBasis.resolve(Decimal("79000"), Decimal("78000"), True).basis == MTOW_CERTIFICATED
    assert MtowBasis.resolve(None, Decimal("78000"), True).basis == MTOW_TYPE_SCENARIO


def test_missing_geometry_and_rates_unavailable():
    assert _charge(segments=[]).status == ComponentStatus.UNAVAILABLE_ROUTE_GEOMETRY
    missing = _charge(rates={"GERMANY": RATES["GERMANY"], "FRANCE": None})
    assert missing.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF and missing.amount is None
    pending = dict(RATES, FRANCE=ZoneRate("FRANCE", "France", Decimal("80"), "EUR", date(2025, 1, 1), None, 1, SYN,
                                          "pending_review"))
    unverified = _charge(rates=pending)
    assert unverified.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF
    assert any("pending review" in w for w in unverified.warnings)


def test_segment_validation():
    validate_segments(SEGMENTS, Decimal("447.8"))
    with pytest.raises(CostInputError, match="great circle"):
        validate_segments(SEGMENTS, Decimal("600"))
    with pytest.raises(CostInputError, match="one take-off"):
        validate_segments([ZoneSegment("GERMANY", Decimal("460"), 0, 1)], None)
    with pytest.raises(CostInputError, match="once"):
        validate_segments(SEGMENTS + [ZoneSegment("GERMANY", Decimal("1"), 0, 0)], None)
    with pytest.raises(CostInputError):
        MtowBasis.resolve(Decimal("-1"), None, False)
