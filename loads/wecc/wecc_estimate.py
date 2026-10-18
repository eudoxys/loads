"""WECC county hourly load estimate for 2018 through 2022

Generates `wecc_estimate.csv`, which contains the estimated hourly electric
load in MW of every WECC county from 2018-01-01 00:00 UTC through 2022-12-31
23:00 UTC.

Usage
-----

    python3 wecc_estimate.py [--jobs N] [--refresh] [--debug] [--output FILE]

Options
-------
- `-j N`, `--jobs N`: number of worker processes (default all CPUs)
- `--refresh`: ignore cached county estimates and recompute them
- `--debug`: enable debug logging
- `-o FILE`, `--output FILE`: output file name (default `wecc_estimate.csv`
  in this folder)

Description
-----------

For each WECC county (as given by `fips.Counties`) the estimate is computed
as follows:

```mermaid
flowchart LR
    clusters.csv -->|medoid| harmonics
    explore_estimator_clusters.csv -->|MAPE best| harmonics
    harmonics --> Estimator
    Weather[NSRDB weather 2018-2022] --> Estimator
    Sectors[2018 sector loads] --> Estimator
    Estimator -->|hourly MW| shape
    shape -->|Σ month| model_mwh
    county_mwh.csv --> target_mwh
    county_dg.csv.gz -->|Σ month| target_mwh
    shape --> mul((x))
    target_mwh --> mul
    model_mwh -->|1/| mul
    mul --> wecc_estimate.csv
```

1. The hourly load shape is obtained from `loads.estimator.Estimator` for the
   years 2018 through 2022 using the TSGAM harmonics that minimize the MAPE
   for the county's cluster medoid (see `loads/clusters.csv` and
   `loads/_explore/explore_estimator_clusters.csv`). The 2018 reference
   year data is kept as the actual sector loads.

2. The hourly shape is rescaled month by month so that the monthly energy
   matches the county's gross load, i.e., the EIA 861M retail energy
   allocated to the county (`county_mwh.csv`) plus the county's distributed
   solar generation (`county_dg.csv.gz`), which is not included in retail
   sales.

The rows of the output are hourly UTC timestamps. The columns are named
`COUNTY_ST`, where `COUNTY` is the county name and `ST` is the state
abbreviation, sorted by state and then by county name. Values are in MW
rounded to 4 decimals.

County estimates are cached so an interrupted run resumes where it left off.

Caveats
-------

1. Building the inputs for all WECC counties downloads RESstock, COMstock,
   Census, NLR and NSRDB data and can take many hours on a cold cache. NSRDB
   credentials are required in `~/.nsrdb/credentials.json`.

2. Counties without monthly energy data in `county_mwh.csv` are not
   calibrated and the TSGAM estimate is used as is. A warning is printed for
   each such county. Counties without DG data are calibrated to retail
   energy only.

3. Monthly calibration uses UTC calendar months.

See also
--------
- `loads.estimator.Estimator`
- `examples/county_total.py`
"""

START = "2018-01-01 00:00:00+00:00"
"""First hour of the estimate (UTC)"""

STOP = "2022-12-31 23:00:00+00:00"
"""Last hour of the estimate (UTC)"""

OUTPUT = "wecc_estimate.csv"
"""Default output file name"""

PRECISION = 4
"""Number of decimals in output values"""

CACHE_NAME = "Estimate_2018-2022.csv.gz"
"""Cache file name for each county's estimate"""

# python modules
import os
import sys
import logging
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp

# limit each worker to one BLAS/OpenMP thread so N workers don't oversubscribe
# N cores (must be set before numpy is imported; spawned workers inherit it)
for _var in ["OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS","NUMEXPR_NUM_THREADS"]:
    os.environ.setdefault(_var,"1")

# third-party modules
import pandas as pd

# eudoxys modules
from fips import Counties
from cache import Cache

_logger = logging.getLogger(__file__)

HERE = os.path.dirname(os.path.abspath(__file__))
"""@private Folder containing this script and its input data"""

PACKAGE = os.path.dirname(HERE)
"""@private Folder containing the `loads` package source"""

