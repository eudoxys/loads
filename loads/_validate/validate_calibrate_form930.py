"""Validate `CalibrateForm930` on the WECC 2018-2022 county estimate

Calibrates the WECC county net load estimate to the EIA-930 demand of the 28
US WECC balancing authorities (BAs) that report it, allocates the counties to
the WECC 240 load nodes, and checks the result against EIA-930 and, when
given, against the node loads published by `eudoxys/wecc240` (pull request
#2, `wecc240/data/node_ba_load.csv.gz`), which use the same method and
inputs.

Inputs
------

  - county net load $L$: `loads/wecc/wecc_estimate.csv.gz` (gross load)
    minus `loads/wecc/county_dg_scaled.csv.gz` (rooftop PV), clipped at
    zero; counties missing from the DG file have no DG

  - BA participation factors $f$: `loads/wecc/county_ba.csv` (EIA-861 2018)

  - BA demand $D$: `loads/_test/data/WECC_BA_hourly_load_2018-2022.csv`
    (cleaned EIA-930 demand, UTC hour-ending, converted to hour-beginning)

  - county-to-node factors $g$: `loads/wecc/node_estimate_cf.csv`

`county_ba.csv` and the hourly BA demand are added by pull request #62
(branch `review-calibrate-eia930`). When they are not in the package folder,
they are read from that branch at commit `INPUTS_COMMIT`, the commit the
`wecc240` node loads were built from.

Usage
-----

    python3 loads/_validate/validate_calibrate_form930.py [--compare NODE_BA_LOAD] [--factors CSV] [--demand CSV] [--debug]

prints the annual EIA-930, county and node energy and the node peak, runs
the checks below, and writes `form930_county_net.csv.gz` and
`form930_node_net.csv.gz` (MW, hour-beginning UTC) to the `loads/0/_validate`
cache folder. Set `LOADS_CACHEDIR` to use a cache folder other than the
`cache` package default.

Checks
------

  1. In every hour with demand from all BAs, the county total equals the
     EIA-930 total plus the uncalibrated `SWPP` share, and the node total
     equals the county total.
  2. No county or node load is negative.
  3. With `--compare`, the node loads equal the `wecc240` node loads to
     within their rounding (4 decimals).
"""

# pylint: disable=invalid-name
import os
import sys
import argparse
import logging

import numpy as np
import pandas as pd

from cache import Cache
from loads.calibrate import CalibrateForm930

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WECC = os.path.join(PACKAGE,"wecc")
DATA = os.path.join(PACKAGE,"_test","data")

INPUTS_COMMIT = "9341b1342fb64d23db0e169017fee6fa11821e46"
"""`eudoxys/loads` commit (PR #62) holding `county_ba.csv` and the hourly BA demand"""

INPUTS_URL = f"https://raw.githubusercontent.com/eudoxys/loads/{INPUTS_COMMIT}/loads/"
"""URL of the package folder at `INPUTS_COMMIT`"""

HOURS = pd.date_range("2018-01-01 00:00:00+00:00","2022-12-31 23:00:00+00:00",freq="1h",name="timestamp")
"""Validation period (hour-beginning UTC)"""

_logger = logging.getLogger(__file__)

if os.environ.get("LOADS_CACHEDIR"):
    Cache.CACHEDIR = os.environ["LOADS_CACHEDIR"]


def _source(path:str|None,local:str,remote:str) -> str:
    """Pick an explicit path, else the package file, else the pinned URL"""
    if path:
        return path
    return local if os.path.exists(local) else INPUTS_URL + remote


def county_net_load() -> pd.DataFrame:
    """County net load estimate (MW): gross minus rooftop PV, clipped at zero"""
    gross = pd.read_csv(os.path.join(WECC,"wecc_estimate.csv.gz"),index_col=[0],parse_dates=[0])
    dg = pd.read_csv(os.path.join(WECC,"county_dg_scaled.csv.gz"),index_col=[0],parse_dates=[0])
    dg = dg.reindex(index=gross.index,columns=gross.columns).fillna(0.0)
    net = (gross - dg.abs()).clip(lower=0.0)
    net = net.reindex(HOURS)
    if net.isna().any().any():
        raise ValueError("county estimate does not cover the validation period")
    return net


