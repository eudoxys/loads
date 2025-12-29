"""Industrial load data

Collects industrial load data at state/county level. Data is based on[NREL US
County-Level Industrial Energy Use](https://data.nrel.gov/submissions/97).

Industrial non-electric total load and electric net load are converted average
MW. All industries in each county are aggregated. 

# Examples

Get the industrial load data for all US counties using the command

    from loads.industry import Industry
    print(Industry())

which outputs the following

                          nonelec_total_MW  elec_net_MW
    state county                                       
    AK    Aleutians East         41.933534    15.655625
          Aleutians West         42.319171    16.922788
          Anchorage             168.897481    39.530040
          Bethel                 15.566359     7.720212
          Bristol Bay             0.226564     0.044128
    ...                                ...          ...
    WY    Sweetwater           2699.670664    85.240132
          Teton                  19.056917     2.809565
          Uinta                 238.257039    11.872925
          Washakie               65.464650     7.581157
          Weston                113.971320    16.414641

    [3136 rows x 2 columns]

Get the industrial load data for all California counties using the command

    print(Industry("CA"))

which outputs the following

                     nonelec_total_MW  elec_net_MW
    county                                        
    Alameda                485.513443   223.618361
    Alpine                   0.106659     0.043838
    Amador                  61.116353    19.487183
    Butte                  118.602559    50.740839
    ...
    Tuolumne                16.937469     5.142913
    Ventura                641.076206   243.793152
    Yolo                   264.316616    51.424299
    Yuba                    23.722993     9.363254

Get the industrial load data for Alameda County in California using the command

    print(Industry("CA","Alameda"))

which outputs the following

                              CA
                         Alameda
    nonelec_total_MW  485.513443
    elec_net_MW       223.618361


Generate a load shape for Alameda County CA from a Pandas data frame using the command

    print(Industry("CA","Alameda",
        loadshape=pd.DataFrame(
            data=[0.1, 0.2, 0.3, 0.2],
            index=pd.date_range(
                start="2018-01-01 00:00:00+0000",
                end="2018-01-01 03:00:00+0000",
                freq="1h"
                ))))

which outputs the following

                               nonelec_total_MW  elec_net_MW
    2018-01-01 00:00:00+00:00         48.551344    22.361836
    2018-01-01 01:00:00+00:00         97.102689    44.723672
    2018-01-01 02:00:00+00:00        145.654033    67.085508
    2018-01-01 03:00:00+00:00         97.102689    44.723672


Generate a load shape for Alameda County CA from a dict using the command

    print(Industry("CA","Alameda",
        loadshape={
            "shape": [0.1,0.2,0.3,0.2],
            "start": "2020-08-01 00:00:00+0000",
            "end": "2020-08-02 00:00:00+0000",
            "freq": "1h",
        }))

which output the following

                               nonelec_total_MW  elec_net_MW
    2020-08-01 00:00:00+00:00         48.551344    22.361836
    2020-08-01 01:00:00+00:00         97.102689    44.723672
    2020-08-01 02:00:00+00:00        145.654033    67.085508
    2020-08-01 03:00:00+00:00         97.102689    44.723672
    2020-08-01 04:00:00+00:00         48.551344    22.361836
    ...                                     ...          ...
    2020-08-31 20:00:00+00:00         48.551344    22.361836
    2020-08-31 21:00:00+00:00         97.102689    44.723672
    2020-08-31 22:00:00+00:00        145.654033    67.085508
    2020-08-31 23:00:00+00:00         97.102689    44.723672
    2020-09-01 00:00:00+00:00         48.551344    22.361836

    [745 rows x 2 columns]

# Caveat

- Any industry for which a county FIPS code in the NREL data does not match a
  valid county FIPS code is matched to the previous county FIPS code, e.g.,
  `2270` is aggregated with `2265` and not `2275`.
"""

import os
import numpy as np
import pandas as pd
from fips.counties import Counties

CACHE = None
"""Global cache of industrial load data"""

class Industry(pd.DataFrame):
    """Construct industrial loads data frame

Description:

By default the Industry loads data frame contains on the annual total
non-electric and net electric energy consumed by industry in US counties,
rescaled to a average hourly power in MW.

The load can be shaped using the `loadshape` parameter. Loadshapes can be
a Pandas data frame or a dict. If a data frame is used it must have only
1 column for the scaling of the load data and the index must be a Pandas
date/time index.  If a dict is used, the following must be included

- `shape`: the load scaling vector, which may be shorter than the
  date/time index implied by the start/end/freq values given, in
  which case the shape is repeated and/or truncated to fit the
  date/time index.

- `start`: the start date/time of the date/time index

- `end`: the end date/time of the date/time index (inclusive)

- `freq`: the interval of the date/time index, e.g., (`"1h"`)

Caveat: 

The load shape must total 1.0 and fit evenly into the date/time
index for the total annual energy use to match the original industry
energy use data.
    """

    # pylint: disable=invalid-name
    CACHEDIR = None
    """Cache folder path (`None` is package source folder)"""

    SOURCE = "https://data.nrel.gov/system/files/97/County_industry_energy_use.gz"
    """Source of industry energy use data"""

    COLUMNS = {
        "fips_matching":None,
        "Coal": "nonelec_total_MW",
        "Coke_and_breeze": "nonelec_total_MW",
        "Diesel": "nonelec_total_MW",
        "LPG_NGL": "nonelec_total_MW",
        "Natural_gas": "nonelec_total_MW",
        "Net_electricity": "elec_net_MW",
        "Other": "nonelec_total_MW",
        "Residual_fuel_oil": "nonelec_total_MW",
    }
    """Mapping of source data columns to `Industry` columns"""

    def __init__(self,
        state:str=None,
        county:str=None,
        loadshape:pd.DataFrame|dict|None=None,
        ):
        """Construct an industrial load data frame

        # Arguments

        - `state`: state (default all states)

        - `county`: county (default all counties)

        - `loadshape`: load shape to roll out county load
        """

        # set cache location
        if self.CACHEDIR is None:
            self.CACHEDIR = os.path.join(os.path.dirname(__file__),".cache")
        os.makedirs(self.CACHEDIR,exist_ok=True)

        # load data
        global CACHE
        if CACHE is None:
            file = os.path.join(self.CACHEDIR,"industry.csv.gz")
            if not os.path.exists(file):
                data = pd.read_csv(self.SOURCE,
                    low_memory=False).sort_values("fips_matching")
                data.to_csv(file,index=False,header=True,compression="gzip"
                    if file.endswith(".gz") else None)
            else:
                data = pd.read_csv(file,low_memory=False)

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
                plt.title(f"{last} Industry")
                plt.savefig(f".cache/industry_{last}.png")
                print()
                loads = {}
            print(state,end="")
            last = state
        print(".",end="",flush=True)
        loads[county] = Industry(state,county).T.elec_net_MW.values[0].round(1)

