"""Calibration tests on a small synthetic system

These tests need no data downloads or cache and run in seconds. They check
the formulation of `loads.calibrate.Calibrate` on twelve synthetic
"County ST" units in three states, with a CAISO-like region nested in a
WECC-like region and two monthly blocks.
"""

# pylint: disable=redefined-outer-name
import numpy as np
import pandas as pd
import pytest

from loads.calibrate import Calibrate, CalibrationError

STATES = {"CA":5,"NV":3,"AZ":4}
MONTHS = ["2020-07","2020-08"]
ENERGY_FACTORS = {"CA":1.10,"NV":0.90,"AZ":1.05}
PEAK_FACTORS = {"CAISO":1.15,"WECC":1.12}


@pytest.fixture(scope="module")
def system() -> dict:
    """Synthetic loads, DG, memberships, and monthly targets"""
    rng = np.random.default_rng(1)
    index = pd.date_range("2020-07-01 00:00:00+00:00","2020-08-31 23:00:00+00:00",freq="1h",name="timestamp")
    hour = np.arange(len(index))
    units = [f"C{n} {state}" for n,state in enumerate(st for st,count in STATES.items() for _ in range(count))]
    load = pd.DataFrame({unit:(10+n)*(1+0.3*np.sin(2*np.pi*(hour+n)/24)) + rng.random(len(hour))
        for n,unit in enumerate(units)},index=index)
    dg = pd.DataFrame({unit:2*np.clip(np.sin(2*np.pi*hour/24),0,None) for unit in units},index=index)
    regions = pd.DataFrame({
        "CAISO":[float(x.endswith(" CA")) for x in units],
        "WECC":1.0,
        },index=units)
    net = load - dg
    months = pd.to_datetime([f"{x}-01" for x in MONTHS])
    energy = pd.DataFrame([{state:net.loc[month,[x for x in units if x.endswith(f" {state}")]].values.sum()*factor
        for state,factor in ENERGY_FACTORS.items()} for month in MONTHS],index=months)
    peak = pd.DataFrame([{region:(net.loc[month] @ regions[region]).max()*factor
        for region,factor in PEAK_FACTORS.items()} for month in MONTHS],index=months)
    return {"load":load,"dg":dg,"regions":regions,"energy":energy,"peak":peak}


@pytest.fixture(scope="module")
def searched(system) -> Calibrate:
    """Calibration with the default weight search over both months"""
    return Calibrate(system["load"],
        dg=system["dg"],
        energy=system["energy"],
        peak=system["peak"],
        regions=system["regions"],
        search=True,
        )


def test_shape(searched,system):
    """The result is the shaped load with the input's index and columns"""
    assert isinstance(searched,Calibrate)
    assert searched.shape == system["load"].shape
    assert (searched.index == system["load"].index).all()
    assert list(searched.columns) == list(system["load"].columns)
    assert np.allclose(searched.net.values,(searched - system["dg"]).values)


def test_blocks(searched):
    """Each calendar month is a separate block with its own selection"""
    assert len(searched.summary) == 2
    assert (searched.summary.candidates == 88).all()
    assert (searched.summary.selection == "passed selection tolerances").all()
    assert len(searched.sweep) == 2 * 88
    assert searched.parameters.index.get_level_values("block").nunique() == 2


def test_targets(searched):
    """Peaks reach their ceilings and state energies meet the tolerance"""
    regions = searched.regions
    assert (regions.shaped_MW <= regions.target_MW * (1 + 1e-6)).all()
    assert (regions.shaped_MW >= regions.target_MW * (1 - Calibrate.PEAK_SHORTFALL_TOL)).all()
    assert (searched.states.shaped_error.abs() <= Calibrate.STATE_ENERGY_TOL).all()
    assert (regions.dual_active_hours >= 1).all()


def test_affine(searched,system):
    """Every unit's shaped load is its input load scaled and offset"""
    for block,parameters in searched.parameters.groupby(level="block"):
        rows = (system["load"].index.year == block.year) & (system["load"].index.month == block.month)
        parameters = parameters.droplevel(0).reindex(system["load"].columns)
        expected = system["load"].values[rows] * parameters.scale.values + parameters.offset_MW.values
        assert np.allclose(searched.values[rows],expected)
        assert (parameters.scale >= -1e-9).all()
    assert searched.values.min() >= Calibrate.NONNEGATIVE_TOL


def test_fixed_weights(system):
    """Fixed weights solve one candidate; a zero drive leaves the peaks below target"""
    august = system["load"].index.month == 8
    result = Calibrate(system["load"][august],
        dg=system["dg"][august],
        energy=system["energy"].iloc[1],
        peak=system["peak"].iloc[1].to_dict(),
        regions={"CAISO":[x for x in system["load"].columns if x.endswith(" CA")],
            "WECC":list(system["load"].columns)},
        energy_weight=100.0,
        )
    summary = result.summary.iloc[0]
    assert summary.selection == "fixed weights"
    assert summary.candidates == 1
    assert summary.status == "optimal"
    assert summary.state_energy_max_abs_relative_error < 0.01
    assert summary.wecc_peak_shortfall_fraction > 0


def test_safeguards(system):
    """Tight unit safeguards bind and are respected"""
    august = system["load"].index.month == 8
    result = Calibrate(system["load"][august],
        dg=system["dg"][august],
        energy=system["energy"].iloc[1],
        peak=system["peak"].iloc[1],
        regions=system["regions"],
        drive={"CAISO":1.0,"WECC":1.0},
        peak_multiple=1.1,
        relative_rmse=0.1,
        )
    parameters = result.parameters
    assert (parameters.peak_multiple <= 1.1 + 1e-6).all()
    assert (parameters.relative_rmse <= 0.1 + 1e-6).all()
    assert result.summary.iloc[0].column_rmse_caps_active > 0


def test_zero_unit(system):
    """An identically zero unit is excluded and returned unchanged"""
    august = system["load"].index.month == 8
    load = system["load"][august].copy()
    load["Z0 NV"] = 0.0
    dg = system["dg"][august].copy()
    dg["Z0 NV"] = 0.0
    regions = pd.concat([system["regions"],pd.DataFrame({"CAISO":[0.0],"WECC":[1.0]},index=["Z0 NV"])])
    result = Calibrate(load,dg=dg,energy=system["energy"].iloc[1],peak=system["peak"].iloc[1],
        regions=regions,energy_weight=100.0)
    zero = result.parameters.droplevel(0).loc["Z0 NV"]
    assert not zero.active
    assert zero.scale == 1.0 and zero.offset_MW == 0.0
    assert (result["Z0 NV"] == 0).all()


def test_invalid_inputs(system):
    """Invalid inputs raise CalibrationError"""
    august = system["load"].index.month == 8
    load = system["load"][august]
    energy = system["energy"].iloc[1]
    peak = system["peak"].iloc[1]
    with pytest.raises(CalibrationError):
        Calibrate(-load,energy=energy,peak=peak)
    with pytest.raises(CalibrationError):
        Calibrate(load,dg=-system["dg"][august],energy=energy,peak=peak)
    with pytest.raises(CalibrationError):
        Calibrate(load,energy=energy.drop("NV"),peak=peak)
    with pytest.raises(CalibrationError):
        Calibrate(load,energy=system["energy"].iloc[:1],peak=system["peak"].iloc[:1])
    with pytest.raises(CalibrationError):
        Calibrate(load,energy=energy,peak=peak,peak_multiple=0.5)
