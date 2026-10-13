"""Build hourly county commercial demand from COMstock intensities.

For each end-use group and hour:

    stock_MW = sum(intensity_W_per_ft2[b] * stock_area_ft2[b]) / 1e6
    county_MW = stock_MW * county_area_ft2 / sum(stock_area_ft2[b])

Floorarea supplies total county area; COMstock supplies the building mix.
Inventory category proportions are deliberately not used. All inventory area,
including unmatched categories, is distributed across available stock profiles.

Custom end-use groups are honored, calibration preserves the net-load identity,
and the cache key includes the grouping configuration. COMstock owns
the reference-year timestamps and source-area normalization. Zero total stock
area is unavailable model data and raises ValueError, rather than returning NaNs.
"""

import hashlib
import json
import logging
import math
from typing import Callable

import pandas as pd

from cache import Cache
from fips import States, Counties
from loads.comstock import COMstock
from loads.floorarea import Floorarea

_logger = logging.getLogger(__file__)
_COMPONENTS = ("baseload","cooling","heating")


def _build_loads(state,county,year,collect):
    """Build represented-stock MW, then scale to total county inventory area."""
    inventory = Floorarea(state=state,county=county,year=year)
    county_area_ft2 = inventory.FLOORAREA.sum(skipna=False)
    if not math.isfinite(county_area_ft2) or county_area_ft2 < 0:
        raise ValueError("County floor area must be finite and nonnegative")

    # Totals are derived below; source totals are not independent contributions.
    groups = {name:columns for name,columns in collect.items()
        if name not in {"elec_total","nonelec_total","nonelec_dg","elec_net"}}
    stock_mw = None
    total_stock_area_ft2 = None
    for building_type in COMstock.BUILDING_TYPES:
        intensity = COMstock(state=state,county=county,building_type=building_type)
        if stock_mw is None:
            if not intensity.index.is_unique:
                raise ValueError(f"Duplicate COMstock timestamps for {building_type}")
            stock_mw = pd.DataFrame(0.0,index=intensity.index,
                columns=[f"{name}_MW" for name in groups])
            total_stock_area_ft2 = pd.Series(0.0,index=intensity.index)
        elif not intensity.index.equals(stock_mw.index):
            raise ValueError(f"COMstock timestamps differ for {building_type}")

        stock_area_ft2 = intensity["floor_area"]
        if not ((stock_area_ft2 >= 0) & (stock_area_ft2 < float("inf"))).all():
            raise ValueError(f"Invalid COMstock floor area for {building_type}")
        total_stock_area_ft2 += stock_area_ft2
        for group,end_uses in groups.items():
            # Empty groups (default DG) contribute zero at every timestamp.
            intensity_w_per_ft2 = intensity[end_uses].sum(axis=1)
            type_stock_mw = intensity_w_per_ft2 * stock_area_ft2 / 1e6
            stock_mw[f"{group}_MW"] += type_stock_mw

    if stock_mw is None:
        raise ValueError("No COMstock building types configured")
    if (total_stock_area_ft2 <= 0).any():
        raise ValueError("No represented commercial floor area at one or more timestamps")

    # Stock shares allocate ONE county total, preserving its total floor area.
    # A common scaling of stock-area metadata cancels in numerator/denominator.
    county_mw = stock_mw.div(total_stock_area_ft2,axis=0) * county_area_ft2
    county_mw = _update_totals(county_mw)
    county_mw.index.name = "timestamp"
    return county_mw.sort_index().round(4)


def _update_totals(data):
    """Derive gross and net demand from the component columns, in MW."""
    for fuel in ("elec","nonelec"):
        columns = [f"{fuel}_{component}_MW" for component in _COMPONENTS]
        data[f"{fuel}_total_MW"] = data[columns].sum(axis=1)
    # Generation follows the package's negative-load convention.
    data["elec_net_MW"] = data["elec_total_MW"] + data["elec_dg_MW"]
    return data


