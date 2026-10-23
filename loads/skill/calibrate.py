"""Rescale county loads to known energy or peak values.

Three tools, from simplest to most constrained:

- `scale_to_energy` / `scale_monthly`: proportional rescaling
  (P_new = P_old * E_new / E_old), so the load shape is kept exactly. Pure
  pandas.
- `fit_energy_peak`: an affine rescale of one series that hits an energy and
  a peak target at once. Pure numpy.
- `shape_to_targets`: a front end to `loads.calibrate.Calibrate`, the convex
  net-load shaping program that fits a whole panel of counties (or nodes) to
  monthly state net-load energy targets and regional peak ceilings at once.
  It converts the `loads` sign convention for DG, checks the inputs the
  program rejects, and records provenance.

`loads.calibrate.Calibrate` is not a proportional rescale either: it fits a
scale *and an offset* per unit and per UTC calendar month. Use it when the
targets are regional (states, balancing areas) and coupled; use the
proportional helpers when each county has its own energy target.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

import numpy as np
import pandas as pd


def _window(frame: pd.DataFrame, start, end) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    if start is not None:
        mask &= frame.index >= pd.Timestamp(start, tz=frame.index.tz) if pd.Timestamp(start).tzinfo is None \
            else frame.index >= pd.Timestamp(start)
    if end is not None:
        mask &= frame.index <= pd.Timestamp(end, tz=frame.index.tz) if pd.Timestamp(end).tzinfo is None \
            else frame.index <= pd.Timestamp(end)
    return mask


def scale_to_energy(
    frame: pd.DataFrame,
    targets: dict[str, float],
    *,
    start=None,
    end=None,
    also_scale: dict[str, list[str]] | None = None,
    recompute_net: bool = True,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Proportionally rescale columns so their energy over [`start`, `end`]
    equals `targets[column]` in MWh: P_new = P_old * E_new / E_old.

    The factor is applied to the whole frame (not only the window), so the
    window is where the energy is matched. `also_scale={"elec_total_MW":
    ["elec_residential_MW", ...]}` applies the same factor to sector columns
    so the sector sum still holds. With `recompute_net`, `elec_net_MW` is
    recomputed from total and DG. Returns the new frame and the factors.
    """
    out = frame.copy()
    window = _window(frame, start, end)
    factors: dict[str, float] = {}
    for col, target in targets.items():
        old = float(frame.loc[window, col].sum())
        if old == 0:
            raise ValueError(f"{col} has zero energy in the window; cannot scale")
        k = float(target) / old
        factors[col] = k
        for c in [col] + list((also_scale or {}).get(col, [])):
            out[c] = frame[c] * k
    if recompute_net and {"elec_net_MW", "elec_total_MW", "elec_dg_MW"} <= set(out.columns):
        out["elec_net_MW"] = out["elec_total_MW"] + out["elec_dg_MW"]
    return out, factors


