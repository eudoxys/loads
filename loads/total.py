"""Total load aggregation module

The total load aggregate module computes the sum of the residential,
commercial, industrial and agricultural loads at the county level in each
state.

Example
-------

To compute the total load in 2020 for Alameda County CA use the following

    from loads import Total
    Total("CA","Alameda",2020)

which outputs

                               elec_baseload_MW  elec_cooling_MW  elec_dg_MW  elec_heating_MW  ...  humidity_pc  global_Wpms  direct_Wpms  diffuse_Wpms
    timestamp                                                                                  ...                                                     
    2020-01-01 00:00:00+00:00        875.936758        12.275047   -1.308691       119.031976  ...  7441.843208  1613.893708     0.000000   1613.893708
    2020-01-01 01:00:00+00:00        966.255125        11.165026    0.000000       125.994575  ...  7190.793076    89.660762   224.151904     89.660762
    2020-01-01 02:00:00+00:00        985.739523        10.193724    0.000000       140.598172  ...  7136.996619     0.000000     0.000000      0.000000
    2020-01-01 03:00:00+00:00        972.520338         9.490080    0.000000       148.451541  ...  6195.558622     0.000000     0.000000      0.000000
    2020-01-01 04:00:00+00:00        931.999704         9.656636    0.000000       142.825713  ...  5962.440642     0.000000     0.000000      0.000000
    ...                                     ...              ...         ...              ...  ...          ...          ...          ...           ...
    2020-12-31 19:00:00+00:00        947.877004        12.888278   -2.859527       178.552351  ...  7450.809284  3227.787415     0.000000   3227.787415
    2020-12-31 20:00:00+00:00        962.784910        12.836871   -4.207248       183.036471  ...  8338.450823  4617.529219     0.000000   4617.529219
    2020-12-31 21:00:00+00:00        934.669867        12.684631   -3.040338       177.558581  ...  8338.450823  3407.108939     0.000000   3407.108939
    2020-12-31 22:00:00+00:00        901.014894        12.377845   -3.209998       174.477905  ...  8338.450823  3586.430462     0.000000   3586.430462
    2020-12-31 23:00:00+00:00        851.636725        11.707962   -2.954313       184.026453  ...  8966.076154  3317.448177     0.000000   3317.448177

    [8784 rows x 15 columns]

"""

import logging

import pandas as pd

from fips import Counties
from weather import Weather
from loads.residential import Residential
from loads.commercial import Commercial
from loads.industry import Industry
from loads.agriculture import Agriculture
from loads.cast import Cast
from loads.calibrate import Calibrate

_logger = logging.getLogger(__file__)

class Total(pd.DataFrame):
    """Total load aggregation class implementation"""

    CACHEDIR = None
    """Cache folder"""

    cache = {
        "scale": {},
    }

    def __init__(self,
        state:str,
        county:str,
        year:int|None=None,
        refresh:bool=False,
        ):
        """Total load class constructor

        Arguments
        ---------

          - `state`: state for which to aggregate loads

          - `county`: county for which to aggregate loads

          - `year`: year for which to aggregate loads

          - `refresh`: refresh sector-level cache data
        """
        try:
            scale = self.cache["scale"][(state,year)]
        except KeyError:
            scale = Calibrate.state(state,year=year).to_dict()["scalar"]
            self.cache["scale"][(state,year)] = scale
        
        data = Cast(Residential(state,county,refresh=refresh).join(Weather(state,county)),year)
        total = Calibrate(data,scale=scale["R"])
        
        data = Cast(Commercial(state,county,refresh=refresh).join(Weather(state,county)),year)
        total += Calibrate(data,scale=scale["C"])
        
        data = Industry(state,county,refresh=refresh)
        for column in [x for x in total.columns if x.endswith("_MW") and x in data.columns]:
            total[column] += data.column
        
        data = Agriculture(state,county,refresh=refresh)
        for column in [x for x in total.columns if x.endswith("_MW") and x in data.columns]:
            total[column] += data.column
        
        super().__init__(total.fillna(0.0))

    @classmethod
    def makeargs(cls,**kwargs):
        """@private Return dict of accepted kwargs by this class constructor"""
        return {x:y for x,y in kwargs.items()
            if x in cls.__init__.__annotations__}

if __name__ == "__main__":
    """Main script

    The main script refreshes the cache with debugging enabled.
    """
    import sys
    refresh = "--refresh" in sys.argv
    debug = "--debug" in sys.argv
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    
    for state,county in Counties(use_index="SYSTEM",selection="WECC")[["ST","COUNTY"]].values:
        for year in range(2018,2023):
            try:
                Total(state,county,year,refresh=refresh)
                _logger.debug(f"{state} {county} {year} ok")
            except Exception as err:
                (_logger.exception if debug else _logger.error)(f"{state} {county} {year} {err}")

