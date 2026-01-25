"""Commercial building load data accessor


The commercial load data frame collects and consolidates `COMstock` data. Floor areas are
obtained from `Floorarea` data to scale loads for the specified year.

Examples
--------

To get the commercial building load data for Alameda County CA, use the following command

    from loads import Commercial
    print(Commercial(state="CA",county="Alameda"))

which outputs the following

                               elec_baseload_MW  ...  nonelec_total_MW
    2018-01-01 00:00:00+00:00          6.288318  ...          1.970713
    2018-01-01 01:00:00+00:00          6.690304  ...          2.775018
    2018-01-01 02:00:00+00:00          6.362257  ...          3.586859
    2018-01-01 03:00:00+00:00          6.157291  ...          4.237439
    2018-01-01 04:00:00+00:00          6.043443  ...          4.681834
    ...                                     ...  ...               ...
    2018-12-31 19:00:00+00:00          7.498333  ...          2.924475
    2018-12-31 20:00:00+00:00          7.660632  ...          2.249275
    2018-12-31 21:00:00+00:00          7.640507  ...          1.753567
    2018-12-31 22:00:00+00:00          7.358111  ...          1.600068
    2018-12-31 23:00:00+00:00          6.819952  ...          1.606544

    [8760 rows x 10 columns]
"""

import os
import pandas as pd
import logging

from fips import States, Counties
from loads.floorarea import Floorarea
from loads.comstock import COMstock
from cache import Cache

_logger = logging.getLogger(__file__)

