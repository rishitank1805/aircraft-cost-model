"""BTS Form 41 benchmark processing (real excerpts), FAA reference values and comparability rules."""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.benchmarks import (
    BTS_SOURCE,
    FAA_SOURCE,
    BenchmarkSelection,
    benchmark_metric,
    compare_with_benchmark,
    load_faa_benchmarks,
    read_aircraft_mapping,
)
from aircraft_cost_model.analytics.cases import calculate_case, load_saved_case
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.fullcost.scenario import load_scenario
from aircraft_cost_model.ingestion.bts_form41 import load_bts_benchmarks, lookup_url
from aircraft_cost_model.ingestion.snapshots import store_snapshot_bytes
from aircraft_cost_model.models import BenchmarkObservation, ExchangeRate
from aircraft_cost_model.processing.bts_form41 import (
    NM_PER_STATUTE_MILE,
    TONNE_NM_PER_TON_MILE,
    build_records,
    read_lookup,
    read_zip_csv,
)
from conftest import BTS_FIXTURES, REPO_ROOT, SCENARIOS

MAPPING = read_aircraft_mapping(REPO_ROOT / "data" / "reference" / "bts_aircraft_type_mapping.csv")
FAA_CSV = REPO_ROOT / "data" / "reference" / "faa_economic_values_table_4_7.csv"


def frames():
    return (read_zip_csv(BTS_FIXTURES / "p52_2025q1_excerpt.zip", "T_F41SCHEDULE_P52.csv"),
            read_zip_csv(BTS_FIXTURES / "t2_2025q1_excerpt.zip", "T_SCHEDULE_T2.csv"),
            read_lookup(BTS_FIXTURES / "l_aircraft_type_excerpt.csv"))


def rec(records, carrier, type_code, region, category):
    return next(r for r in records if (r["carrier_code"], r["aircraft_type_code"], r["region"], r["cost_category"])
                == (carrier, type_code, region, category))


def test_unit_conversions_are_exact():
    assert TONNE_NM_PER_TON_MILE == Decimal("0.90718474") * Decimal("1609.344") / Decimal("1852")
    assert NM_PER_STATUTE_MILE == Decimal("1609.344") / Decimal("1852")
    assert abs(TONNE_NM_PER_TON_MILE - Decimal("0.7883")) < Decimal("0.0001")


def test_lookup_urls_use_exact_transtats_identifiers():
    import codecs

    assert lookup_url("L_REGION").endswith("Y11x72=Y_eRTVba")
    assert codecs.decode(lookup_url("L_AIRCRAFT_TYPE").split("=")[-1], "rot13").upper() == "L_AIRCRAFT_TYPE"


def test_schema_validation():
    p52, t2, _ = frames()
    with pytest.raises(SourceSchemaError, match="TOTAL_AIR_HOURS"):
        build_records(p52.drop(columns=["TOTAL_AIR_HOURS"]), t2, {})
    with pytest.raises(SourceSchemaError, match="expected"):
        read_zip_csv(BTS_FIXTURES / "p52_2025q1_excerpt.zip", "T_SCHEDULE_T2.csv")


def test_build_records_join_and_exclusions():
    p52, t2, types = frames()
    result = build_records(p52, t2, types)
    unattributed = int(((p52.AIRCRAFT_TYPE == "999") | (p52.AIRCRAFT_CONFIG == "9")).sum())
    assert result.excluded_unattributed == unattributed > 0
    assert not any(r["aircraft_type_code"] == "999" for r in result.records)  # fleet-level never stored
    fx = rec(result.records, "FX", "683", "P", "fuel")
    p_row = p52[(p52.UNIQUE_CARRIER == "FX") & (p52.AIRCRAFT_TYPE == "683") & (p52.REGION == "P")].iloc[0]
    z = t2[(t2.UNIQUE_CARRIER == "FX") & (t2.AIRCRAFT_TYPE == "683") & (t2.CARRIER_REGION == "P")
           & (t2.SERVICE_CLASS == "Z")].iloc[0]
    assert fx["amount"] == Decimal(p_row.FUEL_FLY_OPS) * 1000  # $000 -> USD
    assert fx["airborne_hours"] == Decimal(p_row.TOTAL_AIR_HOURS) * 1000
    assert fx["block_hours"] == Decimal(z.ACRFT_HRS_RAMPTORAMP_630)  # service class Z only (K+V would double count)
    assert fx["revenue_tonne_nm"] == Decimal(z.REV_TON_MILES_240) * TONNE_NM_PER_TON_MILE
    assert fx["departures"] == Decimal(z.REV_ACRFT_DEP_PERF_510)
    assert fx["operation_scope"] == "freight_configuration_all_cargo_carrier"
    assert rec(result.records, "DL", "694", "D", "fuel")["operation_scope"] == "passenger_configuration"
    assert fx["quality_status"] == "ok" and fx["period_label"] == "2025Q1"
    assert fx["period_start"] == date(2025, 1, 1) and fx["period_end"] == date(2025, 3, 31)