def _cpu_count():
    """@private Number of CPUs this process may use"""
    try:
        return len(os.sched_getaffinity(0)) # honors taskset/cgroup limits (Linux)
    except AttributeError:
        return os.cpu_count() or 1 # macOS/Windows

def get_counties() -> list[tuple[str,str]]:
    """Get the WECC counties

    Returns
    -------
    - `list[tuple[str,str]]`: list of `(state,county)` sorted by state
      abbreviation and then by county name
    """
    counties = Counties(use_index=["RO"],selection="WECC",set_index=["ST","COUNTY"])
    return sorted(set(counties.index))

def get_harmonics(metric:str="mape") -> dict[str,list[int]]:
    """Get the TSGAM harmonics for each county from its cluster medoid

    Arguments
    ---------
    - `metric`: error metric used to select the medoid harmonics (`mae`,
      `rmse`, or `mape`)

    Returns
    -------
    - `dict[str,list[int]]`: `[yearly,weekly,daily]` harmonics by `"County ST"`
    """
    clusters = pd.read_csv(os.path.join(PACKAGE,"clusters.csv"),index_col="county_st")
    best = pd.read_csv(os.path.join(PACKAGE,"_explore","explore_estimator_clusters.csv"))
    best = best[best.metric==metric].set_index("county")
    return {county_st:[int(best.loc[medoid,x]) for x in ["yearly","weekly","daily"]]
        for county_st,medoid in clusters.medoid.items()}

def get_targets() -> pd.DataFrame:
    """Get the monthly gross energy targets for each county

    Returns
    -------
    - `pd.DataFrame`: monthly MWh by `"County ST"`, indexed by month start (UTC)

    The target is the retail energy allocated to the county plus the county's
    distributed solar generation.
    """
    retail = pd.read_csv(os.path.join(HERE,"county_mwh.csv"),index_col=[0])
    retail.index = pd.DatetimeIndex(pd.to_datetime(retail.index,format="%b %Y"),tz="UTC")
    retail = retail[[x for x in retail.columns if "." not in x]] # drop duplicated columns

    dg = pd.read_csv(os.path.join(HERE,"county_dg.csv.gz"),index_col=[0],parse_dates=[0])
    dg = dg.loc[START:STOP].resample("MS").sum()

    return retail.add(dg.reindex(index=retail.index,columns=retail.columns).fillna(0.0))

def estimate_county(
        state:str,
        county:str,
        harmonics:list[int],
        refresh:bool=False,
        ) -> pd.Series:
    """Get the uncalibrated hourly load estimate for a county

    Arguments
    ---------
    - `state`: state abbreviation
    - `county`: county name
    - `harmonics`: TSGAM `[yearly,weekly,daily]` harmonics
    - `refresh`: ignore cached data

    Returns
    -------
    - `pd.Series`: hourly `elec_total_MW` from `START` to `STOP`
    """
    cache = Cache(package="loads",version=0,path=[state,county,CACHE_NAME])
    if cache.exists() and not refresh:
        try:
            _logger.debug(f"cache hit {cache.pathname}")
            data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0]).iloc[:,0]
        except Exception: # pylint: disable=broad-exception-caught
            data = None
            cache.delete()
    else:
        data = None

    if data is None:
        _logger.debug(f"cache miss {cache.pathname}")

        from loads.estimator import Estimator, EstimatorConfig # pylint: disable=import-outside-toplevel

        start,stop = pd.Timestamp(START),pd.Timestamp(STOP)
        config = EstimatorConfig(harmonics=harmonics)
        data = Estimator(f"{county} {state}",list(range(start.year,stop.year+1)),config=config)
        data = data[config.enduse]
        data.index = pd.DatetimeIndex(data.index).tz_convert("UTC")
        data = data.reindex(pd.date_range(start,stop,freq="1h",name="timestamp"))

        # leading hours are undefined by exogenous lags
        data = data.interpolate(limit_direction="both")
        data.to_csv(cache.pathname,index=True,header=True)

    return data

