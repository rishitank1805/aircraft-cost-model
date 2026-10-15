"""Airport download, cleaning and validation tests (offline, fixture based)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest
import requests

from aircraft_cost_model.ingestion.airports import DownloadError, download_airports, latest_snapshot
from aircraft_cost_model.processing.airport_cleaner import (
    REJECTED_REASON_COLUMN,
    clean_airports,
    save_cleaned_airports,
)
from aircraft_cost_model.validation.airport_validator import validate_airports


def _validate(result):
    return validate_airports(
        result, source_name="test", source_url="file://fixture", retrieved_at=None, source_version=None
    )


def _by_ident(df: pd.DataFrame, ident: str) -> pd.Series:
    return df.loc[df["airport_ident"] == ident].iloc[0]


# --- Cleaning -----------------------------------------------------------------


def test_valid_coordinates_are_kept_as_numeric(raw_airports):
    result = clean_airports(raw_airports)
    fra = _by_ident(result.cleaned, "EDDF")
    assert fra["latitude"] == pytest.approx(50.026706)
    assert fra["longitude"] == pytest.approx(8.55835)
    assert pd.api.types.is_float_dtype(result.cleaned["latitude"])
    assert result.cleaned["latitude"].between(-90, 90).all()
    assert result.cleaned["longitude"].between(-180, 180).all()


def test_invalid_coordinates_are_rejected_with_reason(raw_airports):
    result = clean_airports(raw_airports)
    reasons = dict(zip(result.rejected["ident"], result.rejected[REJECTED_REASON_COLUMN]))
    assert reasons["XB04"] == "latitude_out_of_range"
    assert reasons["XB05"] == "non_numeric_coordinates"
    assert "XB04" not in set(result.cleaned["airport_ident"])
    assert "XB05" not in set(result.cleaned["airport_ident"])


def test_empty_identifier_is_rejected(raw_airports):
    result = clean_airports(raw_airports)
    assert "missing_airport_ident" in set(result.rejected[REJECTED_REASON_COLUMN])


def test_missing_iata_code_is_null_not_invented(raw_airports):
    result = clean_airports(raw_airports)
    heliport = _by_ident(result.cleaned, "XH02")
    assert pd.isna(heliport["iata_code"])
    assert pd.isna(heliport["icao_code"])
    assert result.cleaned["iata_code"].notna().sum() == 3  # FRA, JFK, ABC


def test_duplicate_source_ids_keep_first_and_reject_rest(raw_airports):
    result = clean_airports(raw_airports)
    assert result.duplicate_count == 1
    assert not result.cleaned["source_airport_id"].duplicated().any()
    assert _by_ident(result.cleaned, "EDDF")["airport_name"] == "Frankfurt Main Airport"
    dup = result.rejected[result.rejected[REJECTED_REASON_COLUMN] == "duplicate_source_airport_id"]
    assert dup["name"].tolist() == ["Frankfurt Duplicate"]


def test_code_normalization_whitespace_and_uppercase(raw_airports):
    result = clean_airports(raw_airports)
    strip = result.cleaned.loc[result.cleaned["source_airport_id"] == 9001].iloc[0]
    assert strip["airport_ident"] == "XS01"
    assert strip["gps_code"] == "XS01"
    assert strip["country_code"] == "NG"
    assert strip["region_code"] == "NG-LA"
    assert strip["airport_name"] == "Example Strip"
    assert _by_ident(result.cleaned, "XC03")["iata_code"] == "ABC"


def test_north_america_continent_code_is_not_treated_as_missing(raw_airports):
    result = clean_airports(raw_airports)
    assert _by_ident(result.cleaned, "KJFK")["continent"] == "NA"


def test_types_preserved_and_service_mapped(raw_airports):
    result = clean_airports(raw_airports)
    types = set(result.cleaned["airport_type"])
    assert {"heliport", "closed", "small_airport", "seaplane_base"} <= types
    assert bool(_by_ident(result.cleaned, "EDDF")["scheduled_service"]) is True
    assert bool(_by_ident(result.cleaned, "XH02")["scheduled_service"]) is False
    odd = _by_ident(result.cleaned, "XS07")
    assert pd.isna(odd["scheduled_service"])  # 'maybe' -> NULL, not a guess
    assert pd.isna(odd["elevation_ft"])  # 'not-a-number' -> NULL
    assert pd.isna(_by_ident(result.cleaned, "XS01")["elevation_ft"])
    assert any("scheduled_service" in w for w in result.warnings)


def test_cleaning_is_reproducible(raw_airports, tmp_path: Path):
    first = clean_airports(raw_airports.copy())
    second = clean_airports(raw_airports.copy())
    pd.testing.assert_frame_equal(first.cleaned, second.cleaned)
    paths_a = save_cleaned_airports(first, tmp_path / "a")
    paths_b = save_cleaned_airports(second, tmp_path / "b")
    assert paths_a["cleaned"].read_bytes() == paths_b["cleaned"].read_bytes()


def test_missing_required_column_raises(raw_airports):
    with pytest.raises(ValueError, match="latitude_deg"):
        clean_airports(raw_airports.drop(columns=["latitude_deg"]))


# --- Validation ---------------------------------------------------------------


def test_validation_report_counts(raw_airports):
    result = clean_airports(raw_airports)
    report = _validate(result)
    assert report.passed
    assert report.total_source_records == 10
    assert report.cleaned_records == 6
    assert report.rejected_records == 4
    assert report.duplicate_records == 1
    assert report.missing_values_by_field["iata_code"] == 3
    assert report.statistics["airports_by_country"]["US"] == 2
    assert report.statistics["airports_by_type"]["large_airport"] == 2


def test_validator_flags_out_of_range_and_duplicates(raw_airports):
    result = clean_airports(raw_airports)
    result.cleaned.loc[0, "latitude"] = 123.0
    result.cleaned = pd.concat([result.cleaned, result.cleaned.iloc[[1]]], ignore_index=True)
    report = _validate(result)
    assert not report.passed
    assert any("latitude" in e for e in report.errors)
    assert any("duplicate source_airport_id" in e for e in report.errors)


def test_missing_optional_fields_do_not_fail_validation(raw_airports):
    result = clean_airports(raw_airports.drop(columns=["iata_code", "keywords"]))
    report = _validate(result)
    assert report.passed
    assert result.cleaned["iata_code"].isna().all()
    assert any("iata_code" in w for w in report.warnings)


# --- Download -----------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int = 200, chunks: list[bytes] | None = None, fail_after: int | None = None,
                 headers: dict[str, str] | None = None):
        self.status_code = status
        self._chunks = chunks or []
        self._fail_after = fail_after
        self.headers = headers or {}
        self.url = "https://example.test/final/airports.csv"

    def iter_content(self, chunk_size: int):
        for index, chunk in enumerate(self._chunks):
            if self._fail_after is not None and index >= self._fail_after:
                raise requests.ConnectionError("connection reset")
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse | Exception):
        self.response = response
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


CSV_BYTES = b"id,ident\n1,AAAA\n"


def test_download_success_stores_snapshot_and_metadata(tmp_path: Path):
    session = _FakeSession(_FakeResponse(chunks=[CSV_BYTES[:5], CSV_BYTES[5:]],
                                         headers={"Content-Length": str(len(CSV_BYTES))}))
    snapshot = download_airports("https://example.test/airports.csv", tmp_path, timeout=(1, 2), session=session)
    assert snapshot.path.read_bytes() == CSV_BYTES
    assert snapshot.sha256 == hashlib.sha256(CSV_BYTES).hexdigest()
    assert snapshot.size_bytes == len(CSV_BYTES)
    assert snapshot.meta_path.is_file()
    assert snapshot.final_url.endswith("/final/airports.csv")
    assert session.calls[0]["timeout"] == (1, 2)
    assert latest_snapshot(tmp_path).sha256 == snapshot.sha256


def test_identical_redownload_reuses_existing_snapshot(tmp_path: Path):
    first = download_airports("u", tmp_path, session=_FakeSession(_FakeResponse(chunks=[CSV_BYTES])))
    second = download_airports("u", tmp_path, session=_FakeSession(_FakeResponse(chunks=[CSV_BYTES])))
    assert second.reused_existing
    assert second.path == first.path
    assert len(list(tmp_path.glob("airports_*.csv"))) == 1


@pytest.mark.parametrize(
    "response",
    [
        requests.ConnectionError("no network"),
        requests.Timeout("timed out"),
        _FakeResponse(status=503, chunks=[CSV_BYTES]),
        _FakeResponse(chunks=[CSV_BYTES, CSV_BYTES], fail_after=1),
        _FakeResponse(chunks=[CSV_BYTES], headers={"Content-Length": "999"}),
        _FakeResponse(chunks=[]),
    ],
    ids=["connection-error", "timeout", "http-503", "mid-stream-failure", "truncated", "empty"],
)
def test_failed_download_leaves_no_partial_file(tmp_path: Path, response):
    with pytest.raises(DownloadError):
        download_airports("https://example.test/airports.csv", tmp_path, session=_FakeSession(response))
    assert list(tmp_path.iterdir()) == []
