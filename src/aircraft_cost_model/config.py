"""Central configuration: project paths, public dataset URLs and runtime settings.

All modules obtain paths from :func:`get_settings` so that every script uses the
same locations regardless of operating system or current working directory.
Values can be overridden through environment variables (optionally loaded from a
``.env`` file in the project root).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

OURAIRPORTS_AIRPORTS_URL = "https://ourairports.com/data/airports.csv"
OURAIRPORTS_DATA_PAGE_URL = "https://ourairports.com/data/"
OURAIRPORTS_DATA_DICTIONARY_URL = "https://ourairports.com/help/data-dictionary.html"
OPENAP_REPOSITORY_URL = "https://github.com/TUDelft-CNS-ATM/openap"
OPENAP_DOCUMENTATION_URL = "https://openap.dev/"

EIA_JET_FUEL_SERIES = "EER_EPJK_PF4_RGC_DPG"
EIA_JET_FUEL_XLS_URL = "https://www.eia.gov/dnav/pet/hist_xls/EER_EPJK_PF4_RGC_DPGd.xls"
EIA_JET_FUEL_PAGE_URL = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=EER_EPJK_PF4_RGC_DPG&f=D"
EIA_API_V2_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
ECB_EXR_API_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{currencies}.EUR.SP00.A"

# Jet fuel density used by OpenAP itself (openap/mass.py: ``mfc * 0.8025  # L->kg``).
# Used only to produce explicitly labelled *derived* fuel capacity values in kg.
JET_FUEL_DENSITY_KG_PER_L = 0.8025

_ENV_PREFIX = "ACM_"


def _find_project_root() -> Path:
    """Locate the project root.

    Order of precedence:
    1. ``ACM_PROJECT_ROOT`` environment variable.
    2. The nearest parent of this file containing ``pyproject.toml``
       (works for editable installs and running from a source checkout).
    3. The nearest parent of the current working directory containing ``pyproject.toml``.
    """
    env_root = os.environ.get(f"{_ENV_PREFIX}PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for candidate in (start, *start.parents):
            if (candidate / "pyproject.toml").is_file():
                return candidate

    raise RuntimeError(
        "Could not determine the project root. Run from inside the repository or set "
        f"{_ENV_PREFIX}PROJECT_ROOT."
    )


def _resolve(root: Path, value: str | None, default: Path) -> Path:
    """Resolve an optional path override relative to the project root."""
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


@dataclass(frozen=True)
class Settings:
    """Immutable bundle of paths and settings used across the project."""

    project_root: Path
    raw_airports_dir: Path
    raw_aircraft_dir: Path
    processed_airports_dir: Path
    processed_aircraft_dir: Path
    processed_flights_dir: Path
    raw_fuel_prices_dir: Path
    raw_exchange_rates_dir: Path
    local_tariffs_dir: Path
    local_navigation_dir: Path
    reference_dir: Path
    database_path: Path
    airports_url: str
    http_connect_timeout_s: float
    http_read_timeout_s: float
    log_level: str
    eia_api_key: str | None = None

    @property
    def cargo_targets_path(self) -> Path:
        """Version-controlled freighter target list."""
        return self.reference_dir / "cargo_aircraft_targets.csv"

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL for the SQLite database."""
        return f"sqlite:///{self.database_path.as_posix()}"

    @property
    def http_timeout(self) -> tuple[float, float]:
        """(connect, read) timeout tuple for :mod:`requests`."""
        return (self.http_connect_timeout_s, self.http_read_timeout_s)

    def ensure_directories(self) -> None:
        """Create all data and database directories if they do not exist."""
        for directory in (
            self.raw_airports_dir,
            self.raw_aircraft_dir,
            self.processed_airports_dir,
            self.processed_aircraft_dir,
            self.processed_flights_dir,
            self.raw_fuel_prices_dir,
            self.raw_exchange_rates_dir,
            self.local_tariffs_dir,
            self.local_navigation_dir,
            self.database_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def get_settings(create_directories: bool = True) -> Settings:
    """Build :class:`Settings` from defaults, ``.env`` and environment variables.

    Args:
        create_directories: Create the configured directories if missing.
    """
    root = _find_project_root()
    load_dotenv(root / ".env", override=False)
    env = os.environ.get

    data_dir = root / "data"
    settings = Settings(
        project_root=root,
        raw_airports_dir=data_dir / "raw" / "airports",
        raw_aircraft_dir=data_dir / "raw" / "aircraft",
        processed_airports_dir=data_dir / "processed" / "airports",
        processed_aircraft_dir=data_dir / "processed" / "aircraft",
        processed_flights_dir=data_dir / "processed" / "flights",
        raw_fuel_prices_dir=data_dir / "raw" / "fuel_prices",
        raw_exchange_rates_dir=data_dir / "raw" / "exchange_rates",
        local_tariffs_dir=data_dir / "local" / "airport_tariffs",
        local_navigation_dir=data_dir / "local" / "navigation_rates",
        reference_dir=data_dir / "reference",
        database_path=_resolve(
            root, env(f"{_ENV_PREFIX}DATABASE_PATH"), root / "database" / "aircraft_costs.db"
        ),
        airports_url=env(f"{_ENV_PREFIX}AIRPORTS_URL", OURAIRPORTS_AIRPORTS_URL),
        http_connect_timeout_s=float(env(f"{_ENV_PREFIX}HTTP_CONNECT_TIMEOUT", "10")),
        http_read_timeout_s=float(env(f"{_ENV_PREFIX}HTTP_READ_TIMEOUT", "120")),
        log_level=env(f"{_ENV_PREFIX}LOG_LEVEL", "INFO").upper(),
        eia_api_key=env(f"{_ENV_PREFIX}EIA_API_KEY") or None,
    )
    if create_directories:
        settings.ensure_directories()
    return settings
