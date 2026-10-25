"""Aircraft library, detail and comparison endpoints (read-only)."""

from __future__ import annotations

import csv
import re
from decimal import Decimal
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.api.db import get_session
from aircraft_cost_model.api.specs import (
    SPEC_META,
    AircraftSpecs,
    _sources,
    aircraft_specs,
    latest_source_ids,
    role_of,
)
from aircraft_cost_model.models import AircraftType

router = APIRouter(tags=["aircraft"])

COMPARE_KEYS = ("length_m", "wingspan_m", "height_m", "wing_area_m2", "mtow_kg", "mlw_kg", "oew_kg", "mzfw_kg",
                "max_structural_payload_kg", "fuel_capacity_l", "engine_count", "engine_model", "rated_thrust_kn",
                "bypass_ratio", "cruise_mach", "cruise_speed_kt", "ceiling_m", "nominal_cruise_range_km",
                "published_range_nm", "published_range_km", "body_class", "freighter_type", "main_deck_capacity",
                "lower_deck_capacity", "cargo_volume_m3")
WHY_IT_MATTERS = {
    "length_m": "A longer fuselage fits more seats or cargo positions, but needs more room at the gate.",
    "wingspan_m": "Wingspan decides which gates and taxiways the aircraft can use (FAA Airplane Design Group).",
    "height_m": "Tail height matters for hangars, and it also counts towards the FAA Airplane Design Group.",
    "mtow_kg": "MTOW caps payload and fuel together, and landing and navigation charges are based on it.",
    "mzfw_kg": "MZFW limits how much payload can be loaded.",
    "max_structural_payload_kg": "The most the structure can carry. A real flight's paid load is usually less.",
    "rated_thrust_kn": "Thrust sets how well the aircraft takes off and climbs.",
    "published_range_nm": "A range only means something together with the payload it assumes.",
    "fuel_capacity_l": "Fuel capacity limits how far the aircraft can fly once payload is reduced.",
}


def series_of(model: str | None) -> str | None:
    """Model series derived from the designation (e.g. '737-800' -> '737', 'A320neo' -> 'A320')."""
    if not model:
        return None
    match = re.match(r"([A-Z]*\d{3})", model.replace(" ", ""))
    return match.group(1) if match else None


@lru_cache(maxsize=1)
def _provider():
    from aircraft_cost_model.performance.openap_adapter import OpenAPPerformanceProvider

    return OpenAPPerformanceProvider()


def flight_model_status(aircraft: AircraftType) -> dict[str, Any]:
    if not aircraft.openap_supported:
        return {"supported": False, "reasons": [f"OpenAP has no performance model for the {aircraft.aircraft_code}, and "
                                                "a passenger version isn't used in its place."]}
    meta = _provider().get_model_metadata(aircraft.aircraft_code)
    return {"supported": meta.supported, "reasons": list(meta.unsupported_reasons),
            "description": meta.describe() if meta.supported else None}


def _mapping_csv(request: Request, name: str) -> list[dict[str, str]]:
    path = request.app.state.settings.reference_dir / name
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summary(specs: AircraftSpecs, flight: dict[str, Any]) -> dict[str, Any]:
    a = specs.aircraft
    role = role_of(specs)
    mtow = specs.primary("mtow_kg")
    expected = sum(len(v) for v in (("length_m", "wingspan_m", "height_m"), ("mtow_kg", "oew_kg", "mzfw_kg"),
                                     ("engine_model", "rated_thrust_kn"), ("cruise_mach", "ceiling_m")))
    present = sum(1 for k in ("length_m", "wingspan_m", "height_m", "mtow_kg", "oew_kg", "mzfw_kg", "engine_model",
                              "rated_thrust_kn", "cruise_mach", "ceiling_m") if specs.primary(k) is not None)
    engine_count = specs.primary("engine_count")
    return {
        "code": a.aircraft_code, "name": f"{a.manufacturer or ''} {a.model or a.aircraft_code}".strip(),
        "manufacturer": a.manufacturer, "model": a.model, "variant": a.variant,
        "icao_type_designator": a.icao_type_designator,
        "series": series_of(a.model), "series_basis": "read from the model name",
        "role": role["role"], "freighter_type": role["freighter_type"],
        "body_class": specs.text("body_class"),
        "engine_count": int(engine_count.value) if engine_count and engine_count.value is not None else None,
        "engine_model": specs.text("engine_model"),
        "mtow_kg": float(mtow.value) if mtow and mtow.value is not None else None,
        "mtow_source": mtow.source_dataset if mtow else None,
        "aircraft_data": a.openap_coverage, "flight_model_supported": flight["supported"],
        "key_spec_coverage": {"present": present, "expected": expected},
        "image": None,
    }


