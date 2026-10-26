"""Sweep a state's counties, map them to network nodes, check conservation.

Needs data access and NSRDB credentials. A state with many counties takes a
long time on first run; outputs are written per county so reruns resume.

    python3 loads/skill/examples/nodal_profiles.py NV 2020 nodes.csv

`nodes.csv` has columns `id,lat,lon` (e.g. buses of a network model). The
WECC 240-bus node list is at
https://github.com/eudoxys/wecc240/raw/refs/heads/main/wecc240/gis/wecc240.csv
(columns GEOHASH, LAT, LON).
"""

import os
import sys

import pandas as pd

import loads.skill as ls


def county_file(c, year, outdir):
    path = os.path.join(outdir, f"{c.state}_{c.county.replace(' ', '_')}_{year}.csv.gz")
    if os.path.exists(path):
        df = ls.read_csv(path)
        if ls.validate(df).ok:
            return df
    df = ls.county_loads(c, year)
    ls.validate(df).raise_if_failed()
    ls.to_csv(df, path)
    return df


def main(state: str, year: int, nodes_csv: str, outdir: str = "out/counties") -> None:
    ls.configure(estimator_cache=False)
    nodes = pd.read_csv(nodes_csv).set_index("id")[["lat", "lon"]]
    places = ls.counties(state=state)
    ambiguous = [c.county_st for c in places if c.ambiguous]
    if ambiguous:
        print("ambiguous county names (loads cannot disambiguate):", ambiguous)

    res = ls.batch(places, county_file, year, outdir,
                   progress=lambda name, n, k: print(f"[{n}/{k}] {name}", flush=True))
    for name, err in res.errors.items():
        print("FAILED", name, err)

    mapping = ls.nearest_nodes([ls.resolve(n) for n in res.frames], nodes)
    county_net = {n: f["elec_net_MW"] for n, f in res.frames.items()}
    nodal = ls.allocate(county_net, mapping)
    print("conservation error (MWh):", ls.conservation_error(county_net, nodal))
    print(ls.coincident_peak(nodal).round(1))

    ls.to_csv(nodal, f"out/{state}_{year}_nodal_net.csv.gz",
              extra={"mapping": "nearest county centroid", "failed": res.errors,
                     "ambiguous": ambiguous})
    mapping.to_csv(f"out/{state}_{year}_mapping.csv")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
