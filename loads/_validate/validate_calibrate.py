"""Calibrated 2020 load inputs for the CAISO validation notebook

Builds and caches the inputs used by `validate_calibrate_marimo.py`:

  - the 2020 gross load matrix $X$: `Total(...,samples=0)` TSGAM predictions
    of `elec_total_MW` for every WECC county, driven by 2020 weather (the
    same construction as `loads/_test/test_calibrate.py`, for the whole
    year instead of August);

  - the calibrated load $L$: `Calibrate(...,search=True)` month by month,
    with the default settings of `loads/_explore/explore_calibrate_marimo.py`
    (DG from `loads/wecc/county_dg_scaled.csv.gz`, the monthly state energy and
    CAISO/WECC peak targets and the CAISO/WECC membership in
    `loads/_test/data`, and the predeclared 88-point weight grid and
    selection rule);

  - the CAISO reported hourly load from `loads/caiso/{year}.csv`.

Usage
-----

    python3 loads/_validate/validate_calibrate.py [--refresh] [--debug]

builds the load matrix and runs the calibration, so the notebook only reads
the cache. The load matrix is cached as
`loads/0/_validate/calibrate_X_2020.csv.gz` and the calibration as
`loads/0/_validate/calibrate_L_2020.csv.gz` (plus `calibrate_summary_2020.csv`,
`calibrate_regions_2020.csv` and `calibrate_states_2020.csv`). The load
matrix runs 407 county predictions in parallel (`LOADS_TEST_WORKERS`
processes, default all cores) and the calibration solves 89 programs for
each of the 12 months. Set `LOADS_CACHEDIR` to use a cache folder other than
the `cache` package default.
"""

# pylint: disable=invalid-name
import os
import sys
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable

import numpy as np
import pandas as pd

from cache import Cache
from fips import Counties

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PACKAGE,"_test","data")
CAISO = os.path.join(PACKAGE,"caiso")
DG_FILE = os.path.join(PACKAGE,"wecc","county_dg_scaled.csv.gz")
YEAR = 2020
LAGS = 3 # Total trims this many hours from each end of a prediction
REGIONS = ["CAISO","WECC"]

_logger = logging.getLogger(__file__)

if os.environ.get("LOADS_CACHEDIR"):
    Cache.CACHEDIR = os.environ["LOADS_CACHEDIR"]


def hours(year:int=YEAR) -> pd.DatetimeIndex:
    """Hourly UTC index of a calendar year"""
    return pd.date_range(f"{year}-01-01 00:00:00+00:00",f"{year}-12-31 23:00:00+00:00",
        freq="1h",name="timestamp")


def wecc_units() -> list[tuple[str,str]]:
    """WECC (state,county) pairs, sorted by "County ST" name"""
    counties = Counties(use_index=["SYSTEM"]).loc["WECC"]
    return sorted(zip(counties.ST,counties.COUNTY),key=lambda x:f"{x[1]} {x[0]}")


def _cache(name:str,year:int=YEAR) -> Cache:
    """@private Validation cache file"""
    return Cache(package="loads",version=0,path=["_validate",name.format(year=year)])


def load_cache(year:int=YEAR) -> Cache:
    """Cache file holding the gross county load matrix"""
    return _cache("calibrate_X_{year}.csv.gz",year)


def result_caches(year:int=YEAR) -> dict[str,Cache]:
    """Cache files holding the calibration results"""
    return {
        "load": _cache("calibrate_L_{year}.csv.gz",year),
        "summary": _cache("calibrate_summary_{year}.csv",year),
        "regions": _cache("calibrate_regions_{year}.csv",year),
        "states": _cache("calibrate_states_{year}.csv",year),
        }


def missing_inputs(year:int=YEAR) -> list[str]:
    """Counties whose TSGAM training data or weather is not in the cache

    The cache files are named exactly as `loads.total.Total` (version 2
    training data) and `weather.Weather` (version 0) name them. The padded
    prediction window reaches into the previous and next years.
    """
    missing = []
    for state,county in wecc_units():
        training = Cache(package="loads",version=2,path=[state,county,"T_elec_1h_training.csv.gz"])
        weather = [Cache([state,county,f"W_{x}.csv.gz"],package="weather",version=0)
            for x in (year-1,year,year+1)]
        if not training.exists() or not all(x.exists() for x in weather):
            missing.append(f"{county} {state}")
    return missing


