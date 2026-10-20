"""End-to-end variable costs for the saved A320 FRA->CDG estimate (offline fixtures, temporary DB).

The A320 is a passenger aircraft directly supported by OpenAP; these results are
not cargo-aircraft costs.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aircraft_cost_model.costs.calculator import VariableCostRequest, calculate_variable_costs
from aircraft_cost_model.costs.coverage import ComponentName, ComponentStatus
from aircraft_cost_model.costs.exceptions import FlightEstimateNotFoundError, LegacyFuelAccountingError
from aircraft_cost_model.costs.fuel_cost import US_GALLON_LITRES
from aircraft_cost_model.costs.handling_cost import HandlingAssumption
from aircraft_cost_model.costs.navigation_cost import ZoneSegment
from aircraft_cost_model.costs.persistence import save_variable_cost_estimate
from aircraft_cost_model.database import create_db_engine
from aircraft_cost_model.ingestion.airport_tariffs import load_airport_tariffs
from aircraft_cost_model.models import AircraftType, CostComponent, FlightEstimate, VariableCostEstimate
from conftest import FRA_CONTEXT, write_synthetic_tariff

PRICING = date(2025, 1, 15)
ZONES = (ZoneSegment("GERMANY", Decimal("170"), 1, 0), ZoneSegment("FRANCE", Decimal("290"), 0, 1))


@pytest.fixture
def cost_engine(cost_db):
    engine = create_db_engine(cost_db)
    yield engine
    engine.dispose()


CERT_MTOW = Decimal("78000")  # stands in for a user-supplied AFM certificated MTOW in these tests


def run(engine, **kw):
    with Session(engine) as session:
        return calculate_variable_costs(session, VariableCostRequest(flight_estimate_id=1, pricing_date=PRICING, **kw))


def test_a320_fra_cdg_fuel_benchmark_conversion(cost_engine):
    result = run(cost_engine)
    fuel = result.component(ComponentName.FUEL)
    with Session(cost_engine) as session:
        estimate = session.get(FlightEstimate, 1)
        block_kg = Decimal(str(estimate.block_fuel_kg))
        density = Decimal(str(estimate.fuel_density_kg_per_l))
    expected = (block_kg / density / US_GALLON_LITRES * Decimal("2.463") / Decimal("1.03")).quantize(Decimal("0.01"))
    assert fuel.status == ComponentStatus.CALCULATED_BENCHMARK and fuel.amount == expected
    assert fuel.observation_date == PRICING
    assert result.flight.fuel_accounting_basis == "v2"


def test_navigation_unavailable_without_zones(cost_engine):
    nav = run(cost_engine).component(ComponentName.NAVIGATION)
    assert nav.status == ComponentStatus.UNAVAILABLE_ROUTE_GEOMETRY and nav.amount is None


def test_navigation_with_explicit_zones_requires_certificated_mtow(cost_engine):
    missing = run(cost_engine, nav_segments=ZONES).component(ComponentName.NAVIGATION)
    assert missing.status == ComponentStatus.MISSING_REQUIRED_INPUT
    nav = run(cost_engine, nav_segments=ZONES, certificated_mtow_kg=CERT_MTOW).component(ComponentName.NAVIGATION)
    assert nav.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF and nav.amount == Decimal("457.50")  # synthetic rates
    assert not nav.partial_scope
    scenario = run(cost_engine, nav_segments=ZONES, use_type_level_mtow_scenario=True).component(ComponentName.NAVIGATION)
    assert scenario.status == ComponentStatus.CALCULATED_ASSUMPTION


def test_terminal_navigation_departure_charged_arrival_zero(cost_engine):
    terminal = run(cost_engine, certificated_mtow_kg=CERT_MTOW).component(ComponentName.TERMINAL_NAVIGATION)
    assert terminal.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF
    assert terminal.amount == Decimal("411.00")  # synthetic FRA zone rate 300.00 x 1.37; CDG arrival 0 by rule
    parts = {p["part"]: p for p in terminal.breakdown}
    assert parts["CDG arrival"]["amount"] == "0.00" and parts["FRA departure"]["amount"] == "411.00"
    assert run(cost_engine).component(ComponentName.TERMINAL_NAVIGATION).status == ComponentStatus.MISSING_REQUIRED_INPUT


def test_terminal_pending_review_rate_is_na(cost_engine):
    with Session(cost_engine) as session:  # 2026 synthetic Germany terminal rate is pending_review
        result = calculate_variable_costs(session, VariableCostRequest(1, date(2026, 6, 1), certificated_mtow_kg=CERT_MTOW))
    terminal = result.component(ComponentName.TERMINAL_NAVIGATION)
    assert terminal.status == ComponentStatus.UNAVAILABLE_PUBLIC_TARIFF and terminal.amount is None
    assert any("pending_review" in w for w in terminal.warnings)


def test_landing_missing_parameter_with_tariff_loaded(cost_engine, tmp_path):
    write_synthetic_tariff(tmp_path / "tariffs", "EDDF")
    write_synthetic_tariff(tmp_path / "tariffs", "LFPG")
    load_airport_tariffs(cost_engine, tmp_path / "tariffs")
    missing = run(cost_engine, certificated_mtow_kg=CERT_MTOW,
                  tariff_context={"FRA": {k: v for k, v in FRA_CONTEXT.items() if k != "noise_category_takeoff"},
                                  "CDG": FRA_CONTEXT})
    landing = missing.component(ComponentName.LANDING)
    assert landing.status == ComponentStatus.MISSING_REQUIRED_INPUT and landing.amount is None
    assert "noise_category_takeoff" in landing.missing_inputs
    both = run(cost_engine, certificated_mtow_kg=CERT_MTOW,
               tariff_context={"FRA": FRA_CONTEXT, "CDG": FRA_CONTEXT}).component(ComponentName.LANDING)
    assert both.status == ComponentStatus.CALCULATED_PUBLIC_TARIFF and both.amount > 0


def test_complete_only_when_every_component_calculated(cost_engine, tmp_path):
    write_synthetic_tariff(tmp_path / "t", "EDDF")
    write_synthetic_tariff(tmp_path / "t", "LFPG")
    load_airport_tariffs(cost_engine, tmp_path / "t")
    kwargs = dict(nav_segments=ZONES, certificated_mtow_kg=CERT_MTOW,
                  tariff_context={"FRA": FRA_CONTEXT, "CDG": FRA_CONTEXT})
    partial = run(cost_engine, **kwargs)
    assert len(partial.summary.calculated) == 4 and partial.summary.complete_variable_cost is None
    complete = run(cost_engine, **kwargs, handling_assumptions={"FRA": HandlingAssumption(Decimal("600"), "EUR"),
                                                                 "CDG": HandlingAssumption(Decimal("700"), "EUR")})
    assert complete.summary.is_complete and complete.summary.coverage_status == "complete"
    assert complete.summary.complete_variable_cost == complete.summary.calculated_subtotal
    assert complete.summary.counts_by_category()["assumption"] == 1  # handling is a labelled assumption
    assert complete.component(ComponentName.GROUND_HANDLING).status == ComponentStatus.CALCULATED_ASSUMPTION
    assert complete.summary.unresolved_interpretations  # rounding interpretations are surfaced


def test_legacy_v1_and_missing_estimate_rejected(cost_engine):
    with Session(cost_engine) as session, session.begin():
        session.get(FlightEstimate, 1).fuel_accounting_basis = "v1"
    with pytest.raises(LegacyFuelAccountingError):
        run(cost_engine)
    with Session(cost_engine) as session, pytest.raises(FlightEstimateNotFoundError):
        calculate_variable_costs(session, VariableCostRequest(99, PRICING))


def test_unsupported_freighter_not_priced(cost_engine):
    with Session(cost_engine) as session, session.begin():
        freighter = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == "B777F"))
        session.get(FlightEstimate, 1).aircraft_type_id = freighter.aircraft_type_id
    result = run(cost_engine)
    assert all(c.status == ComponentStatus.UNSUPPORTED_AIRCRAFT and c.amount is None for c in result.summary.components)


def test_missing_fuel_price_for_date(cost_engine):
    with Session(cost_engine) as session:
        result = calculate_variable_costs(session, VariableCostRequest(1, date(2024, 12, 1)))
    assert result.component(ComponentName.FUEL).status == ComponentStatus.UNAVAILABLE_PRICE


def test_deterministic_results(cost_engine):
    a = run(cost_engine, nav_segments=ZONES, certificated_mtow_kg=CERT_MTOW)
    b = run(cost_engine, nav_segments=ZONES, certificated_mtow_kg=CERT_MTOW)
    assert a.input_hash == b.input_hash
    assert [c.to_dict() for c in a.summary.components] == [c.to_dict() for c in b.summary.components]


def test_persistence_precision_and_provenance(cost_engine):
    result = run(cost_engine, nav_segments=ZONES, certificated_mtow_kg=CERT_MTOW)
    estimate_id = save_variable_cost_estimate(cost_engine, result)
    with Session(cost_engine) as session:
        saved = session.get(VariableCostEstimate, estimate_id)
        assert saved.calculated_subtotal == result.summary.calculated_subtotal
        assert isinstance(saved.calculated_subtotal, Decimal)
        assert saved.complete_variable_cost is None and saved.coverage_status == "partial"
        components = {c.component_name: c for c in saved.components}
        assert components["navigation"].amount == Decimal("457.50")
        assert components["terminal_navigation"].amount == Decimal("411.00")
        assert components["landing"].amount is None and components["landing"].status == "unavailable_public_tariff"
        fuel = components["fuel"]
        assert fuel.source_id is not None and fuel.pricing_observation_date == PRICING
        assert any(a["name"] == "fuel_density_kg_per_l" for a in json.loads(fuel.assumptions_json))
        assert any(b.get("step") == "price" for b in json.loads(fuel.breakdown_json))
    with cost_engine.connect() as conn:
        raw = conn.execute(text("SELECT amount FROM cost_component WHERE component_name = 'navigation'")).scalar_one()
    assert raw == "457.50"  # stored as exact decimal text, not a binary float
