"""Housing units

Examples
--------

The number of housing units in Alameda County CA in 2020 is obtained with the code

    from loads.units import Units
    print(Units("CA","Alameda",2020))

which gives the following output

    623350.0

Years after the most recent Census data (currently 2024) are extrapolated
from the most recent year at the annual rate `Units.GROWTH_RATE`, e.g.,

    Units.GROWTH_RATE = 0.015 # 1.5% annual growth
    print(Units("CA","Alameda",2030))

Years before the earliest Census data (currently 2020) use the 2020 data
unless `backcast=True`, in which case they are extrapolated backward at the
same rate, e.g.,

    print(Units("CA","Alameda",2018,backcast=True))

Caveats
-------

The default `GROWTH_RATE` of 1% is based on the national growth in total
housing units from July 2023 to July 2024 (145.36 to 146.77 million, about
1.0%). Growth varies considerably by state. In the WECC states, growth from
2023 to 2024 was

| State | Growth 2023-24 |
| ----- | -------------- |
| Idaho | 2.2% |
| Utah | 2.0% |
| Arizona | 1.7% |
| Colorado | 1.4% |
| Washington, Nevada | 1.3% |
| New Mexico | 1.0% |
| Oregon | 0.9% |
| California, Montana | 0.8% |
| Wyoming | 0.6% |

so a state- or county-specific rate may be more appropriate in some cases.
County-level rates can be estimated from the 2020-2024 county data used by
this class.

Growth also differs by housing type. In 2025 about 1.0 million single-family,
0.6 million multifamily, and 0.1 million manufactured homes were completed
nationally, and relative to the existing stock multifamily units have recently
grown somewhat faster than single-family homes. These are gross completions
(not net of demolitions), and multifamily completions in 2024-2025 were
elevated by the backlog of projects started during the pandemic. The Census
county data used by this class only provides total housing units, so a single
growth rate is applied to all housing types, which keeps the housing type mix
of each county fixed. Type-specific growth would require county-level housing
type data (e.g., ACS table B25024).

References
----------

  - https://www.census.gov/data/tables/time-series/demo/popest/2020s-total-housing-units.html
  - https://files.hawaii.gov/dbedt/census/archive/popestimate/NST-EST2024-HU-ANNCHG.pdf
  - https://calculatedrisk.substack.com/p/1600-million-total-housing-completions
"""

import os
import warnings
import socket
import logging
from typing import Callable

import pandas as pd

from fips import State
from cache import Cache

_logger = logging.getLogger(__file__)

# pylint: disable=redefined-outer-name
class Units(float):
    """Class to contain the number of residential units in a county for a year"""
    CACHEDIR = None
    """Cache folder path (`None` is package source folder)"""

    SOURCE = "https://www2.census.gov/programs-surveys/popest/tables/2020-2024/housing/totals"
    """Source of housing units data"""

    GROWTH_RATE = 0.01
    """Annual growth rate applied to years outside the available data (default is 1% annual)"""

    def __new__(cls,
        state:str,
        county:str=None,
        year:str|int=None,
        refresh:bool=False,
        aggregate:Callable=sum,
        backcast:bool=False,
        ):
        """Load housing units from Census Bureau

        Arguments
        ---------

          - `state`: state for which to read data

          - `county`: county for which to read data (default entire state)

          - `year`: year for which to read data (default most recent). Years
            after the most recent year for which county-level data is
            available are extrapolated from that year using `GROWTH_RATE`.
            Years prior to the earliest data use the earliest data unless
            `backcast` is `True`.

          - `refresh`: force refresh of cache data

          - `aggregate`: function to call when multiple values are found
            (must return a float)

          - `backcast`: extrapolate years prior to the earliest data
            backward from that year using `GROWTH_RATE` (default `False`)
        """

        if cls.CACHEDIR:
            Cache.CACHEDIR = cls.CACHEDIR
        cache = Cache(package="loads",version=0,path=[state,"units.csv.gz"])

        data = None
        if not refresh and cache.download():
            try:
                data = pd.read_csv(cache.pathname,index_col=[0])
                _logger.debug(f"{cache=} ok")
            except Exception as err: # pylint: disable=broad-exception-caught
                data = None
                cache.delete()
                _logger.debug(f"{cache=} {err}")
        else:
            data = None
            _logger.debug(f"{cache=} (re)generation required")

        if data is None:
            info = State(ST=state)
            name = f"CO-EST2024-HU-{info.FIPS}"
            url = f"{cls.SOURCE}/{name}.xlsx"
            old_timeout = socket.getdefaulttimeout()
            maxretry = 5
            retry = 0
            while data is None and retry < maxretry:
                try:
                    socket.setdefaulttimeout(5)
                    data = pd.read_excel(url,
                        sheet_name=name,
                        skiprows=2,
                        header=1,
                        index_col=[0],
                        usecols=[0,2,3,4,5,6],
                        ).dropna()
                    _logger.debug(f"{url=} download ok")
                except socket.timeout:
                    retry -= 1
                finally:
                    socket.setdefaulttimeout(old_timeout)
            if data is None:
                _logger.debug(f"{url=} download failed after {retry} retries")
                raise socket.timeout(f"maximum retries exceeded getting {url=}")
            data.to_csv(cache.pathname,
                index=True,
                header=True,
                compression="gzip" if cache.pathname.endswith(".gz") else None,
                )

        # apply annual growth rate to years outside the available data
        growth = 1.0
        if year is None:
            year = data.columns[-1]
        else:
            year = type(data.columns[-1])(year)
        if year < min(data.columns):
            if backcast:
                growth = (1+cls.GROWTH_RATE)**(int(year)-int(min(data.columns)))
                _logger.debug(f"Units({state=},{county=},{year=}) is prior to {min(data.columns)}, "\
                    f"applying {cls.GROWTH_RATE*100:.2f}% annual growth ({growth=:.4f})")
            else:
                _logger.warning(f"Units({state=},{county=},{year=}) is prior to {min(data.columns)}, using year={min(data.columns)} instead")
            year = min(data.columns)
        elif year > max(data.columns):
            growth = (1+cls.GROWTH_RATE)**(int(year)-int(max(data.columns)))
            _logger.debug(f"Units({state=},{county=},{year=}) is after {max(data.columns)}, "\
                f"applying {cls.GROWTH_RATE*100:.2f}% annual growth ({growth=:.4f})")
            year = max(data.columns)

        if county is None:
            row = data.index
        else:
            row = [x for x in data.index if x.startswith(f".{county}")]

        result = data.loc[row,year].values * growth
        if len(result) > 1:
            _logger.warning(f"Units({state=},{county=},{year=}) "\
                f"result has {len(result)} values ({', '.join(result.astype(str))})"\
                f"--returning {aggregate.__name__}")
            return aggregate(result)
        if len(result) == 0:
            _logger.debug(f"Units({state=},{county=},{year=}) "\
                f"has not result ({result=})--returning 0")
            return 0
        return result[0]

if __name__ == '__main__':
    """Main script

    The main script refreshes the cache with debugging enabled.
    """
    logging.basicConfig(level=logging.INFO)

    from fips.counties import Counties
    counties = Counties(use_index="RO").loc["WECC"].set_index(["ST","COUNTY"]).sort_index()
    
    data = None
    for state,county in counties.index.values:
        data = Units(state,county,refresh=data is None)
        print(state,county,data,flush=True)