class Commercial(pd.DataFrame):
    """Commercial building data frame class

    The `Commercial` class is a data frame that contains the collected
    building loads for each commercial building types, aggregated by load
    category, i.e., `baseload`,`cooling`, `heating`, `dg`, and `total` for
    both electric and non-electric loads.  Values are delivered both in MW.
    """
    COLLECT = {
            "elec_baseload": [
                "elec_exteriorlights",
                "elec_fans",
                "elec_heatrejection",
                "elec_equipment",
                "elec_interiorlights",
                "elec_pumps",
                "elec_refrigeration",
                "elec_watersystems",
                ],
            "elec_cooling": [
                "elec_cooling",
                ],
            "elec_heating": [
                "elec_heating",
                "elec_heatrecovery",
                ],
            "elec_dg":[
                ],
            "elec_total": [
                "elec_total",
                ],
            "nonelec_baseload": [
                "district_hotwater",
                "gas_heating",
                "gas_equipment",
                "gas_watersystems",
                "other_watersystems",
                ],
            "nonelec_cooling": [
                "district_cooling",
                ],
            "nonelec_heating": [
                "other_heating",
                "district_heating",
                ],
            "nonelec_dg": [
                ],
            "nonelec_total": [
                "other_total",
                "gas_total",
                "district_totalcooling",
                "district_totalheating",
                ],
            }
    """Mapping of COMstock data columns to Commercial data columns"""

    CACHEDIR = None
    """Cache folder"""

    CALIBRATION = {}
    """Load calibration data"""

    def __init__(self,
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        state:str,
        county:str,
        year:int=None,
        *,
        collect=None,
        refresh:bool=False,
        calibrate:float|str|None="auto",
        ):
        """Construct building types data frame

        Arguments
        ---------

          - `state`: specify the state abbreviation (required)

          - `county`: specify the county name (required)

          - `collect`: specify how COMstock columns are collected (default is `COLLECT`)

          - `year`: specify the year on which the floor area is based
            (default most recent in `Floorarea()`)

          - `refresh`: force cache refresh from source data

          - `calibrate`: set load calibration, automatically set calibration
            to state-level total energy using
            `loads.commercial.Commercial.CALIBRATION` table, or disable
            calibration

        Description
        -----------

        This class compiles the building type data for a county by collecting
        COMstock columns, scaling by the floor area in that year, and finally
        computing total electric and non-electric loads in MW.

        If calibrate is set to `'auto'`, then the loadshape will scaled based
        on the contents of the `loads.commercial.Commercial.CALIBRATE` data
        if the `state` is among its keys. Alternatively, a float value can be
        provided to scale accordingly. 
        """
        # pylint: disable=too-many-locals
        assert state in States()["ST"].values, f"{state=} is not valid"
        assert county in Counties().set_index(["ST","COUNTY"]).loc[state].index, \
            f"{state=} {county=} is not valid"

        if collect is None:
            collect = self.COLLECT

        floorarea = {}
        total_area = 0.0
        data = None

        # split floor areas by building type
        actual_areas = Floorarea(state=state,county=county,year=year)\
            .set_index("BUILDING_TYPE")\
            .sort_index()
        split_areas = {"BUILDING_TYPE":[],"FLOORAREA":[],"SPLITS":[],"FRACTION":[]}
        actual_areas_sum = actual_areas.FLOORAREA.sum()
        for bts,area in list(actual_areas.iterrows()):
            for bt in bts.split("+"):
                split_areas["BUILDING_TYPE"].append(bt if bt else "OTH")
                split_areas["FLOORAREA"].append(area.FLOORAREA / len(bts.split("+")))
                split_areas["SPLITS"].append(bts)
                split_areas["FRACTION"].append(area.FLOORAREA/actual_areas_sum)
        split_areas = pd.DataFrame(split_areas).set_index("BUILDING_TYPE")

        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR
        cache = Cache(package="loads",version=0,path=[state,county,"C.csv.gz"])
        if cache.exists() and not refresh:
            try:
                data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
                _logger.debug(f"{cache=} ok")
            except Exception as err:
                data = None
                cache.delete()
                _logger.error(f"{cache=} {err}")
        else:
            data = None
            _logger.debug(f"{cache=} (re)generation required")

        if data is None:

            # collect building type data
            data = {}
            for btype in COMstock.BUILDING_TYPES:
                bdata = COMstock(
                    state=state,
                    county=county,
                    building_type=btype,
                    )
                for aggr,columns in collect.items():
                    data[f"{btype}_{aggr}_MW"] = bdata[columns].sum(axis=1) / 1e6
                    floorarea[btype] = bdata["floor_area"].max()
                    total_area += floorarea[btype]
            data = pd.DataFrame(data)

            # prepare consolidation columns
            for ctype in collect.keys():
                data[f"{ctype}_MW"] = 0.0

            # collect and consolidate data
            for btype in COMstock.BUILDING_TYPES:

                # collect building type data
                if btype in split_areas.index:
                    for ctype in {x.split("_",1)[0] for x in collect.keys()}:
                        for kwname in [x for x in data.columns if x.startswith(f"{btype}_{ctype}_")]:
                            data[kwname] *= floorarea[btype] / total_area * split_areas.loc[btype].FLOORAREA
                else:
                    for ctype in {x.split("_",1)[0] for x in collect.keys()}:
                        for kwname in [x for x in data.columns if x.startswith(f"{btype}_{ctype}_")]:
                            data[kwname] = 0.0
                    _logger.debug(f"COMstock {county} {state} building type '{btype}' has zero floor area for {kwname}")

                # consolidate building type data
                for ctype in collect.keys():
                    data[f"{ctype}_MW"] += data[f"{btype}_{ctype}_MW"]
                    data.drop(f"{btype}_{ctype}_MW",axis=1,inplace=True)

            # update totals
            data["elec_total_MW"] = sum(data[f"elec_{x}_MW"] for x in ["baseload","cooling","heating"])
            data["elec_net_MW"] = data["elec_total_MW"] + data["elec_dg_MW"]
            data["nonelec_total_MW"] = sum(data[f"nonelec_{x}_MW"] for x in ["baseload","cooling","heating"])
            data.drop("nonelec_dg_MW",axis=1,inplace=True)

            # move year-end data to beginning
            data.index = pd.DatetimeIndex([str(x).replace("2019","2018") for x in data.index])
            data.index.name = "timestamp"
            data.sort_index(inplace=True)
            data = data.round(4)
            data.to_csv(cache.pathname,
                index=True,
                header=True,
                compression="gzip" if cache.pathname.endswith(".gz") else None,
                )

        # calibrate load is requested
        if self.CALIBRATION and calibrate == "auto":
            if isinstance(self.CALIBRATION,dict):
                if state in self.CALIBRATION:
                    data *= self.CALIBRATION[state][year]
                else:
                    _logger.warning(f"{state=} not in calibration data")
            elif isinstance(self.CALIBRATION,float):
                data *= self.CALIBRATION
            elif callable(self.CALIBRATION):
                data *= self.CALIBRATION(state)
            else:
                _logger.error(f"CALIBRATION={repr(CALIBRATION)} in invalid")
        elif isinstance(calibrate,float):
            data *= calibrate
            
        super().__init__(data[sorted(data.columns)])

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":
    """Main script

    The main script refreshes the cache with debugging enabled.
    """
    import sys
    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    from fips.counties import Counties

    for state,county in Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"].index.values:
        try:
            Commercial(state,county,refresh=True)
            _logger.debug(f"{state} {county} ok")
        except Exception as err:
            (_logger.exception if debug else _logger.error)(f"{state} {county} {err}")
