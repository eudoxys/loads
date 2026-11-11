"""Energy tests with a stubbed total load model

These tests need no data downloads and run in seconds. `loads.estimator.Estimator`
is replaced by a stub that returns a constant load per county and fails for
selected counties, so the tests check how `loads.energy.Energy` assembles
county columns, in particular that a failed county does not inherit the
previous county's data (issue #44).
"""

# pylint: disable=redefined-outer-name
import pandas as pd
import pytest

from cache import Cache
from loads import energy as energy_module
from loads.energy import Energy

LOADS = {"Pima":3.0,"Pinal":2.0,"Santa Cruz":1.0,"Yavapai":4.0}
"""Constant county loads in MW returned by the stub"""


class _StubEstimator(pd.DataFrame):
    """Stand-in for `loads.estimator.Estimator` returning a constant load"""

    FAIL = set()

    def __init__(self,county_st,years):
        county = " ".join(county_st.split()[:-1])
        if county in self.FAIL:
            raise ValueError(f"stub failure for {county_st}")
        index = pd.date_range(f"{min(years)}-01-01",f"{max(years)}-12-31 23:00",freq="1h",tz="UTC")
        super().__init__({
            "temperature_degF":70.0,
            "elec_total_MW":LOADS[county],
            },index=index)


@pytest.fixture
def stub(monkeypatch,tmp_path):
    """Install the stub and keep `Energy` cache files in a temporary folder"""
    monkeypatch.setattr(energy_module,"Estimator",_StubEstimator)
    monkeypatch.setattr(Cache,"CACHEDIR",str(tmp_path))
    _StubEstimator.FAIL = set()
    return _StubEstimator


def test_energy_all_counties(stub): # pylint: disable=unused-argument
    """Every county gets its own column with its own energy"""
    data = Energy("AZ",list(LOADS),[2018,2018],refresh=True)
    assert list(data.columns) == [f"{x} AZ" for x in LOADS]
    assert len(data) == 12
    jan = data.iloc[0]
    for county,load in LOADS.items():
        assert jan[f"{county} AZ"] == pytest.approx(load*31*24)


def test_energy_failed_county_is_omitted(stub):
    """A failed county is omitted, not filled with the previous county's data"""
    stub.FAIL = {"Santa Cruz"}
    with pytest.warns(UserWarning,match="Santa Cruz AZ"):
        data = Energy("AZ",list(LOADS),[2018,2018],refresh=True)
    assert list(data.columns) == ["Pima AZ","Pinal AZ","Yavapai AZ"]
    assert not data.columns.duplicated().any()
    assert data["Yavapai AZ"].iloc[0] == pytest.approx(LOADS["Yavapai"]*31*24)


def test_energy_failed_first_county(stub):
    """A failure on the first county doesn't break the remaining counties"""
    stub.FAIL = {"Pima"}
    with pytest.warns(UserWarning,match="Pima AZ"):
        data = Energy("AZ",list(LOADS),[2018,2018],refresh=True)
    assert list(data.columns) == ["Pinal AZ","Santa Cruz AZ","Yavapai AZ"]


def test_energy_all_counties_fail(stub):
    """An error is raised when no county has a total load"""
    stub.FAIL = set(LOADS)
    with pytest.warns(UserWarning), pytest.raises(RuntimeError,match="AZ"):
        Energy("AZ",list(LOADS),[2018,2018],refresh=True)
