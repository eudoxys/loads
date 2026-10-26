"""Test that `loads` classes use the cache archive

When a cache file is not in the local cache, the `loads` classes must
download it from the `cache` package archive (by default the Eudoxys WECC
data archive, https://github.com/eudoxys/wecc) instead of building it from
the original sources.

The `Residential` and `Commercial` tests run offline in seconds: the archive
is a temporary folder served through a `file://` URL template, and the
RESstock/COMstock/Units/Floorarea builders are replaced by stubs that fail if
called.

The `network` tests read the real archive for Alameda County CA into an
empty temporary cache, with every original source pointed at an invalid
host, so a rebuild from source fails instead of passing silently. They
download about 25 MB.
"""

import os

import numpy as np
import pandas as pd
import pytest

import cache.cache as cache_module
from cache import Cache

from loads import residential as residential_module
from loads import commercial as commercial_module
from loads import industry as industry_module
from loads import agriculture as agriculture_module
from loads import total as total_module
from loads.residential import Residential
from loads.commercial import Commercial
from loads.resstock import RESstock
from loads.comstock import COMstock
from loads.units import Units
from loads.floorarea import Floorarea
from loads.industry import Industry
from loads.agriculture import Agriculture
from loads.total import Total

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

INVALID = "https://invalid.invalid"
"""Source URL that cannot be reached, so a rebuild from source fails"""

@pytest.fixture
def real_archive(tmp_path,monkeypatch):
    """Empty local cache, the default archive, and unreachable original sources"""
    cachedir = str(tmp_path / "cache")
    monkeypatch.setattr(Cache,"CACHEDIR",cachedir)
    for cls in [Residential,Commercial,RESstock,COMstock,Units,Floorarea,Industry,Agriculture]:
        monkeypatch.setattr(cls,"CACHEDIR",cachedir)
    for cls in [RESstock,COMstock,Units,Floorarea,Industry,Agriculture]:
        monkeypatch.setattr(cls,"SOURCE",INVALID)
    monkeypatch.setattr(industry_module,"CACHE",None)
    monkeypatch.setattr(agriculture_module,"CACHE",None)
    monkeypatch.setattr(total_module,"Weather",_fail)
    return cachedir

def _local(cachedir:str,version:int,*path:str) -> str:
    """Path of a file in the local cache"""
    return os.path.join(cachedir,"loads",str(version),*path)

@pytest.mark.network
@pytest.mark.parametrize("cls,building_type",[
    (RESstock,"RSD"),
    (COMstock,"CMO"),
    ])
def test_stock_from_archive(real_archive,cls,building_type):
    """Raw ResStock/ComStock data comes from the archive"""
    data = cls(STATE,COUNTY,building_type)
    assert os.path.exists(_local(real_archive,0,STATE,COUNTY,f"{building_type}.csv.gz"))
    assert len(data) == 8760
    assert data.select_dtypes("number").abs().sum().sum() > 0

@pytest.mark.network
def test_units_from_archive(real_archive):
    """Census housing units come from the archive"""
    units = Units(STATE,COUNTY,2020)
    assert os.path.exists(_local(real_archive,0,STATE,"units.csv.gz"))
    assert units > 0

@pytest.mark.network
@pytest.mark.parametrize("cls,name",[
    (Floorarea,"floorarea_2019.csv.gz"),
    (Industry,"industry.csv.gz"),
    (Agriculture,"agriculture.csv.gz"),
    ])
def test_national_from_archive(real_archive,cls,name):
    """Package-wide inventories come from the archive"""
    data = cls(STATE,COUNTY)
    assert os.path.exists(_local(real_archive,0,name))
    assert len(data) > 0

@pytest.mark.network
def test_training_from_archive(real_archive):
    """`Total` training data comes from the archive (weather is not built)"""
    X = Total.EXOGENOUS_VARIABLES["elec_total_MW"]
    data = Total._get_training(STATE,COUNTY,X,"elec_total_MW") # pylint: disable=protected-access
    assert os.path.exists(_local(real_archive,2,STATE,COUNTY,"T_elec_1h_training.csv.gz"))
    assert "elec_total_MW" in data.columns
    assert data["elec_total_MW"].sum() > 0
