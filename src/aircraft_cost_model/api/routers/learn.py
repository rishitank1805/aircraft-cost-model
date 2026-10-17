"""Aviation Knowledge Hub and Cargo & P2F Explorer content (version-controlled JSON with references)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.api.db import get_session
from aircraft_cost_model.api.specs import SPEC_META, aircraft_specs
from aircraft_cost_model.models import AircraftType

router = APIRouter(tags=["learn"])
CONTENT = Path(__file__).resolve().parents[1] / "content"


@lru_cache(maxsize=None)
def _load(name: str) -> dict[str, Any]:
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


@router.get("/glossary")
def glossary(q: str | None = Query(None, max_length=60), category: str | None = None) -> dict[str, Any]:
    topics = _load("glossary.json")["topics"]
    if q:
        needle = q.lower()
        topics = [t for t in topics if needle in (t["term"] + " " + " ".join(t["aliases"]) + " " + t["definition"]).lower()]
    if category:
        topics = [t for t in topics if t["category"] == category]
    return {"count": len(topics), "categories": sorted({t["category"] for t in _load("glossary.json")["topics"]}),
            "topics": topics}


@router.get("/glossary/{slug}")
def glossary_topic(slug: str) -> dict[str, Any]:
    topic = next((t for t in _load("glossary.json")["topics"] if t["slug"] == slug), None)
    if topic is None:
        raise HTTPException(404, f"unknown glossary topic {slug!r}")
    return topic


@router.get("/cargo")
def cargo(session: Session = Depends(get_session)) -> dict[str, Any]:
    from aircraft_cost_model.api.routers.aircraft import flight_model_status

    content = dict(_load("cargo.json"))
    targets = []
    for t in content["targets"]:
        aircraft = session.scalar(select(AircraftType).where(AircraftType.aircraft_code == t["code"]))
        specs = aircraft_specs(session, aircraft) if aircraft else None
        facts = []
        if specs:
            for key in ("max_structural_payload_kg", "published_range_nm", "published_range_km", "mzfw_kg",
                        "main_deck_capacity", "lower_deck_capacity", "main_deck_cargo_door", "cargo_volume_m3",
                        "cargo_capacity_statement"):
                v = specs.primary(key)
                if v is not None:
                    facts.append(v.to_dict())
        targets.append({**t, "name": f"{aircraft.manufacturer} {aircraft.model}" if aircraft else t["code"],
                        "flight_model_supported": bool(aircraft) and flight_model_status(aircraft)["supported"],
                        "published_facts": facts, "missing": specs.missing if specs else {},
                        "missing_labels": sorted({SPEC_META[k].label if k in SPEC_META else k
                                                  for keys in (specs.missing.values() if specs else []) for k in keys})})
    content["targets"] = targets
    return content