def ba_demand(path:str|None=None) -> pd.DataFrame:
    """Cleaned EIA-930 BA demand (MW), hour-beginning UTC"""
    demand = pd.read_csv(_source(path,os.path.join(DATA,"WECC_BA_hourly_load_2018-2022.csv"),
        "_test/data/WECC_BA_hourly_load_2018-2022.csv"))
    demand.index = pd.DatetimeIndex(pd.to_datetime(demand["utc_hour_ending"],utc=True)
        - pd.Timedelta(hours=1),name="timestamp")
    return demand.drop(["utc_hour_ending","pst_hour_ending"],axis=1).reindex(HOURS)


def inputs(factors:str|None=None,demand:str|None=None) -> tuple:
    """Validation inputs: county net load, BA factors, BA demand and node factors

    Also used by the review notebooks `loads/_review/review_calibrated_*_marimo.py`.
    """
    load = county_net_load()
    factors = pd.read_csv(_source(factors,os.path.join(WECC,"county_ba.csv"),"wecc/county_ba.csv"))
    demand = ba_demand(demand)
    nodes = pd.read_csv(os.path.join(WECC,"node_estimate_cf.csv")).rename({"cf":"factor"},axis=1)
    return load,factors,demand,nodes


def main(argv:list[str]) -> int:
    """Run the validation"""
    parser = argparse.ArgumentParser(description=__doc__.split("\n",1)[0])
    parser.add_argument("--compare",help="wecc240 node_ba_load.csv.gz to compare with")
    parser.add_argument("--factors",help="county_ba.csv (default package file or pinned URL)")
    parser.add_argument("--demand",help="WECC_BA_hourly_load_2018-2022.csv (default package file or pinned URL)")
    parser.add_argument("--debug",action="store_true",help="debug logging")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)

    load,factors,demand,nodes = inputs(args.factors,args.demand)

    county = CalibrateForm930(load,factors,demand)
    node = county.allocate(nodes)
    print(f"counties: {county.shape[1]}, unassigned: {county.unassigned}, "
        f"BAs: {len(county.factors.columns)}, uncalibrated: {county.uncalibrated}, nodes: {node.shape[1]}")

    # check 1: totals
    complete = county.demand.notna().all(axis=1)
    uncalibrated = (county.estimate[county.uncalibrated].sum(axis=1)
        + load[county.unassigned].sum(axis=1))
    expected = county.demand.sum(axis=1) + uncalibrated
    error = (county.sum(axis=1) - expected)[complete].abs().max()
    node_error = (node.sum(axis=1) - county.sum(axis=1))[complete].abs().max()
    print(f"hours with all BA demand: {complete.sum()} of {len(complete)}")
    print(f"max |county total - (EIA-930 + uncalibrated)|: {error:.3g} MW")
    print(f"max |node total - county total|: {node_error:.3g} MW")
    print(f"uncalibrated share: {uncalibrated.groupby(uncalibrated.index.year).sum().mean()/1e6:.2f} TWh/y")

    # check 2: nonnegative
    print(f"min county load: {np.nanmin(county.values):.4g} MW, min node load: {np.nanmin(node.values):.4g} MW")

    # annual table
    years = county.index.year
    table = pd.DataFrame({
        "EIA-930 TWh": county.demand.sum(axis=1).groupby(years).sum()/1e6,
        "County TWh": county.sum(axis=1).groupby(years).sum()/1e6,
        "Node TWh": node.sum(axis=1).groupby(years).sum()/1e6,
        "Node peak MW": node.sum(axis=1,min_count=1).groupby(years).max(),
        })
    print(table.round(1).to_string())

    # check 3: compare with wecc240
    if args.compare:
        other = pd.read_csv(args.compare,index_col=[0],parse_dates=[0]).reindex(HOURS)
        common = [x for x in node.columns if x in other.columns]
        print(f"nodes: {len(common)} common, {len(set(node.columns)^set(other.columns))} not common")
        diff = (node[common] - other[common]).abs()
        print(f"max |node - wecc240 node|: {np.nanmax(diff.values):.3g} MW; "
            f"NaN pattern equal: {node[common].isna().equals(other[common].isna())}")

    folder = Cache(package="loads",version=0,path=["_validate","form930_county_net.csv.gz"]).pathname
    pd.DataFrame(county).round(4).to_csv(folder,index=True,header=True,compression="gzip")
    folder = Cache(package="loads",version=0,path=["_validate","form930_node_net.csv.gz"]).pathname
    node.round(4).to_csv(folder,index=True,header=True,compression="gzip")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
