"""Read the precomputed WECC estimates shipped in `loads/wecc/`.

For WECC counties in 2018-2022 the repository already holds hourly results
that took hours to build, so most WECC questions can be answered by reading
a file instead of fitting a model per county:

| file | contents | built by |
|---|---|---|
| `wecc_estimate.csv.gz` | gross load (MW) of 407 WECC counties, `"County ST"` columns, monthly energy calibrated to EIA-861M retail sales allocated to the county plus its rooftop PV | `loads/wecc/wecc_estimate.py` (`Estimator`) |
| `node_estimate.csv.gz` | uncalibrated gross load (MW) of the WECC240 load nodes (geohash columns), incl. Canadian and Mexican nodes | `loads/wecc/node_estimate.py` |
| `county_dg.csv.gz` | rooftop PV output (MW, **positive**) from NLR dGen, 369 counties, no year-to-year growth | `loads.dgen.compile` |
| `county_dg_scaled.csv.gz` | the same, filled for all 407 counties and scaled per state and year to EIA small-scale solar | `loads/wecc/county_dg_scale.py` |

All are hourly UTC (hour beginning). The DG files start at
2018-01-01 07:00 UTC; the missing night hours read as 0.

`county_dg.csv.gz` is installed with the package, so `wecc_dg()` works from
any install. The other files are in the git repository but are not
installed by a non-editable `pip install`; their readers raise
`FileNotFoundError` with that hint. Use a clone with `pip install -e .`.
"""

from __future__ import annotations

import os

import pandas as pd

from .locations import County, resolve
from .timeaxis import hourly_range

FILES = {
    "estimate": "wecc_estimate.csv.gz",
    "nodes": "node_estimate.csv.gz",
    "dg": "county_dg.csv.gz",
    "dg_scaled": "county_dg_scaled.csv.gz",
}


def path(name: str) -> str:
    """Absolute path of a bundled `loads/wecc` file (a key of `FILES` or a
    file name). Raises `FileNotFoundError` when it is not installed."""
    import loads

    filename = FILES.get(name, name)
    full = os.path.join(os.path.dirname(os.path.abspath(loads.__file__)), "wecc", filename)
    if not os.path.exists(full):
        raise FileNotFoundError(
            f"{full} not found. This loads/wecc data file is not installed by a "
            "non-editable pip install; clone https://github.com/eudoxys/loads and "
            "`pip install -e .`, or pass the file path yourself."
        )
    return full


def _columns(places, available: list[str], what: str) -> list[str] | None:
    if places is None:
        return None
    names = []
    for p in ([places] if isinstance(places, (str, County, tuple)) else places):
        name = p if isinstance(p, str) and p in available else (
            p.county_st if isinstance(p, County) else resolve(p).county_st)
        if name not in available:
            raise KeyError(f"{name!r} is not in the {what} file")
        names.append(name)
    return names


def _wecc_counties(places) -> list[str]:
    """`"County ST"` names of WECC counties, checked with the bundled `fips`
    data (not a data file, so this works from a non-editable install)."""
    names = []
    for p in ([places] if isinstance(places, (str, County, tuple)) else places):
        c = p if isinstance(p, County) else resolve(p)
        if c.system != "WECC":
            raise KeyError(f"{c.county_st!r} is not a WECC county")
        names.append(c.county_st)
    return names


def _read(name: str, columns: list[str] | None, when) -> pd.DataFrame:
    file = path(name)
    usecols = None if columns is None else ["timestamp"] + columns
    data = pd.read_csv(file, index_col=0, usecols=usecols)
    data.index = pd.DatetimeIndex(pd.to_datetime(data.index, utc=True), name="timestamp")
    if when is not None:
        index = when if isinstance(when, pd.DatetimeIndex) else hourly_range(when)
        data = data.reindex(index.tz_convert("UTC"))
    return data


def _header(name: str) -> list[str]:
    return list(pd.read_csv(path(name), nrows=0).columns[1:])


def _stamp(data: pd.DataFrame, mode: str, notes: list[str]) -> pd.DataFrame:
    data.attrs["loadskill"] = {
        "county": None,
        "mode": mode,
        "columns": [str(c) for c in data.columns],
        "start": str(data.index[0]) if len(data) else None,
        "end": str(data.index[-1]) if len(data) else None,
        "notes": notes,
    }
    return data


