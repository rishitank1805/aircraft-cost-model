"""Every curated reference CSV parses cleanly: no row has more or fewer fields than its header."""

from __future__ import annotations

import csv

import pytest

from aircraft_cost_model.config import get_settings

REFERENCE_FILES = sorted(get_settings(create_directories=False).reference_dir.glob("*.csv"))


@pytest.mark.parametrize("path", REFERENCE_FILES, ids=lambda p: p.name)
def test_rows_match_header(path):
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        bad = [reader.line_num for row in reader if row and len(row) != len(header)]
    assert not bad, f"{path.name}: rows with a different number of fields than the header at lines {bad}"
