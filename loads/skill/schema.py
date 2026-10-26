"""Column vocabulary and invariants of `eudoxys/loads` data frames.

Everything here is transcribed from the `loads` source in this repository.
Keep it in sync when `loads` changes; `loads/_test/test_skill_loads_api.py`
fails loudly when the class attributes drift.
"""

from __future__ import annotations

# --- units -------------------------------------------------------------------

POWER_SUFFIX = "_MW"
"""Every load/generation column ends in `_MW` (hourly average power, MW)."""

HOURS_PER_SAMPLE = 1.0
"""`loads` frames are hourly, so sum(MW) over rows == energy in MWh."""

# --- weather (from `weather.Weather`) -----------------------------------------

WEATHER_COLUMNS = (
    "temperature_degF",
    "humidity_pc",
    "global_Wpms",
    "direct_Wpms",
    "diffuse_Wpms",
)

# --- sector models (`Residential`, `Commercial`) ------------------------------

END_USE_CATEGORIES = ("baseload", "cooling", "heating")
"""Categories collected from RESstock/COMstock end uses."""

ELEC_ENDUSE_COLUMNS = tuple(f"elec_{c}_MW" for c in END_USE_CATEGORIES)
NONELEC_ENDUSE_COLUMNS = tuple(f"nonelec_{c}_MW" for c in END_USE_CATEGORIES)

# --- total model (`Total`) ----------------------------------------------------

SECTORS = ("residential", "commercial", "industrial", "agricultural", "transportation")

SECTOR_COLUMNS = tuple(f"elec_{s}_MW" for s in SECTORS)

WEATHER_DRIVEN_SECTORS = ("residential", "commercial")
"""Sectors whose shape follows weather. Industrial and agricultural are flat
(constant) load shapes; transportation is always zero."""

PREDICTABLE_TARGETS = {
    # Y column -> default exogenous X columns (`loads.Total.EXOGENOUS_VARIABLES`)
    "elec_residential_MW": ("temperature_degF", "humidity_pc"),
    "elec_commercial_MW": ("temperature_degF", "humidity_pc"),
    "elec_total_MW": ("temperature_degF", "humidity_pc"),
    "elec_dg_MW": ("direct_Wpms", "diffuse_Wpms"),
    "nonelec_residential_MW": ("temperature_degF", "humidity_pc"),
    "nonelec_commercial_MW": ("temperature_degF", "humidity_pc"),
    "nonelec_total_MW": ("temperature_degF", "humidity_pc"),
}
"""Columns `Total` can predict for an arbitrary year without passing `X`."""

TRAINING_YEAR = 2018
"""RESstock/COMstock reference year; `Total` trains on it."""

TSGAM_LAGS = (-3, -2, -1, 0, 1, 2, 3)
"""Exogenous lags of `Total.TSGAM_CONFIG`; `Total` blanks max(-lag) leading
and max(lag) trailing rows of every predicted/sampled series."""

# --- building types -----------------------------------------------------------

RESIDENTIAL_BUILDING_TYPES = {
    "RSD": "single-family detached",
    "RSA": "single-family attached",
    "RSM": "multi-family with 2-4 units",
    "RMM": "multi-family with 5+ units",
    "RMH": "mobile home",
}

COMMERCIAL_BUILDING_TYPES = {
    "CLF": "full-service restaurant",
    "CLH": "hospital",
    "CLL": "large hotel",
    "CLO": "large office",
    "CSH": "outpatient",
    "CMO": "medium office",
    "CSE": "primary school",
    "CSF": "quick-service restaurant",
    "CSR": "retail standalone",
    "CMR": "retail strip mall",
    "CME": "secondary school",
    "CSL": "small hotel",
    "CSO": "small office",
    "CMW": "warehouse",
}


def is_power_column(name: str) -> bool:
    """True for columns measured in MW."""
    return isinstance(name, str) and name.endswith(POWER_SUFFIX)


def power_columns(columns) -> list[str]:
    """The MW columns of a frame, in frame order."""
    return [c for c in columns if is_power_column(c)]
