"""Index adjustment of benchmarks (real BLS API excerpt); originals are preserved."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.benchmarks import FAA_SOURCE, load_faa_benchmarks
from aircraft_cost_model.analytics.inflation import (
    IndexPoint,
    adjust_amount,
    adjust_benchmarks,
    read_index_mapping,
    save_adjustments,
)
from aircraft_cost_model.ingestion.price_indices import load_index_observations, parse_series_json
from aircraft_cost_model.ingestion.snapshots import store_snapshot_bytes
from aircraft_cost_model.models import BenchmarkAdjustment, BenchmarkObservation
from conftest import BLS_FIXTURES, REPO_ROOT

FIXTURE = BLS_FIXTURES / "bls_api_2022_2025_excerpt.json"
MAPPING = read_index_mapping(REPO_ROOT / "data" / "reference" / "benchmark_index_mapping.csv")
FAA_CSV = REPO_ROOT / "data" / "reference" / "faa_economic_values_table_4_7.csv"


def raw(series: str) -> dict[str, Decimal]:
    data = json.loads(FIXTURE.read_text())
    s = next(x for x in data["Results"]["series"] if x["seriesID"] == series)
    return {f"{d['year']}-{d['period']}": Decimal(d["value"]) for d in s["data"]}


def points(series: str) -> list[IndexPoint]:
    records, _ = parse_series_json(FIXTURE)
    return [IndexPoint(r["period"], r["period_start"], r["period_end"], r["value"], r["preliminary"])
            for r in records if r["series_id"] == series]


def mean(values):
    values = list(values)
    return sum(values, Decimal(0)) / len(values)


def test_parse_bls_response():
    records, messages = parse_series_json(FIXTURE)
    eci = [r for r in records if r["series_id"] == "CIU2014300000000I"]
    ppi = [r for r in records if r["series_id"] == "PCU524126524126"]
    assert len(eci) == 16 and len(ppi) == 48
    q = next(r for r in eci if r["period"] == "2024-Q03")
    assert (q["period_start"], q["period_end"]) == (date(2024, 7, 1), date(2024, 9, 30))
    assert any("PCU488190488190" in m for m in messages)  # the maintenance-related index is not served


def test_quarterly_adjustment_uses_published_window_only():
    v = raw("CIU2014300000000I")
    r = adjust_amount(Decimal("1378"), "USD", date(2022, 7, 1), date(2023, 6, 30), "YE2023Q2", "CIU2014300000000I",
                      points("CIU2014300000000I"), date(2025, 1, 15))
    base = mean(v[p] for p in ("2022-Q03", "2022-Q04", "2023-Q01", "2023-Q02"))
    target = mean(v[p] for p in ("2023-Q04", "2024-Q01", "2024-Q02", "2024-Q03"))  # Q4 2024 not yet published
    assert r.status == "adjusted" and r.base_index == base and r.target_index == target
    assert r.factor == target / base and r.adjusted_amount == Decimal("1378") * (target / base)  # original x factor
    assert r.target_period == "2023-Q04..2024-Q03" and r.original_amount == Decimal("1378")


def test_retrospective_mode_is_explicit():
    r = adjust_amount(Decimal("1378"), "USD", date(2022, 7, 1), date(2023, 6, 30), "YE2023Q2", "CIU2014300000000I",
                      points("CIU2014300000000I"), date(2025, 1, 15), retrospective=True)
    assert r.target_period == "2024-Q01..2024-Q04" and "RETROSPECTIVE" in r.methodology


def test_monthly_adjustment_and_no_future_observations():
    v = raw("PCU524126524126")
    r = adjust_amount(Decimal("6"), "USD", date(2022, 7, 1), date(2023, 6, 30), "YE2023Q2", "PCU524126524126",
                      points("PCU524126524126"), date(2025, 1, 15))
    months = [f"2023-M12"] + [f"2024-M{m:02d}" for m in range(1, 12)]
    assert r.target_period == "2023-M12..2024-M11"
    assert r.target_index == mean(v[m] for m in months)
    late = adjust_amount(Decimal("6"), "USD", date(2022, 7, 1), date(2023, 6, 30), "YE2023Q2", "PCU524126524126",
                         points("PCU524126524126"), date(2023, 7, 15))
    assert late.status == "unavailable" and "not fully published" in late.reason  # no future data used


def test_incomplete_base_window_is_unavailable():
    pts = [p for p in points("CIU2014300000000I") if p.period != "2022-Q04"]
    r = adjust_amount(Decimal("1378"), "USD", date(2022, 7, 1), date(2023, 6, 30), "YE2023Q2", "CIU2014300000000I",
                      pts, date(2025, 1, 15))
    assert r.status == "unavailable" and "found 3" in r.reason and r.adjusted_amount is None


def test_adjust_faa_benchmarks_preserves_originals(analytics_db, tmp_path):
    engine, _ = analytics_db
    snapshot = store_snapshot_bytes(FIXTURE.read_bytes(), tmp_path, "bls_fixture", ".json", "fixture", "fixture", 200)
    records, _ = parse_series_json(snapshot.path)
    assert load_index_observations(engine, snapshot, records)[0] == len(records)
    assert load_index_observations(engine, snapshot, records) == (0, len(records))
    with Session(engine) as session, session.begin():
        load_faa_benchmarks(session, FAA_CSV)
        results = adjust_benchmarks(session, MAPPING, date(2025, 1, 15))
        assert save_adjustments(session, results) == 3
        assert save_adjustments(session, adjust_benchmarks(session, MAPPING, date(2025, 1, 15))) == 0
    with Session(engine) as session:
        originals = {r.cost_category: r.amount for r in session.scalars(select(BenchmarkObservation).where(
            BenchmarkObservation.benchmark_source == FAA_SOURCE))}
        adjustments = {session.get(BenchmarkObservation, a.benchmark_id).cost_category: a
                       for a in session.scalars(select(BenchmarkAdjustment))}
        assert originals == {"crew": Decimal("1378"), "maintenance": Decimal("954"), "insurance": Decimal("6")}
        assert adjustments["maintenance"].status == "unavailable" and adjustments["maintenance"].adjusted_amount is None
        assert "PCU488190488190" in adjustments["maintenance"].reason
        crew = adjustments["crew"]
        assert crew.status == "adjusted" and crew.original_amount == Decimal("1378")
        assert crew.adjusted_amount == crew.original_amount * crew.factor
        assert crew.factor == crew.target_index / crew.base_index
        assert "proxy_pending_owner_approval" in crew.methodology and crew.index_source_id is not None
