"""EIA fuel-price parsing, validation, idempotent loading and pricing-date selection (offline)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aircraft_cost_model.costs import repository
from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.costs.pricing import REASON_NONE_BEFORE, REASON_STALE, select_observation
from aircraft_cost_model.ingestion import fuel_prices as fp
from aircraft_cost_model.models import DataSource, FuelPrice
from conftest import COST_FIXTURES, _snapshot

EXCERPT = COST_FIXTURES / "eia_jet_2025-01_excerpt.xls"


def test_valid_source_file_parses_exact_decimals():
    parsed = fp.parse_eia_xls(EXCERPT)
    assert parsed.series_identifier == "EER_EPJK_PF4_RGC_DPG"
    assert "(Dollars per Gallon)" in parsed.description
    by_date = {r["observation_date"]: r["price"] for r in parsed.rows}
    assert by_date[date(2025, 1, 15)] == Decimal("2.463")
    assert all(isinstance(v, Decimal) for v in by_date.values())
    assert date(2025, 1, 9) not in by_date  # no EIA observation that day (market closed)
    assert fp.validate_fuel_prices(parsed).passed


@pytest.mark.parametrize("name, match", [("synthetic_eia_wrong_unit.xls", "unit label"),
                                         ("synthetic_eia_wrong_series.xls", "series")])
def test_schema_changes_rejected(name, match):
    with pytest.raises(SourceSchemaError, match=match):
        fp.parse_eia_xls(COST_FIXTURES / name)


def test_missing_negative_and_duplicate_observations():
    parsed = fp.parse_eia_xls(COST_FIXTURES / "synthetic_eia_dirty.xls")
    assert parsed.blank_observations == 1
    validation = fp.validate_fuel_prices(parsed)
    assert [reason for _, reason in validation.rejected] == ["value is not positive"]
    assert not validation.passed and any("duplicate" in e for e in validation.errors)


def test_invalid_unit_rows_rejected():
    rows = [{"observation_date": date(2025, 1, 2), "price": Decimal("2.1"), "price_unit": "USD/bbl"}]
    validation = fp.validate_fuel_prices(fp.ParsedFuelPrices("EER_EPJK_PF4_RGC_DPG", "x", rows))
    assert validation.rejected and "unit" in validation.rejected[0][1]


def test_api_json_parser():
    parsed = fp.parse_eia_api_json(COST_FIXTURES / "synthetic_eia_api_response.json")
    assert [r["price"] for r in parsed.rows] == [Decimal("2.385"), Decimal("2.365"), Decimal("2.463")]


def test_api_key_missing_error_is_schema_error(tmp_path):
    path = tmp_path / "err.json"
    path.write_text('{"error": {"code": "API_KEY_MISSING"}}', encoding="utf-8")
    with pytest.raises(SourceSchemaError, match="API_KEY_MISSING"):
        fp.parse_eia_api_json(path)


def test_offline_snapshot_ingestion_is_idempotent(engine):
    snap = _snapshot(EXCERPT)
    parsed = fp.parse_snapshot(snap)
    first = fp.load_fuel_prices(engine, parsed, fp.validate_fuel_prices(parsed), snap)
    second = fp.load_fuel_prices(engine, parsed, fp.validate_fuel_prices(parsed), snap)
    assert first == (15, 0, 0) and second == (0, 0, 15)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(FuelPrice)) == 15
        row = session.scalar(select(FuelPrice).where(FuelPrice.observation_date == date(2025, 1, 15)))
        assert row.price == Decimal("2.463") and row.price_unit == "USD/USgal" and row.currency == "USD"
        assert session.get(DataSource, row.source_id).license.startswith("U.S. government work")


def test_historical_selection_never_uses_future_or_latest(engine):
    snap = _snapshot(EXCERPT)
    parsed = fp.parse_snapshot(snap)
    fp.load_fuel_prices(engine, parsed, fp.validate_fuel_prices(parsed), snap)
    with Session(engine) as session:
        row = repository.latest_fuel_price_on_or_before(session, "EER_EPJK_PF4_RGC_DPG", "daily", date(2025, 1, 9))
        assert row.observation_date == date(2025, 1, 8)  # prior day, not 1-10 and not the latest (1-24)
        assert repository.latest_fuel_price_on_or_before(session, "EER_EPJK_PF4_RGC_DPG", "daily",
                                                         date(2025, 1, 1)) is None


def test_selection_policy_staleness_and_gap():
    obs = [(date(2025, 1, 8), "a"), (date(2025, 1, 10), "b"), (date(2025, 1, 24), "future")]
    s = select_observation(obs, date(2025, 1, 12), 7)
    assert s.ok and s.value == "b" and s.gap_days == 2
    stale = select_observation(obs, date(2025, 1, 20), 7)
    assert stale.ok is False and stale.reason == REASON_STALE and stale.observation_date == date(2025, 1, 10)
    assert select_observation(obs, date(2025, 1, 20), 10).value == "b"
    assert select_observation(obs, date(2025, 1, 1), 7).reason == REASON_NONE_BEFORE
    with pytest.raises(ValueError):
        select_observation(obs, date(2025, 1, 1), -1)
