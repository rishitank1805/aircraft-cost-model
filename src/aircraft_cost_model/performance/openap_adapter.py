"""Adapter isolating all OpenAP performance-model calls.

Inspection of OpenAP 2.6.2 (2026-10-15) established:

- ``openap.prop.aircraft(code, use_synonym=False)``: aircraft limits and
  engine options (37 types).
- ``openap.kinematic.WRAP(code, use_synonym=...)``: WRAP kinematic
  parameters (speeds m/s, vertical rates m/s, altitudes/ranges km). **Its
  default is use_synonym=True**, which silently maps e.g. A21N to A320. This
  adapter always passes ``use_synonym=False``.
- ``openap.drag.Drag``: drag polar; 26 types have a polar file.
- ``openap.FuelFlow(code, eng=None, use_synonym=False)``:
  ``enroute(mass[kg], tas[kt], alt[ft], vs[ft/min], acc[m/s2])`` and
  ``takeoff(tas[kt], alt[ft], throttle)`` return fuel flow in **kg/s** for the
  whole aircraft. Thrust is derived from a clean-configuration drag polar.
  Fuel-flow coefficients are type-specific for the 14 types in
  ``data/fuel/fuel_models.csv``; other types use a default curve scaled by
  the engine's ICAO take-off fuel flow.
- ICAO Engine Emissions Databank values in ``data/engine/engines.csv``
  (``ff_idl`` = idle (7 % rated thrust) fuel flow, kg/s per engine).

A type is *supported* only if the aircraft file, WRAP model, drag polar and
default engine record all exist for that exact type code.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import metadata
from pathlib import Path

import pandas as pd

from aircraft_cost_model.performance.exceptions import UnsupportedAircraftError
from aircraft_cost_model.performance.profile import KinematicParameters

MODE_TAKEOFF_ROLL = "takeoff_roll"
MODE_AIRBORNE = "airborne"
MODE_GROUND_IDLE = "ground_idle"


@dataclass(frozen=True)
class FlowState:
    """Operating state for a fuel-flow evaluation."""

    mode: str
    mass_kg: float
    tas_kt: float
    altitude_ft: float
    vertical_speed_fpm: float = 0.0
    acceleration_ms2: float = 0.0


@dataclass(frozen=True)
class AircraftProperties:
    """OpenAP aircraft properties used by the performance engine."""

    aircraft_code: str
    name: str
    mtow_kg: float | None
    mlw_kg: float | None
    oew_kg: float | None
    fuel_capacity_l: float | None
    ceiling_m: float | None
    engine_count: int
    default_engine: str


@dataclass(frozen=True)
class ModelMetadata:
    """Exactly which OpenAP models a calculation uses."""

    aircraft_code: str
    openap_version: str
    supported: bool
    unsupported_reasons: tuple[str, ...] = field(default_factory=tuple)
    aircraft_name: str | None = None
    engine_model: str | None = None
    engine_count: int | None = None
    engine_in_databank: bool = False
    kinematic_model: str | None = None
    drag_polar: str | None = None
    fuel_coefficients: str | None = None
    idle_fuel_flow_kg_s_per_engine: float | None = None

    def describe(self) -> str:
        """One-line description of the model chain."""
        return (
            f"OpenAP {self.openap_version}: aircraft {self.aircraft_code} ({self.aircraft_name}), "
            f"engine {self.engine_model} x{self.engine_count}, kinematics {self.kinematic_model}, "
            f"drag polar {self.drag_polar}, fuel coefficients {self.fuel_coefficients}"
        )


class AircraftPerformanceProvider(abc.ABC):
    """Interface for aircraft performance models."""

    @abc.abstractmethod
    def get_supported_aircraft(self) -> list[str]:
        """Aircraft codes with a complete, direct performance model."""

    @abc.abstractmethod
    def get_model_metadata(self, aircraft_code: str) -> ModelMetadata:
        """Model chain and support status for an aircraft code (never raises for unknown codes)."""

    @abc.abstractmethod
    def get_aircraft_properties(self, aircraft_code: str) -> AircraftProperties:
        """Aircraft properties; raises :class:`UnsupportedAircraftError` if unsupported."""

    @abc.abstractmethod
    def get_kinematic_parameters(self, aircraft_code: str) -> KinematicParameters:
        """Kinematic profile parameters; raises :class:`UnsupportedAircraftError` if unsupported."""

    @abc.abstractmethod
    def get_fuel_flow(self, aircraft_code: str, state: FlowState) -> float:
        """Whole-aircraft fuel flow in kg/s for ``state`` (raw model output, not validated)."""


def _openap_dir() -> Path:
    import openap

    return Path(openap.__file__).resolve().parent


@lru_cache(maxsize=1)
def _engine_table() -> pd.DataFrame:
    return pd.read_csv(_openap_dir() / "data" / "engine" / "engines.csv")


@lru_cache(maxsize=1)
def _fuel_model_table() -> pd.DataFrame:
    return pd.read_csv(_openap_dir() / "data" / "fuel" / "fuel_models.csv")


def _engine_record(name: str) -> dict | None:
    table = _engine_table()
    match = table[table["name"].str.upper() == name.strip().upper()]
    return None if match.empty else match.iloc[0].to_dict()


class OpenAPPerformanceProvider(AircraftPerformanceProvider):
    """:class:`AircraftPerformanceProvider` backed by the installed OpenAP package (no synonyms)."""

    def __init__(self) -> None:
        self.openap_version = metadata.version("openap")
        self._fuel_flow_cache: dict[str, object] = {}
        self._metadata_cache: dict[str, ModelMetadata] = {}

    # -- support -----------------------------------------------------------------

    def _available_files(self, subdir: str, suffix: str) -> set[str]:
        return {p.stem.upper() for p in (_openap_dir() / "data" / subdir).glob(f"*{suffix}") if not p.stem.startswith("_")}

    def get_supported_aircraft(self) -> list[str]:
        return sorted(
            code for code in self._available_files("aircraft", ".yml") if self.get_model_metadata(code).supported
        )

    def get_model_metadata(self, aircraft_code: str) -> ModelMetadata:
        code = aircraft_code.strip().upper()
        if code not in self._metadata_cache:
            self._metadata_cache[code] = self._build_metadata(code)
        return self._metadata_cache[code]

    def _build_metadata(self, code: str) -> ModelMetadata:
        from openap import prop

        reasons: list[str] = []
        if code not in self._available_files("aircraft", ".yml"):
            return ModelMetadata(code, self.openap_version, False, (f"No OpenAP aircraft file for {code}",))

        acdict = prop.aircraft(code, use_synonym=False)
        engine_name = acdict["engine"]["default"]
        engine_count = int(acdict["engine"]["number"])
        engine = _engine_record(engine_name)
        has_wrap = code in self._available_files("wrap", ".txt")
        has_polar = code in self._available_files("dragpolar", ".yml")
        if not has_wrap:
            reasons.append(f"No OpenAP WRAP kinematic model for {code} (synonyms not used)")
        if not has_polar:
            reasons.append(f"No OpenAP drag polar for {code} (synonyms not used)")
        if engine is None:
            reasons.append(f"Default engine {engine_name} not found in OpenAP engine databank")

        fuel_models = _fuel_model_table()
        specific = fuel_models[fuel_models["typecode"].str.upper() == code]
        if not specific.empty:
            ref_engine = specific.iloc[0]["engine_type"]
            fuel_coefficients = f"type-specific ({code}, reference engine {ref_engine})"
            if engine is not None and str(ref_engine).upper() != engine_name.upper():
                fuel_coefficients += f", scaled to {engine_name} by ICAO take-off fuel-flow ratio"
        else:
            fuel_coefficients = f"OpenAP default curve scaled by {engine_name} ICAO take-off fuel flow"

        return ModelMetadata(
            aircraft_code=code,
            openap_version=self.openap_version,
            supported=not reasons,
            unsupported_reasons=tuple(reasons),
            aircraft_name=acdict.get("aircraft"),
            engine_model=engine_name,
            engine_count=engine_count,
            engine_in_databank=engine is not None,
            kinematic_model=f"WRAP {code}" if has_wrap else None,
            drag_polar=code if has_polar else None,
            fuel_coefficients=fuel_coefficients,
            idle_fuel_flow_kg_s_per_engine=float(engine["ff_idl"]) if engine is not None else None,
        )

    def _require_supported(self, aircraft_code: str) -> ModelMetadata:
        meta = self.get_model_metadata(aircraft_code)
        if not meta.supported:
            raise UnsupportedAircraftError(
                f"Aircraft {meta.aircraft_code} has no complete OpenAP performance model: "
                + "; ".join(meta.unsupported_reasons)
            )
        return meta

    # -- data --------------------------------------------------------------------

    def get_aircraft_properties(self, aircraft_code: str) -> AircraftProperties:
        from openap import prop

        meta = self._require_supported(aircraft_code)
        acdict = prop.aircraft(meta.aircraft_code, use_synonym=False)

        def num(value: object) -> float | None:
            return None if value is None else float(value)

        return AircraftProperties(
            aircraft_code=meta.aircraft_code,
            name=acdict.get("aircraft", meta.aircraft_code),
            mtow_kg=num(acdict.get("mtow")),
            mlw_kg=num(acdict.get("mlw")),
            oew_kg=num(acdict.get("oew")),
            fuel_capacity_l=num(acdict.get("mfc")),
            ceiling_m=num(acdict.get("ceiling")),
            engine_count=int(acdict["engine"]["number"]),
            default_engine=acdict["engine"]["default"],
        )

    def get_kinematic_parameters(self, aircraft_code: str) -> KinematicParameters:
        from openap.kinematic import WRAP

        meta = self._require_supported(aircraft_code)
        wrap = WRAP(meta.aircraft_code, use_synonym=False)

        def d(method: str) -> float:
            return float(getattr(wrap, method)()["default"])

        return KinematicParameters(
            source=f"OpenAP {self.openap_version} WRAP {meta.aircraft_code} default values",
            liftoff_speed_ms=d("takeoff_speed"),
            takeoff_acceleration_ms2=d("takeoff_acceleration"),
            initial_climb_vs_ms=d("initclimb_vs"),
            climb_cas_ms=d("climb_const_vcas"),
            climb_cas_start_altitude_m=d("climb_cross_alt_concas") * 1000.0,
            climb_vs_pre_cas_ms=d("climb_vs_pre_concas"),
            climb_vs_cas_ms=d("climb_vs_concas"),
            climb_vs_mach_ms=d("climb_vs_conmach"),
            cruise_mach=d("cruise_mach"),
            cruise_altitude_m=d("cruise_alt") * 1000.0,
            descent_mach=d("descent_const_mach"),
            descent_cas_ms=d("descent_const_vcas"),
            descent_cas_end_altitude_m=d("descent_cross_alt_concas") * 1000.0,
            descent_vs_mach_ms=d("descent_vs_conmach"),
            descent_vs_cas_ms=d("descent_vs_concas"),
            descent_vs_post_cas_ms=d("descent_vs_post_concas"),
            approach_cas_ms=d("finalapp_vcas"),
            approach_vs_ms=d("finalapp_vs"),
            touchdown_speed_ms=d("landing_speed"),
            landing_deceleration_ms2=d("landing_acceleration"),
        )

    def _fuel_flow_model(self, code: str):
        if code not in self._fuel_flow_cache:
            from openap import FuelFlow

            self._fuel_flow_cache[code] = FuelFlow(code, use_synonym=False)
        return self._fuel_flow_cache[code]

    def get_fuel_flow(self, aircraft_code: str, state: FlowState) -> float:
        meta = self._require_supported(aircraft_code)
        if state.mode == MODE_GROUND_IDLE:
            return float(meta.idle_fuel_flow_kg_s_per_engine * meta.engine_count)
        model = self._fuel_flow_model(meta.aircraft_code)
        if state.mode == MODE_TAKEOFF_ROLL:
            return float(model.takeoff(tas=state.tas_kt, alt=state.altitude_ft, throttle=1))
        if state.mode == MODE_AIRBORNE:
            return float(
                model.enroute(
                    mass=state.mass_kg,
                    tas=state.tas_kt,
                    alt=state.altitude_ft,
                    vs=state.vertical_speed_fpm,
                    acc=state.acceleration_ms2,
                )
            )
        raise ValueError(f"Unknown fuel-flow mode {state.mode!r}")

