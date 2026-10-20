"""Database queries for priced reference data (no pricing logic here)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from aircraft_cost_model.models import (
    AirportTariff,
    DataSource,
    ExchangeRate,
    FuelPrice,
    NavigationRate,
    NavigationZoneAerodrome,
)


def latest_fuel_price_on_or_before(session: Session, series: str, period: str, pricing_date: date) -> FuelPrice | None:
    """Latest observation of ``series`` dated on or before ``pricing_date`` (never a future observation)."""
    return session.scalar(
        select(FuelPrice)
        .where(FuelPrice.series_identifier == series, FuelPrice.observation_period == period,
               FuelPrice.observation_date <= pricing_date)
        .order_by(FuelPrice.observation_date.desc())
        .limit(1)
    )


def latest_eur_rate_on_or_before(session: Session, quote_currency: str, pricing_date: date) -> ExchangeRate | None:
    """Latest ECB EUR reference rate for ``quote_currency`` on or before ``pricing_date``."""
    return session.scalar(
        select(ExchangeRate)
        .where(ExchangeRate.base_currency == "EUR", ExchangeRate.quote_currency == quote_currency,
               ExchangeRate.observation_date <= pricing_date)
        .order_by(ExchangeRate.observation_date.desc())
        .limit(1)
    )


def navigation_rates_in_force(session: Session, zone: str, pricing_date: date,
                              charge_type: str = "en_route") -> list[NavigationRate]:
    """All unit-rate versions for ``zone`` whose validity covers ``pricing_date`` (normally one)."""
    return list(session.scalars(
        select(NavigationRate).where(
            NavigationRate.charging_zone == zone,
            NavigationRate.charge_type == charge_type,
            NavigationRate.valid_from <= pricing_date,
            or_(NavigationRate.valid_to.is_(None), NavigationRate.valid_to >= pricing_date),
        )
    ))


def terminal_zones_for_aerodrome(session: Session, icao: str, pricing_date: date) -> list[str]:
    """Terminal charging zones listing aerodrome ``icao`` on ``pricing_date``."""
    return sorted(set(session.scalars(
        select(NavigationZoneAerodrome.charging_zone).where(
            NavigationZoneAerodrome.aerodrome_icao == icao,
            NavigationZoneAerodrome.valid_from <= pricing_date,
            or_(NavigationZoneAerodrome.valid_to.is_(None), NavigationZoneAerodrome.valid_to >= pricing_date),
        )
    )))


def airport_tariffs_in_force(session: Session, airport_id: int, tariff_type: str, pricing_date: date) -> list[AirportTariff]:
    """All tariff versions for an airport and type whose validity covers ``pricing_date``."""
    return list(session.scalars(
        select(AirportTariff).where(
            AirportTariff.airport_id == airport_id,
            AirportTariff.tariff_type == tariff_type,
            AirportTariff.valid_from <= pricing_date,
            or_(AirportTariff.valid_to.is_(None), AirportTariff.valid_to >= pricing_date),
        )
    ))


def source_label(session: Session, source_id: int | None) -> str | None:
    if source_id is None:
        return None
    source = session.get(DataSource, source_id)
    return None if source is None else f"{source.source_name} / {source.dataset_name} ({source.source_version})"
