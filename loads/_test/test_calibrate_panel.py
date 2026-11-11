"""Panel calibration tests on synthetic data

These tests need no data downloads or cache and run in seconds (the energy
and peak cases solve small programs). They check that
`loads.calibrate.CalibrateTotal` and `loads.calibrate.CalibrateNet`
calibrate panels of county (`"County ST"`) and node (geohash) loads with
each calibration chosen by `loads.calibrate.CalibrateConfig`, holding the
configuration's DG fixed whatever DG it is.
"""

# pylint: disable=redefined-outer-name
import numpy as np
import pandas as pd
import pytest

from loads.calibrate import (Calibrate, CalibrateConfig, CalibrationError, CalibrateTotal, CalibrateNet,
    CalibrateEnergy, CalibrateEnergyPeak, CalibratePeaks, CalibrateHourly)

COUNTIES = ["Alameda CA","Contra Costa CA","Washoe NV"]
NODES = ["9q9p1x","9qh0bz"]


def _panel(columns,start="2020-07-01",end="2020-08-31") -> pd.DataFrame:
    """Synthetic total (gross) load panel"""
    index = pd.date_range(f"{start} 00:00:00+00:00",f"{end} 23:00:00+00:00",freq="1h",name="timestamp")
    hour = np.arange(len(index))
    return pd.DataFrame({name:100*(k+1)*(1.5+np.sin(2*np.pi*((hour+2*k)%24)/24))
        for k,name in enumerate(columns)},index=index)


def _pv(total,scale=1.0) -> pd.DataFrame:
    """Rooftop PV (positive output) of every column but the last"""
    hour = np.arange(len(total))
    shape = np.clip(np.sin(2*np.pi*((hour-14)%24)/24),0,None)
    return pd.DataFrame({name:scale*20*(k+1)*shape for k,name in enumerate(total.columns[:-1])},index=total.index)


@pytest.fixture(scope="module")
def total():
    """July-August 2020 total load of three counties"""
    return _panel(COUNTIES)


@pytest.fixture(scope="module")
def pv(total):
    """PV of the first two counties"""
    return _pv(total)


def check_panel(result,data,dg):
    """Same shape; total = net + |dg|"""
    assert list(result.columns) == list(data.columns) and result.index.equals(data.index)
    dg = 0.0 if dg is None else dg.reindex(columns=data.columns).fillna(0.0).abs()
    assert np.allclose(result.total - result.net,dg)


# --- columns -------------------------------------------------------------------

def test_columns(total):
    """Columns must be 'County ST' names or geohashes"""
    mixed = _panel(COUNTIES[:2] + NODES)
    result = CalibrateTotal(mixed,CalibrateConfig(energy=mixed.sum().to_dict()))
    assert result.counties == COUNTIES[:2] and result.geohashes == NODES
    for bad in ("Alamda CA","Alameda","total_MW","9q9p1a"):
        with pytest.raises(CalibrationError,match="County ST"):
            CalibrateTotal(total.rename(columns={"Washoe NV":bad}),CalibrateConfig(energy=1.0))


# --- energy --------------------------------------------------------------------

def test_total_energy(total,pv):
    """Unit energy targets: total without DG, net with DG"""
    targets = (1.1*total.sum()).to_dict()
    result = CalibrateTotal(total,CalibrateConfig(energy=targets))
    assert result.method is CalibrateEnergy and result.dg is None
    check_panel(result,total,None)
    assert np.allclose(result.sum(),pd.Series(targets))
    result = CalibrateTotal(total,CalibrateConfig(energy=targets,dg=pv))
    check_panel(result,total,pv)
    assert np.allclose(result.net.sum(),pd.Series(targets))
    assert np.allclose(result / total,result.calibration.scale)  # only the total is scaled


