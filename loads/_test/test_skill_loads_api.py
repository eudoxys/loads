"""Guard the facts the agent skill (`loads/skill/`) documents about `loads`

These tests import `loads` but touch no network. Each one pins a behavior
that `loads/skill/SKILL.md` or `loads/skill/reference/` describes. If one
fails after a change to `loads`, update the skill documentation (and
`loads.skill.schema`) in the same change to describe the new behavior; do not
just relax the test.
"""

import inspect
import os

import numpy as np
import pandas as pd
import pytest

import loads
from loads.skill import schema


def params(fn):
    return inspect.signature(fn).parameters


# --- Total ---------------------------------------------------------------------

def test_total_signature():
    p = params(loads.Total.__init__)
    assert list(p)[:3] == ["self", "state", "county"]
    for name in ("Y", "X", "date_range", "samples", "percentile", "refresh"):
        assert p[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert "year" not in p  # footguns.md #1: no year argument
    assert p["samples"].default is None and p["percentile"].default == 96


def test_cli_year_is_dropped_for_total():
    # footguns.md #3: makeargs keeps only annotated __init__ args; Total has no `year`
    assert "year" not in loads.Total.makeargs(state="CA", county="Alameda", year=2020)


def test_total_constants_match_schema():
    assert loads.Total.TRAINING_YEAR == schema.TRAINING_YEAR
    assert {k: tuple(v) for k, v in loads.Total.EXOGENOUS_VARIABLES.items()} == schema.PREDICTABLE_TARGETS
    lags = [l for c in loads.Total.TSGAM_CONFIG.exog_config for l in getattr(c, "lags", [])]
    assert tuple(sorted(set(lags))) == schema.TSGAM_LAGS


def test_total_positional_year_raises():
    with pytest.raises(TypeError):
        loads.Total("CA", "Alameda", 2020)


# --- sector models --------------------------------------------------------------

def test_building_types_match_schema():
    assert set(loads.RESstock.BUILDING_TYPES) == set(schema.RESIDENTIAL_BUILDING_TYPES)
    assert set(loads.COMstock.BUILDING_TYPES) == set(schema.COMMERCIAL_BUILDING_TYPES)


def test_sector_models_keyword_only_after_county():
    for cls in (loads.Residential, loads.Commercial):
        p = params(cls.__init__)
        assert p["refresh"].kind is inspect.Parameter.KEYWORD_ONLY
        assert "year" not in p  # 2018 only


# --- Calibrate -------------------------------------------------------------------

def _panel(months=("2020-07",), units=("Alameda CA", "Kern CA", "Washoe NV")):
    idx = pd.DatetimeIndex([], tz="UTC")
    for m in months:
        start = pd.Timestamp(f"{m}-01", tz="UTC")
        idx = idx.append(pd.date_range(start, start + pd.offsets.MonthEnd(0) + pd.Timedelta(hours=23),
                                       freq="1h"))
    h = np.arange(len(idx))
    X = pd.DataFrame({u: 100 * (k + 1) * (1.5 + np.sin(2 * np.pi * (h % 24) / 24))
                      for k, u in enumerate(units)}, index=idx.rename("timestamp"))
    D = pd.DataFrame({u: 10 * (k + 1) * np.clip(np.sin(2 * np.pi * ((h - 14) % 24) / 24), 0, None)
                      for k, u in enumerate(units)}, index=X.index)
    net = X - D
    energy = {st: float(net[[u for u in units if u.endswith(st)]].sum().sum()) * 1.03 for st in ("CA", "NV")}
    peak = {"ALL": float(net.sum(axis=1).max()) * 1.01}
    return X, D, energy, peak


def test_calibrate_signature():
    p = params(loads.Calibrate.__init__)
    for name in ("energy", "peak"):
        assert p[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert p[name].default is inspect.Parameter.empty  # both required
    assert {"dg", "states", "regions", "search", "progress"} <= set(p)
    from loads.calibrate import CalibrationError  # noqa: F401
    import loads.calibrate as cal
    assert not hasattr(cal, "fit_load") and not hasattr(loads.Calibrate, "load")


def test_calibrate_dg_must_be_positive_output():
    from loads.calibrate import CalibrationError
    X, D, energy, peak = _panel()
    with pytest.raises(CalibrationError, match="nonnegative"):
        loads.Calibrate(X, energy=energy, peak=peak, dg=-D)  # elec_dg_MW convention is rejected
    out = loads.Calibrate(X, energy=energy, peak=peak, dg=D)
    assert out.shape == X.shape and np.allclose(out.net, out - D)


def test_calibrate_rejects_nan_edges():
    from loads.calibrate import CalibrationError
    X, D, energy, peak = _panel()
    X.iloc[:3] = np.nan  # Total's lag window
    with pytest.raises(CalibrationError, match="missing"):
        loads.Calibrate(X, energy=energy, peak=peak, dg=D)


def test_calibrate_without_peak_regions_raises():
    # footguns.md: energy-only calibration (peak={}) fails building the region table
    X, D, energy, _ = _panel()
    with pytest.raises(KeyError):
        loads.Calibrate(X, energy=energy, peak={}, dg=D)


def test_calibrate_is_affine_per_utc_month():
    X, D, energy, peak = _panel(months=("2020-07", "2020-08"))
    out = loads.Calibrate(X, energy=energy, peak=peak, dg=D)  # same targets for both months
    assert len(out.summary) == 2  # one block per UTC calendar month
    par = out.parameters.reset_index()
    for (block, unit), row in out.parameters.iterrows():
        rows = X.index.tz_convert("UTC").tz_localize(None).to_period("M") == block.tz_localize(None).to_period("M")
        assert np.allclose(out.loc[rows, unit], row.scale * X.loc[rows, unit] + row.offset_MW)
    assert par.offset_MW.abs().max() > 0  # an offset, not a proportional rescale


def test_cast_module_removed():
    with pytest.raises(ModuleNotFoundError):
        __import__("loads.cast")


# --- Estimator, Energy, DG ---------------------------------------------------------

def test_estimator_uses_county_st():
    p = params(loads.Estimator.__init__)
    assert list(p)[1] == "county_st"
    from loads.estimator import EstimatorConfig
    assert EstimatorConfig().log is True and EstimatorConfig().holdout == "5d"
    assert EstimatorConfig().fold == 0 and "fold" in EstimatorConfig._fields  # #38 folds


def test_estimator_fold_groups():
    # #38: fold=0 is the old every-Nth-interval holdout; fold=k shifts it by k
    from loads.estimator import EstimatorError, _get_holdout
    idx = pd.date_range("2018-01-01", "2018-01-10 23:00", freq="1h", tz="UTC")
    frame = pd.DataFrame({"x": 0.0}, index=idx)
    days = lambda k: sorted({t.day for t in _get_holdout(frame, "5d", k)})
    assert days(0) == [4, 9] and days(1) == [5, 10]  # ndx is the 1-based day of year
    with pytest.raises(EstimatorError):
        _get_holdout(frame, "5d", 5)


# --- Normalize ---------------------------------------------------------------------

def _meters():
    t = pd.date_range("2020-01-01", periods=8, freq="15min")  # two hours of 15-min kWh
    return pd.DataFrame({"t": list(t) * 2, "m": ["a"] * 8 + ["b"] * 8, "kwh": [1.0] * 8 + [3.0] * 8})


def test_normalize_signature_and_required_args():
    p = params(loads.Normalize.__init__)
    assert list(p)[1] == "source"
    assert all(p[k].kind is inspect.Parameter.KEYWORD_ONLY
               for k in ("timestamps", "timezone", "scales", "mapping", "groups", "weather"))
    with pytest.raises(ValueError):
        loads.Normalize(_meters(), mapping={"elec_net_MW": "kwh"})
    with pytest.raises(ValueError):
        loads.Normalize(_meters(), timestamps={"t": pd.DatetimeIndex})


def test_normalize_averages_rows_within_an_hour():
    # footguns.md #31/#32: ungrouped rows are averaged across units, and
    # sub-hourly energy is averaged per interval (not summed to hourly energy)
    args = dict(timestamps={"t": pd.DatetimeIndex}, mapping={"elec_net_MW": "kwh"}, scales={"kwh": 1e-3})
    flat = loads.Normalize(_meters(), **args)
    assert str(flat.index.tz) == "UTC" and len(flat) == 2
    assert np.allclose(flat.elec_net_MW, 0.002)       # mean of meters (sum would be 0.004)
    grouped = loads.Normalize(_meters(), groups={"kwh": "m"}, **args)
    assert grouped.index.names == ["m", "timestamp"]
    assert np.allclose(grouped.xs("a").elec_net_MW, 0.001)  # 4 kWh/h is 0.004 MW
    total = grouped.groupby(level="timestamp").sum()
    assert np.allclose(total.elec_net_MW, 0.004)       # sum of per-meter means"


def test_energy_needs_year_sequence():
    p = params(loads.Energy.__init__)
    assert list(p)[1:4] == ["state", "counties", "year"]


def test_energy_int_year_fails(tmp_path, monkeypatch):
    from cache import Cache
    monkeypatch.setattr(Cache, "CACHEDIR", str(tmp_path))
    with pytest.raises(TypeError):
        loads.Energy("NV", "Esmeralda", 2019)


def _stub_dg(monkeypatch, tmp_path, state="CA", tot_mwh=1000.0):
    """Stub the EIA download and the NSRDB profile of `loads.dgen.DG`"""
    import loads.dgen as dgen
    from cache import Cache
    monkeypatch.setattr(Cache, "CACHEDIR", str(tmp_path))
    monkeypatch.setattr(dgen.SmallScaleSolar, "_data", {})

    def eia(cls, year, refresh):
        months = pd.period_range(f"{year}-01", f"{year}-12", freq="M")
        index = pd.MultiIndex.from_product([months, [state]], names=["month", "state"])
        frame = pd.DataFrame(0.0, index=index, columns=dgen.SmallScaleSolar.COLUMNS)
        frame["tot_mwh"] = tot_mwh
        return frame

    def profile(cls, state, county, year, profile):
        index = dgen.DG._year_range(year)
        hour = index.hour.to_numpy()
        return pd.Series(np.clip(np.sin(np.pi * (hour - 14) / 12), 0, None), index=index)

    monkeypatch.setattr(dgen.SmallScaleSolar, "_get_eia", classmethod(eia))
    monkeypatch.setattr(dgen.DG, "_get_profile", classmethod(profile))
    return dgen


def test_dg_signature():
    p = params(loads.DG.__init__)
    assert list(p)[1:4] == ["state", "county", "date_range"]
    assert p["profile"].default == "weather" and p["source"].default is None
    assert loads.DG.PROFILES == ["weather", "dgen"]


def test_dg_is_eia_allocated_negative_load(monkeypatch, tmp_path):
    # #43: DG allocates EIA-861M state small-scale PV by county share of state energy use
    dgen = _stub_dg(monkeypatch, tmp_path)
    july = pd.date_range("2020-07-01", "2020-07-31 23:00", freq="1h", tz="UTC")
    dg = dgen.DG("CA", "Alameda", date_range=july)
    assert list(dg.columns) == ["elec_dg_MW"] and len(dg) == len(july)
    assert (dg.elec_dg_MW <= 0).all() and dg.elec_dg_MW.min() < 0
    share = dgen.DG._get_share("CA", "Alameda", pd.PeriodIndex(["2020-07"], freq="M")).iloc[0]
    assert np.isclose(-dg.elec_dg_MW.sum(), 1000.0 * share, rtol=1e-4)


def test_dg_outside_county_mwh_is_zero(monkeypatch, tmp_path):
    dgen = _stub_dg(monkeypatch, tmp_path, state="IL")
    with pytest.warns(UserWarning, match="no DG allocated"):
        dg = dgen.DG("IL", "Cook", date_range=pd.date_range("2020-07-01", periods=48, freq="1h", tz="UTC"))
    assert (dg.elec_dg_MW == 0).all()


def test_total_dg_option_rules():
    p = params(loads.Total.__init__)
    assert p["dg"].default is False
    assert "dg" in loads.Total.makeargs(state="CA", county="Alameda", dg=True)  # CLI -G reaches Total
    assert loads.Total.DG_PROFILE == "weather" and loads.Total.DG_SOURCE is None
    with pytest.raises(ValueError):
        loads.Total("CA", "Alameda", Y="nonelec_total_MW", dg=True)
    with pytest.raises(ValueError):
        loads.Total("CA", "Alameda", Y="elec_net_MW", samples=0, dg=True,
                    date_range=pd.date_range("2020-01-01", periods=24, freq="1h", tz="UTC"))


def test_growth_not_wired_into_sector_models():
    # #19: Units/Floorarea grow outside their data years, but the sector models
    # still ask for the 2018/2019 base, so Total predictions carry no growth
    import loads.residential as res
    import loads.commercial as com
    assert "year=2018)" in inspect.getsource(res.Residential.__init__)
    assert "backcast" not in inspect.getsource(res.Residential.__init__)
    assert "Floorarea(state=state,county=county)" in inspect.getsource(com.Commercial.__init__)
    assert loads.Units.GROWTH_RATE == 0.01 and loads.Floorarea.GROWTH_RATE == 0.0175
    assert params(loads.Units.__new__)["backcast"].default is False


def test_bundled_dg_files_are_positive_output():
    source = os.path.join(os.path.dirname(loads.__file__), "wecc", "county_dg.csv.gz")
    if not os.path.exists(source):
        pytest.skip("loads/wecc data files are not installed")
    head = pd.read_csv(source, index_col=0, nrows=24 * 200)
    assert (head.values >= 0).all() and head.values.max() > 0  # opposite to elec_dg_MW <= 0
