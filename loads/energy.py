"""County-level energy consumption

The `Energy` class calculates the total energy consumed at the
county level on periodic basis.  Groupings can be daily, weekly,
monthly, quarterly, or annually. Values are stored in MWh.

Example
-------

To obtain the monthly energy consumptions for Alameda County for the years
2018 through 2022 use the following:

    from loads.energy import Energy
    Energy("CA","Alameda",year=[2018,2022])

which outputs the following:

                                  Alameda CA
    2018-01-01 00:00:00+00:00  900618.497937
    2018-02-01 00:00:00+00:00  811258.315333
    2018-03-01 00:00:00+00:00  869751.391940
    ...
    2020-10-01 00:00:00+00:00  837109.013352
    2020-11-01 00:00:00+00:00  842237.369591
    2020-12-01 00:00:00+00:00  905353.692676
"""

import datetime as dt
from typing import Callable

import pandas as pd

from cache import Cache
from loads.total import Total
from fips import Counties

class Energy(pd.DataFrame):
    """County-level energy consumption implementation"""

    def __init__(self,
        state:str,
        counties:str|list[str]|None,
        year:int|tuple[int,int]|list[int,int],
        month:int=None,
        groupby:str="1MS",
        datetime_format:str|None=None,
        progress:Callable|None=None,
        refresh:bool=False,
        ):
        """Construct periodic energy use data frame for a county or state

        Arguments
        ---------

        - `state`: state for which energy is computed

        - `county`: Use `None` for the entire state

        - `year`: year or year start/stop to compute energy

        - `month`: month (`None` for all months)

        - `groupby`: grouping period (see `pandas.resample` for valid
          grouping periods)

        - `datetime_format`: timestamp formatting to use (`None` to use
          `pandas.DatetimeIndex`)

        - `progress`: callback function for progress reports (arguments are
          `state`, `county`, `done_count`, `total_count`)

        - `refresh`: cache refresh enable flag
        """

        if counties is None:
            counties = Counties(use_index=["ST"],selection=[state],set_index=["COUNTY"]).index.values
        elif isinstance(counties,str):
            counties = [counties]
        else:
            assert hasattr(counties,"__iter__"), f"counties is not iterable"

        cache = Cache(package="loads",version=0,path=[state,f"T_{min(year)}-{max(year)}_{month}_{groupby}.csv.gz"])
        energy = None
        if cache.exists() and not refresh:
            try:
                energy = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
            except Exception as err:
                cache.delete()
        if energy is None:
            result = []
            for n,county in enumerate(counties):
                if progress:
                    progress(state,county,n+1,len(counties))
                if isinstance(year,(list,tuple)):
                    assert month is None, f"month cannot be specified when multiple years are specified"
                    start = dt.datetime(year[0],1,1,0,0,0,0,dt.timezone.utc)
                    stop = dt.datetime(year[1]+1,1,1,0,0,0,0,dt.timezone.utc) - dt.timedelta(seconds=1)
                else:
                    start = dt.datetime(year,1 if month is None else month,1,0,0,0,0,dt.timezone.utc)
                    stop = dt.datetime(
                        year+1 if month==12 or month is None else year,
                        1 if month==12 or month is None else month+1,
                        1,0,0,0,0,dt.timezone.utc) - dt.timedelta(seconds=1)

                total = Total(state,county,date_range=pd.date_range(start,stop,freq="1h"),samples=0)
                energy = total.drop(Total.EXOGENOUS_VARIABLES["elec_total_MW"],axis=1).resample(groupby).sum()
                energy.columns = [f"{county} {state}"]
                result.append(energy)
            energy = pd.concat(result,axis=1)
            energy.to_csv(cache.pathname,index=True,header=True,compression="gzip" if cache.pathname.endswith(".gz") else None)
        if datetime_format:
            energy.index = [x.strftime(datetime_format) for x in energy.index]
        super().__init__(energy)


if __name__ == '__main__':
    
    # Calculate the energy contribution factors for each state from 2018 to 2022
    # Stores results in cache for <state>/CF_2018-2022.csv
    Total.cache = None

    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    pd.options.display.max_columns = None
    pd.options.display.max_rows = None
    pd.options.display.width = None

    years = [2018,2022] # start and end years
    refresh = False

    states = set(Counties(use_index=["SYSTEM"],selection=["WECC"],set_index=["ST"]).index)
    for n,state in enumerate(sorted(states)):

        cache = Cache(package="loads",version=0,path=[state,f"CF_{'-'.join(map(str,years))}.csv"])
        if cache.exists() and not refresh:
            energy = pd.read_csv(cache.pathname,index_col=[0])
        else:
            print(f"Processing {state} ({n+1} of {len(states)} states in WECC)...",flush=True)
            energy = Energy(state,None,years,
                datetime_format="%b %Y",
                progress=lambda *x: print(f"  {x[1]} {x[0]} ({x[2]} of {x[3]} counties in {state})...",flush=True)
                )
            energy.index.name = "month_year"
            total = energy.sum(axis=1)
            for column in energy.columns:
                energy[column] /= total
            energy.round(6).to_csv(cache.pathname,index=True,header=True)
        
        print(energy,flush=True)

        # animate monthly fractions
        # fig = plt.figure(figsize=(10,10))
        # for month in energy.index:
        #     plt.clf()
        #     energy.T.plot(ax=plt.gca(),kind="pie",y=month,legend=False,title=f"{state} {month} Energy Contribution Factors")
        #     plt.pause(0.1)
        # plt.close()

        # plot monthly fractions as bar plot
        # energy.plot(
        #     figsize=(20,10),
        #     kind='bar',
        #     title=f"{county[1]} {county[0]}",
        #     xlabel="Month/Year (UTC)",
        #     ylabel="Energy (MWh)",
        #     grid=True,
        #     legend=False,
        #     )
        # plt.show()

        # plot monthly fractions as area plot
        # (energy*100).plot(figsize=(20,10),
        #         kind="area",
        #         grid=True,
        #         title=f"{state} Energy Contribution Factor",
        #         xlabel="Month",
        #         ylabel="% of state total",
        #         )
        # plt.show()
