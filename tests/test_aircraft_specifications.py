"""Part 6 specification loading: provenance, units, freighter rules, idempotence."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.ingestion import aircraft_specs as specs
from aircraft_cost_model.models import AircraftSpecification, AircraftType


def values(engine, code, key):
    with Session(engine) as s:
        aircraft = s.scalar(select(AircraftType).where(AircraftType.aircraft_code == code))
        return s.scalars(select(AircraftSpecification).where(AircraftSpecification.aircraft_type_id == aircraft.aircraft_type_id,
                                                            AircraftSpecification.spec_key == key)).all()


def test_all_sources_load_and_are_idempotent(explorer_db):
    engine, ids = explorer_db
    assert all(r[0] > 0 for r in ids["report"].values())
    assert specs.load_engine_specs(engine)[0] == 0
    assert specs.load_faa_acd(engine, ids["faa_snapshot"])[0] == 0
    assert specs.load_openap_specs(engine, ids["raw"])[0] == 0


def test_units_converted_exactly_and_originals_kept(explorer_db):
    engine, _ = explorer_db
    mtow = next(v for v in values(engine, "A320", "mtow_kg") if v.source_type == "published_specification")
    assert mtow.original_value == "171961" and mtow.original_unit == "lb"
    assert mtow.value_decimal == Decimal("171961") * Decimal("0.45359237")
    length = values(engine, "A320", "length_m")[0]
    assert length.value_decimal == Decimal("123.3") * Decimal("0.3048") and length.original_unit == "ft"
    thrust = values(engine, "A320", "rated_thrust_kn")[0]
    assert thrust.original_unit == "N" and thrust.source_type == "engine_databank"


def test_openap_fuselage_height_is_not_overall_height(explorer_db):
    engine, _ = explorer_db
    fuselage = values(engine, "A320", "fuselage_height_m")[0]
    overall = values(engine, "A320", "height_m")
    assert "NOT the overall" in fuselage.notes and fuselage.verification_status == "unverified_model_value"
    assert [v.source_type for v in overall] == ["published_specification"]  # only the FAA tail height


def test_passenger_rows_never_used_for_freighters(explorer_db):
    engine, _ = explorer_db
    assert not [v for v in values(engine, "B747-400F", "length_m")]  # FAA B744 row is the passenger 747-400
    assert not [v for v in values(engine, "A330-200F", "wheelbase_m") if v.source_type == "published_specification"
                and "FAA" in (v.source_reference or "")]
    shared = values(engine, "B777F", "length_m")
    assert shared and all(v.verification_status == "shared_designator_row" for v in shared)
    assert "777-200LRF/LR" in shared[0].variant


def test_inconsistent_published_value_is_flagged(explorer_db):
    engine, _ = explorer_db
    mtow = values(engine, "A330-200F", "mtow_kg")
    assert len(mtow) == 1 and mtow[0].verification_status == "source_inconsistent"
    assert "max ramp weight" in mtow[0].notes


def test_documented_classification_and_programmes(explorer_db):
    engine, _ = explorer_db
    assert values(engine, "B777F", "body_class")[0].value_text == "widebody"
    assert values(engine, "A321P2F", "freighter_type")[0].value_text == "converted_freighter"
    assert {values(engine, c, "freighter_type")[0].value_text for c in ("A330-200F", "B777F", "B767-300F", "B747-400F")} == {
        "production_freighter"}
    assert not values(engine, "A19N", "body_class")  # not in FAA Table 4-16: not documented, not guessed
