"""Resolve airport identifiers against the local ``airport`` table.

Matching rules:
- Input is stripped and uppercased.
- Without a prefix, the code is matched against ``iata_code``, ``icao_code``
  (the source's dedicated ICAO column) and ``airport_ident``. ``gps_code`` and
  ``local_code`` are never used.
- If the matches point to more than one airport, :class:`AmbiguousAirportError`
  is raised listing the candidates; nothing is chosen silently. An explicit
  prefix (``iata:``, ``icao:``, ``ident:``) restricts matching to one field.
- The matched airport must have finite coordinates within valid ranges.

No data is downloaded during a lookup.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from aircraft_cost_model.models import Airport
from aircraft_cost_model.performance.exceptions import (
    AirportNotFoundError,
    AmbiguousAirportError,
    InputValidationError,
    InvalidAirportCoordinatesError,
)

_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,15}$")
_PREFIX_FIELDS = {"IATA": "iata_code", "ICAO": "icao_code", "IDENT": "airport_ident"}


@dataclass(frozen=True)
class AirportInfo:
    """Resolved airport with validated coordinates."""

    airport_id: int
    airport_ident: str
    airport_name: str | None
    airport_type: str | None
    iata_code: str | None
    icao_code: str | None
    country_code: str | None
    latitude: float
    longitude: float
    elevation_ft: float | None
    matched_field: str

    @property
    def label(self) -> str:
        """Short display label, e.g. ``FRA/EDDF Frankfurt Main Airport``."""
        codes = "/".join(c for c in (self.iata_code, self.icao_code or self.airport_ident) if c)
        return f"{codes} {self.airport_name or ''}".strip()


def normalize_airport_code(raw: str | None) -> tuple[str | None, str]:
    """Return ``(field_or_None, CODE)`` from user input such as ``" fra"`` or ``"icao:eddf"``.

    Raises:
        InputValidationError: For empty or malformed identifiers or unknown prefixes.
    """
    if raw is None or not str(raw).strip():
        raise InputValidationError("Airport identifier is missing")
    text = str(raw).strip().upper()
    field: str | None = None
    if ":" in text:
        prefix, _, text = text.partition(":")
        if prefix not in _PREFIX_FIELDS:
            raise InputValidationError(f"Unknown airport identifier prefix {prefix!r}; use iata:, icao: or ident:")
        field = _PREFIX_FIELDS[prefix]
        text = text.strip()
    if not _CODE_PATTERN.match(text):
        raise InputValidationError(f"Invalid airport identifier {raw!r}")
    return field, text


def _to_info(airport: Airport, matched_field: str) -> AirportInfo:
    lat, lon = airport.latitude, airport.longitude
    if (
        lat is None
        or lon is None
        or not (math.isfinite(lat) and math.isfinite(lon))
        or not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0)
    ):
        raise InvalidAirportCoordinatesError(
            f"Airport {airport.airport_ident} has invalid coordinates (lat={lat}, lon={lon})"
        )
    return AirportInfo(
        airport_id=airport.airport_id,
        airport_ident=airport.airport_ident,
        airport_name=airport.airport_name,
        airport_type=airport.airport_type,
        iata_code=airport.iata_code,
        icao_code=airport.icao_code,
        country_code=airport.country_code,
        latitude=float(lat),
        longitude=float(lon),
        elevation_ft=None if airport.elevation_ft is None else float(airport.elevation_ft),
        matched_field=matched_field,
    )


def get_airport(session: Session, identifier: str) -> AirportInfo:
    """Resolve one airport by IATA code, ICAO code or OurAirports identifier.

    Raises:
        InputValidationError: Malformed identifier.
        AirportNotFoundError: No match.
        AmbiguousAirportError: Matches on more than one airport.
        InvalidAirportCoordinatesError: Match has unusable coordinates.
    """
    field, code = normalize_airport_code(identifier)
    fields = [field] if field else list(_PREFIX_FIELDS.values())
    columns = [getattr(Airport, f) for f in fields]
    candidates = session.scalars(select(Airport).where(or_(*(c == code for c in columns)))).all()
    if not candidates:
        raise AirportNotFoundError(f"No airport found for {identifier!r}")
    if len(candidates) > 1:
        described = "; ".join(
            f"airport_id={a.airport_id} ident={a.airport_ident} iata={a.iata_code} icao={a.icao_code} "
            f"type={a.airport_type} name={a.airport_name!r}"
            for a in sorted(candidates, key=lambda a: a.airport_id)
        )
        raise AmbiguousAirportError(
            f"{identifier!r} matches {len(candidates)} airports ({described}). "
            "Use an explicit prefix such as ident:<code> to choose one."
        )
    airport = candidates[0]
    matched = next(f for f in fields if getattr(airport, f) == code)
    return _to_info(airport, matched)
