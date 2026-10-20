"""Part 5 acceptance checks on the A320 FRA->CDG example (offline fixture database)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import find_route_case, load_saved_case
from aircraft_cost_model.analytics.metrics import DistanceBasis, DistanceInput, unit_metrics
from aircraft_cost_model.analytics.scenarios import base_from_saved
from aircraft_cost_model.analytics.sensitivity import one_way
from aircraft_cost_model.analytics.validation import validate_estimate
from aircraft_cost_model.fullcost.scenario import load_scenario
from aircraft_cost_model.models import AircraftType, FullCostEstimate
from conftest import REPO_ROOT, SCENARIOS

GC = DistanceInput(DistanceBasis.GREAT_CIRCLE)


def test_a320_example_acceptance(analytics_db):
    engine, ids = analytics_db
    with Session(engine) as session:
        case = load_saved_case(session, ids["full"])
        s = case.summary
        # 1-5: Part 3/4 values unchanged; complete totals unavailable
        assert s.components["fuel"].amount == Decimal("1788.05")
        assert s.components["fuel"].source_type.value == "public_market_benchmark"
        assert (s.coc[0], s.toc[0], s.total[0]) == (Decimal("3946.08"), Decimal("4844.31"), Decimal("5443.13"))
        assert s.coc[1] is s.toc[1] is s.total[1] is None
        # 6-7: unit metrics are labelled partial; no RTNM without explicit revenue payload
        metrics = unit_metrics(case, GC)
        assert all(m.label.startswith("Partial") for m in metrics.metrics
                   if m.cost_measure == "calculated_subtotal" and m.cost_basis in ("coc", "toc", "total_costs"))
        assert metrics.traffic.rtnm is None
        assert all(m.metric_value is None for m in metrics.metrics if m.denominator_unit == "revenue_tonne_nm")
        assert metrics.operational_validity == "calculated_limits_unverified"
        assert metrics.source_quality == "mixed: explicit_user_assumption, public_market_benchmark"


def test_sensitivity_does_not_overwrite_base(analytics_db):
    engine, ids = analytics_db
    with engine.connect() as conn:
        before = {t: conn.execute(text(f"SELECT * FROM {t} ORDER BY 1")).all()
                  for t in ("full_cost_estimate", "full_cost_component", "cost_scenario", "cost_component")}
    with Session(engine) as session:
        base = base_from_saved(session, ids["full"], GC)
        result = one_way(session, base, "fuel_price", "percent", [Decimal(-20), Decimal(20)])
        assert result.rows[1].outputs["fuel"] == Decimal("2145.66")
        assert session.get(FullCostEstimate, ids["full"]).cash_operating_subtotal == Decimal("3946.08")
    with engine.connect() as conn:
        after = {t: conn.execute(text(f"SELECT * FROM {t} ORDER BY 1")).all() for t in before}
    assert after == before


def test_unsupported_freighters_remain_unsupported(analytics_db):
    engine, _ = analytics_db
    scenario = load_scenario(SCENARIOS / "example_owned_aircraft.json")
    with Session(engine) as session:
        for code in ("A330-200F", "B777F", "B767-300F", "B747-400F", "A321P2F"):
            assert not session.scalar(select(AircraftType).where(AircraftType.aircraft_code == code)).openap_supported
            case = find_route_case(session, code, "FRA", "JFK", date(2025, 1, 15), "EUR", scenario)
            assert case.origin == "unsupported" and case.summary is None
            assert unit_metrics(case, GC).cost_coverage == "unsupported"


def test_validation_of_example(analytics_db):
    engine, ids = analytics_db
    with Session(engine) as session:
        result = validate_estimate(session, ids["full"], REPO_ROOT / "data" / "reference" / "bts_aircraft_type_mapping.csv")
    statuses = {c.name: c.status for c in result.checks}
    assert statuses["reproducibility"] == "pass" and statuses["fuel_conversion_recheck"] == "pass"
    assert statuses["no_missing_as_zero"] == "pass" and statuses["ownership_mode_consistency"] == "pass"
    assert statuses["validity_carried_forward"] == "pass" and statuses["historical_pricing_rule"] == "pass"
    assert result.status == "warn"  # limits unverified + illustrative assumptions; no failed check
    assert all(c.comparability == "not_comparable" for c in result.benchmark_comparisons)  # no benchmarks loaded
