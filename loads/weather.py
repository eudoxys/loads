"""Weather data accessor

Access the weather corresponding to the load data.

# Example

To get the weather data for Alameda County CA use the command

    Weather("CA","Alameda")

which outputs the following

                                temperature_degF  ...    diffuse_Wpms
    2018-01-01 00:00:00+00:00              53.96  ...            32.0
    2018-01-01 01:00:00+00:00              51.98  ...             2.0
    2018-01-01 02:00:00+00:00              51.08  ...             0.0
    2018-01-01 03:00:00+00:00              51.08  ...             0.0
    2018-01-01 04:00:00+00:00              51.08  ...             0.0
    ...                                      ...  ...             ...
    2018-12-31 19:00:00+00:00              57.02  ...            58.0
    2018-12-31 20:00:00+00:00              57.92  ...            61.5
    2018-12-31 21:00:00+00:00              57.92  ...            63.5
    2018-12-31 22:00:00+00:00              57.92  ...            58.5
    2018-12-31 23:00:00+00:00              57.02  ...            52.0

    [8760 rows x 5 columns]
"""

import os
import datetime as dt
import pytz
import pandas as pd
from fips.counties import County
from fips.states import State
from loads.cache import Cache

class Weather(pd.DataFrame):
    """Weather data frame implementation"""

    # pylint: disable=invalid-name
    CACHEDIR = None
    """Cache folder path (`None` is '{packagedir}/.cache')"""

    def __init__(self,
        state:str,
        county:str,
        refresh:bool=False,
        ):
        """Construct weather data frame for a county

        # Arguments

        - `state`: specify the state abbreviation (required)

        - `county`: specify the county name (required)

        - `refresh`: force download of data from source repository
        """

        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR
        cache = Cache([state,county,"W.csv.gz"])

        # download data and save to cache
        if not cache.exists() or refresh:

            root = "https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/"\
                "end-use-load-profiles-for-us-building-stock/2021/comstock_amy2018_release_1/"\
                "weather/amy2018"
            fips = County(ST=state,COUNTY=county).FIPS
            tzoffset = float(State(ST=state).TZOFFSET)
            url = f"{root}/G{fips[:2]}0{fips[2:]}0_2018.csv"
            data = pd.read_csv(url,
                usecols=[
                    "date_time",
                    "Dry Bulb Temperature [°C]",
                    "Relative Humidity [%]",
                    "Global Horizontal Radiation [W/m2]", 
                    "Direct Normal Radiation [W/m2]",
                    "Diffuse Horizontal Radiation [W/m2]",
                    ],
                index_col=["date_time"]
                )
            data.index = pd.DatetimeIndex(data.index,tz=pytz.UTC) - dt.timedelta(hours=tzoffset+1)
            data.columns = [
                "temperature_degF",
                "humidity_pc",
                "global_Wpms",
                "direct_Wpms",
                "diffuse_Wpms",
                ]
            data["temperature_degF"] = (data["temperature_degF"]*9/5+32).round(2)
            data["humidity_pc"] = data["humidity_pc"].round(1)
            data.index = pd.DatetimeIndex([str(x).replace("2019","2018") for x in data.index])
            data.index.name = "timestamp"
            data.sort_index(inplace=True)
            data.to_csv(cache.pathname,
                index=True,
                header=True,
                compression="gzip" if cache.name.endswith(".gz") else None,
                )

        else:

            # load from cache
            data = pd.read_csv(cache.pathname,
                index_col=["timestamp"],
                parse_dates=["timestamp"],
                )

        # move year-end data to beginning
        super().__init__(data)

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == '__main__':
    
    from fips.counties import Counties

    pd.options.display.width = None
    pd.options.display.max_columns = None

    for state,county in Counties(use_index=["RO","ST","COUNTY"]).loc["WECC"].index.values:
        print("Processing",state,county,end="...",flush=True)
        try:
            print("ok")
            print(pd.DataFrame(Weather(state,county,refresh=False).std()).T)
        except Exception as err:
            raise