def test_net_energy_monthly(total,pv):
    """Monthly net energy of a net panel, with the DG held fixed"""
    net = total - pv.reindex(columns=total.columns).fillna(0.0)
    monthly = net.resample("1MS").sum() * 1.05
    result = CalibrateNet(net,CalibrateConfig(energy=monthly,dg=pv))
    check_panel(result,net,pv)
    assert np.allclose(result.resample("1MS").sum(),monthly)
    assert np.allclose(result.uncalibrated,net)


@pytest.mark.parametrize("scale",[1.0,1.5])
def test_dg_indifferent(total,scale):
    """Any DG is held fixed: scaled or not, either sign"""
    dg = _pv(total,scale)
    net = total - dg.reindex(columns=total.columns).fillna(0.0)
    targets = (1.05*net.sum()).to_dict()
    positive = CalibrateNet(net,CalibrateConfig(energy=targets,dg=dg))
    negative = CalibrateNet(net,CalibrateConfig(energy=targets,dg=-dg))
    assert np.allclose(positive,negative)
    assert np.allclose(positive.sum(),pd.Series(targets))
    assert np.allclose(positive.total - positive,dg.reindex(columns=total.columns).fillna(0.0))


# --- energy and peak -----------------------------------------------------------

def test_energy_peak_counties(total,pv):
    """State energy and a regional peak over a county panel"""
    august = total.loc["2020-08"]
    dg = pv.loc["2020-08"]
    net = august - dg.reindex(columns=august.columns).fillna(0.0)
    energy = {"CA":1.03*net[COUNTIES[:2]].sum().sum(),"NV":1.03*net["Washoe NV"].sum()}
    peak = {"ALL":1.01*net.sum(axis=1).max()}
    result = CalibrateTotal(august,CalibrateConfig(energy=energy,peak=peak,dg=dg,energy_weight=1.0e4))
    assert result.method is CalibrateEnergyPeak
    check_panel(result,august,dg)
    assert result.net.sum(axis=1).max() <= peak["ALL"]*(1+1e-6)
    assert np.allclose(result.calibration.states.shaped_error.abs(),0.0,atol=1e-2)


def test_energy_peak_geohashes():
    """Geohash columns need the states option"""
    nodes = _panel(NODES,"2020-08-01","2020-08-31")
    energy = {"CA":1.02*nodes.sum().sum()}
    peak = {"ALL":1.01*nodes.sum(axis=1).max()}
    with pytest.raises(CalibrationError,match="states"):
        CalibrateTotal(nodes,CalibrateConfig(energy=energy,peak=peak))
    states = pd.DataFrame({"CA":[1.0,1.0]},index=NODES)
    result = CalibrateTotal(nodes,CalibrateConfig(energy=energy,peak=peak,states=states,energy_weight=1.0e4))
    assert result.sum(axis=1).max() <= peak["ALL"]*(1+1e-6)


# --- peaks and troughs ---------------------------------------------------------

def test_net_peaks(total,pv):
    """Daily peaks and troughs of the panel's net load sum"""
    net = total - pv.reindex(columns=total.columns).fillna(0.0)
    daily = net.sum(axis=1).resample("1D")
    peaks = pd.DataFrame({"max":daily.max()*1.1,"min":daily.min()*0.9})
    result = CalibrateNet(net,CalibrateConfig(peaks=peaks,dg=pv))
    assert result.method is CalibratePeaks
    check_panel(result,net,pv)
    out = result.sum(axis=1).resample("1D")
    assert np.allclose(out.max(),peaks["max"]) and np.allclose(out.min(),peaks["min"])
    result = CalibrateTotal(total,CalibrateConfig(peaks=peaks,dg=pv,peak=0.95,trough=0.05))
    assert (result.calibration.parameters.fraction_above <= 0.05 + 1e-12).all()


# --- hourly demand -------------------------------------------------------------

