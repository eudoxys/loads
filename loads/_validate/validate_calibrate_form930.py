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

Each check prints `PASS` or `FAIL`; the script exits with status 1 if any
check fails. Hours without demand from every BA (the first 8 hours of 2018)
are excluded from the totals.

  1. **BA shares.** The fractional share $f_{ub}L_u(t)D_b(t)/S_b(t)$ of
     each county in each BA is recomputed from the inputs, BA by BA,
     independently of `CalibrateForm930`: in every hour with demand the
     county shares of each BA sum to its EIA-930 demand, and the sum of each
     county's BA shares equals the `CalibrateForm930` county load (same
     `NaN` hours). Tolerance `TOL_MW`.
  2. **WECC total.** The county total minus the uncalibrated `SWPP` share
     equals the EIA-930 US WECC total `WECC_load_MW` in
     `loads/_test/data/WECC_CAISO_hourly_load_2018-2022.csv` (on `main`,
     independent of the PR #62 inputs) to within `WECC_TOL_MW`, which
     allows for the rounding of the per-BA series.
  3. **US only.** Every county is in a US state (`fips.States`), no county
     is served by a Canadian or Mexican BA (`FOREIGN_BAS`), and the node
     total equals the county total, so the nodes carry no Canadian or
     Mexican load (node `c2u6xt` is in Canada but receives only nearby US
     county load).
  4. **Nonnegative.** No county or node load is negative.
  5. **wecc240.** With `--compare`, the node loads equal the `wecc240` node
     loads to within their rounding (`COMPARE_TOL_MW`), with the same `NaN`
     hours.
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

TOL_MW = 1.0e-6
"""Tolerance of the internal consistency checks (MW)"""

WECC_TOL_MW = 5.0
"""Tolerance of the WECC total check (MW); the per-BA series are integers and
their sum differs from `WECC_load_MW` by at most 2 MW"""

COMPARE_TOL_MW = 0.01
"""Tolerance of the comparison with the `wecc240` node loads (MW)"""

FOREIGN_BAS = ("AESO","BCHA","CFE")
"""Canadian and Mexican WECC BAs (no EIA-930 demand)"""

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


def wecc_total() -> pd.Series:
    """EIA-930 US WECC total demand `WECC_load_MW` (MW), hour-beginning UTC"""
    data = pd.read_csv(os.path.join(DATA,"WECC_CAISO_hourly_load_2018-2022.csv"))
    data.index = pd.DatetimeIndex(pd.to_datetime(data["utc_hour_ending"],utc=True)
        - pd.Timedelta(hours=1),name="timestamp")
    return data["WECC_load_MW"].reindex(HOURS)


def inputs(factors:str|None=None,demand:str|None=None) -> tuple:
    """Validation inputs: county net load, BA factors, BA demand and node factors

    Also used by the review notebooks `loads/_review/review_calibrated_*_marimo.py`.
    """
    load = county_net_load()
    factors = pd.read_csv(_source(factors,os.path.join(WECC,"county_ba.csv"),"wecc/county_ba.csv"))
    demand = ba_demand(demand)
    nodes = pd.read_csv(os.path.join(WECC,"node_estimate_cf.csv")).rename({"cf":"factor"},axis=1)
    return load,factors,demand,nodes


def ba_shares(load:pd.DataFrame,factors:pd.DataFrame,demand:pd.DataFrame) -> tuple:
    """Recompute each county's share of each BA from the inputs, BA by BA

    Arguments
    ---------

      - `load`: county load (hours x counties)
      - `factors`: wide BA factors (counties x BAs), rows summing to one
      - `demand`: BA demand (hours x BAs), `NaN` when missing

    Returns
    -------

      - `pandas.DataFrame`: county load as the sum of its BA shares (`NaN` in
        hours when any of its BAs with demand has none)
      - `pandas.Series`: largest |sum of county shares − demand| (MW) of each
        BA with demand, over hours with demand
    """
    counties = [x for x in load.columns if x in factors.index]
    L = load[counties].values
    total = np.zeros(L.shape)
    missing = np.zeros(L.shape,dtype=bool)
    errors = {}
    for ba in factors.columns:
        f = factors.loc[counties,ba].values
        if not (f > 0).any():
            continue
        estimate = L * f[None,:]                    # county estimate share of the BA
        if ba not in demand.columns:
            total += estimate                       # uncalibrated BA keeps the estimate
            continue
        D = demand[ba].reindex(load.index).values
        S = estimate.sum(axis=1)
        with np.errstate(divide="ignore",invalid="ignore"):
            share = np.where((S > 0)[:,None],estimate*(D/S)[:,None],D[:,None]*f[None,:]/f.sum())
        ok = ~np.isnan(D)
        errors[ba] = float(np.abs(share[ok].sum(axis=1) - D[ok]).max()) if ok.any() else 0.0
        missing |= ~ok[:,None] & (f > 0)[None,:]
        total += np.nan_to_num(share)
    total[missing] = np.nan
    return pd.DataFrame(total,index=load.index,columns=counties),pd.Series(errors,dtype=float)


def checks(load:pd.DataFrame,factors:pd.DataFrame,demand:pd.DataFrame,
        county:CalibrateForm930,node:pd.DataFrame,wecc:pd.Series,
        compare:pd.DataFrame|None=None) -> list[tuple[str,bool,str]]:
    """Run the validation checks

    Returns
    -------

      - `list`: `(name,passed,detail)` for each check (see the module docstring)
    """
    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    results = []
    complete = county.demand.notna().all(axis=1)
    calibrated = pd.DataFrame(county)

    # 1. BA shares
    shares,errors = ba_shares(load,county.factors,demand)
    columns = list(shares.columns)
    same_nan = shares.isna().equals(calibrated[columns].isna())
    diff = float(np.nanmax(np.abs(shares.values - calibrated[columns].values)))
    worst = errors.idxmax() if len(errors) else "none"
    results.append(("1. BA shares",
        bool(errors.max() <= TOL_MW and diff <= TOL_MW and same_nan),
        f"{len(errors)} BAs: max |sum of county shares - demand| {errors.max():.3g} MW ({worst});"
        f" max |sum of BA shares - county load| {diff:.3g} MW; same NaN hours {same_nan}"))

    # 2. WECC total
    uncalibrated = (county.estimate[county.uncalibrated].sum(axis=1)
        + load.loc[county.index,county.unassigned].sum(axis=1))
    ok = complete & wecc.reindex(county.index).notna()
    gap = (calibrated.sum(axis=1) - uncalibrated - wecc.reindex(county.index))[ok]
    results.append(("2. WECC total",bool(ok.any() and gap.abs().max() <= WECC_TOL_MW),
        f"{int(ok.sum())} hours: county total - uncalibrated share ({', '.join(county.uncalibrated) or 'none'},"
        f" {uncalibrated[ok].sum()/1e6/max(1,ok.sum()/8766):.2f} TWh/y) - WECC_load_MW:"
        f" max |.| {gap.abs().max():.3g} MW, mean {gap.mean():.3g} MW"))

    # 3. US only
    from fips import States # pylint: disable=import-outside-toplevel
    states = set(States()["ST"])
    foreign_counties = [x for x in calibrated.columns if x.rsplit(" ",1)[-1] not in states]
    foreign_bas = sorted(set(county.factors.columns) & set(FOREIGN_BAS))
    node_gap = float((node.sum(axis=1) - calibrated.sum(axis=1))[complete].abs().max())
    results.append(("3. US only",not foreign_counties and not foreign_bas and node_gap <= TOL_MW,
        f"non-US counties {foreign_counties or 'none'}; Canadian/Mexican BAs {foreign_bas or 'none'};"
        f" max |node total - county total| {node_gap:.3g} MW"))

    # 4. nonnegative
    low = min(float(np.nanmin(calibrated.values)),float(np.nanmin(node.values)))
    results.append(("4. Nonnegative",low >= 0,f"min county/node load {low:.4g} MW"))

    # 5. wecc240
    if compare is not None:
        common = [x for x in node.columns if x in compare.columns]
        other = compare.reindex(node.index)[common]
        delta = float(np.nanmax(np.abs(node[common].values - other.values)))
        same = node[common].isna().equals(other.isna())
        unmatched = sorted(set(node.columns) ^ set(compare.columns))
        results.append(("5. wecc240",bool(delta <= COMPARE_TOL_MW and same and not unmatched),
            f"{len(common)} common nodes, unmatched {unmatched or 'none'};"
            f" max |node - wecc240 node| {delta:.3g} MW; same NaN hours {same}"))
    return results


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
    print(f"hours with all BA demand: {int(county.demand.notna().all(axis=1).sum())} of {len(county)}")

    years = county.index.year
    table = pd.DataFrame({
        "EIA-930 TWh": county.demand.sum(axis=1).groupby(years).sum()/1e6,
        "County TWh": county.sum(axis=1).groupby(years).sum()/1e6,
        "Node TWh": node.sum(axis=1).groupby(years).sum()/1e6,
        "Node peak MW": node.sum(axis=1,min_count=1).groupby(years).max(),
        })
    print(table.round(1).to_string())

    compare = pd.read_csv(args.compare,index_col=[0],parse_dates=[0]) if args.compare else None
    results = checks(load,factors,demand,county,node,wecc_total(),compare)
    for name,passed,detail in results:
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")

    folder = Cache(package="loads",version=0,path=["_validate","form930_county_net.csv.gz"]).pathname
    pd.DataFrame(county).round(4).to_csv(folder,index=True,header=True,compression="gzip")
    folder = Cache(package="loads",version=0,path=["_validate","form930_node_net.csv.gz"]).pathname
    node.round(4).to_csv(folder,index=True,header=True,compression="gzip")
    return 0 if all(x[1] for x in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
