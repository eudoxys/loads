import numpy as np
import pandas as pd
import pytest

from loads.skill import (
    allocate, coincident_peak, conservation_error, daily_profile, duration_curve, energy,
    fit_energy_peak, hourly_range, nearest_nodes, peaks, scale_monthly, scale_to_energy,
    shape_to_targets, summary, temperature_response, validate,
)
from skill_synthetic import synthetic_total


def test_hourly_range():
    assert len(hourly_range(2019)) == 8760
    assert len(hourly_range(2020)) == 8784
    two = hourly_range([2021, 2019])
    assert len(two) == 2 * 8760 and two.is_monotonic_increasing
    assert str(two.tz) == "UTC" and two.name == "timestamp"
    w = hourly_range(start="2020-07-01", end="2020-07-31 23:00")
    assert len(w) == 31 * 24
    with pytest.raises(ValueError):
        hourly_range(2020, start="2020-01-01")


def test_energy_is_sum_of_mw(total2018):
    e = energy(total2018, None)
    assert np.isclose(e["elec_total_MWh"].iloc[0], total2018["elec_total_MW"].sum())
    m = energy(total2018, "MS")
    assert len(m) == 12
    assert np.isclose(m["elec_total_MWh"].sum(), total2018["elec_total_MW"].sum())


def test_summary_peaks_and_curves(total2018):
    s = summary(total2018)
    assert s["hours"] == 8760 and 0 < s["load_factor"] < 1
    p = peaks(total2018, ["elec_total_MW", "elec_dg_MW"], n=2)
    assert p.loc[p.column == "elec_dg_MW", "MW"].max() < 0
    ldc = duration_curve(total2018["elec_total_MW"])
    assert ldc.is_monotonic_decreasing and np.isclose(ldc.index[-1], 1.0)
    prof = daily_profile(total2018["elec_total_MW"], by="season", tzoffset_hours=-8)
    assert prof.shape == (24, 4)
    tr = temperature_response(total2018)
    assert tr["hours"].sum() == 8760


def test_scale_to_energy_proportional(total2018):
    target = 1.1 * total2018["elec_total_MW"].sum()
    sectors = [c for c in total2018 if c.startswith("elec_") and c not in ("elec_total_MW", "elec_dg_MW", "elec_net_MW")]
    out, k = scale_to_energy(total2018, {"elec_total_MW": target}, also_scale={"elec_total_MW": sectors})
    assert np.isclose(k["elec_total_MW"], 1.1)
    assert np.isclose(out["elec_total_MW"].sum(), target)
    assert validate(out).ok  # sector sum and net identity preserved
    # shape preserved: correlation 1
    assert np.isclose(np.corrcoef(out["elec_total_MW"], total2018["elec_total_MW"])[0, 1], 1.0)


def test_scale_monthly(total2018):
    old = total2018["elec_total_MW"].resample("MS").sum()
    target = old * np.linspace(0.9, 1.2, 12)
    out, f = scale_monthly(total2018, "elec_total_MW", target)
    assert np.allclose(out["elec_total_MW"].resample("MS").sum().to_numpy(), target.to_numpy())
    assert np.allclose(f.to_numpy(), np.linspace(0.9, 1.2, 12))
    assert np.allclose(out["elec_net_MW"], out["elec_total_MW"] + out["elec_dg_MW"])


