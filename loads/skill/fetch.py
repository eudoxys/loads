"""Safe front ends to `loads.Total` for use inside larger workflows.

`loads.Total` has four modes selected by `samples`, and their outputs differ in
shape. Agents keep tripping on that, so these wrappers make the mode explicit,
build the time axis, deal with the lag-trimmed edges, and assemble the
quantities downstream tools usually want (total, DG, net, sectors).

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

Mode = Literal["training", "predict", "sample", "percentile", "samples"]
Edges = Literal["fill", "pad", "nan"]

DEFAULT_CACHEDIR = os.path.join(os.path.expanduser("~"), ".cache", "eudoxys")
NSRDB_CREDENTIALS = os.path.join(os.path.expanduser("~"), ".nsrdb", "credentials.json")


# --- environment ----------------------------------------------------------------

def check_credentials(path: str = NSRDB_CREDENTIALS) -> bool:
    """True when the NSRDB credentials file `weather` needs is present and
    parses as `{"email": "api_key"}`.

    `weather.Weather(state, county, year)` (used by every `Total` call)
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
    estimator_cache: bool = True,
) -> dict[str, Any]:
    """Prepare the process for `loads` calls. Call once at workflow start.

    - Points the shared `cache.Cache` at `cachedir` (default `$LOADS_CACHEDIR`
      or `~/.cache/eudoxys`). Upstream defaults to a folder inside
      site-packages, which is lost on reinstall and often read-only.
    - Raises `RuntimeError` early if NSRDB credentials are missing.
    - `estimator_cache=False` sets `Total.cache = None` so fitted TSGAM models
      are not kept in memory (do this for many-county sweeps).
    """
    from cache import Cache
    from loads import Total

    cachedir = cachedir or os.environ.get("LOADS_CACHEDIR") or DEFAULT_CACHEDIR
    Cache.cachedir(cachedir)
    if not estimator_cache:
        Total.cache = None
    elif Total.cache is None:
        Total.cache = {}
    ok = check_credentials()
    if require_credentials and not ok:
        raise RuntimeError(
            f"NSRDB credentials not found at {NSRDB_CREDENTIALS}. Register at "
            "https://developer.nlr.gov/signup/ and write {\"<email>\": \"<api_key>\"} "
            "to that file (the user must do this; never invent a key)."
        )
    return {"cachedir": cachedir, "nsrdb_credentials": ok, "estimator_cache": Total.cache is not None}


# --- results --------------------------------------------------------------------

@dataclass
class Provenance:
    """What produced a frame. Stored in `frame.attrs["loadskill"]`."""

    county: str
    mode: str
    columns: list[str]
    start: str | None = None
    end: str | None = None
    samples: int | None = None
    percentile: float | None = None
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


def _contiguous_runs(index: pd.DatetimeIndex) -> list[pd.DatetimeIndex]:
    if len(index) < 2:
        return [index]
    breaks = [i + 1 for i, d in enumerate(index[1:] - index[:-1]) if d != pd.Timedelta(hours=1)]
    bounds = [0] + breaks + [len(index)]
    return [index[a:b] for a, b in zip(bounds[:-1], bounds[1:])]


# --- single-series access --------------------------------------------------------

