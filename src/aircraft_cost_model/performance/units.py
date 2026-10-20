"""Exact unit conversion constants (SI definitions)."""

from __future__ import annotations

KM_PER_NM = 1.852  # international nautical mile, exact
M_PER_FT = 0.3048  # international foot, exact
MS_PER_KT = 1852.0 / 3600.0  # 1 kt = 1 NM/h, exact
MS_PER_FPM = M_PER_FT / 60.0  # 1 ft/min in m/s, exact
SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0


def km_to_nm(km: float) -> float:
    """Kilometres to nautical miles."""
    return km / KM_PER_NM


def nm_to_km(nm: float) -> float:
    """Nautical miles to kilometres."""
    return nm * KM_PER_NM


def m_to_ft(m: float) -> float:
    """Metres to feet."""
    return m / M_PER_FT


def ft_to_m(ft: float) -> float:
    """Feet to metres."""
    return ft * M_PER_FT


def ms_to_kt(ms: float) -> float:
    """Metres per second to knots."""
    return ms / MS_PER_KT


def kt_to_ms(kt: float) -> float:
    """Knots to metres per second."""
    return kt * MS_PER_KT


def ms_to_fpm(ms: float) -> float:
    """Metres per second to feet per minute."""
    return ms / MS_PER_FPM
