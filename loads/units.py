"""Housing units

# Example

The number of housing units in Alameda County CA in 2020 is obtained with the code

    from loads.units import Units
    print(Units("CA","Alameda",2020))

which gives the following output

    623350.0

See https://www.census.gov/data/tables/time-series/demo/popest/2020s-total-housing-units.html

"""

import os
import warnings
import socket

import pandas as pd

from fips.states import State
from loads.cache import Cache

# pylint: disable=redefined-outer-name
class Units(float):
    """Class to contain the number of residential units in a county for a year"""
    CACHEDIR = None
    """Cache folder path (`None` is package source folder)"""

    SOURCE = "https://www2.census.gov/programs-surveys/popest/tables/2020-2024/housing/totals"
    """Source of housing units data"""

    def __new__(cls,
        state:str,
        county:str=None,
        year:str|int=None,
        ):
        """Load housing units from Census Bureau

        # Arguments

        - `state`: state for which to read data

        - `county`: county for which to read data (default entire state)

        - `year`: year for which to read data (default most recent)
        """

        if cls.CACHEDIR:
            Cache.CACHEDIR = cls.CACHEDIR
        cache = Cache([state,"units.csv.gz"])

        data = None
        if cache.exists():
            try:
                data = pd.read_csv(cache.pathname,index_col=[0])
            except:
                cache.delete()
        if data is None:
            info = State(ST=state)
            name = f"CO-EST2024-HU-{info.FIPS}"
            url = f"{cls.SOURCE}/{name}.xlsx"
            old_timeout = socket.getdefaulttimeout()
            retry = 5
            while retry > 0:
                try:
                    socket.setdefaulttimeout(5)
                    data = pd.read_excel(url,
                        sheet_name=name,
                        skiprows=2,
                        header=1,
                        index_col=[0],
                        usecols=[0,2,3,4,5,6],
                        ).dropna()
                    break
                except socket.timeout:
                    retry -= 1
                finally:
                    socket.setdefaulttimeout(old_timeout)
            if retry == 0:
                raise socket.timeout(f"maximum retries exceeded getting {url=}")
            data.to_csv(cache.pathname,
                index=True,
                header=True,
                compression="gzip" if cache.pathname.endswith(".gz") else None,
                )

        if year is None:
            year = data.columns[-1]
        else:
            year = type(data.columns[-1])(year)
        assert year in data.columns, f"{year=} is not valid, must be one of {data.columns}"

        if county is None:
            row = data.index
        else:
            row = [x for x in data.index if x.startswith(f".{county}")]

        result = data.loc[row,year].values
        if len(result) != 1:
            warnings.warn(f"Units({state=},{county=},{year=}) "\
                f"did not result in a single value ({result=})")
            return float('nan')
        return result[0]

if __name__ == '__main__':
    
    from fips.counties import Counties
    counties = Counties(use_index="RO").loc["WECC"].set_index(["ST","COUNTY"]).sort_index()
    
    for state,county in counties.index.values:
        print(state,county,Units(state,county),flush=True)
