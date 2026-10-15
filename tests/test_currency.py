"""ECB quote direction, non-publication days, staleness and Decimal precision."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aircraft_cost_model.costs.currency import (
    DatabaseRateProvider,
    StaticRateProvider,
    convert,
    normalize_currency,
    round_money,
)
from aircraft_cost_model.costs.exceptions import CostInputError, ObservationUnavailableError
from aircraft_cost_model.ingestion import exchange_rates as er
from conftest import COST_FIXTURES, _snapshot

D = date(2025, 1, 15)
RATES = StaticRateProvider({"USD": (Decimal("1.0300"), D), "GBP": (Decimal("0.84"), D)})


def test_eur_to_usd_multiplies_and_usd_to_eur_divides():
    assert convert(Decimal("100"), "EUR", "USD", D, RATES).amount_out == Decimal("103.00")
    back = convert(Decimal("103.00"), "USD", "EUR", D, RATES)
    assert back.amount_out == Decimal("100")
    assert "divide" in back.steps[0]["operation"]


def test_cross_rate_via_eur_records_both_quotes():
    result = convert(Decimal("103"), "USD", "GBP", D, RATES)
    assert result.amount_out == Decimal("84.00")
    assert [q.currency for q in result.quotes] == ["USD", "GBP"]


def test_identity_and_iso_validation():
    assert convert(Decimal("1.23"), "eur", "EUR", D, RATES).amount_out == Decimal("1.23")
    for bad in ("EURO", "us", "", None, "12A"):
        with pytest.raises(CostInputError):
            normalize_currency(bad)


def test_decimal_precision_and_rounding():
    amount = Decimal("1841.691736187037554318614733")
    out = convert(amount, "USD", "EUR", D, RATES).amount_out
    assert out == amount / Decimal("1.0300")
    assert round_money(Decimal("2.345")) == Decimal("2.35") and round_money(Decimal("2.344999")) == Decimal("2.34")
    assert isinstance(out, Decimal)


def test_ecb_csv_parse_and_weekend_holiday_handling(engine):
    snap = _snapshot(COST_FIXTURES / "ecb_exr_2025-01_excerpt.csv")
    parsed = er.parse_ecb_csv(snap.path)
    assert parsed.currencies == ["CHF", "GBP", "USD"]
    er.load_exchange_rates(engine, parsed, er.validate_rates(parsed), snap)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        provider = DatabaseRateProvider(session, max_staleness_days=7)
        assert provider.eur_quote("USD", D).rate == Decimal("1.03")  # ECB publishes 1.03 for 2025-01-15
        saturday = provider.eur_quote("USD", date(2025, 1, 11))
        assert saturday.observation_date == date(2025, 1, 10) and saturday.gap_days == 1
        assert saturday.rate == Decimal("1.0304")
        with pytest.raises(ObservationUnavailableError) as exc:
            provider.eur_quote("USD", date(2025, 1, 1))  # before first observation (and 1 Jan is a TARGET holiday)
        assert exc.value.reason == "no_observation_on_or_before"
        with pytest.raises(ObservationUnavailableError) as stale:
            DatabaseRateProvider(session, 3).eur_quote("USD", date(2025, 2, 10))
        assert stale.value.reason == "stale"
        with pytest.raises(ObservationUnavailableError):
            provider.eur_quote("JPY", D)  # missing currency


def test_ecb_unexpected_series_rejected(tmp_path):
    lines = (COST_FIXTURES / "ecb_exr_2025-01_excerpt.csv").read_text(encoding="utf-8").splitlines()
    bad = tmp_path / "bad.csv"
    bad.write_text("\n".join([lines[0], lines[1].replace(",EUR,SP00,", ",USD,SP00,")]), encoding="utf-8")
    from aircraft_cost_model.costs.exceptions import SourceSchemaError

    with pytest.raises(SourceSchemaError):
        er.parse_ecb_csv(bad)
