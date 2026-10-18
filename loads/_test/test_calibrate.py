"""Calibration tests: August 2020 net-load shaping over all WECC counties

The test assembles the county form of the shaping problem for August 2020:

  - gross load $X$: `Total(...,samples=0)` TSGAM predictions of
    `elec_total_MW` for every WECC county, driven by 2020 weather;

  - fixed DG $D$: `loads/wecc/county_dg.csv.gz`;

  - state energy targets: `data/energy_target.csv` (August 2020 row);

  - CAISO and WECC peak targets: `data/peak_target.csv` (August 2020 row);

  - CAISO/WECC county membership: `data/state_groups.csv`.

It then searches the predeclared 88-point weight grid and checks the selected
solution against the selection tolerances and unit safeguards.

The TSGAM inputs are built only from the local `cache` package files (2018
training data and 2020 weather), so nothing is downloaded when the cache is
populated. The assembled load matrix is itself cached as
`loads/0/_test/calibrate_X_2020-08.csv.gz`, so only the first run pays for
the 407 county predictions (run in parallel; set `LOADS_TEST_WORKERS` to
change the number of processes). Set `LOADS_CACHEDIR` to use a cache folder
other than the `cache` package default.
"""

# pylint: disable=redefined-outer-name
import os
import sys
import logging
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
import pytest

from cache import Cache
from fips import Counties

import loads
from loads.calibrate import Calibrate

_logger = logging.getLogger(__file__)

DATA = os.path.join(os.path.dirname(__file__),"data")
MONTH = "2020-08"
START = pd.Timestamp(f"{MONTH}-01 00:00:00+00:00")
END = pd.Timestamp("2020-08-31 23:00:00+00:00")
LAGS = 3 # Total trims this many hours from each end of a prediction
DG_FILE = os.path.join(os.path.dirname(loads.__file__),"wecc","county_dg.csv.gz")

if os.environ.get("LOADS_CACHEDIR"):
    Cache.CACHEDIR = os.environ["LOADS_CACHEDIR"]


def _read_month(name:str) -> pd.Series:
    """Read the August 2020 row of a monthly target file"""
    data = pd.read_csv(os.path.join(DATA,name),index_col=[0])
    data.index = pd.to_datetime(data.index,utc=True)
    return data.loc[data.index == START].iloc[0].dropna()


def _wecc_units() -> list[tuple[str,str]]:
    """WECC (state,county) pairs, sorted by "County ST" name"""
    counties = Counties(use_index=["SYSTEM"]).loc["WECC"]
    return sorted(zip(counties.ST,counties.COUNTY),key=lambda x:f"{x[1]} {x[0]}")


def _predict(args:tuple[str,str,str|None]) -> tuple[str,np.ndarray]:
    """Predict one county's August 2020 gross load (runs in a worker)"""
    state,county,cachedir = args
    if cachedir:
        Cache.CACHEDIR = cachedir
    from loads.total import Total # pylint: disable=import-outside-toplevel
    Total.cache = None # don't hold every fitted estimator in the worker
    padded = pd.date_range(START - pd.Timedelta(hours=LAGS),END + pd.Timedelta(hours=LAGS),freq="1h")
    data = Total(state,county,date_range=padded,samples=0)["elec_total_MW"]
    data.index = pd.DatetimeIndex(data.index).tz_convert("UTC")
    return f"{county} {state}",data.loc[START:END].values


def _load_cache() -> Cache:
    """Cache file holding the assembled August 2020 load matrix"""
    return Cache(package="loads",version=0,path=["_test",f"calibrate_X_{MONTH}.csv.gz"])


def _missing_inputs() -> list[str]:
    """Counties whose TSGAM training data or 2020 weather is not in the cache

    The cache files are named exactly as `loads.total.Total` (version 2
    training data) and `weather.Weather` (version 0) name them.
    """
    if _load_cache().exists():
        return []
    missing = []
    for state,county in _wecc_units():
        training = Cache(package="loads",version=2,path=[state,county,"T_elec_1h_training.csv.gz"])
        weather = Cache([state,county,f"W_{START.year}.csv.gz"],package="weather",version=0)
        if not training.exists() or not weather.exists():
            missing.append(f"{county} {state}")
    return missing


def august_2020_load(refresh:bool=False) -> pd.DataFrame:
    """Gross county load for August 2020 (MW), from the cached TSGAM models"""
    cache = _load_cache()
    if cache.exists() and not refresh:
        try:
            return pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
        except Exception as err: # pylint: disable=broad-exception-caught
            _logger.debug(f"{cache=} {err}")
            cache.delete()

    units = _wecc_units()
    workers = int(os.environ.get("LOADS_TEST_WORKERS",os.cpu_count() or 1))
    jobs = [(state,county,Cache.CACHEDIR) for state,county in units]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = dict(pool.map(_predict,jobs))
    else:
        results = dict(map(_predict,jobs))
    index = pd.date_range(START,END,freq="1h",name="timestamp")
    data = pd.DataFrame({f"{c} {s}":results[f"{c} {s}"] for s,c in units},index=index)

    # TSGAM predictions can dip slightly below zero for small flat loads
    if (data.values < 0).any():
        _logger.debug(f"clipping {(data.values < 0).sum()} negative load predictions")
    data = data.clip(lower=0.0)
    data.to_csv(cache.pathname,index=True,header=True,compression="gzip")
    return data


