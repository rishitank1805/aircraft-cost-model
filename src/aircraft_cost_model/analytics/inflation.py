"""Optional index adjustment of public benchmarks (originals are never modified).

    adjusted benchmark = original benchmark x target-period index / base-period index

- **Base period**: the benchmark's own reporting period (e.g. FAA Table 4-7
  "YE June 2023" = Jul 2022 - Jun 2023). The base index is the mean of every
  index period fully inside it; all periods must be present and published by
  the target date.
- **Target period**: the same number of consecutive index periods ending with
  the latest period that would have been *published* by the target date.
  Publication is approximated conservatively: period end + 30 days (monthly
  PPI) or + 45 days (quarterly ECI). With ``retrospective=True`` (explicit
  user request) the lag is ignored and the latest observations whose period
  ended on or before the target date are used; this is labelled.
- One source snapshot per series is used for both windows; preliminary
  values are counted and reported.
- A category without a verified index (see
  ``data/reference/benchmark_index_mapping.csv``) gets an explicit
  ``unavailable`` record with the reason; no adjustment is invented.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aircraft_cost_model.costs.currency import plain
from aircraft_cost_model.models import BenchmarkAdjustment, BenchmarkObservation, PriceIndexObservation

PUBLICATION_LAG_DAYS = {"monthly": 30, "quarterly": 45}


@dataclass(frozen=True)
class IndexPoint:
    period: str
    start: date
    end: date
    value: Decimal
    preliminary: bool = False


@dataclass
class AdjustmentResult:
    status: str  # adjusted | unavailable
    original_amount: Decimal | None
    original_currency: str
    original_period: str
    index_series_id: str
    target_date: date
    methodology: str
    index_source_id: int | None = None
    base_period: str | None = None
    base_index: Decimal | None = None
    target_period: str | None = None
    target_index: Decimal | None = None
    factor: Decimal | None = None
    adjusted_amount: Decimal | None = None
    reason: str | None = None
    preliminary_values: int = 0
    suitability: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: (plain(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, date) else v)
                for k, v in self.__dict__.items()}


def frequency(points: list[IndexPoint]) -> str:
    return "quarterly" if points and "-Q" in points[0].period else "monthly"


def _months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def adjust_amount(original: Decimal, currency: str, period_start: date, period_end: date, period_label: str,
                  series_id: str, points: list[IndexPoint], target_date: date, retrospective: bool = False,
                  index_source_id: int | None = None) -> AdjustmentResult:
    points = sorted(points, key=lambda p: p.start)
    freq = frequency(points)
    step = 3 if freq == "quarterly" else 1
    base_kw = dict(original_amount=original, original_currency=currency, original_period=period_label,
                   index_series_id=series_id, target_date=target_date, index_source_id=index_source_id)
    method = (f"original x mean({series_id}, target window) / mean({series_id}, base window); {freq} index; "
              + ("RETROSPECTIVE: latest observations ending on or before the target date, publication lag ignored"
                 if retrospective else f"target window ends at the latest period published by the target date "
                 f"(period end + {PUBLICATION_LAG_DAYS[freq]} days, approximation)"))
    expected = _months(period_start, period_end) // step
    base = [p for p in points if p.start >= period_start and p.end <= period_end]
    if expected < 1 or len(base) != expected:
        return AdjustmentResult("unavailable", methodology=method, reason=(
            f"base window {period_label} needs {expected} {freq} observations of {series_id}; found {len(base)}"),
            **base_kw)
    lag = timedelta(days=0 if retrospective else PUBLICATION_LAG_DAYS[freq])
    if any(p.end + lag > target_date for p in base):
        return AdjustmentResult("unavailable", methodology=method, reason=(
            f"base window {period_label} was not fully published by the target date {target_date}"), **base_kw)
    available = [p for p in points if p.end + lag <= target_date]
    if len(available) < expected:
        return AdjustmentResult("unavailable", methodology=method, reason=(
            f"fewer than {expected} {series_id} observations published by {target_date}"), **base_kw)
    target = available[-expected:]
    for a, b in zip(target, target[1:]):
        if _months(a.start, b.start) - 1 != step:
            return AdjustmentResult("unavailable", methodology=method, reason=(
                f"target window for {series_id} is not consecutive ({a.period} -> {b.period})"), **base_kw)
    base_index = sum((p.value for p in base), Decimal(0)) / len(base)
    target_index = sum((p.value for p in target), Decimal(0)) / len(target)
    factor = target_index / base_index
    preliminary = sum(p.preliminary for p in base + target)
    return AdjustmentResult(
        "adjusted", methodology=method + (f"; {preliminary} preliminary value(s) included (subject to revision)"
                                          if preliminary else ""),
        base_period=f"{base[0].period}..{base[-1].period}", base_index=base_index,
        target_period=f"{target[0].period}..{target[-1].period}", target_index=target_index, factor=factor,
        adjusted_amount=original * factor, preliminary_values=preliminary, **base_kw)


@dataclass(frozen=True)
class IndexMapping:
    category: str
    series_id: str | None
    title: str | None
    suitability: str
    rationale: str


def read_index_mapping(path: Path) -> dict[str, IndexMapping]:
    with path.open(encoding="utf-8") as handle:
        return {r["benchmark_category"]: IndexMapping(r["benchmark_category"], r["index_series_id"] or None,
                                                      r["index_title"] or None, r["suitability_status"], r["rationale"])
                for r in csv.DictReader(handle)}


def index_points(session: Session, series_id: str) -> tuple[list[IndexPoint], int | None]:
    """Observations of ``series_id`` from its most recent source snapshot (one snapshot, never mixed)."""
    source_id = session.scalar(select(func.max(PriceIndexObservation.source_id))
                               .where(PriceIndexObservation.series_id == series_id))
    if source_id is None:
        return [], None
    rows = session.scalars(select(PriceIndexObservation).where(
        PriceIndexObservation.series_id == series_id, PriceIndexObservation.source_id == source_id)).all()
    return [IndexPoint(r.period, r.period_start, r.period_end, r.value, r.preliminary) for r in rows], source_id


def adjust_benchmarks(session: Session, mapping: dict[str, IndexMapping], target_date: date,
                      benchmark_source: str = "faa_econ_values_s4_t4_7", retrospective: bool = False
                      ) -> list[tuple[BenchmarkObservation, AdjustmentResult]]:
    """Adjust every observation of ``benchmark_source``; categories without a verified index are unavailable."""
    out = []
    observations = session.scalars(select(BenchmarkObservation).where(
        BenchmarkObservation.benchmark_source == benchmark_source).order_by(BenchmarkObservation.benchmark_id)).all()
    for obs in observations:
        m = mapping.get(obs.cost_category)
        common = dict(original_currency=obs.currency, original_period=obs.period_label, target_date=target_date)
        if m is None or m.series_id is None or m.suitability == "unavailable":
            out.append((obs, AdjustmentResult("unavailable", obs.amount, index_series_id="", methodology="none",
                                              reason=m.rationale if m else "no index mapping for this category",
                                              suitability=m.suitability if m else None, **common)))
            continue
        points, source_id = index_points(session, m.series_id)
        if not points:
            out.append((obs, AdjustmentResult("unavailable", obs.amount, index_series_id=m.series_id, methodology="none",
                                              reason=f"no {m.series_id} observations loaded (run ingest_price_indices.py)",
                                              suitability=m.suitability, **common)))
            continue
        result = adjust_amount(obs.amount, obs.currency, obs.period_start, obs.period_end, obs.period_label,
                               m.series_id, points, target_date, retrospective, source_id)
        result.suitability = m.suitability
        if result.status == "adjusted" and m.suitability != "verified":
            result.methodology += f"; index suitability: {m.suitability} ({m.title})"
        out.append((obs, result))
    return out


def save_adjustments(session: Session, results: list[tuple[BenchmarkObservation, AdjustmentResult]]) -> int:
    """Insert adjustment records (existing identical records are kept; originals are never modified)."""
    inserted = 0
    for obs, r in results:
        exists = session.scalar(select(BenchmarkAdjustment).where(
            BenchmarkAdjustment.benchmark_id == obs.benchmark_id, BenchmarkAdjustment.index_series_id == r.index_series_id,
            BenchmarkAdjustment.target_date == r.target_date,
            (BenchmarkAdjustment.index_source_id == r.index_source_id) if r.index_source_id is not None
            else BenchmarkAdjustment.index_source_id.is_(None)))
        if exists is not None:
            continue
        session.add(BenchmarkAdjustment(
            benchmark_id=obs.benchmark_id, status=r.status, original_amount=r.original_amount,
            original_currency=r.original_currency, original_period=r.original_period,
            index_series_id=r.index_series_id, index_source_id=r.index_source_id, base_period=r.base_period,
            base_index=r.base_index, target_period=r.target_period, target_date=r.target_date,
            target_index=r.target_index, factor=r.factor, adjusted_amount=r.adjusted_amount,
            methodology=r.methodology, reason=r.reason))
        inserted += 1
    session.flush()
    return inserted
