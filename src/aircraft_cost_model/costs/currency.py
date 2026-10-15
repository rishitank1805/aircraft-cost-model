"""Currency handling with ECB euro reference rates.

Quote convention: ECB publishes ``X per 1 EUR`` (e.g. USD/EUR 1.0304 means
1 EUR = 1.0304 USD). Stored as ``exchange_rate(base='EUR', quote='X', rate)``.

    EUR -> X : amount x rate(X)
    X -> EUR : amount / rate(X)
    X -> Y   : (amount / rate(X)) x rate(Y)      (cross via EUR, both rates recorded)

All arithmetic uses Decimal. Rates are selected with the pricing-date policy
in :mod:`pricing`: latest observation on or before the pricing date within the
staleness window; weekends and TARGET holidays have no ECB observation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

from sqlalchemy.orm import Session

from aircraft_cost_model.costs import repository
from aircraft_cost_model.costs.exceptions import CostInputError, ObservationUnavailableError
from aircraft_cost_model.costs.pricing import select_observation

CENT = Decimal("0.01")
_ISO_4217 = re.compile(r"^[A-Z]{3}$")


def normalize_currency(code: str | None) -> str:
    """Uppercase and validate an ISO 4217 alphabetic code (format check)."""
    if code is None or not _ISO_4217.match(str(code).strip().upper()):
        raise CostInputError(f"Invalid ISO 4217 currency code: {code!r}")
    return str(code).strip().upper()


def round_money(amount: Decimal) -> Decimal:
    """Round to cents, half up (presentation rounding applied once per component)."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def plain(value: Decimal) -> str:
    """Decimal as plain notation for reports (``1E+3`` -> ``1000``)."""
    return f"{value:f}"


def to_decimal(value: Any) -> Decimal:
    """Exact Decimal from str/int/Decimal; floats go through their shortest repr (``str``)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


@dataclass(frozen=True)
class FxQuote:
    """One selected ECB reference rate: ``rate`` units of ``currency`` per 1 EUR."""

    currency: str
    rate: Decimal
    observation_date: date
    gap_days: int
    source_id: int | None = None
    series_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"quote": f"{self.currency} per 1 EUR", "rate": str(self.rate),
                "observation_date": self.observation_date.isoformat(), "gap_days": self.gap_days,
                "series_key": self.series_key}


class RateProvider(Protocol):
    def eur_quote(self, currency: str, pricing_date: date) -> FxQuote:
        """Selected ``currency`` per EUR rate; raises :class:`ObservationUnavailableError`."""


class DatabaseRateProvider:
    """Rates from the ``exchange_rate`` table with a staleness window (default 7 days)."""

    def __init__(self, session: Session, max_staleness_days: int = 7) -> None:
        self.session = session
        self.max_staleness_days = max_staleness_days

    def eur_quote(self, currency: str, pricing_date: date) -> FxQuote:
        row = repository.latest_eur_rate_on_or_before(self.session, currency, pricing_date)
        observations = [(row.observation_date, row)] if row is not None else []
        selection = select_observation(observations, pricing_date, self.max_staleness_days)
        if not selection.ok:
            detail = f" (latest {selection.observation_date})" if selection.observation_date else ""
            raise ObservationUnavailableError(
                f"No ECB {currency}/EUR rate within {self.max_staleness_days} days on or before {pricing_date}{detail}",
                selection.reason or "unavailable",
            )
        r = selection.value
        return FxQuote(currency, r.rate, r.observation_date, selection.gap_days or 0, r.source_id, r.series_key)


class StaticRateProvider:
    """Fixed rates (``{currency: (rate, observation_date)}``) for tests and explicit scenarios."""

    def __init__(self, rates: dict[str, tuple[Decimal, date]], max_staleness_days: int = 7) -> None:
        self.rates = rates
        self.max_staleness_days = max_staleness_days

    def eur_quote(self, currency: str, pricing_date: date) -> FxQuote:
        if currency not in self.rates:
            raise ObservationUnavailableError(f"No rate for {currency}", "no_observation_on_or_before")
        rate, obs = self.rates[currency]
        selection = select_observation([(obs, rate)], pricing_date, self.max_staleness_days)
        if not selection.ok:
            raise ObservationUnavailableError(f"{currency} rate unusable: {selection.reason}", selection.reason or "")
        return FxQuote(currency, rate, obs, selection.gap_days or 0)


@dataclass(frozen=True)
class Conversion:
    """A currency conversion with every step recorded."""

    amount_in: Decimal
    from_currency: str
    amount_out: Decimal
    to_currency: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    quotes: list[FxQuote] = field(default_factory=list)


def convert(amount: Decimal, from_currency: str, to_currency: str, pricing_date: date,
            provider: RateProvider) -> Conversion:
    """Convert ``amount`` using ECB EUR reference rates (see module docstring for direction)."""
    src, dst = normalize_currency(from_currency), normalize_currency(to_currency)
    if src == dst:
        return Conversion(amount, src, amount, dst, [{"step": "no conversion", "currency": src}])
    steps: list[dict[str, Any]] = []
    quotes: list[FxQuote] = []
    eur = amount
    if src != "EUR":
        q = provider.eur_quote(src, pricing_date)
        eur = amount / q.rate
        quotes.append(q)
        steps.append({"step": f"{src} -> EUR", "operation": f"divide by {q.rate} {src} per EUR", **q.to_dict(),
                      "result": plain(eur)})
    out = eur
    if dst != "EUR":
        q = provider.eur_quote(dst, pricing_date)
        out = eur * q.rate
        quotes.append(q)
        steps.append({"step": f"EUR -> {dst}", "operation": f"multiply by {q.rate} {dst} per EUR", **q.to_dict(),
                      "result": plain(out)})
    return Conversion(amount, src, out, dst, steps, quotes)
