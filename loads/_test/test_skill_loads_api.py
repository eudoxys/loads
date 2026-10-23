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


def test_energy_needs_year_sequence():
    p = params(loads.Energy.__init__)
    assert list(p)[1:4] == ["state", "counties", "year"]


def test_energy_int_year_fails(tmp_path, monkeypatch):
    from cache import Cache
    monkeypatch.setattr(Cache, "CACHEDIR", str(tmp_path))
    with pytest.raises(TypeError):
        loads.Energy("NV", "Esmeralda", 2019)


def test_dg_default_source_is_cwd_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        loads.DG("CA", "Alameda")


def test_dg_bundled_file_is_positive_output():
    source = os.path.join(os.path.dirname(loads.__file__), "wecc", "county_dg.csv.gz")
    if not os.path.exists(source):
        pytest.skip("loads/wecc data files are not installed")
    day = pd.date_range("2020-07-01 12:00", "2020-07-02 11:00", freq="1h", tz="UTC")
    dg = loads.DG("CA", "Alameda", date_range=day, source=source)
    assert list(dg.columns) == ["elec_dg_MW"] and dg.elec_dg_MW.max() > 0  # opposite to elec_dg_MW <= 0
