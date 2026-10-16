"""Parse, join and derive BTS benchmark observations from P-5.2 and T2 snapshots.

Join: one P-5.2 row (carrier entity x aircraft type x configuration x
quarter) is matched to the T2 row with the same keys and service class ``Z``
("All Service Z (K+V)"); summing T2 service classes would double count,
because K = F+G and V = L+N+P+R are subtotals. The match is checked: T2
airborne hours must agree with P-5.2 airborne hours (Z6500) within
max(10 h, 1 %).

Unit conversions (explicit, exact decimals):

- expenses: thousands of USD x 1000 -> USD
- P-5.2 airborne hours: thousands x 1000 -> hours
- ton-miles (short ton x statute mile) -> tonne-NM: x 0.90718474 t/short ton
  x 1609.344 m / 1852 m
- statute miles -> NM: x 1609.344 / 1852

Excluded: aircraft type ``999`` / configuration ``9`` rows ("expenses not
attributed to specific aircraft types"); they are fleet-level and must not be
divided by an aircraft-type denominator.

Each benchmark category lists the P-5.2 fields it sums. Every field is
required: if one is blank, the amount is unavailable (a blank is never read
as zero).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from aircraft_cost_model.costs.exceptions import SourceSchemaError

SHORT_TON_T = Decimal("0.90718474")
NM_PER_STATUTE_MILE = Decimal("1609.344") / Decimal("1852")
TONNE_NM_PER_TON_MILE = SHORT_TON_T * NM_PER_STATUTE_MILE
THOUSAND = Decimal(1000)
MIN_AIRBORNE_HOURS = Decimal(1000)  # P-5.2 hours are published to 0.01 thousand (+/- 5 h): <= 0.5 % at 1000 h

CATEGORIES: dict[str, tuple[tuple[str, ...], str]] = {
    "fuel": (("FUEL_FLY_OPS",), "51451 Aircraft Fuel"),
    "pilots_and_copilots": (("PILOT_FLY_OPS",), "51230 Pilots and Copilots"),
    "flight_crew_excluding_other_personnel": (
        ("PILOT_FLY_OPS", "TRAIN_FLY_OPS", "PERS_EXP_FLY_OPS", "BENEFITS_FLY_OPS", "PAY_TAX_FLY_OPS"),
        "51230 Pilots and Copilots + 51281 Trainees and Instructors + 51360 Personnel Expenses + 51570 Employee "
        "Benefits and Pensions + 51680 Payroll Taxes (flying operations); excludes 51240 Other Flight Personnel"),
    "maintenance_direct": (("TOT_DIR_MAINT",), "52780 Total Direct Maintenance - Flight Equipment"),
    "maintenance_total": (("TOT_FLT_MAINT_MEMO",), "52990 Total Flight Equipment Maintenance (direct + applied burden)"),
    "insurance": (("INS_FLY_OPS",), "51551 Insurance Purchased - General (flying operations)"),
    "rentals": (("RENTAL_FLY_OPS",), "51470 Rentals (flying operations)"),
    "depreciation_airframe_engine": (("AIRFRAME_DEP", "ENGINE_DEP"), "70751 Airframes + 70752 Aircraft Engines"),
    "flying_operations_total": (("TOT_FLY_OPS",), "51990 Total Flying Operations"),
    "aircraft_operating_total": (("TOT_AIR_OP_EXPENSES",), "70989 Total Aircraft Operating Expense (Direct Operating Expense)"),
}
P52_REQUIRED = ("YEAR", "QUARTER", "UNIQUE_CARRIER", "UNIQUE_CARRIER_NAME", "UNIQUE_CARRIER_ENTITY", "REGION",
                "CARRIER_GROUP_NEW", "AIRCRAFT_TYPE", "AIRCRAFT_CONFIG", "TOTAL_AIR_HOURS") + tuple(
    sorted({f for fields, _ in CATEGORIES.values() for f in fields}))
T2_REQUIRED = ("YEAR", "QUARTER", "UNIQUE_CARRIER", "UNIQUE_CARRIER_ENTITY", "CARRIER_REGION", "AIRCRAFT_TYPE",
               "AIRCRAFT_CONFIG", "SERVICE_CLASS", "REV_TON_MILES_240", "AVL_TON_MILES_280", "REV_ACRFT_MILES_FLOWN_410",
               "REV_ACRFT_DEP_PERF_510", "ACRFT_HRS_RAMPTORAMP_630", "HOURS_AIRBORNE_650", "NUM_MONTHS")
QUARTER_BOUNDS = {1: ((1, 1), (3, 31)), 2: ((4, 1), (6, 30)), 3: ((7, 1), (9, 30)), 4: ((10, 1), (12, 31))}
SEVERITY = ("missing_fields", "negative_amount", "region_mismatch", "hours_mismatch", "no_traffic_match", "low_hours", "partial_quarter",
            "ok")


def read_zip_csv(path: Path, expected_name: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if expected_name not in names:
            raise SourceSchemaError(f"{path.name}: expected {expected_name}, found {names}")
        with archive.open(expected_name) as handle:
            return pd.read_csv(io.TextIOWrapper(handle, encoding="utf-8-sig"), dtype=str, keep_default_na=False)


def read_lookup(path: Path) -> dict[str, str]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(frame.columns[:2]) != ["Code", "Description"]:
        raise SourceSchemaError(f"{path.name}: unexpected lookup columns {list(frame.columns)}")
    return dict(zip(frame["Code"], frame["Description"]))


def _check_columns(frame: pd.DataFrame, required: tuple[str, ...], name: str) -> None:
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise SourceSchemaError(f"{name}: missing columns {missing}")


def _dec(value: str) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise SourceSchemaError(f"not a number: {value!r}") from exc
    return number


@dataclass
class BtsParseResult:
    records: list[dict[str, Any]]
    excluded_unattributed: int
    p52_rows: int
    t2_rows: int
    unmatched_traffic: int
    warnings: list[str] = field(default_factory=list)


def _scope(config: str, carrier_configs: set[str]) -> str:
    if config == "1":
        return "passenger_configuration"
    if config == "2":
        return ("freight_configuration_all_cargo_carrier" if carrier_configs <= {"2"}
                else "freight_configuration_mixed_carrier")
    if config == "3":
        return "combi_configuration"
    return "other_configuration"


def build_records(p52: pd.DataFrame, t2: pd.DataFrame, aircraft_types: dict[str, str]) -> BtsParseResult:
    """Join P-5.2 to T2 (service class Z) and derive one record per cost category."""
    _check_columns(p52, P52_REQUIRED, "P-5.2")
    _check_columns(t2, T2_REQUIRED, "T2")
    key = ["YEAR", "QUARTER", "UNIQUE_CARRIER_ENTITY", "AIRCRAFT_TYPE", "AIRCRAFT_CONFIG"]
    unattributed = p52[(p52["AIRCRAFT_TYPE"] == "999") | (p52["AIRCRAFT_CONFIG"] == "9")]
    p52 = p52.drop(unattributed.index)
    totals = t2[t2["SERVICE_CLASS"] == "Z"]
    duplicated = totals.duplicated(key, keep=False)
    warnings: list[str] = []
    if duplicated.any():
        warnings.append(f"T2: {int(duplicated.sum())} duplicate service-class Z rows dropped (ambiguous)")
        totals = totals[~duplicated]
    traffic = {tuple(r[k] for k in key): r for r in totals.to_dict("records")}
    carrier_configs: dict[str, set[str]] = {}
    for carrier, config in zip(p52["UNIQUE_CARRIER"], p52["AIRCRAFT_CONFIG"]):
        carrier_configs.setdefault(carrier, set()).add(config)
    records: list[dict[str, Any]] = []
    unmatched = 0
    for row in p52.to_dict("records"):
        year, quarter = int(row["YEAR"]), int(row["QUARTER"])
        (m1, d1), (m2, d2) = QUARTER_BOUNDS[quarter]
        t = traffic.get(tuple(row[k] for k in key))
        flags: list[str] = []
        airborne_k = _dec(row["TOTAL_AIR_HOURS"])
        airborne = airborne_k * THOUSAND if airborne_k is not None else None
        block = departures = rtnm = atnm = miles = None
        if t is None:
            unmatched += 1
            flags.append("no_traffic_match")
        else:
            if t["CARRIER_REGION"] != row["REGION"]:
                flags.append("region_mismatch")
            block = _dec(t["ACRFT_HRS_RAMPTORAMP_630"])
            departures = _dec(t["REV_ACRFT_DEP_PERF_510"])
            rtm, atm, statute = (_dec(t["REV_TON_MILES_240"]), _dec(t["AVL_TON_MILES_280"]),
                                 _dec(t["REV_ACRFT_MILES_FLOWN_410"]))
            rtnm = rtm * TONNE_NM_PER_TON_MILE if rtm is not None else None
            atnm = atm * TONNE_NM_PER_TON_MILE if atm is not None else None
            miles = statute * NM_PER_STATUTE_MILE if statute is not None else None
            t2_airborne = _dec(t["HOURS_AIRBORNE_650"])
            if airborne is not None and t2_airborne is not None:
                if abs(t2_airborne - airborne) > max(Decimal(10), airborne * Decimal("0.01")):
                    flags.append("hours_mismatch")
            if (t.get("NUM_MONTHS") or "3") != "3":
                flags.append("partial_quarter")
        if airborne is None or airborne < MIN_AIRBORNE_HOURS:
            flags.append("low_hours")
        for category, (fields, description) in CATEGORIES.items():
            values = [_dec(row[f]) for f in fields]
            cat_flags = list(flags)
            amount = None
            if any(v is None for v in values):
                cat_flags.append("missing_fields")
            else:
                amount = sum(values, Decimal(0)) * THOUSAND
                if any(v < 0 for v in values):
                    cat_flags.append("negative_amount")
            status = next((s for s in SEVERITY if s in cat_flags), "ok")
            records.append({
                "benchmark_source": "bts_form41_p52_t2",
                "source_table": "BTS Form 41 Schedule P-5.2 + T2 (service class Z)",
                "carrier_code": row["UNIQUE_CARRIER"], "carrier_name": row["UNIQUE_CARRIER_NAME"],
                "carrier_group": row["CARRIER_GROUP_NEW"],
                "operation_scope": _scope(row["AIRCRAFT_CONFIG"], carrier_configs[row["UNIQUE_CARRIER"]]),
                "aircraft_type_code": row["AIRCRAFT_TYPE"],
                "aircraft_type_description": aircraft_types.get(row["AIRCRAFT_TYPE"]),
                "aircraft_config": row["AIRCRAFT_CONFIG"], "region": row["REGION"],
                "period_label": f"{year}Q{quarter}", "period_start": date(year, m1, d1), "period_end": date(year, m2, d2),
                "cost_category": category, "amount": amount, "currency": "USD",
                "block_hours": block, "airborne_hours": airborne, "departures": departures,
                "revenue_tonne_nm": rtnm, "available_tonne_nm": atnm, "aircraft_miles_nm": miles,
                "source_fields": " + ".join(fields) + f" [{description}]",
                "methodology": ("P-5.2 expense ($000 x 1000 = USD) for one carrier entity x aircraft type x "
                                "configuration x quarter; denominators from the matching T2 service-class Z row "
                                "(ramp-to-ramp hours, revenue departures, ton-miles converted to tonne-NM); "
                                "P-5.2 airborne hours (Z6500 x 1000)"),
                "quality_status": status,
                "quality_notes": ", ".join(sorted(set(cat_flags))) or None,
            })
    return BtsParseResult(records, len(unattributed), len(p52) + len(unattributed), len(t2), unmatched, warnings)
