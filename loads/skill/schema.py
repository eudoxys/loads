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

# --- sector sum (`Total`) -----------------------------------------------------

SECTORS = ("residential", "commercial", "industrial", "agricultural", "transportation")

SECTOR_COLUMNS = tuple(f"elec_{s}_MW" for s in SECTORS)

TOTAL_COLUMNS = SECTOR_COLUMNS + ("elec_total_MW",)
"""Columns of `loads.Total` (in order): the sectors and their sum, nothing else."""

WEATHER_DRIVEN_SECTORS = ("residential", "commercial")
"""Sectors whose shape follows weather. Industrial and agricultural are flat
(constant) load shapes; transportation is always zero."""

TRAINING_YEAR = 2018
"""RESstock/COMstock reference year; `Total` reports it and `Estimator`
trains on it."""

# --- prediction (`Estimator`) ---------------------------------------------------

_ALL = ("residential", "commercial", "industrial", "agricultural")

PREDICTABLE_TARGETS = {
    # column -> (`EstimatorConfig.sectors`, `EstimatorConfig.enduse`)
    "elec_total_MW": (_ALL, "elec_total_MW"),
    "elec_residential_MW": (("residential",), "elec_total_MW"),
    "elec_commercial_MW": (("commercial",), "elec_total_MW"),
    "nonelec_total_MW": (_ALL, "nonelec_total_MW"),
    "nonelec_residential_MW": (("residential",), "nonelec_total_MW"),
    "nonelec_commercial_MW": (("commercial",), "nonelec_total_MW"),
}
"""Columns `loads.skill.series` estimates, and the `Estimator` configuration
that produces each."""

ESTIMATOR_WEATHER = ("temperature_degF", "humidity_pc")
"""Default `EstimatorConfig.weather`."""

ESTIMATOR_LAGS = (-3, -2, -1, 0)
"""Union of the lags of `loads.estimator.WEATHER_CONFIG` for
`ESTIMATOR_WEATHER`; an estimate's first max(-lag) hours are NaN."""

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
