"""Operating Economics (advanced): Parts 3-5 results through the existing analytics functions (read-only)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import AnalyticsInputError, load_saved_case
from aircraft_cost_model.analytics.metrics import DistanceBasis, DistanceInput, unit_metrics
from aircraft_cost_model.analytics.scenarios import PARAMETERS, base_from_saved, parse_levels
from aircraft_cost_model.analytics.sensitivity import one_way
from aircraft_cost_model.api.db import get_session
from aircraft_cost_model.costs.currency import plain
from aircraft_cost_model.fullcost.aggregate import TAXONOMY, Category, component_source_quality
from aircraft_cost_model.models import (
    AircraftType,
    Airport,
    BenchmarkAdjustment,
    BenchmarkObservation,
    CostScenario,
    FlightEstimate,
    FullCostEstimate,
)

router = APIRouter(tags=["economics"])
NOTICE = ("These are estimates for one illustrative scenario, and the illustrative values are not real airline costs. "
          "When some costs are missing, the totals are marked as partial. A missing cost is never counted as zero.")


def _money(value: Decimal | None) -> str | None:
    return None if value is None else plain(value)


@router.get("/economics/estimates")
def estimates(session: Session = Depends(get_session)) -> dict[str, Any]:
    items = []
    for e in session.scalars(select(FullCostEstimate).order_by(FullCostEstimate.full_cost_estimate_id)):
        f = session.get(FlightEstimate, e.flight_estimate_id)
        a = session.get(AircraftType, f.aircraft_type_id)
        o, d = session.get(Airport, f.origin_airport_id), session.get(Airport, f.destination_airport_id)
        s = session.get(CostScenario, e.scenario_id)
        items.append({"id": e.full_cost_estimate_id, "aircraft": a.aircraft_code,
                      "route": f"{o.iata_code or o.airport_ident}-{d.iata_code or d.airport_ident}",
                      "scenario": s.name, "ownership_mode": e.ownership_mode, "pricing_date": e.pricing_date.isoformat(),
                      "currency": e.reporting_currency, "coc_subtotal": _money(e.cash_operating_subtotal),
                      "toc_subtotal": _money(e.total_operating_subtotal), "total_subtotal": _money(e.total_cost_subtotal),
                      "complete_coc": _money(e.complete_coc), "coverage": e.cost_coverage_status,
                      "operational_validity": e.operational_validity_status, "source_quality": e.source_quality_summary})
    return {"items": items, "notice": NOTICE}


@router.get("/economics/estimates/{estimate_id}")
def estimate_detail(estimate_id: int, session: Session = Depends(get_session),
                    distance_basis: Literal["great_circle", "modelled_route"] = "modelled_route") -> dict[str, Any]:
    try:
        case = load_saved_case(session, estimate_id)
    except AnalyticsInputError as exc:
        raise HTTPException(404, str(exc)) from exc
    s = case.summary
    categories = []
    for category in Category:
        cs = s.category(category)
        categories.append({"category": category.value, "calculated_subtotal": _money(cs.calculated_subtotal),
                           "complete": _money(cs.complete_amount), "missing": list(cs.missing_components),
                           "not_applicable": list(cs.not_applicable_components),
                           "components": [{"name": n, "amount": _money(s.components[n].amount),
                                           "status": s.components[n].status.value,
                                           "source_quality": component_source_quality(s.components[n]).value,
                                           "source_reference": s.components[n].source_reference}
                                          for n in TAXONOMY[category]]})
    metrics = unit_metrics(case, DistanceInput(DistanceBasis(distance_basis)))
    wanted = {"coc_per_block_hour", "toc_per_block_hour", "total_costs_per_block_hour", "coc_per_nautical_mile",
              "coc_per_revenue_tonne_nm"}
    return {"id": estimate_id, "label": case.label, "flight": case.facts.to_dict(), "scenario": case.scenario.name,
            "ownership_mode": case.ownership_mode, "pricing_date": case.pricing_date.isoformat(),
            "currency": s.reporting_currency, "categories": categories,
            "totals": {k: {"calculated_subtotal": _money(v[0]), "complete": _money(v[1]), "missing": list(v[2])}
                       for k, v in (("coc", s.coc), ("toc", s.toc), ("total_costs", s.total))},
            "dimensions": {"cost_coverage": s.cost_coverage_status, "operational_validity": s.operational_validity,
                           "source_quality": s.source_quality_summary},
            "unit_metrics": [m.to_dict() for m in metrics.metrics if m.metric_name in wanted],
            "traffic": metrics.traffic.to_dict(), "warnings": metrics.warnings, "notice": NOTICE}


@router.get("/economics/estimates/{estimate_id}/sensitivity")
def sensitivity(estimate_id: int, session: Session = Depends(get_session),
                parameter: str = Query("fuel_price"), levels: str = Query("-20,-10,0,10,20", max_length=80),
                change_type: Literal["percent", "absolute", "value"] = "percent") -> dict[str, Any]:
    if parameter not in PARAMETERS:
        raise HTTPException(422, f"unknown parameter; choose from {sorted(PARAMETERS)}")
    try:
        values = parse_levels(levels)
        if len(values) > 11:
            raise HTTPException(422, "at most 11 levels")
        base = base_from_saved(session, estimate_id, DistanceInput(DistanceBasis.MODELLED_ROUTE))
        result = one_way(session, base, parameter, change_type, values)
    except AnalyticsInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**result.to_dict(), "parameters_available": {k: v.description for k, v in PARAMETERS.items()},
            "notice": NOTICE}


@router.get("/economics/benchmarks")
def benchmarks(request: Request, session: Session = Depends(get_session),
               aircraft: str | None = Query(None, max_length=20)) -> dict[str, Any]:
    from aircraft_cost_model.api.routers.aircraft import _benchmarks

    faa = []
    for o in session.scalars(select(BenchmarkObservation).where(BenchmarkObservation.benchmark_source ==
                                                                "faa_econ_values_s4_t4_7")):
        adj = session.scalars(select(BenchmarkAdjustment).where(BenchmarkAdjustment.benchmark_id == o.benchmark_id)).all()
        faa.append({"category": o.cost_category, "amount_usd_per_block_hour": _money(o.amount), "period": o.period_label,
                    "class": o.aircraft_type_description, "notes": o.quality_notes,
                    "adjustments": [{"status": a.status, "adjusted": _money(a.adjusted_amount), "factor": _money(a.factor),
                                     "index": a.index_series_id, "target_period": a.target_period,
                                     "methodology": a.methodology, "reason": a.reason} for a in adj]})
    return {"faa_table_4_7": faa, "bts": _benchmarks(request, session, aircraft) if aircraft else None,
            "notice": "Public benchmarks are what U.S. carriers reported spending, or published averages. They aren't "
                      "estimates for a particular route. For freighters, these benchmark figures are all there is."}
