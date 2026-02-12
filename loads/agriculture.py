"""Agricultural load data

Collects agricultural load data at state/county level. Data is based on [NREL US
County-Level Industrial Energy Use](https://data.nrel.gov/submissions/97), which
includes agricultural load data.

Agricultural non-electric total load and electric net load are converted to average
MW. All agricultural loads in each county are aggregated. 

Example
-------

Get the agricultural load data for all California counties using the command

    from loads.agriculture import Agriculture
    print(Agriculture("CA"))

which outputs the following

                     nonelec_total_MW  elec_net_MW  elec_baseload_MW  elec_total_MW  nonelec_baseload_MW
    county                                                                                              
    Alameda                 10.100226     6.901008          6.901008       6.901008            10.100226
    Alpine                   0.094917     0.062058          0.062058       0.062058             0.094917
    Amador                  10.533700     7.517497          7.517497       7.517497            10.533700
    .
    .
    .
    Ventura                 61.580047    54.378405         54.378405      54.378405            61.580047
    Yolo                    40.123365    25.889051         25.889051      25.889051            40.123365
    Yuba                    22.763883    15.086629         15.086629      15.086629            22.763883

For more examples, see `loads.industry.Industry`, which uses the same syntax.

Caveat
------

    - Any agriculture for which a county FIPS code in the NREL data does not match a
      valid county FIPS code is matched to the previous county FIPS code, e.g.,
      `2270` is aggregated with `2265` and not `2275`.
"""

import os
import logging

import numpy as np
import pandas as pd

from fips import Counties
from cache import Cache

_logger = logging.getLogger(__file__)

CACHE = None
"""Global cache of agricultural load data"""

