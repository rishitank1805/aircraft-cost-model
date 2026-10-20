"""Part 3: variable operating costs (fuel, navigation, landing, ground handling).

Pure pricing logic lives in ``fuel_cost``, ``navigation_cost``, ``landing_cost``,
``handling_cost``, ``currency``, ``pricing`` and ``coverage``; database access
in ``repository`` and ``persistence``; orchestration in ``calculator``.
Monetary arithmetic uses :class:`decimal.Decimal` throughout.
"""
