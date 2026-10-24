"""Turn hourly MW frames into the quantities people ask about.

All functions assume hourly rows (so summing MW gives MWh) and work on any
frame with `*_MW` columns, including `BatchResult.column(...)` panels.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import schema


def energy(frame: pd.DataFrame, freq: str | None = "MS", columns=None) -> pd.DataFrame:
    """Energy in MWh per period (`freq` is a pandas offset, e.g. `"MS"`,
    `"QS"`, `"YS"`, `"D"`; `None` for one total row). Output columns are
    renamed `*_MW` -> `*_MWh`. Periods are in the frame's timezone (UTC for
    raw `loads` output; convert first for local-calendar months)."""
    cols = list(columns) if columns is not None else schema.power_columns(frame.columns) or list(frame.columns)
    data = frame[cols] * schema.HOURS_PER_SAMPLE
    out = data.sum().to_frame("total").T if freq is None else data.resample(freq).sum(min_count=1)
    return out.rename(columns=lambda c: f"{c}h" if str(c).endswith("_MW") else c)


def peaks(frame: pd.DataFrame, columns=None, n: int = 1) -> pd.DataFrame:
    """Top-`n` hourly values and timestamps for each column (DG: most negative)."""
    cols = list(columns) if columns is not None else schema.power_columns(frame.columns) or list(frame.columns)
    rows = []
    for col in cols:
        s = frame[col].dropna()
        top = s.nsmallest(n) if col == "elec_dg_MW" else s.nlargest(n)
        for rank, (ts, val) in enumerate(top.items(), 1):
            rows.append({"column": col, "rank": rank, "timestamp": ts, "MW": float(val)})
    return pd.DataFrame(rows)


def load_factor(series: pd.Series) -> float:
    """Mean / peak over the series (NaN ignored)."""
    s = series.dropna()
    return float(s.mean() / s.max()) if len(s) and s.max() else float("nan")


def duration_curve(series: pd.Series) -> pd.Series:
    """Load duration curve: values sorted high to low, indexed by fraction of time."""
    s = np.sort(series.dropna().to_numpy())[::-1]
    return pd.Series(s, index=np.arange(1, len(s) + 1) / len(s), name=series.name).rename_axis("fraction_of_hours")


def daily_profile(series: pd.Series, by: str = "month", tzoffset_hours: float = 0.0) -> pd.DataFrame:
    """Average 24-hour shape grouped by `"month"`, `"season"`, `"weekday"` or
    `"none"`. `tzoffset_hours` shifts UTC to local standard time first (see
    `locations.County.tzoffset`)."""
    s = series.dropna()
    t = s.index.tz_convert("UTC").tz_localize(None) + pd.Timedelta(hours=tzoffset_hours) if s.index.tz is not None \
        else s.index + pd.Timedelta(hours=tzoffset_hours)
    df = pd.DataFrame({"v": s.to_numpy(), "hour": t.hour})
    if by == "month":
        df["group"] = t.month
    elif by == "season":
        df["group"] = pd.Series(t.month).map({12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
                                               6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}).to_numpy()
    elif by == "weekday":
        df["group"] = np.where(t.dayofweek < 5, "weekday", "weekend")
    elif by == "none":
        df["group"] = "all"
    else:
        raise ValueError(f"by={by!r}")
    return df.pivot_table(index="hour", columns="group", values="v", aggfunc="mean")


def temperature_response(frame: pd.DataFrame, column: str = "elec_total_MW",
                         temperature: str = "temperature_degF", bin_width: float = 5.0) -> pd.DataFrame:
    """Mean/min/max load in temperature bins; shows heating and cooling slopes."""
    df = frame[[temperature, column]].dropna()
    bins = np.floor(df[temperature] / bin_width) * bin_width
    g = df.groupby(bins)[column]
    out = pd.DataFrame({"mean_MW": g.mean(), "min_MW": g.min(), "max_MW": g.max(), "hours": g.size()})
    out.index.name = f"{temperature}_bin"
    return out


def coincident_peak(panel: pd.DataFrame) -> pd.DataFrame:
    """For a panel of counties/nodes (one column each): each column's value at
    the system peak hour, its own peak, the coincidence factor and its share
    of the system peak. The peak time and MW are in `.attrs`."""
    system = panel.sum(axis=1, min_count=1)
    t = system.idxmax()
    own = panel.max()
    at = panel.loc[t]
    out = pd.DataFrame({
        "at_system_peak_MW": at,
        "own_peak_MW": own,
        "coincidence": at / own.replace(0, np.nan),
        "share_of_system_peak": at / float(system.loc[t]),
    })
    out.attrs["system_peak_time"] = t
    out.attrs["system_peak_MW"] = float(system.loc[t])
    return out


def summary(frame: pd.DataFrame, column: str = "elec_total_MW") -> dict:
    """One-line facts for a report: annual MWh, peak, min, load factor."""
    s = frame[column].dropna()
    return {
        "column": column,
        "hours": int(len(s)),
        "start": str(s.index.min()) if len(s) else None,
        "end": str(s.index.max()) if len(s) else None,
        "energy_MWh": float(s.sum() * schema.HOURS_PER_SAMPLE),
        "mean_MW": float(s.mean()),
        "peak_MW": float(s.max()),
        "peak_time": str(s.idxmax()) if len(s) else None,
        "min_MW": float(s.min()),
        "load_factor": load_factor(s),
    }
