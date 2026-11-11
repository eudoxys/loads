"""Safe front ends to `loads.Total` and `loads.Estimator` for larger workflows.

`loads.Total` returns the 2018 sector loads and their sum, nothing more.
`loads.Estimator` is the prediction API: it takes a `"County ST"` string and
a list of years, picks the predicted column through an `EstimatorConfig`,
and leaves the first hours of the first year NaN. These wrappers resolve the
place, build the configuration, select the requested hours, deal with the
NaN edge, and assemble the quantities downstream tools usually want
(total, DG, net, sectors).

Nothing here changes the model; every number still comes from `loads`.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from . import schema
from .locations import County, resolve
from .timeaxis import hourly_range

_log = logging.getLogger(__name__)

Mode = Literal["training", "predict"]
Edges = Literal["fill", "pad", "nan"]

DEFAULT_CACHEDIR = os.path.join(os.path.expanduser("~"), ".cache", "eudoxys")
NSRDB_CREDENTIALS = os.path.join(os.path.expanduser("~"), ".nsrdb", "credentials.json")


# --- environment ----------------------------------------------------------------

def check_credentials(path: str = NSRDB_CREDENTIALS) -> bool:
    """True when the NSRDB credentials file `weather` needs is present and
    parses as `{"email": "api_key"}`.

    `weather.Weather(state, county, year)` (used by every `Estimator` call)
    downloads NSRDB data. With no credentials file it tries to open a sign-up
    page in a browser, which hangs or fails in headless agents. Check first.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return isinstance(data, dict) and len(data) >= 1
    except (OSError, ValueError):
        return False


def configure(
    cachedir: str | None = None,
    *,
    require_credentials: bool = True,
) -> dict[str, Any]:
    """Prepare the process for `loads` calls. Call once at workflow start.

    - Points the shared `cache.Cache` at `cachedir` (default `$LOADS_CACHEDIR`
      or `~/.cache/eudoxys`). Upstream defaults to a folder inside
      site-packages, which is lost on reinstall and often read-only.
    - Raises `RuntimeError` early if NSRDB credentials are missing.
    """
    from cache import Cache

    cachedir = cachedir or os.environ.get("LOADS_CACHEDIR") or DEFAULT_CACHEDIR
    Cache.cachedir(cachedir)
    ok = check_credentials()
    if require_credentials and not ok:
        raise RuntimeError(
            f"NSRDB credentials not found at {NSRDB_CREDENTIALS}. Register at "
            "https://developer.nlr.gov/signup/ and write {\"<email>\": \"<api_key>\"} "
            "to that file (the user must do this; never invent a key)."
        )
    return {"cachedir": cachedir, "nsrdb_credentials": ok}


# --- results --------------------------------------------------------------------

@dataclass
class Provenance:
    """What produced a frame. Stored in `frame.attrs["loadskill"]`."""

    county: str
    mode: str
    columns: list[str]
    start: str | None = None
    end: str | None = None
    edges: str | None = None
    edge_hours_filled: int = 0
    notes: list[str] = field(default_factory=list)
    loads_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _loads_version() -> str | None:
    try:
        from importlib.metadata import distribution

        dist = distribution("loads")
        try:
            info = json.loads(dist.read_text("direct_url.json") or "{}")
            commit = info.get("vcs_info", {}).get("commit_id")
        except ValueError:
            commit = None
        return f"{dist.version}+{commit[:7]}" if commit else dist.version
    except Exception:  # pragma: no cover - metadata absent
        return None


def _stamp(frame: pd.DataFrame, prov: Provenance) -> pd.DataFrame:
    prov.loads_version = prov.loads_version or _loads_version()
    frame.attrs["loadskill"] = prov.as_dict()
    return frame


# --- single-series access --------------------------------------------------------

def training(place, refresh: bool = False) -> pd.DataFrame:
    """The 2018 sector loads `loads.Total` returns.

    Columns: `elec_{sector}_MW` for every sector and `elec_total_MW`, their
    sum. 8760 rows, no weather, no DG, no net load. This is the closest
    thing to "actual" county load `loads` has; it is always 2018.
    """
    from loads import Total

    c = place if isinstance(place, County) else resolve(place)
    data = pd.DataFrame(Total(c.state, c.county, refresh=refresh))
    return _stamp(
        data,
        Provenance(county=c.county_st, mode="training", columns=list(data.columns),
                   start=str(data.index[0]), end=str(data.index[-1])),
    )


