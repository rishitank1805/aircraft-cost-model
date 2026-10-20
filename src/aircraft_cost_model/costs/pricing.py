"""Pricing-date observation selection policy.

For a pricing date D and maximum staleness S (days):

1. Only observations dated on or before D are eligible (never future data).
2. The latest eligible observation is selected (no interpolation).
3. If none exists -> unavailable (``no_observation_on_or_before``).
4. If ``D - observation_date > S`` -> unavailable (``stale``); the stale
   candidate is reported but not used.
5. The selected date and the gap in days are always recorded.

The "latest" observation overall is never used for a historical date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Generic, Sequence, TypeVar

T = TypeVar("T")

REASON_NONE_BEFORE = "no_observation_on_or_before"
REASON_STALE = "stale"


@dataclass(frozen=True)
class Selection(Generic[T]):
    """Outcome of selecting an observation for a pricing date."""

    pricing_date: date
    max_staleness_days: int
    observation_date: date | None
    value: T | None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.reason is None

    @property
    def gap_days(self) -> int | None:
        return None if self.observation_date is None else (self.pricing_date - self.observation_date).days


def select_observation(
    observations: Sequence[tuple[date, T]], pricing_date: date, max_staleness_days: int
) -> Selection[T]:
    """Select the latest observation on or before ``pricing_date`` within ``max_staleness_days``."""
    if max_staleness_days < 0:
        raise ValueError("max_staleness_days must be >= 0")
    eligible = [(d, v) for d, v in observations if d <= pricing_date]
    if not eligible:
        return Selection(pricing_date, max_staleness_days, None, None, REASON_NONE_BEFORE)
    obs_date, value = max(eligible, key=lambda item: item[0])
    if (pricing_date - obs_date).days > max_staleness_days:
        return Selection(pricing_date, max_staleness_days, obs_date, None, REASON_STALE)
    return Selection(pricing_date, max_staleness_days, obs_date, value)