def _calibrate(data,calibrate):
    """Apply calibration to a copy; the cached frame remains uncalibrated."""
    data = data.copy()
    if calibrate is None:
        return data
    if isinstance(calibrate,float):
        return data * calibrate
    if isinstance(calibrate,dict):
        load_columns = [name for name in data.columns
            if name not in {"elec_dg_MW","elec_total_MW","nonelec_total_MW","elec_net_MW"}]
        data[load_columns] *= calibrate.get("load",1.0)
        data["elec_dg_MW"] *= calibrate.get("solar",1.0)
        return _update_totals(data)
    if callable(calibrate):
        return calibrate(data)
    raise TypeError("calibrate must be a float, dict, callable, or None")


class Commercial(pd.DataFrame):
    """Hourly commercial demand in MW, with the existing output column names.

    Non-electric MW measures fuel/district-energy consumption, not electric
    demand. 'Baseload' is an end-use grouping, not a constant-load assumption.
    """

    COLLECT = {
        "elec_baseload": ["elec_exteriorlights","elec_fans","elec_heatrejection",
            "elec_equipment","elec_interiorlights","elec_pumps",
            "elec_refrigeration","elec_watersystems"],
        "elec_cooling": ["elec_cooling"],
        "elec_heating": ["elec_heating","elec_heatrecovery"],
        "elec_dg": [],
        "elec_total": ["elec_total"],
        "nonelec_baseload": ["district_hotwater","gas_heating","gas_equipment",
            "gas_watersystems","other_watersystems"],
        "nonelec_cooling": ["district_cooling"],
        "nonelec_heating": ["other_heating","district_heating"],
        "nonelec_dg": [],
        "nonelec_total": ["other_total","gas_total","district_totalcooling",
            "district_totalheating"],
    }

    CACHEDIR = None

    def __init__(self,state:str,county:str,year:int=None,*,
        collect:dict[str,list[str]]|None=None,refresh:bool=False,
        calibrate:float|dict[str,float]|Callable|None=None):
        """Load or construct commercial demand, then apply optional calibration.

        Arguments
        ---------
          - `year`: requested inventory year; Floorarea determines availability.
            This does not change COMstock's 2018 profile year.
          - `collect`: source end-use groups. Electric/non-electric baseload,
            cooling, heating, and electric DG groups are required. Totals are
            always derived from components, regardless of supplied total groups.
            Source columns may occur in multiple groups; each group sums its list.
          - `refresh`: rebuild this aggregate using the accessors' existing
            source-cache behavior; does not force source downloads.
          - `calibrate`: one float for all columns, a dict with independent
            `load` and `solar` factors, or a callable taking the completed frame.
        """
        assert state in States()["ST"].values, f"{state=} is not valid"
        assert county in Counties().set_index(["ST","COUNTY"]).loc[state].index, \
            f"{state=} {county=} is not valid"
        collect = self.COLLECT if collect is None else collect
        required = {f"{fuel}_{part}" for fuel in ("elec","nonelec") for part in _COMPONENTS}
        required.add("elec_dg")
        if missing := required - collect.keys():
            raise ValueError(f"Missing load groups: {sorted(missing)}")

        # Distinct from legacy C.csv.gz; custom groups cannot reuse another result.
        configuration = json.dumps({"year":year,"collect":collect},sort_keys=True)
        cache_key = hashlib.sha256(configuration.encode()).hexdigest()[:16]
        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR
        cache = Cache(package="loads",version=0,
            path=[state,county,f"C_stock_mix_v1_{cache_key}.csv.gz"])
        data = None
        if cache.exists() and not refresh:
            try:
                data = pd.read_csv(cache.pathname,index_col=0,parse_dates=[0])
            except Exception as err:
                _logger.debug("Could not read %s: %s",cache.pathname,err)
                cache.delete()
        if data is None:
            data = _build_loads(state,county,year,collect)
            data.to_csv(cache.pathname,compression="gzip")

        data = _calibrate(data,calibrate)
        super().__init__(data[sorted(data.columns)])

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return accepted constructor arguments for CLI dispatch."""
        return {name:value for name,value in kwargs.items()
            if name in cls.__init__.__annotations__}


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG if "--debug" in sys.argv else logging.INFO)
    for state,county in Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"].index.values:
        try:
            Commercial(state,county,refresh="--refresh" in sys.argv)
            _logger.info("%s %s ok",state,county)
        except Exception as err:
            (_logger.exception if "--debug" in sys.argv else _logger.error)(
                "%s %s %s",state,county,err)
            raise
