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

import pandas as pd

from fips import County
from cache import Cache

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
        ):
        """Commercial floor area data frame constructor

        Arguments
        ---------

          - `state`: specify the state abbreviation (required)

          - `county`: specify the county name (required)

          - `year`: specify the year on which the floor area is based
            (default most recent in `Units()`)
        """

        # set cache location
        if self.CACHEDIR :
            Cache.CACHEDIR = self.CACHEDIR

        # set default year
        if year is None:
            year = self.YEAR

        # load county commercial floor area data
        cache = Cache("floorarea.csv.gz",package=__package__,version=0)
        if not cache.exists():
            data = []
            for n,region in enumerate([
                "South Central",
                "Northeast",
                "South Atlantic",
                "Midwest",
                "West",
                ]):

                file = Cache(f"floorarea_region{n}.csv.gz",package=__package__,version=0)
                if file.exists():
                    try:
                        result = pd.read_csv(file.pathname)
                    except:
                        result = None
                else:
                    result = None
                if result is None:
                    result = pd.read_excel(self.SOURCE.format(
                            region=region.replace(" ","%20"),
                            year=year
                            ),
                        sheet_name="County",
                        usecols=["statecode","countyid","doe_prototype","area_sum"]
                        ).dropna()
                    result = result.groupby(["statecode","countyid","doe_prototype"])\
                        .sum()\
                        .reset_index()
                    result.columns = ["ST","FIPS","BUILDING_TYPE","FLOORAREA"]
                    result.to_csv(file.pathname,index=False,header=True,compression="gzip")
                result.FLOORAREA = result.FLOORAREA.astype(float)
                data.append(result)
            data = pd.concat(data)
            data.to_csv(cache.pathname,
                index=False,
                header=True,
                compression="gzip" if cache.pathname.endswith(".gz") else None,
                )
        else:
            data = pd.read_csv(cache.pathname)
        data.FIPS=[f"{x:05d}" for x in data.FIPS]
        data.BUILDING_TYPE = ["+".join(self.BUILDING_TYPES[x]) for x in data.BUILDING_TYPE]

        if not state and not county:
            super().__init__(data)
        elif state and not county:
            super().__init__(data.set_index("ST").loc[state])
        else:
            fips = County(ST=state,COUNTY=county).FIPS
            super().__init__(data.set_index(["ST","FIPS"]).sort_index().loc[state,fips])

if __name__ == '__main__':
    
    test = Floorarea()
    print(test)