class Agriculture(pd.DataFrame):
    "Agricultural loads data frame implementation"

    # pylint: disable=invalid-name
    CACHEDIR = None
    """Cache folder path (`None` is package source folder)"""

    SOURCE = "https://data.nrel.gov/system/files/97/agriculture_EndUse.gz"
    """Source of agriculture energy use data"""

    COLUMNS = {
        "fips_matching":None,
        "Diesel": "nonelec_total_MW",
        "LPG_NGL": "nonelec_total_MW",
        "Natural_gas": "nonelec_total_MW",
        "Net_electricity": "elec_net_MW",
        "Residual_fuel_oil": "nonelec_total_MW",
    }
    """Mapping of source data columns to `Agriculture` columns"""

    def __init__(self,
        state:str=None,
        county:str=None,
        loadshape:pd.DataFrame|dict|None=None,
        refresh:bool=False,
        ):
        """Construct an agricultural load data frame

        Arguments
        ---------

          - `state`: state (default all states)

          - `county`: county (default all counties)

          - `loadshape`: load shape to roll out county load

          - `refresh`: force reload of data from the online source
        """

        # set cache location
        if self.CACHEDIR :
            Cache.CACHEDIR = self.CACHEDIR

        # load data
        global CACHE
        if CACHE is None:
            cache = Cache(package="loads",version=0,path=["agriculture.csv.gz"])
            if cache.exists() and not refresh:
                try:
                    data = pd.read_csv(cache.pathname,low_memory=False)
                    _logger.debug(f"{cache=} ok")
                except Exception as err:
                    data = None
                    cache.delete()
                    _logger.debug(f"{cache=} {err}")
            else:
                data = None
                _logger.debug(f"{cache=} (re)generation required")
            
            if data is None:
                try:
                    data = pd.read_csv(self.SOURCE,
                        low_memory=False).sort_values("fips_matching")
                    _logger.debug(f"download of '{self.SOURCE}' ok")
                    data.to_csv(cache.pathname,index=False,header=True,compression="gzip"
                        if cache.pathname.endswith(".gz") else None)
                except Exception as err:
                    _logger.error(f"url={self.SOURCE}, {err=}")
                    raise

            # remove unwanted columns, aggregate, and convert from TBTU/y to MWh/h
            data = data\
                .drop([x for x in data.columns if x not in self.COLUMNS],axis=1) \
                .groupby(["fips_matching"]) \
                .sum() \
                * 1e12 \
                * 0.2931 \
                / 1e6 \
                / 365.2425 \
                / 24
                # convert from TBTU/y -> BTU/y -> Wh/y -> MWh/y -> MWh/d -> MWh/h

            # collect columns
            for column,group in [(x,y) for x,y in self.COLUMNS.items() if not y is None]:
                if not group in data.columns:
                    data[group] = 0.0
                data[group] += data[column]
                data.drop(column,inplace=True,axis=1)
            data.reset_index(inplace=True)

            # merge state/county data
            counties = Counties()
            data.fips_matching = [f"{x:05d}" for x in data.fips_matching]
            data = pd.merge(
                left=counties[["FIPS","ST","COUNTY"]],
                right=data,
                left_on="FIPS",
                right_on="fips_matching",
                how="outer",
                )\
                .drop({"FIPS","fips_matching"},axis=1)\
                .rename({"ST":"state","COUNTY":"county"},axis=1)\
                .ffill()\
                .groupby(["state","county"])\
                .sum()
            CACHE = data.copy()
        else:
            data = CACHE.copy()

        # return all states/counties
        if state is None and county is None:
            data["elec_baseload_MW"] = data["elec_net_MW"]
            data["elec_total_MW"] = data["elec_net_MW"]
            data["nonelec_baseload_MW"] = data["nonelec_total_MW"]
            data["elec_cooling_MW"] = 0.0
            data["elec_heating_MW"] = 0.0
            data["elec_dg_MW"] = 0.0
            data["nonelec_cooling_MW"] = 0.0
            data["nonelec_heating_MW"] = 0.0
            super().__init__(data)

        # return requested state
        elif county is None:
            data["elec_baseload_MW"] = data["elec_net_MW"]
            data["elec_total_MW"] = data["elec_net_MW"]
            data["nonelec_baseload_MW"] = data["nonelec_total_MW"]
            data["elec_cooling_MW"] = 0.0
            data["elec_heating_MW"] = 0.0
            data["elec_dg_MW"] = 0.0
            data["nonelec_cooling_MW"] = 0.0
            data["nonelec_heating_MW"] = 0.0
            super().__init__(data.loc[state,:])

        # return requested county raw data
        elif loadshape is None:
            data["elec_baseload_MW"] = data["elec_net_MW"]
            data["elec_total_MW"] = data["elec_net_MW"]
            data["nonelec_baseload_MW"] = data["nonelec_total_MW"]
            data["elec_cooling_MW"] = 0.0
            data["elec_heating_MW"] = 0.0
            data["elec_dg_MW"] = 0.0
            data["nonelec_cooling_MW"] = 0.0
            data["nonelec_heating_MW"] = 0.0
            super().__init__(data.loc[state,county])

        # return rollout of county load
        elif isinstance(loadshape,pd.DataFrame):
            nonelec_total_MW,elec_net_MW = data.loc[state,county].values.tolist()
            assert len(loadshape.columns) == 1, "loadshape must have only one column"
            super().__init__(pd.DataFrame(
                data={
                "elec_baseload_MW":loadshape[0]*elec_net_MW,
                "elec_net_MW":loadshape[0]*elec_net_MW,
                "elec_total_MW":loadshape[0]*elec_net_MW,
                "nonelec_baseload_MW":loadshape[0]*nonelec_total_MW,
                "nonelec_total_MW":loadshape[0]*nonelec_total_MW,
                "elec_heating_MW":loadshape[0]*0.0,
                "elec_cooling_MW":loadshape[0]*0.0,
                "elec_dg_MW":loadshape[0]*0.0,
                "nonelec_heating_MW":loadshape[0]*0.0,
                "nonelec_cooling_MW":loadshape[0]*0.0,
                },
                index=loadshape.index,
                ))

        # return loadshape rollout of county load
        elif isinstance(loadshape,dict):
            assert "shape" in loadshape, "'shape' required in loadshape"
            assert "start" in loadshape, "'start' required in loadshape"
            assert "end" in loadshape, "'end' required in loadshape"
            assert "freq" in loadshape, "'freq' required in loadshape"
            dt_index = pd.date_range(
                start=loadshape["start"],
                end=loadshape["end"],
                freq=loadshape["freq"],
                )
            n,m = len(dt_index), len(loadshape["shape"])
            shape = np.array(loadshape["shape"] * int( n / m ) + loadshape["shape"][:n%m])
            nonelec_total_MW,elec_net_MW = data.loc[state,county].values.tolist()
            super().__init__(pd.DataFrame(
                data={
                "elec_baseload_MW":shape*elec_net_MW,
                "elec_net_MW":shape*elec_net_MW,
                "elec_total_MW":shape*elec_net_MW,
                "nonelec_baseload_MW":shape*nonelec_total_MW,
                "nonelec_total_MW":shape*nonelec_total_MW,
                "elec_heating_MW":shape*0.0,
                "elec_cooling_MW":shape*0.0,
                "elec_dg_MW":shape*0.0,
                "nonelec_heating_MW":shape*0.0,
                "nonelec_cooling_MW":shape*0.0,
                },
                index=dt_index,
                ))

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

    counties = Counties(use_index="RO").loc["WECC"].set_index(["ST","COUNTY"]).sort_index()
    for state,county in counties.index.values:
        try:
            Agriculture(state,county,refresh=refresh)
            refresh = False # no need to download again
            _logger.debug(f"{state} {county} ok")
        except Exception as err:
            (_logger.exception if debug else _logger.error)(f"{county} {state}: {err}")
