"""WECC county hourly uncalibrated load estimate for 2018 through 2022

Generates `wecc_total_estimate.csv.gz`, which contains the uncalibrated
estimated hourly electric load in MW of every WECC county from 2018-01-01
00:00 UTC through 2022-12-31 23:00 UTC, as predicted by
`loads.estimator.Estimator`, without rescaling to monthly energy data.

Usage
-----

    python3 wecc_total_estimate.py [--jobs N] [--refresh] [--debug] [--output FILE]

Options
-------
- `-j N`, `--jobs N`: number of worker processes (default all CPUs)
- `--refresh`: ignore cached county estimates and recompute them
- `--debug`: enable debug logging
- `-o FILE`, `--output FILE`: output file name (default
  `wecc_total_estimate.csv.gz` in this folder)

Description
-----------

For each WECC county (as given by `fips.Counties`) the estimate is computed
as follows:

```mermaid
flowchart LR
    clusters.csv -->|medoid| harmonics
    HARMONICS[PES GM 2027 Table II] --> harmonics
    harmonics --> Estimator
    Weather[NSRDB weather 2018-2022] --> Estimator
    Sectors[2018 sector loads] --> Estimator
    Estimator -->|hourly MW| wecc_total_estimate.csv.gz
```

The hourly load is obtained from `loads.estimator.Estimator` for the years
2018 through 2022 using the parsimonious TSGAM harmonics of the county's
cluster medoid (see `loads/clusters.csv`) given in Table II of the IEEE PES
GM 2027 paper (see `HARMONICS` and References). The 2018 reference year
data is kept as the actual sector loads. Unlike `wecc_estimate.py`, the
estimate is not rescaled to match the county's monthly energy.

The rows of the output are hourly UTC timestamps. The columns are named
`COUNTY ST`, where `COUNTY` is the county name and `ST` is the state
abbreviation, sorted by state and then by county name. Values are in MW
rounded to 4 decimals.

County estimates are cached so an interrupted run resumes where it left off.
The cache file (`Estimate_pesgm2027_2018-2022.csv.gz`) is separate from the
one `wecc_estimate.py` and `node_estimate.py` use, because the harmonics
differ.

Caveats
-------

1. Building the inputs for all WECC counties downloads RESstock, COMstock,
   Census, NLR and NSRDB data and can take many hours on a cold cache. NSRDB
   credentials are required in `~/.nsrdb/credentials.json`.

2. The estimates are not calibrated to EIA energy, so county totals can
   differ substantially from the retail sales and DG in `county_mwh.csv`
   and `county_dg.csv.gz`.

3. Only the harmonics are taken from the paper. The other TSGAM settings
   are the `loads.estimator.EstimatorConfig` defaults.

References
----------
- Harmonics: `data/results/medoid_table.csv` (Table `tab:medoids`) in
  https://github.com/dchassin/load_estimator_pesgm_2027

See also
--------
- `wecc_estimate.py`
- `loads.estimator.Estimator`
"""

START = "2018-01-01 00:00:00+00:00"
"""First hour of the estimate (UTC)"""

STOP = "2022-12-31 23:00:00+00:00"
"""Last hour of the estimate (UTC)"""

OUTPUT = "wecc_total_estimate.csv.gz"
"""Default output file name"""

PRECISION = 4
"""Number of decimals in output values"""

CACHE_NAME = "Estimate_pesgm2027_2018-2022.csv.gz"
"""Cache file name for each county's estimate"""

HARMONICS = {
    "Lincoln OR": [4,2,3],
    "Spokane WA": [4,5,7],
    "Multnomah OR": [2,5,5],
    "San Luis Obispo CA": [4,5,8],
    "Maricopa AZ": [4,3,7],
    "Solano CA": [5,2,7],
    }
"""Parsimonious TSGAM `[yearly,weekly,daily]` harmonics of each cluster
medoid, from Table II of the IEEE PES GM 2027 paper
(`data/results/medoid_table.csv` in `dchassin/load_estimator_pesgm_2027`)"""

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

