"""Agricultural load data

Collects agricultural load data at state/county level. Data is based on [NREL US
County-Level Industrial Energy Use](https://data.nrel.gov/submissions/97), which
includes agricultural load data.

Agricultural non-electric total load and electric net load are converted to average
MW. All agricultural loads in each county are aggregated. 

# Example

Get the agricultural load data for all California counties using the command

    print(Agriculture("CA"))

which outputs the following

                     nonelec_total_MW  elec_net_MW
    county                                        
    Alameda                 10.100226     6.901008
    Alpine                   0.094917     0.062058
    Amador                  10.533700     7.517497
    Butte                   58.790507    45.148467
    ...
    Tuolumne                 6.761928     4.221102
    Ventura                 61.580047    54.378405
    Yolo                    40.123365    25.889051
    Yuba                    22.763883    15.086629

# Caveat

- Any agriculture for which a county FIPS code in the NREL data does not match a
  valid county FIPS code is matched to the previous county FIPS code, e.g.,
  `2270` is aggregated with `2265` and not `2275`.
"""

import os
import numpy as np
import pandas as pd
from fips.counties import Counties
from loads.cache import Cache

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
        ):
        """Construct an agricultural load data frame

        # Arguments

        - `state`: state (default all states)

        - `county`: county (default all counties)

        - `loadshape`: load shape to roll out county load
        """

        # set cache location
        if self.CACHEDIR :
            Cache.CACHEDIR = self.CACHEDIR

        # load data
        global CACHE
        if CACHE is None:
            cache = Cache(["agriculture.csv.gz"])
            if not os.path.exists(cache.pathname):
                data = pd.read_csv(self.SOURCE,
                    low_memory=False).sort_values("fips_matching")
                data.to_csv(cache.pathname,index=False,header=True,compression="gzip"
                    if cache.pathname.endswith(".gz") else None)
            else:
                data = pd.read_csv(cache.pathname,low_memory=False)

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
            super().__init__(data)

        # return requested state
        elif county is None:
            super().__init__(data.loc[state,:])

        # return requested county raw data
        elif loadshape is None:
            super().__init__(data.loc[state,county])

        # return rollout of county load
        elif isinstance(loadshape,pd.DataFrame):
            nonelec_total_MW,elec_net_MW = data.loc[state,county].values.tolist()
            assert len(loadshape.columns) == 1, "loadshape must have only one column"
            super().__init__(pd.DataFrame(
                data={
                "nonelec_total_MW":loadshape[0]*nonelec_total_MW,
                "elec_net_MW":loadshape[0]*elec_net_MW,
                },
                index=loadshape.index,
                ))
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
                "nonelec_total_MW":shape*nonelec_total_MW,
                "elec_net_MW":shape*elec_net_MW,
                },
                index=dt_index,
                ))

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":

    import matplotlib.pyplot as plt
    from fips.counties import Counties
    counties = Counties(use_index="RO").loc["WECC"].set_index(["ST","COUNTY"]).sort_index()
    loads = {}
    last = None
    for state,county in counties.index.values:
        if state != last:
            if not last is None:
                plt.figure(figsize=(20,10))
                plt.bar(loads.keys(),height=loads.values())
                plt.xticks(rotation=90)
                plt.grid()
                plt.ylabel("Electric load annual average (MW)")
                plt.xlabel("County")
                plt.title(f"{last} Agriculture")
                plt.savefig(f"/tmp/{last}_A.png")
                print()
                loads = {}
            print(state,end="")
            last = state
        print(".",end="",flush=True)
        loads[county] = Agriculture(state,county).T.elec_net_MW.values[0].round(1)

            