def test_fit_energy_peak_keeps_peak(total2018):
    s = total2018["elec_total_MW"].iloc[:24 * 31]
    peak = s.max() * 1.05
    e = s.sum() * 1.02
    y = fit_energy_peak(s, energy=e, peak=peak)
    assert np.isclose(y.sum(), e, rtol=1e-6)
    assert np.isclose(y.loc[s.idxmax()], peak)
    assert y.idxmax() == s.idxmax()
    with pytest.raises(ValueError, match="minimum load"):
        fit_energy_peak(s, energy=s.sum() * 0.2, peak=s.max())
    with pytest.raises(ValueError, match="invert"):
        fit_energy_peak(s, energy=s.sum() * 3, peak=s.max())
    s2 = s.copy()
    s2.iloc[0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        fit_energy_peak(s2, energy=e)


def _panel_2020_07():
    frames = {n: synthetic_total(2020, seed=k) for k, n in enumerate(["Alameda CA", "Kern CA", "Washoe NV"])}
    rows = slice("2020-07-01", "2020-07-31 23:00")
    X = pd.DataFrame({n: f.loc[rows, "elec_total_MW"] for n, f in frames.items()})
    D = pd.DataFrame({n: f.loc[rows, "elec_dg_MW"] for n, f in frames.items()})  # <= 0
    net = X + D
    energy = {"CA": float(net[["Alameda CA", "Kern CA"]].sum().sum()) * 1.04,
              "NV": float(net["Washoe NV"].sum()) * 0.97}
    peak = {"ALL": float(net.sum(axis=1).max()) * 1.02}
    return X, D, energy, peak


def test_shape_to_targets_converts_dg_and_hits_targets():
    X, D, energy, peak = _panel_2020_07()
    out = shape_to_targets(X, energy=energy, peak=peak, dg=D)
    assert out.summary.selection.iloc[0] == "passed selection tolerances"
    assert out.states.shaped_error.abs().max() <= 5e-3
    assert np.allclose(out.net, out - (-D))  # net = shaped gross load minus DG output
    assert out.attrs["loadskill"]["mode"] == "shape_to_targets"
    out2 = shape_to_targets(X, energy=energy, peak=peak, dg=-D, dg_convention="output", search=False)
    assert out2.summary.selection.iloc[0] == "fixed weights"


def test_shape_to_targets_rejects_bad_inputs():
    X, D, energy, peak = _panel_2020_07()
    with pytest.raises(ValueError, match="dg_convention"):
        shape_to_targets(X, energy=energy, peak=peak, dg=-D)            # positive DG labeled 'load'
    with pytest.raises(ValueError, match="peak region"):
        shape_to_targets(X, energy=energy, peak={})
    edged = X.copy()
    edged.iloc[:3, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        shape_to_targets(edged, energy=energy, peak=peak)
    with pytest.raises(ValueError, match="gross load"):
        shape_to_targets(X + D * 50, energy=energy, peak=peak)
    with pytest.raises(ValueError, match="County ST"):
        shape_to_targets(X.rename(columns={"Alameda CA": "bus_1"}), energy=energy, peak=peak)


def test_nearest_and_allocate(total2018):
    nodes = pd.DataFrame({"lat": [37.8, 34.05], "lon": [-122.3, -118.25]}, index=["bay", "la"])
    m = nearest_nodes(["Alameda CA", "Los Angeles CA", "Orange CA"], nodes)
    assert m.loc["Alameda CA", "node"] == "bay"
    assert m.loc["Los Angeles CA", "node"] == "la"
    far = nearest_nodes(["King WA"], nodes, max_km=200)
    assert far.loc["King WA", "node"] is None

    s = total2018["elec_net_MW"]
    series = {"Alameda CA": s, "Los Angeles CA": s * 2, "Orange CA": s * 0.5}
    nodal = allocate(series, m)
    assert list(nodal.columns) == ["bay", "la"]
    assert abs(conservation_error(series, nodal)) < 1e-6

    split = allocate({"Alameda CA": s}, {"Alameda CA": {"bay": 0.75, "la": 0.25}})
    assert np.allclose(split["bay"], 0.75 * s)
    with pytest.raises(KeyError):
        allocate({"Kern CA": s}, m)
    with pytest.raises(ValueError):
        allocate({"Alameda CA": s}, {"Alameda CA": {"bay": 0.5}})


def test_coincident_peak(total2018):
    panel = pd.DataFrame({"a": total2018["elec_residential_MW"], "b": total2018["elec_commercial_MW"]})
    cp = coincident_peak(panel)
    assert (cp["coincidence"] <= 1 + 1e-12).all()