def get_harmonics() -> dict[str,list[int]]:
    """Get the TSGAM harmonics for each county from its cluster medoid

    Returns
    -------
    - `dict[str,list[int]]`: `[yearly,weekly,daily]` harmonics by `"County ST"`
      (see `HARMONICS`)
    """
    clusters = pd.read_csv(os.path.join(PACKAGE,"clusters.csv"),index_col="county_st")
    return {county_st:list(HARMONICS[medoid]) for county_st,medoid in clusters.medoid.items()}

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
    if not refresh and cache.download():
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

def _run_county(state,county,harmonics,refresh):
    """@private Run one county in a worker process"""
    return estimate_county(state,county,harmonics,refresh)

def _run_parallel(pool,items,harmonics,refresh,results,label):
    """@private Run counties in the worker pool

    Arguments
    ---------
    - `pool`: process pool executor
    - `items`: list of `(state,county)` to run
    - `harmonics`: TSGAM harmonics by `"County ST"`
    - `refresh`: ignore cached data
    - `results`: dictionary in which estimates are stored by `(state,county)`
    - `label`: progress label

    Returns
    -------
    - `list[str]`: `"County ST"` of counties that failed
    """
    failed = []
    futures = {pool.submit(_run_county,s,c,harmonics[f"{c} {s}"],refresh):(s,c)
        for s,c in items}
    for n,future in enumerate(as_completed(futures),1):
        state,county = futures[future]
        try:
            results[(state,county)] = future.result()
        except Exception as err: # pylint: disable=broad-exception-caught
            failed.append(f"{county} {state}")
            print(f"  {label} [{n}/{len(items)}] FAILED {county} {state}",
                f"({type(err).__name__}: {err})",file=sys.stderr,flush=True)
            continue
        print(f"  {label} [{n}/{len(items)}] {county} {state}",flush=True)
    return failed

def main( # pylint: disable=too-many-locals
        jobs:int=None,
        refresh:bool=False,
        debug:bool=False,
        output:str=None,
        ):
    """Generate the uncalibrated WECC county load estimate

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
    print(f"{len(counties)} WECC counties, {jobs} workers",flush=True)

    missing = [f"{c} {s}" for s,c in counties if f"{c} {s}" not in harmonics]
    if missing:
        print(f"ERROR: no cluster medoid for {', '.join(missing)}",file=sys.stderr)
        return 1

    # Cache warming happens in two stages so that no two workers build the
    # same shared cache file at the same time:
    # 1. one county, serially, builds the package-wide caches (industry,
    #    agriculture, floor area) and its own state's caches;
    # 2. the first county of every other state, in parallel, builds each
    #    state's caches (housing units, RESstock/COMstock state files).
    # The remaining counties then run in parallel with all shared caches warm.
    first = {}
    for state,county in counties:
        first.setdefault(state,county)
    seed = next(iter(first.items()))

    results = {}
    failed = []
    print(f"  warming shared caches with {seed[1]} {seed[0]}",flush=True)
    try:
        results[seed] = estimate_county(*seed,harmonics[f"{seed[1]} {seed[0]}"],refresh)
    except Exception as err: # pylint: disable=broad-exception-caught
        print(f"ERROR: unable to warm shared caches with {seed[1]} {seed[0]}",
            f"({type(err).__name__}: {err})",file=sys.stderr)
        return 1

    with ProcessPoolExecutor(
            max_workers=jobs,
            mp_context=mp.get_context("spawn"), # same behavior on Linux and macOS
            ) as pool:

        warm = [x for x in first.items() if x != seed]
        print(f"  warming state caches for {len(warm)} states",flush=True)
        failed += _run_parallel(pool,warm,harmonics,refresh,results,"warm")

        # skip counties whose state cache could not be warmed
        cold = {s for s,c in warm if (s,c) not in results}
        pending = [x for x in counties if x not in results and x[0] not in cold]
        failed += [f"{c} {s}" for s,c in counties
            if s in cold and (s,c) not in results and (s,c) not in warm]
        print(f"  estimating {len(pending)} counties",flush=True)
        failed += _run_parallel(pool,pending,harmonics,refresh,results,"run")

    if failed:
        print(f"ERROR: {len(failed)} counties failed; rerun to retry them",file=sys.stderr)
        return 1

    # assemble
    columns = {f"{county} {state}":results[(state,county)] for state,county in counties}
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
