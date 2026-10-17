"""Part 6: read-only FastAPI layer for the Aircraft Explorer & Learning Dashboard.

The API reuses the existing models and engines (Part 2 flight performance,
Parts 3-5 cost and analytics). It opens SQLite in read-only mode, so it
cannot modify historical records; flight calculations are returned, not saved.
"""
