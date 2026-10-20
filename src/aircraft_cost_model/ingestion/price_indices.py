"""BLS price-index observations from the official BLS Public Data API (v2).

Verified 2026-10-15: ``POST https://api.bls.gov/publicAPI/v2/timeseries/data/``
with ``{"seriesid": [...], "startyear": "YYYY", "endyear": "YYYY"}`` returns
JSON without a registration key (unregistered limits: few queries per day,
10 years per query). Monthly periods are ``M01``-``M12`` (``M13`` = annual
average, skipped); quarterly periods are ``Q01``-``Q04``. A footnote code
``P`` marks preliminary values (PPI values are revised for four months).

The bulk files on download.bls.gov returned HTTP 403 (access denied) to
scripted access and are not used; no access control is bypassed.

Licence: BLS data are U.S. Government works in the public domain; citation
of BLS as the source is requested.
"""

from __future__ import annotations

import calendar
import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests

from aircraft_cost_model.costs.exceptions import SourceSchemaError
from aircraft_cost_model.ingestion.snapshots import DownloadError, RawSnapshot, store_snapshot_bytes

logger = logging.getLogger(__name__)

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
LICENSE = "U.S. Bureau of Labor Statistics: public domain U.S. Government data; cite BLS as the source."
QUARTER_END = {1: 3, 2: 6, 3: 9, 4: 12}


def download_series(series_ids: list[str], start_year: int, end_year: int, raw_dir: Path,
                    timeout: tuple[float, float] = (15.0, 120.0), session: requests.Session | None = None) -> RawSnapshot:
    if end_year - start_year > 9:
        raise ValueError("the unregistered BLS API serves at most 10 years per request")
    http = session or requests.Session()
    body = {"seriesid": sorted(series_ids), "startyear": str(start_year), "endyear": str(end_year)}
    try:
        response = http.post(BLS_API_URL, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise DownloadError(f"Network error for {BLS_API_URL}: {exc}") from exc
    if response.status_code != 200:
        raise DownloadError(f"HTTP {response.status_code} from {BLS_API_URL}")
    payload = response.json()
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise DownloadError(f"BLS API: {payload.get('status')} {payload.get('message')}")
    name = "_".join(sorted(series_ids))[:80]
    return store_snapshot_bytes(response.content, raw_dir, f"bls_{name}_{start_year}_{end_year}", ".json",
                                source_url=f"{BLS_API_URL} POST {json.dumps(body)}", final_url=response.url,
                                http_status=response.status_code)


def _period_bounds(year: int, period: str) -> tuple[date, date] | None:
    if period.startswith("M") and period != "M13":
        month = int(period[1:])
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    if period.startswith("Q") and period[1:].isdigit() and 1 <= int(period[1:]) <= 4:
        end_month = QUARTER_END[int(period[1:])]
        return date(year, end_month - 2, 1), date(year, end_month, calendar.monthrange(year, end_month)[1])
    return None


def parse_series_json(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return observation records and messages (e.g. 'Series does not exist')."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "Results" not in payload or "series" not in payload["Results"]:
        raise SourceSchemaError(f"{path.name}: not a BLS API v2 response")
    records: list[dict[str, Any]] = []
    for series in payload["Results"]["series"]:
        for item in series.get("data", []):
            bounds = _period_bounds(int(item["year"]), item["period"])
            if bounds is None:
                continue
            try:
                value = Decimal(item["value"])
            except InvalidOperation:
                continue  # BLS uses '-' for unavailable values; never read as zero
            codes = [f.get("code") for f in item.get("footnotes", []) if f]
            records.append({
                "series_id": series["seriesID"], "period": f"{item['year']}-{item['period']}",
                "period_start": bounds[0], "period_end": bounds[1], "value": value,
                "preliminary": "P" in codes,
                "footnotes": "; ".join(f"{f.get('code')}: {f.get('text')}" for f in item.get("footnotes", []) if f) or None,
            })
    return records, list(payload.get("message") or [])


def load_index_observations(engine, snapshot: RawSnapshot, records: list[dict[str, Any]],
                            titles: dict[str, str] | None = None) -> tuple[int, int]:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.orm import Session

    from aircraft_cost_model.database import SourceMetadata, register_data_source
    from aircraft_cost_model.models import PriceIndexObservation

    titles = titles or {}
    with Session(engine) as session, session.begin():
        source_id = register_data_source(session, SourceMetadata(
            source_name="U.S. Bureau of Labor Statistics (BLS)", source_url=BLS_API_URL,
            dataset_name="bls_api_price_indices", license=LICENSE, access_type="BLS Public Data API v2 (JSON)",
            retrieved_at=snapshot.retrieved_at, source_version=f"sha256:{snapshot.sha256[:12]}",
            checksum=snapshot.sha256,
            notes=f"series {sorted({r['series_id'] for r in records})}; raw file {snapshot.path.name}"))
        before = session.query(PriceIndexObservation).filter_by(source_id=source_id).count()
        rows = [{**r, "source_id": source_id, "series_title": titles.get(r["series_id"])} for r in records]
        if rows:
            session.execute(sqlite_insert(PriceIndexObservation.__table__).on_conflict_do_nothing(), rows)
        after = session.query(PriceIndexObservation).filter_by(source_id=source_id).count()
    return after - before, len(rows) - (after - before)
