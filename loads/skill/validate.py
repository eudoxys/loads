"""Check a `loads` frame against the package's stated contract before using it.

The `loads` package documents invariants (hourly UTC coverage, sector sums,
DG never positive, net = total + DG). Frames assembled from several `Total`
calls, edited, calibrated or read back from files only satisfy them if every
step kept them, so a workflow that feeds county loads to another tool should
check them on the frame it actually received. Pure pandas; works offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from . import schema
from .timeaxis import expected_hours

Level = Literal["error", "warning", "info"]


@dataclass
class Issue:
    level: Level
    check: str
    message: str
    count: int = 0

    def __str__(self) -> str:
        n = f" [{self.count}]" if self.count else ""
        return f"{self.level.upper():7s} {self.check}: {self.message}{n}"


@dataclass
class Report:
    """Validation outcome. `ok` is False if any error was found."""

    issues: list[Issue] = field(default_factory=list)
    rows: int = 0
    columns: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def add(self, level: Level, check: str, message: str, count: int = 0) -> None:
        self.issues.append(Issue(level, check, message, int(count)))

    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    def raise_if_failed(self) -> "Report":
        if not self.ok:
            raise ValueError("loads frame failed validation:\n" + str(self))
        return self

    def __str__(self) -> str:
        head = f"{'OK' if self.ok else 'FAILED'}: {self.rows} rows, {len(self.columns)} columns"
        return "\n".join([head] + [f"  {i}" for i in self.issues])


def validate(
    frame: pd.DataFrame,
    *,
    rtol: float = 1e-6,
    atol: float = 1e-3,
    require_full_years: bool = False,
    allow_edge_nan: int = max(-min(schema.TSGAM_LAGS), max(schema.TSGAM_LAGS)),
) -> Report:
    """Validate a `loads`-shaped frame.

    Errors: non-datetime or non-UTC index, duplicate or unsorted timestamps,
    gaps, positive DG, broken `net = total + dg`, broken sector sums, NaN in
    the interior of a power column, negative non-DG load.

    Warnings: NaN only at the lag-trimmed edges (up to `allow_edge_nan`
    hours, the `Total` lag window), partial years, implausible weather.

    `atol` is in MW; `loads` rounds outputs to 3 decimals.
    """
    rep = Report(rows=len(frame), columns=list(frame.columns))
    idx = frame.index

    # --- time axis
    if not isinstance(idx, pd.DatetimeIndex):
        rep.add("error", "index", f"index is {type(idx).__name__}, expected DatetimeIndex")
        return rep
    if idx.tz is None:
        rep.add("error", "timezone", "index is tz-naive; loads output is tz-aware UTC")
    elif str(idx.tz) != "UTC":
        rep.add("warning", "timezone", f"index tz is {idx.tz}; loads output is UTC")
    if idx.name != "timestamp":
        rep.add("info", "index-name", f"index name is {idx.name!r}, loads uses 'timestamp'")
    if idx.has_duplicates:
        rep.add("error", "duplicates", "duplicate timestamps", idx.duplicated().sum())
    if not idx.is_monotonic_increasing:
        rep.add("error", "order", "timestamps not sorted")
    if len(idx) > 1 and idx.is_monotonic_increasing and not idx.has_duplicates:
        steps = idx[1:] - idx[:-1]
        bad = np.flatnonzero(steps != pd.Timedelta(hours=1))
        utc = idx.tz_convert("UTC") if idx.tz is not None else idx
        year_gaps = [i for i in bad
                     if (utc[i].month, utc[i].day, utc[i].hour) == (12, 31, 23)
                     and (utc[i + 1].month, utc[i + 1].day, utc[i + 1].hour) == (1, 1, 0)]
        other = [i for i in bad if i not in year_gaps]
        if year_gaps:
            rep.add("info", "year-gaps", "non-contiguous whole years (e.g. 2018 and 2020 only)", len(year_gaps))
        if other:
            missing = expected_hours(idx) - len(idx)
            rep.add("error", "hourly", f"{len(other)} non-hourly steps ({missing} hours missing)", len(other))
    if len(idx):
        years = pd.Series(idx.year).value_counts().sort_index()
        partial = [
            f"{y}:{n}" for y, n in years.items()
            if n != (8784 if pd.Timestamp(f"{y}-01-01").is_leap_year else 8760)
        ]
        if partial:
            rep.add("error" if require_full_years else "info", "full-years",
                    "partial years (year:rows) " + ", ".join(partial), len(partial))

    # --- power columns
    power = schema.power_columns(frame.columns)
    samples = [c for c in frame.columns if str(c).startswith("sample_")]
    for col in power + samples:
        v = frame[col]
        nan = v.isna().to_numpy()
        if nan.any():
            k = len(v)
            head = int(np.argmax(~nan)) if (~nan).any() else k
            tail = int(np.argmax(~nan[::-1])) if (~nan).any() else k
            interior = int(nan.sum()) - head - tail
            if interior > 0 or head > allow_edge_nan or tail > allow_edge_nan:
                rep.add("error", "nan", f"{col} has NaN outside the lag edges", int(nan.sum()))
            else:
                rep.add("warning", "edge-nan",
                        f"{col} NaN in first {head}/last {tail} hours (Total lag window)", head + tail)
        if col == "elec_dg_MW":
            pos = int((v > atol).sum())
            if pos:
                rep.add("error", "dg-sign", "elec_dg_MW must be <= 0 (DG is a negative load)", pos)
        elif col != "elec_net_MW" and col in power:
            neg = int((v < -atol).sum())
            if neg:
                rep.add("error", "negative-load", f"{col} has negative values", neg)

    # --- identities
    def check_sum(target: str, parts: list[str], name: str) -> None:
        if target in frame and all(p in frame for p in parts):
            lhs = frame[target]
            rhs = frame[parts].sum(axis=1, min_count=len(parts))
            ok = np.isclose(lhs, rhs, rtol=rtol, atol=atol) | lhs.isna() | rhs.isna()
            bad = int((~ok).sum())
            if bad:
                worst = float((lhs - rhs).abs().max())
                rep.add("error", name, f"{target} != {' + '.join(parts)} (max |diff| {worst:.3g} MW)", bad)

    check_sum("elec_net_MW", ["elec_total_MW", "elec_dg_MW"], "net-identity")
    check_sum("elec_total_MW", list(schema.SECTOR_COLUMNS), "sector-sum")
    check_sum("elec_total_MW", list(schema.ELEC_ENDUSE_COLUMNS), "enduse-sum")
    check_sum("nonelec_total_MW", list(schema.NONELEC_ENDUSE_COLUMNS), "nonelec-enduse-sum")

    # --- weather plausibility
    bounds = {
        "temperature_degF": (-80.0, 140.0),
        "humidity_pc": (0.0, 100.5),
        "global_Wpms": (0.0, 1500.0),
        "direct_Wpms": (0.0, 1500.0),
        "diffuse_Wpms": (0.0, 1000.0),
    }
    for col, (lo, hi) in bounds.items():
        if col in frame:
            out = int(((frame[col] < lo) | (frame[col] > hi)).sum())
            if out:
                rep.add("warning", "weather-range", f"{col} outside [{lo}, {hi}]", out)

    return rep
