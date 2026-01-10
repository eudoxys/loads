"""Industrial load data

Collects industrial load data at state/county level. Data is based on [NREL US
County-Level Industrial Energy Use](https://data.nrel.gov/submissions/97).

Industrial non-electric total load and electric net load are converted from
total annual energy use to average MWh/h assuming a flat load. If you wish to
impose a load shape, use the `loadshape` argument of the
`loads.industry.Industry` constructor. 

All industries in each county are aggregated. 

Examples
--------

Get the industrial load data for all US counties using the command

    from loads.industry import Industry
    print(Industry())

which outputs the following

                          nonelec_total_MW  elec_net_MW  elec_baseload_MW  elec_total_MW  nonelec_baseload_MW
    state county                                                                                             
    AK    Aleutians East         41.933534    15.655625         15.655625      15.655625            41.933534
          Aleutians West         42.319171    16.922788         16.922788      16.922788            42.319171
          Anchorage             168.897481    39.530040         39.530040      39.530040           168.897481
          Bethel                 15.566359     7.720212          7.720212       7.720212            15.566359
          Bristol Bay             0.226564     0.044128          0.044128       0.044128             0.226564
    ...                                ...          ...               ...            ...                  ...
    WY    Sweetwater           2699.670664    85.240132         85.240132      85.240132          2699.670664
          Teton                  19.056917     2.809565          2.809565       2.809565            19.056917
          Uinta                 238.257039    11.872925         11.872925      11.872925           238.257039
          Washakie               65.464650     7.581157          7.581157       7.581157            65.464650
          Weston                113.971320    16.414641         16.414641      16.414641           113.971320

Get the industrial load data for all California counties using the command

    print(Industry("CA"))

which outputs the following

                     nonelec_total_MW  elec_net_MW  elec_baseload_MW  elec_total_MW  nonelec_baseload_MW
    county                                                                                              
    Alameda                485.513443   223.618361        223.618361     223.618361           485.513443
    Alpine                   0.106659     0.043838          0.043838       0.043838             0.106659
    .
    .
    .
    Ventura                641.076206   243.793152        243.793152     243.793152           641.076206
    Yolo                   264.316616    51.424299         51.424299      51.424299           264.316616
    Yuba                    23.722993     9.363254          9.363254       9.363254            23.722993

Get the industrial load data for Alameda County in California using the command

    print(Industry("CA","Alameda"))

which outputs the following

                                 CA
                            Alameda
    nonelec_total_MW     485.513443
    elec_net_MW          223.618361
    elec_baseload_MW     223.618361
    elec_total_MW        223.618361
    nonelec_baseload_MW  485.513443

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

                               elec_baseload_MW  elec_net_MW  elec_total_MW  nonelec_baseload_MW  nonelec_total_MW
    2018-01-01 00:00:00+00:00         22.361836    22.361836      22.361836            48.551344         48.551344
    2018-01-01 01:00:00+00:00         44.723672    44.723672      44.723672            97.102689         97.102689
    2018-01-01 02:00:00+00:00         67.085508    67.085508      67.085508           145.654033        145.654033
    2018-01-01 03:00:00+00:00         44.723672    44.723672      44.723672            97.102689         97.102689

Generate a load shape for Alameda County CA from a dict using the command

    print(Industry("CA","Alameda",
        loadshape={
            "shape": [0.1,0.2,0.3,0.2],
            "start": "2020-08-01 00:00:00+0000",
            "end": "2020-08-02 00:00:00+0000",
            "freq": "1h",
        }))

which output the following

                               elec_baseload_MW  elec_net_MW  elec_total_MW  nonelec_baseload_MW  nonelec_total_MW
    2020-08-01 00:00:00+00:00         22.361836    22.361836      22.361836            48.551344         48.551344
    2020-08-01 01:00:00+00:00         44.723672    44.723672      44.723672            97.102689         97.102689
    2020-08-01 02:00:00+00:00         67.085508    67.085508      67.085508           145.654033        145.654033
    .
    .
    .
    2020-08-01 22:00:00+00:00         67.085508    67.085508      67.085508           145.654033        145.654033
    2020-08-01 23:00:00+00:00         44.723672    44.723672      44.723672            97.102689         97.102689
    2020-08-02 00:00:00+00:00         22.361836    22.361836      22.361836            48.551344         48.551344

Caveats
-------

  - Any industry for which a county FIPS code in the NREL data does not match
    a valid county FIPS code is matched to the previous county FIPS code,
    e.g., `2270` is aggregated with `2265` and not `2275`.

  - Many industries have cooling and heating loads that are weather sensitive.
    However there is no data available to enable computing this sensitivity.
    Consequently the `(non)elec_heating_MW` and `(non)elec_cooling_MW` data
    is zero.

  - Some industries have distributed generation. However there is no data
    available to enable computing this power. Consequenty the `elec_dg_MW`
    data is zero and the `elec_total_MW` and `elec_net_MW` are equal.
"""

import os
import numpy as np
import pandas as pd
from fips import Counties
from cache import Cache

CACHE = None
"""Global cache of industrial load data"""

class Industry(pd.DataFrame):
    """Industrial loads data"""

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

        Arguments
        ---------

          - `state`: state (default all states)

          - `county`: county (default all counties)

          - `loadshape`: load shape to roll out county load

        Description
        -----------

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

        Caveats
        -------

          - The load shape must total 1.0 and fit evenly into the date/time
            index for the total annual energy use to match the original
            industry energy use data.
        """

        # set cache location
        if self.CACHEDIR :
            Cache.CACHEDIR = self.CACHEDIR

        # load data
        global CACHE
        if CACHE is None:
            cache = Cache(["industry.csv.gz"],package=__package__,version=0)
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

    import matplotlib.pyplot as plt
    from fips.counties import Counties
    counties = Counties(use_index="RO").loc["WECC"].set_index(["ST","COUNTY"]).sort_index()
    last = None
    loads = {}
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
                plt.savefig(f"/tmp/{last}_I.png")
                loads = {}
            last = state
        loads[county] = Industry(state,county).T.elec_net_MW.values[0].round(1)
        print(state,county,loads[county],"MW",flush=True)