def calibrate(
        load:pd.Series,
        target:pd.Series|None,
        ) -> pd.Series:
    """Rescale an hourly load so its monthly energy matches a target

    Arguments
    ---------
    - `load`: hourly load in MW
    - `target`: monthly energy in MWh indexed by month start (`None` to
      skip calibration)

    Returns
    -------
    - `pd.Series`: calibrated hourly load in MW
    """
    if target is None:
        return load
    model = load.resample("MS").sum()
    scale = (target.reindex(model.index) / model).reindex(load.index,method="ffill")
    return load * scale

def _run_county(state,county,harmonics,refresh):
    """@private Run one county in a worker process"""
    return estimate_county(state,county,harmonics,refresh)

def main( # pylint: disable=too-many-locals
        jobs:int=None,
        refresh:bool=False,
        debug:bool=False,
        output:str=None,
        ):
    """Generate the WECC county load estimate

    Arguments
    ---------
    - `jobs`: number of worker processes (default all CPUs)
    - `refresh`: ignore cached county estimates
    - `debug`: enable debug logging
    - `output`: output file name (default `OUTPUT` in this folder)

    Returns
    -------
    - `int`: exit code
    """
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING)
    jobs = jobs or _cpu_count()
    output = output or os.path.join(HERE,OUTPUT)

    counties = get_counties()
    harmonics = get_harmonics()
    targets = get_targets()
    print(f"{len(counties)} WECC counties, {jobs} workers",flush=True)

    missing = [f"{c} {s}" for s,c in counties if f"{c} {s}" not in harmonics]
    if missing:
        print(f"ERROR: no cluster medoid for {', '.join(missing)}",file=sys.stderr)
        return 1

    # populate shared state-level caches serially before fanning out
    first = {}
    for state,county in counties:
        first.setdefault(state,county)
    results = {}
    for state,county in first.items():
        print(f"  warming cache for {county} {state}",flush=True)
        results[(state,county)] = estimate_county(state,county,harmonics[f"{county} {state}"],refresh)

    # run the remaining counties
    failed = []
    pending = [x for x in counties if x not in results]
    with ProcessPoolExecutor(
            max_workers=jobs,
            mp_context=mp.get_context("spawn"), # same behavior on Linux and macOS
            ) as pool:
        futures = {pool.submit(_run_county,s,c,harmonics[f"{c} {s}"],refresh):(s,c)
            for s,c in pending}
        for n,future in enumerate(as_completed(futures),1):
            state,county = futures[future]
            try:
                results[(state,county)] = future.result()
            except Exception as err: # pylint: disable=broad-exception-caught
                failed.append(f"{county} {state}")
                print(f"  [{n}/{len(pending)}] FAILED {county} {state}",
                    f"({type(err).__name__}: {err})",file=sys.stderr,flush=True)
                continue
            print(f"  [{n}/{len(pending)}] {county} {state}",flush=True)

    if failed:
        print(f"ERROR: {len(failed)} counties failed; rerun to retry them",file=sys.stderr)
        return 1

    # calibrate and assemble
    columns = {}
    for state,county in counties:
        county_st = f"{county} {state}"
        if county_st in targets.columns:
            target = targets[county_st]
        else:
            print(f"WARNING: no monthly energy data for {county_st},",
                "using uncalibrated estimate",file=sys.stderr)
            target = None
        columns[f"{county}_{state}"] = calibrate(results[(state,county)],target)

    result = pd.DataFrame(columns).round(PRECISION)
    result.index.name = "timestamp"
    result.to_csv(output,index=True,header=True)
    print(f"saved {result.shape[0]} hours x {result.shape[1]} counties to {output}")

    return 0

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n",maxsplit=1)[0])
    parser.add_argument("-j","--jobs",type=int,default=None,
        help=f"number of worker processes (default all CPUs: {_cpu_count()})")
    parser.add_argument("--refresh",action="store_true",help="recompute cached county estimates")
    parser.add_argument("--debug",action="store_true",help="enable debug logging")
    parser.add_argument("-o","--output",default=None,help=f"output file (default {OUTPUT})")
    sys.exit(main(**vars(parser.parse_args())))
