"""EIA-930 balancing authority calibration tests on a small synthetic system

These tests need no data downloads or cache and run in seconds. They check
`loads.calibrate.CalibrateForm930` on six synthetic counties served by three
balancing authorities (BAs), one of which (`XX`) reports no demand, and the
`allocate` method on three nodes. The EIA-930 download is replaced by a stub.
"""

# pylint: disable=redefined-outer-name
import sys
import types

import numpy as np
import pandas as pd
import pytest

from loads.calibrate import CalibrateForm930, CalibrationError

UNITS = ["A1 ST","A2 ST","B1 ST","B2 ST","AB ST","BX ST"]
FACTORS = [
    ("A1 ST","AAA",1.0),
    ("A2 ST","AAA",1.0),
    ("B1 ST","BBB",1.0),
    ("B2 ST","BBB",1.0),
    ("AB ST","AAA",0.25),
    ("AB ST","BBB",0.75),
    ("BX ST","BBB",0.6),
    ("BX ST","XX",0.4),
    ]
NODES = [
    ("A1 ST","n1",1.0),
    ("A2 ST","n1",0.5),
    ("A2 ST","n2",0.5),
    ("B1 ST","n2",1.0),
    ("B2 ST","n3",1.0),
    ("AB ST","n3",1.0),
    ("BX ST","n3",1.0),
    ]


@pytest.fixture(scope="module")
def system() -> dict:
    """Synthetic county load, BA factors, BA demand and node factors"""
    rng = np.random.default_rng(2)
    index = pd.date_range("2020-07-31 00:00:00+00:00",periods=72,freq="1h",name="timestamp")
    hour = np.arange(len(index))
    load = pd.DataFrame({unit:(5+n)*(1+0.4*np.sin(2*np.pi*(hour+2*n)/24)) + rng.random(len(hour))
        for n,unit in enumerate(UNITS)},index=index)
    factors = pd.DataFrame(FACTORS,columns=["county_st","ba","factor"]).assign(method="test")
    wide = factors.pivot_table(index="county_st",columns="ba",values="factor",fill_value=0.0)
    estimate = load[wide.index] @ wide
    demand = pd.DataFrame({
        "AAA":estimate["AAA"]*(1.2+0.1*np.cos(2*np.pi*hour/24)),
        "BBB":estimate["BBB"]*0.8,
        "ZZZ":100.0,  # a BA with no counties is ignored
        },index=index)
    nodes = pd.DataFrame(NODES,columns=["county_st","node","factor"])
    return {"load":load,"factors":factors,"wide":wide,"demand":demand,"nodes":nodes}


def naive(load,wide,demand) -> pd.DataFrame:
    """Reference loop implementation of the disaggregation (no missing data)"""
    result = pd.DataFrame(0.0,index=load.index,columns=load.columns)
    for t in load.index:
        for ba in wide.columns:
            share = {u:wide.loc[u,ba]*load.loc[t,u] for u in wide.index if wide.loc[u,ba] > 0}
            total = sum(share.values())
            for u,value in share.items():
                if ba not in demand.columns:
                    result.loc[t,u] += value
                elif total > 0:
                    result.loc[t,u] += demand.loc[t,ba] * value / total
                else:
                    result.loc[t,u] += demand.loc[t,ba] * wide.loc[u,ba] / wide[ba].sum()
    return result


def test_matches_naive_loop(system):
    """Vectorized result equals a direct loop over hours and BAs"""
    result = CalibrateForm930(system["load"],system["factors"],system["demand"])
    expected = naive(system["load"],system["wide"],system["demand"])
    assert list(result.columns) == UNITS
    assert result.index.equals(system["load"].index)
    np.testing.assert_allclose(result.values,expected.values,rtol=1e-12)


def test_ba_shares_sum_to_demand(system):
    """Unit shares of each reporting BA sum to its demand"""
    result = CalibrateForm930(system["load"],system["factors"],system["demand"])
    for ba in ["AAA","BBB"]:
        shares = system["load"][system["wide"].index] * system["wide"][ba] * result.scale[ba].values[:,None]
        np.testing.assert_allclose(shares.sum(axis=1),system["demand"][ba],rtol=1e-12)
    xx = (system["load"][system["wide"].index] * system["wide"]["XX"]).sum(axis=1)
    np.testing.assert_allclose(result.sum(axis=1),system["demand"][["AAA","BBB"]].sum(axis=1) + xx,rtol=1e-12)


def test_attributes(system):
    """Attributes report the factors, demand, estimate and scale used"""
    result = CalibrateForm930(system["load"],system["factors"],system["demand"])
    assert result.uncalibrated == ["XX"]
    assert not result.unassigned
    assert list(result.demand.columns) == ["AAA","BBB"]
    assert list(result.factors.columns) == ["AAA","BBB","XX"]
    assert (result.scale["XX"] == 1.0).all()
    np.testing.assert_allclose(result.scale["BBB"],0.8)
    np.testing.assert_allclose(result.estimate["AAA"]*result.scale["AAA"],system["demand"]["AAA"])
    assert type(result.sum(axis=1)) is pd.Series  # pylint: disable=unidiomatic-typecheck
    assert type(result.iloc[:2]) is pd.DataFrame  # pylint: disable=unidiomatic-typecheck


def test_wide_factors(system):
    """Wide and long factors give the same result"""
    long = CalibrateForm930(system["load"],system["factors"],system["demand"])
    wide = CalibrateForm930(system["load"],system["wide"],system["demand"])
    pd.testing.assert_frame_equal(pd.DataFrame(long),pd.DataFrame(wide))


