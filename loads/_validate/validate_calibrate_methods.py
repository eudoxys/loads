r"""Compare the four calibration methods on the WECC county and node panels

Calibrates the 2018-2022 WECC county load estimate, and the WECC240 node
load allocated from it, with each method `loads.calibrate.CalibrateConfig`
can choose, using `loads.calibrate.CalibrateTotal` with the unscaled
rooftop PV held fixed, and compares every result with the uncalibrated
estimate and with the published energy and peak targets.

Panels
------

  - counties: the gross load estimate $X$ of the 407 WECC counties
    (`loads/wecc/wecc_estimate.csv.gz`) and their rooftop PV $D$
    (`loads/wecc/county_dg.csv.gz`, unscaled, as in the other calibration
    validations)

  - nodes: $X$ and $D$ allocated to the 113 WECC240 load nodes that receive
    US county load with the factors $g$ of `loads/wecc/node_estimate_cf.csv`

Methods and their data
----------------------

| Method | Data | Matched |
| ------ | ---- | ------- |
| `CalibrateEnergy` | EIA-861M retail sales by county and month (`wecc/county_mwh.csv`; nodes: allocated with $g$) | each unit's monthly net energy |
| `CalibrateEnergyPeak` | state monthly net energy (`_test/data/energy_target.csv`), CAISO and WECC monthly net peaks (`_test/data/peak_target.csv`), CAISO membership (`_test/data/state_groups.csv`) | the state energies (soft) and regional peaks (ceilings) |
| `CalibratePeaks` | monthly maximum and minimum of each US WECC BA's EIA-930 demand (`_test/data/ba_minmax_target.csv`), BA factors (`wecc/county_ba.csv`) | each BA's monthly peak and trough, calibrating the BA's share of the units |
| `CalibrateHourly` | hourly EIA-930 demand of each US WECC BA (`_test/data/WECC_BA_hourly_load_2018-2022.csv`), BA factors | every hour of each BA's demand |

Node memberships (state, CAISO, BA) are the county memberships weighted by
each county's 2018-2022 net energy allocated to the node. `CalibrateEnergyPeak`
uses `GRID`, a reduced weight search (8 candidates per month rather than
88), with the predeclared selection rule. `CalibrateHourly` keeps the
estimate in hours without demand (`missing="keep"`, the first 8 hours of
2018) and for BAs without demand (`SWPP`).

Statistics
----------

For each panel, every method and the uncalibrated estimate are compared
with:

  - the estimate: the hourly gross load of every unit (MAPE over the unit
    hours with positive estimate);

  - the energy targets: the monthly net energy of each state (60 months x
    13 states), the sum of the county net loads (nodes: allocated to states
    with the node memberships);

  - the peak targets: the monthly peak of the CAISO and WECC net load (60
    months x 2 regions), with CAISO membership as in `state_groups.csv`.

MAPE (%), MAE, RMSE and $R^2=1-\sum(y-\hat y)^2/\sum(y-\bar y)^2$ are
computed over the pooled observations, where $y$ is the reference.

Usage
-----

    python3 loads/_validate/validate_calibrate_methods.py [--output FOLDER] [--debug]

It takes about an hour, mostly `CalibrateEnergyPeak` on the counties.
The calibrated panels and the tables are saved in `FOLDER` (default the
gitignored `loads/tests/calibrate_methods`).
"""

import argparse
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

from loads.calibrate import CalibrateTotal, CalibrateConfig

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WECC = os.path.join(PACKAGE,"wecc")
DATA = os.path.join(PACKAGE,"_test","data")

HOURS = pd.date_range("2018-01-01 00:00:00+00:00","2022-12-31 23:00:00+00:00",freq="1h",name="timestamp")
"""Comparison period (hour-beginning UTC)"""

GRID = [(mu,{"CAISO":scale*caiso,"WECC":scale*wecc})
    for mu in (1.0e3,1.0e4) for scale in (1.0,3.0) for caiso,wecc in ((1.0,1.0),(1.0,3.0))]
"""Reduced `CalibrateEnergyPeak` weight search: energy weights x drive scales x CAISO:WECC ratios"""

METHODS = ["CalibrateEnergy","CalibrateEnergyPeak","CalibratePeaks","CalibrateHourly"]
"""Methods in table order"""

FITTED = {
    "CalibrateEnergy":"unit energy",
    "CalibrateEnergyPeak":"state energy, regional peaks",
    "CalibratePeaks":"BA monthly max/min",
    "CalibrateHourly":"BA hourly demand",
    }
"""Data each method is fitted to"""

_logger = logging.getLogger(__file__)


