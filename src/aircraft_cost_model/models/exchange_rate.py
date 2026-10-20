"""``exchange_rate``: official reference exchange rates (Part 3)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aircraft_cost_model.models.base import Base, TimestampMixin
from aircraft_cost_model.models.types import DecimalText


class ExchangeRate(TimestampMixin, Base):
    """``rate`` units of ``quote_currency`` per 1 unit of ``base_currency`` on ``observation_date``.

    ECB euro reference rates are stored with ``base_currency='EUR'``; e.g.
    base EUR, quote USD, rate 1.0304 means 1 EUR = 1.0304 USD.
    """

    __tablename__ = "exchange_rate"
    __table_args__ = (
        UniqueConstraint("base_currency", "quote_currency", "observation_date", name="uq_exchange_rate_obs"),
        Index("ix_exchange_rate_pair_date", "base_currency", "quote_currency", "observation_date"),
    )

    exchange_rate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    series_key: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