def _predict(args:tuple[str,str,str|None,int]) -> tuple[str,np.ndarray]:
    """@private Predict one county's gross load for a year (runs in a worker)"""
    state,county,cachedir,year = args
    if cachedir:
        Cache.CACHEDIR = cachedir
    from loads.total import Total # pylint: disable=import-outside-toplevel
    Total.cache = None # don't hold every fitted estimator in the worker
    index = hours(year)
    padded = pd.date_range(index[0] - pd.Timedelta(hours=LAGS),index[-1] + pd.Timedelta(hours=LAGS),freq="1h")
    data = Total(state,county,date_range=padded,samples=0)["elec_total_MW"]
    data.index = pd.DatetimeIndex(data.index).tz_convert("UTC")
    return f"{county} {state}",data.loc[index[0]:index[-1]].values


def gross_load(year:int=YEAR,
    refresh:bool=False,
    progress:Callable[[int,int,str],None]|None=None,
    ) -> pd.DataFrame:
    """Gross county load for a year (MW), from the cached TSGAM models

    Arguments
    ---------

      - `year`: calendar year (UTC)

      - `refresh`: rebuild the load matrix even when it is cached

      - `progress`: function called as `progress(done,total,unit)` after each
        county prediction

    Returns
    -------

      - `pd.DataFrame`: hourly load (MW), one `"County ST"` column per WECC
        county
    """
    cache = load_cache(year)
    if cache.exists() and not refresh:
        try:
            return pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
        except Exception as err: # pylint: disable=broad-exception-caught
            _logger.debug(f"{cache=} {err}")
            cache.delete()

    units = wecc_units()
    workers = int(os.environ.get("LOADS_TEST_WORKERS",os.cpu_count() or 1))
    jobs = [(state,county,Cache.CACHEDIR,year) for state,county in units]
    results = {}
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_predict,job) for job in jobs]
            for future in as_completed(futures):
                unit,values = future.result()
                results[unit] = values
                if progress:
                    progress(len(results),len(jobs),unit)
    else:
        for job in jobs:
            unit,values = _predict(job)
            results[unit] = values
            if progress:
                progress(len(results),len(jobs),unit)
    data = pd.DataFrame({f"{c} {s}":results[f"{c} {s}"] for s,c in units},index=hours(year))

    # TSGAM predictions can dip slightly below zero for small flat loads
    if (data.values < 0).any():
        _logger.debug(f"clipping {(data.values < 0).sum()} negative load predictions")
    data = data.clip(lower=0.0)
    data.to_csv(cache.pathname,index=True,header=True,compression="gzip")
    return data


def distributed_generation(load:pd.DataFrame) -> pd.DataFrame:
    """Fixed county DG aligned with a load matrix (MW, nonnegative)"""
    data = pd.read_csv(DG_FILE,index_col=[0],parse_dates=[0])
    data.index = pd.DatetimeIndex(data.index).tz_convert("UTC")
    return data.reindex(index=load.index,columns=load.columns).fillna(0.0).abs()


def targets(year:int=YEAR) -> tuple[pd.DataFrame,pd.DataFrame]:
    """Monthly state energy (MWh) and CAISO/WECC peak (MW) targets of a year"""
    result = []
    for name,columns in [("energy_target.csv",None),("peak_target.csv",REGIONS)]:
        data = pd.read_csv(os.path.join(DATA,name),index_col=[0])
        data.index = pd.to_datetime(data.index,utc=True)
        data = data[data.index.year == year]
        result.append(data if columns is None else data[columns])
    return tuple(result)


def membership(units:list[str]) -> pd.DataFrame:
    """CAISO/WECC membership of the units"""
    return pd.read_csv(os.path.join(DATA,"state_groups.csv"),index_col=[0]).reindex(units)[REGIONS]


