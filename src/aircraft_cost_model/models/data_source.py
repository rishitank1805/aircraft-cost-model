"""``data_source`` table: provenance of every dataset version loaded."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aircraft_cost_model.models.base import Base


class DataSource(Base):
    """One retrieved version of an external (or curated) dataset.

    A row is identified by ``(dataset_name, checksum)``: re-ingesting identical
    content updates the existing row instead of adding a duplicate, while a new
    upstream version (different checksum) gets its own row.
    """

    __tablename__ = "data_source"
    __table_args__ = (UniqueConstraint("dataset_name", "checksum", name="uq_data_source_dataset_checksum"),)

    source_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    dataset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    license: Mapped[str | None] = mapped_column(Text)
    access_type: Mapped[str | None] = mapped_column(String(100))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_version: Mapped[str | None] = mapped_column(String(200))
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