def august_2020_dg(units:list[str]) -> pd.DataFrame:
    """Fixed county DG for August 2020 (MW, nonnegative)"""
    data = pd.read_csv(DG_FILE,index_col=[0],parse_dates=[0])
    data.index = pd.DatetimeIndex(data.index).tz_convert("UTC")
    data = data.reindex(index=pd.date_range(START,END,freq="1h",name="timestamp"),columns=units)
    return data.fillna(0.0).abs()


@pytest.fixture(scope="module")
def problem() -> dict:
    """Assemble the August 2020 county-form problem

    Building the inputs from scratch downloads weather and building data for
    all 407 WECC counties and takes hours, so the test is skipped unless the
    local cache already holds them. Set `LOADS_TEST_BUILD=1` to build them
    anyway.
    """
    missing = _missing_inputs()
    if missing and not os.environ.get("LOADS_TEST_BUILD"):
        pytest.skip(f"cache lacks August 2020 inputs for {len(missing)} WECC counties "
            f"(e.g. {missing[0]}); set LOADS_TEST_BUILD=1 to build them")
    X = august_2020_load()
    D = august_2020_dg(list(X.columns))
    regions = pd.read_csv(os.path.join(DATA,"state_groups.csv"),index_col=[0])
    return {
        "load": X,
        "dg": D,
        "energy": _read_month("energy_target.csv"),
        "peak": _read_month("peak_target.csv")[["CAISO","WECC"]],
        "regions": regions.reindex(X.columns),
        }


@pytest.fixture(scope="module")
def result(problem) -> Calibrate:
    """Calibrate with the predeclared weight search"""
    return Calibrate(problem["load"],
        dg=problem["dg"],
        energy=problem["energy"],
        peak=problem["peak"],
        regions=problem["regions"],
        search=True,
        )


def test_inputs(problem):
    """Inputs cover all WECC counties and every state target"""
    X = problem["load"]
    assert X.shape == (744,407)
    assert np.isfinite(X.values).all() and (X.values >= 0).all()
    assert problem["dg"].shape == X.shape
    states = {x.rsplit(" ",1)[-1] for x in X.columns}
    assert states == set(problem["energy"].index)
    assert (problem["regions"]["CAISO"] <= problem["regions"]["WECC"]).all()


def test_selection(result):
    """The predeclared rule selects a candidate that passes every tolerance"""
    summary = result.summary.iloc[0]
    assert summary["candidates"] == 88
    assert summary["selection"] == "passed selection tolerances"
    assert summary["qualifying"] > 0
    assert summary["status"] == "optimal"


def test_peaks(result):
    """CAISO and WECC net-load peaks reach their ceilings without exceeding them"""
    for region,row in result.regions.droplevel(0).iterrows():
        assert row.shaped_MW <= row.target_MW * (1 + 1e-6), region
        assert row.shaped_MW >= row.target_MW * (1 - Calibrate.PEAK_SHORTFALL_TOL), region


def test_state_energy(result):
    """Every state's net-load energy is within the selection tolerance"""
    errors = result.states.shaped_error.abs()
    assert errors.max() <= Calibrate.STATE_ENERGY_TOL
    assert errors.max() < result.states.input_error.abs().max()


def test_safeguards(result,problem):
    """Shaped load is affine per county, nonnegative, and within unit safeguards"""
    X = problem["load"]
    parameters = result.parameters.droplevel(0).reindex(X.columns)
    expected = X * parameters.scale.values[None,:] + parameters.offset_MW.values[None,:]
    assert np.allclose(result.values,expected.values)
    assert result.values.min() >= Calibrate.NONNEGATIVE_TOL
    assert (parameters.scale >= -1e-9).all()
    assert (parameters.peak_multiple <= 5.0 + 1e-6).all()
    assert (parameters.relative_rmse <= 2.0 + 1e-6).all()
    assert np.allclose(result.net.values,(result - problem["dg"]).values)


def test_report(result):
    """Write the calibration report to the gitignored `tests/` folder"""
    folder = os.path.join(os.path.dirname(os.path.dirname(__file__)),"tests","calibrate")
    os.makedirs(folder,exist_ok=True)
    result.summary.T.to_csv(os.path.join(folder,f"summary_{MONTH}.csv"))
    result.states.to_csv(os.path.join(folder,f"states_{MONTH}.csv"))
    result.regions.to_csv(os.path.join(folder,f"regions_{MONTH}.csv"))
    result.parameters.to_csv(os.path.join(folder,f"parameters_{MONTH}.csv"))
    result.sweep.to_csv(os.path.join(folder,f"sweep_{MONTH}.csv"),index=False)
    print(result.summary.T.to_string(),file=sys.stderr)


if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG if "--debug" in sys.argv else logging.INFO)
    august_2020_load(refresh="--refresh" in sys.argv)
