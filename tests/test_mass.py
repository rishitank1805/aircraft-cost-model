"""Aircraft mass balance and loading-limit tests."""

from __future__ import annotations

import pytest

from aircraft_cost_model.performance.exceptions import InputValidationError
from aircraft_cost_model.performance.mass import (
    CHECK_FAILED,
    CHECK_NOT_PERFORMED,
    CHECK_PASSED,
    STATUS_CALCULATED,
    STATUS_INFEASIBLE,
    STATUS_LIMITS_UNVERIFIED,
    AircraftLimits,
    evaluate_limits,
    overall_status,
    zero_fuel_weight,
)

FULL = AircraftLimits(oew_kg=42600, mtow_kg=78000, mlw_kg=66000, mzfw_kg=62500, max_payload_kg=19900,
                      fuel_capacity_l=24210, source="test")


def _checks(limits=FULL, payload=10000.0, tow=60000.0, lw=58000.0, fuel=8000.0, trace=None):
    zfw = zero_fuel_weight(limits.oew_kg, payload)
    return {c.name: c for c in evaluate_limits(
        limits, payload_kg=payload, zero_fuel_weight_kg=zfw, ramp_mass_kg=tow + 200, takeoff_mass_kg=tow,
        landing_mass_kg=lw, planned_fuel_kg=fuel, fuel_density_kg_per_l=0.8, mass_trace_kg=trace or [tow, lw],
    )}


def test_zero_fuel_weight():
    assert zero_fuel_weight(42600.0, 10000.0) == 52600.0
    assert zero_fuel_weight(42600.0, 0.0) == 42600.0


@pytest.mark.parametrize("payload", [-1.0, float("nan"), float("inf"), None])
def test_negative_or_invalid_payload_rejected(payload):
    with pytest.raises(InputValidationError):
        zero_fuel_weight(42600.0, payload)


def test_missing_oew_rejected():
    with pytest.raises(InputValidationError, match="Operating empty weight"):
        zero_fuel_weight(None, 1000.0)


def test_valid_payload_passes_all_known_limits():
    checks = _checks()
    assert all(c.status == CHECK_PASSED for name, c in checks.items() if name != "max_ramp_weight")
    assert checks["max_ramp_weight"].status == CHECK_NOT_PERFORMED  # no MRW in master data


def test_payload_above_maximum():
    assert _checks(payload=25000.0)["max_payload"].status == CHECK_FAILED


def test_mzfw_violation():
    assert _checks(payload=19900.0 + 1)["mzfw"].status == CHECK_FAILED  # 42,600 + 19,901 > 62,500


def test_mtow_violation():
    check = _checks(tow=78001.0)["mtow"]
    assert check.status == CHECK_FAILED and "exceeds" in check.note


def test_mlw_violation():
    assert _checks(lw=66001.0)["mlw"].status == CHECK_FAILED


def test_fuel_capacity_violation_uses_density():
    assert _checks(fuel=24210 * 0.8 + 1)["fuel_capacity"].status == CHECK_FAILED
    assert _checks(fuel=24210 * 0.8 - 1)["fuel_capacity"].status == CHECK_PASSED


def test_missing_limits_are_not_performed_and_status_unverified():
    sparse = AircraftLimits(oew_kg=42600, mtow_kg=78000, mlw_kg=None, mzfw_kg=None, max_payload_kg=None,
                            fuel_capacity_l=None, source="test")
    checks = _checks(limits=sparse)
    for name in ("mlw", "mzfw", "max_payload", "fuel_capacity"):
        assert checks[name].status == CHECK_NOT_PERFORMED
    assert overall_status(list(checks.values())) == STATUS_LIMITS_UNVERIFIED


def test_status_precedence():
    checks = list(_checks().values())
    assert overall_status([c for c in checks if c.status == CHECK_PASSED]) == STATUS_CALCULATED
    assert overall_status(list(_checks(tow=90000.0).values())) == STATUS_INFEASIBLE


def test_mass_must_decrease():
    assert _checks(trace=[60000.0, 59000.0, 59500.0])["mass_decreases_with_fuel_burn"].status == CHECK_FAILED
    assert _checks(trace=[60000.0, 59000.0, 58000.0])["mass_decreases_with_fuel_burn"].status == CHECK_PASSED