def training(place, refresh: bool = False) -> pd.DataFrame:
    """The 2018 reference frame `Total` trains on (`samples=None`).

    Columns: weather, `elec_{sector}_MW` for every sector, `elec_dg_MW` (<=0),
    `elec_total_MW`, `elec_net_MW`. 8760 rows. This is the closest thing to
    "actual" county load `loads` has; it ignores any date range.
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
    samples: int = 100,
    percentile: float = 50.0,
    edges: Edges = "fill",
    X: Iterable[str] | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """One `Total` target for an arbitrary period.

    `when` is a year, list of years, or a `DatetimeIndex` (see
    `timeaxis.hourly_range`). Modes map to `Total(samples=...)`:

    | mode         | `samples` | output                                   |
    |--------------|-----------|------------------------------------------|
    | `predict`    | 0         | X columns + `column` (deterministic)     |
    | `sample`     | 1         | X columns + `column` (one AR draw)       |
    | `percentile` | n>1       | X columns + `column` at `percentile`     |
    | `samples`    | n>1       | X columns + `sample_0..sample_{n-1}`     |

    `Total` blanks the first 3 and last 3 hours (exogenous lag window).
    `edges="fill"` copies the nearest valid hour into them, `"pad"` widens
    the request by the lag window and trims (needs weather for the adjacent
    hours, i.e. possibly another NSRDB year), `"nan"` leaves them.
    """
    from loads import Total

    c = place if isinstance(place, County) else resolve(place)
    if mode == "training":
        return training(c, refresh=refresh)
    index = when if isinstance(when, pd.DatetimeIndex) else hourly_range(when)
    if column not in schema.PREDICTABLE_TARGETS and X is None:
        raise ValueError(
            f"{column!r} has no default exogenous variables in Total; pass X=..., "
            f"or use one of {sorted(schema.PREDICTABLE_TARGETS)}. Industrial and "
            "agricultural loads are flat: take them from training()."
        )
    runs = _contiguous_runs(index)
    if len(runs) > 1:
        # Total treats its date_range as one series (lags, AR); a gap would be
        # bridged as if adjacent. Predict each contiguous block separately.
        parts = [series(c, r, column, mode=mode, samples=samples, percentile=percentile,
                        edges=edges, X=X, refresh=refresh) for r in runs]
        out = pd.concat(parts)
        prov = Provenance(**parts[0].attrs["loadskill"])
        prov.start, prov.end = str(index[0]), str(index[-1])
        prov.edge_hours_filled = sum(p_.attrs["loadskill"]["edge_hours_filled"] for p_ in parts)
        prov.notes.append(f"{len(runs)} contiguous blocks predicted separately")
        return _stamp(out, prov)
    head = max([0] + [-lag for lag in schema.TSGAM_LAGS])
    tail = max([0] + list(schema.TSGAM_LAGS))
    request = index
    if edges == "pad":
        request = pd.date_range(index[0] - pd.Timedelta(hours=head),
                                index[-1] + pd.Timedelta(hours=tail), freq="1h")
    nsamples = {"predict": 0, "sample": 1}.get(mode, samples)
    if mode in ("percentile", "samples") and nsamples < 2:
        raise ValueError(f"mode={mode!r} needs samples >= 2")
    kwargs: dict[str, Any] = dict(Y=column, date_range=request, samples=nsamples, refresh=refresh)
    if X is not None:
        kwargs["X"] = list(X)
    if mode == "percentile":
        kwargs["percentile"] = percentile
    elif mode == "samples":
        kwargs["percentile"] = None
    data = pd.DataFrame(Total(c.state, c.county, **kwargs))
    data = data.loc[data.index.isin(index)]
    targets = [col for col in data.columns if col == column or col.startswith("sample_")]
    filled = 0
    if edges == "fill":
        before = int(data[targets].isna().sum().max()) if targets else 0
        data[targets] = data[targets].ffill().bfill()
        filled = before
    if column == "elec_dg_MW":
        data[targets] = data[targets].clip(upper=0.0)
    prov = Provenance(
        county=c.county_st, mode=mode, columns=list(data.columns),
        start=str(index[0]), end=str(index[-1]),
        samples=nsamples if mode in ("percentile", "samples") else None,
        percentile=percentile if mode == "percentile" else None,
        edges=edges, edge_hours_filled=filled,
    )
    if column == "elec_dg_MW":
        prov.notes.append("elec_dg_MW clipped to <= 0")
    return _stamp(data, prov)


# --- assembled county frames ------------------------------------------------------

def county_loads(
    place,
    when,
    *,
    dg: bool = True,
    sectors: bool = False,
    total: Literal["direct", "sum"] | None = None,
    use_training_actuals: bool = True,
    edges: Edges = "fill",
    refresh: bool = False,
) -> pd.DataFrame:
    """A county frame with the columns downstream models usually want.

    Returns weather, `elec_total_MW`, and with `dg=True` also `elec_dg_MW`
    and `elec_net_MW = elec_total_MW + elec_dg_MW`. With `sectors=True`,
    residential and commercial are predicted from weather and industrial,
    agricultural and transportation are copied from the flat 2018 training
    level.

    `total="direct"` predicts `elec_total_MW` with its own model (what
    `Total` does); `"sum"` sets it to the sum of the sector columns so the
    sector identity holds exactly. Default: `"sum"` when `sectors` else
    `"direct"`. The two differ by a few percent; never mix them in one study.

    Hours in the training year (2018) are taken from `training()` when
    `use_training_actuals` (mirrors `Estimator`'s `keep_actuals`).
    """
    c = place if isinstance(place, County) else resolve(place)
    index = when if isinstance(when, pd.DatetimeIndex) else hourly_range(when)
    total = total or ("sum" if sectors else "direct")
    notes: list[str] = []
    ref = None
    if sectors or use_training_actuals:
        ref = training(c, refresh=refresh)

    frames = []
    if total == "direct":
        frames.append(series(c, index, "elec_total_MW", edges=edges, refresh=refresh))
    if sectors:
        for s in schema.WEATHER_DRIVEN_SECTORS:
            frames.append(series(c, index, f"elec_{s}_MW", edges=edges, refresh=refresh)[[f"elec_{s}_MW"]])
    if dg:
        frames.append(series(c, index, "elec_dg_MW", edges=edges, refresh=refresh)[["elec_dg_MW"]])
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
        out["elec_net_MW"] = out["elec_total_MW"] + out["elec_dg_MW"]

    weather = [c_ for c_ in schema.WEATHER_COLUMNS if c_ in out.columns]
    loads_cols = [c_ for c_ in out.columns if c_ not in weather]
    out = out[loads_cols + weather].rename_axis("timestamp")
    prov = Provenance(county=c.county_st, mode=f"county_loads(total={total})",
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
    clear_estimator_cache: bool = True,
    progress: Callable[[str, int, int], None] | None = None,
    **kwargs,
) -> BatchResult:
    """Run `func(county, *args, **kwargs)` over many counties.

    Failures (missing data, solver trouble, network) are collected rather
    than aborting a long sweep; inspect `result.errors` and report them.
    `clear_estimator_cache` drops fitted models between counties to bound
    memory (each county fits its own TSGAM).
    """
    from loads import Total

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
        finally:
            if clear_estimator_cache:
                Total._clear_cache()
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