def _all(session: Session) -> list[tuple[AircraftSpecs, dict[str, Any]]]:
    sources, latest = _sources(session), latest_source_ids(session)
    out = []
    for a in session.scalars(select(AircraftType).order_by(AircraftType.manufacturer, AircraftType.aircraft_code)):
        out.append((aircraft_specs(session, a, sources, latest), flight_model_status(a)))
    return out


@router.get("/aircraft")
def list_aircraft(session: Session = Depends(get_session), search: str | None = Query(None, max_length=60),
                  manufacturer: str | None = None, series: str | None = None, role: str | None = None,
                  freighter_type: str | None = None, body_class: str | None = None,
                  engine_count: int | None = Query(None, ge=1, le=8),
                  flight_model: bool | None = None) -> dict[str, Any]:
    rows = [summary(s, f) for s, f in _all(session)]
    facets = {key: sorted({str(r[key]) for r in rows if r[key] is not None})
              for key in ("manufacturer", "series", "role", "freighter_type", "body_class", "engine_count")}

    def keep(r: dict[str, Any]) -> bool:
        if search and search.lower() not in f"{r['code']} {r['name']} {r['icao_type_designator']}".lower():
            return False
        for key, value in (("manufacturer", manufacturer), ("series", series), ("role", role),
                           ("freighter_type", freighter_type), ("body_class", body_class)):
            if value is not None and str(r[key]) != value:
                return False
        if engine_count is not None and r["engine_count"] != engine_count:
            return False
        return flight_model is None or r["flight_model_supported"] == flight_model
    items = [r for r in rows if keep(r)]
    return {"total": len(rows), "count": len(items), "items": items, "facets": facets,
            "notes": ["Anything we don't know is shown as unavailable. Nothing is filled in or guessed.",
                      "Body type comes from the FAA Economic Values.",
                      "The model series is read from the model name.",]}


def _get(session: Session, code: str) -> AircraftType:
    aircraft = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == code))
    if aircraft is None:
        raise HTTPException(404, f"unknown aircraft code {code!r}")
    return aircraft


def _benchmarks(request: Request, session: Session, code: str) -> dict[str, Any] | None:
    from aircraft_cost_model.analytics.benchmarks import BTS_SOURCE, BenchmarkSelection, benchmark_metric
    from aircraft_cost_model.models import BenchmarkObservation

    mapping = {r["project_aircraft_code"]: r for r in _mapping_csv(request, "bts_aircraft_type_mapping.csv")}
    m = mapping.get(code)
    if m is None or m["mapping_status"] == "unmapped" or not m["bts_aircraft_type"]:
        return None
    periods = sorted({p for (p,) in session.execute(select(BenchmarkObservation.period_label).where(
        BenchmarkObservation.benchmark_source == BTS_SOURCE, BenchmarkObservation.period_label.like("2025%")).distinct())})
    if not periods:
        return None
    metrics = {}
    for category in ("aircraft_operating_total", "fuel", "maintenance_total", "pilots_and_copilots"):
        r = benchmark_metric(session, BenchmarkSelection(BTS_SOURCE, category, (m["bts_aircraft_type"],),
                                                         m["bts_aircraft_config"], period_labels=tuple(periods)),
                             "block_hour")
        metrics[category] = None if r.value is None else {"usd_per_block_hour": float(r.value), "carriers": r.carriers,
                                                          "rows": len(r.rows_used), "periods": r.periods}
    return {"bts_type": m["bts_aircraft_type"], "bts_config": m["bts_aircraft_config"],
            "bts_description": m["bts_description"], "mapping_status": m["mapping_status"], "mapping_notes": m["notes"],
            "metrics": metrics,
            "label": "BTS Form 41: what U.S. carriers reported spending in 2025. It's a benchmark, not a cost "
                     "estimate for any particular route"}


def related_types(session: Session, aircraft: AircraftType) -> list[dict[str, str]]:
    out = []
    if aircraft.openap_related_code:
        rel = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == aircraft.openap_related_code))
        out.append({"code": aircraft.openap_related_code, "relation": "the passenger aircraft it's based on",
                    "available": rel is not None,
                    "warning": "Its specifications are for the passenger aircraft, not this freighter."})
    for f in session.scalars(select(AircraftType).where(AircraftType.openap_related_code.in_(
            [aircraft.aircraft_code, aircraft.icao_type_designator or ""]))):
        if f.aircraft_code != aircraft.aircraft_code:
            out.append({"code": f.aircraft_code, "relation": "freighter version of this aircraft",
                        "available": True, "warning": None})
    return out


