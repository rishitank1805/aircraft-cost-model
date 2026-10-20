"""Cost scenario files: schema, units, validation and hashing.

A scenario is a JSON file holding every assumption Part 4 needs. Each value
is an object::

    {"value": "650.00", "unit": "EUR/block_hour", "source_type": "illustrative_assumption",
     "source_reference": null, "notes": "...", "effective_from": "2025-01-01", "effective_to": "2025-12-31",
     "reference_period": null}

- ``value`` is a decimal *string* (parsed as Decimal; JSON floats are rejected).
- ``unit`` is ``<CCY>/<dimension>`` for money (e.g. ``EUR/block_hour``) or a
  plain dimension (``block_hour/year``, ``ratio``, ``years``, ``count``, ...).
- ``source_type``: ``illustrative_assumption``, ``user_assumption``,
  ``public_financial_benchmark`` or ``observed_public_data``.
- ``effective_from``/``effective_to``: the period the scenario author asserts
  the value applies to (defaults to the scenario's period); the pricing date
  must fall inside it. ``reference_period`` documents the period the source
  data describes (e.g. a benchmark's survey year), which may differ.

Nothing is defaulted: a missing value makes the dependent component
``missing_required_input``. Structural problems (wrong unit dimension,
contradictory flags) raise :class:`ScenarioError` or make the component
``failed_validation``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"
OWNERSHIP_MODES = ("owned", "operating_lease", "custom")
FLIGHT_TYPES = ("passenger", "cargo")
VALUE_SOURCE_TYPES = ("illustrative_assumption", "user_assumption", "public_financial_benchmark",
                      "observed_public_data")
DIMENSIONS = {
    # money per activity unit
    "block_hour", "flight_cycle", "engine_flight_hour", "engine_cycle", "year", "month", "flight",
    "duty_day", "night", "revenue_tonne",
}
PLAIN_UNITS = {"block_hour/year", "flight/year", "ratio", "years", "count", "days", "nights", "tonnes",
               "per_year", "payments/year"}
_MONEY_UNIT = re.compile(r"^([A-Z]{3})(?:/([a-z_]+))?$")


class ScenarioError(ValueError):
    """The scenario file is structurally invalid."""


@dataclass(frozen=True)
class ScenarioValue:
    """One typed scenario input."""

    path: str
    value: Decimal
    unit: str
    source_type: str
    source_reference: str | None
    notes: str | None
    effective_from: date | None
    effective_to: date | None
    reference_period: str | None

    @property
    def currency(self) -> str | None:
        match = _MONEY_UNIT.match(self.unit)
        return match.group(1) if match else None

    @property
    def dimension(self) -> str | None:
        match = _MONEY_UNIT.match(self.unit)
        return (match.group(2) or "amount") if match else None

    @property
    def is_money(self) -> bool:
        return self.currency is not None

    def covers(self, day: date) -> bool:
        return (self.effective_from is None or self.effective_from <= day) and \
               (self.effective_to is None or day <= self.effective_to)

    def to_record(self) -> dict[str, Any]:
        return {"parameter": self.path, "value": f"{self.value:f}", "unit": self.unit, "currency": self.currency,
                "source_type": self.source_type, "source_reference": self.source_reference, "notes": self.notes,
                "effective_from": self.effective_from.isoformat() if self.effective_from else None,
                "effective_to": self.effective_to.isoformat() if self.effective_to else None,
                "reference_period": self.reference_period}


def _parse_date(text: Any, where: str) -> date | None:
    if text in (None, ""):
        return None
    try:
        return date.fromisoformat(str(text))
    except ValueError as exc:
        raise ScenarioError(f"{where}: invalid ISO date {text!r}") from exc


@dataclass
class Scenario:
    """A parsed, structurally validated cost scenario."""

    name: str
    description: str
    scenario_version: str
    ownership_mode: str
    flight_type: str
    reporting_currency: str
    pricing_date: date | None
    effective_from: date | None
    effective_to: date | None
    raw: dict[str, Any]
    canonical_json: str
    content_hash: str
    source_path: str | None = None
    values: dict[str, ScenarioValue] = field(default_factory=dict)

    # -- accessors ---------------------------------------------------------------
    def section(self, *keys: str) -> dict[str, Any] | None:
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node if isinstance(node, dict) else None

    def value(self, path: str) -> ScenarioValue | None:
        return self.values.get(path)

    def flag(self, path: str) -> Any:
        node: Any = self.raw
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node


def _is_value_object(node: Any) -> bool:
    return isinstance(node, dict) and "value" in node and "unit" in node


def _parse_value(path: str, node: dict[str, Any], default_from: date | None, default_to: date | None) -> ScenarioValue:
    raw = node["value"]
    if isinstance(raw, float):
        raise ScenarioError(f"{path}: value must be a decimal string, not a JSON float ({raw!r})")
    try:
        number = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ScenarioError(f"{path}: not a decimal number: {raw!r}") from exc
    if not number.is_finite():
        raise ScenarioError(f"{path}: value must be finite")
    unit = str(node["unit"]).strip()
    match = _MONEY_UNIT.match(unit)
    if match:
        if match.group(2) and match.group(2) not in DIMENSIONS:
            raise ScenarioError(f"{path}: unknown money dimension in unit {unit!r}")
    elif unit not in PLAIN_UNITS:
        raise ScenarioError(f"{path}: unknown unit {unit!r}")
    source_type = node.get("source_type")
    if source_type not in VALUE_SOURCE_TYPES:
        raise ScenarioError(f"{path}: source_type must be one of {VALUE_SOURCE_TYPES}, got {source_type!r}")
    if source_type in ("public_financial_benchmark", "observed_public_data") and not node.get("source_reference"):
        raise ScenarioError(f"{path}: {source_type} values need a source_reference")
    return ScenarioValue(
        path, number, unit, source_type, node.get("source_reference"), node.get("notes"),
        _parse_date(node.get("effective_from"), path) or default_from,
        _parse_date(node.get("effective_to"), path) or default_to,
        node.get("reference_period"),
    )


def _walk(node: Any, prefix: str, out: dict[str, ScenarioValue], default_from: date | None,
          default_to: date | None) -> None:
    if _is_value_object(node):
        out[prefix] = _parse_value(prefix, node, default_from, default_to)
        return
    if isinstance(node, dict):
        for key, child in node.items():
            _walk(child, f"{prefix}.{key}" if prefix else key, out, default_from, default_to)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _walk(child, f"{prefix}[{index}]", out, default_from, default_to)


def parse_scenario(data: dict[str, Any], source_path: str | None = None) -> Scenario:
    """Validate the top-level structure and every value object."""
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioError(f"schema_version must be {SCHEMA_VERSION!r}")
    for key in ("name", "ownership_mode", "flight_type", "reporting_currency", "scenario_version"):
        if not data.get(key):
            raise ScenarioError(f"Missing required field {key!r}")
    if data["ownership_mode"] not in OWNERSHIP_MODES:
        raise ScenarioError(f"ownership_mode must be one of {OWNERSHIP_MODES}")
    if data["flight_type"] not in FLIGHT_TYPES:
        raise ScenarioError(f"flight_type must be one of {FLIGHT_TYPES}")
    if not re.fullmatch(r"[A-Z]{3}", str(data["reporting_currency"])):
        raise ScenarioError("reporting_currency must be an ISO 4217 code")
    if data["ownership_mode"] == "custom" and not isinstance(data.get("custom_treatment"), dict):
        raise ScenarioError("ownership_mode 'custom' requires a custom_treatment section")
    eff_from = _parse_date(data.get("effective_from"), "effective_from")
    eff_to = _parse_date(data.get("effective_to"), "effective_to")
    if eff_from and eff_to and eff_to < eff_from:
        raise ScenarioError("effective_to is before effective_from")
    values: dict[str, ScenarioValue] = {}
    _walk({k: v for k, v in data.items() if isinstance(v, (dict, list))}, "", values, eff_from, eff_to)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return Scenario(
        name=data["name"], description=data.get("description", ""), scenario_version=str(data["scenario_version"]),
        ownership_mode=data["ownership_mode"], flight_type=data["flight_type"],
        reporting_currency=data["reporting_currency"], pricing_date=_parse_date(data.get("pricing_date"), "pricing_date"),
        effective_from=eff_from, effective_to=eff_to, raw=data, canonical_json=canonical,
        content_hash=hashlib.sha256(canonical.encode()).hexdigest(), source_path=source_path, values=values,
    )


def load_scenario(path: Path) -> Scenario:
    """Load and validate a scenario JSON file (floats are rejected to keep values exact)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"), parse_float=lambda s: float(s))
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"{path.name}: invalid JSON: {exc}") from exc
    return parse_scenario(data, str(path))
