"""Validation of Part 3 reference data before it is loaded.

Rows that fail are rejected with a reason (never silently fixed); the
dataset is rejected only for structural problems such as duplicate keys or a
unit change.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass
class RowValidation:
    """Outcome of validating a list of observation rows."""

    valid: list[dict[str, Any]]
    rejected: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def _check_positive_decimal(value: Any) -> str | None:
    if not isinstance(value, Decimal):
        return "value is not a Decimal"
    if not value.is_finite():
        return "value is not finite"
    if value <= 0:
        return "value is not positive"
    return None


def validate_observations(
    rows: list[dict[str, Any]], *, key_fields: tuple[str, ...], value_field: str, unit_field: str | None = None,
    expected_unit: str | None = None,
) -> RowValidation:
    """Generic checks: types, positivity, duplicate keys, single expected unit."""
    result = RowValidation(valid=[])
    for row in rows:
        problem = _check_positive_decimal(row.get(value_field))
        if problem is None and not isinstance(row.get("observation_date"), date):
            problem = "observation_date is not a date"
        if problem is None and unit_field and expected_unit and row.get(unit_field) != expected_unit:
            problem = f"unit {row.get(unit_field)!r} is not {expected_unit!r}"
        if problem:
            result.rejected.append((row, problem))
        else:
            result.valid.append(row)
    counts = Counter(tuple(r[k] for k in key_fields) for r in result.valid)
    duplicates = [k for k, n in counts.items() if n > 1]
    if duplicates:
        result.errors.append(f"{len(duplicates)} duplicate observation keys, e.g. {duplicates[:3]}")
    if result.rejected:
        reasons = Counter(reason for _, reason in result.rejected)
        result.warnings.append(f"Rejected rows by reason: {dict(reasons)}")
    if not result.valid:
        result.errors.append("No valid observations")
    return result


def validate_navigation_rate_rows(rows: list[dict[str, Any]]) -> RowValidation:
    """Unit rates: positive values, EUR for en-route, known formula, ordered validity, no overlaps per zone."""
    result = RowValidation(valid=[])
    for row in rows:
        problem = _check_positive_decimal(row.get("unit_rate"))
        charge_type = row.get("charge_type", "en_route")
        if problem is None and charge_type not in ("en_route", "terminal"):
            problem = f"unknown charge_type {charge_type!r}"
        if problem is None and charge_type == "en_route" and row.get("currency") != "EUR":
            problem = "route unit rates are established in EUR (CoA Art. 7)"
        if problem is None and row.get("service_unit_formula", "sqrt_mtow_over_50") not in (
                "sqrt_mtow_over_50", "mtow_over_50_pow_0_7"):
            problem = f"unknown service_unit_formula {row.get('service_unit_formula')!r}"
        if problem is None and charge_type == "terminal" and row.get("charged_movement") not in ("departure", "arrival"):
            problem = "terminal rates need charged_movement 'departure' or 'arrival'"
        if problem is None and row.get("valid_to") is not None and row["valid_to"] < row["valid_from"]:
            problem = "valid_to before valid_from"
        if problem is None and row.get("verification_status") not in ("verified_against_source", "pending_review"):
            problem = f"unknown verification_status {row.get('verification_status')!r}"
        (result.rejected.append((row, problem)) if problem else result.valid.append(row))
    by_zone: dict[str, list[dict[str, Any]]] = {}
    for row in result.valid:
        by_zone.setdefault(row["charging_zone"], []).append(row)
    for zone, versions in by_zone.items():
        versions.sort(key=lambda r: r["valid_from"])
        for a, b in zip(versions, versions[1:]):
            if a["valid_to"] is None or a["valid_to"] >= b["valid_from"]:
                result.errors.append(f"Overlapping unit-rate versions for {zone}")
    return result
