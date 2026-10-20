"""Part 6: per-value aircraft specifications with provenance (published, open-model and classification data).

One row = one value of one specification for one aircraft type from one
source. Several sources may report the same specification (e.g. MTOW from
OpenAP and from the FAA Aircraft Characteristics Database); they are kept side
by side and never merged. Values are stored in SI units with the original
published value and unit preserved. Missing specifications have no row.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aircraft_cost_model.models.base import Base, utc_now
from aircraft_cost_model.models.types import DecimalText

SOURCE_TYPES = (
    "published_specification",   # official publication (FAA database, manufacturer / conversion-provider page)
    "open_model_data",           # OpenAP model data (not a certified specification)
    "engine_databank",           # ICAO Engine Emissions Databank values as distributed by OpenAP
    "documented_classification", # a classification stated by an official source (e.g. FAA Table 4-16)
)
VERIFICATION_STATUSES = (
    "as_published",              # transcribed / loaded unchanged from the cited source
    "shared_designator_row",     # source row covers several models (e.g. FAA "777-200LRF/LR")
    "source_inconsistent",       # contradicts another value of the same source; not shown as verified
    "unverified_model_value",    # model parameter, not checked against a certified document
)


class AircraftSpecification(Base):
    """One specification value with unit, source, source type, verification status and variant."""

    __tablename__ = "aircraft_specification"
    __table_args__ = (UniqueConstraint("aircraft_type_id", "spec_key", "source_id",
                                       name="uq_aircraft_specification"),)

    specification_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aircraft_type_id: Mapped[int] = mapped_column(ForeignKey("aircraft_type.aircraft_type_id"), nullable=False,
                                                  index=True)
    spec_key: Mapped[str] = mapped_column(String(60), nullable=False)
    section: Mapped[str] = mapped_column(String(30), nullable=False)
    value_decimal: Mapped[Decimal | None] = mapped_column(DecimalText)
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(30))
    original_value: Mapped[str | None] = mapped_column(String(100))
    original_unit: Mapped[str | None] = mapped_column(String(30))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(200))
    condition: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