def test_quality_flags_and_blank_fields():
    p52, t2, types = frames()
    records = build_records(p52, t2, types).records
    zero = [r for r in records if r["airborne_hours"] in (None, Decimal(0))]
    assert zero and all("low_hours" in (r["quality_notes"] or "") for r in zero)
    blank = p52.copy()
    blank.loc[(blank.UNIQUE_CARRIER == "DL") & (blank.AIRCRAFT_TYPE == "694") & (blank.REGION == "D"), "INS_FLY_OPS"] = ""
    ins = rec(build_records(blank, t2, types).records, "DL", "694", "D", "insurance")
    assert ins["amount"] is None and ins["quality_status"] == "missing_fields"  # blank is never zero
    unmatched = t2[~((t2.UNIQUE_CARRIER == "DL") & (t2.CARRIER_REGION == "D"))]
    dl = rec(build_records(p52, unmatched, types).records, "DL", "694", "D", "fuel")
    assert dl["block_hours"] is None and dl["quality_status"] == "no_traffic_match"
    negative = p52.copy()
    negative.loc[(negative.UNIQUE_CARRIER == "UA") & (negative.REGION == "D") & (negative.AIRCRAFT_TYPE == "694"),
                 "RENTAL_FLY_OPS"] = "-5"
    assert rec(build_records(negative, t2, types).records, "UA", "694", "D", "rentals")["quality_status"] == "negative_amount"


def _zip(frame: pd.DataFrame, name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, frame.to_csv(index=False))
    return buf.getvalue()


@pytest.fixture
def bts_loaded(analytics_db, tmp_path):
    engine, ids = analytics_db
    p52, t2, types = frames()
    snap_p = store_snapshot_bytes((BTS_FIXTURES / "p52_2025q1_excerpt.zip").read_bytes(), tmp_path, "bts_p52_2025",
                                  ".zip", "fixture", "fixture", 200)
    snap_t = store_snapshot_bytes((BTS_FIXTURES / "t2_2025q1_excerpt.zip").read_bytes(), tmp_path, "bts_t2_2025",
                                  ".zip", "fixture", "fixture", 200)
    records = build_records(p52, t2, types).records
    first = load_bts_benchmarks(engine, snap_p, snap_t, 2025, records)
    with Session(engine) as session, session.begin():
        load_faa_benchmarks(session, FAA_CSV)
        # labelled SYNTHETIC test rates: the ECB fixture covers January only; Feb-Mar are filled for the period mean
        day = date(2025, 2, 3)
        while day <= date(2025, 3, 31):
            if day.weekday() < 5:
                session.add(ExchangeRate(source_id=1, base_currency="EUR", quote_currency="USD", observation_date=day,
                                         rate=Decimal("1.04"), retrieved_at=pd.Timestamp("2026-10-15").to_pydatetime(),
                                         series_key="SYNTHETIC-TEST"))
            day += timedelta(days=1)
    return engine, ids, first, (snap_p, snap_t, records, tmp_path)


