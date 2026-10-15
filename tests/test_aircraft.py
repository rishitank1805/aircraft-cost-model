"""Aircraft normalization and validation tests."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from aircraft_cost_model.config import JET_FUEL_DENSITY_KG_PER_L
from aircraft_cost_model.ingestion.aircraft import CARGO_AIRCRAFT_TARGETS, read_openap_aircraft
from aircraft_cost_model.processing.aircraft_cleaner import (
    COVERAGE_NONE,
    COVERAGE_RELATED_PASSENGER_ONLY,
    build_cargo_target_rows,
    normalize_openap_aircraft,
    split_manufacturer,
)
from aircraft_cost_model.validation.aircraft_validator import check_weight_relationships, validate_aircraft


def _validate(master: pd.DataFrame):
    return validate_aircraft(
        master, total_source_records=len(master), source_name="test", source_url="x",
        retrieved_at=None, source_version=None,
    )


def test_openap_values_are_kept_in_source_units(openap_like_records):
    master = normalize_openap_aircraft(openap_like_records)
    a332 = master.set_index("aircraft_code").loc["A332"]
    assert a332["manufacturer"] == "Airbus"
    assert a332["model"] == "A330-200"
    assert a332["mtow_kg"] == 230000
    assert a332["fuel_capacity_l"] == 139000
    assert a332["engine_count"] == 2
    assert bool(a332["openap_supported"]) is True


def test_derived_values_are_labelled(openap_like_records):
    a332 = normalize_openap_aircraft(openap_like_records).set_index("aircraft_code").loc["A332"]
    provenance = json.loads(a332["field_provenance"])
    assert a332["fuel_capacity_kg"] == pytest.approx(139000 * JET_FUEL_DENSITY_KG_PER_L)
    assert provenance["fuel_capacity_kg"].startswith("derived:")
    assert provenance["cruise_speed_kt"].startswith("derived:")
    assert provenance["mtow_kg"] == "source"
    assert 460 < a332["cruise_speed_kt"] < 480  # M0.82 at 11 km ISA ~ 470 kt TAS


def test_missing_aircraft_attributes_stay_null(openap_like_records):
    master = normalize_openap_aircraft(openap_like_records).set_index("aircraft_code")
    a332, unknown = master.loc["A332"], master.loc["XYZ1"]
    assert pd.isna(a332["mzfw_kg"]) and pd.isna(a332["max_payload_kg"])
    for field in ("mtow_kg", "mlw_kg", "oew_kg", "fuel_capacity_kg", "cruise_speed_kt", "engine_count"):
        assert pd.isna(unknown[field]), field
    assert pd.isna(unknown["manufacturer"])  # not guessed from an unknown name
    report = _validate(master.reset_index())
    assert report.passed
    assert report.missing_values_by_field["mzfw_kg"] == 2


def test_split_manufacturer():
    assert split_manufacturer("BOMBARDIER CRJ9") == ("Bombardier", "CRJ9")
    assert split_manufacturer("Boeing 777-300ER") == ("Boeing", "777-300ER")
    assert split_manufacturer("Mystery Jet") == (None, "Mystery Jet")
    assert split_manufacturer(None) == (None, None)


def test_weight_relationship_warnings_do_not_reject():
    good = pd.Series({"aircraft_code": "OK", "mtow_kg": 100.0, "mlw_kg": 90.0, "mzfw_kg": 80.0, "oew_kg": 50.0,
                      "max_payload_kg": None})
    equal = pd.Series({"aircraft_code": "EQ", "mtow_kg": 100.0, "mlw_kg": 100.0, "mzfw_kg": None, "oew_kg": 50.0,
                       "max_payload_kg": None})
    bad = pd.Series({"aircraft_code": "BAD", "mtow_kg": 100.0, "mlw_kg": 120.0, "mzfw_kg": None, "oew_kg": 130.0,
                     "max_payload_kg": None})
    assert check_weight_relationships(good) == []
    assert check_weight_relationships(equal) == []
    messages = check_weight_relationships(bad)
    assert any("oew_kg" in m and "mtow_kg" in m for m in messages)
    assert any("mlw_kg" in m and "mtow_kg" in m for m in messages)


def test_validator_errors_on_non_positive_values_and_duplicates(openap_like_records):
    master = normalize_openap_aircraft(openap_like_records)
    master.loc[master["aircraft_code"] == "A332", "mtow_kg"] = -1
    master = pd.concat([master, master.iloc[[0]]], ignore_index=True)
    report = _validate(master)
    assert not report.passed
    assert any("Non-positive mtow_kg" in e for e in report.errors)
    assert any("Duplicate aircraft_code" in e for e in report.errors)


def test_validator_rejects_unlabelled_conversion(openap_like_records):
    master = normalize_openap_aircraft(openap_like_records)
    master.loc[master["aircraft_code"] == "A332", "field_provenance"] = json.dumps({"mtow_kg": "source"})
    report = _validate(master)
    assert any("fuel_capacity_kg populated without" in e for e in report.errors)


def test_cargo_targets_never_inherit_passenger_values():
    rows, warnings = build_cargo_target_rows(CARGO_AIRCRAFT_TARGETS, {"A332", "B763", "B744", "A321"})
    assert warnings == []
    rows = rows.set_index("aircraft_code")
    for field in ("mtow_kg", "oew_kg", "fuel_capacity_kg", "cruise_speed_kt", "engine_count"):
        assert rows[field].isna().all(), field
    assert not rows["openap_supported"].any()
    assert rows.loc["A330-200F", "openap_coverage"] == COVERAGE_RELATED_PASSENGER_ONLY
    assert rows.loc["A330-200F", "openap_related_code"] == "A332"
    assert rows.loc["B777F", "openap_coverage"] == COVERAGE_NONE
    assert pd.isna(rows.loc["B777F", "openap_related_code"])


def test_cargo_target_related_code_cleared_if_not_in_openap():
    rows, warnings = build_cargo_target_rows(CARGO_AIRCRAFT_TARGETS, set())
    assert (rows["openap_coverage"] == COVERAGE_NONE).all()
    assert len(warnings) == 4


def test_installed_openap_data_is_readable_and_valid():
    """Reads the locally installed OpenAP package (no network)."""
    snapshot = read_openap_aircraft()
    assert "A332" in snapshot.records
    assert "B77L" not in snapshot.records  # synonyms are not used
    master = normalize_openap_aircraft(snapshot.records)
    report = _validate(master)
    assert report.passed, report.errors
    assert master["mzfw_kg"].isna().all()
