"""Total load aggregation module

The total load module sums the residential, commercial, industrial,
agricultural and transportation loads of a county for the 2018 reference
year. It does nothing else: it adds no weather, distributed generation or net
load columns, and it does not predict or sample other periods. Use
`loads.estimator.Estimator` to estimate loads for other years, and
`loads.dgen.DG` to get distributed generation (see `loads.dgen.DG.merge` to
add it to a load frame).

Data Flow
---------

```mermaid
flowchart TD

    NLR --> RESstock --> Residential
    NLR --> COMstock --> Commercial
    NLR --> Industrial
    NLR --> Agricultural
    Transportation[Transportation = 0]

    Residential --> Total[2018 sector loads]
    Commercial --> Total
    Industrial --> Total
    Agricultural --> Total
    Transportation --> Total
    Total -->|sum| elec_total_MW
```

Examples
--------

To get the 2018 sector loads of Alameda County CA use

    from loads import Total
    Total("CA","Alameda")

which returns 8760 hourly rows with the columns `elec_residential_MW`,
`elec_commercial_MW`, `elec_industrial_MW`, `elec_agricultural_MW`,
`elec_transportation_MW` and `elec_total_MW`, the sum of the sector columns.

To get the non-electric sector loads instead use

    Total("CA","Alameda",fuel="nonelec")

which returns the same columns with the prefix `nonelec_`.

Caveats
-------

  - Industrial and agricultural loads are flat unless
    `Total.INDUSTRY_LOADSHAPE` or `Total.AGRICULTURE_LOADSHAPE` is set.

  - Transportation loads are currently set to 0 because they are less than
    1% of total electric loads.

  - Large loads as defined by NERC (e.g., data centers) are not included.
"""

import logging

import pandas as pd
import numpy as np

from fips import Counties
from cache import Cache
from loads.residential import Residential
from loads.commercial import Commercial
from loads.industry import Industry
from loads.agriculture import Agriculture

_logger = logging.getLogger(__file__)

class Total(pd.DataFrame):
    """Total load aggregation class implementation

    Columns
    -------

    With `fuel="elec"` (the default) the data frame contains the following
    columns:

      - `elec_residential_MW`: total residential building loads

      - `elec_commercial_MW`: total commercial building loads

      - `elec_industrial_MW`: total industrial loads

      - `elec_agricultural_MW`: total agricultural loads

      - `elec_transportation_MW`: total transportation loads (always 0)

      - `elec_total_MW`: total loads (sum of the sector loads)

    With `fuel="nonelec"` the columns have the prefix `nonelec_` instead.
    """

    CACHEDIR = None
    """Cache folder"""

    FUELS = ["elec","nonelec"]
    """Valid values of the `fuel` argument"""

    SECTORS = ["residential","commercial","industrial","agricultural","transportation"]
    """Sectors summed into the total"""

    INDUSTRY_LOADSHAPE = None
    AGRICULTURE_LOADSHAPE = None
    """Default sector loadshapes (None is a flat load)"""

    TRAINING_YEAR = 2018
    """Year of the sector loads"""

    COLUMNS = {
        "elec_residential_MW": "Total residential building loads",
        "elec_commercial_MW": "Total commercial building loads",
        "elec_industrial_MW": "Total industrial loads",
        "elec_agricultural_MW": "Total agricultural loads",
        "elec_transportation_MW": "Total transportation loads",
        "elec_total_MW": "Total loads",
    }
    """Electric columns and their descriptions"""

    def __init__(self,
        state:str,
        county:str,
        *,
        fuel:str="elec",
        refresh:bool=False,
        ):
        """Total load class constructor

        Arguments
        ---------

          - `state`: state for which to aggregate loads

          - `county`: county for which to aggregate loads

          - `fuel`: `"elec"` (default) or `"nonelec"`

          - `refresh`: refresh cache data

        Returns
        -------

        The data frame is indexed by a UTC `timestamp` in 2018. See `Total`
        for the columns.
        """
        if fuel not in self.FUELS:
            raise ValueError(f"{fuel=} must be one of {self.FUELS}")

        # identify location of cached results
        if self.CACHEDIR:
            Cache.CACHEDIR = self.CACHEDIR
        cache = Cache(package="loads",version=3,path=[state,county,f"T_{fuel}_1h_sectors.csv.gz"])

        # load from cache
        data = None
        if not refresh and cache.download():
            try:
                data = pd.read_csv(cache.pathname,index_col=[0],parse_dates=[0])
                _logger.debug(f"{cache=} ok")
            except Exception as err: # pylint: disable=broad-exception-caught
                cache.delete()
                data = None
                _logger.debug(f"{cache=} {err}")
        else:
            _logger.debug(f"{cache=} (re)generation required")

        if data is None:
            data = self._sum_sectors(state,county,fuel,refresh)
            data.to_csv(cache.pathname,
                index=True,
                header=True,
                compression="gzip" if cache.pathname.endswith(".gz") else None,
                )

        # make index UTC
        if not data.index.tz:
            data.index = data.index.tz_localize("UTC")
        elif not data.index.tz == "UTC":
            data.index = data.index.tz_convert("UTC")

        super().__init__(data.rename_axis("timestamp"))

    @classmethod
    def _sum_sectors(cls,
        state:str,
        county:str,
        fuel:str,
        refresh:bool=False,
        ) -> pd.DataFrame:
        """Build the sector columns and their sum"""
        residential = Residential(state,county,refresh=refresh)
        data = pd.DataFrame(
            data={f"{fuel}_residential_MW":residential[f"{fuel}_total_MW"]},
            index=residential.index,
            )
        data[f"{fuel}_commercial_MW"] = Commercial(state,county,refresh=refresh)[f"{fuel}_total_MW"]

        # make flat loadshape for industry and agriculture
        loadshape = pd.DataFrame(data=np.ones(len(data)),index=data.index)

        # industrial and agricultural electric loads have no DG, so net is total
        column = f"{fuel}_{'net' if fuel == 'elec' else 'total'}_MW"
        data[f"{fuel}_industrial_MW"] = Industry(
            state,
            county,
            loadshape if cls.INDUSTRY_LOADSHAPE is None else cls.INDUSTRY_LOADSHAPE,
            )[column]
        data[f"{fuel}_agricultural_MW"] = Agriculture(
            state,
            county,
            loadshape if cls.AGRICULTURE_LOADSHAPE is None else cls.AGRICULTURE_LOADSHAPE,
            )[column]

        # set transportation to zero until data is available
        data[f"{fuel}_transportation_MW"] = 0.0

        data[f"{fuel}_total_MW"] = data[[f"{fuel}_{x}_MW" for x in cls.SECTORS]].sum(axis=1)
        return data

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":
    """Main script

    The main script refreshes the cache for every WECC county.
    """

    import sys

    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    for _state,_county in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY"]].values:
        try:
            Total(_state,_county,refresh=refresh)
            _logger.info(f"{_county} {_state} ok")
        except Exception as err: # pylint: disable=broad-exception-caught
            _logger.error(f"{_county} {_state} failed -- {err}")
