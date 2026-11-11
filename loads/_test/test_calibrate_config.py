"""Calibration configuration and dispatch tests on synthetic data

These tests need no data downloads or cache and run in seconds (the energy
and peak case solves one small program). They check that
`loads.calibrate.CalibrateConfig` chooses the calibration from the data it
is given, holds the options of that calibration, and that
`loads.calibrate.Calibrate` returns a standard `loads` frame (here shaped
like a `Total` training frame) with the same columns, calibrated.
"""

# pylint: disable=redefined-outer-name
import numpy as np
import pandas as pd
import pytest

from loads.calibrate import (Calibrate, CalibrateConfig, CalibrationError,
    CalibrateEnergy, CalibrateEnergyPeak, CalibratePeaks, CalibrateHourly)

SECTORS = ["elec_residential_MW","elec_commercial_MW","elec_industrial_MW",
    "elec_agricultural_MW","elec_transportation_MW"]


def _total(start:str,end:str) -> pd.DataFrame:
    """Synthetic `Total`-like frame: sectors, total, DG (<= 0), net and weather"""
    index = pd.date_range(f"{start} 00:00:00+00:00",f"{end} 23:00:00+00:00",freq="1h",name="timestamp")
    hour = np.arange(len(index))
    data = pd.DataFrame({
        "elec_residential_MW":60*(1.4+np.sin(2*np.pi*(hour-18)/24)),
        "elec_commercial_MW":50*(1.3+np.sin(2*np.pi*(hour-14)/24)),
        "elec_industrial_MW":30.0,
        "elec_agricultural_MW":5.0,
        "elec_transportation_MW":0.0,
        },index=index)
    data["elec_total_MW"] = data[SECTORS].sum(axis=1)
    data["elec_dg_MW"] = -25*np.clip(np.sin(2*np.pi*(hour-14)/24),0,None)
    data["elec_net_MW"] = data["elec_total_MW"] + data["elec_dg_MW"]
    data["temperature_degF"] = 70 + 10*np.sin(2*np.pi*(hour-15)/24)
    data["humidity_pc"] = 50.0
    return data


@pytest.fixture(scope="module")
def total() -> pd.DataFrame:
    """July and August 2020"""
    return _total("2020-07-01","2020-08-31")


@pytest.fixture(scope="module")
def august() -> pd.DataFrame:
    """August 2020 only"""
    return _total("2020-08-01","2020-08-31")


def check_identities(result,data):
    """Same frame shape; DG and weather unchanged; sectors sum to total; net = total - |dg|"""
    assert list(result.columns) == list(data.columns)
    assert result.index.equals(data.index)
    assert isinstance(result,Calibrate)
    assert np.allclose(result["elec_dg_MW"],data["elec_dg_MW"])
    assert np.allclose(result[["temperature_degF","humidity_pc"]],data[["temperature_degF","humidity_pc"]])
    assert np.allclose(result[SECTORS].sum(axis=1),result["elec_total_MW"])
    assert np.allclose(result["elec_net_MW"],result["elec_total_MW"] - np.abs(result["elec_dg_MW"]))


# --- method selection --------------------------------------------------------

def test_method_selection(total):
    """The data given chooses the calibration"""
    peaks = pd.DataFrame({"max":[1.0],"min":[0.0]},index=total.index[:1])
    assert CalibrateConfig(energy=1.0).method is CalibrateEnergy
    assert CalibrateConfig(energy=1.0,peak=2.0).method is CalibrateEnergyPeak
    assert CalibrateConfig(peaks=peaks).method is CalibratePeaks
    assert CalibrateConfig(peaks=peaks,peak=0.95).method is CalibratePeaks
    assert CalibrateConfig(demand=total["elec_net_MW"]).method is CalibrateHourly


@pytest.mark.parametrize("data,match",[
    ({},"no calibration data"),
    ({"peak":1.0},"needs energy"),
    ({"energy":1.0,"demand":pd.Series(dtype=float)},"demand selects"),
    ({"energy":1.0,"peaks":pd.DataFrame()},"peaks selects"),
    ])
def test_unsupported_data(data,match):
    """Data that supports no calibration raises CalibrationError"""
    with pytest.raises(CalibrationError,match=match):
        CalibrateConfig(**data)