def test_hourly_single_series(total,pv):
    """One demand series shared by all units, net of the DG"""
    net = total - pv.reindex(columns=total.columns).fillna(0.0)
    demand = 1.1*net.sum(axis=1)
    result = CalibrateTotal(total,CalibrateConfig(demand=demand,dg=pv))
    assert result.method is CalibrateHourly
    check_panel(result,total,pv)
    assert np.allclose(result.net.sum(axis=1),demand)


def test_hourly_factors(total,pv):
    """Demand by balancing authority with participation factors"""
    factors = pd.DataFrame({"county_st":COUNTIES+["Washoe NV"],"ba":["CISO","CISO","NEVP","SWPP"],
        "factor":[1.0,1.0,0.9,0.1]})
    net = total - pv.reindex(columns=total.columns).fillna(0.0)
    demand = pd.DataFrame({"CISO":1.1*net[COUNTIES[:2]].sum(axis=1),"NEVP":0.8*net["Washoe NV"]})
    result = CalibrateNet(net,CalibrateConfig(demand=demand,factors=factors,dg=pv))
    check_panel(result,net,pv)
    assert np.allclose(result[COUNTIES[:2]].sum(axis=1),demand["CISO"])
    assert np.allclose(result["Washoe NV"],demand["NEVP"] + 0.1*net["Washoe NV"])
    assert result.calibration.uncalibrated == ["SWPP"]
    with pytest.raises(CalibrationError,match="one column per balancing authority"):
        CalibrateNet(net,CalibrateConfig(demand=demand["CISO"],factors=factors,dg=pv))
    with pytest.raises(CalibrationError,match="frame by balancing authority"):
        CalibrateNet(net,CalibrateConfig(demand=demand,dg=pv))


# --- errors ----------------------------------------------------------------------

def test_errors(total,pv):
    """Invalid inputs raise CalibrationError"""
    config = CalibrateConfig(energy=total.sum().to_dict())
    with pytest.raises(CalibrationError,match="CalibrateConfig"):
        CalibrateTotal(total,None)
    with pytest.raises(CalibrationError,match="indexed by timestamp"):
        CalibrateTotal(total.reset_index(drop=True),config)
    with pytest.raises(CalibrationError,match="lag-window"):
        CalibrateTotal(total.where(total > total.iloc[0,0]),config)
    with pytest.raises(CalibrationError,match="every column"):
        CalibrateTotal(total,CalibrateConfig(energy=total.sum().to_dict(),basis="Alameda CA"))
    with pytest.raises(CalibrationError,match="not in data"):
        CalibrateTotal(total,CalibrateConfig(energy=total.sum().to_dict(),dg=pv.assign(**{"Kern CA":0.0})))
    with pytest.raises(CalibrationError,match="same sign"):
        CalibrateTotal(total,CalibrateConfig(energy=total.sum().to_dict(),dg=pv - 1))
    with pytest.raises(CalibrationError,match="give demand"):
        CalibrateConfig(energy=1.0,factors=pd.DataFrame())
    negative = total - 3*pv.reindex(columns=total.columns).fillna(0.0)
    with pytest.raises(CalibrationError,match="nonnegative"):
        CalibrateNet(negative,CalibrateConfig(energy=total.sum().to_dict()))  # net without dg


def test_calibrate_rejects_panel_inputs(total,pv):
    """Calibrate (one frame) takes DG from its frame, and has no factors or states"""
    frame = pd.DataFrame({"elec_total_MW":total["Alameda CA"]})
    with pytest.raises(CalibrationError,match="config.dg"):
        Calibrate(frame,CalibrateConfig(energy=1.0e6,dg=pv))
    with pytest.raises(CalibrationError,match="config.factors"):
        Calibrate(frame,CalibrateConfig(demand=frame["elec_total_MW"],factors=pd.DataFrame()))
    with pytest.raises(CalibrationError,match="not of Calibrate"):
        Calibrate(frame.loc["2020-08"],CalibrateConfig(energy=1.0e6,peak=1.0e3,states=pd.DataFrame()))
