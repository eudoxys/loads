"""Peak and trough calibration tests on synthetic data

These tests need no data downloads or cache and run in seconds. They check
`loads.calibrate.CalibratePeaks` on a synthetic hourly load calibrated to
daily observed peaks and troughs.
"""

# pylint: disable=redefined-outer-name
import numpy as np
import pandas as pd
import pytest

from loads.calibrate import CalibratePeaks, CalibrationError


@pytest.fixture(scope="module")
def load() -> pd.DataFrame:
    """Two-column synthetic hourly load for August 2020"""
    rng = np.random.default_rng(2)
    index = pd.date_range("2020-08-01 00:00:00+00:00","2020-08-31 23:00:00+00:00",freq="1h",name="timestamp")
    hour = np.arange(len(index))
    return pd.DataFrame({
        "A CA":100*(1+0.3*np.sin(2*np.pi*hour/24)) + 5*rng.random(len(hour)),
        "B NV":40*(1+0.2*np.sin(2*np.pi*(hour+3)/24)) + 2*rng.random(len(hour)),
        },index=index)


@pytest.fixture(scope="module")
def peaks(load) -> pd.DataFrame:
    """Observed daily peaks and troughs, different from the load's"""
    days = pd.date_range("2020-08-01",periods=31,freq="1D",tz="UTC",name="timestamp")
    factor = np.linspace(1.1,1.3,len(days))
    daily = load.sum(axis=1).resample("1D")
    return pd.DataFrame({"max":daily.max().values*factor,"min":daily.min().values*0.9},index=days)


@pytest.mark.parametrize("peak,trough",[(1.0,0.0),(0.95,0.05),(0.9,0.2)])
def test_fractions(load,peaks,peak,trough):
    """No more than the specified fraction of each day is above the peak or below the trough"""
    result = CalibratePeaks(load,peaks,peak=peak,trough=trough)
    assert result.shape == load.shape
    assert result.calibrated.all()
    total = result.sum(axis=1)
    for day,row in peaks.iterrows():
        values = total[(total.index >= day) & (total.index < day + pd.Timedelta("1D"))]
        assert np.mean(values > row["max"] + 1e-9) <= 1 - peak + 1e-12
        assert np.mean(values < row["min"] - 1e-9) <= trough + 1e-12
    assert (result.parameters.fraction_above <= 1 - peak + 1e-12).all()
    assert (result.parameters.fraction_below <= trough + 1e-12).all()


def test_exact_extremes(load,peaks):
    """With the default percentiles the observed peak and trough are reproduced"""
    total = CalibratePeaks(load,peaks).sum(axis=1).resample("1D")
    assert np.allclose(total.max().values,peaks["max"].values)
    assert np.allclose(total.min().values,peaks["min"].values)


def test_affine_shape(load,peaks):
    """Each column is an affine map of the uncalibrated column within an interval"""
    result = CalibratePeaks(load,peaks,peak=0.95,trough=0.05)
    day = slice("2020-08-10","2020-08-10")
    for column in load.columns:
        x,y = load.loc[day,column].values,result.loc[day,column].values
        slope,intercept = np.polyfit(x,y,1)
        assert np.allclose(slope*x + intercept,y)
        assert np.isclose(slope,result.parameters.loc[pd.Timestamp("2020-08-10",tz="UTC"),"scale"])


def test_partial_coverage(load,peaks):
    """Hours outside the intervals or with missing targets are unchanged"""
    partial = peaks.iloc[5:10].copy()
    partial.iloc[2] = np.nan
    result = CalibratePeaks(load,partial,peak=0.95,trough=0.05)
    assert result.calibrated.sum() == 4*24
    unchanged = ~result.calibrated
    assert np.allclose(result[unchanged].values,load[unchanged].values)


def test_series_input(load,peaks):
    """A series load is accepted and returned as a one-column frame"""
    result = CalibratePeaks(load.sum(axis=1).rename("total"),peaks)
    assert list(result.columns) == ["total"]


@pytest.mark.parametrize("kwargs",[{"peak":0.5,"trough":0.5},{"peak":1.1},{"trough":-0.1}])
def test_invalid_percentiles(load,peaks,kwargs):
    """Percentiles must be ordered fractions"""
    with pytest.raises(CalibrationError):
        CalibratePeaks(load,peaks,**kwargs)


def test_invalid_peaks(load,peaks):
    """Peak data must have max and min columns with max >= min"""
    with pytest.raises(CalibrationError):
        CalibratePeaks(load,peaks[["max"]])
    with pytest.raises(CalibrationError):
        CalibratePeaks(load,peaks.rename(columns={"max":"min","min":"max"}))