def test_data_changed_after_construction(total):
    """Changing the data changes the method; unsupported data raises when used"""
    config = CalibrateConfig(energy=1.0)
    config.peak = 2.0
    assert config.method is CalibrateEnergyPeak
    config.energy = None
    with pytest.raises(CalibrationError,match="needs energy"):
        Calibrate(total,config)


# --- options -----------------------------------------------------------------

def test_options():
    """Options are given at construction, have the class defaults, and can be changed"""
    config = CalibrateConfig(energy=1.0,peak=2.0,search=True)
    assert config.search is True
    assert config.shape_weight == 1.0  # CalibrateEnergyPeak default
    config.shape_weight = 2.0
    assert config.options == {"search":True,"shape_weight":2.0}
    del config.shape_weight
    assert config.options == {"search":True}
    assert "progress" in config.option_names() and "dg" not in config.option_names()
    assert "method=CalibrateEnergyPeak" in repr(config)


def test_option_errors():
    """Options the chosen calibration doesn't have raise CalibrationError"""
    with pytest.raises(CalibrationError,match="not an option"):
        CalibrateConfig(energy=1.0,search=True)
    with pytest.raises(CalibrationError,match="set by Calibrate"):
        CalibrateConfig(energy=1.0,dg=None)
    config = CalibrateConfig(energy=1.0)
    with pytest.raises(CalibrationError,match="not an option"):
        config.trough = 0.1
    config = CalibrateConfig(energy=1.0,peak=2.0,search=True)
    config.peak = None
    with pytest.raises(CalibrationError,match="not options"):
        _ = config.options


def test_peaks_options(total):
    """With peaks, peak and trough are the CalibratePeaks percentiles"""
    peaks = pd.DataFrame({"max":[1.0],"min":[0.0]},index=total.index[:1])
    config = CalibrateConfig(peaks=peaks,peak=0.95,trough=0.05)
    assert config.options == {"trough":0.05,"peak":0.95}
    config.trough = 0.1
    assert config.trough == 0.1


# --- calibration of a standard frame -------------------------------------------

def test_energy(total):
    """Monthly net energy is matched; the shape within a month is kept"""
    monthly = total["elec_net_MW"].resample("1MS").sum() * [1.05,0.95]
    result = Calibrate(total,CalibrateConfig(energy=monthly))
    assert result.method is CalibrateEnergy and result.basis == "elec_net_MW"
    check_identities(result,total)
    assert np.allclose(result["elec_net_MW"].resample("1MS").sum(),monthly)
    july = result.index.month == 7
    ratio = result.loc[july,SECTORS[:2]] / total.loc[july,SECTORS[:2]]
    assert np.allclose(ratio.std(),0.0)  # one gross-load scale for the month
    assert np.allclose(result.calibration.net["load"],result["elec_net_MW"])
    assert result.uncalibrated is total


def test_energy_whole_period_total_basis(total):
    """A number is the energy of the whole period; basis total ignores the DG"""
    target = 1.1 * total["elec_total_MW"].sum()
    result = Calibrate(total,CalibrateConfig(energy=target,basis="elec_total_MW"))
    check_identities(result,total)
    assert np.isclose(result["elec_total_MW"].sum(),target)
    assert np.allclose(result[SECTORS[:2]],1.1 * total[SECTORS[:2]])


def test_energy_peak(august):
    """Monthly net energy and peak targets for a single month"""
    net = august["elec_net_MW"]
    energy,peak = 1.04 * net.sum(),1.02 * net.max()
    result = Calibrate(august,CalibrateConfig(energy=energy,peak=peak,energy_weight=1.0e4))
    assert result.method is CalibrateEnergyPeak
    check_identities(result,august)
    assert result["elec_net_MW"].max() <= peak * (1 + 1e-6)
    assert np.isclose(result["elec_net_MW"].sum(),energy,rtol=1e-2)
    assert len(result.calibration.summary) == 1


def test_energy_peak_monthly(total):
    """Monthly series of energy and peak targets span months"""
    net = total["elec_net_MW"]
    energy = net.resample("1MS").sum() * 1.03
    peak = net.resample("1MS").max() * 1.01
    result = Calibrate(total,CalibrateConfig(energy=energy,peak=peak,energy_weight=1.0e4))
    check_identities(result,total)
    assert (result["elec_net_MW"].resample("1MS").max() <= peak * (1 + 1e-6)).all()
    with pytest.raises(CalibrationError,match="applies to every month"):
        Calibrate(total,CalibrateConfig(energy=float(energy.sum()),peak=float(peak.max())))