def calibrated_load(year:int=YEAR,
    refresh:bool=False,
    progress:Callable[[int,int,dict],None]|None=None,
    ) -> dict[str,pd.DataFrame]:
    """Calibrated county load for a year

    Calibrates the gross load matrix month by month with the default settings
    of the calibration exploration notebook, i.e., the predeclared weight
    search (`search=True`) and selection rule.

    Arguments
    ---------

      - `year`: calendar year (UTC)

      - `refresh`: recalibrate even when the result is cached (the load
        matrix is not rebuilt)

      - `progress`: `Calibrate` progress callback

    Returns
    -------

      - `dict`: `load` (shaped gross load, MW), `summary` (per-month
        selection and fit), `regions` (per-month regional peaks) and `states`
        (per-month state energy)
    """
    caches = result_caches(year)
    if all(x.exists() for x in caches.values()) and not refresh:
        try:
            result = {"load":pd.read_csv(caches["load"].pathname,index_col=[0],parse_dates=[0])}
            for name in ["summary","regions","states"]:
                result[name] = pd.read_csv(caches[name].pathname,index_col=[0,1] if name != "summary" else [0])
            return result
        except Exception as err: # pylint: disable=broad-exception-caught
            _logger.debug(f"{caches=} {err}")
            for cache in caches.values():
                if cache.exists():
                    cache.delete()

    from loads.calibrate import Calibrate # pylint: disable=import-outside-toplevel
    load = gross_load(year)
    energy,peak = targets(year)
    shaped = Calibrate(load,
        dg=distributed_generation(load),
        energy=energy,
        peak=peak,
        regions=membership(list(load.columns)),
        search=True,
        progress=progress,
        )
    result = {
        "load": pd.DataFrame(shaped),
        "summary": shaped.summary,
        "regions": shaped.regions,
        "states": shaped.states,
        }
    result["load"].index.name = "timestamp"
    result["load"].to_csv(caches["load"].pathname,index=True,header=True,compression="gzip")
    for name in ["summary","regions","states"]:
        result[name].to_csv(caches[name].pathname,index=True,header=True)
    return result


def caiso_load(year:int=YEAR) -> pd.DataFrame:
    """CAISO reported hourly load (MW) indexed by UTC hour beginning

    The CAISO files list hour-ending (HE) values on Pacific prevailing time,
    with the spring DST hour missing and the fall DST hour repeated, so the
    rows form an unbroken hourly sequence. Each row is assigned its hour
    beginning in UTC from the start of the year, which is checked against
    the local date of every row.
    """
    data = pd.read_csv(os.path.join(CAISO,f"{year}.csv"))
    data = data.loc[:,~data.columns.str.startswith("Unnamed")].dropna(how="all")
    data = data.rename(columns={"HR":"HE","CAISO Total":"CAISO"})
    dates = pd.to_datetime(data["Date"],format="%m/%d/%y")
    start = pd.Timestamp(dates.iloc[0]).tz_localize("America/Los_Angeles").tz_convert("UTC")
    index = pd.date_range(start,periods=len(data),freq="1h",name="timestamp")
    local = index.tz_convert("America/Los_Angeles").tz_localize(None).normalize()
    if not (local == dates.values).all():
        raise ValueError(f"caiso/{year}.csv rows are not an unbroken hourly sequence")
    data.index = index
    return data[["PGE","SCE","SDGE","VEA","CAISO"]].astype(float)


if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG if "--debug" in sys.argv else logging.INFO)
    if not load_cache().exists() or "--refresh" in sys.argv:
        absent = missing_inputs()
        if absent:
            print(f"WARNING: cache lacks {YEAR} inputs for {len(absent)} WECC counties "
                f"(e.g. {absent[0]}); they will be built from the online sources",file=sys.stderr)
    gross_load(refresh="--refresh" in sys.argv,
        progress=lambda done,total,unit:print(f"\rload {done}/{total} {unit:<30}",end="",file=sys.stderr))
    print(file=sys.stderr)
    def _report(done,total,info):
        print(f"\rcalibrate {done}/{total} {info['block']:%Y-%m} {info['step']} {info['status']:<20}",
            end="",file=sys.stderr)
    calibrated_load(refresh="--refresh" in sys.argv,progress=_report)
    print(file=sys.stderr)