def _utc_hour_beginning(frame:pd.DataFrame) -> pd.DataFrame:
    """@private Index an EIA-930 file by UTC hour beginning"""
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame["utc_hour_ending"],utc=True)
        - pd.Timedelta(hours=1),name="timestamp")
    return frame.drop(["utc_hour_ending","pst_hour_ending"],axis=1).reindex(HOURS)


def _month_start(index) -> pd.DatetimeIndex:
    """@private Parse month labels as UTC month starts"""
    return pd.DatetimeIndex(pd.to_datetime(index,format="mixed")).tz_localize(None).tz_localize("UTC")


def inputs() -> dict:
    """Load the panels, targets and memberships"""
    gross = pd.read_csv(os.path.join(WECC,"wecc_estimate.csv.gz"),index_col=[0],parse_dates=[0]).reindex(HOURS)
    if gross.isna().any().any():
        raise ValueError("county estimate does not cover the comparison period")
    dg = pd.read_csv(os.path.join(WECC,"county_dg.csv.gz"),index_col=[0],parse_dates=[0])
    dg = dg.reindex(index=HOURS,columns=gross.columns).fillna(0.0).abs()
    counties = list(gross.columns)
    weight = (gross - dg).sum()

    # county -> node factors
    cf = pd.read_csv(os.path.join(WECC,"node_estimate_cf.csv"))
    nodes = cf.pivot_table(index="county_st",columns="node",values="cf",aggfunc="sum",fill_value=0.0)
    nodes = nodes.reindex(index=counties,fill_value=0.0)
    nodes = nodes.loc[:,nodes.sum() > 0]

    def node_shares(county_frame):
        """Net-energy-weighted county memberships of each node"""
        mixed = nodes.mul(weight,axis=0)
        result = mixed.T @ county_frame.reindex(counties).fillna(0.0)
        return result.div(mixed.sum(),axis=0)

    # memberships
    state = pd.get_dummies(pd.Series([c.rsplit(" ",1)[1] for c in counties],index=counties)).astype(float)
    groups = pd.read_csv(os.path.join(DATA,"state_groups.csv"),index_col=0).reindex(counties)
    bas = pd.read_csv(os.path.join(WECC,"county_ba.csv")).pivot_table(index="county_st",columns="ba",
        values="factor",aggfunc="sum",fill_value=0.0).reindex(counties).fillna(0.0)

    # targets
    mwh = pd.read_csv(os.path.join(WECC,"county_mwh.csv"),index_col=0)
    mwh.index = _month_start(mwh.index)
    mwh = mwh.loc["2018":"2022",counties]
    energy = pd.read_csv(os.path.join(DATA,"energy_target.csv"),index_col=0,parse_dates=[0])
    peak = pd.read_csv(os.path.join(DATA,"peak_target.csv"),index_col=0,parse_dates=[0])
    minmax = pd.read_csv(os.path.join(DATA,"ba_minmax_target.csv"),parse_dates=["timestamp"])
    minmax = {ba:frame.set_index("timestamp")[["max","min"]] for ba,frame in minmax.groupby("ba")}
    demand = _utc_hour_beginning(pd.read_csv(os.path.join(DATA,"WECC_BA_hourly_load_2018-2022.csv")))

    return {
        "county": {
            "gross":gross,"dg":dg,"energy_units":mwh,"states":state,"caiso":groups["CAISO"],"bas":bas,
            },
        "node": {
            "gross":gross @ nodes,"dg":dg @ nodes,"energy_units":mwh @ nodes,
            "states":node_shares(state),"caiso":node_shares(groups[["CAISO"]])["CAISO"],"bas":node_shares(bas),
            },
        "energy":energy,"peak":peak,"minmax":minmax,"demand":demand,
        }


def calibrate(panel:dict,data:dict,method:str,progress=None) -> pd.DataFrame:
    """Calibrated gross load of a panel with one method"""
    X,D = panel["gross"],panel["dg"]
    if method == "CalibrateEnergy":
        return pd.DataFrame(CalibrateTotal(X,CalibrateConfig(energy=panel["energy_units"],dg=D)))
    if method == "CalibrateEnergyPeak":
        regions = pd.DataFrame({"CAISO":panel["caiso"],"WECC":1.0})
        options = {"regions":regions,"search":GRID,"progress":progress}
        if not all(" " in x for x in X.columns):
            options["states"] = panel["states"]
        config = CalibrateConfig(energy=data["energy"],peak=data["peak"],dg=D,**options)
        return pd.DataFrame(CalibrateTotal(X,config))
    if method == "CalibratePeaks":
        result = X.copy()
        for ba,peaks in data["minmax"].items():
            if ba not in panel["bas"].columns:
                continue
            factor = panel["bas"][ba]
            units = factor.index[factor > 0]
            share = X[units].mul(factor[units],axis=1)
            dg = D[units].mul(factor[units],axis=1)
            calibrated = CalibrateTotal(share,CalibrateConfig(peaks=peaks,dg=dg))
            result[units] += calibrated - share
        return result
    if method == "CalibrateHourly":
        config = CalibrateConfig(demand=data["demand"],factors=panel["bas"],dg=D,missing="keep")
        return pd.DataFrame(CalibrateTotal(X,config))
    raise ValueError(f"unknown method {method}")


