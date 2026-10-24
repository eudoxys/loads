"""Map county loads onto network nodes (buses, zones, balancing areas).

`loads.aggregate.aggregate` does this only for WECC counties, always
nearest-node, and recomputes every county with `samples=1` (a random AR
draw). These helpers work for any node list and any county frames you
already have, and support explicit fractional allocations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

from .locations import County, resolve

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km (vectorized)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def nearest_nodes(
    counties: Iterable,
    nodes: pd.DataFrame,
    *,
    lat: str = "lat",
    lon: str = "lon",
    max_km: float | None = None,
) -> pd.DataFrame:
    """Assign each county centroid (from `fips`) to its nearest node.

    `nodes` is indexed by node id with `lat`/`lon` columns. Returns one row
    per county: `node`, `distance_km`. Counties farther than `max_km` get
    `node = None` so they are reported instead of silently attached.
    """
    rows = []
    nlat, nlon = nodes[lat].to_numpy(float), nodes[lon].to_numpy(float)
    for c in counties:
        c = c if isinstance(c, County) else resolve(c)
        d = haversine_km(c.lat, c.lon, nlat, nlon)
        k = int(np.argmin(d))
        node = nodes.index[k] if (max_km is None or d[k] <= max_km) else None
        rows.append({"county": c.county_st, "node": node, "distance_km": float(d[k])})
    return pd.DataFrame(rows).set_index("county")


def allocate(
    county_series: Mapping[str, pd.Series],
    mapping: Mapping[str, str | Mapping[str, float]] | pd.DataFrame,
    *,
    fill: float | None = 0.0,
    strict: bool = True,
) -> pd.DataFrame:
    """Sum county series into node columns.

    `mapping` is `{"County ST": node}` for whole-county assignment,
    `{"County ST": {node_a: 0.6, node_b: 0.4}}` for splits (shares must sum
    to 1), or the frame returned by `nearest_nodes`. `fill` replaces NaN in
    county series before summing (`None` propagates NaN). With `strict`,
    counties missing from `mapping` raise instead of being dropped.
    """
    if isinstance(mapping, pd.DataFrame):
        mapping = {k: v for k, v in mapping["node"].items() if v is not None}
    missing = [k for k in county_series if k not in mapping]
    if missing and strict:
        raise KeyError(f"no node mapping for {missing}")
    columns: dict[str, pd.Series] = {}
    for county, s in county_series.items():
        if county not in mapping:
            continue
        target = mapping[county]
        shares = {target: 1.0} if not isinstance(target, Mapping) else dict(target)
        total = sum(shares.values())
        if not np.isclose(total, 1.0, atol=1e-6):
            raise ValueError(f"{county}: shares sum to {total}, expected 1")
        v = s if fill is None else s.fillna(fill)
        for node, share in shares.items():
            add = v * share
            columns[node] = add if node not in columns else columns[node].add(add, fill_value=0 if fill is not None else None)
    out = pd.DataFrame(columns).sort_index(axis=1)
    out.index.name = "timestamp"
    return out


def conservation_error(county_series: Mapping[str, pd.Series], nodal: pd.DataFrame) -> float:
    """Total county energy minus total nodal energy (MWh); ~0 when every
    county is mapped. Report it alongside any nodal output."""
    src = sum(float(s.fillna(0).sum()) for s in county_series.values())
    return src - float(nodal.fillna(0).to_numpy().sum())
