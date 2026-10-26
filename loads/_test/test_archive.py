"""Test that `Residential` and `Commercial` use the cache archive

When `R.csv.gz` or `C.csv.gz` is not in the local cache, `Residential` and
`Commercial` must download it from the `cache` package archive (by default
the Eudoxys WECC data archive, https://github.com/eudoxys/wecc) instead of
building it from RESstock/COMstock data.

These tests run offline in seconds: the archive is a temporary folder served
through a `file://` URL template, and the RESstock/COMstock/Units/Floorarea
builders are replaced by stubs that fail if called.
"""

import os

import numpy as np
import pandas as pd
import pytest

import cache.cache as cache_module
from cache import Cache

from loads import residential as residential_module
from loads import commercial as commercial_module
from loads.residential import Residential
from loads.commercial import Commercial

STATE,COUNTY = "CA","Alameda"

COLUMNS = [
    "elec_baseload_MW","elec_cooling_MW","elec_heating_MW","elec_dg_MW",
    "elec_total_MW","elec_net_MW","nonelec_baseload_MW","nonelec_cooling_MW",
    "nonelec_heating_MW","nonelec_total_MW",
    ]

def _frame(seed:int) -> pd.DataFrame:
    """Synthetic 2018 sector load frame with the `Residential`/`Commercial` columns"""
    index = pd.date_range("2018-01-01",periods=8760,freq="1h",tz="UTC",name="timestamp")
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.uniform(0,100,(len(index),len(COLUMNS))).round(4),
        index=index,columns=COLUMNS)

def _fail(*args,**kwargs):
    """Stand-in for a source builder that must not be called"""
    raise AssertionError("built from source instead of using the archive")

class _FailStock:
    """Stand-in for `RESstock`/`COMstock` that must not be constructed"""
    BUILDING_TYPES = {"XXX":"stub"}
    def __init__(self,*args,**kwargs):
        _fail()

@pytest.fixture
def archive(tmp_path,monkeypatch):
    """Temporary archive holding `loads/CA/Alameda/{R,C}.csv.gz` and an empty local cache"""
    archivedir = tmp_path / "archive"
    folder = archivedir / "loads" / STATE / COUNTY
    folder.mkdir(parents=True)
    expected = {"R":_frame(1),"C":_frame(2)}
    for name,data in expected.items():
        data.to_csv(folder / f"{name}.csv.gz",index=True,header=True)

    cachedir = str(tmp_path / "cache")
    monkeypatch.setattr(cache_module,"ARCHIVES",[f"file://{archivedir}/{{package}}/{{path}}"])
    monkeypatch.setattr(Cache,"CACHEDIR",cachedir)
    monkeypatch.setattr(Residential,"CACHEDIR",cachedir)
    monkeypatch.setattr(Commercial,"CACHEDIR",cachedir)

    # building from source must not happen
    monkeypatch.setattr(residential_module,"RESstock",_FailStock)
    monkeypatch.setattr(residential_module,"Units",_fail)
    monkeypatch.setattr(commercial_module,"COMstock",_FailStock)
    monkeypatch.setattr(commercial_module,"Floorarea",_fail)

    return cachedir,expected

@pytest.mark.parametrize("cls,name,version",[
    (Residential,"R",1),
    (Commercial,"C",2),
    ])
def test_download_from_archive(archive,cls,name,version):
    """An archived file is downloaded into the local cache and used"""
    cachedir,expected = archive
    local = os.path.join(cachedir,"loads",str(version),STATE,COUNTY,f"{name}.csv.gz")
    assert not os.path.exists(local)

    data = cls(STATE,COUNTY)

    assert os.path.exists(local), "archived file was not stored in the local cache"
    assert data.index.name == "timestamp"
    assert len(data) == 8760
    pd.testing.assert_frame_equal(
        pd.DataFrame(data)[COLUMNS],
        expected[name][COLUMNS],
        check_freq=False,
        )

@pytest.mark.parametrize("cls",[Residential,Commercial])
def test_refresh_ignores_archive(archive,cls):
    """`refresh=True` rebuilds from source and never downloads"""
    with pytest.raises(AssertionError,match="built from source"):
        cls(STATE,COUNTY,refresh=True)

@pytest.mark.parametrize("cls",[Residential,Commercial])
def test_missing_from_archive(archive,monkeypatch,tmp_path,cls):
    """A file missing from the archive is built from source"""
    monkeypatch.setattr(cache_module,"ARCHIVES",[f"file://{tmp_path}/empty/{{package}}/{{path}}"])
    with pytest.raises(AssertionError,match="built from source"):
        cls(STATE,COUNTY)
