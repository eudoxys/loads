"""Hourly UTC time axes in the form `loads` expects.

`Total(..., date_range=...)` requires a `pd.DatetimeIndex`; it does not take a
year. All `loads` output is indexed by tz-aware UTC `timestamp`, hourly, with
8760 rows per normal year and 8784 per leap year.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


def hourly_range(
    years: int | Iterable[int] | None = None,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DatetimeIndex:
    """Build the hourly UTC index `Total` needs.

    `hourly_range(2020)` -> 8784 hours of 2020.
    `hourly_range([2019, 2021])` -> 2019 and 2021 only (no 2020 gap filler).
    `hourly_range(start="2020-07-01", end="2020-07-31 23:00")` -> inclusive.
    Naive `start`/`end` are interpreted as UTC.
    """
    if years is not None:
        if start is not None or end is not None:
            raise ValueError("give either years or start/end, not both")
        if isinstance(years, int):
            years = [years]
        parts = [
            pd.date_range(f"{y}-01-01 00:00", f"{y}-12-31 23:00", freq="1h", tz="UTC")
            for y in sorted(set(int(y) for y in years))
        ]
        if not parts:
            raise ValueError("years is empty")
        idx = parts[0].append(parts[1:]) if len(parts) > 1 else parts[0]
    else:
        if start is None or end is None:
            raise ValueError("give years, or both start and end")
        start, end = _utc(start), _utc(end)
        idx = pd.date_range(start, end, freq="1h")
    return idx.rename("timestamp")


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def expected_hours(index: pd.DatetimeIndex) -> int:
    """Number of hourly rows a contiguous index from first to last should have."""
    if len(index) == 0:
        return 0
    return int((index.max() - index.min()) / pd.Timedelta(hours=1)) + 1


def to_local_standard(frame: pd.DataFrame, tzoffset_hours: float) -> pd.DataFrame:
    """Shift a UTC frame to local *standard* time (no DST), the convention
    `loads.Cluster` uses (`fips` `TZOFFSET`). Returns a copy with a naive index."""
    out = frame.copy()
    idx = out.index
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    out.index = (idx + pd.Timedelta(hours=tzoffset_hours)).rename("local_standard_time")
    return out


def to_local(frame: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Convert to an IANA zone, e.g. `"America/Los_Angeles"` (with DST)."""
    out = frame.copy()
    out.index = out.index.tz_convert(tz)
    return out