@pytest.mark.parametrize("peak,trough",[(1.0,0.0),(0.95,0.05)])
def test_peaks(total,peak,trough):
    """Daily net peaks and troughs are matched with the DG fixed"""
    daily = total["elec_net_MW"].resample("1D")
    peaks = pd.DataFrame({"max":daily.max()*1.1,"min":daily.min()*0.9})
    result = Calibrate(total,CalibrateConfig(peaks=peaks,peak=peak,trough=trough))
    assert result.method is CalibratePeaks
    check_identities(result,total)
    params = result.calibration.parameters
    assert (params.fraction_above <= 1 - peak + 1e-12).all()
    assert (params.fraction_below <= trough + 1e-12).all()
    if peak == 1.0:
        out = result["elec_net_MW"].resample("1D")
        assert np.allclose(out.max(),peaks["max"]) and np.allclose(out.min(),peaks["min"])


def test_hourly(total):
    """Every hour of demand is matched by the net load"""
    demand = total["elec_net_MW"] * (1.1 + 0.05*np.sin(np.arange(len(total))/50))
    result = Calibrate(total,CalibrateConfig(demand=demand))
    assert result.method is CalibrateHourly
    check_identities(result,total)
    assert np.allclose(result["elec_net_MW"],demand)


def test_hourly_missing(total):
    """Missing demand hours are NaN unless missing='keep'"""
    demand = total["elec_net_MW"] * 1.1
    demand.iloc[5] = np.nan
    result = Calibrate(total,CalibrateConfig(demand=demand))
    assert result["elec_net_MW"].isna().sum() == 1 and result[SECTORS].iloc[5].isna().all()
    config = CalibrateConfig(demand=demand,missing="keep")
    result = Calibrate(total,config)
    assert np.isclose(result["elec_net_MW"].iloc[5],total["elec_net_MW"].iloc[5])


def test_estimator_frame(august):
    """An Estimator-like frame (weather and elec_total_MW) calibrates its total"""
    data = august[["temperature_degF","humidity_pc","elec_total_MW"]]
    result = Calibrate(data,CalibrateConfig(energy=2*data["elec_total_MW"].sum()))
    assert result.basis == "elec_total_MW"
    assert np.allclose(result["elec_total_MW"],2*data["elec_total_MW"])
    assert np.allclose(result[["temperature_degF","humidity_pc"]],data[["temperature_degF","humidity_pc"]])


def test_other_basis(august):
    """A basis that isn't a total or net column is calibrated alone"""
    data = august[["temperature_degF"]].assign(prediction=august["elec_total_MW"])
    result = Calibrate(data,CalibrateConfig(energy=3*data["prediction"].sum(),basis="prediction"))
    assert np.allclose(result["prediction"],3*data["prediction"])


def test_zero_gross_hours(august):
    """Hours without gross load share the calibrated load by mean sector share"""
    data = august.copy()
    data.iloc[:3,:] = 0.0
    daily = data["elec_net_MW"].resample("1D")
    peaks = pd.DataFrame({"max":daily.max()*1.1,"min":daily.min()+1.0})
    result = Calibrate(data,CalibrateConfig(peaks=peaks,basis="elec_total_MW"))
    assert np.allclose(result[SECTORS].sum(axis=1),result["elec_total_MW"])
    assert (result["elec_total_MW"].iloc[:3] > 0).all()


def test_calibrate_errors(total):
    """Invalid data raise CalibrationError"""
    config = CalibrateConfig(energy=1.0e6)
    with pytest.raises(CalibrationError,match="CalibrateConfig"):
        Calibrate(total,{"energy":1.0e6})
    with pytest.raises(CalibrationError,match="indexed by timestamp"):
        Calibrate(total.reset_index(drop=True),config)
    with pytest.raises(CalibrationError,match="set the basis"):
        Calibrate(total[SECTORS[:2]],config)
    with pytest.raises(CalibrationError,match="no basis column"):
        Calibrate(total,CalibrateConfig(energy=1.0e6,basis="elec_peak_MW"))
    edges = total.copy()
    edges.iloc[:3,edges.columns.get_loc("elec_net_MW")] = np.nan
    with pytest.raises(CalibrationError,match="lag-window"):
        Calibrate(edges,config)
    with pytest.raises(CalibrationError,match="hourly series"):
        Calibrate(total,CalibrateConfig(demand=1.0))
