"""Public benchmark metrics and model-versus-benchmark comparability.

Benchmark metric (BTS): sum of selected amounts / sum of the matching
denominators over the selected carrier x aircraft type x configuration x
region x quarter rows (an expense-weighted ratio of totals, never an average
of ratios). Only rows with ``quality_status = ok`` are used unless the caller
asks otherwise; fleet-level (unattributed) expenses are never stored.

Comparability verdicts:

- ``comparable``: every check passes;
- ``comparable_with_caveats``: no check fails but definitions, scope or
  currency differ in documented ways; the difference is reported as a
  *difference*, never as model error;
- ``not_comparable``: at least one check fails; no deviation is computed.

    absolute difference   = model metric - benchmark metric
    percentage difference = (model - benchmark) / benchmark x 100   (benchmark > 0 only)
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import CostCase
from aircraft_cost_model.costs.currency import plain
from aircraft_cost_model.database import SourceMetadata, register_data_source
from aircraft_cost_model.fullcost.aggregate import component_source_quality
from aircraft_cost_model.models import Airport, BenchmarkAdjustment, BenchmarkObservation, ExchangeRate, FlightEstimate

FAA_SOURCE = "faa_econ_values_s4_t4_7"
BTS_SOURCE = "bts_form41_p52_t2"
MIN_FX_OBSERVATIONS = 45  # of ~62-66 ECB business days per quarter
MAX_PERIOD_GAP_DAYS = 366
STAGE_RATIO_RANGE = (Decimal("0.5"), Decimal("2"))


@dataclass(frozen=True)
class MetricMapping:
    key: str
    components: tuple[str, ...]
    categories: dict[str, str]  # benchmark_source -> cost_category
    caveats: tuple[str, ...]


MAPPINGS: dict[str, MetricMapping] = {m.key: m for m in (
    MetricMapping("fuel", ("fuel",), {BTS_SOURCE: "fuel"}, (
        "BTS 51451 is the carrier's recorded fuel expense (contract and into-plane prices, taxes, hedging effects, "
        "fuel for all flights of the type); the model values modelled block fuel at the EIA U.S. Gulf Coast spot "
        "benchmark",)),
    MetricMapping("flight_crew", ("crew_salaries", "crew_allowances"),
                  {BTS_SOURCE: "flight_crew_excluding_other_personnel", FAA_SOURCE: "crew"}, (
        "BTS crew cost includes trainees/instructors, benefits, pensions and payroll taxes as recorded by the "
        "carrier and excludes 51240 other flight personnel; the model uses scenario compensation, on-costs and "
        "productivity",)),
    MetricMapping("maintenance", ("airframe_maintenance", "engine_maintenance", "engine_llp"),
                  {BTS_SOURCE: "maintenance_total", FAA_SOURCE: "maintenance"}, (
        "BTS/FAA maintenance is recorded expense (incl. applied burden); the model's LLP component is an economic "
        "accrual and its rates are scenario inputs",)),
    MetricMapping("insurance", ("insurance",), {BTS_SOURCE: "insurance", FAA_SOURCE: "insurance"}, (
        "BTS 51551 is insurance purchased within flying operations",)),
    MetricMapping("depreciation", ("depreciation",), {BTS_SOURCE: "depreciation_airframe_engine"}, (
        "BTS depreciation follows the carrier's accounting lives and residuals over a mixed owned/leased fleet",)),
    MetricMapping("operating_lease", ("operating_lease",), {BTS_SOURCE: "rentals"}, (
        "BTS 51470 rentals cover all rented flight equipment of the type, including short-term and wet-lease "
        "elements",)),
)}
DENOMINATORS = {"block_hour": "block_hours", "airborne_hour": "airborne_hours", "revenue_tonne_nm": "revenue_tonne_nm"}


# ---------------------------------------------------------------------------
# FAA reference values
# ---------------------------------------------------------------------------

def load_faa_benchmarks(session: Session, csv_path: Path) -> tuple[int, int]:
    """Load the transcribed FAA Table 4-7 values (published per-block-hour rates)."""
    content = csv_path.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    source_id = register_data_source(session, SourceMetadata(
        source_name="U.S. Federal Aviation Administration (FAA), Office of Aviation Policy and Plans",
        source_url="https://www.faa.gov/regulations_policies/policy_guidance/benefit_cost/econ-value-section-4-op-costs.pdf",
        dataset_name="faa_economic_values_s4_table_4_7", license="U.S. Government work (public domain in the US)",
        access_type="values transcribed from the official PDF into data/reference/faa_economic_values_table_4_7.csv",
        retrieved_at=None, source_version="2024 update", checksum=checksum,
        notes="Table 4-7, US Part 121 passenger carriers, narrowbody >=165k lb MTOW, YE June 2023, USD/block hour"))
    inserted = existing = 0
    with csv_path.open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            key = dict(source_id=source_id, benchmark_source=FAA_SOURCE, carrier_code="US_P121_PAX",
                       aircraft_type_code="NB165K", aircraft_config="1", region="US", period_label="YE2023Q2",
                       cost_category=r["cost_category"])
            if session.scalar(select(BenchmarkObservation).filter_by(**key)) is not None:
                existing += 1
                continue
            session.add(BenchmarkObservation(
                **key, source_table=f"FAA Economic Values Section 4, {r['table']}", carrier_name=r["carrier_class"],
                carrier_group=None, operation_scope="passenger_configuration",
                aircraft_type_description=r["aircraft_class"], period_start=date.fromisoformat(r["period_start"]),
                period_end=date.fromisoformat(r["period_end"]), amount=Decimal(r["value"]), currency=r["currency"],
                block_hours=Decimal(1), source_fields=f"{r['table']} {r['cost_category']}",
                methodology="published rate per block hour (amount per 1 block hour)", quality_status="ok",
                quality_notes=r["notes"]))
            inserted += 1
    session.flush()
    return inserted, existing


# ---------------------------------------------------------------------------
# Benchmark selection and aggregation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BenchmarkSelection:
    source: str
    cost_category: str
    aircraft_type_codes: tuple[str, ...]
    aircraft_config: str | None = None
    carriers: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    period_labels: tuple[str, ...] = ()
    quality: tuple[str, ...] = ("ok",)
    use_adjusted_target_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v.isoformat() if isinstance(v, date) else v)
                for k, v in self.__dict__.items()}


@dataclass
class BenchmarkMetric:
    selection: BenchmarkSelection
    denominator: str
    value: Decimal | None
    currency: str
    amount_total: Decimal | None
    denominator_total: Decimal | None
    rows_used: list[int]
    rows_excluded: dict[str, int]
    carriers: list[str]
    periods: list[str]
    regions: list[str]
    operation_scopes: list[str]
    period_start: date | None
    period_end: date | None
    average_stage_nm: Decimal | None
    adjustment: dict[str, Any] | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {k: (plain(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, date) else v)
               for k, v in self.__dict__.items() if k != "selection"}
        out["selection"] = self.selection.to_dict()
        return out


def benchmark_metric(session: Session, selection: BenchmarkSelection, denominator: str) -> BenchmarkMetric:
    column = DENOMINATORS[denominator]
    query = select(BenchmarkObservation).where(BenchmarkObservation.benchmark_source == selection.source,
                                               BenchmarkObservation.cost_category == selection.cost_category)
    if selection.aircraft_type_codes:
        query = query.where(BenchmarkObservation.aircraft_type_code.in_(selection.aircraft_type_codes))
    if selection.aircraft_config:
        query = query.where(BenchmarkObservation.aircraft_config == selection.aircraft_config)
    if selection.carriers:
        query = query.where(BenchmarkObservation.carrier_code.in_(selection.carriers))
    if selection.regions:
        query = query.where(BenchmarkObservation.region.in_(selection.regions))
    if selection.period_labels:
        query = query.where(BenchmarkObservation.period_label.in_(selection.period_labels))
    rows = session.scalars(query.order_by(BenchmarkObservation.benchmark_id)).all()
    # one snapshot per source table and period: latest source_id wins (revisions are kept, never mixed)
    latest: dict[str, int] = {}
    for r in rows:
        latest[r.period_label] = max(latest.get(r.period_label, 0), r.source_id)
    rows = [r for r in rows if r.source_id == latest[r.period_label]]
    used, excluded = [], {}
    for r in rows:
        if r.quality_status not in selection.quality:
            excluded[r.quality_status] = excluded.get(r.quality_status, 0) + 1
        elif r.amount is None or getattr(r, column) is None or getattr(r, column) <= 0:
            excluded[f"no_{column}"] = excluded.get(f"no_{column}", 0) + 1
        else:
            used.append(r)
    base = dict(selection=selection, denominator=denominator, currency=used[0].currency if used else "USD",
                rows_excluded=excluded, rows_used=[r.benchmark_id for r in used],
                carriers=sorted({r.carrier_code for r in used}), periods=sorted({r.period_label for r in used}),
                regions=sorted({r.region for r in used}), operation_scopes=sorted({r.operation_scope for r in used}),
                period_start=min((r.period_start for r in used), default=None),
                period_end=max((r.period_end for r in used), default=None))
    if not used:
        return BenchmarkMetric(value=None, amount_total=None, denominator_total=None, average_stage_nm=None,
                               reason="no benchmark rows match the selection and quality filter", **base)
    currencies = {r.currency for r in used}
    if len(currencies) > 1:
        return BenchmarkMetric(value=None, amount_total=None, denominator_total=None, average_stage_nm=None,
                               reason=f"mixed currencies {sorted(currencies)}", **base)
    amounts = [r.amount for r in used]
    adjustment = None
    if selection.use_adjusted_target_date is not None:
        if len(used) != 1:
            return BenchmarkMetric(value=None, amount_total=None, denominator_total=None, average_stage_nm=None,
                                   reason="index adjustment applies to single published values only", **base)
        adj = session.scalar(select(BenchmarkAdjustment).where(
            BenchmarkAdjustment.benchmark_id == used[0].benchmark_id,
            BenchmarkAdjustment.target_date == selection.use_adjusted_target_date,
            BenchmarkAdjustment.status == "adjusted").order_by(BenchmarkAdjustment.adjustment_id.desc()))
        if adj is None:
            return BenchmarkMetric(value=None, amount_total=None, denominator_total=None, average_stage_nm=None,
                                   reason="no index-adjusted value for this benchmark and target date", **base)
        amounts = [adj.adjusted_amount]
        adjustment = {"index_series_id": adj.index_series_id, "factor": plain(adj.factor),
                      "base_period": adj.base_period, "target_period": adj.target_period,
                      "original_amount": plain(adj.original_amount), "adjusted_amount": plain(adj.adjusted_amount),
                      "methodology": adj.methodology}
    total = sum(amounts, Decimal(0))
    denom = sum((getattr(r, column) for r in used), Decimal(0))
    deps = [r.departures for r in used if r.departures]
    miles = [r.aircraft_miles_nm for r in used if r.aircraft_miles_nm is not None]
    stage = (sum(miles, Decimal(0)) / sum(deps, Decimal(0))) if deps and len(miles) == len(used) else None
    return BenchmarkMetric(value=total / denom, amount_total=total, denominator_total=denom, average_stage_nm=stage,
                           adjustment=adjustment, **base)


# ---------------------------------------------------------------------------
# Comparability
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Check:
    name: str
    result: str  # pass | caveat | fail
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "result": self.result, "detail": self.detail}


@dataclass
class BenchmarkComparisonResult:
    model_metric: str
    model_value: Decimal | None
    model_unit: str
    benchmark: BenchmarkMetric
    benchmark_value_converted: Decimal | None
    benchmark_unit: str
    comparability: str
    checks: list[Check]
    fx_basis: str | None
    absolute_difference: Decimal | None = None
    percentage_difference: Decimal | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def s(v):
            return None if v is None else plain(v)
        return {"model_metric": self.model_metric, "model_value": s(self.model_value), "model_unit": self.model_unit,
                "benchmark": self.benchmark.to_dict(), "benchmark_value_converted": s(self.benchmark_value_converted),
                "benchmark_unit": self.benchmark_unit, "comparability": self.comparability,
                "checks": [c.to_dict() for c in self.checks], "reasons": self.reasons, "fx_basis": self.fx_basis,
                "absolute_difference": s(self.absolute_difference),
                "percentage_difference": s(self.percentage_difference),
                "interpretation": ("difference between the model and a differently defined public benchmark; not a "
                                   "measure of model error") if self.comparability != "comparable" else
                                  "difference against a like-for-like benchmark"}


def period_average_usd_per_eur(session: Session, start: date, end: date) -> tuple[Decimal | None, int]:
    rows = session.scalars(select(ExchangeRate.rate).where(
        ExchangeRate.base_currency == "EUR", ExchangeRate.quote_currency == "USD",
        ExchangeRate.observation_date >= start, ExchangeRate.observation_date <= end)).all()
    return (sum(rows, Decimal(0)) / len(rows) if rows else None), len(rows)


def _model_value(case: CostCase, mapping: MetricMapping, denominator: str, rtnm: Decimal | None
                 ) -> tuple[Decimal | None, list[Check]]:
    comps = case.summary.components
    checks: list[Check] = []
    applicable = [n for n in mapping.components if comps[n].status.value != "not_applicable"]
    if not applicable:
        return None, [Check("model_metric", "fail", f"{mapping.key}: not applicable in this scenario")]
    missing = [n for n in applicable if not comps[n].is_calculated]
    if missing:
        return None, [Check("model_metric", "fail", f"{mapping.key}: model component(s) unavailable: {missing}")]
    amount = sum((comps[n].amount for n in applicable), Decimal(0))
    facts = case.facts
    denom = {"block_hour": facts.block_hours, "airborne_hour": facts.airborne_hours, "revenue_tonne_nm": rtnm}[denominator]
    if denom is None or denom <= 0:
        return None, [Check("denominator", "fail", f"model {denominator} unavailable (e.g. no revenue cargo payload)")]
    na = [n for n in mapping.components if n not in applicable]
    checks.append(Check("model_metric", "pass" if not na else "caveat",
                        f"sum of {applicable} / {denominator}" + (f"; {na} not applicable (included elsewhere)" if na else "")))
    return amount / denom, checks


def _model_source_check(case: CostCase, mapping: MetricMapping, source: str) -> Check:
    comps = [case.summary.components[n] for n in mapping.components if case.summary.components[n].is_calculated]
    types = {a.source_type for c in comps for a in c.assumptions}
    refs = " ".join(a.reference or "" for c in comps for a in c.assumptions) + " ".join(
        c.source_reference or "" for c in comps)
    if "illustrative_assumption" in types:
        return Check("model_source", "fail", "model metric is built on ILLUSTRATIVE assumptions; comparing it with "
                     "a public benchmark would not validate anything")
    if source == FAA_SOURCE and "FAA" in refs:
        return Check("model_source", "fail", "circular: the model input is itself the FAA benchmark")
    if source == BTS_SOURCE and ("Form 41" in refs or "BTS" in refs):
        return Check("model_source", "fail", "circular: the model input is derived from BTS Form 41")
    if source == BTS_SOURCE and "FAA" in refs:
        return Check("model_source", "caveat", "model input is an FAA benchmark, which FAA derived from BTS Form 41 "
                     "(different period); agreement partly reflects common origin")
    qualities = {component_source_quality(c).value for c in comps}
    return Check("model_source", "pass", f"model source quality: {sorted(qualities)}")


def _period_check(pricing_date: date, metric: BenchmarkMetric) -> Check:
    start, end = metric.period_start, metric.period_end
    if start is None:
        return Check("period", "fail", "benchmark period unknown")
    if metric.adjustment:
        return Check("period", "caveat", f"benchmark {start}..{end} index-adjusted to the target window "
                     f"{metric.adjustment['target_period']} with {metric.adjustment['index_series_id']} "
                     "(see suitability status)")
    if start <= pricing_date <= end:
        return Check("period", "pass", f"pricing date {pricing_date} inside benchmark period {start}..{end}")
    gap = (pricing_date - end).days if pricing_date > end else (start - pricing_date).days
    if gap <= MAX_PERIOD_GAP_DAYS:
        return Check("period", "caveat", f"periods not aligned: pricing date {pricing_date}, benchmark {start}..{end} "
                     f"({gap} days apart; no inflation adjustment)")
    return Check("period", "fail", f"benchmark period {start}..{end} is {gap} days from pricing date {pricing_date} "
                 "and no index adjustment is applied")


def compare_with_benchmark(session: Session, case: CostCase, metric_key: str, denominator: str,
                           selection: BenchmarkSelection, aircraft_mapping: dict[str, dict[str, str]],
                           rtnm: Decimal | None = None) -> BenchmarkComparisonResult:
    mapping = MAPPINGS[metric_key]
    checks: list[Check] = []
    model_value, model_checks = _model_value(case, mapping, denominator, rtnm)
    checks += model_checks
    if model_value is not None:
        checks.append(_model_source_check(case, mapping, selection.source))
    expected_category = mapping.categories.get(selection.source)
    if expected_category is None or expected_category != selection.cost_category:
        checks.append(Check("category", "fail", f"model {metric_key} has no compatible {selection.source} category "
                            f"(selected {selection.cost_category!r})"))
    else:
        checks.append(Check("category", "caveat", "; ".join(mapping.caveats)))
    metric = benchmark_metric(session, selection, denominator)
    if metric.value is None:
        checks.append(Check("benchmark_data", "fail", metric.reason or "benchmark unavailable"))
    else:
        excl = f"; excluded rows {metric.rows_excluded}" if metric.rows_excluded else ""
        checks.append(Check("benchmark_data", "pass", f"{len(metric.rows_used)} rows, {metric.carriers}, "
                            f"{metric.periods}{excl}"))
        checks.append(_period_check(case.pricing_date, metric))
    # denominators
    if selection.source == FAA_SOURCE and denominator != "block_hour":
        checks.append(Check("denominator", "fail", "FAA Table 4-7 values are per block hour only"))
    else:
        checks.append(Check("denominator", "pass", {"block_hour": "block hours (model Part 2 block time; BTS T2 "
                            "ramp-to-ramp hours / FAA block hour)", "airborne_hour": "airborne hours (model Part 2; "
                            "BTS P-5.2 Z6500)", "revenue_tonne_nm": "revenue tonne-NM (model explicit payload x "
                            "distance; BTS revenue ton-miles converted)"}[denominator]))
    # aircraft type and operation scope
    facts = case.facts
    mapped = aircraft_mapping.get(facts.aircraft_code)
    if selection.source == FAA_SOURCE:
        checks.append(Check("aircraft_type", "caveat", "FAA class average (narrowbody >=165k lb MTOW; A320 assigned "
                            "per Table 4-16), not type-specific; fleet average over carriers"))
    elif mapped is None or mapped["mapping_status"] == "unmapped":
        checks.append(Check("aircraft_type", "fail", f"no verified BTS aircraft-type mapping for {facts.aircraft_code}"))
    elif set(selection.aircraft_type_codes) != {mapped["bts_aircraft_type"]} or (
            selection.aircraft_config or mapped["bts_aircraft_config"]) != mapped["bts_aircraft_config"]:
        checks.append(Check("aircraft_type", "fail", f"selection {selection.aircraft_type_codes}/{selection.aircraft_config} "
                            f"does not match the mapping {mapped['bts_aircraft_type']}/{mapped['bts_aircraft_config']}"))
    else:
        checks.append(Check("aircraft_type", "pass" if mapped["mapping_status"] == "exact_type_match" else "caveat",
                            f"{facts.aircraft_code} -> BTS {mapped['bts_aircraft_type']} ({mapped['bts_description']}); "
                            f"{mapped['mapping_status']}"))
    expected_scope = "passenger_configuration" if case.flight_type == "passenger" else "freight_configuration"
    scopes = metric.operation_scopes
    if scopes and not all(s.startswith(expected_scope) for s in scopes):
        checks.append(Check("operation_scope", "fail", f"model flight type {case.flight_type!r} vs benchmark {scopes}"))
    elif scopes:
        checks.append(Check("operation_scope", "pass", f"{case.flight_type} vs {scopes}"))
    if denominator == "revenue_tonne_nm" and any(sc.startswith("passenger") or sc.startswith("combi") for sc in scopes):
        checks.append(Check("traffic_definition", "fail", "BTS revenue ton-miles of passenger/combi-configured aircraft "
                            "include passenger ton-miles; the model RTNM is revenue cargo only"))
    checks.append(Check("fleet_level", "pass" if selection.source == BTS_SOURCE else "caveat",
                        "aircraft-type-level rows only (unattributed fleet expenses excluded)"
                        if selection.source == BTS_SOURCE else "published class average"))
    # geography and stage length
    flight = session.get(FlightEstimate, facts.flight_estimate_id)
    countries = {session.get(Airport, flight.origin_airport_id).country_code,
                 session.get(Airport, flight.destination_airport_id).country_code}
    if countries != {"US"}:
        checks.append(Check("geographic_scope", "caveat", f"benchmark: U.S. carriers ({metric.regions or 'US'}); model "
                            f"route {facts.origin}-{facts.destination} ({sorted(c or '?' for c in countries)}): "
                            "labour, fuel tax, charges and maintenance markets differ"))
    if metric.average_stage_nm is not None and denominator in ("block_hour", "airborne_hour"):
        ratio = facts.great_circle_nm / metric.average_stage_nm
        detail = (f"model great-circle {plain(facts.great_circle_nm.quantize(Decimal('0.1')))} NM vs benchmark "
                  f"average stage {plain(metric.average_stage_nm.quantize(Decimal('0.1')))} NM (ratio "
                  f"{plain(ratio.quantize(Decimal('0.01')))}); per-hour costs vary with stage length")
        lo, hi = STAGE_RATIO_RANGE
        checks.append(Check("stage_length", "caveat" if not lo <= ratio <= hi else "pass", detail))
    # currency
    converted, fx = metric.value, None
    currency = case.summary.reporting_currency
    if metric.value is not None and metric.currency != currency:
        if (metric.currency, currency) != ("USD", "EUR"):
            checks.append(Check("currency", "fail", f"no conversion rule {metric.currency}->{currency}"))
            converted = None
        else:
            start, end = metric.period_start, metric.period_end
            if metric.adjustment or selection.source == FAA_SOURCE:
                start = end = None
                rate_row = session.scalar(select(ExchangeRate).where(
                    ExchangeRate.base_currency == "EUR", ExchangeRate.quote_currency == "USD",
                    ExchangeRate.observation_date <= case.pricing_date).order_by(ExchangeRate.observation_date.desc()))
                if rate_row is None or (case.pricing_date - rate_row.observation_date).days > 7:
                    checks.append(Check("currency", "fail", "no ECB USD rate within 7 days of the pricing date"))
                    converted = None
                else:
                    converted = metric.value / rate_row.rate
                    fx = f"ECB USD per EUR {rate_row.rate} on {rate_row.observation_date} (model pricing date rule)"
                    checks.append(Check("currency", "caveat", f"USD benchmark converted at {fx}"))
            else:
                avg, n = period_average_usd_per_eur(session, start, end)
                if avg is None or n < MIN_FX_OBSERVATIONS:
                    checks.append(Check("currency", "fail", f"only {n} ECB USD observations in {start}..{end}"))
                    converted = None
                else:
                    converted = metric.value / avg
                    fx = (f"mean of {n} ECB daily USD-per-EUR reference rates {start}..{end} = "
                          f"{plain(avg.quantize(Decimal('0.000001')))} (simple period average)")
                    checks.append(Check("currency", "caveat", f"USD benchmark converted at the {fx}"))
    elif metric.value is not None:
        checks.append(Check("currency", "pass", f"both in {currency}"))
    failed = [c for c in checks if c.result == "fail"]
    verdict = "not_comparable" if failed else ("comparable_with_caveats" if any(c.result == "caveat" for c in checks)
                                               else "comparable")
    unit = f"{currency}/{denominator}"
    result = BenchmarkComparisonResult(f"{metric_key}_per_{denominator}", model_value, unit, metric, converted,
                                       unit if converted is not None else f"{metric.currency}/{denominator}", verdict,
                                       checks, fx, reasons=[f"{c.name}: {c.detail}" for c in failed])
    if verdict != "not_comparable" and model_value is not None and converted is not None:
        result.absolute_difference = model_value - converted
        result.percentage_difference = (model_value - converted) / converted * 100 if converted > 0 else None
    return result


def read_aircraft_mapping(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return {r["project_aircraft_code"]: r for r in csv.DictReader(handle)}


def default_selections(case: CostCase, aircraft_mapping: dict[str, dict[str, str]]
                       ) -> list[tuple[str, str, BenchmarkSelection]]:
    """Standard comparisons for a case: BTS for the mapped type and the quarter containing the pricing date, FAA."""
    out: list[tuple[str, str, BenchmarkSelection]] = []
    mapped = aircraft_mapping.get(case.facts.aircraft_code)
    quarter = f"{case.pricing_date.year}Q{(case.pricing_date.month - 1) // 3 + 1}"
    if mapped and mapped["mapping_status"] != "unmapped":
        for key, mapping in MAPPINGS.items():
            category = mapping.categories.get(BTS_SOURCE)
            if category:
                out.append((key, "block_hour", BenchmarkSelection(BTS_SOURCE, category, (mapped["bts_aircraft_type"],),
                                                                  mapped["bts_aircraft_config"],
                                                                  period_labels=(quarter,))))
    for key, mapping in MAPPINGS.items():
        category = mapping.categories.get(FAA_SOURCE)
        if category:
            out.append((key, "block_hour", BenchmarkSelection(FAA_SOURCE, category, ("NB165K",), "1")))
    return out
