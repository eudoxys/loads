"""County-level energy consumption

"""

import datetime as dt

import pandas as pd

from loads.total import Total
from fips import Counties

class Energy(pd.DataFrame):
    """County-level energy consumption implementation"""

    def __init__(self,
        state:str,
        counties:str|list[str]|None,
        year:int|tuple[int,int]|list[int,int],
        month:int=None,
        groupby="1MS",
        datetime_format=None,
        progress=None,
        ):
        """Construct energy use data frame for a county

        Arguments
        ---------

        - `state`:

        - `county`: Use `None` for the entire state

        - `year`:

        - `month`:

        - `groupby`:

        - `datetime_format`:
        """

        if counties is None:
            counties = Counties(use_index=["SYSTEM"],selection=["WECC"],set_index=["ST","COUNTY"]).loc[state].index.values
        elif isinstance(counties,str):
            counties = [counties]
        else:
            assert hasattr(counties,"__iter__"), f"counties is not iterable"

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
            energy = total.drop("temperature_degF",axis=1).resample(groupby).sum()
            energy.columns = [f"{county} {state}"]
            if datetime_format:
                energy.index = [x.strftime(datetime_format) for x in energy.index]
            result.append(energy)
        super().__init__(pd.concat(result,axis=1))


if __name__ == '__main__':
    
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    states = sorted(set(Counties(use_index=["SYSTEM"],selection=["WECC"],set_index=["ST"]).index))
    for state in states:

        energy = Energy(state,None,[2018,2022],
            datetime_format="%b %Y",
            progress=lambda *x: print(f"Processing {x[1]} {x[0]} ({x[2]} of {x[3]})...",flush=True)
            )
        print(energy / energy.sum(axis=1))

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
