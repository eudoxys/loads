"""Checks of `loads/_validate/validate_calibrate_form930.py` on a synthetic system

These tests need no data downloads and run in seconds. They run the
validation checks (BA shares, WECC total, US only, nonnegative, wecc240
comparison) on the synthetic system of `test_calibrate_form930.py` and
check that each one passes on correct data and fails when the data is
perturbed.
"""

# pylint: disable=redefined-outer-name
import importlib.util
import pathlib

import numpy as np
import pandas as pd
import pytest

from loads.calibrate import CalibrateForm930
from test_calibrate_form930 import system  # pylint: disable=unused-import

_FILE = pathlib.Path(__file__).parents[1] / "_validate" / "validate_calibrate_form930.py"
_SPEC = importlib.util.spec_from_file_location("validate_calibrate_form930",_FILE)
validation = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validation)


@pytest.fixture
def case(system) -> dict:
    """Calibrated synthetic system with its WECC total (EIA-930 sum, rounded)

    The synthetic counties are renamed from state `ST` to `NV` so they pass
    the US-state check.
    """
    names = {x:x.replace(" ST"," NV") for x in system["load"].columns}
    system = {**system,
        "load":system["load"].rename(columns=names),
        "factors":system["factors"].replace(names),
        "nodes":system["nodes"].replace(names),
        }
    county = CalibrateForm930(system["load"],system["factors"],system["demand"])
    node = county.allocate(system["nodes"])
    wecc = system["demand"][["AAA","BBB"]].sum(axis=1).round(0)
    return {**system,"county":county,"node":node,"wecc":wecc}


def run(case,**changes) -> dict:
    """Run the checks and return pass/fail by check number"""
    args = {key:case[key] for key in ["load","factors","demand","county","node","wecc"]}
    args.update(changes)
    return {name.split(".")[0]:passed for name,passed,_ in validation.checks(**args)}


def test_all_pass(case):
    """Every check passes on correct data, including the comparison"""
    result = run(case,compare=case["node"].round(4))
    assert result == {"1":True,"2":True,"3":True,"4":True,"5":None}


def test_ba_shares_fail(case):
    """A county load that is not the sum of its BA shares fails check 1"""
    county = case["county"].copy()
    county.iloc[5,0] += 1.0
    bad = CalibrateForm930(case["load"],case["factors"],case["demand"])
    bad.loc[:,:] = county.values
    assert not run(case,county=bad)["1"]


def test_wecc_total_fail(case):
    """A WECC total that differs by more than the tolerance fails check 2"""
    assert run(case,wecc=case["wecc"] + 2.0)["2"]
    assert not run(case,wecc=case["wecc"] + 10.0)["2"]


def test_us_only_fail(case):
    """A non-US county or a Canadian BA fails check 3"""
    load = case["load"].rename(columns={"A1 NV":"A1 BC"})
    factors = case["factors"].replace({"A1 NV":"A1 BC"})
    county = CalibrateForm930(load,factors,case["demand"])
    nodes = case["nodes"].replace({"A1 NV":"A1 BC"})
    assert not run(case,load=load,factors=factors,county=county,node=county.allocate(nodes))["3"]

    factors = case["factors"].replace({"XX":"BCHA"})
    county = CalibrateForm930(case["load"],factors,case["demand"])
    assert not run(case,factors=factors,county=county,node=county.allocate(case["nodes"]))["3"]


def test_node_total_fail(case):
    """Node loads that do not add up to the county total fail check 3"""
    node = case["node"].copy()
    node.iloc[:,0] *= 1.01
    assert not run(case,node=node)["3"]


def test_compare_informational(case):
    """The wecc240 comparison is reported, never pass/fail"""
    other = case["node"].copy()
    other.iloc[3,1] += 1.0
    detail = {name.split(".")[0]:(passed,text) for name,passed,text in validation.checks(
        **{key:case[key] for key in ["load","factors","demand","county","node","wecc"]},compare=other)}
    assert detail["5"][0] is None
    assert "max |node - wecc240 node| 1 MW" in detail["5"][1]


def test_missing_demand(case):
    """Missing demand hours are excluded from the totals and match NaN"""
    demand = case["demand"].copy()
    demand.iloc[0,0] = np.nan
    county = CalibrateForm930(case["load"],case["factors"],demand)
    result = run(case,demand=demand,county=county,node=county.allocate(case["nodes"]))
    assert result == {"1":True,"2":True,"3":True,"4":True}


def test_ba_shares_function(case):
    """`ba_shares` reproduces the calibrated loads and BA demand"""
    shares,errors = validation.ba_shares(case["load"],case["county"].factors,case["demand"])
    assert sorted(errors.index) == ["AAA","BBB"]
    assert errors.max() < 1e-9
    pd.testing.assert_frame_equal(shares,pd.DataFrame(case["county"]),check_freq=False)


def test_with_dg(case):
    """With DG the checks pass, negative net load is allowed, and the comparison is informational"""
    hour = np.arange(len(case["load"]))
    dg = pd.DataFrame({"A1 NV":20.0*np.clip(np.sin(2*np.pi*(hour-6)/24),0,None)},index=case["load"].index)
    county = CalibrateForm930(case["load"],case["factors"],case["demand"],dg=dg)
    node = county.allocate(case["nodes"])
    assert (county.values < 0).any()
    result = run(case,county=county,node=node,dg=dg,compare=case["node"])
    assert result == {"1":True,"2":True,"3":True,"4":True,"5":None}
    shares,errors = validation.ba_shares(case["load"],county.factors,case["demand"],dg)
    assert errors.max() < 1e-9
    np.testing.assert_allclose(shares.values,county.values,atol=1e-9)