def test_loading_is_idempotent_and_versioned(bts_loaded):
    engine, _, first, (snap_p, snap_t, records, tmp_path) = bts_loaded
    assert first[0] == len(records) and load_bts_benchmarks(engine, snap_p, snap_t, 2025, records) == (0, len(records))
    revised = pd.read_csv(io.BytesIO(zipfile.ZipFile(BTS_FIXTURES / "p52_2025q1_excerpt.zip").read(
        "T_F41SCHEDULE_P52.csv")), dtype=str, keep_default_na=False)
    revised.loc[revised.index[0], "FUEL_FLY_OPS"] = "1.00"
    snap_rev = store_snapshot_bytes(_zip(revised, "T_F41SCHEDULE_P52.csv"), tmp_path, "bts_p52_2025", ".zip", "f", "f", 200)
    inserted, _ = load_bts_benchmarks(engine, snap_rev, snap_t, 2025, build_records(revised, frames()[1], {}).records)
    with Session(engine) as session:
        sources = session.scalars(select(func.count(func.distinct(BenchmarkObservation.source_id))).where(
            BenchmarkObservation.benchmark_source == BTS_SOURCE)).one()
    assert inserted == len(records) and sources == 2  # history kept, nothing overwritten


def test_benchmark_metric_is_ratio_of_sums(bts_loaded):
    engine, *_ = bts_loaded
    with Session(engine) as session:
        sel = BenchmarkSelection(BTS_SOURCE, "fuel", ("694",), "1", carriers=("DL", "UA"), regions=("D",),
                                 period_labels=("2025Q1",))
        m = benchmark_metric(session, sel, "block_hour")
        rows = session.scalars(select(BenchmarkObservation).where(BenchmarkObservation.benchmark_id.in_(m.rows_used))).all()
    assert len(rows) == 2
    assert m.value == sum(r.amount for r in rows) / sum(r.block_hours for r in rows)
    assert m.value != sum(r.amount / r.block_hours for r in rows) / 2
    assert m.average_stage_nm == sum(r.aircraft_miles_nm for r in rows) / sum(r.departures for r in rows)


def _fuel_case(session, ids):
    return load_saved_case(session, ids["full"])


def test_comparable_with_caveats_fuel_deviation(bts_loaded):
    engine, ids, *_ = bts_loaded
    with Session(engine) as session:
        case = _fuel_case(session, ids)
        sel = BenchmarkSelection(BTS_SOURCE, "fuel", ("694",), "1", period_labels=("2025Q1",))
        r = compare_with_benchmark(session, case, "fuel", "block_hour", sel, MAPPING)
    assert r.comparability == "comparable_with_caveats"
    names = {c.name: c.result for c in r.checks}
    assert names["period"] == "pass" and names["model_source"] == "pass" and names["category"] == "caveat"
    assert names["geographic_scope"] == "caveat" and names["currency"] == "caveat"
    assert r.model_value == Decimal("1788.05") / case.facts.block_hours
    assert r.absolute_difference == r.model_value - r.benchmark_value_converted
    assert r.percentage_difference == r.absolute_difference / r.benchmark_value_converted * 100
    assert "not a measure of model error" in r.to_dict()["interpretation"]


