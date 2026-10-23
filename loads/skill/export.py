"""Hand `loads` results to the next tool without losing what they are.

Every writer here saves a `<file>.meta.json` sidecar with the provenance
stored in `frame.attrs["loadskill"]` (county, mode, period, edge handling,
`loads` version) plus caller-supplied notes, so a downstream step or a
later reader can tell a deterministic prediction from a random sample.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _meta(frame: pd.DataFrame, extra: dict[str, Any] | None) -> dict[str, Any]:
    meta = dict(frame.attrs.get("loadskill", {}))
    meta.update(extra or {})
    meta["written_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["rows"] = int(len(frame))
    meta["columns"] = [str(c) for c in frame.columns]
    meta["units"] = {str(c): ("MW" if str(c).endswith("_MW") else None) for c in frame.columns}
    return meta


def write_sidecar(path: str, frame: pd.DataFrame, extra: dict[str, Any] | None = None) -> str:
    side = f"{path}.meta.json"
    with open(side, "w", encoding="utf-8") as fh:
        json.dump(_meta(frame, extra), fh, indent=2, default=str)
    return side


def read_sidecar(path: str) -> dict[str, Any]:
    with open(f"{path}.meta.json", encoding="utf-8") as fh:
        return json.load(fh)


def to_csv(frame: pd.DataFrame, path: str, *, precision: int | None = 3,
           extra: dict[str, Any] | None = None) -> str:
    """CSV (gzip if the name ends in `.gz`) with ISO UTC timestamps + sidecar."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = frame.round(precision) if precision is not None else frame
    data.to_csv(path, index=True, header=True, date_format="%Y-%m-%d %H:%M:%S%z")
    write_sidecar(path, frame, extra)
    return path


def read_csv(path: str) -> pd.DataFrame:
    """Read a CSV written by `to_csv` (or by `loads`) back with a UTC index
    and its provenance restored to `attrs`."""
    data = pd.read_csv(path, index_col=0, parse_dates=[0])
    if data.index.tz is None:
        data.index = pd.DatetimeIndex(data.index).tz_localize("UTC")
    data.index.name = "timestamp"
    try:
        data.attrs["loadskill"] = read_sidecar(path)
    except OSError:
        pass
    return data


def to_long(frame: pd.DataFrame, id_name: str = "series", value_name: str = "MW") -> pd.DataFrame:
    """Tidy (timestamp, series, value) form for databases and plotting."""
    return (frame.rename_axis("timestamp").reset_index()
            .melt(id_vars="timestamp", var_name=id_name, value_name=value_name))


def to_player(series: pd.Series, path: str, *, scale: float = 1.0, precision: int = 4,
              extra: dict[str, Any] | None = None) -> str:
    """GridLAB-D player file: `YYYY-MM-DD HH:MM:SS UTC,value` per line.

    `scale` converts units (e.g. `1e3` for kW). Missing values are dropped,
    because a player holds the last value until the next timestamp.
    """
    s = series.dropna() * scale
    idx = s.index.tz_convert("UTC") if s.index.tz is not None else s.index
    with open(path, "w", encoding="utf-8") as fh:
        for t, v in zip(idx, s.to_numpy()):
            fh.write(f"{t:%Y-%m-%d %H:%M:%S} UTC,{v:.{precision}f}\n")
    write_sidecar(path, series.to_frame(), {"format": "gridlabd-player", "scale": scale, **(extra or {})})
    return path
