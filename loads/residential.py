"""Residential building load model

The residential load data frame collects and consolidates `RESstock` data. Housing units are
obtained from `Units` data to scale loads for the specified year.

# Example

The residential load data for Alameda County CA is obtained using the command

    from loads import Residential
    print(Residential(state="CA",county="Alameda"))

which outputs the following

                               elec_baseload_MW  ...  nonelec_total_MW
    timestamp                                    ...                  
    2018-01-01 00:00:00+00:00         45.084952  ...         46.469329
    2018-01-01 01:00:00+00:00         52.149717  ...         55.490697
    2018-01-01 02:00:00+00:00         58.137018  ...         66.615070
    2018-01-01 03:00:00+00:00         55.908885  ...         76.447298
    2018-01-01 04:00:00+00:00         52.823653  ...         88.704520
    ...                                     ...  ...               ...
    2018-12-31 19:00:00+00:00         41.082225  ...         78.719394
    2018-12-31 20:00:00+00:00         41.320007  ...         65.788885
    2018-12-31 21:00:00+00:00         39.149527  ...         54.617247
    2018-12-31 22:00:00+00:00         37.711368  ...         45.972108
    2018-12-31 23:00:00+00:00         38.225652  ...         39.217772

    [8760 rows x 10 columns]
"""

import os
import pandas as pd

from fips.states import States
from fips.counties import Counties
from loads.units import Units
from loads.resstock import RESstock
from loads.cache import Cache

class Residential(pd.DataFrame):
    """Residential building data frame class

    The `Residential` class is a data frame that contains the collected
    building loads for each residential building types, aggregated by load
    category, i.e., `baseload`,`cooling`, `heating`, `dg`, and `total` for
    both electric and non-electric loads.  Values are delivered both in MW.
    """
    COLLECT = {
            "elec_baseload": [
                "elec_bathfan",
                "elec_ceilingfan",
                "elec_dryer",
                "elec_washer",
                "elec_cooking",
                "elec_dishwasher",
                "elec_holidaylight",
                "elec_extlighting",
                "elec_extrarefrigerator",
                "elec_freezer",
                "elec_garagelighting",
                "elec_hottubheater",
                "elec_hottubpump",
                "elec_housefan",
                "elec_interiorlighting",
                "elec_plugs",
                "elec_poolheater",
                "elec_poolpump",
                "elec_rangefan",
                "elec_recircpump",
                "elec_refrigerator",
                "elec_vehicle",
                "elec_watersystems",
                "elec_wellpump",
                ],
            "elec_cooling": [
                "elec_cooling",
                "elec_coolingfan",
                "elec_coolingpump",
                ],
            "elec_heating": [
                "elec_heating",
                "elec_heatingfan",
                "elec_heatingsupplement",
                "elec_heatingpump",
                ],
            "elec_dg":[
                "elec_pv",
                ],
            "elec_total": [
                "elec_total",
                ],
            "nonelec_baseload": [
                "oil_watersystems",
                "gas_dryer",
                "gas_cooking",
                "gas_grill",
                "gas_hottubheater",
                "gas_lighting",
                "gas_poolheater",
                "lng_dryer",
                "lng_range",
                "lng_watersystems",
                ],
            "nonelec_cooling": [
                ],
            "nonelec_heating": [
                "oil_heating",
                "gas_fireplace",
                "gas_heating",
                "gas_watersystems",
                "lng_heating",
                "wood_heating",
                ],
            "nonelec_dg": [
                ],
            "nonelec_total": [
                "oil_total",
                "gas_total",
                "lng_total",
                "wood_total",
                ],
            }
    """Mapping of `RESstock` columns to `Residential` columns"""

    # pylint: disable=invalid-name
    CACHEDIR = None
    """Cache folder"""

    def __init__(self,
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        state:str,
        county:str,
        collect=None,
        year:int=None,
        refresh:bool=False,
        ):
        """Construct building types data frame

        # Arguments

        - `state`: specify the state abbreviation (required)

        - `county`: specify the county name (required)

        - `collect`: specify how RESstock columns are collected

        - `year`: specify the year on which the number of housing units is
          based (default most recent in `Units()`)

        - `refresh`: force download of data from source

        # Description

        This class compiles the building type data for a county by collecting
        RESstock columns, scaling by the number of housing units in that year,
        and finally computing total MW and the fraction of total of electric
        or non-electric load.
        """
        
        # pylint: disable=too-many-locals
        assert state in States()["ST"].values, f"{state=} is not valid"
        assert county in Counties().set_index(["ST","COUNTY"]).loc[state].index, \
            f"{state=} {county=} is not valid"

        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR
        cache = Cache([state,county,"R.csv.gz"])

        data = None
        if cache.exists() and not refresh:

            try:
                data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
            except:
                data = None
        
        if data is None:
        
            if collect is None:
                collect = self.COLLECT

            units = {}
            total_units = 0.0
            data = {}

            # collect building type data
            for btype in RESstock.BUILDING_TYPES:
                bdata = RESstock(
                    state=state,
                    county=county,
                    building_type=btype,
                    )
                for aggr,columns in collect.items():
                    data[f"{btype}_{aggr}_MW"] = bdata[columns].sum(axis=1) / 1e6
                    units[btype] = bdata["units"].max()
                    total_units += units[btype]
            data = pd.DataFrame(data)

            # prepare consolidation columns
            for ctype in collect.keys():
                data[f"{ctype}_MW"] = 0.0

            # scale by number of residential units and calculate fractional loads
            actual_units = Units(state=state,county=county,year=year)

            for btype in RESstock.BUILDING_TYPES:

                # collect building type data
                for ctype in {x.split("_",1)[0] for x in collect.keys()}:
                    for kwname in [x for x in data.columns if x.startswith(f"{btype}_{ctype}_")]:
                        data[kwname] *= units[btype] / total_units * actual_units

                # consolidate building type data
                for ctype in collect.keys():
                    data[f"{ctype}_MW"] += data[f"{btype}_{ctype}_MW"]
                    data.drop(f"{btype}_{ctype}_MW",axis=1,inplace=True)

            # update net total with DG
            data["elec_net_MW"] = data["elec_total_MW"] + data["elec_dg_MW"]
            data.drop("nonelec_dg_MW",axis=1,inplace=True)

            # move year-end data to beginning
            data.index = pd.DatetimeIndex([str(x).replace("2019","2018") for x in data.index])
            data.index.name = "timestamp"
            data.sort_index(inplace=True)
            data = data.round(4)
            data.to_csv(cache.pathname,index=True,header=True)
            
        super().__init__(data[sorted(data.columns)])

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":

    from fips.counties import Counties

    pd.options.display.width = None
    pd.options.display.max_columns = None

    for state,county in Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"].index.values:
        print("Processing",state,county,end="...",flush=True)
        try:
            print(pd.DataFrame(Residential(state,county,refresh=True).mean()).T.round(3))
            print("done")
        except Exception as err:
            print("ERROR:",err)
            raise