def test_not_comparable_cases(bts_loaded):
    engine, ids, *_ = bts_loaded
    with Session(engine) as session:
        case = _fuel_case(session, ids)
        illustrative = compare_with_benchmark(session, case, "maintenance", "block_hour", BenchmarkSelection(
            BTS_SOURCE, "maintenance_total", ("694",), "1", period_labels=("2025Q1",)), MAPPING)
        assert illustrative.comparability == "not_comparable" and illustrative.absolute_difference is None
        assert any("ILLUSTRATIVE" in reason for reason in illustrative.reasons)
        faa_case, _ = calculate_case(session, 1, ids["variable"],
                                     load_scenario(SCENARIOS / "benchmark_faa_us_narrowbody_partial.json"))
        circular = compare_with_benchmark(session, faa_case, "maintenance", "block_hour",
                                          BenchmarkSelection(FAA_SOURCE, "maintenance", ("NB165K",), "1"), MAPPING)
        assert any("circular" in reason for reason in circular.reasons)
        assert any(r.startswith("period") for r in circular.reasons)  # YE June 2023 vs 2025 without adjustment
        caveat = compare_with_benchmark(session, faa_case, "maintenance", "block_hour", BenchmarkSelection(
            BTS_SOURCE, "maintenance_total", ("694",), "1", period_labels=("2025Q1",)), MAPPING)
        assert {c.name: c.result for c in caveat.checks}["model_source"] == "caveat"  # FAA derived from BTS
        cargo = compare_with_benchmark(session, case, "fuel", "block_hour", BenchmarkSelection(
            BTS_SOURCE, "fuel", ("683",), "2", period_labels=("2025Q1",)), MAPPING)
        assert cargo.comparability == "not_comparable"
        assert any(r.startswith("aircraft_type") for r in cargo.reasons)
        assert any(r.startswith("operation_scope") for r in cargo.reasons)  # passenger model vs freighter rows
        missing = compare_with_benchmark(session, case, "fuel", "block_hour", BenchmarkSelection(
            BTS_SOURCE, "fuel", ("694",), "1", period_labels=("2019Q1",)), MAPPING)
        assert any("no benchmark rows" in r for r in missing.reasons)
        airborne_faa = compare_with_benchmark(session, case, "fuel", "airborne_hour",
                                              BenchmarkSelection(FAA_SOURCE, "crew", ("NB165K",), "1"), MAPPING)
        assert airborne_faa.comparability == "not_comparable"
        rtnm = compare_with_benchmark(session, case, "fuel", "revenue_tonne_nm", BenchmarkSelection(
            BTS_SOURCE, "fuel", ("694",), "1", period_labels=("2025Q1",)), MAPPING)
        assert any("revenue cargo payload" in r for r in rtnm.reasons)
        assert any(r.startswith("traffic_definition") for r in rtnm.reasons)  # passenger RTM includes passengers


def test_zero_benchmark_gives_no_percentage(bts_loaded):
    engine, ids, *_ = bts_loaded
    with Session(engine) as session, session.begin():
        row = session.scalars(select(BenchmarkObservation).where(
            BenchmarkObservation.carrier_code == "DL", BenchmarkObservation.region == "D",
            BenchmarkObservation.cost_category == "fuel")).one()
        session.add(BenchmarkObservation(**{c.name: getattr(row, c.name) for c in BenchmarkObservation.__table__.columns
                                            if c.name not in ("benchmark_id", "cost_category", "amount")},
                                         cost_category="pilots_and_copilots_test_zero", amount=Decimal(0)))
    from aircraft_cost_model.analytics import benchmarks as b
    b.MAPPINGS["fuel_zero_test"] = b.MetricMapping("fuel_zero_test", ("fuel",), {BTS_SOURCE: "pilots_and_copilots_test_zero"},
                                                   ("test",))
    try:
        with Session(engine) as session:
            r = compare_with_benchmark(session, _fuel_case(session, ids), "fuel_zero_test", "block_hour",
                                       BenchmarkSelection(BTS_SOURCE, "pilots_and_copilots_test_zero", ("694",), "1",
                                                          carriers=("DL",), regions=("D",)), MAPPING)
        assert r.benchmark_value_converted == 0 and r.percentage_difference is None
    finally:
        del b.MAPPINGS["fuel_zero_test"]


def test_faa_reference_values_loaded_once(analytics_db):
    engine, _ = analytics_db
    with Session(engine) as session, session.begin():
        assert load_faa_benchmarks(session, FAA_CSV) == (3, 0)
        assert load_faa_benchmarks(session, FAA_CSV) == (0, 3)
        rows = session.scalars(select(BenchmarkObservation).where(BenchmarkObservation.benchmark_source == FAA_SOURCE)).all()
        loaded = {(r.cost_category, r.amount, r.block_hours) for r in rows}
    assert loaded == {
        ("crew", Decimal("1378"), Decimal(1)), ("maintenance", Decimal("954"), Decimal(1)),
        ("insurance", Decimal("6"), Decimal(1))}


def test_aircraft_mapping_has_no_substitutions():
    assert MAPPING["A321P2F"]["mapping_status"] == "unmapped"
    assert MAPPING["B777F"]["bts_aircraft_type"] == "683" and MAPPING["B777F"]["bts_aircraft_config"] == "2"
    assert all(MAPPING[c]["bts_aircraft_config"] == "1" for c in ("A320", "B738", "B763"))