def describe(specs: AircraftSpecs, role: dict[str, Any]) -> list[dict[str, str]]:
    """Short educational description assembled only from sourced values."""
    a = specs.aircraft
    out = []
    name = f"{a.manufacturer or ''} {a.model or a.aircraft_code}".strip()
    body = specs.primary("body_class")
    if body:
        out.append({"text": f"The {name} is classified as a {body.value_text.replace('_', ' ')} aircraft.",
                    "source": body.source_reference or ""})
    engines = specs.primary("engine_count")
    etype = specs.primary("engine_type")
    if engines and engines.value is not None:
        kind = f" {etype.value_text}" if etype and etype.value_text else ""
        source = engines.source_reference or ""
        if kind and etype.source_reference and etype.source_reference != engines.source_reference:
            source += f"; engine type: {etype.source_reference}"
        out.append({"text": f"It has {int(engines.value)}{kind} engines.", "source": source})
    if role["freighter_type"] == "production_freighter":
        out.append({"text": "It is a production (purpose-built) freighter.", "source": specs.primary("freighter_type").source_reference or ""})
    elif role["freighter_type"] == "converted_freighter":
        base = specs.text("base_aircraft")
        out.append({"text": f"It is a passenger-to-freighter conversion{f' of the {base}' if base else ''}.",
                    "source": specs.primary("freighter_type").source_reference or ""})
    elif role["role"] == "passenger":
        seats = specs.primary("max_seats")
        if seats and seats.value is not None:
            out.append({"text": f"OpenAP gives it up to {int(seats.value)} passenger seats.",
                        "source": "OpenAP aircraft data (model data)"})
    return out


@router.get("/aircraft/{code}")
def aircraft_detail(code: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    aircraft = _get(session, code)
    specs = aircraft_specs(session, aircraft)
    flight = flight_model_status(aircraft)
    role = role_of(specs)
    sections: dict[str, list[dict[str, Any]]] = {}
    for v in specs.values:
        sections.setdefault(v.section, []).append(v.to_dict())
    programme = next((r for r in _mapping_csv(request, "freighter_programs.csv") if r["aircraft_code"] == code), None)
    return {
        "summary": summary(specs, flight), "role": role, "description": describe(specs, role),
        "sections": sections, "missing": specs.missing,
        "missing_labels": {k: SPEC_META[k].label if k in SPEC_META else k for keys in specs.missing.values() for k in keys},
        "flight_model": flight, "related": related_types(session, aircraft),
        "freighter_programme": programme, "benchmarks": _benchmarks(request, session, code),
        "notes": aircraft.notes,
        "data_policy": ["Every value comes with its source, its unit, the type of source, how it was checked and "
                        "the variant it applies to.",
                        "OpenAP figures are model values, not certified specifications.",
                        "A passenger aircraft's figures are never shown as a freighter's.",
                        "Missing values are left empty, not estimated."],
    }


@router.get("/compare")
def compare(codes: str = Query(..., description="2 or 3 comma-separated aircraft codes"),
            session: Session = Depends(get_session)) -> dict[str, Any]:
    wanted = [c.strip() for c in codes.split(",") if c.strip()]
    if not 2 <= len(wanted) <= 3 or len(set(wanted)) != len(wanted):
        raise HTTPException(422, "Pick two or three different aircraft.")
    specs = [aircraft_specs(session, _get(session, c)) for c in wanted]
    rows = []
    for key in COMPARE_KEYS:
        cells = [s.primary(key) for s in specs]
        if all(c is None for c in cells):
            continue
        present = [c for c in cells if c is not None]
        issues = []
        if any(c is None for c in cells):
            issues.append("missing for some aircraft")
        if len({c.source_dataset for c in present}) > 1:
            issues.append("values come from different sources: " + ", ".join(sorted({c.source_dataset or "?" for c in present})))
        if len({(c.condition or "") for c in present}) > 1:
            issues.append("measured under different conditions: " + "; ".join(sorted({c.condition or "not stated" for c in present})))
        if any(c.verification_status in ("shared_designator_row", "source_inconsistent") for c in present):
            issues.append("a value is shared with other models or doesn't match its own source")
        if len({c.unit for c in present}) > 1:
            issues.append("different units")
        like_for_like = not issues
        meta = SPEC_META.get(key)
        rows.append({"key": key, "label": meta.label if meta else key, "section": meta.section if meta else "",
                     "glossary": meta.glossary if meta else None, "why_it_matters": WHY_IT_MATTERS.get(key),
                     "like_for_like": like_for_like, "issues": issues,
                     "cells": [None if c is None else c.to_dict() for c in cells]})
    return {"aircraft": [summary(s, flight_model_status(s.aircraft)) for s in specs], "rows": rows,
            "rule": "Values count as like-for-like only when they share the same source, unit and condition. "
                    "Anything else is shown with the reason it can't be compared directly."}
