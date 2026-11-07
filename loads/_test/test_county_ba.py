"""County balancing authority factors and BA min/max targets

These tests need no data downloads and run in seconds. They check the
checked-in `loads/wecc/county_ba.csv` (built by `loads/wecc/county_ba.py`),
its overrides, the EIA-930 BA monthly min/max targets in
`loads/_test/data/ba_minmax_target.csv`, and the fitting step of
`county_ba.py` on a small example.
"""

# pylint: disable=redefined-outer-name
import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

WECC = os.path.join(os.path.dirname(__file__),"..","wecc")
DATA = os.path.join(os.path.dirname(__file__),"data")


@pytest.fixture(scope="module")
def county_ba():
    """The county_ba.py script as a module"""
    spec = importlib.util.spec_from_file_location("county_ba",os.path.join(WECC,"county_ba.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def factors() -> pd.DataFrame:
    """Checked-in county BA factors"""
    return pd.read_csv(os.path.join(WECC,"county_ba.csv"))


@pytest.fixture(scope="module")
def targets() -> pd.DataFrame:
    """Checked-in BA monthly min/max targets"""
    return pd.read_csv(os.path.join(DATA,"ba_minmax_target.csv"),parse_dates=["timestamp"])


def test_factors_cover_wecc_counties(factors):
    """Every WECC county has factors that sum to one"""
    counties = pd.read_csv(os.path.join(WECC,"wecc_estimate.csv.gz"),index_col=0,nrows=1).columns
    assert set(factors.county_st) == set(counties)
    assert np.allclose(factors.groupby("county_st").factor.sum(),1.0,atol=1e-5)
    assert (factors.factor > 0).all() and (factors.factor <= 1).all()
    assert set(factors.method) <= {"eia861","override","state"}


def test_overrides_applied(factors):
    """Each overridden county has exactly the override factors"""
    overrides = pd.read_csv(os.path.join(WECC,"county_ba_overrides.csv"))
    assert np.allclose(overrides.groupby("county_st").factor.sum(),1.0)
    for county,group in overrides.groupby("county_st"):
        found = factors[factors.county_st == county].set_index("ba").factor.sort_index()
        expected = group.set_index("ba").factor.sort_index()
        assert list(found.index) == list(expected.index)
        assert np.allclose(found.values,expected.values,atol=1e-6)
        assert (factors[factors.county_st == county].method == "override").all()


def test_targets(targets,factors):
    """Targets cover 2018-2022 for the 28 EIA-930 BAs, all served by some county"""
    assert targets.timestamp.dt.tz is not None
    assert targets.timestamp.nunique() == 60
    assert targets.groupby("timestamp").ba.nunique().eq(28).all()
    assert (targets["max"] >= targets["min"]).all() and (targets["min"] > 0).all()
    assert set(targets.ba) <= set(factors.ba)


def test_fit_state(county_ba):
    """The fit keeps utility sales and county energy where the support allows"""
    support = pd.DataFrame([[True,True,False],[False,True,True],[False,False,True]],
        index=pd.MultiIndex.from_tuples([(1,"A"),(2,"B"),(3,"B")],names=["utility","ba"]),
        columns=["x","y","z"])
    rows = pd.Series([30.0,50.0,20.0],index=support.index)
    columns = pd.Series([20.0,40.0,40.0],index=support.columns)
    fitted = county_ba.fit_state(support,rows,columns)
    assert np.allclose(fitted.sum(axis=1),rows)
    assert np.allclose(fitted.sum(axis=0),columns)
    assert (fitted.values[~support.values] == 0).all()
