"""ISA standard-atmosphere speed conversions.

Thin wrapper around ``openap.aero`` so the profile generator does not import
OpenAP directly. All functions use SI units (m, m/s) and the ISA atmosphere
with no temperature deviation.
"""

from __future__ import annotations

from openap import aero


def cas_to_tas(cas_ms: float, altitude_m: float) -> float:
    """Calibrated to true airspeed (m/s) at a pressure altitude (m), ISA."""
    return float(aero.cas2tas(cas_ms, altitude_m))


def tas_to_cas(tas_ms: float, altitude_m: float) -> float:
    """True to calibrated airspeed (m/s), ISA."""
    return float(aero.tas2cas(tas_ms, altitude_m))


def mach_to_tas(mach: float, altitude_m: float) -> float:
    """Mach number to true airspeed (m/s), ISA."""
    return float(aero.mach2tas(mach, altitude_m))


def crossover_altitude_m(cas_ms: float, mach: float) -> float:
    """Altitude (m) at which a constant CAS equals a constant Mach number, ISA."""
    return float(aero.crossover_alt(cas_ms, mach))


def schedule_tas(cas_ms: float, mach: float, altitude_m: float) -> float:
    """TAS (m/s) for a CAS/Mach speed schedule: CAS-limited below crossover, Mach-limited above."""
    return min(cas_to_tas(cas_ms, altitude_m), mach_to_tas(mach, altitude_m))
