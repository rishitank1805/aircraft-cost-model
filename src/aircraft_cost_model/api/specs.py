"""Aircraft specification service: assemble every value with provenance; never fill gaps.

Values come from two places:

- ``aircraft_type`` columns (Part 1, OpenAP model data with ``field_provenance``);
- ``aircraft_specification`` rows (Part 6: FAA ACD, ICAO EEDB via OpenAP, OpenAP
  geometry, FAA classification, curated freighter facts).

All values for a specification are returned side by side with their source.
A *primary* value is chosen only for display ordering: published
specifications first, then documented classifications, engine databank values
and open model data. A ``source_inconsistent`` value is never primary.
Expected specifications without any value are listed as missing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aircraft_cost_model.models import AircraftSpecification, AircraftType, DataSource

SECTIONS = ("overview", "classification", "dimensions", "weights", "engines", "performance", "capacity", "cargo")


@dataclass(frozen=True)
class SpecMeta:
    label: str
    section: str
    glossary: str | None = None
    description: str | None = None


SPEC_META: dict[str, SpecMeta] = {
    # classification / overview
    "body_class": SpecMeta("Body type", "classification", "narrowbody-widebody"),
    "faa_aircraft_category": SpecMeta("FAA aircraft category", "classification"),
    "freighter_type": SpecMeta("Freighter type", "cargo", "passenger-vs-freighter"),
    "conversion_provider": SpecMeta("Conversion provider", "cargo", "p2f-conversion"),
    "base_aircraft": SpecMeta("Converted from", "cargo", "p2f-conversion"),
    "original_manufacturer": SpecMeta("Original manufacturer", "cargo"),
    "adg": SpecMeta("Airplane Design Group (FAA)", "classification"),
    "aac": SpecMeta("Aircraft Approach Category (FAA)", "classification"),
    "icao_wtc": SpecMeta("ICAO wake turbulence category", "classification"),
    # dimensions
    "length_m": SpecMeta("Overall length", "dimensions", None, "Nose to tail"),
    "wingspan_m": SpecMeta("Wingspan", "dimensions", None, "Wing tip to wing tip"),
    "wingspan_with_winglets_m": SpecMeta("Wingspan with winglets/sharklets", "dimensions"),
    "height_m": SpecMeta("Overall height", "dimensions", None, "Ground to top of the tail fin"),
    "wing_area_m2": SpecMeta("Wing area", "dimensions"),
    "wing_sweep_deg": SpecMeta("Wing sweep", "dimensions"),
    "wing_mac_m": SpecMeta("Mean aerodynamic chord", "dimensions"),
    "fuselage_length_m": SpecMeta("Fuselage length", "dimensions"),
    "fuselage_width_m": SpecMeta("Fuselage width", "dimensions"),
    "fuselage_height_m": SpecMeta("Fuselage height (not overall height)", "dimensions"),
    "wheelbase_m": SpecMeta("Wheelbase", "dimensions"),
    "main_gear_width_m": SpecMeta("Main gear width", "dimensions"),
    "main_gear_config": SpecMeta("Main gear configuration (FAA code)", "dimensions"),
    # weights
    "mtow_kg": SpecMeta("Maximum takeoff weight (MTOW)", "weights", "mtow"),
    "mlw_kg": SpecMeta("Maximum landing weight (MLW)", "weights", "mlw"),
    "oew_kg": SpecMeta("Operating empty weight (OEW)", "weights", "oew"),
    "mzfw_kg": SpecMeta("Maximum zero-fuel weight (MZFW)", "weights", "mzfw"),
    "max_ramp_weight_kg": SpecMeta("Maximum ramp weight", "weights", "mtow"),
    "max_structural_payload_kg": SpecMeta("Maximum (structural) payload", "weights", "payload"),
    "fuel_capacity_l": SpecMeta("Fuel capacity (volume)", "weights", "fuel-burn"),
    "fuel_capacity_kg": SpecMeta("Fuel capacity (mass, derived)", "weights", "fuel-burn"),
    # engines
    "engine_manufacturer": SpecMeta("Engine manufacturer", "engines", "thrust"),
    "engine_model": SpecMeta("Engine model (default)", "engines", "thrust"),
    "engine_options": SpecMeta("Engine options by variant", "engines"),
    "engine_count": SpecMeta("Number of engines", "engines"),
    "engine_type": SpecMeta("Engine type", "engines", "thrust"),
    "engine_mount": SpecMeta("Engine mounting", "engines"),
    "rated_thrust_kn": SpecMeta("Rated thrust per engine", "engines", "thrust"),
    "bypass_ratio": SpecMeta("Bypass ratio", "engines", "thrust"),
    "overall_pressure_ratio": SpecMeta("Overall pressure ratio", "engines"),
    # performance
    "cruise_mach": SpecMeta("Cruise Mach number", "performance"),
    "cruise_altitude_m": SpecMeta("Cruise altitude", "performance"),
    "cruise_speed_kt": SpecMeta("Cruise speed (true airspeed)", "performance"),
    "ceiling_m": SpecMeta("Service ceiling (max operating altitude)", "performance"),
    "mmo": SpecMeta("Maximum operating Mach (MMO)", "performance"),
    "vmo_kt": SpecMeta("Maximum operating speed (VMO)", "performance"),
    "approach_speed_kt": SpecMeta("Approach speed", "performance"),
    "nominal_cruise_range_km": SpecMeta("Nominal cruise range (model)", "performance", "range"),
    "published_range_km": SpecMeta("Published range", "performance", "range"),
    "published_range_nm": SpecMeta("Published range", "performance", "payload-range"),
    # capacity
    "max_seats": SpecMeta("Maximum seats", "capacity"),
    "typical_seats_high": SpecMeta("Typical seats (high density)", "capacity"),
    "typical_seats_low": SpecMeta("Typical seats (low density)", "capacity"),
    # cargo
    "main_deck_capacity": SpecMeta("Main-deck positions", "cargo", "uld"),
    "lower_deck_capacity": SpecMeta("Lower-deck positions", "cargo", "uld"),
    "cargo_volume_m3": SpecMeta("Cargo volume", "cargo"),
    "main_deck_cargo_door": SpecMeta("Main-deck cargo door", "cargo", "main-deck-cargo-door"),
    "cargo_loading_system": SpecMeta("Cargo loading system", "cargo", "cargo-loading-system"),
    "cargo_barrier": SpecMeta("Cargo barrier", "cargo", "p2f-conversion"),
    "main_deck_compartment_class": SpecMeta("Main-deck compartment class", "cargo"),
    "cargo_capacity_statement": SpecMeta("Published cargo capacity statement", "cargo", "payload"),
}

EXPECTED: dict[str, tuple[str, ...]] = {
    "dimensions": ("length_m", "wingspan_m", "height_m", "wing_area_m2"),
    "weights": ("mtow_kg", "mlw_kg", "oew_kg", "mzfw_kg", "max_structural_payload_kg", "fuel_capacity_l"),
    "engines": ("engine_manufacturer", "engine_model", "engine_count", "engine_type", "rated_thrust_kn"),
    "performance": ("cruise_mach", "cruise_speed_kt", "ceiling_m"),
    "classification": ("body_class",),
}
EXPECTED_CARGO = ("main_deck_cargo_door", "main_deck_capacity", "lower_deck_capacity", "cargo_volume_m3",
                  "cargo_loading_system", "max_structural_payload_kg")
EXPECTED_RANGE = ("nominal_cruise_range_km", "published_range_km", "published_range_nm")

PRIORITY = {("published_specification", "as_published"): 0, ("documented_classification", "as_published"): 1,
            ("published_specification", "shared_designator_row"): 2, ("engine_databank", "as_published"): 3,
            ("open_model_data", "unverified_model_value"): 4}

AIRCRAFT_TYPE_FIELDS = (
    ("engine_model", None), ("engine_type", None), ("engine_count", "count"), ("mtow_kg", "kg"), ("mlw_kg", "kg"),
    ("oew_kg", "kg"), ("mzfw_kg", "kg"), ("max_payload_kg", "kg"), ("fuel_capacity_l", "L"), ("fuel_capacity_kg", "kg"),
    ("cruise_mach", "Mach"), ("cruise_altitude_m", "m"), ("cruise_speed_kt", "kt"),
)
KEY_ALIASES = {"max_payload_kg": "max_structural_payload_kg"}


@dataclass
class SpecValue:
    key: str
    label: str
    section: str
    value: Decimal | None
    value_text: str | None
    unit: str | None
    source_id: int | None
    source_name: str | None
    source_dataset: str | None
    source_url: str | None
    source_license: str | None
    source_reference: str | None
    source_type: str
    verification_status: str
    variant: str | None = None
    condition: str | None = None
    notes: str | None = None
    original_value: str | None = None
    original_unit: str | None = None
    glossary: str | None = None
    primary: bool = False

    @property
    def rank(self) -> int:
        if self.verification_status == "source_inconsistent":
            return 99
        return PRIORITY.get((self.source_type, self.verification_status), 5)

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.__dict__)
        out["value"] = None if self.value is None else float(self.value)
        out["value_exact"] = None if self.value is None else format(self.value, "f")
        return out


@dataclass
class AircraftSpecs:
    aircraft: AircraftType
    values: list[SpecValue]
    missing: dict[str, list[str]] = field(default_factory=dict)

    def by_key(self) -> dict[str, list[SpecValue]]:
        out: dict[str, list[SpecValue]] = {}
        for v in self.values:
            out.setdefault(v.key, []).append(v)
        return out

    def primary(self, key: str) -> SpecValue | None:
        return next((v for v in self.values if v.key == key and v.primary), None)

    def text(self, key: str) -> str | None:
        v = self.primary(key)
        return v.value_text if v else None


def _sources(session: Session) -> dict[int, DataSource]:
    return {s.source_id: s for s in session.scalars(select(DataSource))}


def latest_source_ids(session: Session) -> set[int]:
    """Only the latest snapshot per dataset is used (older versions stay in the database)."""
    latest: dict[str, int] = {}
    for s in session.scalars(select(DataSource)):
        latest[s.dataset_name] = max(latest.get(s.dataset_name, 0), s.source_id)
    return set(latest.values())


def aircraft_specs(session: Session, aircraft: AircraftType, sources: dict[int, DataSource] | None = None,
                   latest: set[int] | None = None, flight_supported: bool | None = None) -> AircraftSpecs:
    sources = sources or _sources(session)
    latest = latest if latest is not None else latest_source_ids(session)
    values: list[SpecValue] = []
    provenance = json.loads(aircraft.field_provenance or "{}")
    src = sources.get(aircraft.source_id)
    for column, unit in AIRCRAFT_TYPE_FIELDS:
        raw = getattr(aircraft, column)
        if raw is None or raw == "":
            continue
        key = KEY_ALIASES.get(column, column)
        meta = SPEC_META.get(key, SpecMeta(key, "performance"))
        number = Decimal(str(raw)) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
        derived = str(provenance.get(column, "source"))
        values.append(SpecValue(
            key, meta.label, meta.section, number, None if number is not None else str(raw), unit,
            aircraft.source_id, src.source_name if src else None, src.dataset_name if src else None,
            src.source_url if src else None, src.license if src else None,
            f"aircraft_type.{column} ({derived})", "open_model_data", "unverified_model_value",
            variant=aircraft.variant or aircraft.model, notes=derived if derived != "source" else None,
            glossary=meta.glossary))
    rows = session.scalars(select(AircraftSpecification).where(
        AircraftSpecification.aircraft_type_id == aircraft.aircraft_type_id)).all()
    for r in rows:
        if r.source_id not in latest:
            continue
        meta = SPEC_META.get(r.spec_key, SpecMeta(r.spec_key.replace("_", " "), r.section))
        s = sources.get(r.source_id)
        values.append(SpecValue(
            r.spec_key, meta.label, meta.section, r.value_decimal, r.value_text, r.unit, r.source_id,
            s.source_name if s else None, s.dataset_name if s else None, s.source_url if s else None,
            s.license if s else None, r.source_reference, r.source_type, r.verification_status, r.variant,
            r.condition, r.notes, r.original_value, r.original_unit, meta.glossary))
    by_key: dict[str, list[SpecValue]] = {}
    for v in values:
        by_key.setdefault(v.key, []).append(v)
    for group in by_key.values():
        best = min(group, key=lambda v: v.rank)
        if best.rank < 99:
            best.primary = True
    present = set(by_key)
    missing = {section: [k for k in keys if k not in present] for section, keys in EXPECTED.items()}
    if not present & set(EXPECTED_RANGE):
        missing["performance"].append("range")
    is_freighter = "freighter_type" in present
    if is_freighter:
        missing["cargo"] = [k for k in EXPECTED_CARGO if k not in present]
    return AircraftSpecs(aircraft, sorted(values, key=lambda v: (SECTIONS.index(v.section) if v.section in SECTIONS
                                                                 else 99, v.key, v.rank)),
                         {k: v for k, v in missing.items() if v})


def role_of(specs: AircraftSpecs) -> dict[str, Any]:
    """Passenger/cargo role with the evidence used (never guessed)."""
    freighter = specs.text("freighter_type")
    if freighter:
        return {"role": "cargo", "freighter_type": freighter,
                "evidence": "freighter_type from curated manufacturer / conversion-provider source"}
    if specs.primary("max_seats") is not None:
        return {"role": "passenger", "freighter_type": None,
                "evidence": "OpenAP passenger seating data for this type (OpenAP models passenger aircraft)"}
    return {"role": None, "freighter_type": None, "evidence": "role not documented"}
