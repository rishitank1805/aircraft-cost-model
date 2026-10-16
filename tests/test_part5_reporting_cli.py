"""Reporting (CSV / JSON / PNG) and the Part 5 command-line scripts (offline, temporary database)."""

from __future__ import annotations

import csv
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from aircraft_cost_model.analytics.cases import load_saved_case
from aircraft_cost_model.analytics.metrics import DistanceBasis, DistanceInput, unit_metrics
from aircraft_cost_model.analytics.reporting import (
    chart_benchmarks,
    chart_categories,
    chart_component_breakdown,
    chart_totals,
    component_rows,
    write_csv,
    write_json,
)
from conftest import REPO_ROOT, SCENARIOS

PNG = b"\x89PNG\r\n\x1a\n"


def script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli_db(analytics_db, monkeypatch):
    engine, ids = analytics_db
    monkeypatch.setenv("ACM_DATABASE_PATH", engine.url.database)
    return engine, ids


def test_csv_and_json_exports(analytics_db, tmp_path):
    engine, ids = analytics_db
    with Session(engine) as session:
        case = load_saved_case(session, ids["full"])
    result = unit_metrics(case, DistanceInput(DistanceBasis.GREAT_CIRCLE))
    path = write_csv([m.to_dict() for m in result.metrics], tmp_path / "m.csv")
    rows = list(csv.DictReader(path.open()))
    coc = next(r for r in rows if r["metric_name"] == "coc_per_block_hour" and r["cost_measure"] == "calculated_subtotal")
    assert coc["label"] == "Partial COC per block hour" and Decimal(coc["metric_value"]) > 0
    assert coc["components_missing"] == "navigation; terminal_navigation; landing; ground_handling"
    rtnm = next(r for r in rows if r["metric_name"] == "coc_per_revenue_tonne_nm")
    assert rtnm["metric_value"] == "" and rtnm["metric_status"] == "unavailable"  # never 0
    components = list(csv.DictReader(write_csv(component_rows(case), tmp_path / "c.csv").open()))
    landing = next(r for r in components if r["component"] == "landing")
    fuel = next(r for r in components if r["component"] == "fuel")
    assert landing["amount"] == "" and landing["status"] == "unavailable_public_tariff"
    assert fuel["source_quality"] == "public_market_benchmark" and fuel["source_reference"]
    data = json.loads(write_json(result.to_dict(), tmp_path / "m.json").read_text())
    assert data["cost_coverage"] == "partial" and data["traffic"]["rtnm"] is None


def test_charts_render(analytics_db, tmp_path):
    engine, ids = analytics_db
    with Session(engine) as session:
        case = load_saved_case(session, ids["full"])
    for fn, name in ((chart_component_breakdown, "a.png"), (chart_categories, "b.png"), (chart_totals, "c.png")):
        assert fn(case, tmp_path / name).read_bytes().startswith(PNG)
    assert chart_benchmarks([], tmp_path / "d.png").read_bytes().startswith(PNG)


def test_unit_metrics_cli(cli_db, tmp_path, capsys):
    engine, ids = cli_db
    cli = script("calculate_unit_metrics")
    out = tmp_path / "metrics.json"
    assert cli.main(["--full-cost-estimate-id", str(ids["full"]), "--distance-basis", "modelled_route",
                     "--output-format", "json", "--output", str(out), "--save"]) == 0
    assert "created" in capsys.readouterr().out
    assert json.loads(out.read_text())["traffic"]["distance_basis"] == "modelled_route"
    assert cli.main(["--full-cost-estimate-id", str(ids["full"]), "--distance-basis", "modelled_route",
                     "--output-format", "json", "--output", str(out), "--save"]) == 0
    assert "reproduced exactly" in capsys.readouterr().out
    assert cli.main(["--full-cost-estimate-id", str(ids["full"]), "--distance-basis", "great_circle",
                     "--revenue-payload-t", "5"]) == 1  # passenger scenario: needs --hypothetical-cargo
    assert "hypothetical" in capsys.readouterr().out
    assert cli.main(["--full-cost-estimate-id", str(ids["full"]), "--distance-basis", "actual_flown"]) == 1
    assert cli.main(["--distance-basis", "great_circle"]) == 1  # no case given


def test_sensitivity_cli(cli_db, tmp_path, capsys):
    engine, ids = cli_db
    out = tmp_path / "fuel.csv"
    assert script("run_sensitivity_analysis").main([
        "--full-cost-estimate-id", str(ids["full"]), "--distance-basis", "great_circle", "--parameter", "fuel_price",
        "--percent-changes=-20,-10,0,10,20", "--output", str(out)]) == 0
    text = capsys.readouterr().out
    assert "not forecasts" in text and "PARTIAL" in text
    assert out.with_suffix(".png").read_bytes().startswith(PNG)
    assert len(list(csv.DictReader(out.open()))) == 6  # base + 5 levels
    grid = tmp_path / "grid.csv"
    assert script("run_sensitivity_analysis").main([
        "--full-cost-estimate-id", str(ids["full"]), "--distance-basis", "great_circle", "--parameter", "fuel_price",
        "--percent-changes=0,10", "--parameter2", "annual_utilization", "--percent-changes2=0,20",
        "--output", str(grid)]) == 0
    assert json.loads(grid.with_suffix(".json").read_text())["analysis_type"] == "sensitivity_2d"


def test_compare_and_validate_cli(cli_db, tmp_path, capsys):
    engine, ids = cli_db
    assert script("compare_cost_scenarios").main([
        "--flight-estimate-id", "1", "--variable-cost-estimate-id", str(ids["variable"]), "--scenario-files",
        str(SCENARIOS / "example_owned_aircraft.json"), str(SCENARIOS / "example_operating_lease.json"),
        "--distance-basis", "great_circle", "--ownership", "--output-dir", str(tmp_path)]) == 0
    assert "IFRS 16" in capsys.readouterr().out
    assert (tmp_path / "owned_vs_leased.png").is_file() and (tmp_path / "ownership_table.csv").is_file()
    assert script("validate_cost_estimates").main(["--full-cost-estimate-id", str(ids["full"]),
                                                    "--output", str(tmp_path / "v.json"), "--save"]) == 0
    report = json.loads((tmp_path / "v.json").read_text())
    assert report["counts"]["arithmetic"] == {"pass": 13}
    assert script("validate_cost_estimates").main(["--full-cost-estimate-id", "999"]) == 1


def test_report_generation_is_reproducible(cli_db, tmp_path):
    engine, ids = cli_db
    args = ["--full-cost-estimate-id", str(ids["full"]), "--distance-basis", "modelled_route",
            "--ownership-scenario", str(SCENARIOS / "example_operating_lease.json")]
    cli = script("generate_cost_report")
    assert cli.main(args + ["--output-dir", str(tmp_path / "a")]) == 0
    assert cli.main(args + ["--output-dir", str(tmp_path / "b")]) == 0
    a = json.loads((tmp_path / "a" / "manifest.json").read_text())
    b = json.loads((tmp_path / "b" / "manifest.json").read_text())
    assert a == b  # identical inputs -> byte-identical outputs
    assert {"01_component_breakdown.png", "03_coc_toc_total.png", "04_sensitivity_fuel_price.png",
            "05_sensitivity_airframe_maintenance_rate.png", "06_sensitivity_annual_utilization.png",
            "07_owned_vs_leased.png", "09_benchmark_comparison.png", "unit_metrics.csv", "validation.json",
            "report.txt"} <= set(a["files"])
    report = (tmp_path / "a" / "report.txt").read_text()
    assert "Partial COC per block hour" in report and "Complete COC per block hour" in report
