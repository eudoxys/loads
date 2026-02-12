"""Commercial floor area data accessor

The commercial floor area data is used to scale the load data from COMstock to
match the actual floor area in a jurisdiction. The COMstock data is provided
with only a representative floor area, which may not match the actual floor area
of a county or state.

Floor area data is provided with a different set of building types than those
available in COMstock. The `BUILDING_TYPE` column is used to determine which
floor areas correspond to COMstock building types. In cases where more than
one COMstock building types matches, the split is weighted equally. Floor
areas that do not match any COMstock building type are not given any
(i.e., `BUILDING_TYPE` is blank).

Examples
--------

Get the commercial building floor areas for Alameda County CA using the code

    from loads.floorarea import Floorarea
    print(Floorarea("CA","Alameda"))

which generates the following output

             BUILDING_TYPE  FLOORAREA
    ST FIPS                          
    CA 06001           CLL  244969200
       06001           CLF    3200900
       06001           CLH    5894800
       06001           CSL   13351200
       06001                 90258900
       06001   CSO+CMO+CLO   84136400
       06001           CSH    9797500
       06001           CSF     706000
       06001           CMS   51336900
       06001       CME+CSE    5879200
       06001           CSR    6843000
       06001           CMR    1994200
       06001           CMW  158914200

References
----------

  - https://data.openei.org/submissions/906
"""

import os
import urllib
import logging

import numpy as np
import pandas as pd

from fips import County
from cache import Cache

_logger = logging.getLogger(__file__)

_cache = {}

class Floorarea(pd.DataFrame):
    """Commercial building floor area data frame implementation"""

    # pylint: disable=invalid-name
    CACHEDIR = None
    """Cache folder path (`None` is package source folder)"""

    SOURCE = "https://data.openei.org/files/906/{year}"\
        "%20Commercial%20Building%20Inventory%20-%20{region}.xlsb"

    YEAR = 2019
    """Default floor area data year"""

    BUILDING_TYPES = {
        "apartment": ["CLL"],
        "full_service_restaurant": ["CLF"],
        "hotel": ["CSL"],
        "no_match": [],
        "office": ["CSO","CMO","CLO"],
        "outpatient": ["CSH"],
        "quick_service_restaurant": ["CSF"],
        "retail": ["CMS"],
        "school": ["CME","CSE"],
        "strip_mall": ["CSR"],
        "supermarket": ["CMR"],
        "warehouse": ["CMW"],
        "hospital": ["CLH"],
    }
    """Mapping of floor area building types to COMstock building types"""

    def __init__(self,
        state:str=None,
        county:str=None,
        year:int=None,
        refresh:bool=False,
        ):
        """Commercial floor area data frame constructor

        Arguments
        ---------

          - `state`: specify the state abbreviation (required)

          - `county`: specify the county name (required)

          - `year`: specify the year on which the floor area is based
            (default most recent in `Units()`)

          - `refresh`: force refresh of cache
        """

        # set cache location
        if self.CACHEDIR :
            Cache.CACHEDIR = self.CACHEDIR

        # set default year
        if year is None:
            year = self.YEAR
        elif year != self.YEAR:
            _logger.debug(f"no floorarea data for {year}--using {self.YEAR} instead")
            year = self.YEAR

        global _cache
        if year not in _cache or refresh:

            # load county commercial floor area data from cache if possible
            cache = Cache(f"floorarea_{year}.csv.gz",package="loads",version=0)
            if cache.exists() and not refresh:
                try:
                    data = pd.read_csv(cache.pathname)
                    _logger.debug(f"{cache=} ok")
                except Exception as err:
                    data = None
                    cache.delete()
                    _logger.debug(f"{cache=} {err}")
            else:
                data = None
                _logger.debug(f"{cache=} (re)generation required")

            # download data if necessary
            if data is None:

                data = []
                for n,region in enumerate([
                    "South Central",
                    "Northeast",
                    "South Atlantic",
                    "Midwest",
                    "West",
                    ]):

                    file = Cache(package="loads",version=0,path=f"floorarea_region{n}_{year}.csv.gz")
                    if file.exists() and not refresh:
                        try:
                            result = pd.read_csv(file.pathname)
                            _logger.debug(f"{file=} ok")
                        except:
                            result = None
                            _logger.error(f"{file=} {err}")
                    else:
                        result = None
                        _logger.debug(f"{file=} (re)generation required")
                    if result is None:
                        url = self.SOURCE.format(region=region.replace(" ","%20"),year=year)
                        try:
                            result = pd.read_excel(url,
                                sheet_name="County",
                                usecols=["statecode","countyid","doe_prototype","area_sum"]
                                ).dropna()
                        except urllib.error.HTTPError as err:
                            _logger.error(f"{url=} {err=}")
                            raise
                        result = result.groupby(["statecode","countyid","doe_prototype"])\
                            .sum()\
                            .reset_index()
                        result.columns = ["ST","FIPS","BUILDING_TYPE","FLOORAREA"]
                        result.to_csv(file.pathname,index=False,header=True,compression="gzip")
                        _logger.debug(f"download of {url=} ok")
                    result.FLOORAREA = result.FLOORAREA.astype(float)
                    data.append(result)
                data = pd.concat(data)
                data.to_csv(cache.pathname,
                    index=False,
                    header=True,
                    compression="gzip" if cache.pathname.endswith(".gz") else None,
                    )
            # fix up records
            data.FIPS=[f"{x:05d}" for x in data.FIPS]
            data.BUILDING_TYPE = ["+".join(self.BUILDING_TYPES[x]) for x in data.BUILDING_TYPE]

            _cache[year] = data
        else:
            data = _cache[year]

        if not state and not county:
            super().__init__(data)
        elif state and not county:
            super().__init__(data.set_index("ST").loc[state])
        else:
            fips = County(ST=state,COUNTY=county).FIPS
            if fips in data.FIPS.values.tolist():
                super().__init__(data.set_index(["ST","FIPS"]).sort_index().loc[state,fips])
            else:
                btypes = data.BUILDING_TYPE.unique()
                super().__init__(pd.DataFrame({
                    "ST":[state]*len(btypes),
                    "FIPS":[fips]*len(btypes),
                    "BUILDING_TYPE":btypes,
                    "FLOORAREA": [0]*len(btypes),
                    },
                    index=range(len(btypes))
                    ))

if __name__ == '__main__':
    
    refresh = True

    pd.options.display.width = None
    pd.options.display.max_columns = None
    pd.options.display.max_rows = None

    logging.basicConfig(level=logging.DEBUG)
    from fips import Counties

    Floorarea(refresh=True)

    counties = Counties(use_index="RO").loc["WECC"].set_index(["ST","COUNTY"]).sort_index()
    last = None
    result = []
    print("Processing WECC counties",end="...",flush=True)
    for n,state,county in [(x,y[0],y[1]) for x,y in enumerate(counties.index.values)]:
        data = Floorarea(state,county)
        data["COUNTY"] = county
        result.append(data)
    print("ok")
    result = pd.concat(result).reset_index().set_index(["ST","COUNTY","BUILDING_TYPE"])
    result.drop("FIPS",axis=1,inplace=True)
    print(result.unstack().fillna(0).astype(int))