def statistics(reference:np.ndarray,value:np.ndarray) -> dict:
    """MAPE (%), MAE, RMSE and R² of `value` against `reference` (pooled)"""
    reference = np.asarray(reference,dtype=float).ravel()
    value = np.asarray(value,dtype=float).ravel()
    keep = np.isfinite(reference) & np.isfinite(value)
    reference,value = reference[keep],value[keep]
    error = value - reference
    positive = reference > 0
    return {
        "MAPE": 100*float(np.mean(np.abs(error[positive])/reference[positive])),
        "MAE": float(np.mean(np.abs(error))),
        "RMSE": float(np.sqrt(np.mean(error**2))),
        "R2": float(1 - np.sum(error**2)/np.sum((reference - reference.mean())**2)),
        }


def compare(panel:dict,data:dict,load:pd.DataFrame) -> dict:
    """Statistics of a calibrated gross load against the estimate and the targets"""
    net = load - panel["dg"]
    months = net.index.tz_localize(None).to_period("M").to_timestamp().tz_localize("UTC")
    state = (net @ panel["states"]).groupby(months).sum()
    energy = data["energy"].reindex(index=state.index,columns=state.columns)
    regions = pd.DataFrame({"CAISO":net @ panel["caiso"],"WECC":net.sum(axis=1)}).groupby(months).max()
    peak = data["peak"].reindex(index=regions.index,columns=regions.columns)
    return {
        "estimate": statistics(panel["gross"].values,load.values),
        "energy": statistics(energy.values,state.values),
        "peak": statistics(peak.values,regions.values),
        }


def table(results:dict) -> pd.DataFrame:
    """Rows are methods, columns are statistics by reference"""
    rows = {}
    for method,stats in results.items():
        rows[method] = {
            "Fitted to": FITTED.get(method,"—"),
            "Estimate MAPE (%)": stats["estimate"]["MAPE"],
            "Estimate MAE (MW)": stats["estimate"]["MAE"],
            "Estimate RMSE (MW)": stats["estimate"]["RMSE"],
            "Estimate R²": stats["estimate"]["R2"],
            "Energy MAPE (%)": stats["energy"]["MAPE"],
            "Energy MAE (GWh)": stats["energy"]["MAE"]/1e3,
            "Energy RMSE (GWh)": stats["energy"]["RMSE"]/1e3,
            "Energy R²": stats["energy"]["R2"],
            "Peak MAPE (%)": stats["peak"]["MAPE"],
            "Peak MAE (MW)": stats["peak"]["MAE"],
            "Peak RMSE (MW)": stats["peak"]["RMSE"],
            "Peak R²": stats["peak"]["R2"],
            }
    return pd.DataFrame(rows).T


def main(argv:list[str]) -> int:
    """Run the comparison"""
    parser = argparse.ArgumentParser(description=__doc__.split("\n",1)[0])
    parser.add_argument("--output",default=os.path.join(PACKAGE,"tests","calibrate_methods"),
        help="folder for the calibrated panels and tables")
    parser.add_argument("--panels",default="county,node",help="panels to run (county,node)")
    parser.add_argument("--debug",action="store_true",help="debug logging")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    os.makedirs(args.output,exist_ok=True)

    data = inputs()
    for name in args.panels.split(","):
        panel = data[name]
        print(f"{name}: {panel['gross'].shape[1]} units, {len(HOURS)} hours",flush=True)
        results = {"Estimate (uncalibrated)":compare(panel,data,panel["gross"])}
        for method in METHODS:
            start = time.time()
            def progress(done,total,info,method=method):
                if info["step"] == "final":
                    print(f"  {method} {info['block']:%Y-%m} {done}/{total} {info['status']}",flush=True)
            load = calibrate(panel,data,method,progress)
            load.to_csv(os.path.join(args.output,f"{name}_{method}.csv.gz"))
            results[method] = compare(panel,data,load)
            print(f"  {method}: {time.time()-start:.0f} s",flush=True)
        result = table(results)
        result.to_csv(os.path.join(args.output,f"{name}_statistics.csv"))
        with pd.option_context("display.width",250,"display.max_columns",20,"display.float_format","{:,.3f}".format):
            print(result,flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
