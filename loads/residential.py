"""Residential building load model

The residential load data frame collects and consolidates `RESstock` data. Housing units are
obtained from `Units` data to scale loads for the specified year.

Data Flow
---------

The data flow from RESstock to the `Residential` data frame is shown in Figure 1.

```mermaid
flowchart LR

    subgraph Residential
        subgraph relec[elec]
            e_baseload[baseload]
            e_cooling[cooling]
            e_heating[heating]
            e_dg[dg]
            e_total[total]
            e_net[net]
        end
        subgraph rnonelec[nonelec]
            ne_baseload[baseload] --> ne_total[total]
            ne_heating[heating] --> ne_total
        end
    end
    subgraph RESstock
        subgraph elec
            others --> e_baseload
            
            elec_cooling[cooling] --> e_cooling
            elec_coolingfan[coolingfan] --> e_cooling
            elec_cooling_pump[coolingpump] --> e_cooling

            elec_heating[heating] --> e_heating
            elec_heatingfan[heatingfan] --> e_heating
            elec_heatingsupplement[heatingsupplement] --> e_heating
            elec_heatingpump[heatingpump] --> e_heating

            pv --> e_dg

            e_baseload --> e_total
            e_cooling --> e_total
            e_heating --> e_total
            e_dg --> e_net
            e_total --> e_net

        end
        subgraph nonelec
            n_others[others] --> ne_baseload
            
            oilheating --> ne_heating
            gasheating --> ne_heating
            gasfireplace --> ne_heating
            lngheating --> ne_heating
            woodheating --> ne_heating
        end
    end
```
Figure 1: RESstock to Residential data frame data flow

In addition, the number of housing units, casting, and calibration are handled
as shown in Figure 2.

```mermaid
flowchart LR

    subgraph Unscaled
        subgraph u_nonelec[nonelec]
            un_baseload[baseload]
            un_heating[heating]
            un_total[total]
        end
        subgraph u_elec[elec]
            ue_baseload[baseload]
            ue_cooling[cooling]
            ue_heating[heating]
            ue_dg[dg]
            ue_total[total]
            ue_net[net]
        end
    end

    Unscaled --> Units --> Cast --> Calibrate --> Scaled

    subgraph Scaled
        subgraph s_nonelec[nonelec]
            sn_baseload[baseload]
            sn_heating[heating]
            sn_total[total]
        end
        subgraph s_elec[elec]
            se_baseload[baseload]
            se_cooling[cooling]
            se_heating[heating]
            se_dg[dg]
            se_total[total]
            se_net[net]
        end
    end
```
Figure 2: Residential load scaling

Examples
--------

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
import logging
from typing import Callable

import pandas as pd

from fips import States, Counties
from loads.units import Units
from loads.resstock import RESstock
from cache import Cache

_logger = logging.getLogger(__file__)

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
                "gas_cooking",
                "gas_dryer",
                "gas_grill",
                "gas_hottubheater",
                "gas_lighting",
                "gas_poolheater",
                "gas_watersystems",
                "lng_dryer",
                "lng_range",
                "lng_watersystems",
                "oil_watersystems",
                ],
            "nonelec_cooling": [
                ],
            "nonelec_heating": [
                "gas_fireplace",
                "gas_heating",
                "lng_heating",
                "oil_heating",
                "wood_heating",
                ],
            "nonelec_dg": [
                ],
            "nonelec_total": [
                "gas_total",
                "lng_total",
                "oil_total",
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
        year:int=None,
        *,
        collect=None,
        refresh:bool=False,
        calibrate:float|dict[str,float]|Callable|None=None,
        ):
        """Construct building types data frame

        Arguments
        ---------

          - `state`: specify the state abbreviation (required)

          - `county`: specify the county name (required)

          - `collect`: specify how RESstock columns are collected

          - `year`: specify the year on which the number of housing units is
            based (default most recent in `Units()`)

          - `refresh`: force download of data from source

          - `calibrate`: set load/solar calibration

        Description
        -----------

        This class compiles the building type data for a county by collecting
        RESstock columns, scaling by the number of housing units in that year,
        and finally computing total MW and the fraction of total of electric
        or non-electric load.

        If calibrate is set to `'auto'`, then the loadshape will scaled based
        on the contents of the `loads.commercial.Commercial.CALIBRATE` data
        if the `state` is among its keys. Alternatively, a float value can be
        provided to scale accordingly.
        """
        
        # pylint: disable=too-many-locals
        assert state in States()["ST"].values, f"{state=} is not valid"
        assert county in Counties().set_index(["ST","COUNTY"]).loc[state].index, \
            f"{state=} {county=} is not valid"

        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR
        cache = Cache(package="loads",version=0,path=[state,county,"R.csv.gz"])

        # load data from cache
        if cache.exists() and not refresh:

            try:
                data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
                _logger.debug(f"{cache=} ok")
            except Exception as err:
                data = None
                cache.delete()
                _logger.debug(f"{cache=} {err}")

        else:
            data = None
            _logger.debug(f"{cache=} (re)generation required")

        # no data in cache or cache needs to be refreshed
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
            data.to_csv(cache.pathname,index=True,header=True)

        # calibrate load is requested
        if isinstance(calibrate,float):
            data *= calibrate
        elif isinstance(calibrate,dict):
            if "load" in calibrate:
                columns = list(set(data.columns) - set("elec_dg_MW"))
                data[columns] *= calibrate["load"]
            if "solar" in calibrate:
                data["elec_dg_MW"] *= calibrate["solar"]
        elif callable(calibrate):
            data = calibrate(data)
        else:
            assert calibrate is None, f"{calibrate=} is not valid"

                        
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
            Residential(state,county,refresh=refresh)
            _logger.info(f"{state} {county} ok")
        except Exception as err:
            (_logger.exception if debug else _logger.error)(f"{state} {county} {err}")
