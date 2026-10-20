"""Part 6 read-only explorer API (FastAPI TestClient against a temporary database)."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from aircraft_cost_model.api.app import create_app
from aircraft_cost_model.models import FlightEstimate


@pytest.fixture
def client(explorer_db, tmp_path):
    engine, ids = explorer_db
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>explorer</html>")
    app = create_app(Path(engine.url.database), static_dir=static)
    with TestClient(app) as c:
        c.ids = ids
        c.app_engine = app.state.engine
        yield c


def test_health_and_read_only(client):
    assert client.get("/api/health").json()["read_only"] is True
    with pytest.raises(OperationalError, match="readonly"):
        with client.app_engine.begin() as conn:
            conn.execute(text("UPDATE aircraft_type SET model = 'x'"))


def test_library_lists_all_aircraft_with_facets(client):
    data = client.get("/api/aircraft").json()
    assert data["total"] == data["count"] > 30
    assert {"cargo", "passenger"} <= set(data["facets"]["role"])
    cargo = client.get("/api/aircraft", params={"role": "cargo"}).json()["items"]
    assert {a["code"] for a in cargo} == {"A330-200F", "B777F", "B767-300F", "B747-400F", "A321P2F"}
    assert all(a["flight_model_supported"] is False and a["image"] is None for a in cargo)
    assert client.get("/api/aircraft", params={"search": "a321p2f"}).json()["count"] == 1
    assert client.get("/api/aircraft", params={"engine_count": 99}).status_code == 422


def test_detail_never_promotes_inconsistent_values_and_lists_missing(client):
    d = client.get("/api/aircraft/A330-200F").json()
    mtow = [v for v in d["sections"]["weights"] if v["key"] == "mtow_kg"]
    assert mtow and not any(v["primary"] for v in mtow) and mtow[0]["verification_status"] == "source_inconsistent"
    assert "oew_kg" in d["missing"]["weights"] and d["summary"]["mtow_kg"] is None
    assert any(r["code"] == "A332" and "not this freighter" in r["warning"] for r in d["related"])
    assert d["freighter_programme"]["freighter_type"] == "production_freighter"
    assert client.get("/api/aircraft/NOPE").status_code == 404


def test_detail_values_carry_full_provenance(client):
    d = client.get("/api/aircraft/A320").json()
    for values in d["sections"].values():
        for v in values:
            assert v["source_type"] and v["verification_status"] and v["source_name"]
    lengths = [v for v in d["sections"]["dimensions"] if v["key"] == "length_m"]
    assert lengths[0]["source_dataset"] == "faa_aircraft_characteristics_database" and lengths[0]["unit"] == "m"
    assert d["flight_model"]["supported"] is True and d["role"]["role"] == "passenger"


def test_compare_rules(client):
    assert client.get("/api/compare", params={"codes": "A320"}).status_code == 422
    assert client.get("/api/compare", params={"codes": "A320,A320"}).status_code == 422
    rows = {r["key"]: r for r in client.get("/api/compare", params={"codes": "A320,A321"}).json()["rows"]}
    assert rows["length_m"]["like_for_like"] is True
    mixed = {r["key"]: r for r in client.get("/api/compare", params={"codes": "A320,A330-200F"}).json()["rows"]}
    assert mixed["length_m"]["like_for_like"] is False
    assert any("different sources" in i for i in mixed["length_m"]["issues"])


def test_glossary_and_cargo_content(client):
    topics = client.get("/api/glossary").json()["topics"]
    assert len(topics) >= 20
    for t in topics:
        assert t["definition"] and t["why_it_matters"] and t["example"] and t["references"] and t["basis"]
    assert client.get("/api/glossary", params={"q": "zero-fuel"}).json()["count"] >= 1
    assert client.get("/api/glossary/unknown").status_code == 404
    cargo = client.get("/api/cargo").json()
    types = {t["code"]: t["freighter_type"] for t in cargo["targets"]}
    assert types.pop("A321P2F") == "converted_freighter" and set(types.values()) == {"production_freighter"}
    assert "not affiliated" in cargo["disclaimer"] and "Airbus" not in cargo["disclaimer"] and len(cargo["conversion_steps"]) == 7


def test_flight_lab_matches_part2_and_saves_nothing(client):
    from sqlalchemy.orm import Session

    with Session(client.app_engine) as s:
        saved = s.get(FlightEstimate, 1)
        before = s.query(FlightEstimate).count()
    r = client.post("/api/flight/estimate", json={"aircraft_code": "A320", "origin": "FRA", "destination": "CDG", "payload_kg": 10000})
    body = r.json()
    assert r.status_code == 200 and body["saved"] is False
    assert body["fuel_kg"]["block"] == pytest.approx(saved.block_fuel_kg)
    assert body["times_min"]["block"] == pytest.approx(saved.block_time_min)
    with Session(client.app_engine) as s:
        assert s.query(FlightEstimate).count() == before
    assert client.post("/api/flight/estimate", json={"aircraft_code": "B777F", "origin": "FRA", "destination": "CDG",
                                                     "payload_kg": 1000}).status_code == 422
    assert client.post("/api/flight/estimate", json={"aircraft_code": "A320", "origin": "FRA", "destination": "CDG",
                                                     "payload_kg": -5}).status_code == 422
    assert len(client.get("/api/flight/aircraft").json()["items"]) == 16
    assert client.get("/api/airports/search", params={"q": "CDG"}).json()["items"][0]["iata"] == "CDG"



def test_economics_keeps_partial_labels(client):
    full = client.ids["full"]
    d = client.get(f"/api/economics/estimates/{full}").json()
    assert d["totals"]["coc"]["calculated_subtotal"] == "3946.08" and d["totals"]["coc"]["complete"] is None
    labels = {m["label"] for m in d["unit_metrics"]}
    assert "Partial COC per block hour" in labels
    assert client.get(f"/api/economics/estimates/{full}/sensitivity", params={"parameter": "nope"}).status_code == 422
    s = client.get(f"/api/economics/estimates/{full}/sensitivity", params={"levels": "0,10"}).json()
    assert s["rows"][1]["outputs"]["coc"] == "4124.89"


def test_static_files_cannot_escape(client):
    assert client.get("/aircraft/A320").text == "<html>explorer</html>"
    assert client.get("/..%2f..%2fetc%2fpasswd").text == "<html>explorer</html>"
    assert client.get("/api/unknown").status_code == 404

