r"""Validate `CalibrateForm930` on the WECC 2018-2022 county estimate

Calibrates the WECC county net load estimate to the EIA-930 demand of the 28
US WECC balancing authorities (BAs) that report it, allocates the counties to
the WECC 240 load nodes, and checks the result against EIA-930 and, when
given, against the node loads published by `eudoxys/wecc240` (pull request
#2, `wecc240/data/node_ba_load.csv.gz`), which use the same method and
inputs.

Inputs
------

  - county gross load $G$: `loads/wecc/wecc_estimate.csv.gz`

  - county rooftop PV $P$: `loads/wecc/county_dg_scaled.csv.gz` (fixed, not
    calibrated); counties missing from the DG file have no DG. The
    calibrated net load $X=G'-P$ may be negative where the PV exceeds the
    calibrated gross load $G'$.

  - with `--clip`, instead the net load $\max(G-P,0)$ and no DG, which is
    the input of the `wecc240` node loads

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

    python3 loads/_validate/validate_calibrate_form930.py [--clip] [--compare NODE_BA_LOAD] [--factors CSV] [--demand CSV] [--debug]

prints the annual EIA-930, county and node energy and the node peak, runs
the checks below, and writes `form930_county_net.csv.gz` and
`form930_node_net.csv.gz` (MW, hour-beginning UTC; `_clip` suffix with `--clip`) to the `loads/0/_validate`
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
  4. **Nonnegative gross.** No calibrated county gross load is negative
     (the number of negative net county and node hours is reported).
  5. **wecc240.** With `--compare` and `--clip`, the node loads equal the
     `wecc240` node loads to within their rounding (`COMPARE_TOL_MW`), with
     the same `NaN` hours. Without `--clip` the differences are reported
     (`INFO`), since `wecc240` clips the net load at zero.
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


def county_load() -> tuple[pd.DataFrame,pd.DataFrame]:
    """County gross load estimate and rooftop PV (MW, nonnegative)"""
    gross = pd.read_csv(os.path.join(WECC,"wecc_estimate.csv.gz"),index_col=[0],parse_dates=[0])
    dg = pd.read_csv(os.path.join(WECC,"county_dg_scaled.csv.gz"),index_col=[0],parse_dates=[0])
    dg = dg.reindex(index=gross.index,columns=gross.columns).fillna(0.0).abs()
    gross,dg = gross.reindex(HOURS),dg.reindex(HOURS)
    if gross.isna().any().any() or dg.isna().any().any():
        raise ValueError("county estimate does not cover the validation period")
    return gross,dg


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


def inputs(factors:str|None=None,demand:str|None=None,clip:bool=False) -> tuple:
    """Validation inputs: county load, DG, BA factors, BA demand and node factors

    Returns the county gross load and rooftop PV, or, with `clip`, the net
    load clipped at zero and `None` (the `wecc240` input). Also used by the
    review notebooks `loads/_review/review_calibrated_*_marimo.py`.
    """
    load,dg = county_load()
    if clip:
        load,dg = (load - dg).clip(lower=0.0),None
    factors = pd.read_csv(_source(factors,os.path.join(WECC,"county_ba.csv"),"wecc/county_ba.csv"))
    demand = ba_demand(demand)
    nodes = pd.read_csv(os.path.join(WECC,"node_estimate_cf.csv")).rename({"cf":"factor"},axis=1)
    return load,dg,factors,demand,nodes


def ba_shares(load:pd.DataFrame,factors:pd.DataFrame,demand:pd.DataFrame,
        dg:pd.DataFrame|None=None) -> tuple:
    """Recompute each county's net share of each BA from the inputs, BA by BA

    Arguments
    ---------

      - `load`: county gross load (hours x counties), or net load without `dg`
      - `factors`: wide BA factors (counties x BAs), rows summing to one
      - `demand`: BA demand (hours x BAs), `NaN` when missing
      - `dg`: county DG (MW, nonnegative; default none)

    Returns
    -------

      - `pandas.DataFrame`: county net load as the sum of its net BA shares
        (`NaN` in hours when any of its BAs with demand has none)
      - `pandas.Series`: largest |sum of county net shares − demand| (MW) of
        each BA with demand, over hours with demand
    """
    # pylint: disable=too-many-locals
    counties = [x for x in load.columns if x in factors.index]
    G = load[counties].values
    P = np.zeros(G.shape) if dg is None else dg.reindex(columns=counties).fillna(0.0).values
    total = np.zeros(G.shape)
    missing = np.zeros(G.shape,dtype=bool)
    errors = {}
    for ba in factors.columns:
        f = factors.loc[counties,ba].values
        if not (f > 0).any():
            continue
        estimate = G * f[None,:]                    # county gross share of the BA
        solar = P * f[None,:]                       # county DG share of the BA
        if ba not in demand.columns:
            total += estimate - solar               # uncalibrated BA keeps the estimate
            continue
        D = demand[ba].reindex(load.index).values
        T = D + solar.sum(axis=1)                   # BA gross demand
        S = estimate.sum(axis=1)
        with np.errstate(divide="ignore",invalid="ignore"):
            share = np.where((S > 0)[:,None],estimate*(T/S)[:,None],T[:,None]*f[None,:]/f.sum()) - solar
        ok = ~np.isnan(D)
        errors[ba] = float(np.abs(share[ok].sum(axis=1) - D[ok]).max()) if ok.any() else 0.0
        missing |= ~ok[:,None] & (f > 0)[None,:]
        total += np.nan_to_num(share)
    total[missing] = np.nan
    return pd.DataFrame(total,index=load.index,columns=counties),pd.Series(errors,dtype=float)


def checks(load:pd.DataFrame,factors:pd.DataFrame,demand:pd.DataFrame,
        county:CalibrateForm930,node:pd.DataFrame,wecc:pd.Series,
        compare:pd.DataFrame|None=None,dg:pd.DataFrame|None=None) -> list[tuple[str,bool|None,str]]:
    """Run the validation checks

    Returns
    -------

      - `list`: `(name,passed,detail)` for each check (see the module
        docstring); `passed` is `None` for an informational result (the
        `wecc240` comparison with `dg`)
    """
    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    results = []
    complete = county.demand.notna().all(axis=1)
    calibrated = pd.DataFrame(county)

    # 1. BA shares
    shares,errors = ba_shares(load,county.factors,demand,dg)
    columns = list(shares.columns)
    same_nan = shares.isna().equals(calibrated[columns].isna())
    diff = float(np.nanmax(np.abs(shares.values - calibrated[columns].values)))
    worst = errors.idxmax() if len(errors) else "none"
    results.append(("1. BA shares",
        bool(errors.max() <= TOL_MW and diff <= TOL_MW and same_nan),
        f"{len(errors)} BAs: max |sum of county shares - demand| {errors.max():.3g} MW ({worst});"
        f" max |sum of BA shares - county load| {diff:.3g} MW; same NaN hours {same_nan}"))

    # 2. WECC total
    net = load if dg is None else load - dg.reindex(index=load.index,columns=load.columns).fillna(0.0)
    uncalibrated = (county.estimate[county.uncalibrated].sum(axis=1)
        + net.loc[county.index,county.unassigned].sum(axis=1))
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

    # 4. nonnegative gross load
    low = float(np.nanmin(county.gross.values))
    results.append(("4. Nonnegative gross",low >= 0,
        f"min county gross load {low:.4g} MW; negative net load:"
        f" {int((calibrated < 0).sum().sum())} county-hours in {int((calibrated < 0).any().sum())} counties,"
        f" {int((node < 0).sum().sum())} node-hours in {int((node < 0).any().sum())} nodes;"
        f" min net county {float(np.nanmin(calibrated.values)):.4g} MW, node {float(np.nanmin(node.values)):.4g} MW"))

    # 5. wecc240
    if compare is not None:
        common = [x for x in node.columns if x in compare.columns]
        other = compare.reindex(node.index)[common]
        delta = float(np.nanmax(np.abs(node[common].values - other.values)))
        same = node[common].isna().equals(other.isna())
        unmatched = sorted(set(node.columns) ^ set(compare.columns))
        passed = bool(delta <= COMPARE_TOL_MW and same and not unmatched) if dg is None else None
        results.append(("5. wecc240",passed,
            f"{len(common)} common nodes, unmatched {unmatched or 'none'};"
            f" max |node - wecc240 node| {delta:.3g} MW; same NaN hours {same}"))
    return results


def main(argv:list[str]) -> int:
    """Run the validation"""
    parser = argparse.ArgumentParser(description=__doc__.split("\n",1)[0])
    parser.add_argument("--clip",action="store_true",
        help="calibrate the net load clipped at zero without DG (the wecc240 method)")
    parser.add_argument("--compare",help="wecc240 node_ba_load.csv.gz to compare with")
    parser.add_argument("--factors",help="county_ba.csv (default package file or pinned URL)")
    parser.add_argument("--demand",help="WECC_BA_hourly_load_2018-2022.csv (default package file or pinned URL)")
    parser.add_argument("--debug",action="store_true",help="debug logging")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)

    load,dg,factors,demand,nodes = inputs(args.factors,args.demand,args.clip)
    county = CalibrateForm930(load,factors,demand,dg=dg)
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
    results = checks(load,factors,demand,county,node,wecc_total(),compare,dg)
    for name,passed,detail in results:
        print(f"{ {True:'PASS',False:'FAIL',None:'INFO'}[passed]} {name}: {detail}")

    suffix = "_clip" if args.clip else ""
    folder = Cache(package="loads",version=0,path=["_validate",f"form930_county_net{suffix}.csv.gz"]).pathname
    pd.DataFrame(county).round(4).to_csv(folder,index=True,header=True,compression="gzip")
    folder = Cache(package="loads",version=0,path=["_validate",f"form930_node_net{suffix}.csv.gz"]).pathname
    node.round(4).to_csv(folder,index=True,header=True,compression="gzip")
    return 0 if all(x[1] is not False for x in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
