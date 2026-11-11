"""Energy-only calibration tests on synthetic data

These tests need no data downloads or cache and run in seconds. They check
`loads.calibrate.CalibrateEnergy` on synthetic hourly county loads with and
without fixed DG, for whole-period and monthly energy targets.
"""

# pylint: disable=redefined-outer-name
import numpy as np
import pandas as pd
import pytest

from loads.calibrate import CalibrateEnergy, CalibrationError


@pytest.fixture(scope="module")
def load() -> pd.DataFrame:
    """Two synthetic counties, July and August 2020"""
    index = pd.date_range("2020-07-01 00:00:00+00:00","2020-08-31 23:00:00+00:00",freq="1h",name="timestamp")
    hour = np.arange(len(index))
    return pd.DataFrame({
        "Alameda CA":100*(1.5+np.sin(2*np.pi*hour/24)),
        "Washoe NV":40*(1.5+np.sin(2*np.pi*(hour+3)/24)),
        },index=index)


@pytest.fixture(scope="module")
def dg(load) -> pd.DataFrame:
    """Rooftop PV (positive output) of the first county only"""
    hour = np.arange(len(load))
    return pd.DataFrame({"Alameda CA":10*np.clip(np.sin(2*np.pi*(hour-14)/24),0,None)},index=load.index)


@pytest.fixture(scope="module")
def monthly(load) -> pd.DataFrame:
    """Monthly energy targets (MWh), 5% and 10% above the load"""
    months = load.resample("1MS").sum()
    return months * [1.05,1.10]


def test_whole_period(load):
    """Each unit's energy over the whole period matches its target"""
    targets = {"Alameda CA":1.2*load["Alameda CA"].sum(),"Washoe NV":0.9*load["Washoe NV"].sum()}
    result = CalibrateEnergy(load,targets)
    assert result.shape == load.shape
    assert np.allclose(result.sum(),pd.Series(targets))
    assert np.allclose(result["Alameda CA"],1.2*load["Alameda CA"])
    assert np.allclose(result.scale["Washoe NV"],0.9)
    assert np.allclose(result.net,result)


def test_monthly(load,monthly):
    """Each month's energy matches its target and the shape within a month is kept"""
    result = CalibrateEnergy(load,monthly)
    assert np.allclose(result.resample("1MS").sum(),monthly)
    for month in monthly.index:
        rows = result.index.month == month.month
        ratio = result.loc[rows] / load.loc[rows]
        assert np.allclose(ratio.std(),0.0)
    assert len(result.parameters) == 4
    assert np.allclose(result.parameters.calibrated_MWh,result.parameters.target_MWh)


def test_dg_is_fixed(load,dg,monthly):
    """With DG, the net energy matches and only the gross load is scaled"""
    result = CalibrateEnergy(load,monthly,dg=dg)
    assert np.allclose(result.net.resample("1MS").sum(),monthly)
    assert np.allclose(result.net["Alameda CA"],result["Alameda CA"] - dg["Alameda CA"])
    assert np.allclose(result.net["Washoe NV"],result["Washoe NV"])
    negative = CalibrateEnergy(load,monthly,dg=-dg)  # elec_dg_MW sign convention
    assert np.allclose(negative,result)


def test_partial_month(load):
    """A partial month is matched over the hours present"""
    part = load.iloc[24*20:24*40]
    targets = part.resample("1MS").sum() * 1.5
    result = CalibrateEnergy(part,targets)
    assert np.allclose(result.resample("1MS").sum(),targets)


def test_zero_unit(load):
    """A unit without load and a zero target is unchanged"""
    data = load.assign(**{"Alpine CA":0.0})
    targets = {"Alameda CA":load["Alameda CA"].sum(),"Washoe NV":load["Washoe NV"].sum(),"Alpine CA":0.0}
    result = CalibrateEnergy(data,targets)
    assert (result["Alpine CA"] == 0).all()


def test_errors(load,dg,monthly):
    """Invalid inputs raise CalibrationError"""
    targets = load.sum().to_dict()
    with pytest.raises(CalibrationError,match="timestamp"):
        CalibrateEnergy(load.reset_index(drop=True),targets)
    with pytest.raises(CalibrationError,match="nonnegative"):
        CalibrateEnergy(-load,targets)
    with pytest.raises(CalibrationError,match="missing"):
        CalibrateEnergy(load.mask(np.repeat((load.index.hour == 3)[:,None],2,axis=1)),targets)
    with pytest.raises(CalibrationError,match="no targets"):
        CalibrateEnergy(load,{"Alameda CA":1.0})
    with pytest.raises(CalibrationError,match="no energy target row"):
        CalibrateEnergy(load,monthly.iloc[:1])
    with pytest.raises(CalibrationError,match="not positive"):
        CalibrateEnergy(load,{"Alameda CA":-1.0,"Washoe NV":1.0})
    with pytest.raises(CalibrationError,match="not positive"):
        CalibrateEnergy(load.assign(**{"Alpine CA":0.0}),{**targets,"Alpine CA":5.0})
    with pytest.raises(CalibrationError,match="same sign"):
        CalibrateEnergy(load,targets,dg=dg - 1)
    with pytest.raises(CalibrationError,match="not in load"):
        CalibrateEnergy(load,targets,dg=dg.assign(**{"Kern CA":0.0}))
    with pytest.raises(CalibrationError,match="dict, Series, or DataFrame"):
        CalibrateEnergy(load,1.0)