def series(
    place,
    when,
    column: str = "elec_total_MW",
    *,
    mode: Mode = "predict",
    edges: Edges = "fill",
    X: Iterable[str] | None = None,
    keep_actuals: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """One `Estimator` target for an arbitrary period.

    `when` is a year, list of years, or a `DatetimeIndex` (see
    `timeaxis.hourly_range`). `mode="predict"` returns the `X` weather
    columns (default `schema.ESTIMATOR_WEATHER`) and `column`;
    `mode="training"` returns `training()`. `column` must be one of
    `schema.PREDICTABLE_TARGETS`, which maps it to the `Estimator`
    `sectors` and `enduse`. With `keep_actuals` (the `Estimator` default)
    2018 hours hold the 2018 sector loads instead of the estimate.

    `Estimator` leaves the first `max(-lag)` hours of the first estimated
    year NaN (weather lags, `schema.ESTIMATOR_LAGS`). `edges="fill"` copies
    the first valid hour into them, `"pad"` also estimates the previous year
    and trims it (needs that year's NSRDB weather), `"nan"` leaves them.
    `refresh` only applies to `mode="training"`.
    """
    from loads.estimator import Estimator, EstimatorConfig

    c = place if isinstance(place, County) else resolve(place)
    if mode == "training":
        return training(c, refresh=refresh)
    if mode != "predict":
        raise ValueError(f"mode must be 'predict' or 'training', not {mode!r}")
    index = when if isinstance(when, pd.DatetimeIndex) else hourly_range(when)
    if column not in schema.PREDICTABLE_TARGETS:
        raise ValueError(
            f"{column!r} cannot be estimated; use one of {sorted(schema.PREDICTABLE_TARGETS)}. "
            "Industrial and agricultural loads are flat: take them from training(). "
            "DG is not estimated: use loads.dgen.DG (county_loads(dg=True))."
        )
    sectors, enduse = schema.PREDICTABLE_TARGETS[column]
    weather = list(X) if X is not None else list(schema.ESTIMATOR_WEATHER)
    head = max([0] + [-lag for lag in schema.ESTIMATOR_LAGS])
    years = sorted(set(index.year))
    if edges == "pad" and (index[0] - pd.Timedelta(hours=head)).year < index[0].year:
        years = [years[0] - 1] + years
    config = EstimatorConfig(sectors=list(sectors), enduse=enduse, weather=weather,
                             keep_actuals=keep_actuals)
    data = pd.DataFrame(Estimator(c.county_st, years, config=config))
    data = data.rename(columns={enduse: column}) if enduse != column else data
    data = data.reindex(index).rename_axis("timestamp")
    filled = 0
    if edges == "fill":
        filled = int(data[column].isna().sum())
        data[column] = data[column].ffill().bfill()
    prov = Provenance(
        county=c.county_st, mode=mode, columns=list(data.columns),
        start=str(index[0]), end=str(index[-1]),
        edges=edges, edge_hours_filled=filled,
    )
    if keep_actuals and (index.year == schema.TRAINING_YEAR).any():
        prov.notes.append(f"{schema.TRAINING_YEAR} hours are Estimator keep_actuals (2018 sector loads)")
    return _stamp(data, prov)


# --- assembled county frames ------------------------------------------------------

def county_loads(
    place,
    when,
    *,
    dg: bool = False,
    sectors: bool = False,
    total: Literal["direct", "sum"] | None = None,
    use_training_actuals: bool = True,
    edges: Edges = "fill",
    refresh: bool = False,
) -> pd.DataFrame:
    """A county frame with the columns downstream models usually want.

    Returns the estimator weather columns and `elec_total_MW`. With
    `sectors=True`, residential and commercial are estimated from weather
    and industrial, agricultural and transportation are copied from the flat
    2018 `Total` level.

    `total="direct"` estimates `elec_total_MW` with its own model (all
    sectors, the `Estimator` default); `"sum"` sets it to the sum of the
    sector columns so the sector identity holds exactly. Default: `"sum"`
    when `sectors` else `"direct"`. The two differ by a few percent; never
    mix them in one study.

    `dg=True` adds `elec_dg_MW` from `loads.dgen.DG` (what `DG.merge` adds):
    EIA-861M state small-scale solar allocated to the county by its share of
    state energy use and shaped by NSRDB irradiance, so monthly DG energy
    matches EIA. It needs EIA access and covers only counties in
    `loads/wecc/county_mwh.csv` (the 13 WECC states); other counties get zero
    DG with a warning, and months EIA has not published are NaN. It also
    adds `elec_net_MW = elec_total_MW + elec_dg_MW`. `Total` and `Estimator`
    have no DG of their own.

    Hours in the training year (2018) are taken from `training()` when
    `use_training_actuals` (as `Estimator`'s `keep_actuals` does).
    """
    c = place if isinstance(place, County) else resolve(place)
    index = when if isinstance(when, pd.DatetimeIndex) else hourly_range(when)
    total = total or ("sum" if sectors else "direct")
    if total not in ("direct", "sum"):
        raise ValueError(f"total must be 'direct' or 'sum', not {total!r}")
    notes: list[str] = []
    ref = None
    if sectors or use_training_actuals:
        ref = training(c, refresh=refresh)

    frames = []
    if total == "direct":
        frames.append(series(c, index, "elec_total_MW", edges=edges, keep_actuals=use_training_actuals))
    if sectors:
        for s in schema.WEATHER_DRIVEN_SECTORS:
            part = series(c, index, f"elec_{s}_MW", edges=edges, keep_actuals=use_training_actuals)
            frames.append(part if not frames else part[[f"elec_{s}_MW"]])
    out = pd.concat(frames, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]

    if sectors:
        for s in schema.SECTORS:
            col = f"elec_{s}_MW"
            if s not in schema.WEATHER_DRIVEN_SECTORS:
                out[col] = float(ref[col].mean()) if col in ref.columns else 0.0
        notes.append("industrial/agricultural flat at 2018 training level; transportation 0")
        if total == "sum":
            out["elec_total_MW"] = out[list(schema.SECTOR_COLUMNS)].sum(axis=1)

    if use_training_actuals and ref is not None:
        hit = out.index.isin(ref.index)
        if hit.any():
            for col in out.columns:
                if col in ref.columns:
                    out.loc[hit, col] = ref.loc[out.index[hit], col].values
            notes.append(f"{int(hit.sum())} hours replaced by 2018 training data")

    if dg:
        from loads.dgen import DG

        eia = pd.DataFrame(DG(c.state, c.county, date_range=index, refresh=refresh))
        out["elec_dg_MW"] = eia["elec_dg_MW"].reindex(out.index).to_numpy()
        out["elec_net_MW"] = out["elec_total_MW"] + out["elec_dg_MW"]
        notes.append("elec_dg_MW from loads.dgen.DG (EIA-861M small-scale solar, NSRDB shape)")

    weather = [c_ for c_ in schema.WEATHER_COLUMNS if c_ in out.columns]
    loads_cols = [c_ for c_ in out.columns if c_ not in weather]
    out = out[loads_cols + weather].rename_axis("timestamp")
    mode = f"county_loads(total={total}" + (", dg=eia)" if dg else ")")
    prov = Provenance(county=c.county_st, mode=mode,
                      columns=list(out.columns), start=str(index[0]), end=str(index[-1]),
                      edges=edges, notes=notes)
    return _stamp(out, prov)


# --- many counties ------------------------------------------------------------------

@dataclass
class BatchResult:
    """Results of `batch`: successes keyed by `"County ST"` plus failures."""

    frames: dict[str, pd.DataFrame]
    errors: dict[str, str]

    def column(self, name: str) -> pd.DataFrame:
        """One column from every successful county, side by side."""
        return pd.concat({k: v[name] for k, v in self.frames.items() if name in v}, axis=1)


def batch(
    places: Iterable,
    func: Callable[..., pd.DataFrame] = county_loads,
    *args,
    on_error: Literal["collect", "raise"] = "collect",
    progress: Callable[[str, int, int], None] | None = None,
    **kwargs,
) -> BatchResult:
    """Run `func(county, *args, **kwargs)` over many counties.

    Failures (missing data, solver trouble, network) are collected rather
    than aborting a long sweep; inspect `result.errors` and report them.
    Each county fits its own TSGAM; `Estimator` keeps no fitted models.
    """
    resolved = [p if isinstance(p, County) else resolve(p) for p in places]
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for n, c in enumerate(resolved, 1):
        if progress:
            progress(c.county_st, n, len(resolved))
        try:
            frames[c.county_st] = func(c, *args, **kwargs)
        except Exception as err:  # noqa: BLE001 - deliberate collection
            if on_error == "raise":
                raise
            errors[c.county_st] = f"{type(err).__name__}: {err}"
            _log.warning("%s failed: %s", c.county_st, err)
    return BatchResult(frames, errors)


def nan_safe_sum(frames: Iterable[pd.Series]) -> pd.Series:
    """Sum aligned series treating missing as 0 (what `loads.aggregate` does)."""
    frames = list(frames)
    if not frames:
        return pd.Series(dtype=float)
    return pd.concat(frames, axis=1).fillna(0.0).sum(axis=1)


__all__ = [
    "BatchResult", "Provenance", "batch", "check_credentials", "configure",
    "county_loads", "nan_safe_sum", "series", "training",
]
