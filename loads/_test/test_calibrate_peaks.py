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
        "A_MW":100*(1+0.3*np.sin(2*np.pi*hour/24)) + 5*rng.random(len(hour)),
        "B_MW":40*(1+0.2*np.sin(2*np.pi*(hour+3)/24)) + 2*rng.random(len(hour)),
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
    result = CalibratePeaks(load.sum(axis=1).rename("total_MW"),peaks)
    assert list(result.columns) == ["total_MW"]


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


@pytest.fixture(scope="module")
def sectors(load) -> pd.DataFrame:
    """Load with a total column, its two parts, and a weather column"""
    frame = load.rename(columns={"A_MW":"elec_residential_MW","B_MW":"elec_commercial_MW"})
    frame["elec_total_MW"] = frame.sum(axis=1)
    frame["temperature_degF"] = 70 + 10*np.sin(2*np.pi*np.arange(len(frame))/24)
    return frame


def test_defaults_are_mw_columns(load,peaks):
    """With only _MW columns the defaults use their sum and calibrate them all"""
    default = CalibratePeaks(load,peaks,peak=0.95,trough=0.05)
    explicit = CalibratePeaks(load,peaks,peak=0.95,trough=0.05,
        basis=list(load.columns),columns=list(load.columns))
    pd.testing.assert_frame_equal(pd.DataFrame(default),pd.DataFrame(explicit))
    assert default.basis == list(load.columns)
    assert default.calibrated_columns == list(load.columns)


def test_defaults_skip_non_mw_columns(sectors,peaks):
    """The defaults use and calibrate only the columns whose names end in _MW"""
    frame = sectors.drop(columns="elec_total_MW")
    result = CalibratePeaks(frame,peaks)
    assert result.basis == ["elec_residential_MW","elec_commercial_MW"]
    assert result.calibrated_columns == result.basis
    pd.testing.assert_series_equal(result["temperature_degF"],frame["temperature_degF"])
    total = result[result.basis].sum(axis=1).resample("1D")
    assert np.allclose(total.max().values,peaks["max"].values)
    assert np.allclose(total.min().values,peaks["min"].values)


def test_defaults_need_mw_columns(load,peaks):
    """A frame with no _MW column needs explicit basis and columns"""
    frame = load.rename(columns={"A_MW":"A","B_MW":"B"})
    with pytest.raises(CalibrationError,match="_MW"):
        CalibratePeaks(frame,peaks)
    with pytest.raises(CalibrationError,match="_MW"):
        CalibratePeaks(frame,peaks,basis="A")
    result = CalibratePeaks(frame,peaks,basis=["A","B"],columns=["A","B"])
    assert np.allclose(result.values,CalibratePeaks(load,peaks).values)


def test_basis_column(sectors,peaks):
    """A single basis column is matched and its parts stay consistent"""
    parts = ["elec_residential_MW","elec_commercial_MW"]
    result = CalibratePeaks(sectors,peaks,peak=0.95,trough=0.05,
        basis="elec_total_MW",columns=parts+["elec_total_MW"])
    assert result.basis == ["elec_total_MW"]
    assert np.allclose(result[parts].sum(axis=1),result["elec_total_MW"])
    pd.testing.assert_series_equal(result["temperature_degF"],sectors["temperature_degF"])
    total = result["elec_total_MW"]
    for day,row in peaks.iterrows():
        values = total[(total.index >= day) & (total.index < day + pd.Timedelta("1D"))]
        assert np.mean(values > row["max"] + 1e-9) <= 0.05 + 1e-12
        assert np.mean(values < row["min"] - 1e-9) <= 0.05 + 1e-12
    # same as calibrating the parts on the sum of the parts
    plain = CalibratePeaks(sectors[parts],peaks,peak=0.95,trough=0.05)
    assert np.allclose(result[parts].values,plain.values)


def test_columns_subset(sectors,peaks):
    """Only the named columns change; the basis may be left uncalibrated"""
    result = CalibratePeaks(sectors,peaks,basis="elec_total_MW",columns="elec_residential_MW")
    assert result.calibrated_columns == ["elec_residential_MW"]
    for column in ["elec_commercial_MW","elec_total_MW","temperature_degF"]:
        pd.testing.assert_series_equal(result[column],sectors[column])
    day = slice("2020-08-10","2020-08-10")
    x,y = sectors.loc[day,"elec_residential_MW"].values,result.loc[day,"elec_residential_MW"].values
    slope,_ = np.polyfit(x,y,1)
    assert np.isclose(slope,result.parameters.loc[pd.Timestamp("2020-08-10",tz="UTC"),"scale"])


def test_basis_ignores_other_columns(sectors,peaks):
    """Non-numeric or missing values outside basis and columns are allowed"""
    frame = sectors.copy()
    frame["note"] = "x"
    frame.iloc[0,frame.columns.get_loc("temperature_degF")] = np.nan
    result = CalibratePeaks(frame,peaks,basis="elec_total_MW",columns="elec_total_MW")
    assert (result["note"] == "x").all()
    exact = result["elec_total_MW"].resample("1D")
    assert np.allclose(exact.max().values,peaks["max"].values)


@pytest.mark.parametrize("kwargs",[
    {"basis":"nope"},{"columns":["elec_total_MW","nope"]},{"basis":[]},
    {"columns":["elec_total_MW","elec_total_MW"]},{"basis":"note"},
    ])
def test_invalid_selection(sectors,peaks,kwargs):
    """Basis and columns must name distinct, existing, numeric columns"""
    frame = sectors.copy()
    frame["note"] = "x"
    with pytest.raises(CalibrationError):
        CalibratePeaks(frame,peaks,**kwargs)


def test_ba_net_load_with_fixed_dg(sectors,peaks):
    """BA reports are net load; known DG stays fixed and gross load is rebuilt"""
    parts = ["elec_residential_MW","elec_commercial_MW"]
    hour = np.arange(len(sectors))
    frame = sectors.copy()
    frame["elec_dg_MW"] = -20*np.clip(np.sin(2*np.pi*(hour-6)/24),0,None)
    frame["elec_net_MW"] = frame["elec_total_MW"] + frame["elec_dg_MW"]

    # documented usage: calibrate the net load alone, then rebuild gross load
    result = CalibratePeaks(frame,peaks,basis="elec_net_MW",columns="elec_net_MW")
    pd.testing.assert_series_equal(result["elec_dg_MW"],frame["elec_dg_MW"])
    net = result["elec_net_MW"].resample("1D")
    assert np.allclose(net.max().values,peaks["max"].values)
    assert np.allclose(net.min().values,peaks["min"].values)
    gross = result["elec_net_MW"] - result["elec_dg_MW"]
    result[parts] = frame[parts].mul(gross/frame["elec_total_MW"],axis=0)
    result["elec_total_MW"] = gross
    assert np.allclose(result[parts].sum(axis=1),result["elec_total_MW"])
    assert np.allclose(result["elec_total_MW"] + result["elec_dg_MW"],result["elec_net_MW"])

    # calibrating net and gross together breaks the net identity (documented caveat)
    both = CalibratePeaks(frame,peaks,basis="elec_net_MW",columns=parts+["elec_total_MW","elec_net_MW"])
    assert not np.allclose(both["elec_total_MW"] + both["elec_dg_MW"],both["elec_net_MW"])