def wecc_estimate(places=None, when=None) -> pd.DataFrame:
    """Hourly gross load (MW) of WECC counties, 2018-2022, from
    `wecc_estimate.csv.gz`.

    `places` is one county or a list (anything `resolve` accepts, or
    `"County ST"` names); `None` reads all 407 (about 65 MB compressed,
    takes a while). `when` is a year, list of years or `DatetimeIndex`;
    hours outside 2018-2022 come back NaN.

    Columns are `"County ST"`. Values are gross load (the analogue of
    `elec_total_MW`, before subtracting rooftop PV), with each UTC month's
    energy equal to the county's EIA-861M retail sales allocation plus
    `county_dg.csv.gz`. Hourly shapes come from `loads.estimator.Estimator`
    (not `Total`), and 2018 shapes are the 2018 sector sums.
    """
    columns = _columns(places, _header("estimate"), "WECC estimate")
    data = _read("estimate", columns, when)
    return _stamp(data, "wecc_estimate", [
        "precomputed loads/wecc/wecc_estimate.csv.gz (Estimator shapes, monthly energy "
        "= EIA-861M retail allocation + county_dg.csv.gz)",
        "gross load: subtract wecc_dg(scaled=False) to recover retail-sales energy",
    ])


def node_estimate(nodes=None, when=None) -> pd.DataFrame:
    """Hourly gross load (MW) of WECC240 load nodes (geohash columns),
    2018-2022, from `node_estimate.csv.gz`. Not calibrated to EIA, node or
    balancing-authority data; counties are split among nodes by constant
    factors (`loads/wecc/node_estimate_cf.csv`)."""
    available = _header("nodes")
    if nodes is not None:
        nodes = [nodes] if isinstance(nodes, str) else list(nodes)
        missing = [n for n in nodes if n not in available]
        if missing:
            raise KeyError(f"nodes {missing[:5]} are not in the node estimate file")
    data = _read("nodes", nodes, when)
    return _stamp(data, "node_estimate", [
        "precomputed loads/wecc/node_estimate.csv.gz (uncalibrated Estimator county loads "
        "allocated to WECC240 nodes)",
    ])


def wecc_dg(places=None, when=None, *, scaled: bool = False, convention: str = "load") -> pd.DataFrame:
    """Hourly county rooftop PV (MW) from the bundled WECC DG files.

    `scaled=False` reads `county_dg.csv.gz` (dGen, the DG used to build
    `wecc_estimate.csv.gz`; counties absent from it come back 0 with a
    note); `scaled=True` reads `county_dg_scaled.csv.gz` (all
    counties, scaled per state and year to EIA small-scale solar; what
    `loads.calibrate` validation uses).

    The files store positive generation. `convention="load"` (default)
    returns the `loads` convention, `elec_dg_MW <= 0`; `"output"` returns
    the stored positive values.
    """
    if convention not in ("load", "output"):
        raise ValueError(f"convention must be 'load' or 'output', not {convention!r}")
    name = "dg_scaled" if scaled else "dg"
    available = _header(name)
    notes = [f"precomputed loads/wecc/{FILES[name]}", f"{convention} sign convention",
             "hours before 2018-01-01 07:00 UTC are not in the file and read as 0"]
    absent: list[str] = []
    if places is None:
        columns = None
    else:
        wanted = _wecc_counties(places)
        absent = [c for c in wanted if c not in available]
        columns = [c for c in wanted if c in available]
    data = _read(name, columns, None) if columns is None or columns else pd.DataFrame(
        index=_read(name, available[:1], None).index)
    for c in absent:
        data[c] = 0.0
    if absent:
        notes.append(f"not in {FILES[name]} (set to 0): {', '.join(absent)}")
    if columns is not None:
        data = data[wanted]
    index = hourly_range(start="2018-01-01", end="2022-12-31 23:00") if when is None else (
        when if isinstance(when, pd.DatetimeIndex) else hourly_range(when))
    inside = (index >= "2018-01-01") & (index < "2023-01-01")
    data = data.reindex(index.tz_convert("UTC"))
    data.loc[inside] = data.loc[inside].fillna(0.0)
    if convention == "load":
        data = -data
        data = data.where(data != 0, 0.0)   # no -0.0
    return _stamp(data, "wecc_dg", notes)


def county_names(which: str = "estimate") -> list[str]:
    """`"County ST"` columns of a bundled county file (`FILES` key)."""
    return _header(which)


__all__ = ["FILES", "county_names", "node_estimate", "path", "wecc_dg", "wecc_estimate"]
