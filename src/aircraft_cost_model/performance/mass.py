"""Aircraft mass balance and loading-limit checks.

Simplified mass balance (kg):

    ZFW          = OEW + payload
    ramp mass    = ZFW + planned fuel load
    take-off mass = ramp mass - taxi-out fuel
    landing mass = take-off mass - airborne trip fuel

A limit whose value is unknown is reported as ``not_performed``, never as passed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aircraft_cost_model.performance.exceptions import InputValidationError

CHECK_PASSED = "passed"
CHECK_FAILED = "failed"
CHECK_NOT_PERFORMED = "not_performed"

STATUS_CALCULATED = "calculated"
STATUS_LIMITS_UNVERIFIED = "calculated_limits_unverified"
STATUS_INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class AircraftLimits:
    """Weight and fuel limits; ``None`` means the value is not available from a free source."""

    oew_kg: float | None
    mtow_kg: float | None
    mlw_kg: float | None
    mzfw_kg: float | None
    max_payload_kg: float | None
    fuel_capacity_l: float | None
    source: str


@dataclass(frozen=True)
class LimitCheck:
    """Result of one loading check."""

    name: str
    status: str
    value: float | None
    limit: float | None
    unit: str
    note: str = ""
    comparison: str = "<="  # how value relates to limit when the check passes


def require_nonnegative(name: str, value: float) -> float:
    """Return ``value`` if it is a finite number >= 0, else raise :class:`InputValidationError`."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputValidationError(f"{name} must be a finite number, got {value!r}")
    if value < 0:
        raise InputValidationError(f"{name} must not be negative, got {value}")
    return float(value)


def zero_fuel_weight(oew_kg: float | None, payload_kg: float) -> float:
    """ZFW = OEW + payload.

    Raises:
        InputValidationError: Negative payload or unavailable OEW.
    """
    require_nonnegative("payload_kg", payload_kg)
    if oew_kg is None:
        raise InputValidationError("Operating empty weight is unavailable; zero fuel weight cannot be computed")
    return oew_kg + payload_kg


def _upper_limit(name: str, value: float, limit: float | None, unit: str, missing_note: str) -> LimitCheck:
    if limit is None:
        return LimitCheck(name, CHECK_NOT_PERFORMED, value, None, unit, missing_note)
    status = CHECK_PASSED if value <= limit + 1e-6 else CHECK_FAILED
    note = "" if status == CHECK_PASSED else f"exceeds limit by {value - limit:,.0f} {unit}"
    return LimitCheck(name, status, value, limit, unit, note)


def evaluate_limits(
    limits: AircraftLimits,
    *,
    payload_kg: float,
    zero_fuel_weight_kg: float,
    ramp_mass_kg: float,
    takeoff_mass_kg: float,
    landing_mass_kg: float,
    planned_fuel_kg: float,
    fuel_density_kg_per_l: float,
    mass_trace_kg: list[float],
) -> list[LimitCheck]:
    """Evaluate every loading check; unknown limits are reported as ``not_performed``."""
    checks = [
        LimitCheck("payload_nonnegative", CHECK_PASSED if payload_kg >= 0 else CHECK_FAILED, payload_kg, 0.0, "kg",
                   comparison=">="),
        LimitCheck("planned_fuel_nonnegative", CHECK_PASSED if planned_fuel_kg >= 0 else CHECK_FAILED,
                   planned_fuel_kg, 0.0, "kg", comparison=">="),
        _upper_limit("max_payload", payload_kg, limits.max_payload_kg, "kg", "maximum payload not available from free sources"),
        _upper_limit("mzfw", zero_fuel_weight_kg, limits.mzfw_kg, "kg", "MZFW not available from free sources"),
        LimitCheck("max_ramp_weight", CHECK_NOT_PERFORMED, ramp_mass_kg, None, "kg", "maximum ramp weight not in master data"),
        _upper_limit("mtow", takeoff_mass_kg, limits.mtow_kg, "kg", "MTOW unavailable"),
        _upper_limit("mlw", landing_mass_kg, limits.mlw_kg, "kg", "MLW unavailable"),
    ]
    if limits.fuel_capacity_l is None:
        checks.append(LimitCheck("fuel_capacity", CHECK_NOT_PERFORMED, planned_fuel_kg, None, "kg", "fuel capacity unavailable"))
    else:
        capacity_kg = limits.fuel_capacity_l * fuel_density_kg_per_l
        check = _upper_limit("fuel_capacity", planned_fuel_kg, capacity_kg, "kg", "")
        checks.append(
            LimitCheck(check.name, check.status, check.value, check.limit, check.unit,
                       (check.note + "; " if check.note else "")
                       + f"capacity {limits.fuel_capacity_l:,.0f} L x {fuel_density_kg_per_l} kg/L")
        )
    decreasing = all(b <= a + 1e-9 for a, b in zip(mass_trace_kg, mass_trace_kg[1:]))
    checks.append(
        LimitCheck("mass_decreases_with_fuel_burn", CHECK_PASSED if decreasing else CHECK_FAILED, None, None, "kg")
    )
    return checks


def overall_status(checks: list[LimitCheck]) -> str:
    """``infeasible`` if any check failed, ``calculated_limits_unverified`` if any was not performed."""
    if any(c.status == CHECK_FAILED for c in checks):
        return STATUS_INFEASIBLE
    if any(c.status == CHECK_NOT_PERFORMED for c in checks):
        return STATUS_LIMITS_UNVERIFIED
    return STATUS_CALCULATED
