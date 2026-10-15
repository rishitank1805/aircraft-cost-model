"""Custom column types."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class DecimalText(TypeDecorator):
    """Exact decimal stored as its canonical string.

    SQLite has no decimal type: SQLAlchemy ``Numeric`` stores SQLite values as
    binary floating point (REAL), which loses precision. This type writes
    ``str(Decimal)`` and reads it back as :class:`~decimal.Decimal`, so
    monetary values and rates round-trip exactly. Floats are rejected to avoid
    silent binary rounding. Values are compared as text in SQL, so do not rely
    on SQL ``ORDER BY`` / range filters on these columns.
    """

    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("DecimalText does not accept float; pass Decimal or str")
        try:
            number = value if isinstance(value, Decimal) else Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"Not a decimal number: {value!r}") from exc
        if not number.is_finite():
            raise ValueError(f"Non-finite decimal not allowed: {value!r}")
        return str(number)

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        return None if value is None else Decimal(value)