def test_zero_estimate_splits_by_factors(system):
    """BA demand is split by the factors when its estimated load is zero"""
    load = system["load"].copy()
    load.iloc[:3,:] = 0.0
    result = CalibrateForm930(load,system["factors"],system["demand"])
    for t in range(3):
        assert result.iloc[t]["A1 ST"] == pytest.approx(system["demand"]["AAA"].iloc[t]/2.25)
        assert result.iloc[t]["AB ST"] == pytest.approx(system["demand"]["AAA"].iloc[t]*0.25/2.25
            + system["demand"]["BBB"].iloc[t]*0.75/3.35)
    np.testing.assert_allclose(result.iloc[:3].sum(axis=1),system["demand"][["AAA","BBB"]].iloc[:3].sum(axis=1))
    np.testing.assert_allclose(result.values,naive(load,system["wide"],system["demand"]).values,rtol=1e-12)


def test_missing_demand(system):
    """Missing, negative or non-finite demand hours are NaN or keep the estimate"""
    demand = system["demand"].copy()
    demand.iloc[0,0] = np.nan                 # AAA
    demand.iloc[1,1] = -5.0                   # BBB
    demand = demand.drop(demand.index[2])     # both
    result = CalibrateForm930(system["load"],system["factors"],demand)
    assert result.iloc[0][["A1 ST","A2 ST","AB ST"]].isna().all()
    assert result.iloc[0][["B1 ST","B2 ST","BX ST"]].notna().all()
    assert result.iloc[1][["B1 ST","B2 ST","AB ST","BX ST"]].isna().all()
    assert result.iloc[2].isna().all()
    assert result.iloc[3:].notna().all().all()
    assert np.isnan(result.scale.iloc[0]["AAA"])

    keep = CalibrateForm930(system["load"],system["factors"],demand,missing="keep")
    assert keep.notna().all().all()
    load = system["load"]
    np.testing.assert_allclose(keep.iloc[2],load.iloc[2])
    assert keep.iloc[0]["A1 ST"] == pytest.approx(load.iloc[0]["A1 ST"])
    np.testing.assert_allclose(keep.iloc[3:],result.iloc[3:])


def test_unassigned_units_unchanged(system):
    """Units without factors are returned unchanged"""
    load = system["load"].assign(**{"Other ST":7.0})
    result = CalibrateForm930(load,system["factors"],system["demand"])
    assert result.unassigned == ["Other ST"]
    assert (result["Other ST"] == 7.0).all()
    assert list(result.columns) == UNITS + ["Other ST"]


def test_invalid_inputs(system):
    """Invalid inputs raise CalibrationError"""
    load,factors,demand = system["load"],system["factors"],system["demand"]
    with pytest.raises(CalibrationError):
        CalibrateForm930(load.reset_index(drop=True),factors,demand)
    with pytest.raises(CalibrationError):
        CalibrateForm930(load - 100,factors,demand)
    bad = load.copy()
    bad.iloc[0,0] = np.nan
    with pytest.raises(CalibrationError):
        CalibrateForm930(bad,factors,demand)
    with pytest.raises(CalibrationError):
        CalibrateForm930(load,factors.assign(factor=factors["factor"]*0.9),demand)
    with pytest.raises(CalibrationError):
        CalibrateForm930(load,factors.assign(factor=-factors["factor"]),demand)
    with pytest.raises(CalibrationError):
        CalibrateForm930(load,factors.values,demand)
    with pytest.raises(CalibrationError):
        CalibrateForm930(load,factors,demand.reset_index(drop=True))
    with pytest.raises(CalibrationError):
        CalibrateForm930(load,factors,demand,missing="drop")


def test_allocate(system):
    """Allocation to nodes conserves the total and propagates NaN"""
    result = CalibrateForm930(system["load"],system["factors"],system["demand"])
    nodes = result.allocate(system["nodes"])
    assert list(nodes.columns) == ["n1","n2","n3"]
    np.testing.assert_allclose(nodes.sum(axis=1),result.sum(axis=1),rtol=1e-12)
    np.testing.assert_allclose(nodes["n1"],result["A1 ST"] + 0.5*result["A2 ST"])

    demand = system["demand"].copy()
    demand.iloc[0,0] = np.nan
    nodes = CalibrateForm930(system["load"],system["factors"],demand).allocate(system["nodes"])
    assert nodes.iloc[0].isna().all()  # every node has a county served by AAA
    assert nodes.iloc[1:].notna().all().all()


def test_form930_download(system,monkeypatch):
    """Default demand is downloaded with eia.Form930 for every BA respondent"""
    calls = []

    class Form930(pd.DataFrame):
        """Stub of `eia.Form930`"""
        @staticmethod
        def respondents():
            return ["AAA","BBB"]
        def __init__(self,region,year,month,refresh=False):
            calls.append((region,year,month,refresh))
            start = pd.Timestamp(year=year,month=month,day=1,tz="UTC")
            hours = pd.date_range(start,start+pd.DateOffset(months=1),freq="h",inclusive="left",name="timestamp")
            super().__init__({"timestamp":hours,
                "load_MW":system["demand"][region].reindex(hours).values})

    monkeypatch.setitem(sys.modules,"eia",types.SimpleNamespace(Form930=Form930))
    result = CalibrateForm930(system["load"],system["factors"])
    assert sorted(calls) == [("AAA",2020,7,False),("AAA",2020,8,False),("BBB",2020,7,False),("BBB",2020,8,False)]
    assert result.uncalibrated == ["XX"]
    expected = CalibrateForm930(system["load"],system["factors"],system["demand"])
    pd.testing.assert_frame_equal(pd.DataFrame(result),pd.DataFrame(expected))