def scale_monthly(
    frame: pd.DataFrame,
    column: str,
    monthly_mwh: pd.Series,
    *,
    also_scale: list[str] | None = None,
    recompute_net: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """Match each calendar month's energy to `monthly_mwh` (indexed by month
    start, same tz as the frame), e.g. a county's share of EIA-861M retail
    sales. Returns the frame and the monthly factors. Months absent from
    `monthly_mwh` keep factor 1."""
    out = frame.copy()
    month = frame.index.to_period("M") if frame.index.tz is None else frame.index.tz_convert(None).to_period("M")
    old = frame[column].groupby(month).sum()
    target = monthly_mwh.copy()
    target.index = pd.DatetimeIndex(target.index).tz_localize(None).to_period("M") \
        if pd.DatetimeIndex(target.index).tz is not None else pd.DatetimeIndex(target.index).to_period("M")
    factor = (target / old).reindex(old.index).fillna(1.0)
    per_row = factor.reindex(month).to_numpy()
    for c in [column] + list(also_scale or []):
        out[c] = frame[c].to_numpy() * per_row
    if recompute_net and {"elec_net_MW", "elec_total_MW", "elec_dg_MW"} <= set(out.columns):
        out["elec_net_MW"] = out["elec_total_MW"] + out["elec_dg_MW"]
    return out, factor


def fit_energy_peak(series: pd.Series, *, energy: float | None = None, peak: float | None = None,
                    constraints=("positive", "inverted")) -> pd.Series:
    """Affine rescale `y = a*x + b` of one series so that its sum equals
    `energy` (MWh) and its value at the hour of the original peak equals
    `peak` (MW). Either target defaults to the series' own value.

    The minimum moves until the energy matches, so unlike a proportional
    rescale this changes the load factor. Constraints, checked after the
    fit (`ValueError` when violated):

    - `"positive"`: every value of the result is > 0;
    - `"inverted"`: the shape is not inverted (`a >= 0`), so the original
      peak hour is still the peak.

    Closed form; replaces the iterative `loads.calibrate.fit_load`, which
    the `Calibrate` rewrite removed.
    """
    for c in constraints:
        if c not in ("positive", "inverted"):
            raise ValueError(f"unknown constraint {c!r}")
    x = series.to_numpy(dtype=float)
    if np.isnan(x).any():
        raise ValueError("series contains NaN; fill the lag-window edges first")
    n = len(x)
    xmax, xsum = float(x.max()), float(x.sum())
    energy = xsum if energy is None else float(energy)
    peak = xmax if peak is None else float(peak)
    span = xsum - n * xmax
    if span == 0:
        raise ValueError("series is constant; an affine fit cannot change its energy and peak separately")
    a = (energy - n * peak) / span
    b = peak - a * xmax
    y = a * x + b
    if "inverted" in constraints and a < 0:
        raise ValueError(f"energy {energy:g} MWh and peak {peak:g} MW invert the load shape (slope {a:.3g})")
    if "positive" in constraints and y.min() <= 0:
        raise ValueError(f"energy {energy:g} MWh and peak {peak:g} MW give a minimum load of {y.min():.3g} MW")
    return pd.Series(y, index=series.index, name=series.name)


_COUNTY_ST = re.compile(r"^.+ [A-Z]{2}$")


def shape_to_targets(
    load: pd.DataFrame,
    *,
    energy: dict[str, float] | pd.Series | pd.DataFrame,
    peak: dict[str, float] | pd.Series | pd.DataFrame,
    dg: pd.DataFrame | None = None,
    dg_convention: Literal["load", "output"] = "load",
    regions: pd.DataFrame | dict | None = None,
    states: pd.DataFrame | dict | None = None,
    search: bool | list = True,
    progress: Callable[[int, int, dict], None] | None = None,
    **options: Any,
):
    """Shape a panel of gross loads to state energy and regional peak targets
    with `loads.calibrate.Calibrate`.

    - `load`: gross load panel in MW, one column per unit (`elec_total_MW` of
      each county, e.g. `BatchResult.column("elec_total_MW")`), hourly UTC,
      no NaN, nothing negative. Columns named `"County ST"` let `Calibrate`
      infer state membership; otherwise pass `states`.
    - `energy`: *net-load* energy targets (MWh) per state, i.e. load minus
      DG; a frame indexed by UTC month start gives one row per month.
    - `peak`: net-load peak ceilings (MW) per region (`{}` for none); a frame
      indexed by UTC month start gives one row per month.
    - `dg`: DG panel with the same columns. `dg_convention="load"` (default)
      means the `loads` sign convention (`elec_dg_MW <= 0`);
      `"output"` means positive generation (the bundled
      `loads/wecc/county_dg*.csv.gz` files). It is converted to the positive
      output `Calibrate` requires.
    - `regions`: peak-region membership (units x regions, 0..1, or dict of
      region -> unit list). Default: every unit is in every peak region.
    - `search`: `True` (default) runs `Calibrate`'s predeclared weight grid
      (88 solves per month for two regions) and its selection rule; `False`
      uses fixed weights from `options` (`energy_weight`, `drive`).
    - `options`: passed to `Calibrate` (`shape_weight`, `ridge`,
      `peak_multiple`, `relative_rmse`, `verbose`, ...).

    Each UTC calendar month is solved independently (expect small steps at
    month boundaries) and needs its own target row. Returns the `Calibrate`
    frame (shaped gross load, MW) with `.net`, `.parameters`, `.states`,
    `.regions`, `.summary` and `.constraints`; check `.summary.selection`
    and `.states.shaped_error`. Provenance is in `attrs["loadskill"]`.
    Raises `loads.calibrate.CalibrationError` when the program is infeasible.
    """
    from loads.calibrate import Calibrate

    X = pd.DataFrame(load)
    if peak is None or len(peak) == 0 or (isinstance(peak, pd.DataFrame) and peak.shape[1] == 0):
        # Calibrate builds its region table from the peak keys and raises
        # KeyError when there are none (see reference/footguns.md)
        raise ValueError("Calibrate needs at least one peak region; for energy-only matching "
                         "use scale_monthly or scale_to_energy")
    if X.isna().any().any():
        bad = [c for c in X.columns if X[c].isna().any()]
        raise ValueError(f"load has NaN in {bad[:5]}; Calibrate rejects NaN (fill the lag-window "
                         "edges, e.g. series(..., edges='fill'))")
    if (X < 0).any().any():
        raise ValueError("load must be the nonnegative gross load (elec_total_MW), not net load")
    if states is None:
        odd = [str(c) for c in X.columns if not _COUNTY_ST.match(str(c))]
        if odd:
            raise ValueError(f"columns {odd[:5]} are not 'County ST' names; pass states= "
                             "(units x states membership summing to 1 per unit)")
    D = None
    if dg is not None:
        D = pd.DataFrame(dg).reindex(index=X.index, columns=X.columns)
        if D.isna().any().any():
            raise ValueError("dg is missing hours or columns of load (reindex and fill first)")
        if dg_convention == "load":
            if (D > 1e-9).any().any():
                raise ValueError("dg has positive values but dg_convention='load' expects elec_dg_MW <= 0; "
                                 "pass dg_convention='output' for positive generation")
            D = -D
        elif dg_convention == "output":
            if (D < -1e-9).any().any():
                raise ValueError("dg has negative values but dg_convention='output' expects generation >= 0")
        else:
            raise ValueError(f"dg_convention must be 'load' or 'output', not {dg_convention!r}")
        D = D.clip(lower=0.0)
    result = Calibrate(X, energy=energy, peak=peak, dg=D, regions=regions, states=states,
                       search=search, progress=progress, **options)
    months = sorted({f"{t:%Y-%m}" for t in X.index.tz_convert("UTC")})
    result.attrs["loadskill"] = {
        "mode": "shape_to_targets",
        "columns": [str(c) for c in X.columns],
        "start": str(X.index[0]),
        "end": str(X.index[-1]),
        "notes": [
            "loads.calibrate.Calibrate: per-unit scale and offset per UTC month",
            f"blocks: {', '.join(months)}",
            f"search: {search if isinstance(search, bool) else f'{len(search)} candidates'}",
            f"dg: {'none' if dg is None else dg_convention + ' convention, passed to Calibrate as output'}",
        ],
    }
    return result
