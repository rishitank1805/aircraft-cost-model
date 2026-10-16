"""BTS TranStats downloads: Form 41 Schedule P-5.2 and Air Carrier Summary T2, plus lookup tables.

Verified 2026-10-15 on https://www.transtats.bts.gov/:

- **Schedule P-5.2** (database "Air Carrier Financial Reports (Form 41
  Financial Data)", table id ``FMK``): quarterly aircraft operating expenses by
  carrier, aircraft type, aircraft configuration and reporting region for
  large certificated U.S. carriers (annual operating revenue >= $20 million).
  Expenses in thousands of USD; ``TOTAL_AIR_HOURS`` (Z6500) in thousands of
  airborne hours. Data 1990 to June 2026 at verification.
- **T2** ("U.S. Air Carrier Traffic and Capacity Statistics by Aircraft
  Type", table id ``FIH``): quarterly ramp-to-ramp hours, airborne hours,
  revenue departures, revenue ton-miles and available ton-miles by carrier,
  aircraft type, configuration, region and service class. A ton-mile is one
  short ton (2,000 lb) carried one statute mile (BTS glossary).

Access: the TranStats "Download" page is an ASP.NET form without a bot
challenge. This module performs the same request a browser does (GET the
form, POST the selected year and fields) and stores the returned ZIP byte for
byte. No access control is bypassed. Lookup tables come from TranStats'
``Download_Lookup.asp`` links (exact identifiers in ``LOOKUP_KEYS``).

Licence: BTS states that its published material is in the public domain and
may be reused without special permission; citation is required.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from aircraft_cost_model.ingestion.snapshots import (
    DownloadError,
    RawSnapshot,
    download_snapshot,
    latest_snapshot,
    store_snapshot_bytes,
)

logger = logging.getLogger(__name__)

TRANSTATS = "https://www.transtats.bts.gov/"
LICENSE = ("U.S. Bureau of Transportation Statistics (TranStats): public domain U.S. Government data; citation of "
           "BTS as the source is required. https://www.transtats.bts.gov/")
USER_AGENT = "open-aircraft-cost-model (BTS Form 41 benchmark ingestion; python-requests)"


@dataclass(frozen=True)
class BtsTable:
    key: str
    table_id: str
    csv_name: str
    dataset_name: str
    description: str


TABLES = {
    "P52": BtsTable("P52", "FMK", "T_F41SCHEDULE_P52.csv", "bts_form41_schedule_p52",
                    "Form 41 Schedule P-5.2: aircraft operating expenses by carrier, aircraft type, configuration, "
                    "region and quarter (USD thousands; airborne hours in thousands)"),
    "T2": BtsTable("T2", "FIH", "T_SCHEDULE_T2.csv", "bts_air_carrier_summary_t2",
                   "Air Carrier Summary T2: traffic and capacity by carrier, aircraft type, configuration, region, "
                   "service class and quarter (hours, departures, ton-miles)"),
}
# Exact identifiers used by TranStats' Download_Lookup.asp links on the P-5.2/T2 download pages (verified
# 2026-10-15). They are ROT13 of mixed-case table names (e.g. "Y_NVePeNSg_glcR" -> "L_AIrCrAFt_typE"); the
# server is case-sensitive, so they cannot be derived from upper-case names.
LOOKUP_KEYS = {
    "L_AIRCRAFT_TYPE": "Y_NVePeNSg_glcR",
    "L_AIRCRAFT_CONFIG": "Y_NVePeNSg_PbaSVT",
    "L_REGION": "Y_eRTVba",
    "L_SERVICE_CLASS": "Y_fReiVPR_PYNff",
    "L_CARRIER_GROUP_NEW": "Y_PNeeVRe_Tebhc_aRj",
}
LOOKUPS = tuple(LOOKUP_KEYS)


def lookup_url(name: str) -> str:
    """URL of a TranStats lookup table (see ``LOOKUP_KEYS``)."""
    return f"{TRANSTATS}Download_Lookup.asp?Y11x72={LOOKUP_KEYS[name]}"


def form_url(table: BtsTable) -> str:
    return f"{TRANSTATS}DL_SelectFields.aspx?gnoyr_VQ={table.table_id}&QO_fu146_anzr="


_HIDDEN = re.compile(r'<input type="hidden" name="([^"]+)" id="[^"]+" value="([^"]*)"')
_FIELD = re.compile(r'<input id="([A-Z0-9_]+)" type="checkbox" name="\1"')


def download_table(table_key: str, year: int, raw_dir: Path, timeout: tuple[float, float] = (15.0, 300.0),
                   session: requests.Session | None = None) -> RawSnapshot:
    """Download one calendar year (all quarters, all fields) of a TranStats table as an immutable ZIP snapshot."""
    table = TABLES[table_key]
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", USER_AGENT)
    url = form_url(table)
    try:
        page = http.get(url, timeout=timeout)
        if page.status_code != 200:
            raise DownloadError(f"HTTP {page.status_code} for {url}")
        hidden = dict(_HIDDEN.findall(page.text))
        fields = _FIELD.findall(page.text)
        if not fields or "__VIEWSTATE" not in hidden:
            raise DownloadError(f"TranStats form for {table.table_id} has an unexpected structure")
        years = re.findall(r'<option[^>]*value="(\d{4})"', page.text)
        if str(year) not in years:
            raise DownloadError(f"{table.key}: year {year} not offered by TranStats (available {years[:1]}..{years[-1:]})")
        data = {k: hidden[k] for k in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION") if k in hidden}
        data.update({"cboGeography": "All", "cboYear": str(year), "cboPeriod": "All", "btnDownload": "Download"})
        data.update({f: "on" for f in fields})
        response = http.post(url, data=data, timeout=timeout)
    except requests.RequestException as exc:
        raise DownloadError(f"Network error for {url}: {exc}") from exc
    if response.status_code != 200 or "zip" not in (response.headers.get("Content-Type") or ""):
        raise DownloadError(f"{table.key} {year}: expected a ZIP, got HTTP {response.status_code} "
                            f"{response.headers.get('Content-Type')}")
    logger.info("bts_download_complete", extra={"table": table.key, "year": year, "bytes": len(response.content)})
    return store_snapshot_bytes(response.content, raw_dir, f"bts_{table.key.lower()}_{year}", ".zip",
                                source_url=f"{url} (POST cboYear={year}, cboPeriod=All, all fields)",
                                final_url=response.url, http_status=response.status_code,
                                last_modified=response.headers.get("Content-Disposition"))


def download_lookup(name: str, raw_dir: Path, timeout: tuple[float, float] = (15.0, 120.0),
                    session: requests.Session | None = None) -> RawSnapshot:
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", USER_AGENT)
    return download_snapshot(lookup_url(name), raw_dir, f"bts_lookup_{name.lower()}", ".csv", timeout=timeout,
                             session=http)


def latest_table_snapshot(raw_dir: Path, table_key: str, year: int) -> RawSnapshot | None:
    return latest_snapshot(raw_dir, f"bts_{table_key.lower()}_{year}", ".zip")


def latest_lookup_snapshot(raw_dir: Path, name: str) -> RawSnapshot | None:
    return latest_snapshot(raw_dir, f"bts_lookup_{name.lower()}", ".csv")


def register_snapshot_source(session, snapshot: RawSnapshot, table_key: str, year: int) -> int:
    from aircraft_cost_model.database import SourceMetadata, register_data_source

    table = TABLES[table_key]
    return register_data_source(session, SourceMetadata(
        source_name="U.S. Bureau of Transportation Statistics (BTS), TranStats",
        source_url=form_url(table), dataset_name=table.dataset_name, license=LICENSE,
        access_type="TranStats download form (ZIP of CSV), all fields, all quarters of one year",
        retrieved_at=snapshot.retrieved_at, source_version=f"{year} sha256:{snapshot.sha256[:12]}",
        checksum=snapshot.sha256, notes=f"{table.description}; raw file {snapshot.path.name}",
    ))


def load_bts_benchmarks(engine, p52_snapshot: RawSnapshot, t2_snapshot: RawSnapshot, year: int,
                        records: list[dict]) -> tuple[int, int]:
    """Insert derived observations for one year; rows already stored for these snapshots are left untouched.

    Returns ``(inserted, already_present)``.
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.orm import Session

    from aircraft_cost_model.models import BenchmarkObservation
    from aircraft_cost_model.models.base import utc_now

    with Session(engine) as session, session.begin():
        p52_id = register_snapshot_source(session, p52_snapshot, "P52", year)
        t2_id = register_snapshot_source(session, t2_snapshot, "T2", year)
        table = BenchmarkObservation.__table__
        before = session.query(BenchmarkObservation).filter_by(source_id=p52_id).count()
        now = utc_now()
        rows = [{**r, "source_id": p52_id, "traffic_source_id": t2_id, "created_at": now} for r in records]
        for start in range(0, len(rows), 1000):
            session.execute(sqlite_insert(table).on_conflict_do_nothing(), rows[start:start + 1000])
        after = session.query(BenchmarkObservation).filter_by(source_id=p52_id).count()
    logger.info("bts_benchmarks_loaded", extra={"year": year, "inserted": after - before})
    return after - before, len(rows) - (after - before)
